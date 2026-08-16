# -*- coding: utf-8 -*-
"""Fence operacional W01/W02: writer paga, no-writer lee y no finaliza."""
from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.operational_balance import FINANCIAL_WRITER_FENCE, PaymentError
from tests.fase4d.helpers import (
    assert_commercial_untouched,
    commercial_db_mtime,
    credit_purchase,
    credit_sale,
    cxc,
    cxp,
    pay_customer,
    pay_supplier,
    phase4d_env,
    seed_cliente,
    seed_ops,
    station_context,
)


class FinancialWriterFenceTest(unittest.TestCase):
    def setUp(self):
        self._mtime = commercial_db_mtime()

    def tearDown(self):
        assert_commercial_untouched(self._mtime)

    def test_01_w01_designated_payment_pass(self):
        with phase4d_env() as env:
            seed_ops(env)
            cid = seed_cliente(env)
            venta = credit_sale(env, total=80, cliente_id=cid)
            compra_id = credit_purchase(env, total=50)
            with station_context(current="W01", writer="W01"):
                pay_customer(env, venta.id, 40)
                pay_supplier(env, compra_id, 20)
            snap = cxc(env).obtener_saldo_venta(venta.id)
            self.assertEqual(str(snap["saldo_pendiente"]), "40.00")
            pay = cxp(env).obtener_saldo_compra(compra_id)
            self.assertEqual(str(pay["saldo_pendiente"]), "30.00")

    def test_02_w02_payment_blocked(self):
        with phase4d_env() as env:
            seed_ops(env)
            cid = seed_cliente(env)
            venta = credit_sale(env, total=80, cliente_id=cid)
            compra_id = credit_purchase(env, total=50)
            with station_context(current="W02", writer="W01"):
                with self.assertRaises(PaymentError) as ctx:
                    pay_customer(env, venta.id, 10)
                self.assertEqual(ctx.exception.code, FINANCIAL_WRITER_FENCE)
                with self.assertRaises(PaymentError) as ctx2:
                    pay_supplier(env, compra_id, 10)
                self.assertEqual(ctx2.exception.code, FINANCIAL_WRITER_FENCE)
            snap = cxc(env).obtener_saldo_venta(venta.id)
            self.assertEqual(str(snap["monto_pagado"]), "0.00")
            pay = cxp(env).obtener_saldo_compra(compra_id)
            self.assertEqual(str(pay["monto_pagado"]), "0.00")

    def test_03_w02_balance_read_allowed(self):
        with phase4d_env() as env:
            seed_ops(env)
            cid = seed_cliente(env)
            venta = credit_sale(env, total=90, cliente_id=cid)
            with station_context(current="W01", writer="W01"):
                pay_customer(env, venta.id, 15)
            with station_context(current="W02", writer="W01"):
                snap = cxc(env).obtener_saldo_venta(venta.id)
                pendientes = cxc(env).obtener_ventas_credito_pendientes()
            self.assertEqual(str(snap["saldo_pendiente"]), "75.00")
            self.assertEqual(len(pendientes), 1)

    def test_gate_lives_in_repository_not_only_ui(self):
        from repositories import abonos_compras_repo, abonos_ventas_repo

        sales = inspect.getsource(abonos_ventas_repo.AbonosVentasRepository.crear_abono)
        purchases = inspect.getsource(
            abonos_compras_repo.registrar_abono_compra_en_transaccion
        )
        self.assertIn("assert_can_finalize_payment", sales)
        self.assertIn("assert_can_finalize_payment", purchases)
        ui_files = [
            REPO_ROOT / "ui" / "ventas_ui_modern.py",
            REPO_ROOT / "ui" / "compras_ui.py",
            REPO_ROOT / "ui" / "caja_ui.py",
            REPO_ROOT / "ui" / "clientes_ui.py",
            REPO_ROOT / "ui" / "dashboard_ui.py",
        ]
        for path in ui_files:
            src = path.read_text(encoding="utf-8")
            self.assertIn("PaymentError", src)
            self.assertIn("Pago no permitido", src)
