# -*- coding: utf-8 -*-
"""Análisis estático: todo UPDATE de stock debe estar en el inventario Fase 0."""
import re
import unittest
from pathlib import Path

try:
    from harness import REPO_ROOT
    from stock_writers import UPDATE_STOCK_FILES
except ImportError:
    from tests.fase0.harness import REPO_ROOT
    from tests.fase0.stock_writers import UPDATE_STOCK_FILES

UPDATE_STOCK_RE = re.compile(
    r"UPDATE\s+productos\s+SET[\s\S]{0,500}?stock",
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


class StockWritersStaticTest(unittest.TestCase):
    def test_scanner_coincide_con_inventario(self):
        found = set()
        for path, rel in _iter_production_py():
            text = path.read_text(encoding="utf-8", errors="replace")
            if UPDATE_STOCK_RE.search(text):
                found.add(rel)
        extra = found - UPDATE_STOCK_FILES
        missing = UPDATE_STOCK_FILES - found
        self.assertFalse(
            extra,
            msg="Writer de stock no inventariado en tests/fase0/stock_writers.py "
                f"ni docs/fase0/STOCK_WRITERS.md: {sorted(extra)}",
        )
        self.assertFalse(
            missing,
            msg="El inventario cita archivos sin UPDATE productos/stock; "
                f"actualizar STOCK_WRITERS.md: {sorted(missing)}",
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
