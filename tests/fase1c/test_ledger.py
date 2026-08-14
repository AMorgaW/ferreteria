# -*- coding: utf-8 -*-
"""FASE 1C: comando de inventario, idempotencia, fixed-point y schema."""
from __future__ import annotations

import sys
import threading
import unittest
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase0.harness import official_temp_db


DEVICE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def _seed(conn, env, *, stock=50, local_id=None, producto_id=1):
    lid = local_id or str(uuid.uuid4())
    env.insert_proveedor(conn)
    env.insert_producto(
        conn,
        producto_id=producto_id,
        stock=stock,
        local_id=lid,
        codigo=f"TEST-1C-{producto_id:03d}",
    )
    conn.commit()
    return lid


def _op(producto_local_id, delta, line_no=1, operation_id=None, **extra):
    payload = {
        "operation_id": operation_id or str(uuid.uuid4()),
        "producto_local_id": producto_local_id,
        "line_no": line_no,
        "delta": delta,
    }
    payload.update(extra)
    return payload


class ComandoEIdempotenciaTest(unittest.TestCase):
    def test_comando_una_linea(self):
        from inventory_ledger import create_inventory_command

        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = _seed(conn, env)
                cid = str(uuid.uuid4())
                oid = str(uuid.uuid4())
                rec = create_inventory_command(
                    conn,
                    command_id=cid,
                    tipo="VENTA",
                    device_id=DEVICE,
                    operations=[_op(lid, "-5", operation_id=oid)],
                )
                self.assertEqual(rec.command_id, cid)
                self.assertEqual(len(rec.operations), 1)
                self.assertEqual(rec.operations[0].operation_id, oid)
                self.assertEqual(rec.operations[0].delta_scaled, -5000)
                self.assertEqual(rec.estado, "PERSISTED")
                self.assertEqual(rec.resultado, "PERSISTED")
                self.assertFalse(rec.replayed)
            finally:
                conn.close()

    def test_comando_multilinea(self):
        from inventory_ledger import create_inventory_command

        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid_a = _seed(conn, env, producto_id=1)
                lid_b = str(uuid.uuid4())
                env.insert_producto(
                    conn, producto_id=2, stock=20, local_id=lid_b, codigo="TEST-1C-002"
                )
                lid_c = str(uuid.uuid4())
                env.insert_producto(
                    conn, producto_id=3, stock=10, local_id=lid_c, codigo="TEST-1C-003"
                )
                conn.commit()
                rec = create_inventory_command(
                    conn,
                    command_id=str(uuid.uuid4()),
                    tipo="VENTA",
                    device_id=DEVICE,
                    documento_tipo="venta",
                    documento_local_id=str(uuid.uuid4()),
                    operations=[
                        _op(lid_a, "-5", 1),
                        _op(lid_b, "-2", 2),
                        _op(lid_c, "-1", 3),
                    ],
                )
                self.assertEqual(len(rec.operations), 3)
                self.assertEqual(
                    [op.delta_scaled for op in rec.operations],
                    [-5000, -2000, -1000],
                )
            finally:
                conn.close()

    def test_command_id_uuid_unique(self):
        from inventory_ledger import (
            IdempotencyConflictError,
            create_inventory_command,
        )

        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = _seed(conn, env)
                cid = str(uuid.uuid4())
                create_inventory_command(
                    conn,
                    command_id=cid,
                    tipo="VENTA",
                    device_id=DEVICE,
                    operations=[_op(lid, "-1")],
                )
                with self.assertRaises(IdempotencyConflictError):
                    create_inventory_command(
                        conn,
                        command_id=cid,
                        tipo="VENTA",
                        device_id=DEVICE,
                        operations=[_op(lid, "-2")],
                    )
                n = conn.execute(
                    "SELECT COUNT(*) FROM inventory_commands WHERE command_id=?",
                    (cid,),
                ).fetchone()[0]
                self.assertEqual(n, 1)
            finally:
                conn.close()

    def test_operation_id_uuid_unique_y_otro_comando(self):
        from inventory_ledger import (
            DuplicateOperationError,
            create_inventory_command,
        )

        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = _seed(conn, env)
                oid = str(uuid.uuid4())
                create_inventory_command(
                    conn,
                    command_id=str(uuid.uuid4()),
                    tipo="VENTA",
                    device_id=DEVICE,
                    operations=[_op(lid, "-1", operation_id=oid)],
                )
                cid_b = str(uuid.uuid4())
                oid_new = str(uuid.uuid4())
                with self.assertRaises(DuplicateOperationError):
                    create_inventory_command(
                        conn,
                        command_id=cid_b,
                        tipo="VENTA",
                        device_id=DEVICE,
                        operations=[
                            _op(lid, "-1", 1, oid_new),
                            _op(lid, "-1", 2, oid),
                        ],
                    )
                self.assertIsNone(
                    conn.execute(
                        "SELECT 1 FROM inventory_commands WHERE command_id=?",
                        (cid_b,),
                    ).fetchone()
                )
                self.assertIsNone(
                    conn.execute(
                        "SELECT 1 FROM inventory_operations WHERE operation_id=?",
                        (oid_new,),
                    ).fetchone()
                )
            finally:
                conn.close()

    def test_unique_command_id_line_no(self):
        from inventory_ledger import InventoryLedgerError, create_inventory_command

        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = _seed(conn, env)
                with self.assertRaises(InventoryLedgerError):
                    create_inventory_command(
                        conn,
                        command_id=str(uuid.uuid4()),
                        tipo="VENTA",
                        device_id=DEVICE,
                        operations=[
                            _op(lid, "-1", 1),
                            _op(lid, "-2", 1),
                        ],
                    )
            finally:
                conn.close()

    def test_retry_idempotente_mismo_payload(self):
        from inventory_ledger import create_inventory_command

        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = _seed(conn, env)
                cid = str(uuid.uuid4())
                oid = str(uuid.uuid4())
                ops = [_op(lid, "-50", operation_id=oid)]
                first = create_inventory_command(
                    conn,
                    command_id=cid,
                    tipo="VENTA",
                    device_id=DEVICE,
                    operations=ops,
                )
                second = create_inventory_command(
                    conn,
                    command_id=cid,
                    tipo="VENTA",
                    device_id=DEVICE,
                    operations=ops,
                )
                self.assertTrue(second.replayed)
                self.assertEqual(first.request_hash, second.request_hash)
                self.assertEqual(first.estado, second.estado)
                self.assertEqual(first.resultado, second.resultado)
                self.assertEqual(
                    [op.operation_id for op in first.operations],
                    [op.operation_id for op in second.operations],
                )
                n_cmd = conn.execute(
                    "SELECT COUNT(*) FROM inventory_commands"
                ).fetchone()[0]
                n_op = conn.execute(
                    "SELECT COUNT(*) FROM inventory_operations"
                ).fetchone()[0]
                self.assertEqual(n_cmd, 1)
                self.assertEqual(n_op, 1)
            finally:
                conn.close()

    def test_retry_payload_distinto_es_conflicto(self):
        from inventory_ledger import (
            IdempotencyConflictError,
            create_inventory_command,
        )

        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = _seed(conn, env)
                cid = str(uuid.uuid4())
                oid = str(uuid.uuid4())
                create_inventory_command(
                    conn,
                    command_id=cid,
                    tipo="VENTA",
                    device_id=DEVICE,
                    operations=[_op(lid, "-50", operation_id=oid)],
                )
                with self.assertRaises(IdempotencyConflictError):
                    create_inventory_command(
                        conn,
                        command_id=cid,
                        tipo="VENTA",
                        device_id=DEVICE,
                        operations=[_op(lid, "-40", operation_id=oid)],
                    )
            finally:
                conn.close()

    def test_hash_equivalente_por_orden(self):
        from inventory_ledger import command_request_hash, quantity_to_scaled

        cid = str(uuid.uuid4())
        oid_a = str(uuid.uuid4())
        oid_b = str(uuid.uuid4())
        lid_a = str(uuid.uuid4())
        lid_b = str(uuid.uuid4())
        scaled_a = quantity_to_scaled("-5")
        scaled_b = quantity_to_scaled("-2")
        first = command_request_hash(
            command_id=cid,
            tipo="VENTA",
            documento_tipo="venta",
            documento_local_id=None,
            operations=[
                {
                    "line_no": 1,
                    "operation_id": oid_a,
                    "producto_local_id": lid_a,
                    "delta_scaled": scaled_a,
                },
                {
                    "line_no": 2,
                    "operation_id": oid_b,
                    "producto_local_id": lid_b,
                    "delta_scaled": scaled_b,
                },
            ],
        )
        second = command_request_hash(
            command_id=cid,
            tipo="VENTA",
            documento_tipo="venta",
            documento_local_id=None,
            operations=[
                {
                    "line_no": 2,
                    "operation_id": oid_b,
                    "producto_local_id": lid_b,
                    "delta_scaled": scaled_b,
                },
                {
                    "line_no": 1,
                    "operation_id": oid_a,
                    "producto_local_id": lid_a,
                    "delta_scaled": scaled_a,
                },
            ],
        )
        self.assertEqual(first, second)

    def test_cambio_cantidad_cambia_hash(self):
        from inventory_ledger import command_request_hash

        cid = str(uuid.uuid4())
        oid = str(uuid.uuid4())
        lid = str(uuid.uuid4())
        kwargs = dict(
            command_id=cid,
            tipo="VENTA",
            documento_tipo=None,
            documento_local_id=None,
        )
        h50 = command_request_hash(
            operations=[
                {
                    "line_no": 1,
                    "operation_id": oid,
                    "producto_local_id": lid,
                    "delta_scaled": -50000,
                }
            ],
            **kwargs,
        )
        h40 = command_request_hash(
            operations=[
                {
                    "line_no": 1,
                    "operation_id": oid,
                    "producto_local_id": lid,
                    "delta_scaled": -40000,
                }
            ],
            **kwargs,
        )
        self.assertNotEqual(h50, h40)

    def test_falla_linea_n_rollback_completo(self):
        from inventory_ledger import DuplicateOperationError, create_inventory_command

        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = _seed(conn, env)
                oid_keep = str(uuid.uuid4())
                create_inventory_command(
                    conn,
                    command_id=str(uuid.uuid4()),
                    tipo="VENTA",
                    device_id=DEVICE,
                    operations=[_op(lid, "-1", operation_id=oid_keep)],
                )
                cid = str(uuid.uuid4())
                oid_new = str(uuid.uuid4())
                with self.assertRaises(DuplicateOperationError):
                    create_inventory_command(
                        conn,
                        command_id=cid,
                        tipo="VENTA",
                        device_id=DEVICE,
                        operations=[
                            _op(lid, "-1", 1, oid_new),
                            _op(lid, "-1", 2, oid_keep),
                        ],
                    )
                self.assertIsNone(
                    conn.execute(
                        "SELECT 1 FROM inventory_commands WHERE command_id=?",
                        (cid,),
                    ).fetchone()
                )
                n_ops = conn.execute(
                    "SELECT COUNT(*) FROM inventory_operations"
                ).fetchone()[0]
                self.assertEqual(n_ops, 1)
            finally:
                conn.close()

    def test_dos_conexiones_mismo_sqlite(self):
        from inventory_ledger import create_inventory_command
        from local_first_db import connect

        with official_temp_db() as env:
            setup = env.connect()
            try:
                lid = _seed(setup, env)
            finally:
                setup.close()
            cid = str(uuid.uuid4())
            oid = str(uuid.uuid4())
            ops = [_op(lid, "-3", operation_id=oid)]
            results = []
            errors = []

            def worker():
                conn = connect(str(env.db_path))
                try:
                    rec = create_inventory_command(
                        conn,
                        command_id=cid,
                        tipo="VENTA",
                        device_id=DEVICE,
                        operations=ops,
                    )
                    results.append(rec)
                except Exception as exc:
                    errors.append(exc)
                finally:
                    conn.close()

            t1 = threading.Thread(target=worker)
            t2 = threading.Thread(target=worker)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
            self.assertEqual(errors, [])
            self.assertEqual(len(results), 2)
            hashes = {rec.request_hash for rec in results}
            self.assertEqual(len(hashes), 1)
            conn = env.connect()
            try:
                n = conn.execute(
                    "SELECT COUNT(*) FROM inventory_commands WHERE command_id=?",
                    (cid,),
                ).fetchone()[0]
                self.assertEqual(n, 1)
            finally:
                conn.close()

    def test_retry_tras_reiniciar_conexion(self):
        from inventory_ledger import create_inventory_command, get_inventory_command

        with official_temp_db() as env:
            cid = str(uuid.uuid4())
            oid = str(uuid.uuid4())
            conn = env.connect()
            try:
                lid = _seed(conn, env)
                ops = [_op(lid, "7", operation_id=oid)]
                first = create_inventory_command(
                    conn,
                    command_id=cid,
                    tipo="COMPRA",
                    device_id=DEVICE,
                    operations=ops,
                )
            finally:
                conn.close()
            conn = env.connect()
            try:
                loaded = get_inventory_command(conn, cid)
                retry = create_inventory_command(
                    conn,
                    command_id=cid,
                    tipo="COMPRA",
                    device_id=DEVICE,
                    operations=ops,
                )
                self.assertEqual(loaded.request_hash, first.request_hash)
                self.assertEqual(retry.estado, first.estado)
                self.assertEqual(retry.resultado, first.resultado)
                self.assertTrue(retry.replayed)
                self.assertEqual(retry.operations[0].delta_scaled, 7000)
            finally:
                conn.close()

    def test_producto_inexistente_rollback(self):
        from inventory_ledger import UnknownProductError, create_inventory_command

        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = _seed(conn, env)
                cid = str(uuid.uuid4())
                with self.assertRaises(UnknownProductError):
                    create_inventory_command(
                        conn,
                        command_id=cid,
                        tipo="VENTA",
                        device_id=DEVICE,
                        operations=[
                            _op(lid, "-1", 1),
                            _op(str(uuid.uuid4()), "-1", 2),
                        ],
                    )
                self.assertIsNone(
                    conn.execute(
                        "SELECT 1 FROM inventory_commands WHERE command_id=?",
                        (cid,),
                    ).fetchone()
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM inventory_operations"
                    ).fetchone()[0],
                    0,
                )
            finally:
                conn.close()

    def test_identidad_producto_es_uuid_global(self):
        from inventory_ledger import create_inventory_command

        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = _seed(conn, env, producto_id=99)
                rec = create_inventory_command(
                    conn,
                    command_id=str(uuid.uuid4()),
                    tipo="AJUSTE",
                    device_id=DEVICE,
                    operations=[_op(lid, "1")],
                )
                stored = rec.operations[0].producto_local_id
                uuid.UUID(stored)
                self.assertEqual(stored, lid)
                self.assertNotEqual(stored, "99")
                row = conn.execute(
                    "SELECT producto_local_id FROM inventory_operations "
                    "WHERE operation_id=?",
                    (rec.operations[0].operation_id,),
                ).fetchone()
                self.assertEqual(row["producto_local_id"], lid)
            finally:
                conn.close()

    def test_crear_ledger_no_modifica_stock(self):
        from inventory_ledger import create_inventory_command

        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = _seed(conn, env, stock=42)
                before = conn.execute(
                    "SELECT stock FROM productos WHERE local_id=?", (lid,)
                ).fetchone()[0]
                create_inventory_command(
                    conn,
                    command_id=str(uuid.uuid4()),
                    tipo="VENTA",
                    device_id=DEVICE,
                    operations=[_op(lid, "-10")],
                )
                after = conn.execute(
                    "SELECT stock FROM productos WHERE local_id=?", (lid,)
                ).fetchone()[0]
                self.assertEqual(before, 42)
                self.assertEqual(after, 42)
            finally:
                conn.close()

    def test_estado_recuperable_en_retry(self):
        from inventory_ledger import create_inventory_command

        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = _seed(conn, env)
                cid = str(uuid.uuid4())
                ops = [_op(lid, "3")]
                first = create_inventory_command(
                    conn,
                    command_id=cid,
                    tipo="COMPRA",
                    device_id=DEVICE,
                    usuario_id=7,
                    operations=ops,
                )
                retry = create_inventory_command(
                    conn,
                    command_id=cid,
                    tipo="COMPRA",
                    device_id=DEVICE,
                    usuario_id=7,
                    operations=ops,
                )
                self.assertEqual(retry.estado, "PERSISTED")
                self.assertEqual(retry.resultado, "PERSISTED")
                self.assertEqual(retry.estado, first.estado)
                self.assertEqual(retry.operations, first.operations)
            finally:
                conn.close()

