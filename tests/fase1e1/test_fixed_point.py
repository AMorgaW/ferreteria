# -*- coding: utf-8 -*-
"""Fixed-point: float no entra al ledger autoritativo."""
from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class FixedPointBridgeTest(unittest.TestCase):
    def test_ledger_rechaza_float(self):
        from inventory_ledger import QuantityScaleError, quantity_to_scaled

        with self.assertRaises(QuantityScaleError):
            quantity_to_scaled(1.5)

    def test_writer_bridge_convierte_sin_pasar_float_al_ledger(self):
        from inventory_writer_support import commercial_quantity_to_scaled

        self.assertEqual(commercial_quantity_to_scaled(1.5), 1500)
        self.assertEqual(commercial_quantity_to_scaled("1.5"), 1500)
        self.assertEqual(commercial_quantity_to_scaled(Decimal("0.125")), 125)
        self.assertEqual(commercial_quantity_to_scaled(2), 2000)
        self.assertIsInstance(commercial_quantity_to_scaled(1.5), int)
