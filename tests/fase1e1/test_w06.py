# -*- coding: utf-8 -*-
"""W06 VentasService.agregar_productos_a_factura — 1E.1."""
from __future__ import annotations

import ast
import sys
import unittest
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase0.harness import official_temp_db
from tests.fase1e.helpers import insert_usuario, seed_producto, stock_of, count_mov
from tests.fase1e1.helpers import (
    command_count,
    transport_applied,
    transport_rejected,
    ventas_service,
)


class W06LegacyTest(unittest.TestCase):
    def test_legacy_sin_stock_ge_conservado(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=15)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = ventas_service(env)
            ok, msg, venta = svc.registrar_venta(
                items=[{"producto_id": 1, "cantidad": 2, "precio_unitario": 1000}],
                metodo_pago="CREDITO",
            )
            self.assertTrue(ok, msg)
            ok2, msg2 = svc.agregar_productos_a_factura(
                venta.id,
                [{"producto_id": 1, "cantidad": 3, "precio_unitario": 1000}],
            )
            self.assertTrue(ok2, msg2)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 10)
                self.assertEqual(count_mov(conn, "SALIDA_VENTA"), 2)
                self.assertEqual(command_count(conn), 0)
            finally:
                conn.close()


class W06AuthoritativeTest(unittest.TestCase):
    def test_coordinador_decide_insuficiencia(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=15)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = ventas_service(env)
            ok, msg, venta = svc.registrar_venta(
                items=[{"producto_id": 1, "cantidad": 2, "precio_unitario": 1000}],
                metodo_pago="CREDITO",
            )
            self.assertTrue(ok, msg)
            ok2, msg2 = svc.agregar_productos_a_factura(
                venta.id,
                [{"producto_id": 1, "cantidad": 3, "precio_unitario": 1000}],
                inventory_mode="authoritative",
                inventory_transport=transport_rejected("INSUFFICIENT_STOCK"),
            )
            self.assertFalse(ok2)
            self.assertIn("INSUFFICIENT_STOCK", msg2)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 13)
                self.assertEqual(count_mov(conn, "SALIDA_VENTA"), 1)
            finally:
                conn.close()

    def test_applied_sin_dual_write(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = seed_producto(conn, env, stock=15)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = ventas_service(env)
            ok, msg, venta = svc.registrar_venta(
                items=[{"producto_id": 1, "cantidad": 2, "precio_unitario": 1000}],
                metodo_pago="CREDITO",
            )
            self.assertTrue(ok, msg)
            cid = str(uuid.uuid4())
            transport = transport_applied()
            ok2, msg2 = svc.agregar_productos_a_factura(
                venta.id,
                [{"producto_id": 1, "cantidad": 3, "precio_unitario": 1000}],
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport,
            )
            self.assertTrue(ok2, msg2)
            self.assertEqual(transport.calls[0]["tipo"], "VENTA")
            self.assertEqual(
                transport.calls[0]["operations"][0]["producto_local_id"], lid
            )
            self.assertEqual(
                transport.calls[0]["operations"][0]["delta_scaled"], -3000
            )
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 13)
                self.assertEqual(count_mov(conn, "SALIDA_VENTA"), 2)
            finally:
                conn.close()

    def test_authoritative_no_update_stock(self):
        src = (REPO_ROOT / "services" / "ventas_service.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "_agregar_productos_a_factura_authoritative"
            ):
                body = ast.get_source_segment(src, node) or ""
                self.assertNotIn("stock = stock -", body)
                return
        self.fail("no está _agregar_productos_a_factura_authoritative")
