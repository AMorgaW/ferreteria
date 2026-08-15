# -*- coding: utf-8 -*-
"""Post-APPLY local recovery para W06 / W02 / W15."""
from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from repositories.compras_repo import ComprasRepository
from repositories.productos_repo import ProductosRepository
from services.mezclas_service import MezclasService
from tests.fase0.harness import official_temp_db
from tests.fase1e.helpers import AuthPermitido, count_mov, insert_usuario, seed_producto, stock_of
from tests.fase1e2.helpers import command_count, transport_applied, ventas_service


class RecoveryW06Test(unittest.TestCase):
    def test_applied_remoto_crash_local_retry_completa(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=20)
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
            conn = env.connect()
            try:
                conn.execute("DELETE FROM movimientos WHERE motivo LIKE ?", (f"%{cid}%",))
                conn.execute(
                    "DELETE FROM detalle_ventas WHERE venta_id = ? AND id NOT IN "
                    "(SELECT MIN(id) FROM detalle_ventas WHERE venta_id = ?)",
                    (venta.id, venta.id),
                )
                conn.execute(
                    "UPDATE ventas SET total = 2000, subtotal = 2000 WHERE id = ?",
                    (venta.id,),
                )
                conn.commit()
                self.assertEqual(count_mov(conn, "SALIDA_VENTA"), 1)
            finally:
                conn.close()
            ok3, msg3 = svc.agregar_productos_a_factura(
                venta.id,
                [{"producto_id": 1, "cantidad": 3, "precio_unitario": 1000}],
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport,
            )
            self.assertTrue(ok3, msg3)
            self.assertEqual(len(transport.calls), 1)
            conn = env.connect()
            try:
                self.assertEqual(count_mov(conn, "SALIDA_VENTA"), 2)
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM detalle_ventas WHERE venta_id = ?",
                        (venta.id,),
                    ).fetchone()[0],
                    2,
                )
                self.assertEqual(command_count(conn), 1)
                self.assertEqual(stock_of(conn), 18)
            finally:
                conn.close()


class RecoveryW02Test(unittest.TestCase):
    def test_applied_crash_antes_de_cancelada(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=0)
            finally:
                conn.close()
            repo = ComprasRepository(env.db)
            ok, msg, compra_id = repo.crear_compra(
                proveedor_id=1,
                productos=[{"producto_id": 1, "cantidad": 4, "precio_unitario": 50}],
                numero_factura="FAC-W02-REC",
            )
            self.assertTrue(ok, msg)
            cid = str(uuid.uuid4())
            transport = transport_applied()
            ok2, msg2 = repo.eliminar_compra(
                compra_id,
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport,
            )
            self.assertTrue(ok2, msg2)
            conn = env.connect()
            try:
                conn.execute("UPDATE compras SET estado = 'COMPLETADA' WHERE id = ?", (compra_id,))
                conn.execute("DELETE FROM movimientos WHERE motivo LIKE ?", (f"%{cid}%",))
                conn.commit()
            finally:
                conn.close()
            ok3, msg3 = repo.eliminar_compra(
                compra_id,
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport,
            )
            self.assertTrue(ok3, msg3)
            self.assertEqual(len(transport.calls), 1)
            conn = env.connect()
            try:
                estado = conn.execute(
                    "SELECT estado FROM compras WHERE id = ?", (compra_id,)
                ).fetchone()["estado"]
                self.assertEqual(estado, "CANCELADA")
                self.assertEqual(count_mov(conn, "SALIDA_AJUSTE"), 1)
            finally:
                conn.close()


class RecoveryW15Test(unittest.TestCase):
    def test_applied_crash_sin_movimientos(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = MezclasService(env.db, ProductosRepository(env.db), AuthPermitido())
            cid = str(uuid.uuid4())
            transport = transport_applied()
            ok, msg = svc.descontar_stock_mezcla(
                [{"producto_id": 1, "cantidad": 2}],
                num_factura="MZ-REC",
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport,
            )
            self.assertTrue(ok, msg)
            conn = env.connect()
            try:
                conn.execute("DELETE FROM movimientos WHERE motivo LIKE ?", (f"%{cid}%",))
                conn.commit()
                self.assertEqual(count_mov(conn, "SALIDA_VENTA"), 0)
            finally:
                conn.close()
            ok2, msg2 = svc.descontar_stock_mezcla(
                [{"producto_id": 1, "cantidad": 2}],
                num_factura="MZ-REC",
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport,
            )
            self.assertTrue(ok2, msg2)
            self.assertEqual(len(transport.calls), 1)
            conn = env.connect()
            try:
                self.assertEqual(count_mov(conn, "SALIDA_VENTA"), 1)
                self.assertEqual(stock_of(conn), 10)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
