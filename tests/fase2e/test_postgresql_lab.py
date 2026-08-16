from __future__ import annotations

import threading
import unittest
import uuid

from inventory_coordinator import InventoryCoordinatorClient
from tests.fase1d.helpers import DEVICE
from tests.fase1d.pg_harness import (
    apply_coordinator_schema,
    connect,
    connect_as,
    insert_producto,
    provision_inventory_test_roles,
)
from tests.fase1e1.pg_dsn import ensure_pg_test_dsn


class Phase2EPostgreSQLCriticalTest(unittest.TestCase):
    """Laboratorio obligatorio: nunca usa SUPABASE_URI ni conexión owner en app."""

    @classmethod
    def setUpClass(cls):
        if not ensure_pg_test_dsn():
            raise RuntimeError("Fase 2E requiere ferrepro-pg-test localhost:55432")
        conn = connect()
        try:
            apply_coordinator_schema(conn)
            cls.allowed_password = "f2e-" + uuid.uuid4().hex
            provision_inventory_test_roles(
                conn,
                allowed_password=cls.allowed_password,
                denied_password="f2e-denied-" + uuid.uuid4().hex,
            )
        finally:
            conn.close()

    def setUp(self):
        self.conn = connect()
        self.local_id = insert_producto(self.conn, stock=999, nombre="Fase2E CAS")
        self.client = InventoryCoordinatorClient(self.conn)
        self.client.seed_balance(self.local_id, 80000)
        self.command_ids = []

    def tearDown(self):
        try:
            self.conn.rollback()
            with self.conn.cursor() as cur:
                if self.command_ids:
                    cur.execute("DELETE FROM inventory_operations WHERE command_id = ANY(%s)", (self.command_ids,))
                    cur.execute("DELETE FROM inventory_commands WHERE command_id = ANY(%s)", (self.command_ids,))
                cur.execute("DELETE FROM inventory_balances WHERE producto_local_id=%s", (self.local_id,))
                cur.execute("DELETE FROM productos WHERE local_id=%s", (self.local_id,))
            self.conn.commit()
        finally:
            self.conn.close()

    def _operation(self, command_id):
        return {
            "operation_id": str(uuid.uuid5(uuid.UUID(command_id), "line:1")),
            "producto_local_id": self.local_id,
            "line_no": 1,
            "delta_scaled": -5000,
            "expected_base_scaled": 80000,
        }

    def test_67_two_stations_same_expected_base_only_one_applies(self):
        command_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        self.command_ids.extend(command_ids)
        barrier = threading.Barrier(2)
        results = []
        errors = []

        def station(command_id):
            conn = connect_as("ferrepro_inventory_allowed_test", self.allowed_password)
            try:
                barrier.wait(timeout=10)
                result = InventoryCoordinatorClient(conn).apply_command(
                    command_id=command_id, tipo="AJUSTE", device_id=DEVICE,
                    documento_tipo="inventory_reconciliation",
                    documento_local_id=str(uuid.uuid4()),
                    operations=[self._operation(command_id)],
                )
                results.append((result.estado, result.motivo or ""))
            except Exception as exc:
                errors.append(exc)
            finally:
                conn.close()

        threads = [threading.Thread(target=station, args=(cid,)) for cid in command_ids]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertEqual(errors, [])
        self.assertEqual(sum(state == "APPLIED" for state, _ in results), 1)
        self.assertEqual(sum(state == "REJECTED" and "STALE_BALANCE" in reason for state, reason in results), 1)
        self.assertEqual(self.client.get_balance(self.local_id), 75000)

    def test_68_replay_same_inventory_command_is_exactly_once(self):
        command_id = str(uuid.uuid4())
        self.command_ids.append(command_id)
        operation = self._operation(command_id)
        document_id = str(uuid.uuid4())
        app_conn = connect_as("ferrepro_inventory_allowed_test", self.allowed_password)
        self.addCleanup(app_conn.close)
        app_client = InventoryCoordinatorClient(app_conn)
        first = app_client.apply_command(
            command_id=command_id, tipo="AJUSTE", device_id=DEVICE,
            documento_tipo="inventory_reconciliation",
            documento_local_id=document_id, operations=[operation],
        )
        second = app_client.apply_command(
            command_id=command_id, tipo="AJUSTE", device_id=DEVICE,
            documento_tipo="inventory_reconciliation",
            documento_local_id=document_id, operations=[operation],
        )
        self.assertEqual(first.estado, "APPLIED")
        self.assertTrue(second.replayed)
        self.assertEqual(self.client.get_balance(self.local_id), 75000)


if __name__ == "__main__":
    unittest.main()
