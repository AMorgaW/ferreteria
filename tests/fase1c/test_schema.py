# -*- coding: utf-8 -*-
"""FASE 1C: schema SQLite/PostgreSQL, bootstrap y exclusión del sync LWW."""
from __future__ import annotations

import ast
import sqlite3
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase0.harness import (
    REPO_FERRETERIA_DB,
    _patch_local_paths,
    _restore_local_paths,
    official_temp_db,
)
from tests.fase1c.test_ledger import DEVICE, _op, _seed


class SchemaSyncYAlcanceTest(unittest.TestCase):
    def test_bootstrap_dos_veces_idempotente(self):
        import database
        import local_first_db

        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = _seed(conn, env, stock=9)
            finally:
                conn.close()
            database.DatabaseManager._schema_initialized = False
            env.db.crear_estructura_completa()
            local_first_db.ensure_local_first_schema(str(env.db_path))
            local_first_db.ensure_local_first_schema(str(env.db_path))
            database.DatabaseManager._schema_initialized = True
            conn = env.connect()
            try:
                stock = conn.execute(
                    "SELECT stock FROM productos WHERE local_id=?", (lid,)
                ).fetchone()[0]
                self.assertEqual(stock, 9)
                tables = {
                    r[0]
                    for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                self.assertIn("inventory_commands", tables)
                self.assertIn("inventory_operations", tables)
            finally:
                conn.close()

    def test_bd_antigua_recibe_tablas_sin_perder_datos(self):
        import local_first_db

        tmp = tempfile.TemporaryDirectory(prefix="ferrepro-fase1c-old-")
        db_path = Path(tmp.name) / "antigua.db"
        self.assertNotEqual(db_path.resolve(), REPO_FERRETERIA_DB.resolve())
        lid = str(uuid.uuid4())
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "CREATE TABLE productos ("
                "id INTEGER PRIMARY KEY, nombre TEXT, stock INTEGER, local_id TEXT)"
            )
            conn.execute(
                "INSERT INTO productos (id, nombre, stock, local_id) "
                "VALUES (1, 'Legacy', 42, ?)",
                (lid,),
            )
            conn.commit()
        finally:
            conn.close()
        snapshot = _patch_local_paths(db_path)
        try:
            local_first_db.ensure_local_first_schema(str(db_path))
            local_first_db.ensure_local_first_schema(str(db_path))
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "SELECT nombre, stock, local_id FROM productos WHERE id=1"
                ).fetchone()
                self.assertEqual(row["nombre"], "Legacy")
                self.assertEqual(row["stock"], 42)
                self.assertEqual(row["local_id"], lid)
                tables = {
                    r[0]
                    for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                self.assertIn("inventory_commands", tables)
                self.assertIn("inventory_operations", tables)
            finally:
                conn.close()
        finally:
            _restore_local_paths(snapshot)
            tmp.cleanup()

    def test_postgres_ddl_paridad_semantica(self):
        from inventory_ledger import (
            REMOTE_LEDGER_MIGRATION_FILENAME,
            postgres_ledger_sql,
        )

        sql = postgres_ledger_sql()
        artifact = (REPO_ROOT / REMOTE_LEDGER_MIGRATION_FILENAME).read_text(
            encoding="utf-8"
        )
        self.assertEqual(artifact, sql)
        self.assertIn("Nunca ejecutar contra SQLite", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS inventory_commands", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS inventory_operations", sql)
        self.assertIn("command_id TEXT PRIMARY KEY", sql)
        self.assertIn("operation_id TEXT PRIMARY KEY", sql)
        self.assertIn("producto_local_id TEXT NOT NULL", sql)
        self.assertIn("delta_scaled BIGINT NOT NULL", sql)
        self.assertIn("request_hash TEXT NOT NULL", sql)
        self.assertIn("UNIQUE (command_id, line_no)", sql)
        self.assertIn("REFERENCES inventory_commands(command_id)", sql)
        self.assertNotIn("CREATE FUNCTION", sql)
        lowered = sql.lower()
        self.assertNotIn("uuid primary key", lowered)

    def test_sqlite_no_ejecuta_sql_postgres_del_ledger(self):
        from inventory_ledger import postgres_ledger_sql
        from schema_bootstrap import (
            SchemaBootstrapError,
            apply_engine_schema_fixes,
            apply_postgres_ledger_sql,
        )

        with official_temp_db() as env:
            conn = env.connect()
            try:
                with self.assertRaises(SchemaBootstrapError) as ctx:
                    apply_postgres_ledger_sql(conn, postgres_ledger_sql())
                self.assertIn("SQLite", str(ctx.exception))
                apply_engine_schema_fixes(conn)
            finally:
                conn.close()
        src = (REPO_ROOT / "schema_bootstrap.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == (
                "apply_engine_schema_fixes"
            ):
                called = [
                    n.func.id
                    for n in ast.walk(node)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                ]
                self.assertNotIn("apply_postgres_ledger_sql", called)
                self.assertNotIn("apply_postgres_identity_sql", called)

    def test_ledger_no_entra_a_sync_lww(self):
        from inventory_ledger import create_inventory_command
        from schema_bootstrap import INTEGER_PK_TABLES as BOOT_PK
        from sync_registry import (
            APPLY_AUTHORITATIVE_EXCLUDE,
            NON_SYNC_INSERT_PK,
            NON_SYNC_TABLES,
            is_sync_table,
            sync_tables,
        )

        self.assertFalse(APPLY_AUTHORITATIVE_EXCLUDE)
        self.assertFalse(is_sync_table("inventory_commands"))
        self.assertFalse(is_sync_table("inventory_operations"))
        self.assertNotIn("inventory_commands", sync_tables())
        self.assertNotIn("inventory_operations", sync_tables())
        self.assertIn("inventory_commands", NON_SYNC_TABLES)
        self.assertIn("inventory_operations", NON_SYNC_TABLES)
        self.assertEqual(NON_SYNC_INSERT_PK["inventory_commands"], "command_id")
        self.assertEqual(NON_SYNC_INSERT_PK["inventory_operations"], "operation_id")
        self.assertEqual(set(NON_SYNC_INSERT_PK), set(NON_SYNC_TABLES))
        self.assertNotIn("inventory_commands", BOOT_PK)
        self.assertNotIn("inventory_operations", BOOT_PK)
        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = _seed(conn, env)
                create_inventory_command(
                    conn,
                    command_id=str(uuid.uuid4()),
                    tipo="VENTA",
                    device_id=DEVICE,
                    operations=[_op(lid, "-1")],
                )
                queued = conn.execute(
                    "SELECT COUNT(*) FROM sync_queue WHERE table_name IN "
                    "('inventory_commands', 'inventory_operations')"
                ).fetchone()[0]
                self.assertEqual(queued, 0)
            finally:
                conn.close()

    def test_1c_no_adelanta_coordinador(self):
        from sync_registry import APPLY_AUTHORITATIVE_EXCLUDE

        self.assertFalse(APPLY_AUTHORITATIVE_EXCLUDE)
        forbidden = (
            "def apply_inventory_operation",
            "OFFLINE_INVENTORY_AUTHORITY",
            "recepcion_documentos",
            "producto_codigos",
        )
        hits = []
        for path in REPO_ROOT.rglob("*.py"):
            rel = path.relative_to(REPO_ROOT)
            if any(
                part in {".git", "tests", "docs", ".cursor", "__pycache__"}
                for part in rel.parts
            ):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for token in forbidden:
                if token in text:
                    hits.append(f"{rel.as_posix()}: {token}")
        self.assertEqual(hits, [])
        src = (REPO_ROOT / "sync_registry.py").read_text(encoding="utf-8")
        self.assertIn("APPLY_AUTHORITATIVE_EXCLUDE = False", src)
        ls = (REPO_ROOT / "local_sync.py").read_text(encoding="utf-8")
        self.assertIn("apply_postgres_ledger_sql", ls)
        self.assertIn("postgres_ledger_sql()", ls)
