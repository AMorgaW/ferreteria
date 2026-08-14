# -*- coding: utf-8 -*-
"""W03 VentasService.registrar_venta — 1E.1."""
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
    load_ops,
    transport_applied,
    transport_rejected,
    transport_unknown,
    ventas_service,
)


class W03LegacyTest(unittest.TestCase):
    def test_default_conserva_comportamiento_y_cutover_off(self):
        from inventory_gateway import INVENTORY_CUTOVER_ENABLED

        self.assertFalse(INVENTORY_CUTOVER_ENABLED)
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=50)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            ok, msg, venta = ventas_service(env).registrar_venta(
                items=[{"producto_id": 1, "cantidad": 5, "precio_unitario": 1000}],
            )
            self.assertTrue(ok, msg)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 45)
                self.assertEqual(count_mov(conn, "SALIDA_VENTA"), 1)
                self.assertEqual(command_count(conn), 0)
            finally:
                conn.close()

    def test_multilinea_insuficiente_no_crea_venta(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=2)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            ok, msg, venta = ventas_service(env).registrar_venta(
                items=[
                    {"producto_id": 1, "cantidad": 1, "precio_unitario": 1000},
                    {"producto_id": 1, "cantidad": 9, "precio_unitario": 1000},
                ],
            )
            self.assertFalse(ok)
            self.assertIsNone(venta)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 2)
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0], 0
                )
            finally:
                conn.close()


class W03AuthoritativeTest(unittest.TestCase):
    def _seed(self, env, *, stock=50, local_id=None, producto_id=1):
        conn = env.connect()
        try:
            lid = seed_producto(
                conn, env, stock=stock, local_id=local_id, producto_id=producto_id
            )
            insert_usuario(conn)
            conn.commit()
            return lid
        finally:
            conn.close()

    def test_construye_un_command_multilinea_fixed_point(self):
        with official_temp_db() as env:
            lid1 = self._seed(env, stock=50, producto_id=1)
            lid2 = str(uuid.uuid4())
            conn = env.connect()
            try:
                env.insert_producto(
                    conn,
                    producto_id=2,
                    stock=20,
                    local_id=lid2,
                    codigo="TEST-1E1-002",
                )
                conn.commit()
            finally:
                conn.close()
            cid = str(uuid.uuid4())
            transport = transport_applied()
            ok, msg, venta = ventas_service(env).registrar_venta(
                items=[
                    {"producto_id": 1, "cantidad": 2, "precio_unitario": 1000},
                    {"producto_id": 2, "cantidad": 1.5, "precio_unitario": 500},
                ],
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport,
            )
            self.assertTrue(ok, msg)
            self.assertEqual(len(transport.calls), 1)
            call = transport.calls[0]
            self.assertEqual(call["command_id"], cid)
            self.assertEqual(call["tipo"], "VENTA")
            self.assertEqual(len(call["operations"]), 2)
            ops = call["operations"]
            self.assertEqual(ops[0]["producto_local_id"], lid1)
            self.assertEqual(ops[1]["producto_local_id"], lid2)
            self.assertEqual(ops[0]["delta_scaled"], -2000)
            self.assertEqual(ops[1]["delta_scaled"], -1500)
            self.assertEqual([op["line_no"] for op in ops], [1, 2])
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn, 1), 50)
                self.assertEqual(stock_of(conn, 2), 20)
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0], 1
                )
                self.assertEqual(len(load_ops(conn, cid)), 2)
                self.assertEqual(command_count(conn, intent_class="AUTHORITATIVE"), 1)
            finally:
                conn.close()

    def test_retry_conserva_command_y_operation_ids(self):
        with official_temp_db() as env:
            self._seed(env)
            cid = str(uuid.uuid4())
            unknown = transport_unknown()
            svc = ventas_service(env)
            ok, msg, venta = svc.registrar_venta(
                items=[{"producto_id": 1, "cantidad": 3, "precio_unitario": 1000}],
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=unknown,
            )
            self.assertFalse(ok)
            self.assertIsNone(venta)
            self.assertIn("INVENTORY_UNKNOWN", msg)
            self.assertIn(cid, msg)
            first_ops = unknown.calls[0]["operations"]
            applied = transport_applied()
            ok2, msg2, venta2 = svc.registrar_venta(
                items=[{"producto_id": 1, "cantidad": 3, "precio_unitario": 1000}],
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=applied,
            )
            self.assertTrue(ok2, msg2)
            self.assertEqual(applied.calls[0]["command_id"], cid)
            self.assertEqual(
                [op["operation_id"] for op in applied.calls[0]["operations"]],
                [op["operation_id"] for op in first_ops],
            )
            conn = env.connect()
            try:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0], 1
                )
                self.assertEqual(command_count(conn), 1)
            finally:
                conn.close()

    def test_rejected_no_exito_comercial(self):
        with official_temp_db() as env:
            self._seed(env)
            ok, msg, venta = ventas_service(env).registrar_venta(
                items=[{"producto_id": 1, "cantidad": 4, "precio_unitario": 1000}],
                inventory_mode="authoritative",
                inventory_transport=transport_rejected(),
            )
            self.assertFalse(ok)
            self.assertIsNone(venta)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 50)
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0], 0
                )
            finally:
                conn.close()

    def test_sin_local_id_no_llega_al_coordinador(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=50, local_id=str(uuid.uuid4()))
                conn.execute("UPDATE productos SET local_id = NULL WHERE id = 1")
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            calls = []
            ok, msg, venta = ventas_service(env).registrar_venta(
                items=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 1000}],
                inventory_mode="authoritative",
                inventory_transport=transport_applied(calls),
            )
            self.assertFalse(ok)
            self.assertIn("local_id", msg.lower())
            self.assertEqual(calls, [])

    def test_descuento_invalido_no_aplica_inventario(self):
        with official_temp_db() as env:
            self._seed(env)
            calls = []
            ok, msg, venta = ventas_service(env).registrar_venta(
                items=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 1000}],
                descuento_general=999999,
                inventory_mode="authoritative",
                inventory_transport=transport_applied(calls),
            )
            self.assertFalse(ok)
            self.assertIsNone(venta)
            self.assertIn("descuento", msg.lower())
            self.assertEqual(calls, [])
            conn = env.connect()
            try:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0], 0
                )
                self.assertEqual(command_count(conn), 0)
            finally:
                conn.close()

    def test_retry_applied_no_crea_segunda_venta(self):
        with official_temp_db() as env:
            self._seed(env)
            cid = str(uuid.uuid4())
            svc = ventas_service(env)
            ok1, msg1, venta1 = svc.registrar_venta(
                items=[{"producto_id": 1, "cantidad": 2, "precio_unitario": 1000}],
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport_applied(),
            )
            self.assertTrue(ok1, msg1)
            ok2, msg2, venta2 = svc.registrar_venta(
                items=[{"producto_id": 1, "cantidad": 2, "precio_unitario": 1000}],
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport_applied(),
            )
            self.assertTrue(ok2, msg2)
            self.assertEqual(venta1.id, venta2.id)
            conn = env.connect()
            try:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0], 1
                )
                self.assertEqual(command_count(conn), 1)
            finally:
                conn.close()

    def test_authoritative_method_no_update_stock(self):
        src = (REPO_ROOT / "services" / "ventas_service.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "_registrar_venta_authoritative"
            ):
                body = ast.get_source_segment(src, node) or ""
                self.assertNotIn("UPDATE productos SET", body)
                self.assertNotIn("stock = stock -", body)
                return
        self.fail("no está _registrar_venta_authoritative")
