# -*- coding: utf-8 -*-
"""1E.2: intent_class fail-closed. Ausencia = no transmitir."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase0.harness import official_temp_db
from tests.fase1e.helpers import DEVICE, _op, seed_producto


class IntentClassFailClosedTest(unittest.TestCase):
    def test_db_fresca_default_legacy_observed(self):
        from inventory_ledger import create_inventory_command, ensure_inventory_ledger_schema

        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = seed_producto(conn, env)
                ensure_inventory_ledger_schema(conn)
                row = conn.execute(
                    "SELECT dflt_value FROM pragma_table_info('inventory_commands') "
                    "WHERE name = 'intent_class'"
                ).fetchone()
                self.assertIn("LEGACY_OBSERVED", str(row[0]))
                rec = create_inventory_command(
                    conn,
                    command_id=str(uuid.uuid4()),
                    tipo="VENTA",
                    device_id=DEVICE,
                    operations=[_op(lid, "-1")],
                )
                self.assertEqual(rec.intent_class, "LEGACY_OBSERVED")
            finally:
                conn.close()

    def test_db_migrada_filas_viejas_no_transmissibles(self):
        from inventory_gateway import list_transmittable_command_ids
        from inventory_ledger import ensure_inventory_ledger_schema
        from local_first_db import now_iso

        tmp = tempfile.TemporaryDirectory(prefix="ferrepro-1e2-intent-")
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
            cid = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO inventory_commands (
                    command_id, tipo, documento_tipo, documento_local_id,
                    device_id, usuario_id, request_hash, estado, resultado,
                    motivo, created_at, updated_at
                ) VALUES (?, 'VENTA', NULL, NULL, ?, NULL, 'hash',
                          'PERSISTED', 'PERSISTED', NULL, ?, ?)
                """,
                (cid, DEVICE, stamp, stamp),
            )
            conn.commit()
            ensure_inventory_ledger_schema(conn)
            row = conn.execute("SELECT intent_class FROM inventory_commands").fetchone()
            self.assertEqual(row["intent_class"], "LEGACY_OBSERVED")
            self.assertEqual(list_transmittable_command_ids(conn), ())
        finally:
            if conn is not None:
                conn.close()
            tmp.cleanup()

    def test_intent_class_null_no_transmite(self):
        from inventory_gateway import command_is_transmittable, list_transmittable_command_ids
        from inventory_ledger import InventoryCommandRecord

        rec = InventoryCommandRecord(
            command_id=str(uuid.uuid4()),
            tipo="VENTA",
            documento_tipo=None,
            documento_local_id=None,
            device_id=DEVICE,
            usuario_id=None,
            request_hash="x",
            estado="PERSISTED",
            resultado="PERSISTED",
            motivo=None,
            created_at="t",
            updated_at="t",
            operations=(),
            replayed=False,
            intent_class=None,  # type: ignore[arg-type]
        )
        self.assertFalse(command_is_transmittable(rec))
        tmp = tempfile.TemporaryDirectory(prefix="ferrepro-1e2-null-")
        conn = None
        try:
            conn = sqlite3.connect(str(Path(tmp.name) / "n.db"))
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
                    updated_at TEXT NOT NULL,
                    intent_class TEXT
                )
                """
            )
            conn.execute(
                """
                INSERT INTO inventory_commands (
                    command_id, tipo, device_id, request_hash, estado, resultado,
                    created_at, updated_at, intent_class
                ) VALUES (?, 'VENTA', ?, 'hash', 'PERSISTED', 'PERSISTED', 't', 't', NULL)
                """,
                (str(uuid.uuid4()), DEVICE),
            )
            self.assertEqual(list_transmittable_command_ids(conn), ())
        finally:
            if conn is not None:
                conn.close()
            tmp.cleanup()

    def test_intent_class_omitido_es_legacy(self):
        from inventory_ledger import _normalize_intent_class

        self.assertEqual(_normalize_intent_class(None), "LEGACY_OBSERVED")

    def test_intent_class_vacio_es_legacy(self):
        from inventory_ledger import _normalize_intent_class

        self.assertEqual(_normalize_intent_class(""), "LEGACY_OBSERVED")
        self.assertEqual(_normalize_intent_class("   "), "LEGACY_OBSERVED")

    def test_intent_class_invalido_rechaza(self):
        from inventory_ledger import InventoryLedgerError, _normalize_intent_class

        with self.assertRaises(InventoryLedgerError):
            _normalize_intent_class("WHATEVER")

    def test_legacy_observed_explicito(self):
        from inventory_ledger import _normalize_intent_class, create_inventory_command

        self.assertEqual(_normalize_intent_class("LEGACY_OBSERVED"), "LEGACY_OBSERVED")
        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = seed_producto(conn, env)
                rec = create_inventory_command(
                    conn,
                    command_id=str(uuid.uuid4()),
                    tipo="VENTA",
                    device_id=DEVICE,
                    operations=[_op(lid, "-1")],
                    intent_class="LEGACY_OBSERVED",
                )
                self.assertEqual(rec.intent_class, "LEGACY_OBSERVED")
            finally:
                conn.close()

    def test_authoritative_explicito(self):
        from inventory_ledger import create_inventory_command

        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = seed_producto(conn, env)
                rec = create_inventory_command(
                    conn,
                    command_id=str(uuid.uuid4()),
                    tipo="VENTA",
                    device_id=DEVICE,
                    operations=[_op(lid, "-1")],
                    intent_class="AUTHORITATIVE",
                )
                self.assertEqual(rec.intent_class, "AUTHORITATIVE")
            finally:
                conn.close()

    def test_list_transmittable_solo_authoritative_persisted(self):
        from inventory_gateway import list_transmittable_command_ids
        from inventory_ledger import create_inventory_command

        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = seed_producto(conn, env)
                auth = create_inventory_command(
                    conn,
                    command_id=str(uuid.uuid4()),
                    tipo="VENTA",
                    device_id=DEVICE,
                    operations=[_op(lid, "-1")],
                    intent_class="AUTHORITATIVE",
                )
                create_inventory_command(
                    conn,
                    command_id=str(uuid.uuid4()),
                    tipo="VENTA",
                    device_id=DEVICE,
                    operations=[_op(lid, "-2")],
                    intent_class="LEGACY_OBSERVED",
                )
                ids = list_transmittable_command_ids(conn)
                self.assertEqual(ids, (auth.command_id,))
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
