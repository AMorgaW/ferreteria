# -*- coding: utf-8 -*-
"""Concurrencia de recepción: incrementos serializados. ferrepro-pg-test."""
from __future__ import annotations

import sys
import threading
import unittest
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase1d.pg_harness import insert_producto, postgres_available
from tests.fase1e.helpers import insert_usuario, seed_producto
from tests.fase1e3.helpers import app_factory, force_postgres_status, pin_env_db
from tests.fase1e4.helpers import prepare_pg
from tests.fase3b.helpers import assert_not_commercial_db, compras_service, phase3b_env


@unittest.skipUnless(
    postgres_available(),
    "POSTGRES INTEGRATION opt-in: ferrepro-pg-test / FERREPRO_PG_TEST_DSN",
)
class ReceivingConcurrencyTest(unittest.TestCase):
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

    def test_18_concurrent_increments_and_duplicate_command(self):
        from inventory_coordinator import InventoryCoordinatorClient
        from inventory_cutover import STATUS_AUTHORITATIVE, STATUS_CUTOVER_IN_PROGRESS

        lid = insert_producto(self.admin, stock=100)
        InventoryCoordinatorClient(self.admin).seed_balance(lid, 100000)
        force_postgres_status(self.admin, STATUS_CUTOVER_IN_PROGRESS)
        force_postgres_status(self.admin, STATUS_AUTHORITATIVE, epoch=1)
        results = []
        barrier = threading.Barrier(2)

        def worker(env, qty, factura, command_id=None):
            pin_env_db(env)
            conn = env.connect()
            try:
                seed_producto(
                    conn, env, stock=100, local_id=lid, codigo=f"RCV-{uuid.uuid4().hex[:6]}"
                )
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            barrier.wait(timeout=15)
            ok, msg, cid = compras_service(env).confirmar_recepcion(
                proveedor_id=1,
                productos=[{"producto_id": 1, "cantidad": qty, "precio_unitario": 50}],
                numero_factura=factura,
                inventory_mode="authoritative",
                inventory_command_id=command_id or str(uuid.uuid4()),
                inventory_connection_factory=app_factory(),
            )
            results.append((ok, msg, cid, qty))

        with phase3b_env() as env1, phase3b_env() as env2:
            assert_not_commercial_db(env1)
            assert_not_commercial_db(env2)
            t1 = threading.Thread(target=worker, args=(env1, 10, "W01-10"))
            t2 = threading.Thread(target=worker, args=(env2, 20, "W02-20"))
            t1.start()
            t2.start()
            t1.join(timeout=30)
            t2.join(timeout=30)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(item[0] for item in results), results)
        from inventory_coordinator import InventoryCoordinatorClient

        self.assertEqual(InventoryCoordinatorClient(self.admin).get_balance(lid), 130000)

        dup_cmd = str(uuid.uuid4())
        with phase3b_env() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=130, local_id=lid, codigo="DUP-R")
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = compras_service(env)
            ok1, msg1, cid1 = svc.confirmar_recepcion(
                proveedor_id=1,
                productos=[{"producto_id": 1, "cantidad": 10, "precio_unitario": 50}],
                numero_factura="DUP-CMD",
                inventory_mode="authoritative",
                inventory_command_id=dup_cmd,
                inventory_connection_factory=app_factory(),
            )
            self.assertTrue(ok1, msg1)
            ok2, msg2, cid2 = svc.confirmar_recepcion(
                compra_id=cid1,
                inventory_mode="authoritative",
                inventory_command_id=dup_cmd,
                inventory_connection_factory=app_factory(),
            )
            self.assertTrue(ok2, msg2)
            self.assertEqual(cid1, cid2)
            self.assertEqual(
                InventoryCoordinatorClient(self.admin).get_balance(lid), 140000
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
