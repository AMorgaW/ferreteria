# -*- coding: utf-8 -*-
"""FASE 1E.0: InventoryGateway — persistencia antes de red, UNKNOWN, cutover OFF."""
from __future__ import annotations

import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase0.harness import official_temp_db
from tests.fase1e.helpers import DEVICE, _op, seed_producto


def _applied_record(command_id, request_hash, *, estado="APPLIED", motivo=None):
    from inventory_ledger import InventoryCommandRecord

    return InventoryCommandRecord(
        command_id=command_id,
        tipo="VENTA",
        documento_tipo=None,
        documento_local_id=None,
        device_id=DEVICE,
        usuario_id=None,
        request_hash=request_hash,
        estado=estado,
        resultado=estado,
        motivo=motivo,
        created_at="t",
        updated_at="t",
        operations=(),
        replayed=False,
    )


class GatewayPersistenciaTest(unittest.TestCase):
    def test_cutover_default_es_off(self):
        from inventory_gateway import INVENTORY_CUTOVER_ENABLED, InventoryGateway

        self.assertIs(INVENTORY_CUTOVER_ENABLED, False)
        src = (REPO_ROOT / "inventory_gateway.py").read_text(encoding="utf-8")
        self.assertIn("INVENTORY_CUTOVER_ENABLED = False", src)
        with official_temp_db() as env:
            conn = env.connect()
            try:
                gw = InventoryGateway(conn)
                self.assertFalse(gw.cutover_enabled)
                self.assertFalse(gw.cutover_is_on)
            finally:
                conn.close()

    def test_command_id_persistido_antes_del_primer_transporte(self):
        from inventory_coordinator import CoordinatorUnknownOutcomeError
        from inventory_gateway import InventoryGateway, OUTCOME_UNKNOWN
        from inventory_ledger import LEDGER_STATE_PERSISTED

        order = []

        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = seed_producto(conn, env)
                cid = str(uuid.uuid4())
                oid = str(uuid.uuid4())

                def transport(**kwargs):
                    row = conn.execute(
                        "SELECT command_id, estado, request_hash FROM inventory_commands "
                        "WHERE command_id = ?",
                        (kwargs["command_id"],),
                    ).fetchone()
                    order.append("transport")
                    self.assertIsNotNone(row)
                    self.assertEqual(row["command_id"], cid)
                    self.assertEqual(row["estado"], LEDGER_STATE_PERSISTED)
                    self.assertEqual(row["request_hash"], kwargs["request_hash"])
                    raise CoordinatorUnknownOutcomeError("lost after persist")

                gw = InventoryGateway(
                    conn, cutover_enabled=True, transport=transport
                )
                order.append("submit")
                result = gw.submit(
                    tipo="VENTA",
                    command_id=cid,
                    device_id=DEVICE,
                    operations=[_op(lid, "-1", operation_id=oid)],
                )
                self.assertEqual(order, ["submit", "transport"])
                self.assertEqual(result.outcome, OUTCOME_UNKNOWN)
                self.assertEqual(result.estado_local, LEDGER_STATE_PERSISTED)
                self.assertEqual(result.command_id, cid)
            finally:
                conn.close()

    def test_cutover_off_no_envia_ni_finge_applied(self):
        from inventory_gateway import (
            InventoryGateway,
            OUTCOME_PENDING_CUTOVER,
        )
        from inventory_ledger import LEDGER_STATE_PERSISTED

        called = []

        def transport(**kwargs):
            called.append(kwargs)
            raise AssertionError("cutover OFF no debe transportar")

        factory_calls = []

        def factory():
            factory_calls.append(1)
            raise AssertionError("cutover OFF no debe abrir PG")

        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = seed_producto(conn, env)
                gw = InventoryGateway(
                    conn,
                    connection_factory=factory,
                    transport=transport,
                )
                result = gw.submit(
                    tipo="VENTA",
                    device_id=DEVICE,
                    operations=[_op(lid, "-2")],
                )
                self.assertEqual(result.outcome, OUTCOME_PENDING_CUTOVER)
                self.assertEqual(result.estado_local, LEDGER_STATE_PERSISTED)
                self.assertNotEqual(result.outcome, "APPLIED")
                self.assertEqual(called, [])
                self.assertEqual(factory_calls, [])
                n = conn.execute(
                    "SELECT COUNT(*) FROM inventory_commands"
                ).fetchone()[0]
                self.assertEqual(n, 1)
            finally:
                conn.close()

    def test_mismo_comando_en_retry(self):
        from inventory_coordinator import CoordinatorUnknownOutcomeError
        from inventory_gateway import InventoryGateway, OUTCOME_APPLIED, OUTCOME_UNKNOWN

        transports = []

        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = seed_producto(conn, env)
                cid = str(uuid.uuid4())
                oid = str(uuid.uuid4())
                ops = [_op(lid, "-3", operation_id=oid)]

                def transport(**kwargs):
                    transports.append(
                        (
                            kwargs["command_id"],
                            kwargs["request_hash"],
                            tuple(
                                (
                                    op["operation_id"],
                                    op.get("delta") or op.get("delta_scaled"),
                                    op["line_no"],
                                )
                                for op in kwargs["operations"]
                            ),
                        )
                    )
                    if len(transports) == 1:
                        raise CoordinatorUnknownOutcomeError("first lost")
                    return _applied_record(
                        kwargs["command_id"], kwargs["request_hash"]
                    )

                gw = InventoryGateway(
                    conn, cutover_enabled=True, transport=transport
                )
                first = gw.submit(
                    tipo="VENTA",
                    command_id=cid,
                    device_id=DEVICE,
                    operations=ops,
                )
                second = gw.submit(
                    tipo="VENTA",
                    command_id=cid,
                    device_id=DEVICE,
                    operations=ops,
                )
                self.assertEqual(first.outcome, OUTCOME_UNKNOWN)
                self.assertEqual(second.outcome, OUTCOME_APPLIED)
                self.assertEqual(first.command_id, second.command_id)
                self.assertEqual(first.request_hash, second.request_hash)
                self.assertEqual(transports[0], transports[1])
                self.assertEqual(first.command_id, cid)
            finally:
                conn.close()

    def test_unknown_preserva_persisted_no_es_rejected_ni_applied(self):
        from inventory_coordinator import CoordinatorUnknownOutcomeError
        from inventory_gateway import (
            InventoryGateway,
            OUTCOME_APPLIED,
            OUTCOME_REJECTED,
            OUTCOME_UNKNOWN,
        )
        from inventory_ledger import LEDGER_STATE_PERSISTED

        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = seed_producto(conn, env)

                def transport(**kwargs):
                    raise CoordinatorUnknownOutcomeError("ambiguous commit")

                gw = InventoryGateway(
                    conn, cutover_enabled=True, transport=transport
                )
                result = gw.submit(
                    tipo="VENTA",
                    device_id=DEVICE,
                    operations=[_op(lid, "-1")],
                )
                self.assertEqual(result.outcome, OUTCOME_UNKNOWN)
                self.assertNotEqual(result.outcome, OUTCOME_REJECTED)
                self.assertNotEqual(result.outcome, OUTCOME_APPLIED)
                self.assertEqual(result.estado_local, LEDGER_STATE_PERSISTED)
                row = conn.execute(
                    "SELECT estado, resultado FROM inventory_commands WHERE command_id = ?",
                    (result.command_id,),
                ).fetchone()
                self.assertEqual(row["estado"], LEDGER_STATE_PERSISTED)
                self.assertEqual(row["resultado"], LEDGER_STATE_PERSISTED)
            finally:
                conn.close()

    def test_gateway_no_genera_ids_en_retry(self):
        from inventory_coordinator import CoordinatorUnknownOutcomeError
        from inventory_gateway import InventoryGateway

        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = seed_producto(conn, env)
                cid = str(uuid.uuid4())
                oid = str(uuid.uuid4())
                ops = [_op(lid, "-1", operation_id=oid)]

                def transport(**kwargs):
                    raise CoordinatorUnknownOutcomeError("lost")

                gw = InventoryGateway(
                    conn, cutover_enabled=True, transport=transport
                )
                gw.submit(
                    tipo="VENTA",
                    command_id=cid,
                    device_id=DEVICE,
                    operations=ops,
                )
                with patch("inventory_gateway.uuid.uuid4") as gen:
                    gen.side_effect = AssertionError("retry no genera UUIDs")
                    result = gw.submit(
                        tipo="VENTA",
                        command_id=cid,
                        device_id=DEVICE,
                        operations=ops,
                    )
                self.assertEqual(result.command_id, cid)
                ops_row = conn.execute(
                    "SELECT operation_id FROM inventory_operations WHERE command_id = ?",
                    (cid,),
                ).fetchone()
                self.assertEqual(ops_row["operation_id"], oid)
            finally:
                conn.close()

    def test_gateway_no_usa_sqlite_como_autoridad_online(self):
        from inventory_gateway import InventoryGateway, InventoryGatewayError

        with official_temp_db() as env:
            conn = env.connect()
            try:
                with self.assertRaises(InventoryGatewayError):
                    InventoryGateway(conn, pg_conn=conn, cutover_enabled=True)

                lid = seed_producto(conn, env)

                def sqlite_factory():
                    return conn

                gw = InventoryGateway(
                    conn,
                    connection_factory=sqlite_factory,
                    cutover_enabled=True,
                )
                with self.assertRaises(InventoryGatewayError) as ctx:
                    gw.submit(
                        tipo="VENTA",
                        device_id=DEVICE,
                        operations=[_op(lid, "-1")],
                    )
                self.assertIn("SQLite", str(ctx.exception))
                estado = conn.execute(
                    "SELECT estado FROM inventory_commands"
                ).fetchone()["estado"]
                self.assertEqual(estado, "PERSISTED")
            finally:
                conn.close()

    def test_connection_factory_se_pasa_en_cutover_on(self):
        from inventory_gateway import InventoryGateway, OUTCOME_APPLIED

        factory = MagicMock(name="pg_factory")

        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = seed_producto(conn, env)
                cid = str(uuid.uuid4())

                def fake_apply(pg_conn, *, connection_factory=None, **kwargs):
                    self.assertIsNotNone(connection_factory)
                    connection_factory()
                    self.assertEqual(kwargs["command_id"], cid)
                    self.assertTrue(kwargs["request_hash"])
                    return _applied_record(kwargs["command_id"], kwargs["request_hash"])

                gw = InventoryGateway(
                    conn,
                    connection_factory=factory,
                    cutover_enabled=True,
                )
                with patch(
                    "inventory_gateway.apply_inventory_command", side_effect=fake_apply
                ):
                    result = gw.submit(
                        tipo="VENTA",
                        command_id=cid,
                        device_id=DEVICE,
                        operations=[_op(lid, "-1")],
                    )
                self.assertEqual(result.outcome, OUTCOME_APPLIED)
                self.assertEqual(result.estado_local, "APPLIED")
                factory.assert_called()
            finally:
                conn.close()

    def test_unknown_reconnect_usa_factory(self):
        from inventory_coordinator import CoordinatorUnknownOutcomeError
        from inventory_gateway import InventoryGateway, OUTCOME_UNKNOWN

        factory_calls = []

        def factory():
            factory_calls.append("reconnect")
            return MagicMock(name="pg")

        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = seed_producto(conn, env)

                def transport(**kwargs):
                    kwargs["connection_factory"]()
                    raise CoordinatorUnknownOutcomeError("lost after commit?")

                gw = InventoryGateway(
                    conn,
                    connection_factory=factory,
                    cutover_enabled=True,
                    transport=lambda **kw: transport(
                        connection_factory=factory, **kw
                    ),
                )
                result = gw.submit(
                    tipo="VENTA",
                    device_id=DEVICE,
                    operations=[_op(lid, "-1")],
                )
                self.assertEqual(result.outcome, OUTCOME_UNKNOWN)
                self.assertEqual(factory_calls, ["reconnect"])
                self.assertEqual(result.estado_local, "PERSISTED")
            finally:
                conn.close()

    def test_dsn_no_owner_sin_fallback_supabase(self):
        from inventory_gateway import (
            INVENTORY_DSN_ENV,
            InventoryGatewayConfigError,
            connection_factory_from_env,
            read_inventory_dsn,
        )

        env_vacio = {"SUPABASE_URI": "postgresql://owner:secret@host/db"}
        with self.assertRaises(InventoryGatewayConfigError) as ctx:
            read_inventory_dsn(environ=env_vacio)
        msg = str(ctx.exception)
        self.assertIn(INVENTORY_DSN_ENV, msg)
        self.assertIn("SUPABASE_URI", msg)
        self.assertNotIn("owner:secret", msg)

        with self.assertRaises(InventoryGatewayConfigError):
            connection_factory_from_env(environ=env_vacio)

        dsn = read_inventory_dsn(
            environ={INVENTORY_DSN_ENV: "postgresql://app@localhost/inv"}
        )
        self.assertEqual(dsn, "postgresql://app@localhost/inv")
        self.assertNotIn("SUPABASE_URI", os.environ.get(INVENTORY_DSN_ENV, "") or "ok")

    def test_rejected_remoto_no_escribe_productos_stock(self):
        from inventory_gateway import InventoryGateway, OUTCOME_REJECTED

        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = seed_producto(conn, env, stock=50)
                before = conn.execute(
                    "SELECT stock FROM productos WHERE id = 1"
                ).fetchone()[0]

                def transport(**kwargs):
                    return _applied_record(
                        kwargs["command_id"],
                        kwargs["request_hash"],
                        estado="REJECTED",
                        motivo="INSUFFICIENT_STOCK",
                    )

                gw = InventoryGateway(
                    conn, cutover_enabled=True, transport=transport
                )
                result = gw.submit(
                    tipo="VENTA",
                    device_id=DEVICE,
                    operations=[_op(lid, "-1")],
                )
                self.assertEqual(result.outcome, OUTCOME_REJECTED)
                after = conn.execute(
                    "SELECT stock FROM productos WHERE id = 1"
                ).fetchone()[0]
                self.assertEqual(before, after)
                self.assertEqual(after, 50)
            finally:
                conn.close()

    def test_check_ledger_no_incluye_unknown(self):
        src = (REPO_ROOT / "inventory_ledger.py").read_text(encoding="utf-8")
        self.assertIn("PERSISTED", src)
        self.assertIn("APPLIED", src)
        self.assertIn("REJECTED", src)
        self.assertNotIn("'UNKNOWN'", src)
        gw = (REPO_ROOT / "inventory_gateway.py").read_text(encoding="utf-8")
        self.assertIn("OUTCOME_UNKNOWN", gw)
        self.assertIn("PENDING_CUTOVER", gw)
