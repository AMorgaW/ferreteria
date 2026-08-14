# -*- coding: utf-8 -*-
"""Scanner 1E.0: writers directos de stock vs inventario declarado."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase0.test_stock_writers import _scan_direct_stock_files
from tests.fase0.stock_writers import (
    CLASSIFICATION_COUNTS,
    DIRECT_STOCK_WRITER_FILES,
    INSERT_STOCK_FILES,
    STOCK_WRITERS,
    UPDATE_STOCK_FILES,
)


class Fase1EScannerTest(unittest.TestCase):
    def test_conteos_1e0(self):
        self.assertEqual(CLASSIFICATION_COUNTS["NEGATIVO"], 5)
        self.assertEqual(CLASSIFICATION_COUNTS["POSITIVO"], 5)
        self.assertEqual(CLASSIFICATION_COUNTS["MIXTO"], 8)
        self.assertEqual(CLASSIFICATION_COUNTS["DERIVADO"], 4)
        self.assertEqual(CLASSIFICATION_COUNTS["UNKNOWN"], 0)
        self.assertEqual(len(STOCK_WRITERS), 22)
        self.assertEqual(len(UPDATE_STOCK_FILES), 8)
        self.assertEqual(INSERT_STOCK_FILES, frozenset({"repositories/productos_repo.py"}))
        self.assertEqual(len(DIRECT_STOCK_WRITER_FILES), 8)

    def test_scan_no_deja_archivos_fuera(self):
        update_found, insert_found, _ = _scan_direct_stock_files()
        extra = (update_found | insert_found) - DIRECT_STOCK_WRITER_FILES
        missing_update = UPDATE_STOCK_FILES - update_found
        missing_insert = INSERT_STOCK_FILES - insert_found
        self.assertFalse(extra, msg=f"writers no inventariados: {sorted(extra)}")
        self.assertFalse(
            missing_update, msg=f"UPDATE citados sin match: {sorted(missing_update)}"
        )
        self.assertFalse(
            missing_insert, msg=f"INSERT citados sin match: {sorted(missing_insert)}"
        )
        self.assertEqual(len(STOCK_WRITERS), 22)
