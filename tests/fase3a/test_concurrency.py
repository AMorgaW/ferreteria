# -*- coding: utf-8 -*-
"""Concurrencia POS: última unidad, ferrepro-pg-test. No Supabase real."""
from __future__ import annotations

import sys
import threading
import unittest
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.pos_cart import PosCart
from tests.fase0.harness import official_temp_db
from tests.fase1d.pg_harness import insert_producto, postgres_available
from tests.fase1e.helpers import insert_usuario, seed_producto
from tests.fase1e1.helpers import ventas_service
from tests.fase1e3.helpers import app_factory, force_postgres_status, pin_env_db
from tests.fase1e4.helpers import prepare_pg
from tests.fase3a.helpers import assert_not_commercial_db


@unittest.skipUnless(
    postgres_available(),
    "POSTGRES INTEGRATION opt-in: ferrepro-pg-test / FERREPRO_PG_TEST_DSN",
)
class PosConcurrencyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_pg()
        from tests.fase1d.pg_harness import connect

        cls.admin = connect()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.admin.close()
        except Exception:
            pass

    def test_20_two_station_last_unit(self):
        from inventory_coordinator import InventoryCoordinatorClient
        from inventory_cutover import STATUS_AUTHORITATIVE, STATUS_CUTOVER_IN_PROGRESS

        lid = insert_producto(self.admin, stock=1)
        InventoryCoordinatorClient(self.admin).seed_balance(lid, 1000)
        force_postgres_status(self.admin, STATUS_CUTOVER_IN_PROGRESS)
        force_postgres_status(self.admin, STATUS_AUTHORITATIVE, epoch=1)
        results = []
        barrier = threading.Barrier(2)

        def worker(env):
            pin_env_db(env)
            conn = env.connect()
            try:
                seed_producto(
                    conn, env, stock=1, local_id=lid, codigo=f"LU-{uuid.uuid4().hex[:6]}"
                )
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            cart = PosCart()
            cart.add_manual(
                {"id": 1, "nombre": "Ultima", "precio_venta": 1000, "permite_decimales": 0},
                1,
            )
            items = cart.to_sale_items()
            barrier.wait(timeout=15)
            ok, msg, venta = ventas_service(env).registrar_venta(
                items=items,
                inventory_command_id=str(uuid.uuid4()),
                inventory_connection_factory=app_factory(),
            )
            conn = env.connect()
            try:
                n_ventas = conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0]
            finally:
                conn.close()
            results.append((ok, venta is not None, msg, n_ventas))

        with official_temp_db() as env_a, official_temp_db() as env_b:
            assert_not_commercial_db(env_a)
            assert_not_commercial_db(env_b)
            t1 = threading.Thread(target=worker, args=(env_a,))
            t2 = threading.Thread(target=worker, args=(env_b,))
            t1.start()
            t2.start()
            t1.join(timeout=30)
            t2.join(timeout=30)
        applied = [r for r in results if r[0] and r[1]]
        rejected = [r for r in results if not r[0]]
        self.assertEqual(len(results), 2, msg=repr(results))
        self.assertEqual(len(applied), 1, msg=repr(results))
        self.assertEqual(len(rejected), 1, msg=repr(results))
        self.assertEqual(InventoryCoordinatorClient(self.admin).get_balance(lid), 0)
        for ok, has_venta, msg, n_ventas in results:
            if not (ok and has_venta):
                self.assertEqual(n_ventas, 0, msg=repr(results))


if __name__ == "__main__":
    unittest.main(verbosity=2)
