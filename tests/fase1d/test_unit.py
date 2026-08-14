# -*- coding: utf-8 -*-
"""FASE 1D UNIT: validación del adapter y del contrato Python, sin PostgreSQL."""
from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from psycopg2.errors import QueryCanceled

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase0.harness import official_temp_db
from tests.fase1d.helpers import DEVICE, _op, _op_scaled


class UnitCoordinatorTest(unittest.TestCase):
    def test_escala_1000_cincuenta_unidades(self):
        from inventory_coordinator import QUANTITY_SCALE
        from inventory_ledger import quantity_to_scaled

        self.assertEqual(QUANTITY_SCALE, 1000)
        self.assertEqual(quantity_to_scaled("50"), 50000)
        self.assertEqual(quantity_to_scaled("50.000"), 50000)
        self.assertEqual(quantity_to_scaled("-50"), -50000)

    def test_adapter_rechaza_sqlite(self):
        from inventory_coordinator import CoordinatorError, apply_inventory_command

        with official_temp_db() as env:
            conn = env.connect()
            try:
                with self.assertRaises(CoordinatorError):
                    apply_inventory_command(
                        conn,
                        command_id=str(uuid.uuid4()),
                        tipo="VENTA",
                        device_id=DEVICE,
                        operations=[_op(str(uuid.uuid4()), "-1")],
                    )
            finally:
                conn.close()

    def test_no_genera_command_id_en_retry(self):
        from inventory_coordinator import InventoryLedgerError, apply_inventory_command

        src = (REPO_ROOT / "inventory_coordinator.py").read_text(encoding="utf-8")
        self.assertIn("un retry no debe generar uno nuevo", src)
        self.assertNotIn("uuid.uuid4()", src)
        with official_temp_db() as env:
            conn = env.connect()
            try:
                with self.assertRaises(InventoryLedgerError):
                    apply_inventory_command(
                        conn,
                        command_id="",
                        tipo="VENTA",
                        device_id=DEVICE,
                        operations=[_op(str(uuid.uuid4()), "-1")],
                    )
            finally:
                conn.close()

    def test_delta_cero_conforme_1c(self):
        from inventory_ledger import ZeroDeltaError, create_inventory_command

        with official_temp_db() as env:
            conn = env.connect()
            try:
                from tests.fase1c.test_ledger import _seed

                lid = _seed(conn, env)
                with self.assertRaises(ZeroDeltaError):
                    create_inventory_command(
                        conn,
                        command_id=str(uuid.uuid4()),
                        tipo="VENTA",
                        device_id=DEVICE,
                        operations=[_op(lid, "0")],
                    )
                from inventory_coordinator import apply_inventory_command

                with self.assertRaises(ZeroDeltaError):
                    apply_inventory_command(
                        conn,
                        command_id=str(uuid.uuid4()),
                        tipo="VENTA",
                        device_id=DEVICE,
                        operations=[_op(lid, "0")],
                    )
            finally:
                conn.close()

    def test_comando_vacio_rechazado(self):
        from inventory_coordinator import InventoryLedgerError, apply_inventory_command

        fake = MagicMock()
        with self.assertRaises(InventoryLedgerError):
            apply_inventory_command(
                fake,
                command_id=str(uuid.uuid4()),
                tipo="VENTA",
                device_id=DEVICE,
                operations=[],
            )

    def test_overflow_bigint_rechazado(self):
        from inventory_coordinator import BIGINT_MAX, QuantityScaleError, apply_inventory_command

        fake = MagicMock()
        pid = str(uuid.uuid4())
        with self.assertRaises(QuantityScaleError):
            apply_inventory_command(
                fake,
                command_id=str(uuid.uuid4()),
                tipo="COMPRA",
                device_id=DEVICE,
                operations=[_op_scaled(pid, BIGINT_MAX + 1)],
            )

    def test_request_hash_no_coincide_conflicto(self):
        from inventory_coordinator import IdempotencyConflictError, apply_inventory_command

        fake = MagicMock()
        with self.assertRaises(IdempotencyConflictError):
            apply_inventory_command(
                fake,
                command_id=str(uuid.uuid4()),
                tipo="VENTA",
                device_id=DEVICE,
                operations=[_op(str(uuid.uuid4()), "-1")],
                request_hash="0" * 64,
            )

    def test_timeout_reintenta_el_mismo_command_id(self):
        from inventory_coordinator import apply_inventory_command

        command_id = str(uuid.uuid4())
        producto = str(uuid.uuid4())
        seen_ids = []

        class FakeCursor:
            def __init__(self, owner):
                self.owner = owner

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, params=None):
                if "SET LOCAL" in sql:
                    return
                seen_ids.append(params[0])
                if self.owner.fails:
                    self.owner.fails -= 1
                    raise QueryCanceled(
                        "canceling statement due to statement timeout"
                    )
                self._row = (
                    {
                        "command_id": command_id,
                        "tipo": "VENTA",
                        "documento_tipo": None,
                        "documento_local_id": None,
                        "device_id": DEVICE,
                        "usuario_id": None,
                        "request_hash": "a" * 64,
                        "estado": "APPLIED",
                        "resultado": "APPLIED",
                        "motivo": None,
                        "created_at": "t",
                        "updated_at": "t",
                        "operations": [
                            {
                                "operation_id": str(uuid.uuid4()),
                                "producto_local_id": producto,
                                "delta_scaled": -1000,
                                "line_no": 1,
                            }
                        ],
                        "replayed": True,
                    },
                )

            def fetchone(self):
                return self._row

        class FakeConn:
            def __init__(self):
                self.fails = 1
                self.commits = 0
                self.rollbacks = 0

            def cursor(self):
                return FakeCursor(self)

            def commit(self):
                self.commits += 1

            def rollback(self):
                self.rollbacks += 1

        conn = FakeConn()
        rec = apply_inventory_command(
            conn,
            command_id=command_id,
            tipo="VENTA",
            device_id=DEVICE,
            operations=[_op(producto, "-1")],
        )
        self.assertEqual(seen_ids, [command_id, command_id])
        self.assertEqual(rec.command_id, command_id)
        self.assertTrue(rec.replayed)
        self.assertGreaterEqual(conn.commits, 1)

    def test_deadlock_agota_todos_los_reintentos_configurados(self):
        from inventory_coordinator import CoordinatorDeadlockError, apply_inventory_command

        calls = []

        def fail_deadlock(*_args, **_kwargs):
            calls.append(True)
            raise CoordinatorDeadlockError("deadlock sintético")

        with patch("inventory_coordinator._invoke_apply_rpc", fail_deadlock), patch(
            "inventory_coordinator.schema_bootstrap.is_sqlite_connection",
            return_value=False,
        ):
            with self.assertRaises(CoordinatorDeadlockError):
                apply_inventory_command(
                    object(),
                    command_id=str(uuid.uuid4()),
                    tipo="VENTA",
                    device_id=DEVICE,
                    operations=[_op(str(uuid.uuid4()), "-1")],
                    retry_on_timeout=False,
                    max_deadlock_retries=3,
                )

        self.assertEqual(len(calls), 4)

    def test_rechaza_conexion_postgres_autocommit(self):
        from inventory_coordinator import CoordinatorError, apply_inventory_command

        conn = MagicMock()
        conn.autocommit = True
        with self.assertRaises(CoordinatorError):
            apply_inventory_command(
                conn,
                command_id=str(uuid.uuid4()),
                tipo="VENTA",
                device_id=DEVICE,
                operations=[_op(str(uuid.uuid4()), "-1")],
            )

    def test_rechaza_transaccion_activa_ajena(self):
        from inventory_coordinator import CoordinatorError, apply_inventory_command
        from psycopg2.extensions import TRANSACTION_STATUS_INTRANS

        conn = MagicMock()
        conn.autocommit = False
        conn.get_transaction_status.return_value = TRANSACTION_STATUS_INTRANS
        with self.assertRaises(CoordinatorError):
            apply_inventory_command(
                conn,
                command_id=str(uuid.uuid4()),
                tipo="VENTA",
                device_id=DEVICE,
                operations=[_op(str(uuid.uuid4()), "-1")],
            )

    def test_no_adelanta_writers_productivos(self):
        writers = [
            REPO_ROOT / "services" / "ventas_service.py",
            REPO_ROOT / "repositories" / "compras_repo.py",
            REPO_ROOT / "services" / "movimientos_service.py",
            REPO_ROOT / "services" / "mezclas_service.py",
            REPO_ROOT / "repositories" / "inventario_repository.py",
            REPO_ROOT / "local_server.py",
        ]
        for path in writers:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("inventory_coordinator", text)
            self.assertNotIn("apply_inventory_command", text)
            self.assertNotIn("inventory_balances", text)
