# -*- coding: utf-8 -*-
"""FASE 1B.1: política de arranque remota ≠ registry de sync."""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


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


class ArranqueRemotoTest(unittest.TestCase):
    def test_no_enumera_todas_las_tablas_sync(self):
        from sync_registry import (
            CRITICAL_REMOTE_TABLES,
            REMOTE_TABLES_REQUIRED_FOR_STARTUP,
            remote_tables_required_for_startup,
            sync_tables,
        )

        startup = remote_tables_required_for_startup()
        sync = sync_tables()
        self.assertEqual(tuple(startup), REMOTE_TABLES_REQUIRED_FOR_STARTUP)
        self.assertEqual(CRITICAL_REMOTE_TABLES, REMOTE_TABLES_REQUIRED_FOR_STARTUP)
        self.assertTrue(set(startup).issubset(set(sync)))
        self.assertNotEqual(set(startup), set(sync))
        self.assertLess(len(startup), len(sync))
        self.assertNotIn("configuracion", startup)
        self.assertNotIn("historial_precios", startup)
        self.assertNotIn("pagos_cuentas", startup)
        self.assertNotIn("auditoria", startup)
        self.assertIn("productos", startup)
        self.assertIn("ventas", startup)
        self.assertIn("compras", startup)

    def test_lista_se_deriva_del_registry_no_es_paralela(self):
        src = (REPO_ROOT / "sync_registry.py").read_text(encoding="utf-8")
        self.assertEqual(
            _assign_from_call(src, "REMOTE_TABLES_REQUIRED_FOR_STARTUP"),
            "remote_tables_required_for_startup",
        )
        self.assertEqual(
            _assign_from_call(src, "CRITICAL_REMOTE_TABLES"),
            "REMOTE_TABLES_REQUIRED_FOR_STARTUP",
        )
        ls = (REPO_ROOT / "local_sync.py").read_text(encoding="utf-8")
        self.assertIn("REMOTE_TABLES_REQUIRED_FOR_STARTUP", ls)
        self.assertIn("validar_arranque", ls)
