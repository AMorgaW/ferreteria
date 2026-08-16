# -*- coding: utf-8 -*-
"""CxC: obligación, abonos, retry, overpayment, returns/voids, crédito a favor."""
from __future__ import annotations

import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from returns_schema import KIND_CUSTOMER_RETURN, KIND_SALE_VOID
from services.operational_balance import PAYMENT_EXCEEDS_BALANCE, PaymentError, CUSTOMER_CREDIT
from tests.fase4b.helpers import (
    confirm_return,
    credit_sale,
    cxc,
    pay_customer,
    phase4b_env,
    seed_cliente,
    seed_ops,
)


class ReceivablesTest(unittest.TestCase):
    def test_01_credit_sale_creates_receivable(self):
        with phase4b_env() as env:
            seed_ops(env)
            cid = seed_cliente(env)
            venta = credit_sale(env, total=100, cliente_id=cid)
            snap = cxc(env).obtener_saldo_venta(venta.id)
            self.assertEqual(snap["original"], Decimal("100.00"))
            self.assertEqual(snap["monto_pagado"], Decimal("0.00"))
            self.assertEqual(snap["saldo_pendiente"], Decimal("100.00"))
            pendientes = cxc(env).obtener_ventas_credito_pendientes()
            self.assertEqual(len(pendientes), 1)
            self.assertEqual(pendientes[0]["saldo_pendiente"], Decimal("100.00"))

    def test_02_03_partial_then_final_customer_payment(self):
        with phase4b_env() as env:
            seed_ops(env)
            venta = credit_sale(env, total=100)
            pay_customer(env, venta.id, 30)
            snap = cxc(env).obtener_saldo_venta(venta.id)
            self.assertEqual(snap["monto_pagado"], Decimal("30.00"))
            self.assertEqual(snap["saldo_pendiente"], Decimal("70.00"))
            self.assertEqual(snap["estado_pago"], "PARCIAL")
            pay_customer(env, venta.id, 70)
            snap = cxc(env).obtener_saldo_venta(venta.id)
            self.assertEqual(snap["saldo_pendiente"], Decimal("0.00"))
            self.assertEqual(snap["estado_pago"], "PAGADO")
            pendientes = [
                v for v in cxc(env).obtener_ventas_credito_pendientes() if v["saldo_pendiente"] > 0
            ]
            self.assertEqual(pendientes, [])

    def test_04_customer_payment_retry_exactly_once(self):
        with phase4b_env() as env:
            seed_ops(env)
            venta = credit_sale(env, total=100)
            lid = str(uuid.uuid4())
            first = pay_customer(env, venta.id, 40, local_id=lid)
            second = pay_customer(env, venta.id, 40, local_id=lid)
            self.assertEqual(first, second)
            snap = cxc(env).obtener_saldo_venta(venta.id)
            self.assertEqual(snap["monto_pagado"], Decimal("40.00"))
            self.assertEqual(snap["saldo_pendiente"], Decimal("60.00"))
            conn = env.connect()
            try:
                n = conn.execute(
                    "SELECT COUNT(*) FROM abonos_ventas WHERE id_venta=?", (venta.id,)
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(n, 1)

    def test_05_customer_overpayment_rejected(self):
        with phase4b_env() as env:
            seed_ops(env)
            venta = credit_sale(env, total=100)
            pay_customer(env, venta.id, 70)
            with self.assertRaises(PaymentError) as ctx:
                pay_customer(env, venta.id, 40)
            self.assertEqual(ctx.exception.code, PAYMENT_EXCEEDS_BALANCE)
            snap = cxc(env).obtener_saldo_venta(venta.id)
            self.assertEqual(snap["saldo_pendiente"], Decimal("30.00"))
            self.assertEqual(snap["credito_a_favor"], Decimal("0.00"))

    def test_06_customer_return_reduces_net_obligation(self):
        with phase4b_env() as env:
            seed_ops(env, stock=20)
            venta = credit_sale(env, total=10, cantidad=10)
            confirm_return(env, venta.id, KIND_CUSTOMER_RETURN, 3)
            snap = cxc(env).obtener_saldo_venta(venta.id)
            self.assertEqual(snap["original"], Decimal("100.00"))
            self.assertEqual(snap["reversals"], Decimal("30.00"))
            self.assertEqual(snap["net_obligation"], Decimal("70.00"))
            self.assertEqual(snap["saldo_pendiente"], Decimal("70.00"))

    def test_07_sale_void_reduces_obligation(self):
        with phase4b_env() as env:
            seed_ops(env)
            venta = credit_sale(env, total=100)
            confirm_return(env, venta.id, KIND_SALE_VOID, 1)
            snap = cxc(env).obtener_saldo_venta(venta.id)
            self.assertEqual(snap["net_obligation"], Decimal("0.00"))
            self.assertEqual(snap["saldo_pendiente"], Decimal("0.00"))

    def test_08_paid_then_return_exposes_credit_no_invented_cash(self):
        with phase4b_env() as env:
            seed_ops(env, stock=20)
            from tests.fase4b.helpers import open_caja, count_movements

            open_caja(env, Decimal("0"))
            venta = credit_sale(env, total=10, cantidad=10)
            pay_customer(env, venta.id, 100, "EFECTIVO")
            cash_before = count_movements(env)
            confirm_return(env, venta.id, KIND_CUSTOMER_RETURN, 3)
            snap = cxc(env).obtener_saldo_venta(venta.id)
            self.assertEqual(snap["net_obligation"], Decimal("70.00"))
            self.assertEqual(snap["credito_a_favor"], Decimal("30.00"))
            self.assertEqual(snap["credit_kind"], CUSTOMER_CREDIT)
            self.assertEqual(snap["saldo_pendiente"], Decimal("0.00"))
            conn = env.connect()
            try:
                drawer_in = conn.execute(
                    "SELECT COUNT(*) FROM cash_movements WHERE cash_effect_kind='DRAWER_IN'"
                ).fetchone()[0]
                drawer_out = conn.execute(
                    "SELECT COUNT(*) FROM cash_movements WHERE cash_effect_kind='DRAWER_OUT'"
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(drawer_in, 1)
            self.assertEqual(drawer_out, 0)
            self.assertGreaterEqual(count_movements(env), cash_before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
