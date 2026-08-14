# -*- coding: utf-8 -*-
"""FASE 1D.3: reconexión real tras pérdida de sesión PostgreSQL."""
from __future__ import annotations

import sys
import threading
import time
import unittest
import uuid
from pathlib import Path

import psycopg2

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase1d.helpers import DEVICE, _op_scaled
from tests.fase1d.pg_harness import (
    POSTGRES_SKIP_REASON,
    apply_coordinator_schema,
    backend_pid,
    connect,
    insert_producto,
    postgres_available,
)


def _skip_unless_pg():
    return unittest.skipUnless(postgres_available(), POSTGRES_SKIP_REASON)


class _CommitThenTerminate:
    """Proxy: COMMIT real, luego pg_terminate_backend de ESTA sesión."""

    def __init__(self, real, admin_factory):
        self._real = real
        self._admin_factory = admin_factory
        self.pid = backend_pid(real)
        self.autocommit = False

    def commit(self):
        self._real.commit()
        admin = self._admin_factory()
        try:
            admin.autocommit = True
            with admin.cursor() as cur:
                cur.execute("SELECT pg_terminate_backend(%s)", (self.pid,))
        finally:
            try:
                admin.close()
            except Exception:
                pass
        raise psycopg2.OperationalError(
            "server closed the connection after COMMIT"
        )

    def __getattr__(self, name):
        return getattr(self._real, name)


