# -*- coding: utf-8 -*-
"""Certificación PostgreSQL real 1E.1: APPLIED / REJECTED / multilínea / reconnect."""
from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase0.harness import official_temp_db
from tests.fase1d.pg_harness import (
    apply_coordinator_schema,
    connect,
    insert_producto,
    postgres_available,
)
from tests.fase1e.helpers import insert_usuario, seed_producto, stock_of
from tests.fase1e1.helpers import ventas_service
from tests.fase1e1.pg_dsn import ensure_pg_test_dsn


def _require_pg():
    ensure_pg_test_dsn()
    if not postgres_available():
        raise unittest.SkipTest(
            "PostgreSQL ferrepro-pg-test no disponible; no certifica 1E.1"
        )


class Fase1E1PostgresTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _require_pg()
        conn = connect()
        try:
            apply_coordinator_schema(conn)
        finally:
            conn.close()

    def setUp(self):
        self.pg = connect()
        try:
            with self.pg.cursor() as cur:
                cur.execute(
                    "UPDATE inventory_cutover_control SET status = 'PRE_CUTOVER', "
                    "epoch = 0 WHERE id = 1"
                )
            self.pg.commit()
        except Exception:
            try:
                self.pg.rollback()
            except Exception:
                pass

    def tearDown(self):
        try:
            self.pg.close()
        except Exception:
            pass

    def _factory(self):
        return connect()

    def test_applied_multilinea_atomica(self):
        from inventory_coordinator import InventoryCoordinatorClient, STATE_APPLIED

        client = InventoryCoordinatorClient(self.pg, timeout_seconds=15)
        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid_a = seed_producto(conn, env, stock=50, producto_id=1)
                lid_b = str(uuid.uuid4())
                env.insert_producto(
                    conn,
                    producto_id=2,
                    stock=20,
                    local_id=lid_b,
                    codigo="TEST-1E1-PG-B",
                )
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            insert_producto(self.pg, local_id=lid_a, stock=999)
            insert_producto(self.pg, local_id=lid_b, stock=999)
            client.seed_balance(lid_a, 10000)
            client.seed_balance(lid_b, 5000)
            ok, msg, venta = ventas_service(env).registrar_venta(
                items=[
                    {"producto_id": 1, "cantidad": 2, "precio_unitario": 1000},
                    {"producto_id": 2, "cantidad": 1, "precio_unitario": 500},
                ],
                inventory_mode="authoritative",
                inventory_connection_factory=self._factory,
            )
            self.assertTrue(ok, msg)
            self.assertIsNotNone(venta)
            self.assertEqual(client.get_balance(lid_a), 8000)
            self.assertEqual(client.get_balance(lid_b), 4000)
            sqlite = env.connect()
            try:
                self.assertEqual(stock_of(sqlite, 1), 50)
                self.assertEqual(stock_of(sqlite, 2), 20)
                estado = sqlite.execute(
                    "SELECT estado, intent_class FROM inventory_commands"
                ).fetchone()
                self.assertEqual(estado["estado"], STATE_APPLIED)
                self.assertEqual(estado["intent_class"], "AUTHORITATIVE")
            finally:
                sqlite.close()

    def test_rejected_no_muta_ni_completa_venta(self):
        from inventory_coordinator import InventoryCoordinatorClient

        client = InventoryCoordinatorClient(self.pg, timeout_seconds=15)
        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = seed_producto(conn, env, stock=50)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            insert_producto(self.pg, local_id=lid, stock=999)
            client.seed_balance(lid, 1000)
            ok, msg, venta = ventas_service(env).registrar_venta(
                items=[{"producto_id": 1, "cantidad": 5, "precio_unitario": 1000}],
                inventory_mode="authoritative",
                inventory_connection_factory=self._factory,
            )
            self.assertFalse(ok)
            self.assertIsNone(venta)
            self.assertEqual(client.get_balance(lid), 1000)
            sqlite = env.connect()
            try:
                self.assertEqual(stock_of(sqlite), 50)
                self.assertEqual(
                    sqlite.execute("SELECT COUNT(*) FROM ventas").fetchone()[0], 0
                )
            finally:
                sqlite.close()

    def test_unknown_reconnect_mismo_command_id(self):
        from inventory_coordinator import (
            InventoryCoordinatorClient,
            STATE_APPLIED,
        )
        from inventory_gateway import InventoryGateway, OUTCOME_APPLIED, OUTCOME_UNKNOWN
        from tests.fase1e.helpers import DEVICE, _op

        client = InventoryCoordinatorClient(self.pg, timeout_seconds=15)
        with official_temp_db() as env:
            sqlite = env.connect()
            try:
                lid = seed_producto(sqlite, env, stock=50)
                insert_producto(self.pg, local_id=lid, stock=999)
                client.seed_balance(lid, 8000)
                cid = str(uuid.uuid4())
                ops = [_op(lid, "-2")]
                gw = InventoryGateway(
                    sqlite,
                    cutover_enabled=True,
                    connection_factory=self._factory,
                )
                first = gw.submit(
                    tipo="VENTA",
                    command_id=cid,
                    device_id=DEVICE,
                    operations=ops,
                )
                self.assertIn(first.outcome, (OUTCOME_APPLIED, OUTCOME_UNKNOWN))
                second = gw.submit(
                    tipo="VENTA",
                    command_id=cid,
                    device_id=DEVICE,
                    operations=ops,
                )
                self.assertEqual(second.command_id, cid)
                self.assertEqual(second.outcome, OUTCOME_APPLIED)
                self.assertEqual(client.get_balance(lid), 6000)
                row = sqlite.execute(
                    "SELECT estado FROM inventory_commands WHERE command_id=?",
                    (cid,),
                ).fetchone()
                self.assertEqual(row["estado"], STATE_APPLIED)
            finally:
                sqlite.close()
