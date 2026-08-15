# -*- coding: utf-8 -*-
"""Caracterización de writers ANTES de migrarlos. No modifica producción."""
from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from models import MovimientoInventario, Producto
from repositories.compras_repo import ComprasRepository
from repositories.inventario_repository import InventarioRepository
from repositories.productos_repo import ProductosRepository
from services.mezclas_service import MezclasService
from services.movimientos_service import MovimientosService
from services.ventas_service import VentasService
from tests.fase0.harness import official_temp_db
from tests.fase1e.helpers import (
    AuthPermitido,
    ClientesRepoDummy,
    FakeHTTPHandler,
    count_mov,
    insert_usuario,
    seed_producto,
    stock_of,
)


def _ventas_service(env):
    return VentasService(
        env.db, ProductosRepository(env.db), ClientesRepoDummy(), AuthPermitido()
    )


class CaracterizacionComprasTest(unittest.TestCase):
    def test_w01_crear_compra_incrementa_stock_y_kardex(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=0)
            finally:
                conn.close()
            ok, msg, cid = ComprasRepository(env.db).crear_compra(
                proveedor_id=1,
                productos=[{"producto_id": 1, "cantidad": 10, "precio_unitario": 100}],
                numero_factura="FAC-W01",
            )
            self.assertTrue(ok, msg)
            self.assertIsNotNone(cid)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 10)
                self.assertEqual(count_mov(conn, "ENTRADA_COMPRA"), 1)
                compra = conn.execute(
                    "SELECT id, estado FROM compras WHERE id = ?", (cid,)
                ).fetchone()
                self.assertEqual(compra["estado"], "COMPLETADA")
            finally:
                conn.close()

    def test_w02_eliminar_compra_resta_stock_sin_piso(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=0)
            finally:
                conn.close()
            repo = ComprasRepository(env.db)
            ok, msg, cid = repo.crear_compra(
                proveedor_id=1,
                productos=[{"producto_id": 1, "cantidad": 4, "precio_unitario": 50}],
                numero_factura="FAC-W02",
            )
            self.assertTrue(ok, msg)
            ok2, msg2 = repo.eliminar_compra(cid)
            self.assertTrue(ok2, msg2)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 0)
                self.assertEqual(count_mov(conn, "SALIDA_AJUSTE"), 1)
                estado = conn.execute(
                    "SELECT estado FROM compras WHERE id = ?", (cid,)
                ).fetchone()["estado"]
                self.assertEqual(estado, "CANCELADA")
            finally:
                conn.close()

    def test_w02_rollback_compra_inexistente(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=7)
            finally:
                conn.close()
            ok, msg = ComprasRepository(env.db).eliminar_compra(999)
            self.assertFalse(ok)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 7)
            finally:
                conn.close()


class CaracterizacionVentasTest(unittest.TestCase):
    def test_w03_registrar_venta_descuenta_con_guard(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=50)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            ok, msg, venta = _ventas_service(env).registrar_venta(
                items=[{"producto_id": 1, "cantidad": 5, "precio_unitario": 1000}],
            )
            self.assertTrue(ok, msg)
            self.assertIsNotNone(venta)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 45)
                self.assertEqual(count_mov(conn, "SALIDA_VENTA"), 1)
                n = conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0]
                self.assertEqual(n, 1)
            finally:
                conn.close()

    def test_w03_stock_insuficiente_no_crea_venta(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=2)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            ok, msg, venta = _ventas_service(env).registrar_venta(
                items=[{"producto_id": 1, "cantidad": 9, "precio_unitario": 1000}],
            )
            self.assertFalse(ok)
            self.assertIsNone(venta)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 2)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0], 0)
            finally:
                conn.close()

    def test_w04_cancelar_venta_devuelve_stock(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=20)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = _ventas_service(env)
            ok, msg, venta = svc.registrar_venta(
                items=[{"producto_id": 1, "cantidad": 6, "precio_unitario": 1000}],
            )
            self.assertTrue(ok, msg)
            ok2, msg2 = svc.cancelar_venta(venta.id, "test 1E.0")
            self.assertTrue(ok2, msg2)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 20)
                self.assertEqual(count_mov(conn, "ENTRADA_DEVOLUCION"), 1)
                estado = conn.execute(
                    "SELECT estado FROM ventas WHERE id = ?", (venta.id,)
                ).fetchone()["estado"]
                self.assertEqual(estado, "CANCELADA")
            finally:
                conn.close()

    def test_w05_registrar_devolucion_parcial(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = _ventas_service(env)
            ok, msg, venta = svc.registrar_venta(
                items=[{"producto_id": 1, "cantidad": 4, "precio_unitario": 1000}],
            )
            self.assertTrue(ok, msg)
            ok2, msg2, dev_id = svc.registrar_devolucion(
                venta.id, items=[{"producto_id": 1, "cantidad": 1}], motivo="parcial"
            )
            self.assertTrue(ok2, msg2)
            self.assertIsNotNone(dev_id)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 7)
                self.assertEqual(count_mov(conn, "ENTRADA_DEVOLUCION"), 1)
                n = conn.execute("SELECT COUNT(*) FROM devoluciones").fetchone()[0]
                self.assertEqual(n, 1)
            finally:
                conn.close()

    def test_w06_agregar_productos_a_factura_sin_stock_ge(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=15)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = _ventas_service(env)
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
            finally:
                conn.close()


