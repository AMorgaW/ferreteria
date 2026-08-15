# -*- coding: utf-8 -*-
"""Delta 0 no crea InventoryOperation; documento puede continuar."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from inventory_writer_support import NO_INVENTORY_CHANGE, build_signed_operations
from tests.fase0.harness import official_temp_db
from tests.fase1e.helpers import insert_usuario, seed_producto
from tests.fase1e2.helpers import transport_applied, ventas_service


class DeltaZeroTest(unittest.TestCase):
    def test_builder_omite_delta_cero(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                ops = build_signed_operations(
                    conn,
                    [{"producto_id": 1, "delta": 0}],
                    command_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                )
                self.assertEqual(ops, [])
            finally:
                conn.close()

    def test_w17_solo_precio_no_envia_command(self):
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
            transport = transport_applied()
            ok2, msg2 = svc.editar_linea_factura(
                venta.id, det, 2, 1500,
                inventory_mode="authoritative",
                inventory_transport=transport,
            )
            self.assertTrue(ok2, msg2)
            self.assertEqual(transport.calls, [])
            self.assertEqual(svc.last_gateway_result, NO_INVENTORY_CHANGE)
            conn = env.connect()
            try:
                precio = conn.execute(
                    "SELECT precio_unitario FROM detalle_ventas WHERE id = ?", (det,)
                ).fetchone()[0]
                self.assertEqual(precio, 1500)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
