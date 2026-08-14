# -*- coding: utf-8 -*-
"""FASE 1B.1: historial_precios existe antes de columnas sync y conserva identidad."""
from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase0.harness import official_temp_db


class HistorialPreciosBootstrapTest(unittest.TestCase):
    def test_bd_nueva_historial_precios_con_local_id_unique(self):
        from sync_registry import (
            is_sync_table,
            tables_requiring_postgres_local_id_unique,
        )

        self.assertTrue(is_sync_table("historial_precios"))
        self.assertIn(
            "historial_precios", tables_requiring_postgres_local_id_unique()
        )
        with official_temp_db() as env:
            conn = env.connect()
            try:
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='historial_precios'"
                ).fetchone()
                self.assertIsNotNone(exists)
                cols = {
                    row[1]
                    for row in conn.execute("PRAGMA table_info(historial_precios)")
                }
                self.assertIn("local_id", cols)
                idx = conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='index' "
                    "AND tbl_name='historial_precios' AND sql LIKE ?",
                    ("%historial_precios%local_id%",),
                ).fetchone()
                self.assertIsNotNone(idx)
                self.assertIn("UNIQUE", (idx[0] or "").upper())

                lid = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO historial_precios "
                    "(producto_id, tipo, precio_anterior, precio_nuevo, local_id) "
                    "VALUES (1, 'venta', 1, 2, ?)",
                    (lid,),
                )
                conn.commit()
            finally:
                conn.close()

            import database
            import local_first_db

            database.DatabaseManager._schema_initialized = False
            env.db.crear_estructura_completa()
            local_first_db.ensure_local_first_schema(str(env.db_path))
            local_first_db.ensure_local_first_schema(str(env.db_path))
            database.DatabaseManager._schema_initialized = True

            conn = env.connect()
            try:
                row = conn.execute(
                    "SELECT local_id FROM historial_precios LIMIT 1"
                ).fetchone()
                self.assertEqual(row["local_id"], lid)
                idx = conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='index' "
                    "AND tbl_name='historial_precios' AND sql LIKE ?",
                    ("%historial_precios%local_id%",),
                ).fetchone()
                self.assertIsNotNone(idx)
            finally:
                conn.close()
