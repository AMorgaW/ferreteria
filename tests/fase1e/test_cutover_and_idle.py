# -*- coding: utf-8 -*-
"""FASE 1E.0: writers productivos no activan el gateway; LWW/exclude intactos."""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase0.harness import REPO_ROOT as HARNESS_ROOT
from tests.fase0.stock_writers import PRODUCTIVE_WRITER_FILES

FORBIDDEN_TOKENS = (
    "inventory_gateway",
    "InventoryGateway",
    "apply_inventory_command",
    "InventoryCoordinatorClient",
    "INVENTORY_CUTOVER_ENABLED",
)


class WritersIdleAndContractTest(unittest.TestCase):
    def test_ningun_writer_productivo_importa_gateway_ni_coordinador(self):
        for rel in PRODUCTIVE_WRITER_FILES:
            path = HARNESS_ROOT / rel
            text = path.read_text(encoding="utf-8")
            for token in FORBIDDEN_TOKENS:
                self.assertNotIn(
                    token,
                    text,
                    msg=f"{rel} no debe mencionar {token} en 1E.0",
                )
            tree = ast.parse(text)
            imported = set()
            called = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imported.add(alias.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
                elif isinstance(node, ast.Call):
                    func = node.func
                    if isinstance(func, ast.Name):
                        called.add(func.id)
                    elif isinstance(func, ast.Attribute):
                        called.add(func.attr)
            self.assertNotIn("inventory_gateway", imported)
            self.assertNotIn("inventory_coordinator", imported)
            self.assertNotIn("apply_inventory_command", called)
            self.assertNotIn("InventoryGateway", called)
            self.assertNotIn("InventoryCoordinatorClient", called)

    def test_inventory_balances_no_entra_en_lww(self):
        from local_sync import build_remote_upsert_sql
        from sync_registry import (
            COORDINATOR_REMOTE_TABLES,
            is_sync_table,
            sync_tables,
            synced_tables,
            topo_order,
            SYNC_REGISTRY,
        )

        self.assertIn("inventory_balances", COORDINATOR_REMOTE_TABLES)
        self.assertNotIn("inventory_balances", SYNC_REGISTRY)
        self.assertFalse(is_sync_table("inventory_balances"))
        self.assertNotIn("inventory_balances", sync_tables())
        self.assertNotIn("inventory_balances", [name for name, _ in synced_tables()])
        self.assertNotIn("inventory_balances", topo_order())
        upsert = build_remote_upsert_sql(
            "productos", ["local_id", "nombre", "stock"]
        )
        self.assertIn("stock=EXCLUDED.stock", upsert)
        self.assertNotIn("inventory_balances", upsert)

    def test_apply_authoritative_exclude_sigue_false(self):
        from sync_registry import (
            APPLY_AUTHORITATIVE_EXCLUDE,
            declared_authoritative_exclude,
        )

        src = (HARNESS_ROOT / "sync_registry.py").read_text(encoding="utf-8")
        self.assertFalse(APPLY_AUTHORITATIVE_EXCLUDE)
        self.assertIn("APPLY_AUTHORITATIVE_EXCLUDE = False", src)
        self.assertEqual(declared_authoritative_exclude("productos"), ("stock",))

    def test_xfail_inv01_inv02_siguen(self):
        from tests.fase0 import test_contrato_xfail

        src = Path(test_contrato_xfail.__file__).read_text(encoding="utf-8")
        self.assertIn("@unittest.expectedFailure", src)
        self.assertIn("test_contrato_unicidad_global_ultimo_stock", src)
        self.assertIn("test_contrato_payload_productos_sin_stock_autoritativo", src)
