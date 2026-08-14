# -*- coding: utf-8 -*-
"""FASE 1B: device_id persistente básico y migraciones SQLite vs PostgreSQL."""
from __future__ import annotations

import ast
import sqlite3
import sys
import unittest
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase0.harness import official_temp_db


class DeviceIdentityTest(unittest.TestCase):
    def test_device_id_uuid_estable_no_hostname(self):
        import socket

        from local_first_config import (
            _device_identity_path,
            get_or_create_device_id,
        )

        with official_temp_db() as env:
            first = get_or_create_device_id()
            second = get_or_create_device_id()
            self.assertEqual(first, second)
            uuid.UUID(first)
            self.assertNotEqual(first, socket.gethostname())
            self.assertNotEqual(first.lower(), socket.gethostname().lower())
            path = _device_identity_path()
            self.assertTrue(path.exists())
            self.assertEqual(path.name, "device_identity.json")
            self.assertTrue(str(env.db_path.parent) in str(path.resolve()))
            src = (REPO_ROOT / "local_first_config.py").read_text(encoding="utf-8")
            self.assertNotIn("gethostname", src)
            self.assertNotIn("uuid.getnode", src)
            self.assertNotIn("getuser", src)
            self.assertNotIn("OFFLINE_INVENTORY_AUTHORITY", src)


class MigracionesIdentidadTest(unittest.TestCase):
    def test_sqlite_no_ejecuta_sql_pg_de_identidad(self):
        from schema_bootstrap import (
            REMOTE_IDENTITY_MIGRATION_FILENAME,
            SchemaBootstrapError,
            apply_engine_schema_fixes,
            apply_postgres_identity_sql,
        )
        from sync_registry import postgres_identity_sql

        sql = (REPO_ROOT / REMOTE_IDENTITY_MIGRATION_FILENAME).read_text(
            encoding="utf-8"
        )
        self.assertIn("gen_random_uuid", sql)
        self.assertIn("Nunca ejecutar contra SQLite", sql)
        self.assertEqual(sql, postgres_identity_sql())

        with official_temp_db() as env:
            conn = env.connect()
            try:
                with self.assertRaises(SchemaBootstrapError) as ctx:
                    apply_postgres_identity_sql(conn, sql)
                self.assertIn("SQLite", str(ctx.exception))
                apply_engine_schema_fixes(conn)
            finally:
                conn.close()

        bootstrap_src = (REPO_ROOT / "schema_bootstrap.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(bootstrap_src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == (
                "apply_engine_schema_fixes"
            ):
                called = [
                    n.func.id
                    for n in ast.walk(node)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                ]
                self.assertNotIn("apply_postgres_identity_sql", called)

    def test_sqlite_y_postgres_comparten_contrato_local_id(self):
        from sync_registry import sync_tables

        with official_temp_db() as env:
            conn = env.connect()
            try:
                for table in sync_tables():
                    cols = {
                        row[1]: row[2]
                        for row in conn.execute(f"PRAGMA table_info({table})")
                    }
                    self.assertIn("local_id", cols, msg=table)
                    self.assertEqual(str(cols["local_id"]).upper(), "TEXT")
                    idx = conn.execute(
                        "SELECT sql FROM sqlite_master WHERE type='index' "
                        "AND tbl_name=? AND sql LIKE ?",
                        (table, f"%{table}%local_id%"),
                    ).fetchone()
                    self.assertIsNotNone(idx, msg=f"UNIQUE local_id ausente en {table}")
            finally:
                conn.close()

        pg_sql = (REPO_ROOT / "supabase_local_first_migration.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn("ADD COLUMN IF NOT EXISTS local_id text", pg_sql)
        self.assertIn("ON %I(local_id)", pg_sql)
        identity_sql = (REPO_ROOT / "supabase_sync_identity.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn("gen_random_uuid()::text", identity_sql)
        self.assertIn("uq_' || t || '_local_id'", identity_sql)

    def test_ensure_local_id_unique_idempotente_en_tempfile(self):
        with official_temp_db() as env:
            conn = sqlite3.connect(str(env.db_path))
            conn.row_factory = sqlite3.Row
            try:
                conn.execute(
                    "INSERT INTO productos (nombre, precio_venta, stock) "
                    "VALUES (?, ?, ?)",
                    ("SinUUID", 1, 0),
                )
                conn.commit()
                from local_first_db import ensure_local_id_unique

                ensure_local_id_unique(conn)
                first = conn.execute(
                    "SELECT local_id FROM productos WHERE nombre=?",
                    ("SinUUID",),
                ).fetchone()[0]
                uuid.UUID(first)
                ensure_local_id_unique(conn)
                second = conn.execute(
                    "SELECT local_id FROM productos WHERE nombre=?",
                    ("SinUUID",),
                ).fetchone()[0]
                self.assertEqual(first, second)
            finally:
                conn.close()
