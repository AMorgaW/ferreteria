# -*- coding: utf-8 -*-
"""Checkout POS: stock, atomicidad, idempotencia y recovery. Writer existente."""
from __future__ import annotations

import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.pos_cart import PosCart, format_min_receipt
from tests.fase0.harness import official_temp_db
from tests.fase1e.helpers import insert_usuario, seed_producto, stock_of
from tests.fase1e1.helpers import (
    command_count,
    load_ops,
    transport_applied,
    transport_rejected,
    transport_unknown,
    ventas_service,
)
from tests.fase3a.helpers import assert_not_commercial_db


class PosCheckoutTest(unittest.TestCase):
    def test_10_insufficient_stock_rejects_without_partial_sale(self):
        with official_temp_db() as env:
            assert_not_commercial_db(env)
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=5)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = ventas_service(env)
            ok, msg, venta = svc.registrar_venta(
                items=[{"producto_id": 1, "cantidad": 7, "precio_unitario": 1000}],
            )
            self.assertFalse(ok)
            self.assertIsNone(venta)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 5)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0], 0)
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM detalle_ventas").fetchone()[0], 0
                )
            finally:
                conn.close()
            self.assertIn("insuficiente", msg.lower())

    def test_10b_authoritative_insufficient_does_not_insert_sale(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=5)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = ventas_service(env)
            ok, _msg, venta = svc.registrar_venta(
                items=[{"producto_id": 1, "cantidad": 7, "precio_unitario": 1000}],
                inventory_mode="authoritative",
                inventory_command_id=str(uuid.uuid4()),
                inventory_transport=transport_rejected(),
            )
            self.assertFalse(ok)
            self.assertIsNone(venta)
            conn = env.connect()
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0], 0)
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM detalle_ventas").fetchone()[0], 0
                )
            finally:
                conn.close()

    def test_11_exact_decrement(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = ventas_service(env)
            command_id = str(uuid.uuid4())
            ok, msg, venta = svc.registrar_venta(
                items=[{"producto_id": 1, "cantidad": 3, "precio_unitario": 1000}],
                inventory_mode="authoritative",
                inventory_command_id=command_id,
                inventory_transport=transport_applied(),
            )
            self.assertTrue(ok, msg)
            self.assertIsNotNone(venta)
            conn = env.connect()
            try:
                ops = load_ops(conn, command_id)
                self.assertEqual(len(ops), 1)
                self.assertEqual(int(ops[0]["delta_scaled"]), -3000)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0], 1)
            finally:
                conn.close()

    def test_12_multi_line_atomicity(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10, producto_id=1)
                env.insert_producto(
                    conn,
                    producto_id=2,
                    nombre="Producto B",
                    stock=10,
                    codigo="PROD-B",
                    precio_venta=1000,
                    local_id=str(uuid.uuid4()),
                )
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = ventas_service(env)
            ok, _msg, venta = svc.registrar_venta(
                items=[
                    {"producto_id": 1, "cantidad": 1, "precio_unitario": 1000},
                    {"producto_id": 2, "cantidad": 1, "precio_unitario": 1000},
                ],
                inventory_mode="authoritative",
                inventory_command_id=str(uuid.uuid4()),
                inventory_transport=transport_rejected("INSUFFICIENT_STOCK"),
            )
            self.assertFalse(ok)
            self.assertIsNone(venta)
            conn = env.connect()
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0], 0)
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM detalle_ventas").fetchone()[0], 0
                )
                self.assertEqual(stock_of(conn, 1), 10)
                self.assertEqual(stock_of(conn, 2), 10)
            finally:
                conn.close()

    def test_13_idempotent_retry_one_sale_one_inventory_effect(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = ventas_service(env)
            command_id = str(uuid.uuid4())
            items = [{"producto_id": 1, "cantidad": 1, "precio_unitario": 1000}]
            transport = transport_applied()
            ok1, msg1, venta1 = svc.registrar_venta(
                items=items,
                inventory_mode="authoritative",
                inventory_command_id=command_id,
                inventory_transport=transport,
            )
            self.assertTrue(ok1, msg1)
            ok2, msg2, venta2 = svc.registrar_venta(
                items=items,
                inventory_mode="authoritative",
                inventory_command_id=command_id,
                inventory_transport=transport,
            )
            self.assertTrue(ok2, msg2)
            self.assertEqual(venta1.id, venta2.id)
            conn = env.connect()
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0], 1)
                self.assertEqual(command_count(conn), 1)
                ops = load_ops(conn, command_id)
                self.assertEqual(len(ops), 1)
                self.assertEqual(int(ops[0]["delta_scaled"]), -1000)
            finally:
                conn.close()

    def test_14_duplicate_confirm_protection_on_cart(self):
        cart = PosCart()
        cart.lines.append(
            {
                "producto": {"id": 1, "nombre": "X", "precio_venta": 1000},
                "cantidad": Decimal("1"),
                "precio_unitario": Decimal("1000"),
                "descuento": Decimal("0"),
            }
        )
        self.assertTrue(cart.begin_checkout())
        self.assertFalse(cart.begin_checkout())
        cart.end_checkout()
        self.assertTrue(cart.begin_checkout())

    def test_19_unknown_retry_reuses_command_id(self):
        from inventory_cutover import ACT_KIND_POS_CHECKOUT, begin_or_resume_open_act

        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = ventas_service(env)
            transport = transport_unknown()
            ok, msg, venta = svc.registrar_venta(
                items=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 1000}],
                inventory_mode="authoritative",
                inventory_transport=transport,
            )
            self.assertFalse(ok)
            self.assertIsNone(venta)
            self.assertIn("INVENTORY_UNKNOWN", msg)
            cid = svc.last_inventory_command_id
            conn = env.connect()
            try:
                resumed = begin_or_resume_open_act(conn, ACT_KIND_POS_CHECKOUT)
            finally:
                conn.close()
            self.assertEqual(resumed, cid)
            svc2 = ventas_service(env)
            ok2, msg2, venta2 = svc2.registrar_venta(
                items=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 1000}],
                inventory_mode="authoritative",
                inventory_transport=transport,
            )
            self.assertFalse(ok2)
            self.assertEqual(svc2.last_inventory_command_id, cid)
            conn = env.connect()
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0], 0)
                self.assertEqual(command_count(conn), 1)
            finally:
                conn.close()

    def test_comprobante_minimo(self):
        text = format_min_receipt(
            sale_id=9,
            fecha="2026-08-16 09:00",
            numero_factura="20260816-0001",
            lines=[
                {
                    "producto_nombre": "Tornillo",
                    "cantidad": 2,
                    "precio_unitario": 1000,
                    "subtotal": 2000,
                }
            ],
            total=2000,
        )
        self.assertIn("sale_id: 9", text)
        self.assertIn("Tornillo", text)
        self.assertIn("total: 2000", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
