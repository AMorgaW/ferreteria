# -*- coding: utf-8 -*-
"""FASE 1B.1: sync genérico no asume PK entera `id`."""
from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase0.harness import official_temp_db


class _FakeCursor:
    def __init__(self, owner):
        self.owner = owner

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.owner.sqls.append(sql)
        self.owner.last_sql = sql
        self.owner.last_params = params

    def fetchall(self):
        return [(lid,) for lid in self.owner.remote_lids]

    def fetchone(self):
        return (self.owner.returning_value,)


class _FakeRemote:
    def __init__(self, remote_lids=(), returning_value=None):
        self.remote_lids = set(remote_lids)
        self.returning_value = returning_value
        self.sqls = []
        self.last_sql = ""
        self.last_params = None
        self.commits = 0

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.commits += 1

    def close(self):
        pass


class PkGenericaTest(unittest.TestCase):
    def test_unicas_pk_no_id_en_registry_sync(self):
        from sync_registry import pk_column, sync_tables, tables_with_non_surrogate_pk

        self.assertEqual(tables_with_non_surrogate_pk(), ("configuracion",))
        self.assertEqual(pk_column("configuracion"), "clave")
        for table in sync_tables():
            if table == "configuracion":
                continue
            self.assertEqual(pk_column(table), "id", msg=table)

    def test_upsert_sql_usa_pk_declarada_no_asume_id(self):
        from local_sync import build_remote_upsert_sql
        from sync_registry import pk_column, sync_tables

        for table in sync_tables():
            pk = pk_column(table)
            sql = build_remote_upsert_sql(table, ["local_id", "updated_at", pk])
            self.assertIn(f"RETURNING {pk}", sql, msg=table)
            self.assertIn("ON CONFLICT (local_id)", sql, msg=table)
            if pk != "id":
                self.assertNotIn("RETURNING id", sql, msg=table)

        cfg = build_remote_upsert_sql(
            "configuracion", ["clave", "valor", "local_id"]
        )
        self.assertIn("RETURNING clave", cfg)
        self.assertNotIn("RETURNING id", cfg)
        prod = build_remote_upsert_sql(
            "productos", ["nombre", "stock", "local_id"]
        )
        self.assertIn("RETURNING id", prod)

    def test_source_upsert_no_hardcodea_returning_id(self):
        src = (REPO_ROOT / "local_sync.py").read_text(encoding="utf-8")
        self.assertIn("build_remote_upsert_sql", src)
        self.assertIn("remote_upsert_returning_column", src)
        self.assertNotIn("RETURNING id", src)

    def test_enqueue_y_backfill_configuracion_sin_columna_id(self):
        from local_first_db import enqueue_entity, ensure_local_id_unique
        from local_sync import SupabaseSyncService

        with official_temp_db() as env:
            conn = env.connect()
            try:
                conn.execute(
                    "INSERT INTO configuracion (clave, valor) VALUES (?, ?)",
                    ("tema", "oscuro"),
                )
                conn.commit()
                cols = {
                    row[1] for row in conn.execute("PRAGMA table_info(configuracion)")
                }
                self.assertNotIn("id", cols)
                ensure_local_id_unique(conn)
                payload = enqueue_entity(
                    conn, "config", "tema", "create", "configuracion"
                )
                conn.commit()
                self.assertIsNotNone(payload)
                self.assertNotIn("id", payload)
                self.assertEqual(payload["clave"], "tema")
                uuid.UUID(payload["local_id"])
            finally:
                conn.close()

            fake = _FakeRemote()
            svc = SupabaseSyncService(
                db_path=str(env.db_path), database_url="postgres://test"
            )
            with patch.object(svc, "_remote_connect", return_value=fake):
                result = svc.backfill_to_remote()
            self.assertIn("configuracion", result["encolados"])
            self.assertGreater(result["encolados"]["configuracion"], 0)
            cfg_sqls = [sql for sql in fake.sqls if "configuracion" in sql.lower()]
            self.assertTrue(cfg_sqls)
            self.assertFalse(any("RETURNING id" in sql for sql in cfg_sqls))
            self.assertFalse(
                any("SELECT id" in sql.lower().replace("local_id", "")
                    for sql in cfg_sqls)
            )
            self.assertTrue(any("local_id" in sql for sql in cfg_sqls))

    def test_upsert_configuracion_insert_update_retry_idempotente(self):
        from local_first_db import enqueue_entity, ensure_local_id
        from local_sync import SupabaseSyncService, build_remote_upsert_sql

        with official_temp_db() as env:
            conn = env.connect()
            try:
                conn.execute(
                    "INSERT INTO configuracion (clave, valor) VALUES (?, ?)",
                    ("tema", "claro"),
                )
                lid = ensure_local_id(conn, "configuracion", "tema")
                conn.commit()

                sql = build_remote_upsert_sql(
                    "configuracion", ["clave", "valor", "local_id"]
                )
                sqlite_sql = sql.replace("%s", "?")
                conn.execute(sqlite_sql, ("tema", "oscuro", lid))
                conn.execute(sqlite_sql, ("tema", "oscuro", lid))
                conn.execute(sqlite_sql, ("tema", "nieve", lid))
                rows = conn.execute(
                    "SELECT clave, valor, local_id FROM configuracion WHERE clave=?",
                    ("tema",),
                ).fetchall()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["valor"], "nieve")
                self.assertEqual(rows[0]["local_id"], lid)

                nuevo = str(uuid.uuid4())
                conn.execute(sqlite_sql, ("iva_tasa", "0.19", nuevo))
                total = conn.execute(
                    "SELECT COUNT(*) FROM configuracion"
                ).fetchone()[0]
                self.assertEqual(total, 2)

                fake = _FakeRemote(returning_value="tema")
                svc = SupabaseSyncService(db_path=str(env.db_path))
                payload = enqueue_entity(
                    conn, "config", "tema", "update", "configuracion"
                )
                first = svc._upsert(fake, conn, "configuracion", payload, {})
                second = svc._upsert(fake, conn, "configuracion", payload, {})
                self.assertEqual(first, "tema")
                self.assertEqual(second, "tema")
                self.assertIn("RETURNING clave", fake.last_sql)
                self.assertNotIn("RETURNING id", fake.last_sql)
            finally:
                conn.close()

    def test_upsert_tabla_con_id_sigue_funcionando(self):
        from local_first_db import enqueue_entity
        from local_sync import SupabaseSyncService, build_remote_upsert_sql

        with official_temp_db() as env:
            conn = env.connect()
            try:
                env.insert_proveedor(conn)
                env.insert_producto(conn, stock=7, local_id=str(uuid.uuid4()))
                conn.commit()
                payload = enqueue_entity(
                    conn, "product", 1, "update", "productos"
                )
                self.assertIn("id", payload)
                self.assertIn("stock", payload)
                payload = dict(payload)
                payload["proveedor_id"] = None
                sql = build_remote_upsert_sql(
                    "productos", ["nombre", "stock", "local_id"]
                )
                self.assertIn("RETURNING id", sql)
                fake = _FakeRemote(returning_value=99)
                svc = SupabaseSyncService(db_path=str(env.db_path))
                remote_id = svc._upsert(fake, conn, "productos", payload, {})
                self.assertEqual(remote_id, 99)
                self.assertIn("RETURNING id", fake.last_sql)
            finally:
                conn.close()
