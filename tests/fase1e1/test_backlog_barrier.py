# -*- coding: utf-8 -*-
"""Barrera: backlog LEGACY_OBSERVED no atraviesa cutover ni seed."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase0.harness import official_temp_db
from tests.fase1e.helpers import DEVICE, _op, insert_usuario, seed_producto, stock_of
from tests.fase1e1.helpers import applied_record, command_count, ventas_service


class PreCutoverBacklogBarrierTest(unittest.TestCase):
    def test_observed_no_entra_a_lista_transmissible(self):
        from inventory_gateway import (
            GatewayPreCutoverBacklogError,
            InventoryGateway,
            list_transmittable_command_ids,
        )

        sent = []

        def transport(**kwargs):
            sent.append(kwargs)
            return applied_record(kwargs["command_id"], kwargs["request_hash"])

        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = seed_producto(conn, env, stock=50)
                off = InventoryGateway(conn, transport=transport)
                first = off.submit(
                    tipo="VENTA",
                    device_id=DEVICE,
                    operations=[_op(lid, "-5")],
                )
                self.assertEqual(first.outcome, "LEGACY_OBSERVED")
                self.assertEqual(list_transmittable_command_ids(conn), ())

                on = InventoryGateway(
                    conn, cutover_enabled=True, transport=transport
                )
                retry = on.submit(
                    tipo="VENTA",
                    command_id=first.command_id,
                    device_id=DEVICE,
                    operations=[_op(lid, "-5")],
                )
                self.assertEqual(retry.outcome, "LEGACY_OBSERVED")
                self.assertEqual(sent, [])
                with self.assertRaises(GatewayPreCutoverBacklogError):
                    on._send_to_coordinator(
                        retry.record,
                        [_op(lid, "-5")],
                        documento_tipo=None,
                        documento_local_id=None,
                        device_id=DEVICE,
                        usuario_id=None,
                    )
            finally:
                conn.close()

    def test_venta_legacy_no_crea_command_autoritativo(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=50)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            ok, msg, venta = ventas_service(env).registrar_venta(
                items=[{"producto_id": 1, "cantidad": 5, "precio_unitario": 1000}],
            )
            self.assertTrue(ok, msg)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 45)
                self.assertEqual(command_count(conn), 0)
                self.assertEqual(command_count(conn, intent_class="AUTHORITATIVE"), 0)
            finally:
                conn.close()

    def test_migracion_filas_viejas_no_son_transmissibles(self):
        import sqlite3
        import tempfile
        from pathlib import Path

        from inventory_gateway import list_transmittable_command_ids
        from inventory_ledger import ensure_inventory_ledger_schema
        from local_first_db import now_iso

        tmp = tempfile.TemporaryDirectory(prefix="ferrepro-1e1-old-ledger-")
        conn = None
        try:
            db_path = Path(tmp.name) / "old.db"
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                CREATE TABLE inventory_commands (
                    command_id TEXT PRIMARY KEY,
                    tipo TEXT NOT NULL,
                    documento_tipo TEXT,
                    documento_local_id TEXT,
                    device_id TEXT NOT NULL,
                    usuario_id INTEGER,
                    request_hash TEXT NOT NULL,
                    estado TEXT NOT NULL,
                    resultado TEXT NOT NULL,
                    motivo TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            stamp = now_iso()
            conn.execute(
                """
                INSERT INTO inventory_commands (
                    command_id, tipo, documento_tipo, documento_local_id,
                    device_id, usuario_id, request_hash, estado, resultado,
                    motivo, created_at, updated_at
                ) VALUES (?, 'VENTA', NULL, NULL, ?, NULL, 'hash',
                          'PERSISTED', 'PERSISTED', NULL, ?, ?)
                """,
                (
                    "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                    "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                    stamp,
                    stamp,
                ),
            )
            conn.commit()
            ensure_inventory_ledger_schema(conn)
            row = conn.execute(
                "SELECT intent_class FROM inventory_commands"
            ).fetchone()
            self.assertEqual(row["intent_class"], "LEGACY_OBSERVED")
            self.assertEqual(list_transmittable_command_ids(conn), ())
        finally:
            if conn is not None:
                conn.close()
            tmp.cleanup()
