# -*- coding: utf-8 -*-
"""Writers positivos 1E.2: W01 W04 W05 W09 W18."""
from __future__ import annotations

import ast
import sys
import unittest
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from repositories.compras_repo import ComprasRepository
from repositories.productos_repo import ProductosRepository
from tests.fase0.harness import official_temp_db
from tests.fase1e.helpers import count_mov, insert_usuario, seed_producto, stock_of
from tests.fase1e2.helpers import (
    command_count,
    load_ops,
    make_producto,
    transport_applied,
    transport_rejected,
    transport_unknown,
    ventas_service,
)


class W01Test(unittest.TestCase):
    def test_legacy_default_sin_rpc(self):
        from inventory_gateway import INVENTORY_CUTOVER_ENABLED

        self.assertFalse(INVENTORY_CUTOVER_ENABLED)
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=1)
            finally:
                conn.close()
            ok, msg, cid = ComprasRepository(env.db).crear_compra(
                proveedor_id=1,
                productos=[
                    {"producto_id": 1, "cantidad": 2, "precio_unitario": 10},
                    {"producto_id": 1, "cantidad": 3, "precio_unitario": 10},
                ],
                numero_factura="FAC-W01-LEG",
            )
            self.assertTrue(ok, msg)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 6)
                self.assertEqual(count_mov(conn, "ENTRADA_COMPRA"), 2)
                self.assertEqual(command_count(conn), 0)
            finally:
                conn.close()

    def test_authoritative_multilinea_sin_dual_write(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = seed_producto(conn, env, stock=1)
            finally:
                conn.close()
            cid = str(uuid.uuid4())
            transport = transport_applied()
            ok, msg, compra_id = ComprasRepository(env.db).crear_compra(
                proveedor_id=1,
                productos=[
                    {"producto_id": 1, "cantidad": 2, "precio_unitario": 10},
                    {"producto_id": 1, "cantidad": 3, "precio_unitario": 10},
                ],
                numero_factura="FAC-W01-AUTH",
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport,
            )
            self.assertTrue(ok, msg)
            self.assertEqual(transport.calls[0]["tipo"], "COMPRA")
            self.assertEqual(
                [op["delta_scaled"] for op in transport.calls[0]["operations"]],
                [2000, 3000],
            )
            self.assertEqual(transport.calls[0]["operations"][0]["producto_local_id"], lid)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 1)
                self.assertEqual(count_mov(conn, "ENTRADA_COMPRA"), 2)
                self.assertEqual(len(load_ops(conn, cid)), 2)
            finally:
                conn.close()
            ok2, msg2, compra2 = ComprasRepository(env.db).crear_compra(
                proveedor_id=1,
                productos=[
                    {"producto_id": 1, "cantidad": 2, "precio_unitario": 10},
                    {"producto_id": 1, "cantidad": 3, "precio_unitario": 10},
                ],
                numero_factura="FAC-W01-AUTH",
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport,
            )
            self.assertTrue(ok2, msg2)
            self.assertEqual(compra_id, compra2)
            self.assertEqual(len(transport.calls), 1)
            conn = env.connect()
            try:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM compras").fetchone()[0], 1
                )
            finally:
                conn.close()

    def test_rejected_no_crea_compra(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=1)
            finally:
                conn.close()
            ok, msg, compra_id = ComprasRepository(env.db).crear_compra(
                proveedor_id=1,
                productos=[{"producto_id": 1, "cantidad": 2, "precio_unitario": 10}],
                inventory_mode="authoritative",
                inventory_transport=transport_rejected(),
            )
            self.assertFalse(ok)
            self.assertIsNone(compra_id)
            conn = env.connect()
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM compras").fetchone()[0], 0)
                self.assertEqual(stock_of(conn), 1)
            finally:
                conn.close()

    def test_unknown_conserva_command_id(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=1)
            finally:
                conn.close()
            cid = str(uuid.uuid4())
            repo = ComprasRepository(env.db)
            ok, msg, compra_id = repo.crear_compra(
                proveedor_id=1,
                productos=[{"producto_id": 1, "cantidad": 2, "precio_unitario": 10}],
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport_unknown(),
            )
            self.assertFalse(ok)
            self.assertIsNone(compra_id)
            self.assertIn("INVENTORY_UNKNOWN", msg)
            self.assertEqual(repo.last_inventory_command_id, cid)