class CaracterizacionProductosTest(unittest.TestCase):
    def test_w07_actualizar_stock_sumar_y_restar(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
            finally:
                conn.close()
            repo = ProductosRepository(env.db)
            ok, msg = repo.actualizar_stock(1, 5, "sumar")
            self.assertTrue(ok, msg)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 15)
                self.assertEqual(count_mov(conn, "ENTRADA_AJUSTE"), 0)
            finally:
                conn.close()
            ok2, msg2 = repo.actualizar_stock(1, 4, "restar")
            self.assertTrue(ok2, msg2)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 11)
            finally:
                conn.close()
            ok3, msg3 = repo.actualizar_stock(1, 50, "restar")
            self.assertFalse(ok3)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 11)
            finally:
                conn.close()

    def test_w08_actualizar_producto_pisa_stock_sin_kardex(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
            finally:
                conn.close()
            repo = ProductosRepository(env.db)
            ok, msg = repo.actualizar_producto(
                Producto(
                    id=1,
                    nombre="Tornillo Fase0",
                    precio_venta=1000,
                    precio_compra=0,
                    stock=3,
                    codigo_barras="TEST-1E0-001",
                )
            )
            self.assertTrue(ok, msg)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 3)
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM movimientos").fetchone()[0], 0
                )
            finally:
                conn.close()

    def test_w09_crear_producto_con_stock_inicial(self):
        with official_temp_db() as env:
            repo = ProductosRepository(env.db)
            ok, msg, pid = repo.crear_producto(
                Producto(
                    nombre="SKU nuevo 1E0",
                    precio_venta=2000,
                    precio_compra=500,
                    stock=8,
                )
            )
            self.assertTrue(ok, msg)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn, pid), 8)
                self.assertEqual(count_mov(conn, "ENTRADA_AJUSTE"), 1)
            finally:
                conn.close()


class CaracterizacionMovimientosTest(unittest.TestCase):
    def test_w10_registrar_movimiento_entrada_y_salida(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = MovimientosService(
                env.db, ProductosRepository(env.db), None, AuthPermitido()
            )
            ok, msg = svc.registrar_movimiento(
                tipo="ENTRADA_COMPRA",
                producto_id=1,
                cantidad=5,
                precio_unitario=100,
                proveedor_id=1,
                num_factura="FAC-W10",
            )
            self.assertTrue(ok, msg)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 15)
                self.assertEqual(count_mov(conn, "ENTRADA_COMPRA"), 1)
            finally:
                conn.close()
            ok2, msg2 = svc.registrar_movimiento(
                tipo="SALIDA_AJUSTE", producto_id=1, cantidad=2
            )
            self.assertTrue(ok2, msg2)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 13)
            finally:
                conn.close()

    def test_w11_anular_movimiento_revierte(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = MovimientosService(
                env.db, ProductosRepository(env.db), None, AuthPermitido()
            )
            ok, msg = svc.registrar_movimiento(
                tipo="ENTRADA_AJUSTE", producto_id=1, cantidad=7
            )
            self.assertTrue(ok, msg)
            conn = env.connect()
            try:
                mid = conn.execute("SELECT MAX(id) FROM movimientos").fetchone()[0]
            finally:
                conn.close()
            ok2, msg2 = svc.anular_movimiento(mid, "test")
            self.assertTrue(ok2, msg2)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 10)
            finally:
                conn.close()


