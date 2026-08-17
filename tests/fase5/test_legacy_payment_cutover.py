# -*- coding: utf-8 -*-
"""Cutover 010 via migration lifecycle. Decimal. Temp SQLite only."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from schema_lifecycle import ensure_sqlite_schema_current
from services.operational_balance import compute_receivable
from tests.fase0.harness import REPO_FERRETERIA_DB
from tests.fase5.helpers import (
    commercial_sha256,
    insert_legacy_abono_venta,
    insert_legacy_sale,
    make_legacy_station_db,
)


def _baselines(path, venta_id):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT amount, source FROM operational_balance_legacy_payments "
            "WHERE document_tipo='venta' AND document_id=?",
            (venta_id,),
        ).fetchall()
        snap = compute_receivable(conn, venta_id)
        return rows, snap
    finally:
        conn.close()


class Migration010CutoverTest(unittest.TestCase):
    def setUp(self):
        self._sha = commercial_sha256()
        self._tmp = tempfile.TemporaryDirectory(prefix="ferrepro-fase5b-010-")
        self.db_path = Path(self._tmp.name) / "legacy.db"
        self.assertNotEqual(self.db_path.resolve(), REPO_FERRETERIA_DB.resolve())

    def tearDown(self):
        self._tmp.cleanup()
        self.assertEqual(commercial_sha256(), self._sha)

    def _migrate(self):
        return ensure_sqlite_schema_current(str(self.db_path))

    def test_11_monto_pagado_30_becomes_baseline_balance_70(self):
        make_legacy_station_db(self.db_path)
        venta_id = insert_legacy_sale(self.db_path, total=100, monto_pagado=30)
        self._migrate()
        rows, snap = _baselines(self.db_path, venta_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(Decimal(str(rows[0]["amount"])), Decimal("30"))
        self.assertEqual(rows[0]["source"], "CUTOVER_MONTO_PAGADO")
        self.assertEqual(snap.payments, Decimal("30.00"))
        self.assertEqual(snap.balance, Decimal("70.00"))

    def test_12_fully_paid_balance_zero(self):
        make_legacy_station_db(self.db_path)
        venta_id = insert_legacy_sale(self.db_path, total=100, monto_pagado=100)
        self._migrate()
        rows, snap = _baselines(self.db_path, venta_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(Decimal(str(rows[0]["amount"])), Decimal("100"))
        self.assertEqual(snap.payments, Decimal("100.00"))
        self.assertEqual(snap.balance, Decimal("0.00"))

    def test_13_existing_abono_prevents_double_baseline(self):
        make_legacy_station_db(self.db_path)
        venta_id = insert_legacy_sale(self.db_path, total=100, monto_pagado=30)
        insert_legacy_abono_venta(self.db_path, venta_id, 30)
        self._migrate()
        rows, snap = _baselines(self.db_path, venta_id)
        self.assertEqual(len(rows), 0)
        self.assertEqual(snap.payments, Decimal("30.00"))
        self.assertEqual(snap.balance, Decimal("70.00"))

    def test_14_ambiguous_legacy_projection_not_synthesized(self):
        make_legacy_station_db(self.db_path)
        venta_id = insert_legacy_sale(self.db_path, total=100, monto_pagado=50)
        insert_legacy_abono_venta(self.db_path, venta_id, 30)
        self._migrate()
        rows, snap = _baselines(self.db_path, venta_id)
        self.assertEqual(len(rows), 0)
        self.assertEqual(snap.payments, Decimal("30.00"))
        self.assertEqual(snap.balance, Decimal("70.00"))
        self.assertNotEqual(snap.payments, Decimal("50.00"))

    def test_15_rerun_exactly_one_baseline(self):
        make_legacy_station_db(self.db_path)
        venta_id = insert_legacy_sale(self.db_path, total=100, monto_pagado=30)
        self._migrate()
        self._migrate()
        rows, snap = _baselines(self.db_path, venta_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(Decimal(str(rows[0]["amount"])), Decimal("30"))
        self.assertEqual(snap.balance, Decimal("70.00"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