class W04W05W18Test(unittest.TestCase):
    def test_w04_legacy_y_authoritative_idempotente(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = ventas_service(env)
            ok, msg, venta = svc.registrar_venta(
                items=[{"producto_id": 1, "cantidad": 2, "precio_unitario": 1000}],
            )
            self.assertTrue(ok, msg)
            ok2, msg2 = svc.cancelar_venta(venta.id, "test")
            self.assertTrue(ok2, msg2)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 10)
                self.assertEqual(command_count(conn), 0)
            finally:
                conn.close()
            ok, msg, venta2 = svc.registrar_venta(
                items=[{"producto_id": 1, "cantidad": 2, "precio_unitario": 1000}],
            )
            self.assertTrue(ok, msg)
            cid = str(uuid.uuid4())
            transport = transport_applied()
            ok3, msg3 = svc.cancelar_venta(
                venta2.id, "auth",
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport,
            )
            self.assertTrue(ok3, msg3)
            self.assertEqual(transport.calls[0]["tipo"], "DEVOLUCION")
            self.assertEqual(transport.calls[0]["operations"][0]["delta_scaled"], 2000)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 8)
            finally:
                conn.close()
            ok4, msg4 = svc.cancelar_venta(
                venta2.id, "auth",
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport,
            )
            self.assertTrue(ok4, msg4)
            self.assertEqual(len(transport.calls), 1)

    def test_w05_no_duplica_devolucion(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = ventas_service(env)
            ok, msg, venta = svc.registrar_venta(
                items=[{"producto_id": 1, "cantidad": 4, "precio_unitario": 1000}],
            )
            self.assertTrue(ok, msg)
            cid = str(uuid.uuid4())
            transport = transport_applied()
            ok2, msg2, dev_id = svc.registrar_devolucion(
                venta.id, [{"producto_id": 1, "cantidad": 2}],
                motivo="parcial",
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport,
            )
            self.assertTrue(ok2, msg2)
            self.assertEqual(transport.calls[0]["tipo"], "DEVOLUCION")
            ok3, msg3, dev2 = svc.registrar_devolucion(
                venta.id, [{"producto_id": 1, "cantidad": 2}],
                motivo="parcial",
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport,
            )
            self.assertTrue(ok3, msg3)
            self.assertEqual(dev_id, dev2)
            self.assertEqual(len(transport.calls), 1)
            conn = env.connect()
            try:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM devoluciones").fetchone()[0], 1
                )
                self.assertEqual(stock_of(conn), 6)
            finally:
                conn.close()

    def test_w18_legacy_y_authoritative(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
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
            conn = env.connect()
            try:
                det = conn.execute(
                    "SELECT id FROM detalle_ventas WHERE venta_id = ?", (venta.id,)
                ).fetchone()["id"]
            finally:
                conn.close()
            ok2, msg2 = svc.eliminar_linea_factura(venta.id, det)
            self.assertTrue(ok2, msg2)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 10)
                self.assertEqual(command_count(conn), 0)
            finally:
                conn.close()
            ok, msg, venta2 = svc.registrar_venta(
                items=[{"producto_id": 1, "cantidad": 2, "precio_unitario": 1000}],
                metodo_pago="CREDITO",
            )
            conn = env.connect()
            try:
                det2 = conn.execute(
                    "SELECT id FROM detalle_ventas WHERE venta_id = ?", (venta2.id,)
                ).fetchone()["id"]
            finally:
                conn.close()
            cid = str(uuid.uuid4())
            transport = transport_applied()
            ok3, msg3 = svc.eliminar_linea_factura(
                venta2.id, det2,
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport,
            )
            self.assertTrue(ok3, msg3)
            self.assertEqual(transport.calls[0]["tipo"], "DEVOLUCION")
            self.assertEqual(transport.calls[0]["operations"][0]["delta_scaled"], 2000)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 8)
            finally:
                conn.close()
            ok4, msg4 = svc.eliminar_linea_factura(
                venta2.id, det2,
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport,
            )
            self.assertTrue(ok4, msg4)
            self.assertEqual(len(transport.calls), 1)


class W09Test(unittest.TestCase):
    def test_stock_cero_no_command(self):
        with official_temp_db() as env:
            repo = ProductosRepository(env.db)
            transport = transport_applied()
            ok, msg, pid = repo.crear_producto(
                make_producto(nombre="Cero", stock=0),
                inventory_mode="authoritative",
                inventory_transport=transport,
            )
            self.assertTrue(ok, msg)
            self.assertEqual(transport.calls, [])
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn, pid), 0)
                self.assertEqual(command_count(conn), 0)
            finally:
                conn.close()

    def test_stock_inicial_positivo_sin_dual_write(self):
        with official_temp_db() as env:
            repo = ProductosRepository(env.db)
            cid = str(uuid.uuid4())
            lid = str(uuid.uuid4())
            transport = transport_applied()
            ok, msg, pid = repo.crear_producto(
                make_producto(nombre="Inicial", stock=5, marca="A"),
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport,
                producto_local_id=lid,
            )
            self.assertTrue(ok, msg)
            self.assertEqual(transport.calls[0]["tipo"], "AJUSTE")
            self.assertEqual(transport.calls[0]["operations"][0]["delta_scaled"], 5000)
            self.assertEqual(transport.calls[0]["operations"][0]["producto_local_id"], lid)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn, pid), 0)
            finally:
                conn.close()
            ok2, msg2, pid2 = repo.crear_producto(
                make_producto(nombre="Inicial", stock=5, marca="A"),
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport,
                producto_local_id=lid,
            )
            self.assertTrue(ok2, msg2)
            self.assertEqual(pid, pid2)
            self.assertEqual(len(transport.calls), 1)


class AuthoritativeNoStockSqlTest(unittest.TestCase):
    def test_w01_authoritative_no_update_stock(self):
        src = (REPO_ROOT / "repositories" / "compras_repo.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_crear_compra_authoritative":
                body = ast.get_source_segment(src, node) or ""
                self.assertNotIn("stock = stock +", body)
                return
        self.fail("no está _crear_compra_authoritative")


if __name__ == "__main__":
    unittest.main()