@_skip_unless_pg()
class Fase1D3ReconnectTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        conn = connect()
        try:
            apply_coordinator_schema(conn)
        finally:
            conn.close()

    def setUp(self):
        self.admin = connect()

    def tearDown(self):
        try:
            self.admin.close()
        except Exception:
            pass

    def _seed_product(self, qty):
        from inventory_coordinator import InventoryCoordinatorClient

        lid = insert_producto(self.admin, stock=0)
        InventoryCoordinatorClient(self.admin).seed_balance(lid, qty)
        return lid

    def _wait_for_lock(self, pid, timeout=12.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.admin.cursor() as cur:
                cur.execute(
                    """
                    SELECT wait_event_type, state, query
                    FROM pg_stat_activity
                    WHERE pid = %s
                    """,
                    (pid,),
                )
                row = cur.fetchone()
            self.admin.rollback()
            if row and row[0] == "Lock":
                return True
            time.sleep(0.05)
        return False

    def test_caida_antes_de_commit_retry_aplica_una_vez(self):
        from inventory_coordinator import (
            CoordinatorUnknownOutcomeError,
            InventoryCoordinatorClient,
            STATE_APPLIED,
        )

        lid = self._seed_product(50000)
        cid = str(uuid.uuid4())
        oid = str(uuid.uuid4())
        ops = [_op_scaled(lid, -50000, operation_id=oid)]
        holder = connect()
        self.addCleanup(holder.close)
        with holder.cursor() as cur:
            cur.execute(
                "SELECT quantity_scaled FROM inventory_balances "
                "WHERE producto_local_id=%s FOR UPDATE",
                (lid,),
            )

        started = threading.Event()
        holder_box = {"pid": None, "err": None}

        def victim():
            conn = connect()
            try:
                holder_box["pid"] = backend_pid(conn)
                started.set()
                InventoryCoordinatorClient(conn).apply_command(
                    command_id=cid,
                    tipo="VENTA",
                    device_id=DEVICE,
                    operations=ops,
                    timeout_seconds=20,
                )
            except Exception as exc:
                holder_box["err"] = exc
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

        thread = threading.Thread(target=victim)
        thread.start()
        self.assertTrue(started.wait(timeout=8))
        self.assertIsNotNone(holder_box["pid"])
        self.assertTrue(self._wait_for_lock(holder_box["pid"]))
        with self.admin.cursor() as cur:
            cur.execute("SELECT pg_terminate_backend(%s)", (holder_box["pid"],))
        self.admin.commit()
        thread.join(timeout=20)
        self.assertIsInstance(holder_box["err"], CoordinatorUnknownOutcomeError)
        holder.rollback()
        holder.close()

        retry_conn = connect()
        self.addCleanup(retry_conn.close)
        self.assertNotEqual(backend_pid(retry_conn), holder_box["pid"])
        rec = InventoryCoordinatorClient(retry_conn).apply_command(
            command_id=cid,
            tipo="VENTA",
            device_id=DEVICE,
            operations=ops,
        )
        self.assertEqual(rec.estado, STATE_APPLIED)
        self.assertFalse(rec.replayed)
        self.assertEqual(InventoryCoordinatorClient(retry_conn).get_balance(lid), 0)

    def test_caida_despues_de_commit_replay_en_conexion_nueva(self):
        from inventory_coordinator import (
            InventoryCoordinatorClient,
            STATE_APPLIED,
        )

        lid = self._seed_product(50000)
        cid = str(uuid.uuid4())
        oid = str(uuid.uuid4())
        ops = [_op_scaled(lid, -50000, operation_id=oid)]
        first_real = connect()
        first_pid = backend_pid(first_real)
        wrapped = _CommitThenTerminate(first_real, connect)
        pids = {"second": None}

        def factory():
            conn = connect()
            pids["second"] = backend_pid(conn)
            return conn

        client = InventoryCoordinatorClient(
            wrapped, connection_factory=factory, timeout_seconds=15
        )
        rec = client.apply_command(
            command_id=cid,
            tipo="VENTA",
            device_id=DEVICE,
            operations=ops,
        )
        self.assertEqual(rec.estado, STATE_APPLIED)
        self.assertTrue(rec.replayed)
        self.assertIsNotNone(pids["second"])
        self.assertNotEqual(pids["second"], first_pid)
        self.assertNotEqual(backend_pid(client.conn), first_pid)
        self.assertEqual(client.get_balance(lid), 0)

    def test_rejected_reconnect_no_reevalua(self):
        from inventory_coordinator import InventoryCoordinatorClient, STATE_REJECTED

        lid = self._seed_product(50000)
        cid = str(uuid.uuid4())
        ops = [_op_scaled(lid, -51000)]
        first_conn = connect()
        try:
            first = InventoryCoordinatorClient(first_conn).apply_command(
                command_id=cid, tipo="VENTA", device_id=DEVICE, operations=ops
            )
            self.assertEqual(first.estado, STATE_REJECTED)
            motivo = first.motivo
            old_pid = backend_pid(first_conn)
        finally:
            try:
                first_conn.close()
            except Exception:
                pass
        with self.admin.cursor() as cur:
            cur.execute(
                "UPDATE inventory_balances SET quantity_scaled = 100000 "
                "WHERE producto_local_id = %s",
                (lid,),
            )
        self.admin.commit()
        retry_conn = connect()
        self.addCleanup(retry_conn.close)
        self.assertNotEqual(backend_pid(retry_conn), old_pid)
        retry = InventoryCoordinatorClient(retry_conn).apply_command(
            command_id=cid, tipo="VENTA", device_id=DEVICE, operations=ops
        )
        self.assertTrue(retry.replayed)
        self.assertEqual(retry.estado, STATE_REJECTED)
        self.assertEqual(retry.motivo, motivo)
        self.assertEqual(
            InventoryCoordinatorClient(retry_conn).get_balance(lid), 100000
        )

    def test_hash_conflict_despues_de_reconnect(self):
        from inventory_coordinator import (
            IdempotencyConflictError,
            InventoryCoordinatorClient,
        )

        lid = self._seed_product(50000)
        cid = str(uuid.uuid4())
        InventoryCoordinatorClient(self.admin).apply_command(
            command_id=cid,
            tipo="VENTA",
            device_id=DEVICE,
            operations=[_op_scaled(lid, -1000)],
        )
        other = connect()
        self.addCleanup(other.close)
        self.assertNotEqual(backend_pid(other), backend_pid(self.admin))
        with self.assertRaises(IdempotencyConflictError):
            InventoryCoordinatorClient(other).apply_command(
                command_id=cid,
                tipo="VENTA",
                device_id=DEVICE,
                operations=[_op_scaled(lid, -2000)],
            )
        self.assertEqual(InventoryCoordinatorClient(other).get_balance(lid), 49000)

    def test_conexion_nueva_es_sesion_distinta_y_autocommit_false(self):
        a = connect()
        b = connect()
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        self.assertFalse(a.autocommit)
        self.assertFalse(b.autocommit)
        self.assertNotEqual(backend_pid(a), backend_pid(b))
        self.assertEqual(a.get_transaction_status(), 0)

    def test_timeout_no_genera_command_id_nuevo(self):
        from inventory_coordinator import apply_inventory_command

        src = (REPO_ROOT / "inventory_coordinator.py").read_text(encoding="utf-8")
        self.assertNotIn("uuid.uuid4()", src)
        lid = self._seed_product(5000)
        cid = str(uuid.uuid4())
        ops = [_op_scaled(lid, -1000)]
        rec = apply_inventory_command(
            self.admin,
            command_id=cid,
            tipo="VENTA",
            device_id=DEVICE,
            operations=ops,
            timeout_seconds=15,
        )
        self.assertEqual(rec.command_id, cid)
        retry = apply_inventory_command(
            self.admin,
            command_id=cid,
            tipo="VENTA",
            device_id=DEVICE,
            operations=ops,
        )
        self.assertEqual(retry.command_id, cid)
        self.assertTrue(retry.replayed)