class CaracterizacionInventarioRepoTest(unittest.TestCase):
    def test_w12_registrar_movimiento_inventario(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=0)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            ok, msg = InventarioRepository(env.db).registrar_movimiento(
                MovimientoInventario(
                    tipo_movimiento="ENTRADA_COMPRA",
                    producto_id=1,
                    cantidad=12,
                    precio_unitario=80,
                    usuario_id=1,
                    fecha=datetime.now(),
                    proveedor_id=1,
                    numero_factura="FAC-W12",
                )
            )
            self.assertTrue(ok, msg)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 12)
                self.assertEqual(
                    count_mov(conn, "ENTRADA_COMPRA", "movimientos_inventario"), 1
                )
            finally:
                conn.close()

    def test_w13_ajustar_stock_directo(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            ok, msg = InventarioRepository(env.db).ajustar_stock_directo(
                1, 4, "conteo fisico", 1
            )
            self.assertTrue(ok, msg)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 4)
                self.assertEqual(
                    count_mov(conn, "SALIDA_AJUSTE", "movimientos_inventario"), 1
                )
            finally:
                conn.close()

    def test_w14_eliminar_movimiento_revierte(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=5)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            repo = InventarioRepository(env.db)
            ok, msg = repo.registrar_movimiento(
                MovimientoInventario(
                    tipo_movimiento="ENTRADA_AJUSTE",
                    producto_id=1,
                    cantidad=3,
                    precio_unitario=0,
                    usuario_id=1,
                    fecha=datetime.now(),
                )
            )
            self.assertTrue(ok, msg)
            conn = env.connect()
            try:
                mid = conn.execute(
                    "SELECT MAX(id) FROM movimientos_inventario"
                ).fetchone()[0]
            finally:
                conn.close()
            ok2, msg2 = repo.eliminar_movimiento(mid, revertir_stock=True)
            self.assertTrue(ok2, msg2)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 5)
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM movimientos_inventario"
                    ).fetchone()[0],
                    0,
                )
            finally:
                conn.close()


class CaracterizacionMezclasYLanTest(unittest.TestCase):
    def test_w15_descontar_stock_mezcla(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = MezclasService(env.db, ProductosRepository(env.db), AuthPermitido())
            ok, msg = svc.descontar_stock_mezcla(
                [{"producto_id": 1, "cantidad": 2}], num_factura="MZ-1"
            )
            self.assertTrue(ok, msg)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 8)
                self.assertEqual(count_mov(conn, "SALIDA_VENTA"), 1)
            finally:
                conn.close()

    def test_w16_create_sale_lan_descuenta(self):
        from local_server import LocalFerreteriaAPI

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
                    "items": [
                        {"producto_id": 1, "cantidad": 3, "descuento": 0}
                    ],
                    "metodo_pago": "EFECTIVO",
                }
            ).encode("utf-8")
            handler = FakeHTTPHandler(env.db_path, body)
            LocalFerreteriaAPI.create_sale(handler, {"usuario_id": 1})
            self.assertEqual(handler.status, 201)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 17)
                self.assertEqual(count_mov(conn, "SALIDA_VENTA"), 1)
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0], 1
                )
            finally:
                conn.close()


class CaracterizacionDashboardSqlTest(unittest.TestCase):
    """W17/W18 extraídos a VentasService; el SQL ya no vive en closures."""

    def test_w17_editar_cantidad_sql_mixto(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = _ventas_service(env)
            ok, msg, venta = svc.registrar_venta(
                items=[{"producto_id": 1, "cantidad": 2, "precio_unitario": 1000}],
                metodo_pago="CREDITO",
            )
            self.assertTrue(ok, msg)
            conn = env.connect()
            try:
                det = conn.execute(
                    "SELECT id FROM detalle_ventas WHERE venta_id = ?", (venta.id,)
                ).fetchone()
            finally:
                conn.close()
            ok2, msg2 = svc.editar_linea_factura(venta.id, det["id"], 5, 1000)
            self.assertTrue(ok2, msg2)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 5)
            finally:
                conn.close()
        src = (REPO_ROOT / "ui" / "dashboard_ui.py").read_text(encoding="utf-8")
        self.assertNotIn("UPDATE productos SET stock = stock - ? WHERE id = ?", src)
        self.assertIn("editar_linea_factura", src)
        svc_src = (REPO_ROOT / "services" / "ventas_service.py").read_text(encoding="utf-8")
        self.assertIn("UPDATE productos SET stock = stock - ? WHERE id = ?", svc_src)

    def test_w18_quitar_linea_sql_positivo(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = _ventas_service(env)
            ok, msg, venta = svc.registrar_venta(
                items=[{"producto_id": 1, "cantidad": 2, "precio_unitario": 1000}],
                metodo_pago="CREDITO",
            )
            self.assertTrue(ok, msg)
            conn = env.connect()
            try:
                det = conn.execute(
                    "SELECT id FROM detalle_ventas WHERE venta_id = ?", (venta.id,)
                ).fetchone()
            finally:
                conn.close()
            ok2, msg2 = svc.eliminar_linea_factura(venta.id, det["id"])
            self.assertTrue(ok2, msg2)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 10)
            finally:
                conn.close()
        src = (REPO_ROOT / "ui" / "dashboard_ui.py").read_text(encoding="utf-8")
        self.assertNotIn("UPDATE productos SET stock = stock + ? WHERE id = ?", src)
        self.assertIn("eliminar_linea_factura", src)
        svc_src = (REPO_ROOT / "services" / "ventas_service.py").read_text(encoding="utf-8")
        self.assertIn("UPDATE productos SET stock = stock + ? WHERE id = ?", svc_src)
