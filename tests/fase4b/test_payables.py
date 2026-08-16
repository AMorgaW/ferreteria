# -*- coding: utf-8 -*-
"""CxP: obligación proveedor, pagos, retry, overpayment, supplier return."""
from __future__ import annotations

import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from returns_schema import KIND_SUPPLIER_RETURN
from services.operational_balance import (
    PAYMENT_EXCEEDS_BALANCE,
    PaymentError,
    SUPPLIER_CREDIT,
)
from tests.fase4b.helpers import (
    confirm_return,
    credit_purchase,
    cxp,
    pay_supplier,
    phase4b_env,
    seed_ops,
)


class PayablesTest(unittest.TestCase):
    def test_09_purchase_credit_creates_payable(self):
        with phase4b_env() as env:
            seed_ops(env)
            cid = credit_purchase(env, total=100)
            snap = cxp(env).obtener_saldo_compra(cid)
            self.assertEqual(snap["original"], Decimal("100.00"))
            self.assertEqual(snap["monto_pagado"], Decimal("0.00"))
            self.assertEqual(snap["saldo_pendiente"], Decimal("100.00"))
            resumen = cxp(env).obtener_resumen_deudas()
            self.assertTrue(any(r["total_deuda"] == Decimal("100.00") for r in resumen))

    def test_10_11_partial_then_final_supplier_payment(self):
        with phase4b_env() as env:
            seed_ops(env)
            cid = credit_purchase(env, total=100)
            pay_supplier(env, cid, 40)
            snap = cxp(env).obtener_saldo_compra(cid)
            self.assertEqual(snap["saldo_pendiente"], Decimal("60.00"))
            self.assertEqual(snap["estado_pago"], "PARCIAL")
            pay_supplier(env, cid, 60)
            snap = cxp(env).obtener_saldo_compra(cid)
            self.assertEqual(snap["saldo_pendiente"], Decimal("0.00"))
            self.assertEqual(snap["estado_pago"], "PAGADO")

    def test_12_supplier_payment_retry_exactly_once(self):
        with phase4b_env() as env:
            seed_ops(env)
            cid = credit_purchase(env, total=100)
            lid = str(uuid.uuid4())
            first = pay_supplier(env, cid, 40, local_id=lid)
            second = pay_supplier(env, cid, 40, local_id=lid)
            self.assertEqual(first, second)
            snap = cxp(env).obtener_saldo_compra(cid)
            self.assertEqual(snap["monto_pagado"], Decimal("40.00"))
            conn = env.connect()
            try:
                n = conn.execute(
                    "SELECT COUNT(*) FROM abonos_compras WHERE id_compra=?", (cid,)
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(n, 1)

    def test_13_supplier_overpayment_rejected(self):
        with phase4b_env() as env:
            seed_ops(env)
            cid = credit_purchase(env, total=100)
            pay_supplier(env, cid, 70)
            with self.assertRaises(PaymentError) as ctx:
                pay_supplier(env, cid, 40)
            self.assertEqual(ctx.exception.code, PAYMENT_EXCEEDS_BALANCE)
            snap = cxp(env).obtener_saldo_compra(cid)
            self.assertEqual(snap["saldo_pendiente"], Decimal("30.00"))

    def test_14_supplier_return_reduces_payable(self):
        with phase4b_env() as env:
            seed_ops(env, stock=0)
            cid = credit_purchase(env, total=10, cantidad=10)
            confirm_return(env, cid, KIND_SUPPLIER_RETURN, 3, original_tipo="compra")
            snap = cxp(env).obtener_saldo_compra(cid)
            self.assertEqual(snap["original"], Decimal("100.00"))
            self.assertEqual(snap["reversals"], Decimal("30.00"))
            self.assertEqual(snap["net_obligation"], Decimal("70.00"))
            self.assertEqual(snap["saldo_pendiente"], Decimal("70.00"))

    def test_15_paid_then_supplier_return_exposes_credit_no_cash_in(self):
        with phase4b_env() as env:
            seed_ops(env, stock=0)
            from tests.fase4b.helpers import open_caja

            svc = open_caja(env, Decimal("10000"))
            cid = credit_purchase(env, total=10, cantidad=10)
            pay_supplier(env, cid, 100, "EFECTIVO")
            expected = svc.expected_cash()
            confirm_return(env, cid, KIND_SUPPLIER_RETURN, 3, original_tipo="compra")
            snap = cxp(env).obtener_saldo_compra(cid)
            self.assertEqual(snap["credito_a_favor"], Decimal("30.00"))
            self.assertEqual(snap["credit_kind"], SUPPLIER_CREDIT)
            self.assertEqual(snap["saldo_pendiente"], Decimal("0.00"))
            self.assertEqual(svc.expected_cash(), expected)
            conn = env.connect()
            try:
                drawer_in = conn.execute(
                    "SELECT COUNT(*) FROM cash_movements WHERE cash_effect_kind='DRAWER_IN'"
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(drawer_in, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
