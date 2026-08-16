from __future__ import annotations

import sqlite3
import threading
import time
import unittest
import uuid

from inventory_coordinator import (
    CoordinatorUnknownOutcomeError,
    apply_inventory_command,
    seed_inventory_balance,
)
from inventory_cutover import (
    approve_inventory_cutover_snapshot,
    build_cutover_snapshot,
    freeze_inventory_writes,
    initialize_inventory_balances_from_snapshot,
    load_postgres_cutover_state,
    register_inventory_cutover_fleet,
    set_after_legacy_share_hook,
    submit_inventory_cutover_attestation,
)
from inventory_gateway import InventoryGateway, OUTCOME_APPLIED, OUTCOME_UNKNOWN
from inventory_ledger import IdempotencyConflictError
from services.ventas_service import VentasService
from tests.fase0.harness import official_temp_db
from tests.fase1d.pg_harness import connect, insert_producto
from tests.fase1e.helpers import AuthPermitido, insert_usuario, seed_producto
from tests.fase1e4c.helpers import app_factory, prepare_pg, reset_lab_balances, require_pg


class _PathDB:
    def __init__(self, path):
        self.path = str(path)

    def conectar(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn


class Fase1E4DPostgresTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_pg()

    def setUp(self):
        require_pg()
        self.admin = connect()
        reset_lab_balances(self.admin)
        set_after_legacy_share_hook(None)

    def tearDown(self):
        set_after_legacy_share_hook(None)
        reset_lab_balances(self.admin)
        self.admin.close()

    def _submit(self, local, *, cutover_id, epoch, device_id):
        return submit_inventory_cutover_attestation(
            local,
            self.admin,
            cutover_id=cutover_id,
            epoch=epoch,
            device_id=device_id,
            product_catalog_conn=self.admin,
        )

    def test_writer_wins_fence_snapshot_uses_fleet_source(self):
        device_a, device_b = str(uuid.uuid4()), str(uuid.uuid4())
        cutover_id = str(uuid.uuid4())
        with official_temp_db() as env_a:
            with official_temp_db() as env_b:
                lid = str(uuid.uuid4())
                for env, code in ((env_a, "FLEET-A"), (env_b, "FLEET-B")):
                    conn = env.connect()
                    try:
                        seed_producto(conn, env, stock=50, local_id=lid, codigo=code)
                        insert_usuario(conn)
                        conn.commit()
                    finally:
                        conn.close()
                insert_producto(self.admin, local_id=lid, stock=50, nombre="fleet")

                holding = threading.Event()
                release = threading.Event()
                freeze_done = threading.Event()
                results = {}
                errors = []

                def after_share(_status, _epoch):
                    holding.set()
                    if not release.wait(15):
                        raise RuntimeError("writer release timeout")

                set_after_legacy_share_hook(after_share)

                def writer():
                    try:
                        results["sale"] = VentasService(
                            _PathDB(env_a.db_path), None, None, AuthPermitido()
                        ).registrar_venta(
                            [{"producto_id": 1, "cantidad": 5, "precio_unitario": 10}],
                            inventory_mode="LEGACY",
                            inventory_connection_factory=app_factory(),
                        )
                    except Exception as exc:
                        errors.append(exc)

                def freezer():
                    local = admin = None
                    try:
                        local = env_b.connect()
                        admin = connect()
                        freeze_inventory_writes(
                            local, admin_conn=admin, device_id=device_b
                        )
                    except Exception as exc:
                        errors.append(exc)
                    finally:
                        freeze_done.set()
                        for conn in (local, admin):
                            if conn is not None:
                                conn.close()

                writer_thread = threading.Thread(target=writer)
                writer_thread.start()
                self.assertTrue(holding.wait(15))
                freeze_thread = threading.Thread(target=freezer)
                freeze_thread.start()
                self.assertFalse(freeze_done.wait(0.3))
                release.set()
                writer_thread.join(15)
                freeze_thread.join(15)
                self.assertFalse(errors, errors)
                self.assertTrue(results["sale"][0], results["sale"][1])

                epoch = load_postgres_cutover_state(self.admin).epoch
                register_inventory_cutover_fleet(
                    self.admin,
                    cutover_id=cutover_id,
                    epoch=epoch,
                    expected_station_ids=[device_a, device_b],
                )
                conn_a, conn_b = env_a.connect(), env_b.connect()
                try:
                    self.assertEqual(
                        conn_a.execute("SELECT stock FROM productos WHERE id=1").fetchone()[0],
                        45,
                    )
                    self.assertEqual(
                        conn_b.execute("SELECT stock FROM productos WHERE id=1").fetchone()[0],
                        50,
                    )
                    self._submit(
                        conn_a, cutover_id=cutover_id, epoch=epoch, device_id=device_a
                    )
                    self._submit(
                        conn_b, cutover_id=cutover_id, epoch=epoch, device_id=device_b
                    )
                    with self.assertRaisesRegex(Exception, "FLEET_ATTESTATION_DIVERGENT"):
                        approve_inventory_cutover_snapshot(
                            self.admin, cutover_id=cutover_id, epoch=epoch
                        )

                    conn_b.execute("UPDATE productos SET stock=45 WHERE id=1")
                    conn_b.commit()
                    self._submit(
                        conn_b, cutover_id=cutover_id, epoch=epoch, device_id=device_b
                    )
                    approved = approve_inventory_cutover_snapshot(
                        self.admin, cutover_id=cutover_id, epoch=epoch
                    )
                    self.assertEqual(approved.quantity_identity(), ((lid, 45000),))

                    tampered = build_cutover_snapshot(
                        ((lid, 40000),), epoch=epoch, cutover_id=cutover_id
                    )
                    initialize_inventory_balances_from_snapshot(self.admin, tampered)
                    with self.admin.cursor() as cur:
                        cur.execute(
                            "SELECT quantity_scaled FROM inventory_balances "
                            "WHERE producto_local_id=%s",
                            (lid,),
                        )
                        self.assertEqual(cur.fetchone()[0], 45000)
                finally:
                    conn_a.close()
                    conn_b.close()

    def test_missing_station_stale_epoch_and_app_tampering_rejected(self):
        device_a, device_b = str(uuid.uuid4()), str(uuid.uuid4())
        cutover_id = str(uuid.uuid4())
        with official_temp_db() as env:
            local = env.connect()
            try:
                lid = seed_producto(local, env, stock=5)
                insert_producto(self.admin, local_id=lid, stock=5)
                freeze_inventory_writes(local, admin_conn=self.admin, device_id=device_a)
                epoch = load_postgres_cutover_state(self.admin).epoch
                register_inventory_cutover_fleet(
                    self.admin,
                    cutover_id=cutover_id,
                    epoch=epoch,
                    expected_station_ids=[device_a, device_b],
                )
                self._submit(
                    local, cutover_id=cutover_id, epoch=epoch, device_id=device_a
                )
                with self.assertRaisesRegex(Exception, "FLEET_ATTESTATION_MISSING"):
                    approve_inventory_cutover_snapshot(
                        self.admin, cutover_id=cutover_id, epoch=epoch
                    )
                remote = app_factory()()
                try:
                    with self.assertRaises(Exception):
                        submit_inventory_cutover_attestation(
                            local,
                            remote,
                            cutover_id=cutover_id,
                            epoch=epoch + 1,
                            device_id=device_b,
                            product_catalog_conn=self.admin,
                        )
                    remote.rollback()
                    with self.assertRaises(Exception):
                        with remote.cursor() as cur:
                            cur.execute(
                                "UPDATE inventory_cutover_snapshots SET checksum='x' "
                                "WHERE cutover_id=%s",
                                (cutover_id,),
                            )
                    remote.rollback()
                finally:
                    remote.close()
            finally:
                local.close()

    def test_seed_recomputes_approved_checksum_after_admin_line_tampering(self):
        device_id = str(uuid.uuid4())
        cutover_id = str(uuid.uuid4())
        with official_temp_db() as env:
            local = env.connect()
            try:
                lid = seed_producto(local, env, stock=5)
                insert_producto(self.admin, local_id=lid, stock=5)
                freeze_inventory_writes(
                    local, admin_conn=self.admin, device_id=device_id
                )
                epoch = load_postgres_cutover_state(self.admin).epoch
                register_inventory_cutover_fleet(
                    self.admin,
                    cutover_id=cutover_id,
                    epoch=epoch,
                    expected_station_ids=[device_id],
                )
                self._submit(
                    local,
                    cutover_id=cutover_id,
                    epoch=epoch,
                    device_id=device_id,
                )
                approved = approve_inventory_cutover_snapshot(
                    self.admin, cutover_id=cutover_id, epoch=epoch
                )
                with self.admin.cursor() as cur:
                    cur.execute(
                        "UPDATE inventory_cutover_snapshot_lines "
                        "SET quantity_scaled=4000 "
                        "WHERE cutover_id=%s AND producto_local_id=%s",
                        (cutover_id, lid),
                    )
                self.admin.commit()

                with self.assertRaisesRegex(Exception, "INVENTORY_SNAPSHOT_INVALID"):
                    initialize_inventory_balances_from_snapshot(self.admin, approved)
                self.admin.rollback()
                with self.admin.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM inventory_balances")
                    self.assertEqual(cur.fetchone()[0], 0)
                    cur.execute(
                        "SELECT status FROM inventory_cutover_snapshots "
                        "WHERE cutover_id=%s",
                        (cutover_id,),
                    )
                    self.assertEqual(cur.fetchone()[0], "APPROVED")
                self.admin.rollback()
            finally:
                local.close()

    def _coordinator_case(self, *, balance, expected, delta):
        lid, command_id, operation_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
        insert_producto(self.admin, local_id=lid, stock=balance / 1000)
        seed_inventory_balance(self.admin, lid, balance)
        operation = {
            "operation_id": operation_id,
            "producto_local_id": lid,
            "line_no": 1,
            "delta_scaled": delta,
            "expected_base_scaled": expected,
        }
        return lid, command_id, operation

    def test_expected_base_applied_and_rejected_replay_or_conflict(self):
        remote = app_factory()()
        try:
            for balance, expected, delta, expected_state in (
                (50000, 50000, -1000, "APPLIED"),
                (500, 500, -1000, "REJECTED"),
            ):
                _lid, command_id, operation = self._coordinator_case(
                    balance=balance, expected=expected, delta=delta
                )
                common = {
                    "command_id": command_id,
                    "tipo": "AJUSTE",
                    "documento_tipo": "ajuste",
                    "device_id": str(uuid.uuid4()),
                }
                first = apply_inventory_command(remote, operations=[operation], **common)
                same = apply_inventory_command(remote, operations=[operation], **common)
                self.assertEqual(first.estado, expected_state)
                self.assertTrue(same.replayed)
                changed = dict(operation)
                changed["expected_base_scaled"] = expected - 1
                with self.assertRaises(IdempotencyConflictError):
                    apply_inventory_command(remote, operations=[changed], **common)
        finally:
            remote.close()

    def test_unknown_reconnect_keeps_expected_base_identity(self):
        with official_temp_db() as env:
            local = env.connect()
            try:
                lid = seed_producto(local, env, stock=50)
                insert_producto(self.admin, local_id=lid, stock=50)
                seed_inventory_balance(self.admin, lid, 50000)
                command_id, operation_id = str(uuid.uuid4()), str(uuid.uuid4())
                operation = {
                    "operation_id": operation_id,
                    "producto_local_id": lid,
                    "line_no": 1,
                    "delta_scaled": -1000,
                    "expected_base_scaled": 50000,
                }

                def applied_then_unknown(**payload):
                    apply_inventory_command(connection_factory=app_factory(), **payload)
                    raise CoordinatorUnknownOutcomeError("simulated post-commit disconnect")

                gateway = InventoryGateway(
                    local, cutover_enabled=True, transport=applied_then_unknown
                )
                common = {
                    "tipo": "AJUSTE",
                    "command_id": command_id,
                    "documento_tipo": "ajuste",
                    "device_id": str(uuid.uuid4()),
                }
                unknown = gateway.submit(operations=[operation], **common)
                self.assertEqual(unknown.outcome, OUTCOME_UNKNOWN)
                changed = dict(operation)
                changed["expected_base_scaled"] = 40000
                with self.assertRaises(IdempotencyConflictError):
                    gateway.submit(operations=[changed], **common)

                replay = InventoryGateway(
                    local, cutover_enabled=True, connection_factory=app_factory()
                ).submit(operations=[operation], **common)
                self.assertEqual(replay.outcome, OUTCOME_APPLIED)
                self.assertTrue(replay.record.replayed or replay.record.estado == "APPLIED")
            finally:
                local.close()


if __name__ == "__main__":
    unittest.main()
