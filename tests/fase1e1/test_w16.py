# -*- coding: utf-8 -*-
"""W16 LocalFerreteriaAPI.create_sale — 1E.1."""
from __future__ import annotations

import ast
import json
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
    lan_create_sale,
    load_ops,
    transport_applied,
    transport_rejected,
    transport_unknown,
)


class W16LegacyTest(unittest.TestCase):
    def test_default_lan_descuenta_sin_command(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=20)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            handler = lan_create_sale(
                env, [{"producto_id": 1, "cantidad": 3, "descuento": 0}]
            )
            self.assertEqual(handler.status, 201)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 17)
                self.assertEqual(count_mov(conn, "SALIDA_VENTA"), 1)
                self.assertEqual(command_count(conn), 0)
            finally:
                conn.close()

    def test_json_inventory_mode_no_activa_autoridad(self):
        import json
        from local_server import LocalFerreteriaAPI
        from tests.fase1e.helpers import FakeHTTPHandler, insert_usuario, seed_producto, stock_of

        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=20)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            body = json.dumps(
                {
                    "items": [{"producto_id": 1, "cantidad": 2, "descuento": 0}],
                    "metodo_pago": "EFECTIVO",
                    "inventory_mode": "authoritative",
                }
            ).encode("utf-8")
            handler = FakeHTTPHandler(env.db_path, body)
            LocalFerreteriaAPI.create_sale(handler, {"usuario_id": 1})
            self.assertEqual(handler.status, 201)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 18)
                self.assertEqual(command_count(conn), 0)
            finally:
                conn.close()


class W16AuthoritativeTest(unittest.TestCase):
    def test_mismo_contrato_que_w03(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = seed_producto(conn, env, stock=20)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            cid = str(uuid.uuid4())
            transport = transport_applied()
            handler = lan_create_sale(
                env,
                [
                    {"producto_id": 1, "cantidad": 2, "descuento": 0},
                    {"producto_id": 1, "cantidad": 1, "descuento": 0},
                ],
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport,
            )
            self.assertEqual(handler.status, 201, handler.wfile.getvalue())
            self.assertEqual(len(transport.calls), 1)
            call = transport.calls[0]
            self.assertEqual(call["command_id"], cid)
            self.assertEqual(call["tipo"], "VENTA")
            self.assertEqual(len(call["operations"]), 2)
            self.assertEqual(call["operations"][0]["producto_local_id"], lid)
            self.assertEqual(call["operations"][0]["delta_scaled"], -2000)
            self.assertEqual(call["operations"][1]["delta_scaled"], -1000)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 20)
                self.assertEqual(len(load_ops(conn, cid)), 2)
                self.assertEqual(command_count(conn), 1)
            finally:
                conn.close()

    def test_rejected_no_crea_venta(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=20)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            handler = lan_create_sale(
                env,
                [{"producto_id": 1, "cantidad": 2, "descuento": 0}],
                inventory_mode="authoritative",
                inventory_transport=transport_rejected(),
            )
            self.assertEqual(handler.status, 409)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 20)
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0], 0
                )
            finally:
                conn.close()

    def test_unknown_conserva_identidad(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=20)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            cid = str(uuid.uuid4())
            handler = lan_create_sale(
                env,
                [{"producto_id": 1, "cantidad": 2, "descuento": 0}],
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport_unknown(),
            )
            self.assertEqual(handler.status, 503)
            payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
            self.assertEqual(payload.get("command_id"), cid)
            self.assertTrue(payload.get("retryable"))
            conn = env.connect()
            try:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0], 0
                )
                self.assertEqual(command_count(conn), 1)
            finally:
                conn.close()

    def test_descuento_invalido_no_aplica_inventario(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=20)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            body = json.dumps(
                {
                    "items": [{"producto_id": 1, "cantidad": 2, "descuento": 0}],
                    "metodo_pago": "EFECTIVO",
                    "descuento": 999999,
                }
            ).encode("utf-8")
            from local_server import LocalFerreteriaAPI
            from tests.fase1e.helpers import FakeHTTPHandler

            calls = []
            handler = FakeHTTPHandler(env.db_path, body)
            LocalFerreteriaAPI.create_sale(
                handler,
                {"usuario_id": 1},
                inventory_mode="authoritative",
                inventory_transport=transport_applied(calls),
            )
            self.assertEqual(handler.status, 400)
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
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=20)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            cid = str(uuid.uuid4())
            first = lan_create_sale(
                env,
                [{"producto_id": 1, "cantidad": 2, "descuento": 0}],
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport_applied(),
            )
            self.assertEqual(first.status, 201, first.wfile.getvalue())
            second = lan_create_sale(
                env,
                [{"producto_id": 1, "cantidad": 2, "descuento": 0}],
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport_applied(),
            )
            self.assertEqual(second.status, 201, second.wfile.getvalue())
            conn = env.connect()
            try:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0], 1
                )
                self.assertEqual(command_count(conn), 1)
            finally:
                conn.close()

    def test_authoritative_no_update_stock(self):
        src = (REPO_ROOT / "local_server.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "_create_sale_authoritative"
            ):
                body = ast.get_source_segment(src, node) or ""
                self.assertNotIn("stock = stock -", body)
                return
        self.fail("no está _create_sale_authoritative")

    def test_comparte_builder_con_w03(self):
        w03 = (REPO_ROOT / "services" / "ventas_service.py").read_text(
            encoding="utf-8"
        )
        w16 = (REPO_ROOT / "local_server.py").read_text(encoding="utf-8")
        self.assertIn("build_negative_operations", w03)
        self.assertIn("build_negative_operations", w16)
