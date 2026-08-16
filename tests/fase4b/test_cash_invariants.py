# -*- coding: utf-8 -*-
"""Caja, Decimal, carrera local, aging, local-first, UI, DB comercial."""
from __future__ import annotations

import inspect
import sys
import threading
import unittest
import uuid
from decimal import Decimal
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.caja_service import money
from services.operational_balance import PAYMENT_EXCEEDS_BALANCE, PaymentError
from tests.fase4a.helpers import assert_commercial_untouched, commercial_db_mtime
from tests.fase4b.helpers import (
    count_movements,
    credit_purchase,
    credit_sale,
    cxc,
    cxp,
    open_caja,
    pay_customer,
    pay_supplier,
    phase4b_env,
    seed_ops,
)


class CashDecimalConcurrencyTest(unittest.TestCase):
    def test_16_17_cash_and_noncash_customer_payment(self):
        with phase4b_env() as env:
            seed_ops(env, stock=20)
            svc = open_caja(env, Decimal("0"))
            venta = credit_sale(env, total=100)
            pay_customer(env, venta.id, 40, "EFECTIVO")
            self.assertEqual(svc.expected_cash(), Decimal("40.00"))
            self.assertEqual(count_movements(env, source_kind="abono_venta"), 1)
            pay_customer(env, venta.id, 30, "TRANSFERENCIA")
            self.assertEqual(svc.expected_cash(), Decimal("40.00"))
            self.assertEqual(count_movements(env, source_kind="abono_venta"), 2)
            conn = env.connect()
            try:
                effects = [
                    row[0]
                    for row in conn.execute(
                        "SELECT cash_effect_kind FROM cash_movements "
                        "WHERE source_kind='abono_venta' ORDER BY id"
                    )
                ]
            finally:
                conn.close()
            self.assertEqual(effects[0], "DRAWER_IN")
            self.assertEqual(effects[1], "INFORMATIONAL")

    def test_18_19_20_supplier_cash_noncash_no_legacy_double_count(self):
        with phase4b_env() as env:
            seed_ops(env, stock=0)
            svc = open_caja(env, Decimal("10000"))
            cid = credit_purchase(env, total=100)
            pay_supplier(env, cid, 40, "EFECTIVO")
            self.assertEqual(svc.expected_cash(), Decimal("9960.00"))
            self.assertEqual(count_movements(env, source_kind="abono_compra"), 1)
            pay_supplier(env, cid, 20, "TRANSFERENCIA")
            self.assertEqual(svc.expected_cash(), Decimal("9960.00"))
            from repositories.abonos_compras_repo import reconciliar_pagos_proveedor_huerfanos

            reconciliar_pagos_proveedor_huerfanos()
            self.assertEqual(count_movements(env, source_kind="abono_compra"), 2)
            self.assertEqual(svc.expected_cash(), Decimal("9960.00"))

    def test_21_decimal_exact_100_10_minus_30_20(self):
        self.assertEqual(money("100.10") - money("30.20"), money("69.90"))
        with phase4b_env() as env:
            seed_ops(env)
            venta = credit_sale(env, total=100.10)
            pay_customer(env, venta.id, "30.20")
            snap = cxc(env).obtener_saldo_venta(venta.id)
            self.assertEqual(snap["saldo_pendiente"], Decimal("69.90"))
            self.assertNotIn("69.899", str(snap["saldo_pendiente"]))

    def test_22_local_concurrent_final_payment_race(self):
        with phase4b_env() as env:
            seed_ops(env)
            venta = credit_sale(env, total=100)
            errors = []
            ids = []

            def _pay():
                try:
                    ids.append(pay_customer(env, venta.id, 100, local_id=str(uuid.uuid4())))
                except Exception as exc:
                    errors.append(exc)

            t1 = threading.Thread(target=_pay)
            t2 = threading.Thread(target=_pay)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
            self.assertEqual(len(ids), 1)
            self.assertTrue(
                any(isinstance(e, PaymentError) and e.code == PAYMENT_EXCEEDS_BALANCE for e in errors)
            )
            snap = cxc(env).obtener_saldo_venta(venta.id)
            self.assertEqual(snap["saldo_pendiente"], Decimal("0.00"))
            self.assertEqual(snap["monto_pagado"], Decimal("100.00"))
            conn = env.connect()
            try:
                n = conn.execute(
                    "SELECT COUNT(*) FROM abonos_ventas WHERE id_venta=?", (venta.id,)
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(n, 1)

    def test_23_restart_retry_balance_stable(self):
        with phase4b_env() as env:
            seed_ops(env)
            venta = credit_sale(env, total=100)
            lid = str(uuid.uuid4())
            pay_customer(env, venta.id, 55, local_id=lid)
            pay_customer(env, venta.id, 55, local_id=lid)
            snap = cxc(env).obtener_saldo_venta(venta.id)
            self.assertEqual(snap["saldo_pendiente"], Decimal("45.00"))

    def test_24_projection_reconciliation(self):
        with phase4b_env() as env:
            seed_ops(env)
            venta = credit_sale(env, total=100)
            pay_customer(env, venta.id, 25)
            conn = env.connect()
            try:
                conn.execute(
                    "UPDATE ventas SET monto_pagado=99 WHERE id=?", (venta.id,)
                )
                conn.commit()
            finally:
                conn.close()
            snap = cxc(env).obtener_saldo_venta(venta.id)
            self.assertEqual(snap["monto_pagado"], Decimal("25.00"))
            self.assertEqual(snap["saldo_pendiente"], Decimal("75.00"))
            self.assertTrue(snap["projection_stale"])
            fixed = cxc(env).reconciliar_venta(venta.id)
            self.assertEqual(fixed["monto_pagado"], Decimal("25.00"))
            conn = env.connect()
            try:
                projected = conn.execute(
                    "SELECT monto_pagado FROM ventas WHERE id=?", (venta.id,)
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(money(projected), Decimal("25.00"))

    def test_30_migration_010_idempotent(self):
        from migration_runner import default_runner

        with phase4b_env() as env:
            conn = env.connect()
            try:
                default_runner().run(conn, dry_run=False)
                second = default_runner().run(conn, dry_run=False)
                versions = [
                    row[0]
                    for row in conn.execute(
                        "SELECT version FROM schema_migrations ORDER BY version"
                    )
                ]
            finally:
                conn.close()
            self.assertIn("20260816_010", versions)
            self.assertTrue(all(item.status == "SKIPPED_APPLIED" for item in second))

    def test_25_26_aging_net_balance_excludes_paid(self):
        with phase4b_env() as env:
            seed_ops(env, stock=30)
            v_old = credit_sale(env, total=100)
            v_paid = credit_sale(env, total=50)
            pay_customer(env, v_paid.id, 50)
            conn = env.connect()
            try:
                conn.execute(
                    "UPDATE ventas SET fecha = datetime('now', '-95 days') WHERE id=?",
                    (v_old.id,),
                )
                conn.commit()
            finally:
                conn.close()
            confirm_partial = pay_customer(env, v_old.id, 40)
            self.assertTrue(confirm_partial)
            resumen = cxc(env).obtener_resumen_cuentas_por_cobrar()
            self.assertTrue(resumen)
            row = resumen[0]
            self.assertEqual(row["total_deuda"], Decimal("60.00"))
            self.assertEqual(row["aging_90_plus"], Decimal("60.00"))
            self.assertEqual(row["deuda_90"], Decimal("60.00"))
            pendientes_ids = {v["id"] for v in cxc(env).obtener_ventas_credito_pendientes() if v["saldo_pendiente"] > 0}
            self.assertIn(v_old.id, pendientes_ids)
            self.assertNotIn(v_paid.id, pendientes_ids)

    def test_27_local_first_no_remote(self):
        with phase4b_env() as env:
            seed_ops(env)
            credit_sale(env, total=80)

            def boom(*_a, **_k):
                raise AssertionError("network")

            with mock.patch("psycopg2.connect", side_effect=boom):
                snap = cxc(env).obtener_ventas_credito_pendientes()
                self.assertEqual(snap[0]["saldo_pendiente"], Decimal("80.00"))
                deudas = cxp(env).obtener_totales_deudas()
                self.assertEqual(deudas["total_deuda"], Decimal("0.00"))

    def test_28_ui_service_canonical_path(self):
        from repositories import abonos_compras_repo, abonos_ventas_repo
        from ui import dashboard_ui, compras_ui, ventas_ui_modern

        self.assertIn("operational_balance", inspect.getsource(abonos_ventas_repo.AbonosVentasRepository.crear_abono))
        self.assertIn("assert_payment_allowed", inspect.getsource(abonos_compras_repo.registrar_abono_compra_en_transaccion))
        dash = inspect.getsource(dashboard_ui)
        self.assertIn("obtener_ventas_credito_pendientes", dash)
        self.assertIn("crear_abono", dash)
        self.assertNotIn("INSERT INTO abonos_ventas", dash)
        ventas_src = inspect.getsource(ventas_ui_modern)
        self.assertIn("self.abonos_repo.crear_abono", ventas_src)
        compras_src = inspect.getsource(compras_ui)
        self.assertIn("self.abonos_repo.crear_abono", compras_src)
        self.assertIn("obtener_totales_deudas", compras_src)

    def test_29_commercial_db_untouched(self):
        before = commercial_db_mtime()
        with phase4b_env() as env:
            seed_ops(env)
            venta = credit_sale(env, total=10)
            pay_customer(env, venta.id, 10)
            cid = credit_purchase(env, total=10)
            pay_supplier(env, cid, 10)
            self.assertNotEqual(Path(env.db_path).resolve().name, "ferreteria.db")
        assert_commercial_untouched(before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
