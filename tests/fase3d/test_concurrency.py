# -*- coding: utf-8 -*-
"""Concurrencia cierre vs movimiento y local-first 3D."""
from __future__ import annotations

import sys
import threading
import unittest
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase1e.helpers import insert_usuario
from tests.fase3d.helpers import (
    assert_not_commercial_db,
    caja_service,
    complete_sale_cash,
    count_movements,
    open_caja,
    phase3d_env,
    seed_pos_product,
)


class CashConcurrencyTest(unittest.TestCase):
    def test_23_operation_vs_close_race(self):
        with phase3d_env() as env:
            conn = env.connect()
            try:
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            seed_pos_product(env, stock=20, precio_venta=100)
            svc = open_caja(env, Decimal("0"))
            session_id = svc.obtener_caja_abierta()["id"]
            errors = []
            sale_result = {}

            def sell():
                try:
                    from tests.fase1e1.helpers import transport_applied
                    from tests.fase3d.helpers import pos_service
                    import uuid

                    sale_result["value"] = pos_service(env).registrar_venta(
                        items=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 100}],
                        metodo_pago="EFECTIVO",
                        inventory_mode="authoritative",
                        inventory_command_id=str(uuid.uuid4()),
                        inventory_transport=transport_applied(),
                    )
                except Exception as exc:
                    errors.append(exc)

            def close():
                try:
                    caja_service(env).cerrar_caja(Decimal("0"))
                except Exception as exc:
                    errors.append(exc)

            t_sale = threading.Thread(target=sell)
            t_close = threading.Thread(target=close)
            t_sale.start()
            t_close.start()
            t_sale.join(5)
            t_close.join(5)
            self.assertFalse(errors)
            self.assertFalse(t_sale.is_alive())
            self.assertFalse(t_close.is_alive())
            sale_ok, sale_message, _sale = sale_result["value"]
            if not sale_ok:
                self.assertTrue(
                    "NO_OPEN_SESSION" in sale_message
                    or "INVENTORY_UNKNOWN" in sale_message,
                    sale_message,
                )
            conn = env.connect()
            try:
                session = dict(
                    conn.execute(
                        "SELECT * FROM cierres_caja WHERE id=?", (session_id,)
                    ).fetchone()
                )
                open_now = conn.execute(
                    "SELECT COUNT(*) FROM cierres_caja WHERE station_id='W01' "
                    "AND fecha_cierre IS NULL"
                ).fetchone()[0]
                movements = list(
                    conn.execute(
                        "SELECT * FROM cash_movements WHERE cash_session_id=?",
                        (session_id,),
                    )
                )
                expected_from_ledger = Decimal(str(session["monto_inicial"] or 0))
                for movement in movements:
                    amount = Decimal(str(movement["amount"]))
                    if movement["cash_effect_kind"] == "DRAWER_IN":
                        expected_from_ledger += amount
                    elif movement["cash_effect_kind"] == "DRAWER_OUT":
                        expected_from_ledger -= amount
            finally:
                conn.close()
            self.assertEqual(open_now, 0)
            self.assertIsNotNone(session["fecha_cierre"])
            self.assertEqual(session["estado"], "CLOSED")
            self.assertEqual(
                Decimal(str(session["monto_esperado"])), expected_from_ledger
            )
            for row in movements:
                self.assertEqual(row["cash_session_id"], session_id)

    def test_26_local_first_offline_open(self):
        with phase3d_env() as env:
            conn = env.connect()
            try:
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            from unittest import mock

            with mock.patch("psycopg2.connect", side_effect=AssertionError("network")):
                svc = open_caja(env, Decimal("50"))
                self.assertIsNotNone(svc.obtener_caja_abierta())
                self.assertEqual(svc.expected_cash(), Decimal("50.00"))

    def test_simultaneous_double_close_keeps_first_snapshot(self):
        with phase3d_env() as env:
            conn = env.connect()
            try:
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = open_caja(env, Decimal("100"))
            session_id = svc.obtener_caja_abierta()["id"]
            barrier = threading.Barrier(3)
            results = []

            def close(amount, note):
                barrier.wait()
                results.append((amount, caja_service(env).cerrar_caja(amount, note)))

            first = threading.Thread(target=close, args=(Decimal("100"), "first"))
            second = threading.Thread(target=close, args=(Decimal("999"), "second"))
            first.start()
            second.start()
            barrier.wait()
            first.join(5)
            second.join(5)
            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertEqual(sum(1 for _amount, result in results if result[0]), 1)

            winner_amount = next(amount for amount, result in results if result[0])
            conn = env.connect()
            try:
                before = dict(
                    conn.execute(
                        "SELECT fecha_cierre, monto_esperado, monto_real, "
                        "diferencia, observaciones FROM cierres_caja WHERE id=?",
                        (session_id,),
                    ).fetchone()
                )
            finally:
                conn.close()
            self.assertEqual(Decimal(str(before["monto_real"])), winner_amount)
            self.assertFalse(svc.cerrar_caja(Decimal("1"), "overwrite")[0])
            conn = env.connect()
            try:
                after = dict(
                    conn.execute(
                        "SELECT fecha_cierre, monto_esperado, monto_real, "
                        "diferencia, observaciones FROM cierres_caja WHERE id=?",
                        (session_id,),
                    ).fetchone()
                )
            finally:
                conn.close()
            self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
