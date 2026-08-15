# -*- coding: utf-8 -*-
"""Scanner 1E.2: W01–W18 preparados, 0 UNTRACKED."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase0.stock_writers import (
    DIRECT_WRITER_IDS,
    GATEWAY_PREPARED_IDS,
    MIXED_WRITER_IDS,
    POSITIVE_WRITER_IDS,
    PRE_CUTOVER_SQL_ALLOWED,
    UNTRACKED_DIRECT_WRITER,
)
from tests.fase0.test_stock_writers import scan_stock_writes_by_function
from inventory_gateway import INVENTORY_CUTOVER_ENABLED


class Fase1E2ScannerTest(unittest.TestCase):
    def test_cutover_off(self):
        self.assertFalse(INVENTORY_CUTOVER_ENABLED)
        src = (REPO_ROOT / "inventory_gateway.py").read_text(encoding="utf-8")
        self.assertIn("INVENTORY_CUTOVER_ENABLED = False", src)

    def test_w01_w18_preparados(self):
        self.assertEqual(len(POSITIVE_WRITER_IDS), 5)
        self.assertEqual(len(MIXED_WRITER_IDS), 8)
        self.assertEqual(set(DIRECT_WRITER_IDS), GATEWAY_PREPARED_IDS)
        self.assertEqual(len(GATEWAY_PREPARED_IDS), 18)
        hits = scan_stock_writes_by_function()
        untracked = [h for h in hits if h["status"] == UNTRACKED_DIRECT_WRITER]
        self.assertFalse(untracked, msg=repr(untracked))
        found = {h["writer_id"] for h in hits if h["writer_id"]}
        self.assertTrue(set(DIRECT_WRITER_IDS).issubset(found))
        for hit in hits:
            if hit["writer_id"] in GATEWAY_PREPARED_IDS:
                self.assertEqual(hit["status"], PRE_CUTOVER_SQL_ALLOWED)
                self.assertTrue(hit["function"])
                self.assertTrue(hit["file"])
                self.assertIn("stock", hit["sql"].lower())


if __name__ == "__main__":
    unittest.main()
