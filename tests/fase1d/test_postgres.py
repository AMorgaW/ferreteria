# -*- coding: utf-8 -*-
"""FASE 1D POSTGRES INTEGRATION: locking, idempotencia y atomicidad reales.

Opt-in: FERREPRO_PG_TEST_DSN. No SQLite. No SUPABASE_URI.
Sin DSN estos tests se saltan; eso NO certifica concurrencia PostgreSQL.
"""
from __future__ import annotations

import sys
import threading
import unittest
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase1d.helpers import DEVICE, _op, _op_scaled
from tests.fase1d.pg_harness import (
    POSTGRES_SKIP_REASON,
    apply_coordinator_schema,
    connect,
    insert_producto,
    postgres_available,
)


def _skip_unless_pg():
    return unittest.skipUnless(postgres_available(), POSTGRES_SKIP_REASON)


@_skip_unless_pg()
class PostgresIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        conn = connect()
        try:
            apply_coordinator_schema(conn)
        finally:
            conn.close()

    def setUp(self):
        self.conn = connect()

    def tearDown(self):
        try:
            self.conn.close()
        except Exception:
            pass

    def _client(self, conn=None):
        from inventory_coordinator import InventoryCoordinatorClient

        return InventoryCoordinatorClient(conn or self.conn, timeout_seconds=15)

    def _seed_product(self, qty, *, stock_legacy=999999, conn=None):
        c = conn or self.conn
        lid = insert_producto(c, stock=stock_legacy)
        self._client(c).seed_balance(lid, qty)
        return lid

    def test_01_applied_deja_balance_cero(self):
        from inventory_coordinator import STATE_APPLIED

        lid = self._seed_product(50000)
        rec = self._client().apply_command(
            command_id=str(uuid.uuid4()),
            tipo="VENTA",
            device_id=DEVICE,
            operations=[_op_scaled(lid, -50000)],
        )
        self.assertEqual(rec.estado, STATE_APPLIED)
        self.assertEqual(rec.resultado, STATE_APPLIED)
        self.assertFalse(rec.replayed)
        self.assertEqual(self._client().get_balance(lid), 0)

    def test_02_insuficiente_no_cambia_balance(self):
        from inventory_coordinator import MOTIVO_INSUFFICIENT_STOCK, STATE_REJECTED

        lid = self._seed_product(50000)
        rec = self._client().apply_command(
            command_id=str(uuid.uuid4()),
            tipo="VENTA",
            device_id=DEVICE,
            operations=[_op_scaled(lid, -51000)],
        )
        self.assertEqual(rec.estado, STATE_REJECTED)
        self.assertIn(MOTIVO_INSUFFICIENT_STOCK, rec.motivo or "")
        self.assertEqual(self._client().get_balance(lid), 50000)

    def test_03_y_escenario_dos_cajas_ultimo_stock(self):
        """El escenario que motivó el rediseño: 50 vs 50 concurrentes."""
        from inventory_coordinator import STATE_APPLIED, STATE_REJECTED

        lid = self._seed_product(50000)
        results = []
        errors = []
        barrier = threading.Barrier(2)

        def worker(delta_cmd):
            conn = connect()
            try:
                barrier.wait(timeout=10)
                rec = self._client(conn).apply_command(
                    command_id=str(uuid.uuid4()),
                    tipo="VENTA",
                    device_id=DEVICE,
                    operations=[_op_scaled(lid, -50000)],
                )
                results.append(rec.estado)
            except Exception as exc:
                errors.append(exc)
            finally:
                conn.close()

        t1 = threading.Thread(target=worker, args=("A",))
        t2 = threading.Thread(target=worker, args=("B",))
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)
        self.assertEqual(errors, [])
        self.assertEqual(results.count(STATE_APPLIED), 1)
        self.assertEqual(results.count(STATE_REJECTED), 1)
        self.assertEqual(self._client().get_balance(lid), 0)

    def test_04_retry_applied_no_doble_delta(self):
        lid = self._seed_product(50000)
        cid = str(uuid.uuid4())
        oid = str(uuid.uuid4())
        ops = [_op_scaled(lid, -50000, operation_id=oid)]
        first = self._client().apply_command(
            command_id=cid, tipo="VENTA", device_id=DEVICE, operations=ops
        )
        second = self._client().apply_command(
            command_id=cid, tipo="VENTA", device_id=DEVICE, operations=ops
        )
        self.assertEqual(first.estado, "APPLIED")
        self.assertTrue(second.replayed)
        self.assertEqual(second.estado, first.estado)
        self.assertEqual(second.request_hash, first.request_hash)
        self.assertEqual(self._client().get_balance(lid), 0)

    def test_05_retry_rejected_conserva_motivo(self):
        lid = self._seed_product(50000)
        cid = str(uuid.uuid4())
        ops = [_op_scaled(lid, -51000)]
        first = self._client().apply_command(
            command_id=cid, tipo="VENTA", device_id=DEVICE, operations=ops
        )
        second = self._client().apply_command(
            command_id=cid, tipo="VENTA", device_id=DEVICE, operations=ops
        )
        self.assertEqual(first.estado, "REJECTED")
        self.assertTrue(second.replayed)
        self.assertEqual(second.motivo, first.motivo)
        self.assertEqual(self._client().get_balance(lid), 50000)

    def test_06_hash_distinto_conflicto(self):
        from inventory_coordinator import IdempotencyConflictError

        lid = self._seed_product(50000)
        cid = str(uuid.uuid4())
        self._client().apply_command(
            command_id=cid,
            tipo="VENTA",
            device_id=DEVICE,
            operations=[_op_scaled(lid, -1000)],
        )
        with self.assertRaises(IdempotencyConflictError):
            self._client().apply_command(
                command_id=cid,
                tipo="VENTA",
                device_id=DEVICE,
                operations=[_op_scaled(lid, -2000)],
            )
        self.assertEqual(self._client().get_balance(lid), 49000)

    def test_07_timeout_simulado_post_commit(self):
        lid = self._seed_product(50000)
        cid = str(uuid.uuid4())
        ops = [_op_scaled(lid, -50000)]
        first = self._client().apply_command(
            command_id=cid, tipo="VENTA", device_id=DEVICE, operations=ops
        )
        self.assertEqual(first.estado, "APPLIED")
        other = connect()
        try:
            retry = self._client(other).apply_command(
                command_id=cid, tipo="VENTA", device_id=DEVICE, operations=ops
            )
        finally:
            other.close()
        self.assertTrue(retry.replayed)
        self.assertEqual(retry.estado, "APPLIED")
        self.assertEqual(self._client().get_balance(lid), 0)

    def test_08_multilinea_suficiente(self):
        x = self._seed_product(10000)
        y = self._seed_product(5000)
        z = self._seed_product(3000)
        rec = self._client().apply_command(
            command_id=str(uuid.uuid4()),
            tipo="VENTA",
            device_id=DEVICE,
            operations=[
                _op_scaled(x, -5000, line_no=1),
                _op_scaled(y, -2000, line_no=2),
                _op_scaled(z, -1000, line_no=3),
            ],
        )
        self.assertEqual(rec.estado, "APPLIED")
        self.assertEqual(self._client().get_balance(x), 5000)
        self.assertEqual(self._client().get_balance(y), 3000)
        self.assertEqual(self._client().get_balance(z), 2000)

    def test_09_multilinea_parcial_no_aplica(self):
        x = self._seed_product(10000)
        y = self._seed_product(1000)
        rec = self._client().apply_command(
            command_id=str(uuid.uuid4()),
            tipo="VENTA",
            device_id=DEVICE,
            operations=[
                _op_scaled(x, -5000, line_no=1),
                _op_scaled(y, -2000, line_no=2),
            ],
        )
        self.assertEqual(rec.estado, "REJECTED")
        self.assertEqual(self._client().get_balance(x), 10000)
        self.assertEqual(self._client().get_balance(y), 1000)

    def test_10_orden_inverso_sin_deadlock(self):
        x = self._seed_product(10000)
        y = self._seed_product(10000)
        results = []
        errors = []
        barrier = threading.Barrier(2)

        def worker(ops):
            conn = connect()
            try:
                barrier.wait(timeout=10)
                rec = self._client(conn).apply_command(
                    command_id=str(uuid.uuid4()),
                    tipo="VENTA",
                    device_id=DEVICE,
                    operations=ops,
                    timeout_seconds=20,
                )
                results.append(rec.estado)
            except Exception as exc:
                errors.append(exc)
            finally:
                conn.close()

        t1 = threading.Thread(
            target=worker,
            args=([_op_scaled(x, -1000, 1), _op_scaled(y, -1000, 2)],),
        )
        t2 = threading.Thread(
            target=worker,
            args=([_op_scaled(y, -1000, 1), _op_scaled(x, -1000, 2)],),
        )
        t1.start()
        t2.start()
        t1.join(timeout=40)
        t2.join(timeout=40)
        self.assertEqual(errors, [])
        self.assertEqual(results, ["APPLIED", "APPLIED"])
        self.assertEqual(self._client().get_balance(x), 8000)
        self.assertEqual(self._client().get_balance(y), 8000)

    def test_11_operation_id_repetido(self):
        from inventory_coordinator import DuplicateOperationError

        a = self._seed_product(50000)
        b = self._seed_product(50000)
        oid = str(uuid.uuid4())
        self._client().apply_command(
            command_id=str(uuid.uuid4()),
            tipo="VENTA",
            device_id=DEVICE,
            operations=[_op_scaled(a, -1000, operation_id=oid)],
        )
        with self.assertRaises(DuplicateOperationError):
            self._client().apply_command(
                command_id=str(uuid.uuid4()),
                tipo="VENTA",
                device_id=DEVICE,
                operations=[_op_scaled(b, -1000, operation_id=oid)],
            )
        self.assertEqual(self._client().get_balance(a), 49000)
        self.assertEqual(self._client().get_balance(b), 50000)

    def test_12_delta_positivo(self):
        lid = self._seed_product(50000)
        rec = self._client().apply_command(
            command_id=str(uuid.uuid4()),
            tipo="COMPRA",
            device_id=DEVICE,
            operations=[_op_scaled(lid, 20000)],
        )
        self.assertEqual(rec.estado, "APPLIED")
        self.assertEqual(self._client().get_balance(lid), 70000)

    def test_13_negativo_sin_balance(self):
        from inventory_coordinator import MOTIVO_BALANCE_NOT_FOUND

        lid = insert_producto(self.conn, stock=50)
        rec = self._client().apply_command(
            command_id=str(uuid.uuid4()),
            tipo="VENTA",
            device_id=DEVICE,
            operations=[_op_scaled(lid, -1000)],
        )
        self.assertEqual(rec.estado, "REJECTED")
        self.assertIn(MOTIVO_BALANCE_NOT_FOUND, rec.motivo or "")
        self.assertIsNone(self._client().get_balance(lid))

    def test_14_fixed_point_exacto(self):
        lid = self._seed_product(1500)
        rec = self._client().apply_command(
            command_id=str(uuid.uuid4()),
            tipo="VENTA",
            device_id=DEVICE,
            operations=[_op(lid, "-1.5")],
        )
        self.assertEqual(rec.operations[0].delta_scaled, -1500)
        self.assertEqual(self._client().get_balance(lid), 0)

    def test_18_producto_desconocido(self):
        from inventory_coordinator import MOTIVO_UNKNOWN_PRODUCT

        ghost = str(uuid.uuid4())
        rec = self._client().apply_command(
            command_id=str(uuid.uuid4()),
            tipo="VENTA",
            device_id=DEVICE,
            operations=[_op_scaled(ghost, -1000)],
        )
        self.assertEqual(rec.estado, "REJECTED")
        self.assertIn(MOTIVO_UNKNOWN_PRODUCT, rec.motivo or "")
        self.assertIsNone(self._client().get_balance(ghost))

    def test_20_21_applied_tras_update_rejected_sin_cambio(self):
        lid = self._seed_product(50000)
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT updated_at FROM inventory_balances WHERE producto_local_id=%s",
                (lid,),
            )
            before = cur.fetchone()[0]
        self.conn.rollback()
        applied = self._client().apply_command(
            command_id=str(uuid.uuid4()),
            tipo="VENTA",
            device_id=DEVICE,
            operations=[_op_scaled(lid, -1000)],
        )
        self.assertEqual(applied.estado, "APPLIED")
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT quantity_scaled, updated_at FROM inventory_balances "
                "WHERE producto_local_id=%s",
                (lid,),
            )
            qty, after = cur.fetchone()
        self.conn.rollback()
        self.assertEqual(int(qty), 49000)
        self.assertNotEqual(after, before)
        rejected = self._client().apply_command(
            command_id=str(uuid.uuid4()),
            tipo="VENTA",
            device_id=DEVICE,
            operations=[_op_scaled(lid, -999999)],
        )
        self.assertEqual(rejected.estado, "REJECTED")
        self.assertEqual(self._client().get_balance(lid), 49000)

    def test_22_persistencia_nueva_conexion(self):
        lid = self._seed_product(50000)
        cid = str(uuid.uuid4())
        ops = [_op_scaled(lid, -50000)]
        self._client().apply_command(
            command_id=cid, tipo="VENTA", device_id=DEVICE, operations=ops
        )
        self.conn.close()
        other = connect()
        self.addCleanup(other.close)
        from inventory_coordinator import InventoryCoordinatorClient

        retry = InventoryCoordinatorClient(other).apply_command(
            command_id=cid, tipo="VENTA", device_id=DEVICE, operations=ops
        )
        self.assertTrue(retry.replayed)
        self.assertEqual(retry.estado, "APPLIED")
        self.assertEqual(InventoryCoordinatorClient(other).get_balance(lid), 0)

    def test_23_24_stock_legacy_no_contamina(self):
        lid = insert_producto(self.conn, stock=7)
        self._client().seed_balance(lid, 50000)
        rec = self._client().apply_command(
            command_id=str(uuid.uuid4()),
            tipo="VENTA",
            device_id=DEVICE,
            operations=[_op_scaled(lid, -50000)],
        )
        self.assertEqual(rec.estado, "APPLIED")
        self.assertEqual(self._client().get_balance(lid), 0)
        with self.conn.cursor() as cur:
            cur.execute("SELECT stock FROM productos WHERE local_id=%s", (lid,))
            self.assertEqual(int(cur.fetchone()[0]), 7)

    def test_26_27_rpc_no_public_search_path(self):
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT pg_get_functiondef(p.oid)
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname='public' AND p.proname='apply_inventory_command'
                """
            )
            defn = cur.fetchone()[0]
            self.assertIn("SET search_path TO 'pg_catalog', 'public'", defn)
            cur.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.role_routine_grants
                WHERE routine_schema='public'
                  AND routine_name='apply_inventory_command'
                  AND grantee='PUBLIC'
                  AND privilege_type='EXECUTE'
                """
            )
            self.assertEqual(int(cur.fetchone()[0]), 0)

    def test_28_sql_idempotente_dos_aplicaciones(self):
        apply_coordinator_schema(self.conn)
        apply_coordinator_schema(self.conn)
        lid = self._seed_product(1000)
        self.assertEqual(self._client().get_balance(lid), 1000)

    def test_29_semilla_no_pisa_balance_nuevo(self):
        lid = insert_producto(self.conn, stock=1)
        first = self._client().seed_balance(lid, 50000)
        self.assertTrue(first.created)
        rec = self._client().apply_command(
            command_id=str(uuid.uuid4()),
            tipo="COMPRA",
            device_id=DEVICE,
            operations=[_op_scaled(lid, 1000)],
        )
        self.assertEqual(rec.estado, "APPLIED")
        second = self._client().seed_balance(lid, 1)
        self.assertFalse(second.created)
        self.assertEqual(second.quantity_scaled, 51000)
        from inventory_coordinator import initialize_inventory_balances_from_legacy

        initialize_inventory_balances_from_legacy(self.conn)
        self.assertEqual(self._client().get_balance(lid), 51000)

    def test_positivo_crea_fila_ausente(self):
        lid = insert_producto(self.conn, stock=0)
        rec = self._client().apply_command(
            command_id=str(uuid.uuid4()),
            tipo="COMPRA",
            device_id=DEVICE,
            operations=[_op_scaled(lid, 20000)],
        )
        self.assertEqual(rec.estado, "APPLIED")
        self.assertEqual(self._client().get_balance(lid), 20000)

    def test_unique_violation_no_es_replay(self):
        from inventory_coordinator import DuplicateOperationError
        from psycopg2.errors import UniqueViolation

        a = self._seed_product(50000)
        b = self._seed_product(50000)
        oid = str(uuid.uuid4())
        first = self._client().apply_command(
            command_id=str(uuid.uuid4()),
            tipo="VENTA",
            device_id=DEVICE,
            operations=[_op_scaled(a, -1000, operation_id=oid)],
        )
        self.assertEqual(first.estado, "APPLIED")
        self.assertFalse(first.replayed)
        with self.assertRaises(DuplicateOperationError) as ctx:
            self._client().apply_command(
                command_id=str(uuid.uuid4()),
                tipo="VENTA",
                device_id=DEVICE,
                operations=[_op_scaled(b, -1000, operation_id=oid)],
            )
        self.assertNotIn("ya se proces", str(ctx.exception).lower())
        self.assertEqual(self._client().get_balance(a), 49000)
        self.assertEqual(self._client().get_balance(b), 50000)
        recovered = self._client().apply_command(
            command_id=str(uuid.uuid4()),
            tipo="VENTA",
            device_id=DEVICE,
            operations=[_op_scaled(b, -1000)],
        )
        self.assertEqual(recovered.estado, "APPLIED")
        self.assertFalse(recovered.replayed)
        self.assertEqual(self._client().get_balance(b), 49000)

        lid = insert_producto(self.conn, stock=0)
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT conname FROM pg_constraint con "
                "JOIN pg_class c ON c.oid = con.conrelid "
                "WHERE c.relname = 'inventory_balances' AND con.contype = 'p'"
            )
            self.assertEqual(cur.fetchone()[0], "pk_inventory_balances")
            cur.execute(
                """
                INSERT INTO inventory_balances (
                    producto_local_id, quantity_scaled, created_at, updated_at
                ) VALUES (%s, 1000, 't', 't')
                """,
                (lid,),
            )
        self.conn.commit()
        with self.assertRaises(UniqueViolation):
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO inventory_balances (
                        producto_local_id, quantity_scaled, created_at, updated_at
                    ) VALUES (%s, 1, 't', 't')
                    """,
                    (lid,),
                )
        self.conn.rollback()
        other = self._client().apply_command(
            command_id=str(uuid.uuid4()),
            tipo="COMPRA",
            device_id=DEVICE,
            operations=[_op_scaled(lid, 2000)],
        )
        self.assertEqual(other.estado, "APPLIED")
        self.assertFalse(other.replayed)
        self.assertEqual(self._client().get_balance(lid), 3000)
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT pg_get_functiondef(p.oid)
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname='public' AND p.proname='apply_inventory_command'
                """
            )
            defn = cur.fetchone()[0]
        self.assertIn("GET STACKED DIAGNOSTICS", defn)
        self.assertIn("pk_inventory_commands", defn)
        self.assertIn("inventory_commands_pkey", defn)
        self.assertIn("pk_inventory_balances", defn)
        self.assertIn("inventory_balances_pkey", defn)

    def test_overflow_bigint_real_no_cambia_balance(self):
        from inventory_coordinator import BIGINT_MAX, MOTIVO_QUANTITY_OVERFLOW

        lid = self._seed_product(BIGINT_MAX)
        rec = self._client().apply_command(
            command_id=str(uuid.uuid4()),
            tipo="COMPRA",
            device_id=DEVICE,
            operations=[_op_scaled(lid, 1)],
        )
        self.assertEqual(rec.estado, "REJECTED")
        self.assertIn(MOTIVO_QUANTITY_OVERFLOW, rec.motivo or "")
        self.assertEqual(self._client().get_balance(lid), BIGINT_MAX)

    def test_fixed_point_0125(self):
        lid = self._seed_product(125)
        rec = self._client().apply_command(
            command_id=str(uuid.uuid4()),
            tipo="VENTA",
            device_id=DEVICE,
            operations=[_op(lid, "-0.125")],
        )
        self.assertEqual(rec.operations[0].delta_scaled, -125)
        self.assertEqual(self._client().get_balance(lid), 0)

    def test_set_local_timeout_no_fuga_y_rollback(self):
        lid = self._seed_product(5000)
        self._client().apply_command(
            command_id=str(uuid.uuid4()),
            tipo="VENTA",
            device_id=DEVICE,
            operations=[_op_scaled(lid, -1000)],
            timeout_seconds=15,
        )
        with self.conn.cursor() as cur:
            cur.execute("SHOW statement_timeout")
            shown = str(cur.fetchone()[0]).strip().lower().replace(" ", "")
        self.assertNotIn(shown, ("15s", "15sec", "15000ms", "15000"))
        with self.conn.cursor() as cur:
            try:
                cur.execute("SELECT 1/0")
            except Exception:
                pass
        self.conn.rollback()
        rec = self._client().apply_command(
            command_id=str(uuid.uuid4()),
            tipo="VENTA",
            device_id=DEVICE,
            operations=[_op_scaled(lid, -1000)],
        )
        self.assertEqual(rec.estado, "APPLIED")
        self.assertEqual(self._client().get_balance(lid), 3000)
