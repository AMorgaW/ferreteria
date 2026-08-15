# -*- coding: utf-8 -*-
"""LWW/INV-02, W08, command identity, UNKNOWN, scanner."""
from __future__ import annotations

import json
import sys
import unittest
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from repositories.productos_repo import ProductosRepository
from tests.fase0.harness import official_temp_db
from tests.fase0.stock_writers import GATEWAY_PREPARED_IDS, UNTRACKED_DIRECT_WRITER
from tests.fase0.test_stock_writers import scan_stock_writes_by_function
from tests.fase1e.helpers import insert_usuario, seed_producto, stock_of
from tests.fase1e2.helpers import make_producto, transport_applied, transport_unknown, ventas_service
from tests.fase1e3.helpers import lan_create_sale, mark_authoritative


class LwwExcludeTest(unittest.TestCase):
    def test_pre_cutover_stock_sigue_en_lww(self):
        from local_sync import _lww_excluded_fields, build_remote_upsert_sql
        from sync_registry import APPLY_AUTHORITATIVE_EXCLUDE, fields_excluded_from_authoritative_write

        self.assertFalse(APPLY_AUTHORITATIVE_EXCLUDE)
        self.assertEqual(fields_excluded_from_authoritative_write("productos"), ())
        with official_temp_db() as env:
            conn = env.connect()
            try:
                self.assertEqual(_lww_excluded_fields(conn, "productos"), set())
                sql = build_remote_upsert_sql(
                    "productos", ["local_id", "nombre", "precio_venta", "stock"]
                )
                self.assertIn("stock=EXCLUDED.stock", sql)
                self.assertIn("nombre=EXCLUDED.nombre", sql)
            finally:
                conn.close()

    def test_post_cutover_stock_no_es_autoridad_otros_campos_si(self):
        from local_sync import _lww_excluded_fields, build_remote_upsert_sql

        with official_temp_db() as env:
            conn = env.connect()
            try:
                mark_authoritative(conn)
                excluded = _lww_excluded_fields(conn, "productos")
                self.assertEqual(excluded, {"stock"})
                columns = ["local_id", "nombre", "precio_venta", "codigo_barras", "stock"]
                filtered = [c for c in columns if c not in excluded]
                sql = build_remote_upsert_sql("productos", filtered)
                self.assertNotIn("stock=EXCLUDED.stock", sql)
                self.assertIn("nombre=EXCLUDED.nombre", sql)
                self.assertIn("precio_venta=EXCLUDED.precio_venta", sql)
                self.assertIn("codigo_barras=EXCLUDED.codigo_barras", sql)
            finally:
                conn.close()


class W08NoCacheTest(unittest.TestCase):
    def test_w08_no_usa_productos_stock_como_base(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
            finally:
                conn.close()
            repo = ProductosRepository(env.db)
            conn = env.connect()
            try:
                conn.execute("UPDATE productos SET stock = 99 WHERE id = 1")
                conn.commit()
            finally:
                conn.close()
            prod = make_producto(id=1, nombre="Stale", stock=4)
            transport = transport_applied()
            ok, msg = repo.actualizar_producto(
                prod,
                inventory_mode="authoritative",
                inventory_transport=transport,
                inventory_stock_base_scaled=10000,
            )
            self.assertTrue(ok, msg)
            self.assertEqual(transport.calls[0]["operations"][0]["delta_scaled"], -6000)
            self.assertEqual(
                transport.calls[0]["operations"][0]["expected_base_scaled"], 10000
            )
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 99)
            finally:
                conn.close()


class CommandIdentityTest(unittest.TestCase):
    def test_w03_reusa_command_id_persistido(self):
        from inventory_cutover import get_or_create_act_command_id

        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=20)
                insert_usuario(conn)
                conn.commit()
                act = str(uuid.uuid4())
                cid = get_or_create_act_command_id(conn, "pos_checkout", act)
                cid2 = get_or_create_act_command_id(conn, "pos_checkout", act)
                self.assertEqual(cid, cid2)
            finally:
                conn.close()
            transport = transport_unknown()
            ok, msg, venta = ventas_service(env).registrar_venta(
                items=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 1000}],
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport,
            )
            self.assertFalse(ok)
            self.assertIsNone(venta)
            self.assertIn("INVENTORY_UNKNOWN", msg)
            svc = ventas_service(env)
            ok2, msg2, venta2 = svc.registrar_venta(
                items=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 1000}],
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport,
            )
            self.assertFalse(ok2)
            self.assertEqual(svc.last_inventory_command_id, cid)
            conn = env.connect()
            try:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM inventory_commands").fetchone()[0],
                    1,
                )
            finally:
                conn.close()

    def test_w16_ignora_command_id_http_arbitrario(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=20)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            bogus = str(uuid.uuid4())
            handler = lan_create_sale(
                env,
                [{"producto_id": 1, "cantidad": 1, "descuento": 0}],
                inventory_mode="authoritative",
                inventory_transport=transport_unknown(),
                body_command_id=bogus,
            )
            self.assertEqual(handler.status, 503)
            data = json.loads(handler.wfile.getvalue().decode("utf-8"))
            returned = data.get("command_id")
            self.assertTrue(returned)
            self.assertNotEqual(returned, bogus)
            self.assertTrue(data.get("retryable"))
            handler2 = lan_create_sale(
                env,
                [{"producto_id": 1, "cantidad": 1, "descuento": 0}],
                inventory_mode="authoritative",
                inventory_transport=transport_unknown(),
                inventory_command_id=returned,
            )
            self.assertEqual(handler2.status, 503)
            conn = env.connect()
            try:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM inventory_commands").fetchone()[0],
                    1,
                )
            finally:
                conn.close()


class ScannerTest(unittest.TestCase):
    def test_scanner_cero_untracked(self):
        hits = scan_stock_writes_by_function()
        untracked = [h for h in hits if h["status"] == UNTRACKED_DIRECT_WRITER]
        self.assertFalse(untracked, msg=repr(untracked))
        found = {h["writer_id"] for h in hits if h["writer_id"]}
        self.assertTrue(set(GATEWAY_PREPARED_IDS).issubset(found))
        self.assertIn("D05", found)


if __name__ == "__main__":
    unittest.main()
