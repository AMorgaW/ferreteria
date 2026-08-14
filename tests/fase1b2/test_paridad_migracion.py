# -*- coding: utf-8 -*-
"""FASE 1B.2: paridad semántica de UNIQUE(local_id) en la migración manual."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _norm(sql: str) -> str:
    return " ".join((sql or "").split())


def _sql_array_tables(sql: str) -> set:
    match = re.search(
        r"ARRAY\[\s*(.*?)\s*\]", sql, flags=re.IGNORECASE | re.DOTALL
    )
    if not match:
        return set()
    return set(re.findall(r"'([A-Za-z_][A-Za-z0-9_]*)'", match.group(1)))


def _should_create(indexes) -> bool:
    from sync_registry import equivalent_local_id_unique_exists

    return not equivalent_local_id_unique_exists(indexes)


class ParidadMigracionTest(unittest.TestCase):
    def test_sin_unique_se_crearia_uno_valido(self):
        self.assertTrue(_should_create([]))
        sql = (REPO_ROOT / "supabase_local_first_migration.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn("CREATE UNIQUE INDEX IF NOT EXISTS", sql)
        self.assertIn("uq_' || t || '_local_id'", sql)
        self.assertIn("ON %I(local_id)", sql)

    def test_uq_existente_no_duplica(self):
        indexes = [
            {
                "name": "uq_productos_local_id",
                "unique": True,
                "columns": ("local_id",),
                "predicate": None,
            }
        ]
        self.assertFalse(_should_create(indexes))

    def test_ux_legado_equivalente_no_duplica(self):
        indexes = [
            {
                "name": "ux_productos_local_id",
                "unique": True,
                "columns": ("local_id",),
                "predicate": None,
            }
        ]
        self.assertFalse(_should_create(indexes))

    def test_indice_no_unique_no_cuenta(self):
        indexes = [
            {
                "name": "idx_productos_local_id",
                "unique": False,
                "columns": ("local_id",),
                "predicate": None,
            }
        ]
        self.assertTrue(_should_create(indexes))

    def test_unique_compuesto_no_cuenta_como_identidad(self):
        indexes = [
            {
                "name": "uq_productos_local_id_codigo",
                "unique": True,
                "columns": ("local_id", "codigo_barras"),
                "predicate": None,
            }
        ]
        self.assertTrue(_should_create(indexes))

    def test_migracion_repetida_idempotente(self):
        created = []
        indexes = []
        for _ in range(3):
            if _should_create(indexes):
                created.append("uq_productos_local_id")
                indexes.append(
                    {
                        "name": "uq_productos_local_id",
                        "unique": True,
                        "columns": ("local_id",),
                        "predicate": None,
                    }
                )
        self.assertEqual(created, ["uq_productos_local_id"])
        self.assertFalse(_should_create(indexes))

    def test_paridad_semantica_predicado_y_tablas(self):
        from sync_registry import (
            postgres_identity_sql,
            postgres_local_id_unique_exists_plpgsql,
            tables_requiring_postgres_local_id_unique,
        )

        frag = postgres_local_id_unique_exists_plpgsql()
        migration = (REPO_ROOT / "supabase_local_first_migration.sql").read_text(
            encoding="utf-8"
        )
        identity = postgres_identity_sql()
        self.assertIn(_norm(frag), _norm(migration))
        self.assertIn(_norm(frag), _norm(identity))
        for token in (
            "pg_index",
            "indisunique",
            "indpred IS NULL",
            "indnkeyatts = 1",
            "attname = 'local_id'",
        ):
            self.assertIn(token, migration)
            self.assertIn(token, identity)
        self.assertLess(
            migration.find("FROM pg_index"),
            migration.find("CREATE UNIQUE INDEX"),
        )
        self.assertEqual(
            _sql_array_tables(migration),
            set(tables_requiring_postgres_local_id_unique()),
        )
        self.assertIn("ux_*", migration)
        self.assertNotIn("DROP INDEX", migration.upper().replace("IF NOT EXISTS", ""))
