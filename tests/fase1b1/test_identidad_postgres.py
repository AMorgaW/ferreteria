# -*- coding: utf-8 -*-
"""FASE 1B.1: una sola fuente de identidad local_id PostgreSQL."""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class IdentidadPostgresTest(unittest.TestCase):
    def test_definicion_canonica_es_sync_tables(self):
        from sync_registry import (
            sync_tables,
            tables_requiring_postgres_local_id_unique,
        )

        self.assertEqual(
            tables_requiring_postgres_local_id_unique(),
            sync_tables(),
        )

    def test_artefacto_sql_deriva_de_la_misma_funcion(self):
        from sync_registry import (
            REMOTE_IDENTITY_MIGRATION_FILENAME,
            postgres_identity_sql,
            tables_requiring_postgres_local_id_unique,
        )

        identity_sql = (
            REPO_ROOT / REMOTE_IDENTITY_MIGRATION_FILENAME
        ).read_text(encoding="utf-8")
        self.assertEqual(identity_sql, postgres_identity_sql())
        self.assertEqual(
            identity_sql, postgres_identity_sql(
                tables_requiring_postgres_local_id_unique()
            )
        )

    def test_runtime_usa_la_funcion_canonica_no_ux(self):
        src = (REPO_ROOT / "local_sync.py").read_text(encoding="utf-8")
        self.assertIn("postgres_identity_sql()", src)
        self.assertIn("apply_postgres_identity_sql", src)
        self.assertIn("tables_requiring_postgres_local_id_unique", src)
        self.assertNotIn("CREATE UNIQUE INDEX IF NOT EXISTS ux_", src)
        self.assertNotIn("ux_{table}_local_id", src)

    def test_nombres_uq_y_ux_son_la_misma_identidad(self):
        from sync_registry import (
            postgres_local_id_unique_index_aliases,
            postgres_local_id_unique_index_name,
        )

        self.assertEqual(
            postgres_local_id_unique_index_name("productos"),
            "uq_productos_local_id",
        )
        aliases = postgres_local_id_unique_index_aliases("productos")
        self.assertIn("uq_productos_local_id", aliases)
        self.assertIn("ux_productos_local_id", aliases)
        self.assertEqual(len(set(aliases)), len(aliases))

    def test_sql_no_crea_indice_si_ya_hay_unique_equivalente(self):
        from sync_registry import postgres_identity_sql

        sql = postgres_identity_sql()
        self.assertIn("pg_index", sql)
        self.assertIn("attname = 'local_id'", sql)
        self.assertIn("indisunique", sql)
        self.assertIn("uq_' || t || '_local_id'", sql)
        self.assertLess(sql.find("FROM pg_index"), sql.find("CREATE UNIQUE INDEX"))

    def test_schema_bootstrap_no_mezcla_sql_sqlite_en_identidad_pg(self):
        from schema_bootstrap import apply_engine_schema_fixes

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
                self.assertNotIn("apply_postgres_identity_sql", called)
        self.assertTrue(callable(apply_engine_schema_fixes))
