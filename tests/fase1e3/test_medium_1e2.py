# -*- coding: utf-8 -*-
"""Cierre MEDIUM 1E.2: dual-write W10-W14, W11 post-APPLY, W09 identidad."""
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
from tests.fase1e2.helpers import make_producto, transport_applied


def _authoritative_fn_source(path, name):
    src = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"no está {name} en {path}")


class DualWriteW10W14Test(unittest.TestCase):
    def test_authoritative_functions_no_sql_legacy_stock(self):
        cases = (
            (REPO_ROOT / "services" / "movimientos_service.py",
             "_registrar_movimiento_authoritative"),
            (REPO_ROOT / "services" / "movimientos_service.py",
             "_anular_movimiento_authoritative"),
            (REPO_ROOT / "repositories" / "inventario_repository.py",
             "_registrar_movimiento_authoritative"),
            (REPO_ROOT / "repositories" / "inventario_repository.py",
             "_eliminar_movimiento_authoritative"),
        )
        for path, name in cases:
            body = _authoritative_fn_source(path, name)
            self.assertNotIn("SET stock", body)
            self.assertNotIn("stock = ?", body)
            self.assertNotIn("stock = stock", body)

    def test_w10_authoritative_no_cambia_productos_stock(self):
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
                before = stock_of(conn)
                self.assertEqual(before, 12)
            finally:
                conn.close()
            transport = transport_applied()
            ok2, msg2 = svc.registrar_movimiento(
                "SALIDA_VENTA", 1, 3,
                inventory_mode="authoritative",
                inventory_transport=transport,
            )
            self.assertTrue(ok2, msg2)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), before)
            finally:
                conn.close()

    def test_w12_w14_authoritative_no_cambia_productos_stock(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            repo = InventarioRepository(env.db)
            before_conn = env.connect()
            try:
                before = stock_of(before_conn)
            finally:
                before_conn.close()
            transport = transport_applied()
            ok, msg = repo.registrar_movimiento(
                MovimientoInventario(
                    tipo_movimiento="ENTRADA_AJUSTE",
                    producto_id=1, cantidad=2, precio_unitario=0,
                    usuario_id=1, fecha=datetime.now(),
                ),
                inventory_mode="authoritative",
                inventory_transport=transport,
            )
            self.assertTrue(ok, msg)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), before)
                mid = conn.execute(
                    "SELECT id FROM movimientos_inventario ORDER BY id DESC LIMIT 1"
                ).fetchone()[0]
            finally:
                conn.close()
            ok2, msg2 = repo.eliminar_movimiento(
                mid,
                inventory_mode="authoritative",
                inventory_transport=transport_applied(),
            )
            self.assertTrue(ok2, msg2)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), before)
            finally:
                conn.close()


class W11PostApplyTest(unittest.TestCase):
    def test_crash_post_apply_no_segunda_reversion(self):
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
                before = stock_of(conn)
            finally:
                conn.close()
            cid = str(uuid.uuid4())
            transport = transport_applied()
            ok2, msg2 = svc.anular_movimiento(
                mid, "crash",
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport,
            )
            self.assertTrue(ok2, msg2)
            conn = env.connect()
            try:
                conn.execute(
                    "UPDATE movimientos SET observaciones = 'ENTRADA_AJUSTE original' WHERE id = ?",
                    (mid,),
                )
                conn.commit()
                self.assertEqual(stock_of(conn), before)
            finally:
                conn.close()
            ok3, msg3 = svc.anular_movimiento(
                mid, "crash",
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport,
            )
            self.assertTrue(ok3, msg3)
            self.assertEqual(len(transport.calls), 1)
            conn = env.connect()
            try:
                obs = conn.execute(
                    "SELECT observaciones FROM movimientos WHERE id = ?", (mid,)
                ).fetchone()[0]
                self.assertIn("[ANULADO]", obs)
                self.assertEqual(obs.count("[ANULADO]"), 1)
                cmds = conn.execute("SELECT COUNT(*) FROM inventory_commands").fetchone()[0]
                self.assertEqual(cmds, 1)
                self.assertEqual(stock_of(conn), before)
            finally:
                conn.close()
            ok4, msg4 = svc.anular_movimiento(
                mid, "crash",
                inventory_mode="authoritative",
                inventory_transport=transport,
            )
            self.assertTrue(ok4, msg4)
            self.assertEqual(len(transport.calls), 1)


class W09StockInicialTest(unittest.TestCase):
    def test_producto_existente_no_reaplica_stock_con_command_nuevo(self):
        with official_temp_db() as env:
            repo = ProductosRepository(env.db)
            lid = str(uuid.uuid4())
            cid1 = str(uuid.uuid4())
            transport = transport_applied()
            ok, msg, pid = repo.crear_producto(
                make_producto(nombre="Inicial-Adv", stock=5, marca="ADV"),
                inventory_mode="authoritative",
                inventory_command_id=cid1,
                inventory_transport=transport,
                producto_local_id=lid,
            )
            self.assertTrue(ok, msg)
            self.assertEqual(len(transport.calls), 1)
            cid2 = str(uuid.uuid4())
            ok2, msg2, pid2 = repo.crear_producto(
                make_producto(nombre="Inicial-Adv", stock=5, marca="ADV"),
                inventory_mode="authoritative",
                inventory_command_id=cid2,
                inventory_transport=transport,
                producto_local_id=lid,
            )
            self.assertTrue(ok2, msg2)
            self.assertEqual(pid, pid2)
            self.assertEqual(len(transport.calls), 1)
            conn = env.connect()
            try:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM inventory_commands").fetchone()[0],
                    1,
                )
                self.assertEqual(stock_of(conn, pid), 0)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
