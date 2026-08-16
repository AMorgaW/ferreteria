# -*- coding: utf-8 -*-
"""Ledger de caja 3D: exactly-once, métodos, expected cash, medianoche."""
from __future__ import annotations

import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cash_schema import EFFECT_DRAWER_IN, EFFECT_DRAWER_OUT, EFFECT_INFORMATIONAL
from returns_schema import (
    KIND_CUSTOMER_RETURN,
    KIND_SUPPLIER_RETURN,
    ORIGINAL_TIPO_COMPRA,
    ORIGINAL_TIPO_VENTA,
)
from tests.fase1e.helpers import insert_usuario
from tests.fase1e1.helpers import transport_applied
from tests.fase3c.helpers import complete_receipt
from tests.fase3d.helpers import (
    assert_not_commercial_db,
    caja_service,
    complete_sale_cash,
    count_movements,
    money,
    open_caja,
    phase3d_env,
    pos_service,
    registrar_abono_cliente,
    registrar_abono_proveedor,
    returns_on,
    seed_pos_product,
)


class CashLedgerTest(unittest.TestCase):
    def _seed(self, env, stock=50, precio=1000):
        conn = env.connect()
        try:
            insert_usuario(conn)
            conn.commit()
        finally:
            conn.close()
        return seed_pos_product(env, stock=stock, precio_venta=precio)

    def test_04_decimal_money_exactness(self):
        self.assertEqual(money("0.1") + money("0.2"), money("0.3"))
        self.assertEqual(money(Decimal("0.10")) + money("0.20"), Decimal("0.30"))
        with phase3d_env() as env:
            self._seed(env, stock=10, precio=0.2)
            svc = open_caja(env, Decimal("0.10"))
            complete_sale_cash(
                env,
                [{"producto_id": 1, "cantidad": 1, "precio_unitario": 0.2}],
            )
            self.assertEqual(svc.expected_cash(), Decimal("0.30"))

    def test_05_cash_sale_one_in(self):
        with phase3d_env() as env:
            self._seed(env)
            svc = open_caja(env, Decimal("0"))
            complete_sale_cash(env)
            self.assertEqual(count_movements(env, source_kind="venta"), 1)
            self.assertEqual(svc.expected_cash(), Decimal("1000.00"))
            conn = env.connect()
            try:
                effect = conn.execute(
                    "SELECT cash_effect_kind FROM cash_movements WHERE source_kind='venta'"
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(effect, EFFECT_DRAWER_IN)

    def test_06_07_08_noncash_and_credit_drawer_zero(self):
        with phase3d_env() as env:
            self._seed(env, stock=30)
            svc = open_caja(env, Decimal("5000"))
            pos = pos_service(env)
            for method in ("TARJETA_DEBITO", "TRANSFERENCIA", "CREDITO"):
                ok, msg, _venta = pos.registrar_venta(
                    items=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 1000}],
                    metodo_pago=method,
                    inventory_mode="authoritative",
                    inventory_command_id=str(uuid.uuid4()),
                    inventory_transport=transport_applied(),
                )
                self.assertTrue(ok, msg)
            self.assertEqual(svc.expected_cash(), Decimal("5000.00"))
            conn = env.connect()
            try:
                effects = [
                    row[0]
                    for row in conn.execute(
                        "SELECT cash_effect_kind FROM cash_movements WHERE source_kind='venta'"
                    )
                ]
            finally:
                conn.close()
            self.assertEqual(effects, [EFFECT_INFORMATIONAL] * 3)

    def test_09_cash_customer_payment_in(self):
        with phase3d_env() as env:
            self._seed(env)
            svc = open_caja(env, Decimal("0"))
            pos = pos_service(env)
            ok, msg, venta = pos.registrar_venta(
                items=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 2000}],
                metodo_pago="CREDITO",
                inventory_mode="authoritative",
                inventory_command_id=str(uuid.uuid4()),
                inventory_transport=transport_applied(),
            )
            self.assertTrue(ok, msg)
            self.assertEqual(svc.expected_cash(), Decimal("0.00"))
            registrar_abono_cliente(env, venta.id, 500, "EFECTIVO")
            self.assertEqual(svc.expected_cash(), Decimal("500.00"))
            registrar_abono_cliente(env, venta.id, 500, "TRANSFERENCIA")
            self.assertEqual(svc.expected_cash(), Decimal("500.00"))

    def test_10_11_supplier_payment_one_out_no_double_count(self):
        with phase3d_env() as env:
            self._seed(env)
            conn = env.connect()
            try:
                if conn.execute("SELECT 1 FROM proveedores WHERE id=1").fetchone() is None:
                    env.insert_proveedor(conn)
                conn.commit()
            finally:
                conn.close()
            svc = open_caja(env, Decimal("10000"))
            compra_id = complete_receipt(
                env, [{"producto_id": 1, "cantidad": 10, "precio_unitario": 50}]
            )
            registrar_abono_proveedor(env, compra_id, 100, "EFECTIVO")
            self.assertEqual(svc.expected_cash(), Decimal("9900.00"))
            self.assertEqual(count_movements(env, source_kind="abono_compra"), 1)
            from repositories.abonos_compras_repo import reconciliar_pagos_proveedor_huerfanos

            reconciliar_pagos_proveedor_huerfanos()
            self.assertEqual(count_movements(env, source_kind="abono_compra"), 1)
            self.assertEqual(svc.expected_cash(), Decimal("9900.00"))

    def test_12_13_manual_expense_cash_and_noncash(self):
        with phase3d_env() as env:
            self._seed(env)
            svc = open_caja(env, Decimal("1000"))
            ok, msg, _ = svc.registrar_egreso(
                Decimal("100"), "Gasolina", "tanqueada", "EFECTIVO"
            )
            self.assertTrue(ok, msg)
            self.assertEqual(svc.expected_cash(), Decimal("900.00"))
            ok, msg, _ = svc.registrar_egreso(
                Decimal("50"), "Internet", "wifi", "TRANSFERENCIA"
            )
            self.assertTrue(ok, msg)
            self.assertEqual(svc.expected_cash(), Decimal("900.00"))

    def test_14_15_customer_cash_refund_retry(self):
        with phase3d_env() as env:
            self._seed(env)
            svc = open_caja(env, Decimal("0"))
            venta = complete_sale_cash(
                env, [{"producto_id": 1, "cantidad": 2, "precio_unitario": 1000}]
            )
            self.assertEqual(svc.expected_cash(), Decimal("2000.00"))
            rets = returns_on(env)
            ok, msg, rid = rets.guardar_borrador(
                kind=KIND_CUSTOMER_RETURN,
                original_tipo=ORIGINAL_TIPO_VENTA,
                original_id=venta.id,
                items=[{"producto_id": 1, "cantidad": 1}],
                motivo="cambio",
            )
            self.assertTrue(ok, msg)
            ok, msg, rid = rets.confirmar(
                rid,
                inventory_mode="authoritative",
                inventory_command_id=str(uuid.uuid4()),
                inventory_transport=transport_applied(),
                refund_method="EFECTIVO",
            )
            self.assertTrue(ok, msg)
            self.assertEqual(count_movements(env, source_kind="reversal"), 1)
            expected_after = svc.expected_cash()
            ok, msg, rid = rets.confirmar(
                rid,
                inventory_mode="authoritative",
                inventory_command_id=str(uuid.uuid4()),
                inventory_transport=transport_applied(),
                refund_method="EFECTIVO",
            )
            self.assertTrue(ok, msg)
            self.assertEqual(count_movements(env, source_kind="reversal"), 1)
            self.assertEqual(svc.expected_cash(), expected_after)
            self.assertEqual(expected_after, Decimal("1000.00"))

    def test_noncash_refund_and_supplier_return_do_not_change_drawer(self):
        with phase3d_env() as env:
            self._seed(env)
            svc = open_caja(env, Decimal("500"))
            venta = complete_sale_cash(env)
            rets = returns_on(env)
            ok, msg, customer_rid = rets.guardar_borrador(
                kind=KIND_CUSTOMER_RETURN,
                original_tipo=ORIGINAL_TIPO_VENTA,
                original_id=venta.id,
                items=[{"producto_id": 1, "cantidad": 1}],
            )
            self.assertTrue(ok, msg)
            ok, msg, _ = rets.confirmar(
                customer_rid,
                inventory_mode="authoritative",
                inventory_command_id=str(uuid.uuid4()),
                inventory_transport=transport_applied(),
                refund_method="TRANSFERENCIA",
            )
            self.assertTrue(ok, msg)
            self.assertEqual(svc.expected_cash(), Decimal("1500.00"))

            conn = env.connect()
            try:
                if conn.execute("SELECT 1 FROM proveedores WHERE id=1").fetchone() is None:
                    env.insert_proveedor(conn)
                conn.commit()
            finally:
                conn.close()
            compra_id = complete_receipt(
                env, [{"producto_id": 1, "cantidad": 2, "precio_unitario": 50}]
            )
            ok, msg, supplier_rid = rets.guardar_borrador(
                kind=KIND_SUPPLIER_RETURN,
                original_tipo=ORIGINAL_TIPO_COMPRA,
                original_id=compra_id,
                items=[{"producto_id": 1, "cantidad": 1}],
            )
            self.assertTrue(ok, msg)
            ok, msg, _ = rets.confirmar(
                supplier_rid,
                inventory_mode="authoritative",
                inventory_command_id=str(uuid.uuid4()),
                inventory_transport=transport_applied(),
            )
            self.assertTrue(ok, msg)
            self.assertEqual(svc.expected_cash(), Decimal("1500.00"))
            conn = env.connect()
            try:
                supplier_cash = conn.execute(
                    "SELECT COUNT(*) FROM cash_movements "
                    "WHERE source_kind='reversal' AND source_identity=("
                    "SELECT local_id FROM reversal_documents WHERE id=?)",
                    (supplier_rid,),
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(supplier_cash, 0)

    def test_16_opening_plus_in_minus_out(self):
        with phase3d_env() as env:
            self._seed(env, stock=20)
            svc = open_caja(env, Decimal("100"))
            complete_sale_cash(
                env, [{"producto_id": 1, "cantidad": 1, "precio_unitario": 40}]
            )
            svc.registrar_egreso(Decimal("15"), "Gasolina", "viaje", "EFECTIVO")
            self.assertEqual(svc.expected_cash(), Decimal("125.00"))

    def test_17_session_crosses_midnight(self):
        with phase3d_env() as env:
            self._seed(env, stock=20)
            svc = open_caja(env, Decimal("0"))
            session = svc.obtener_caja_abierta()
            v1 = complete_sale_cash(
                env, [{"producto_id": 1, "cantidad": 1, "precio_unitario": 100}]
            )
            v2 = complete_sale_cash(
                env, [{"producto_id": 1, "cantidad": 1, "precio_unitario": 200}]
            )
            conn = env.connect()
            try:
                conn.execute(
                    "UPDATE cierres_caja SET fecha_apertura=? WHERE id=?",
                    ("2026-08-16 23:50:00", session["id"]),
                )
                conn.execute(
                    "UPDATE ventas SET fecha=? WHERE id=?",
                    ("2026-08-16 23:55:00", v1.id),
                )
                conn.execute(
                    "UPDATE ventas SET fecha=? WHERE id=?",
                    ("2026-08-17 00:10:00", v2.id),
                )
                conn.commit()
            finally:
                conn.close()
            resumen = svc.obtener_resumen_sesion()
            self.assertEqual(resumen["cantidad_ventas"], 2)
            self.assertEqual(resumen["esperado"], Decimal("300.00"))
            self.assertEqual(count_movements(env, session["id"]), 2)

    def test_18_19_20_counted_difference(self):
        with phase3d_env() as env:
            self._seed(env)
            svc = open_caja(env, Decimal("100"))
            complete_sale_cash(
                env, [{"producto_id": 1, "cantidad": 1, "precio_unitario": 50}]
            )
            esperado = svc.expected_cash()
            self.assertEqual(esperado, Decimal("150.00"))
            ok, msg = svc.cerrar_caja(esperado)
            self.assertTrue(ok, msg)
            self.assertIn("CUADRA", msg)

            svc2 = open_caja(env, Decimal("100"), "W02")
            complete_sale_cash(
                env,
                [{"producto_id": 1, "cantidad": 1, "precio_unitario": 50}],
                station_id="W02",
            )
            ok, msg = svc2.cerrar_caja(Decimal("140"))
            self.assertTrue(ok, msg)
            self.assertIn("Faltante", msg)

            svc3 = open_caja(env, Decimal("100"), "W03")
            ok, msg = svc3.cerrar_caja(Decimal("125"))
            self.assertTrue(ok, msg)
            self.assertIn("Sobrante", msg)

    def test_25_retry_does_not_duplicate_sale_cash(self):
        with phase3d_env() as env:
            self._seed(env)
            open_caja(env, Decimal("0"))
            command_id = str(uuid.uuid4())
            kwargs = dict(
                items=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 800}],
                metodo_pago="EFECTIVO",
                inventory_mode="authoritative",
                inventory_command_id=command_id,
                inventory_transport=transport_applied(),
            )
            pos = pos_service(env)
            ok1, msg1, venta = pos.registrar_venta(**kwargs)
            self.assertTrue(ok1, msg1)
            ok2, msg2, _venta2 = pos.registrar_venta(**kwargs)
            self.assertTrue(ok2, msg2)
            self.assertEqual(count_movements(env, source_kind="venta"), 1)

    def test_sale_cash_recovery_uses_durable_identity(self):
        with phase3d_env() as env:
            self._seed(env)
            open_caja(env, Decimal("0"))
            venta = complete_sale_cash(env)
            conn = env.connect()
            try:
                venta_local_id = conn.execute(
                    "SELECT local_id FROM ventas WHERE id = ?", (venta.id,)
                ).fetchone()[0]
                conn.execute("DELETE FROM cash_movements WHERE source_kind='venta'")
                conn.commit()
            finally:
                conn.close()

            restarted = caja_service(env, "W01")
            self.assertEqual(restarted.expected_cash(), Decimal("1000.00"))
            conn = env.connect()
            try:
                rows = conn.execute(
                    "SELECT source_identity FROM cash_movements "
                    "WHERE source_kind='venta'"
                ).fetchall()
            finally:
                conn.close()
            self.assertEqual([row[0] for row in rows], [venta_local_id])
            self.assertNotEqual(venta_local_id, str(venta.id))

    def test_29_closed_session_rejects_new_movement(self):
        with phase3d_env() as env:
            self._seed(env)
            svc = open_caja(env, Decimal("10"))
            session_id = svc.obtener_caja_abierta()["id"]
            svc.cerrar_caja(Decimal("10"))
            before = count_movements(env, session_id)
            pos = pos_service(env)
            ok, msg, venta = pos.registrar_venta(
                items=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 1000}],
                metodo_pago="EFECTIVO",
                inventory_mode="authoritative",
                inventory_command_id=str(uuid.uuid4()),
                inventory_transport=transport_applied(),
            )
            self.assertTrue(ok, msg)
            self.assertIsNotNone(venta)
            self.assertEqual(count_movements(env, session_id), before)
            self.assertEqual(count_movements(env, source_kind="venta"), 1)
            conn = env.connect()
            try:
                pending_session = conn.execute(
                    "SELECT cash_session_id FROM cash_movements "
                    "WHERE source_kind='venta'"
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertIsNone(pending_session)
            next_session = open_caja(env, Decimal("0"), "W01")
            self.assertEqual(next_session.expected_cash(), Decimal("1000.00"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
