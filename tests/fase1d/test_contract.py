# -*- coding: utf-8 -*-
"""FASE 1D CONTRACT: SQL, registry, seguridad y no-LWW. Sin PostgreSQL real."""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase0.harness import official_temp_db


class ContractCoordinatorTest(unittest.TestCase):
    def test_sql_sin_placeholders_psycopg2(self):
        from inventory_coordinator import postgres_coordinator_sql

        self.assertNotIn("%", postgres_coordinator_sql())

    def test_sql_no_empieza_con_backslash_ni_basura(self):
        """Regresión: r'''\\ no debe preservar un backslash de continuación."""
        from inventory_coordinator import postgres_coordinator_sql

        sql = postgres_coordinator_sql()
        self.assertTrue(sql)
        self.assertFalse(sql.startswith("\\"))
        self.assertFalse(sql.startswith("\ufeff"))
        self.assertRegex(
            sql,
            r"^(?:--|[A-Za-z])",
            "el SQL generado debe empezar por comentario o DDL, no por basura",
        )
        src = (REPO_ROOT / "inventory_coordinator.py").read_text(encoding="utf-8")
        self.assertNotIn('r"""\\', src)

    def test_artefacto_sql_paridad(self):
        from inventory_coordinator import (
            REMOTE_COORDINATOR_MIGRATION_FILENAME,
            postgres_coordinator_sql,
        )

        sql = postgres_coordinator_sql()
        artifact = (REPO_ROOT / REMOTE_COORDINATOR_MIGRATION_FILENAME).read_text(
            encoding="utf-8"
        )
        self.assertEqual(artifact, sql)

    def test_balance_bigint_y_pk_local_id(self):
        from inventory_coordinator import postgres_coordinator_sql

        sql = postgres_coordinator_sql()
        self.assertIn("CREATE TABLE IF NOT EXISTS inventory_balances", sql)
        self.assertIn("producto_local_id TEXT PRIMARY KEY", sql)
        self.assertIn("quantity_scaled BIGINT NOT NULL", sql)
        self.assertIn("CHECK (quantity_scaled >= 0)", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS inventory_balance_init", sql)
        self.assertIn("Nunca ejecutar contra SQLite", sql)

    def test_unique_violation_distingue_constraints(self):
        from inventory_coordinator import coordinator_apply_sql

        apply_sql = coordinator_apply_sql()
        self.assertIn("GET STACKED DIAGNOSTICS", apply_sql)
        self.assertIn("CONSTRAINT_NAME", apply_sql)
        self.assertIn("inventory_commands_pkey", apply_sql)
        self.assertIn("inventory_operations_pkey", apply_sql)
        self.assertIn("inventory_operations_command_id_line_no_key", apply_sql)
        self.assertIn("inventory_balances_pkey", apply_sql)
        idx = apply_sql.find("WHEN unique_violation THEN")
        self.assertGreater(idx, 0)
        handler = apply_sql[idx:idx + 1800]
        replay = handler.find("inventory_command_to_json")
        commands_pk = handler.find("inventory_commands_pkey")
        else_raise = handler.rfind("ELSE")
        self.assertGreater(commands_pk, 0)
        self.assertGreater(replay, commands_pk)
        self.assertGreater(else_raise, replay)
        self.assertIn("RAISE;", handler[else_raise:])

    def test_rpc_locking_y_atomicidad(self):
        from inventory_coordinator import coordinator_apply_sql

        apply_sql = coordinator_apply_sql()
        self.assertIn("CREATE OR REPLACE FUNCTION public.apply_inventory_command", apply_sql)
        self.assertIn("SECURITY DEFINER", apply_sql)
        self.assertIn("SET search_path = pg_catalog, public", apply_sql)
        self.assertIn("FOR UPDATE", apply_sql)
        self.assertIn("ORDER BY 1", apply_sql)
        self.assertIn("pg_advisory_xact_lock", apply_sql)
        self.assertIn("IDEMPOTENCY_CONFLICT", apply_sql)
        self.assertIn("INSUFFICIENT_STOCK", apply_sql)
        self.assertIn("BALANCE_NOT_FOUND", apply_sql)
        self.assertIn("'APPLIED'", apply_sql)
        self.assertIn("'REJECTED'", apply_sql)
        self.assertNotIn("EXECUTE format", apply_sql)
        self.assertNotIn("EXECUTE '", apply_sql)

    def test_rpc_no_lee_ni_escribe_productos_stock(self):
        from inventory_coordinator import coordinator_apply_sql, coordinator_seed_sql

        apply_sql = coordinator_apply_sql().lower()
        seed_sql = coordinator_seed_sql().lower()
        self.assertNotIn("productos.stock", apply_sql)
        self.assertNotIn("p.stock", apply_sql)
        self.assertNotIn("update public.productos", apply_sql)
        self.assertNotIn("update productos", apply_sql)
        self.assertNotIn("productos.stock", seed_sql)
        self.assertNotIn("update public.productos", seed_sql)

    def test_legacy_init_existe_pero_es_one_shot(self):
        from inventory_coordinator import coordinator_legacy_init_sql

        sql = coordinator_legacy_init_sql()
        self.assertIn("p.stock", sql)
        self.assertIn("ON CONFLICT (producto_local_id) DO NOTHING", sql)
        self.assertIn("NO la ejecuta el coordinador", sql)
        ls = (REPO_ROOT / "local_sync.py").read_text(encoding="utf-8")
        self.assertNotIn("initialize_inventory_balances_from_legacy(", ls.split("def _ensure_remote_schema")[1][:2500])
        self.assertIn("apply_postgres_coordinator_sql", ls)
        self.assertNotIn(
            "initialize_inventory_balances_from_legacy()",
            Path(REPO_ROOT / "local_sync.py").read_text(encoding="utf-8").split(
                "def _ensure_remote_schema"
            )[1].split("self._schema_ensured = True")[0],
        )

    def test_revoke_public_y_roles_supabase(self):
        from inventory_coordinator import postgres_coordinator_sql

        sql = postgres_coordinator_sql()
        self.assertIn("REVOKE ALL ON FUNCTION public.apply_inventory_command", sql)
        self.assertIn("FROM PUBLIC", sql)
        self.assertIn("FROM anon", sql)
        self.assertIn("FROM authenticated", sql)
        self.assertIn("ENABLE ROW LEVEL SECURITY", sql)

    def test_migracion_idempotente(self):
        from inventory_coordinator import postgres_coordinator_sql

        sql = postgres_coordinator_sql()
        self.assertIn("CREATE TABLE IF NOT EXISTS inventory_balances", sql)
        self.assertIn("CREATE OR REPLACE FUNCTION public.apply_inventory_command", sql)
        self.assertIn("ON CONFLICT (producto_local_id) DO NOTHING", sql)

    def test_no_entra_a_sync_lww(self):
        from local_sync import build_remote_upsert_sql
        from sync_registry import (
            APPLY_AUTHORITATIVE_EXCLUDE,
            COORDINATOR_REMOTE_TABLES,
            NON_SYNC_TABLES,
            is_sync_table,
            sync_tables,
            synced_tables,
            topo_order,
        )

        self.assertFalse(APPLY_AUTHORITATIVE_EXCLUDE)
        for table in ("inventory_balances", "inventory_balance_init"):
            self.assertIn(table, COORDINATOR_REMOTE_TABLES)
            self.assertFalse(is_sync_table(table))
            self.assertNotIn(table, sync_tables())
            self.assertNotIn(table, [name for name, _ in synced_tables()])
            self.assertNotIn(table, topo_order())
        self.assertIn("inventory_commands", NON_SYNC_TABLES)
        self.assertIn("inventory_operations", NON_SYNC_TABLES)
        upsert = build_remote_upsert_sql(
            "productos", ["local_id", "nombre", "stock"]
        )
        self.assertIn("stock=EXCLUDED.stock", upsert)
        self.assertNotIn("inventory_balances", upsert)

    def test_sqlite_no_ejecuta_sql_del_coordinador(self):
        from inventory_coordinator import postgres_coordinator_sql
        from schema_bootstrap import (
            SchemaBootstrapError,
            apply_engine_schema_fixes,
            apply_postgres_coordinator_sql,
        )

        with official_temp_db() as env:
            conn = env.connect()
            try:
                with self.assertRaises(SchemaBootstrapError) as ctx:
                    apply_postgres_coordinator_sql(conn, postgres_coordinator_sql())
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
                self.assertNotIn("apply_postgres_coordinator_sql", called)

    def test_exclude_autoritativa_sigue_inactiva(self):
        from sync_registry import APPLY_AUTHORITATIVE_EXCLUDE

        src = (REPO_ROOT / "sync_registry.py").read_text(encoding="utf-8")
        self.assertFalse(APPLY_AUTHORITATIVE_EXCLUDE)
        self.assertIn("APPLY_AUTHORITATIVE_EXCLUDE = False", src)

    def test_xfail_dos_sqlite_sigue(self):
        from tests.fase0 import test_contrato_xfail
        from tests.fase1b.test_xfail_heredados import STILL_XFAIL

        cls = test_contrato_xfail.ContratoExpectedFailureTest
        method = getattr(cls, "test_contrato_unicidad_global_ultimo_stock")
        self.assertTrue(getattr(method, "__unittest_expecting_failure__", False))
        self.assertIn("test_contrato_unicidad_global_ultimo_stock", STILL_XFAIL)
        self.assertIn("test_contrato_coordinador_inventario_existe", STILL_XFAIL)
