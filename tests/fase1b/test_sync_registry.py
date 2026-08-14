# -*- coding: utf-8 -*-
"""FASE 1B: registry canónico de sync. BD tempfile; nunca copia ferreteria.db."""
from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase0.harness import REPO_FERRETERIA_DB, official_temp_db


def _assign_from_call(source: str, name: str) -> str:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                if isinstance(node.value, ast.Call) and isinstance(
                    node.value.func, ast.Name
                ):
                    return node.value.func.id
                if isinstance(node.value, ast.Name):
                    return node.value.id
    return ""


def _sql_array_tables(sql: str) -> set:
    match = re.search(
        r"ARRAY\[\s*(.*?)\s*\]", sql, flags=re.IGNORECASE | re.DOTALL
    )
    if not match:
        return set()
    return set(re.findall(r"'([A-Za-z_][A-Za-z0-9_]*)'", match.group(1)))


class SyncRegistryTest(unittest.TestCase):
    def test_registry_es_unica_fuente(self):
        from local_first_db import SYNC_TABLES
        from local_sync import FK_MAP, TOPO_ORDER, SupabaseSyncService
        from sync_registry import fk_map, sync_tables, synced_tables, topo_order

        self.assertEqual(list(SYNC_TABLES), list(sync_tables()))
        self.assertEqual(list(SupabaseSyncService.SYNCED_TABLES), synced_tables())
        self.assertEqual(FK_MAP, fk_map())
        self.assertEqual(list(TOPO_ORDER), list(topo_order()))
        self.assertEqual(
            list(SupabaseSyncService.PULL_ORDER), list(TOPO_ORDER)
        )
        synced = {t for t, _et in SupabaseSyncService.SYNCED_TABLES}
        self.assertEqual(set(SYNC_TABLES), synced)
        self.assertIn("configuracion", synced)
        self.assertIn("pagos_cuentas", synced)

    def test_listas_secundarias_no_son_literales_independientes(self):
        lf = (REPO_ROOT / "local_first_db.py").read_text(encoding="utf-8")
        ls = (REPO_ROOT / "local_sync.py").read_text(encoding="utf-8")
        self.assertEqual(_assign_from_call(lf, "SYNC_TABLES"), "sync_tables")
        self.assertEqual(_assign_from_call(ls, "FK_MAP"), "fk_map")
        self.assertEqual(_assign_from_call(ls, "TOPO_ORDER"), "topo_order")
        self.assertIn("SYNCED_TABLES = synced_tables()", ls)
        self.assertIn("PULL_ORDER = TOPO_ORDER", ls)
        self.assertNotIn("self.PULL_ORDER", ls)

    def test_orden_derivado_respeta_fks_padre_hijo(self):
        from sync_registry import fk_map, topo_order

        order = topo_order()
        index = {name: i for i, name in enumerate(order)}
        for table, parents in fk_map().items():
            self.assertIn(table, index, msg=table)
            for _fk, parent in parents:
                self.assertLess(
                    index[parent],
                    index[table],
                    msg=f"{parent} debe ir antes que {table}",
                )
        self.assertLess(index["proveedores"], index["productos"])
        self.assertLess(index["productos"], index["detalle_ventas"])
        self.assertLess(index["cuentas_por_cobrar"], index["pagos_cuentas"])

    def test_ciclo_de_dependencia_es_error_visible(self):
        from sync_registry import SyncRegistryError, topo_order

        cyclic = {
            "a": {
                "sync": True,
                "push": True,
                "entity_type": "a",
                "pk": "id",
                "parents": (("b_id", "b"),),
            },
            "b": {
                "sync": True,
                "push": True,
                "entity_type": "b",
                "pk": "id",
                "parents": (("a_id", "a"),),
            },
        }
        with self.assertRaises(SyncRegistryError) as ctx:
            topo_order(cyclic)
        self.assertIn("Ciclo", str(ctx.exception))

    def test_padre_ausente_es_error_visible(self):
        from sync_registry import SyncRegistryError, topo_order

        broken = {
            "hijos": {
                "sync": True,
                "push": True,
                "entity_type": "child",
                "pk": "id",
                "parents": (("padre_id", "no_existe"),),
            }
        }
        with self.assertRaises(SyncRegistryError) as ctx:
            topo_order(broken)
        self.assertIn("no_existe", str(ctx.exception))

    def test_sql_pg_no_diverge_del_registry(self):
        from sync_registry import (
            REMOTE_IDENTITY_MIGRATION_FILENAME,
            postgres_identity_sql,
            sync_tables,
        )

        expected = set(sync_tables())
        identity_sql = (
            REPO_ROOT / REMOTE_IDENTITY_MIGRATION_FILENAME
        ).read_text(encoding="utf-8")
        self.assertEqual(identity_sql, postgres_identity_sql())
        self.assertEqual(_sql_array_tables(identity_sql), expected)

        legacy = (REPO_ROOT / "supabase_local_first_migration.sql").read_text(
            encoding="utf-8"
        )
        self.assertEqual(_sql_array_tables(legacy), expected)

    def test_non_sync_tables_sin_local_id(self):
        from sync_registry import NON_SYNC_TABLES

        with official_temp_db() as env:
            self.assertNotEqual(
                env.db_path.resolve(), REPO_FERRETERIA_DB.resolve()
            )
            conn = env.connect()
            try:
                for table in ("devoluciones", "formulas_mezcla"):
                    self.assertIn(table, NON_SYNC_TABLES)
                    cols = {
                        row[1]
                        for row in conn.execute(f"PRAGMA table_info({table})")
                    }
                    self.assertNotIn("local_id", cols)
            finally:
                conn.close()

    def test_stock_declarado_proyeccion_pero_no_excluido_aun(self):
        from sync_registry import (
            APPLY_AUTHORITATIVE_EXCLUDE,
            declared_authoritative_exclude,
            declared_projection_fields,
            fields_excluded_from_authoritative_write,
            product_field_class,
        )

        self.assertFalse(APPLY_AUTHORITATIVE_EXCLUDE)
        self.assertEqual(declared_projection_fields("productos"), ("stock",))
        self.assertEqual(declared_authoritative_exclude("productos"), ("stock",))
        self.assertEqual(fields_excluded_from_authoritative_write("productos"), ())
        self.assertEqual(product_field_class("stock"), "projection")
        self.assertEqual(product_field_class("nombre"), "metadata")
        self.assertEqual(product_field_class("local_id"), "identity_global")
        self.assertEqual(product_field_class("id"), "identity_local")
        self.assertEqual(product_field_class("codigo_barras"), "business_key")
