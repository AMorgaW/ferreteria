# -*- coding: utf-8 -*-
"""Compatibilidad de pagos pre-cutover sin filas equivalentes de abono."""
from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from balance_schema import ensure_sqlite_operational_balance_schema
from tests.fase4b.helpers import (
    credit_purchase,
    credit_sale,
    cxc,
    cxp,
    pay_customer,
    pay_supplier,
    phase4b_env,
    seed_ops,
)


def _run_cutover(env) -> None:
    conn = env.connect()
    try:
        ensure_sqlite_operational_balance_schema(conn)
        conn.commit()
    finally:
        conn.close()


class LegacyPaymentCompatibilityTest(unittest.TestCase):
    def test_31_legacy_partially_paid_receivable(self):
        with phase4b_env() as env:
            seed_ops(env)
            venta = credit_sale(env, total=100)
            conn = env.connect()
            try:
                conn.execute(
                    "UPDATE ventas SET monto_pagado=40, estado_pago='PARCIAL' WHERE id=?",
                    (venta.id,),
                )
                conn.commit()
            finally:
                conn.close()
            _run_cutover(env)
            snap = cxc(env).obtener_saldo_venta(venta.id)
            self.assertEqual(snap["monto_pagado"], Decimal("40.00"))
            self.assertEqual(snap["saldo_pendiente"], Decimal("60.00"))

    def test_32_legacy_fully_paid_receivable(self):
        with phase4b_env() as env:
            seed_ops(env)
            venta = credit_sale(env, total=100)
            conn = env.connect()
            try:
                conn.execute(
                    "UPDATE ventas SET monto_pagado=100, estado_pago='PAGADO' WHERE id=?",
                    (venta.id,),
                )
                conn.commit()
            finally:
                conn.close()
            _run_cutover(env)
            snap = cxc(env).obtener_saldo_venta(venta.id)
            self.assertEqual(snap["monto_pagado"], Decimal("100.00"))
            self.assertEqual(snap["saldo_pendiente"], Decimal("0.00"))
            self.assertEqual(snap["estado_pago"], "PAGADO")

    def test_33_legacy_partially_paid_payable(self):
        with phase4b_env() as env:
            seed_ops(env, stock=0)
            compra_id = credit_purchase(env, total=100)
            conn = env.connect()
            try:
                conn.execute(
                    "UPDATE compras SET monto_pagado=35, saldo_pendiente=65, "
                    "estado_pago='PARCIAL' WHERE id=?",
                    (compra_id,),
                )
                conn.commit()
            finally:
                conn.close()
            _run_cutover(env)
            snap = cxp(env).obtener_saldo_compra(compra_id)
            self.assertEqual(snap["monto_pagado"], Decimal("35.00"))
            self.assertEqual(snap["saldo_pendiente"], Decimal("65.00"))

    def test_34_legacy_fully_paid_payable(self):
        with phase4b_env() as env:
            seed_ops(env, stock=0)
            compra_id = credit_purchase(env, total=100)
            conn = env.connect()
            try:
                conn.execute(
                    "UPDATE compras SET monto_pagado=100, saldo_pendiente=0, "
                    "estado_pago='PAGADO' WHERE id=?",
                    (compra_id,),
                )
                conn.commit()
            finally:
                conn.close()
            _run_cutover(env)
            snap = cxp(env).obtener_saldo_compra(compra_id)
            self.assertEqual(snap["monto_pagado"], Decimal("100.00"))
            self.assertEqual(snap["saldo_pendiente"], Decimal("0.00"))
            self.assertEqual(snap["estado_pago"], "PAGADO")

    def test_35_existing_abonos_are_not_double_counted_at_cutover(self):
        with phase4b_env() as env:
            seed_ops(env)
            venta = credit_sale(env, total=100)
            pay_customer(env, venta.id, 25)
            _run_cutover(env)
            snap = cxc(env).obtener_saldo_venta(venta.id)
            self.assertEqual(snap["monto_pagado"], Decimal("25.00"))
            self.assertEqual(snap["saldo_pendiente"], Decimal("75.00"))
            conn = env.connect()
            try:
                baseline = conn.execute(
                    "SELECT COUNT(*) FROM operational_balance_legacy_payments "
                    "WHERE document_tipo='venta' AND document_id=?",
                    (venta.id,),
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(baseline, 0)

    def test_36_baseline_is_stable_and_new_payments_accumulate(self):
        with phase4b_env() as env:
            seed_ops(env)
            venta = credit_sale(env, total=100)
            conn = env.connect()
            try:
                conn.execute(
                    "UPDATE ventas SET monto_pagado=40, estado_pago='PARCIAL' WHERE id=?",
                    (venta.id,),
                )
                conn.commit()
            finally:
                conn.close()
            _run_cutover(env)

            conn = env.connect()
            try:
                conn.execute("UPDATE ventas SET monto_pagado=99 WHERE id=?", (venta.id,))
                conn.commit()
            finally:
                conn.close()
            self.assertEqual(
                cxc(env).obtener_saldo_venta(venta.id)["monto_pagado"],
                Decimal("40.00"),
            )

            pay_customer(env, venta.id, 10)
            snap = cxc(env).obtener_saldo_venta(venta.id)
            self.assertEqual(snap["monto_pagado"], Decimal("50.00"))
            self.assertEqual(snap["saldo_pendiente"], Decimal("50.00"))

    def test_37_new_payment_writers_persist_uuid_unique_identity(self):
        with phase4b_env() as env:
            seed_ops(env, stock=0)
            venta = credit_sale(env, total=100)
            compra_id = credit_purchase(env, total=100)
            pay_customer(env, venta.id, 10)
            pay_supplier(env, compra_id, 10)
            conn = env.connect()
            try:
                venta_local_id = conn.execute(
                    "SELECT local_id FROM abonos_ventas WHERE id_venta=?", (venta.id,)
                ).fetchone()[0]
                compra_local_id = conn.execute(
                    "SELECT local_id FROM abonos_compras WHERE id_compra=?", (compra_id,)
                ).fetchone()[0]
                venta_indexes = conn.execute(
                    "PRAGMA index_list('abonos_ventas')"
                ).fetchall()
                compra_indexes = conn.execute(
                    "PRAGMA index_list('abonos_compras')"
                ).fetchall()
            finally:
                conn.close()
            import uuid

            self.assertEqual(str(uuid.UUID(venta_local_id)), venta_local_id)
            self.assertEqual(str(uuid.UUID(compra_local_id)), compra_local_id)
            self.assertTrue(any(row[1] == "idx_abonos_ventas_local_id" and row[2] for row in venta_indexes))
            self.assertTrue(any(row[1] == "idx_abonos_compras_local_id" and row[2] for row in compra_indexes))

    def test_38_migration_010_captures_legacy_and_is_rerunnable(self):
        from migration_runner import default_runner

        with phase4b_env() as env:
            seed_ops(env, stock=0)
            venta = credit_sale(env, total=100)
            compra_id = credit_purchase(env, total=100)
            conn = env.connect()
            try:
                conn.execute("UPDATE ventas SET monto_pagado=20 WHERE id=?", (venta.id,))
                conn.execute(
                    "UPDATE compras SET monto_pagado=30, saldo_pendiente=70 WHERE id=?",
                    (compra_id,),
                )
                # El harness nace ya migrado; rebobinar solo la 010 en esta DB
                # temporal representa el estado legacy inmediatamente pre-cutover.
                conn.execute(
                    "DELETE FROM schema_migrations WHERE version='20260816_010'"
                )
                conn.execute("DROP TABLE operational_balance_legacy_payments")
                conn.commit()
                first = default_runner().run(conn, dry_run=False)
                second = default_runner().run(conn, dry_run=False)
                captured = conn.execute(
                    "SELECT document_tipo, amount FROM operational_balance_legacy_payments "
                    "ORDER BY document_tipo"
                ).fetchall()
            finally:
                conn.close()
            self.assertTrue(any(item.version == "20260816_010" for item in first))
            self.assertTrue(all(item.status == "SKIPPED_APPLIED" for item in second))
            self.assertEqual(
                [(row[0], Decimal(str(row[1]))) for row in captured],
                [("compra", Decimal("30")), ("venta", Decimal("20"))],
            )

    def test_39_payable_projection_reconciliation(self):
        with phase4b_env() as env:
            seed_ops(env, stock=0)
            compra_id = credit_purchase(env, total=100)
            pay_supplier(env, compra_id, 25)
            conn = env.connect()
            try:
                conn.execute(
                    "UPDATE compras SET monto_pagado=99, saldo_pendiente=1 WHERE id=?",
                    (compra_id,),
                )
                conn.commit()
            finally:
                conn.close()
            canonical = cxp(env).obtener_saldo_compra(compra_id)
            self.assertEqual(canonical["monto_pagado"], Decimal("25.00"))
            self.assertEqual(canonical["saldo_pendiente"], Decimal("75.00"))
            self.assertTrue(canonical["projection_stale"])
            fixed = cxp(env).reconciliar_compra(compra_id)
            self.assertEqual(fixed["monto_pagado"], Decimal("25.00"))
            self.assertEqual(fixed["saldo_pendiente"], Decimal("75.00"))

    def test_40_uncompleted_document_has_no_canonical_payable(self):
        with phase4b_env() as env:
            seed_ops(env, stock=0)
            compra_id = credit_purchase(env, total=100)
            conn = env.connect()
            try:
                conn.execute("UPDATE compras SET estado='DRAFT' WHERE id=?", (compra_id,))
                conn.commit()
            finally:
                conn.close()
            self.assertIsNone(cxp(env).obtener_saldo_compra(compra_id))


if __name__ == "__main__":
    unittest.main(verbosity=2)
