# -*- coding: utf-8 -*-
"""Writers mixtos 1E.2: W07 W08 W10 W11 W12 W13 W14 W17."""
from __future__ import annotations

import ast
import sys
import unittest
import uuid
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from models import MovimientoInventario
from repositories.inventario_repository import InventarioRepository
from repositories.productos_repo import ProductosRepository
from services.movimientos_service import MovimientosService
from tests.fase0.harness import official_temp_db
from tests.fase1e.helpers import AuthPermitido, insert_usuario, seed_producto, stock_of
from tests.fase1e2.helpers import (
    command_count,
    make_producto,
    transport_applied,
    transport_rejected,
    transport_unknown,
    ventas_service,
)


class W07W08Test(unittest.TestCase):
    def test_w07_es_delta_no_absoluto(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
            finally:
                conn.close()
            repo = ProductosRepository(env.db)
            ok, msg = repo.actualizar_stock(1, 3, "sumar")
            self.assertTrue(ok, msg)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 13)
                self.assertEqual(command_count(conn), 0)
            finally:
                conn.close()
            transport = transport_applied()
            ok2, msg2 = repo.actualizar_stock(
                1, 2, "restar",
                inventory_mode="authoritative",
                inventory_transport=transport,
            )
            self.assertTrue(ok2, msg2)
            self.assertEqual(transport.calls[0]["tipo"], "AJUSTE")
            self.assertEqual(transport.calls[0]["operations"][0]["delta_scaled"], -2000)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 13)
            finally:
                conn.close()

    def test_w08_metadata_no_bypasea_stock(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
            finally:
                conn.close()
            repo = ProductosRepository(env.db)
            prod = make_producto(id=1, nombre="Renombrado", stock=10)
            transport = transport_applied()
            ok, msg = repo.actualizar_producto(
                prod,
                inventory_mode="authoritative",
                inventory_transport=transport,
                inventory_stock_base_scaled=10000,
            )
            self.assertTrue(ok, msg)
            self.assertEqual(transport.calls, [])
            conn = env.connect()
            try:
                row = conn.execute("SELECT nombre, stock FROM productos WHERE id = 1").fetchone()
                self.assertEqual(row["nombre"], "Renombrado")
                self.assertEqual(row["stock"], 10)
            finally:
                conn.close()
            prod.stock = 4
            cid = str(uuid.uuid4())
            ok2, msg2 = repo.actualizar_producto(
                prod,
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport,
                inventory_stock_base_scaled=10000,
            )
            self.assertTrue(ok2, msg2)
            self.assertEqual(transport.calls[0]["tipo"], "AJUSTE")
            self.assertEqual(transport.calls[0]["operations"][0]["delta_scaled"], -6000)
            self.assertEqual(
                transport.calls[0]["operations"][0]["expected_base_scaled"], 10000
            )
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 10)
                src = (REPO_ROOT / "repositories" / "productos_repo.py").read_text(encoding="utf-8")
                tree = ast.parse(src)
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef) and node.name == "_actualizar_producto_authoritative":
                        body = ast.get_source_segment(src, node) or ""
                        self.assertNotIn("stock = ?", body)
            finally:
                conn.close()


