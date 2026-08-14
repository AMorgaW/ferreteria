# -*- coding: utf-8 -*-
"""Análisis estático: todo UPDATE/INSERT de stock debe estar en el inventario."""
import ast
import re
import unittest
from pathlib import Path

try:
    from harness import REPO_ROOT
    from stock_writers import (
        CLASSIFICATION_COUNTS,
        DIRECT_STOCK_WRITER_FILES,
        INSERT_STOCK_FILES,
        STOCK_WRITERS,
        UPDATE_STOCK_FILES,
    )
except ImportError:
    from tests.fase0.harness import REPO_ROOT
    from tests.fase0.stock_writers import (
        CLASSIFICATION_COUNTS,
        DIRECT_STOCK_WRITER_FILES,
        INSERT_STOCK_FILES,
        STOCK_WRITERS,
        UPDATE_STOCK_FILES,
    )

UPDATE_STOCK_RE = re.compile(
    r"UPDATE\s+productos\s+SET[\s\S]{0,800}?stock",
    re.IGNORECASE,
)

INSERT_STOCK_RE = re.compile(
    r"INSERT\s+INTO\s+productos\s*\([^;]{0,1200}?\bstock\b",
    re.IGNORECASE | re.DOTALL,
)

SET_STOCK_RE = re.compile(
    r"SET\s+stock\s*=|"
    r"stock\s*=\s*stock\s*[+-]\s*\?|"
    r"stock\s*=\s*\?",
    re.IGNORECASE,
)

SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "tests", "docs",
    ".cursor", ".agents", "dist", "build",
}


def _iter_production_py():
    for path in REPO_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        yield path, rel.as_posix()


def _scan_direct_stock_files():
    update_files = set()
    insert_files = set()
    set_stock_files = set()
    for path, rel in _iter_production_py():
        text = path.read_text(encoding="utf-8", errors="replace")
        if UPDATE_STOCK_RE.search(text):
            update_files.add(rel)
        if INSERT_STOCK_RE.search(text):
            insert_files.add(rel)
        if SET_STOCK_RE.search(text) and (
            "productos" in text.lower()
        ) and UPDATE_STOCK_RE.search(text):
            set_stock_files.add(rel)
    return update_files, insert_files, set_stock_files


class StockWritersStaticTest(unittest.TestCase):
    def test_scanner_coincide_con_inventario(self):
        update_found, insert_found, _set_found = _scan_direct_stock_files()
        extra_update = update_found - UPDATE_STOCK_FILES
        missing_update = UPDATE_STOCK_FILES - update_found
        extra_insert = insert_found - INSERT_STOCK_FILES
        missing_insert = INSERT_STOCK_FILES - insert_found
        extra_direct = (update_found | insert_found) - DIRECT_STOCK_WRITER_FILES
        self.assertFalse(
            extra_update,
            msg="Writer UPDATE de stock no inventariado en "
                "tests/fase0/stock_writers.py ni docs/fase0/STOCK_WRITERS.md: "
                f"{sorted(extra_update)}",
        )
        self.assertFalse(
            missing_update,
            msg="El inventario cita archivos sin UPDATE productos/stock; "
                f"actualizar STOCK_WRITERS.md: {sorted(missing_update)}",
        )
        self.assertFalse(
            extra_insert,
            msg="INSERT INTO productos con columna stock no inventariado: "
                f"{sorted(extra_insert)}",
        )
        self.assertFalse(
            missing_insert,
            msg="El inventario cita INSERT de stock sin coincidencia: "
                f"{sorted(missing_insert)}",
        )
        self.assertFalse(
            extra_direct,
            msg="Writer directo de stock (UPDATE/INSERT) no inventariado: "
                f"{sorted(extra_direct)}",
        )

    def test_inventario_declarado_tiene_ids_y_clasificacion(self):
        ids = [w["id"] for w in STOCK_WRITERS]
        self.assertEqual(len(ids), len(set(ids)), msg=f"IDs duplicados: {ids}")
        allowed = {"NEGATIVO", "POSITIVO", "MIXTO", "DERIVADO", "UNKNOWN"}
        kinds = {"direct", "insert", "derived"}
        for writer in STOCK_WRITERS:
            self.assertIn(writer["classification"], allowed, msg=writer["id"])
            self.assertIn(writer["kind"], kinds, msg=writer["id"])
            self.assertTrue(writer["file"], msg=writer["id"])
            self.assertTrue(writer["function"], msg=writer["id"])
            path = REPO_ROOT / writer["file"]
            self.assertTrue(path.is_file(), msg=f"{writer['id']} {writer['file']}")
            source = path.read_text(encoding="utf-8", errors="replace")
            token = writer["function"].split("(")[0].split(".")[-1].strip()
            if writer["kind"] != "derived":
                self.assertIn(
                    token.split()[0],
                    source,
                    msg=f"{writer['id']} no encuentra {token} en {writer['file']}",
                )
        self.assertEqual(CLASSIFICATION_COUNTS["UNKNOWN"], 0)
        self.assertEqual(sum(CLASSIFICATION_COUNTS.values()), len(STOCK_WRITERS))

    def test_funciones_directas_existen_en_ast_cuando_son_metodos(self):
        for writer in STOCK_WRITERS:
            if writer["kind"] == "derived":
                continue
            func = writer["function"]
            if "(" in func or "closure" in func.lower():
                continue
            if "." not in func:
                continue
            class_name, method_name = func.split(".", 1)
            path = REPO_ROOT / writer["file"]
            tree = ast.parse(path.read_text(encoding="utf-8"))
            found = False
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef) and item.name == method_name:
                            found = True
            self.assertTrue(
                found,
                msg=f"{writer['id']}: no está {class_name}.{method_name} en {writer['file']}",
            )

    def test_ui_todavia_ofrece_entrada_compra(self):
        """CAR INV-03: los combos productivos siguen listando ENTRADA_COMPRA."""
        entrada = (REPO_ROOT / "ui" / "entrada_inventario_ui.py").read_text(
            encoding="utf-8"
        )
        movimientos = (REPO_ROOT / "ui" / "movimientos_ui.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("ENTRADA_COMPRA", entrada)
        self.assertIn("ENTRADA_COMPRA", movimientos)
        self.assertIn("addItems(['ENTRADA_COMPRA'", entrada)

    def test_docs_stock_writers_menciona_ids_1e0(self):
        docs = (REPO_ROOT / "docs" / "fase0" / "STOCK_WRITERS.md").read_text(
            encoding="utf-8"
        )
        for writer in STOCK_WRITERS:
            self.assertIn(
                writer["id"],
                docs,
                msg=f"{writer['id']} falta en STOCK_WRITERS.md",
            )
        self.assertIn("UNKNOWN", docs)
        self.assertIn("0", docs)
