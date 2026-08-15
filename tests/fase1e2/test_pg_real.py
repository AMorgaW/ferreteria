# -*- coding: utf-8 -*-
"""PostgreSQL real 1E.2. Laboratorio ferrepro-pg-test:55432. No SUPABASE_URI."""
from __future__ import annotations

import sys
import unittest
import uuid
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from models import MovimientoInventario
from repositories.compras_repo import ComprasRepository
from repositories.inventario_repository import InventarioRepository
from tests.fase0.harness import official_temp_db
from tests.fase1d.pg_harness import (
    apply_coordinator_schema,
    connect,
    insert_producto,
    postgres_available,
)
from tests.fase1e.helpers import insert_usuario, seed_producto, stock_of
from tests.fase1e1.pg_dsn import ensure_pg_test_dsn
from tests.fase1e2.helpers import ventas_service


def _require_pg():
    ensure_pg_test_dsn()
    if not postgres_available():
        raise AssertionError(
            "PostgreSQL ferrepro-pg-test no disponible; no certifica 1E.2"
        )


class Fase1E2PostgresTest(unittest.TestCase):
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

    def tearDown(self):
        try:
            self.pg.close()
        except Exception:
            pass

    def _factory(self):
        return connect()

    def test_w01_compra_multilinea(self):
        from inventory_coordinator import InventoryCoordinatorClient

        client = InventoryCoordinatorClient(self.pg, timeout_seconds=15)
        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = seed_producto(conn, env, stock=1)
            finally:
                conn.close()
            insert_producto(self.pg, local_id=lid, stock=999)
            client.seed_balance(lid, 1000)
            ok, msg, compra_id = ComprasRepository(env.db).crear_compra(
                proveedor_id=1,
                productos=[
                    {"producto_id": 1, "cantidad": 2, "precio_unitario": 10},
                    {"producto_id": 1, "cantidad": 3, "precio_unitario": 10},
                ],
                numero_factura="PG-W01",
                inventory_mode="authoritative",
                inventory_connection_factory=self._factory,
            )
            self.assertTrue(ok, msg)
            self.assertIsNotNone(compra_id)
            self.assertEqual(client.get_balance(lid), 6000)
            sqlite = env.connect()
            try:
                self.assertEqual(stock_of(sqlite), 1)
            finally:
                sqlite.close()

    def test_mixto_positivo_y_negativo(self):
        from inventory_coordinator import InventoryCoordinatorClient

        client = InventoryCoordinatorClient(self.pg, timeout_seconds=15)
        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            insert_producto(self.pg, local_id=lid, stock=999)
            client.seed_balance(lid, 10000)
            repo = InventarioRepository(env.db)
            ok, msg = repo.registrar_movimiento(
                MovimientoInventario(
                    tipo_movimiento="ENTRADA_AJUSTE",
                    producto_id=1, cantidad=2, precio_unitario=0,
                    usuario_id=1, fecha=datetime.now(),
                ),
                inventory_mode="authoritative",
                inventory_connection_factory=self._factory,
            )
            self.assertTrue(ok, msg)
            self.assertEqual(client.get_balance(lid), 12000)
            ok2, msg2 = repo.registrar_movimiento(
                MovimientoInventario(
                    tipo_movimiento="SALIDA_AJUSTE",
                    producto_id=1, cantidad=3, precio_unitario=0,
                    usuario_id=1, fecha=datetime.now(),
                ),
                inventory_mode="authoritative",
                inventory_connection_factory=self._factory,
            )
            self.assertTrue(ok2, msg2)
            self.assertEqual(client.get_balance(lid), 9000)

    def test_negativo_insuficiente_rejected(self):
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

    def test_atomicidad_retry_unknown_w13_cas(self):
        from inventory_coordinator import InventoryCoordinatorClient, STATE_APPLIED
        from inventory_gateway import InventoryGateway, OUTCOME_APPLIED, OUTCOME_UNKNOWN
        from tests.fase1e.helpers import DEVICE, _op

        client = InventoryCoordinatorClient(self.pg, timeout_seconds=15)
        with official_temp_db() as env:
            sqlite = env.connect()
            try:
                lid = seed_producto(sqlite, env, stock=10)
                insert_usuario(sqlite)
                sqlite.commit()
                insert_producto(self.pg, local_id=lid, stock=999)
                client.seed_balance(lid, 10000)
                cid = str(uuid.uuid4())
                ops = [_op(lid, "5")]
                gw = InventoryGateway(sqlite, connection_factory=self._factory, cutover_enabled=True)
                first = gw.submit(
                    tipo="AJUSTE",
                    command_id=cid,
                    device_id=DEVICE,
                    operations=ops,
                )
                self.assertEqual(first.outcome, OUTCOME_APPLIED)
                self.assertEqual(client.get_balance(lid), 15000)
                retry = gw.submit(
                    tipo="AJUSTE",
                    command_id=cid,
                    device_id=DEVICE,
                    operations=ops,
                )
                self.assertEqual(retry.outcome, OUTCOME_APPLIED)
                self.assertEqual(client.get_balance(lid), 15000)
                repo = InventarioRepository(env.db)
                ok, msg = repo.ajustar_stock_directo(
                    1, 12, "cas", 1,
                    inventory_mode="authoritative",
                    inventory_connection_factory=self._factory,
                    inventory_stock_base_scaled=10000,
                )
                self.assertFalse(ok)
                self.assertIn("STALE_BALANCE", msg)
                self.assertEqual(client.get_balance(lid), 15000)
                ok2, msg2 = repo.ajustar_stock_directo(
                    1, 12, "cas-ok", 1,
                    inventory_mode="authoritative",
                    inventory_connection_factory=self._factory,
                    inventory_stock_base_scaled=15000,
                )
                self.assertTrue(ok2, msg2)
                self.assertEqual(client.get_balance(lid), 12000)
            finally:
                sqlite.close()

    def test_w13_no_bypass_y_post_apply_w01(self):
        from inventory_coordinator import InventoryCoordinatorClient

        client = InventoryCoordinatorClient(self.pg, timeout_seconds=15)
        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = seed_producto(conn, env, stock=0)
            finally:
                conn.close()
            insert_producto(self.pg, local_id=lid, stock=999)
            client.seed_balance(lid, 0)
            repo = ComprasRepository(env.db)
            cid = str(uuid.uuid4())
            ok, msg, compra_id = repo.crear_compra(
                proveedor_id=1,
                productos=[{"producto_id": 1, "cantidad": 4, "precio_unitario": 10}],
                numero_factura="PG-REC",
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_connection_factory=self._factory,
            )
            self.assertTrue(ok, msg)
            sqlite = env.connect()
            try:
                sqlite.execute("DELETE FROM detalle_compras WHERE compra_id = ?", (compra_id,))
                sqlite.execute("DELETE FROM compras WHERE id = ?", (compra_id,))
                sqlite.commit()
            finally:
                sqlite.close()
            ok2, msg2, compra2 = repo.crear_compra(
                proveedor_id=1,
                productos=[{"producto_id": 1, "cantidad": 4, "precio_unitario": 10}],
                numero_factura="PG-REC",
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_connection_factory=self._factory,
            )
            self.assertTrue(ok2, msg2)
            self.assertEqual(client.get_balance(lid), 4000)
            sqlite = env.connect()
            try:
                self.assertEqual(
                    sqlite.execute("SELECT COUNT(*) FROM compras").fetchone()[0], 1
                )
                self.assertEqual(stock_of(sqlite), 0)
            finally:
                sqlite.close()

    def test_unknown_nueva_conexion_mismo_command_id(self):
        from inventory_coordinator import InventoryCoordinatorClient, STATE_APPLIED
        from inventory_gateway import InventoryGateway, OUTCOME_APPLIED, OUTCOME_UNKNOWN
        from tests.fase1e.helpers import DEVICE, _op

        client = InventoryCoordinatorClient(self.pg, timeout_seconds=15)
        with official_temp_db() as env:
            sqlite = env.connect()
            try:
                lid = seed_producto(sqlite, env, stock=10)
                insert_producto(self.pg, local_id=lid, stock=999)
                client.seed_balance(lid, 5000)
                cid = str(uuid.uuid4())
                ops = [_op(lid, "3")]
                gw = InventoryGateway(
                    sqlite,
                    cutover_enabled=True,
                    connection_factory=self._factory,
                )
                first = gw.submit(
                    tipo="COMPRA",
                    command_id=cid,
                    device_id=DEVICE,
                    operations=ops,
                )
                self.assertIn(first.outcome, (OUTCOME_APPLIED, OUTCOME_UNKNOWN))
                sqlite.close()
                sqlite = env.connect()
                gw2 = InventoryGateway(
                    sqlite,
                    cutover_enabled=True,
                    connection_factory=self._factory,
                )
                second = gw2.submit(
                    tipo="COMPRA",
                    command_id=cid,
                    device_id=DEVICE,
                    operations=ops,
                )
                self.assertEqual(second.command_id, cid)
                self.assertEqual(second.outcome, OUTCOME_APPLIED)
                self.assertEqual(client.get_balance(lid), 8000)
                row = sqlite.execute(
                    "SELECT estado FROM inventory_commands WHERE command_id=?",
                    (cid,),
                ).fetchone()
                self.assertEqual(row["estado"], STATE_APPLIED)
            finally:
                sqlite.close()


if __name__ == "__main__":
    unittest.main()
