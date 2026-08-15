# -*- coding: utf-8 -*-
"""Preconditions, freeze, rollback, restart persistente (SQLite)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from repositories.compras_repo import ComprasRepository
from repositories.inventario_repository import InventarioRepository
from repositories.productos_repo import ProductosRepository
from tests.fase0.harness import official_temp_db
from tests.fase1e.helpers import insert_usuario, seed_producto
from tests.fase1e2.helpers import ventas_service
from tests.fase1e3.helpers import freeze_only, lan_create_sale, mark_authoritative


class PreconditionsTest(unittest.TestCase):
    def test_local_id_incompleto_bloquea(self):
        from inventory_cutover import list_invalid_product_local_ids, verify_preconditions

        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=4)
                conn.execute("UPDATE productos SET local_id = '' WHERE id = 1")
                conn.commit()
                invalid = list_invalid_product_local_ids(conn)
                self.assertTrue(invalid)
                failures = verify_preconditions(
                    conn, require_app_dsn=False, app_factory=None
                )
                self.assertTrue(any("local_id" in f for f in failures))
            finally:
                conn.close()

    def test_preconditions_scanner_y_writers(self):
        from inventory_cutover import verify_preconditions

        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=1)
                failures = verify_preconditions(
                    conn, require_app_dsn=False, app_factory=None
                )
                self.assertFalse(
                    any("UNTRACKED" in f or "W01-W18" in f for f in failures),
                    msg=repr(failures),
                )
            finally:
                conn.close()


class FreezeTest(unittest.TestCase):
    def _freeze(self, env):
        conn = env.connect()
        try:
            seed_producto(conn, env, stock=20)
            insert_usuario(conn)
            conn.commit()
            freeze_only(conn)
        finally:
            conn.close()

    def test_venta_compra_ajuste_lan_bloqueados(self):
        with official_temp_db() as env:
            self._freeze(env)
            ok, msg, venta = ventas_service(env).registrar_venta(
                items=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 1000}],
            )
            self.assertFalse(ok)
            self.assertIn("congelado", msg.lower())
            self.assertIsNone(venta)
            ok2, msg2, cid = ComprasRepository(env.db).crear_compra(
                proveedor_id=1,
                productos=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 10}],
                numero_factura="FZ-1",
            )
            self.assertFalse(ok2)
            self.assertIn("congelado", msg2.lower())
            ok3, msg3 = InventarioRepository(env.db).ajustar_stock_directo(
                1, 1, "fz", 1
            )
            self.assertFalse(ok3)
            self.assertIn("congelado", msg3.lower())
            handler = lan_create_sale(
                env, [{"producto_id": 1, "cantidad": 1, "descuento": 0}]
            )
            self.assertEqual(handler.status, 503)


class RollbackRestartTest(unittest.TestCase):
    def test_no_unsafe_rollback_tras_authoritative(self):
        from inventory_cutover import UnsafeRollbackError, abort_pre_activation, load_cutover_state

        with official_temp_db() as env:
            conn = env.connect()
            try:
                mark_authoritative(conn)
                with self.assertRaises(UnsafeRollbackError):
                    abort_pre_activation(conn)
                self.assertEqual(load_cutover_state(conn).status, "AUTHORITATIVE")
            finally:
                conn.close()

    def test_no_legacy_explicit_tras_authoritative(self):
        from inventory_cutover import InventoryCutoverError
        from inventory_writer_support import resolve_writer_mode

        with official_temp_db() as env:
            conn = env.connect()
            try:
                mark_authoritative(conn)
                with self.assertRaises(InventoryCutoverError):
                    resolve_writer_mode("legacy", sqlite_conn=conn)
            finally:
                conn.close()

    def test_restart_conserva_authoritative(self):
        from inventory_cutover import is_cutover_authoritative, load_cutover_state
        from inventory_writer_support import WRITER_MODE_AUTHORITATIVE, resolve_writer_mode

        with official_temp_db() as env:
            conn = env.connect()
            try:
                mark_authoritative(conn)
            finally:
                conn.close()
            conn2 = env.connect()
            try:
                state = load_cutover_state(conn2)
                self.assertEqual(state.status, "AUTHORITATIVE")
                self.assertTrue(is_cutover_authoritative(conn2))
                self.assertEqual(
                    resolve_writer_mode(db=env.db), WRITER_MODE_AUTHORITATIVE
                )
            finally:
                conn2.close()

    def test_rollback_pre_activation_ok(self):
        from inventory_cutover import abort_pre_activation, freeze_inventory_writes, load_cutover_state

        with official_temp_db() as env:
            conn = env.connect()
            try:
                freeze_inventory_writes(conn)
                state = abort_pre_activation(conn, reason="lab")
                self.assertEqual(state.status, "ROLLBACK_SAFE")
                self.assertEqual(load_cutover_state(conn).status, "ROLLBACK_SAFE")
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