class W10W11W12W14Test(unittest.TestCase):
    def test_w10_signos_entrada_salida(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = MovimientosService(env.db, ProductosRepository(env.db), None, AuthPermitido())
            ok, msg = svc.registrar_movimiento("ENTRADA_AJUSTE", 1, 2)
            self.assertTrue(ok, msg)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 12)
                self.assertEqual(command_count(conn), 0)
            finally:
                conn.close()
            transport = transport_applied()
            ok2, msg2 = svc.registrar_movimiento(
                "SALIDA_VENTA", 1, 3,
                inventory_mode="authoritative",
                inventory_transport=transport,
            )
            self.assertTrue(ok2, msg2)
            self.assertEqual(transport.calls[0]["tipo"], "VENTA")
            self.assertEqual(transport.calls[0]["operations"][0]["delta_scaled"], -3000)
            transport2 = transport_applied()
            ok3, msg3 = svc.registrar_movimiento(
                "ENTRADA_COMPRA", 1, 1, precio_unitario=50,
                inventory_mode="authoritative",
                inventory_transport=transport2,
            )
            self.assertTrue(ok3, msg3)
            self.assertEqual(transport2.calls[0]["tipo"], "COMPRA")
            self.assertEqual(transport2.calls[0]["operations"][0]["delta_scaled"], 1000)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 12)
            finally:
                conn.close()

    def test_w11_no_anula_dos_veces(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = MovimientosService(env.db, ProductosRepository(env.db), None, AuthPermitido())
            ok, msg = svc.registrar_movimiento("ENTRADA_AJUSTE", 1, 2)
            self.assertTrue(ok, msg)
            conn = env.connect()
            try:
                mid = conn.execute("SELECT id FROM movimientos ORDER BY id DESC LIMIT 1").fetchone()[0]
            finally:
                conn.close()
            cid = str(uuid.uuid4())
            transport = transport_applied()
            ok2, msg2 = svc.anular_movimiento(
                mid, "test",
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport,
            )
            self.assertTrue(ok2, msg2)
            self.assertEqual(transport.calls[0]["operations"][0]["delta_scaled"], -2000)
            ok3, msg3 = svc.anular_movimiento(
                mid, "test",
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport,
            )
            self.assertTrue(ok3, msg3)
            self.assertEqual(len(transport.calls), 1)

    def test_w12_y_w14(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            repo = InventarioRepository(env.db)
            mov = MovimientoInventario(
                tipo_movimiento="SALIDA_AJUSTE",
                producto_id=1,
                cantidad=2,
                precio_unitario=0,
                usuario_id=1,
                fecha=datetime.now(),
                observaciones="w12",
            )
            ok, msg = repo.registrar_movimiento(mov)
            self.assertTrue(ok, msg)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 8)
                mid = conn.execute(
                    "SELECT id FROM movimientos_inventario ORDER BY id DESC LIMIT 1"
                ).fetchone()[0]
            finally:
                conn.close()
            transport = transport_applied()
            ok2, msg2 = repo.registrar_movimiento(
                MovimientoInventario(
                    tipo_movimiento="ENTRADA_AJUSTE",
                    producto_id=1, cantidad=1, precio_unitario=0,
                    usuario_id=1, fecha=datetime.now(),
                ),
                inventory_mode="authoritative",
                inventory_transport=transport,
            )
            self.assertTrue(ok2, msg2)
            self.assertEqual(transport.calls[0]["tipo"], "AJUSTE")
            self.assertEqual(transport.calls[0]["operations"][0]["delta_scaled"], 1000)
            cid = str(uuid.uuid4())
            t2 = transport_applied()
            ok3, msg3 = repo.eliminar_movimiento(
                mid, True,
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=t2,
            )
            self.assertTrue(ok3, msg3)
            self.assertEqual(t2.calls[0]["operations"][0]["delta_scaled"], 2000)
            ok4, msg4 = repo.eliminar_movimiento(
                mid, True,
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=t2,
            )
            self.assertTrue(ok4, msg4)
            self.assertEqual(len(t2.calls), 1)


class W13Test(unittest.TestCase):
    def test_positivo_negativo_cero_rejected_unknown_retry(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            repo = InventarioRepository(env.db)
            ok, msg = repo.ajustar_stock_directo(1, 10, "noop", 1)
            self.assertTrue(ok, msg)
            self.assertIn("No hay diferencia", msg)
            tpos = transport_applied()
            ok2, msg2 = repo.ajustar_stock_directo(
                1, 15, "up", 1,
                inventory_mode="authoritative",
                inventory_transport=tpos,
                inventory_stock_base_scaled=10000,
            )
            self.assertTrue(ok2, msg2)
            self.assertEqual(tpos.calls[0]["tipo"], "AJUSTE")
            self.assertEqual(tpos.calls[0]["operations"][0]["delta_scaled"], 5000)
            tneg = transport_applied()
            ok3, msg3 = repo.ajustar_stock_directo(
                1, 7, "down", 1,
                inventory_mode="authoritative",
                inventory_transport=tneg,
                inventory_stock_base_scaled=10000,
            )
            self.assertTrue(ok3, msg3)
            self.assertEqual(tneg.calls[0]["operations"][0]["delta_scaled"], -3000)
            ok4, msg4 = repo.ajustar_stock_directo(
                1, 10, "zero", 1,
                inventory_mode="authoritative",
                inventory_transport=transport_applied(),
                inventory_stock_base_scaled=10000,
            )
            self.assertTrue(ok4, msg4)
            self.assertIn("No hay diferencia", msg4)
            ok5, msg5 = repo.ajustar_stock_directo(
                1, 0, "rej", 1,
                inventory_mode="authoritative",
                inventory_transport=transport_rejected("INSUFFICIENT_STOCK"),
                inventory_stock_base_scaled=10000,
            )
            self.assertFalse(ok5)
            self.assertIn("INSUFFICIENT_STOCK", msg5)
            cid = str(uuid.uuid4())
            ok6, msg6 = repo.ajustar_stock_directo(
                1, 12, "unk", 1,
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport_unknown(),
                inventory_stock_base_scaled=10000,
            )
            self.assertFalse(ok6)
            self.assertIn("INVENTORY_UNKNOWN", msg6)
            tretry = transport_applied()
            ok7, msg7 = repo.ajustar_stock_directo(
                1, 12, "unk", 1,
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=tretry,
                inventory_stock_base_scaled=10000,
            )
            self.assertTrue(ok7, msg7)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 10)
            finally:
                conn.close()

    def test_unknown_reusa_expected_base_persistido(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            repo = InventarioRepository(env.db)
            cid = str(uuid.uuid4())
            ok, msg = repo.ajustar_stock_directo(
                1, 12, "unk-cas", 1,
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport_unknown(),
                inventory_stock_base_scaled=10000,
            )
            self.assertFalse(ok)
            self.assertIn("INVENTORY_UNKNOWN", msg)
            tretry = transport_applied()
            ok2, msg2 = repo.ajustar_stock_directo(
                1, 12, "unk-cas", 1,
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=tretry,
                inventory_stock_base_scaled=99999,
            )
            self.assertTrue(ok2, msg2)
            self.assertEqual(
                tretry.calls[0]["operations"][0]["expected_base_scaled"], 10000
            )
            self.assertEqual(
                tretry.calls[0]["operations"][0]["delta_scaled"], 2000
            )

    def test_authoritative_no_sql_directo(self):
        src = (REPO_ROOT / "repositories" / "inventario_repository.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_ajustar_stock_directo_authoritative":
                body = ast.get_source_segment(src, node) or ""
                self.assertNotIn("SET stock = ?", body)
                self.assertNotIn("stock = ?", body)
                return
        self.fail("no está _ajustar_stock_directo_authoritative")


class W17DeltaTest(unittest.TestCase):
    def test_positivo_negativo_cero(self):
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
            t0 = transport_applied()
            ok0, msg0 = svc.editar_linea_factura(
                venta.id, det, 4, 1100,
                inventory_mode="authoritative",
                inventory_transport=t0,
            )
            self.assertTrue(ok0, msg0)
            self.assertEqual(t0.calls, [])
            tplus = transport_applied()
            ok1, msg1 = svc.editar_linea_factura(
                venta.id, det, 6, 1000,
                inventory_mode="authoritative",
                inventory_transport=tplus,
            )
            self.assertTrue(ok1, msg1)
            self.assertEqual(tplus.calls[0]["operations"][0]["delta_scaled"], -2000)
            tminus = transport_applied()
            ok2, msg2 = svc.editar_linea_factura(
                venta.id, det, 3, 1000,
                inventory_mode="authoritative",
                inventory_transport=tminus,
            )
            self.assertTrue(ok2, msg2)
            self.assertEqual(tminus.calls[0]["operations"][0]["delta_scaled"], 3000)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 6)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
