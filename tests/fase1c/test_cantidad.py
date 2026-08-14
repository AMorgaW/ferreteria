# -*- coding: utf-8 -*-
"""FASE 1C: fixed-point del ledger y request_hash determinístico."""
from __future__ import annotations

import subprocess
import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase0.harness import official_temp_db
from tests.fase1c.test_ledger import DEVICE, _op, _seed


class FixedPointYHashTest(unittest.TestCase):
    def test_1_5_almacena_1500(self):
        from inventory_ledger import create_inventory_command, quantity_to_scaled

        self.assertEqual(quantity_to_scaled("1.5"), 1500)
        self.assertEqual(quantity_to_scaled(Decimal("1.5")), 1500)
        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = _seed(conn, env)
                rec = create_inventory_command(
                    conn,
                    command_id=str(uuid.uuid4()),
                    tipo="COMPRA",
                    device_id=DEVICE,
                    operations=[_op(lid, Decimal("1.5"))],
                )
                self.assertEqual(rec.operations[0].delta_scaled, 1500)
            finally:
                conn.close()

    def test_0_125_almacena_125(self):
        from inventory_ledger import create_inventory_command, quantity_to_scaled

        self.assertEqual(quantity_to_scaled("0.125"), 125)
        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = _seed(conn, env)
                rec = create_inventory_command(
                    conn,
                    command_id=str(uuid.uuid4()),
                    tipo="COMPRA",
                    device_id=DEVICE,
                    operations=[_op(lid, "0.125")],
                )
                self.assertEqual(rec.operations[0].delta_scaled, 125)
            finally:
                conn.close()

    def test_mas_de_tres_decimales_rechazado(self):
        from inventory_ledger import QuantityScaleError, quantity_to_scaled

        with self.assertRaises(QuantityScaleError):
            quantity_to_scaled("1.0001")
        with self.assertRaises(QuantityScaleError):
            quantity_to_scaled(Decimal("0.0001"))

    def test_no_acepta_float(self):
        from inventory_ledger import (
            QuantityScaleError,
            create_inventory_command,
            quantity_to_scaled,
        )

        with self.assertRaises(QuantityScaleError):
            quantity_to_scaled(1.5)
        with self.assertRaises(QuantityScaleError):
            quantity_to_scaled(0.125)
        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = _seed(conn, env)
                with self.assertRaises(QuantityScaleError):
                    create_inventory_command(
                        conn,
                        command_id=str(uuid.uuid4()),
                        tipo="COMPRA",
                        device_id=DEVICE,
                        operations=[_op(lid, 1.5)],
                    )
                with self.assertRaises(QuantityScaleError):
                    create_inventory_command(
                        conn,
                        command_id=str(uuid.uuid4()),
                        tipo="COMPRA",
                        device_id=DEVICE,
                        operations=[
                            {
                                "operation_id": str(uuid.uuid4()),
                                "producto_local_id": lid,
                                "line_no": 1,
                                "delta_scaled": Decimal("1500.9"),
                            }
                        ],
                    )
            finally:
                conn.close()

    def test_delta_cero_rechazado(self):
        from inventory_ledger import ZeroDeltaError, create_inventory_command

        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = _seed(conn, env)
                with self.assertRaises(ZeroDeltaError):
                    create_inventory_command(
                        conn,
                        command_id=str(uuid.uuid4()),
                        tipo="AJUSTE",
                        device_id=DEVICE,
                        operations=[_op(lid, "0")],
                    )
            finally:
                conn.close()

    def test_request_hash_estable_entre_procesos(self):
        cid = "11111111-1111-4111-8111-111111111111"
        oid = "22222222-2222-4222-8222-222222222222"
        lid = "33333333-3333-4333-8333-333333333333"
        script = (
            "import sys; sys.path.insert(0, %r); "
            "from inventory_ledger import command_request_hash; "
            "print(command_request_hash("
            "command_id=%r, tipo='VENTA', documento_tipo=None, "
            "documento_local_id=None, operations=[{"
            "'line_no': 1, 'operation_id': %r, "
            "'producto_local_id': %r, 'delta_scaled': -5000}]))"
            % (str(REPO_ROOT), cid, oid, lid)
        )
        first = subprocess.check_output(
            [sys.executable, "-c", script], text=True
        ).strip()
        second = subprocess.check_output(
            [sys.executable, "-c", script], text=True
        ).strip()
        self.assertEqual(len(first), 64)
        self.assertEqual(first, second)
