# -*- coding: utf-8 -*-
"""1E.4: flota, fail-closed, freeze, snapshot, proyección, dos estaciones."""
from __future__ import annotations

import json
import sys
import threading
import unittest
import uuid
from pathlib import Path
from urllib.parse import quote, urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from repositories.compras_repo import ComprasRepository
from repositories.inventario_repository import InventarioRepository
from repositories.productos_repo import ProductosRepository
from tests.fase0.harness import official_temp_db
from tests.fase0.stock_writers import GATEWAY_PREPARED_IDS, UNTRACKED_DIRECT_WRITER
from tests.fase0.test_stock_writers import scan_stock_writes_by_function
from tests.fase1d.pg_harness import connect, current_session_user, insert_producto
from tests.fase1e.helpers import insert_usuario, seed_producto, stock_of
from tests.fase1e1.pg_dsn import ensure_pg_test_dsn
from tests.fase1e2.helpers import make_producto, transport_unknown, ventas_service
from tests.fase1e4.helpers import (
    ALLOWED_PASSWORD,
    ALLOWED_ROLE,
    app_factory,
    broken_factory,
    force_postgres_status,
    lan_create_sale,
    pin_env_db,
    prepare_pg,
    reset_lab_balances,
    require_pg,
)


def _app_dsn() -> str:
    raw = ensure_pg_test_dsn()
    parsed = urlparse(raw)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 55432
    db = (parsed.path or "/ferrepro_test").lstrip("/")
    return (
        f"postgresql://{quote(ALLOWED_ROLE, safe='')}:{quote(ALLOWED_PASSWORD, safe='')}"
        f"@{host}:{port}/{db}"
    )


def _app_environ():
    return {"FERREPRO_INVENTORY_DSN": _app_dsn()}


class Fase1E4PostgresTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_pg()
        admin = connect()
        try:
            with admin.cursor() as cur:
                cur.execute(
                    "ALTER TABLE productos ALTER COLUMN stock TYPE NUMERIC "
                    "USING stock::numeric"
                )
            admin.commit()
        except Exception:
            try:
                admin.rollback()
            except Exception:
                pass
        finally:
            admin.close()

    def setUp(self):
        require_pg()
        self.admin = connect()
        reset_lab_balances(self.admin)

    def tearDown(self):
        try:
            self.admin.close()
        except Exception:
            pass

    def test_01_remote_state_wins_over_stale_sqlite(self):
        from inventory_cutover import (
            STATUS_AUTHORITATIVE,
            STATUS_CUTOVER_IN_PROGRESS,
            STATUS_PRE_CUTOVER,
            load_cutover_state,
            observe_cutover_state,
        )
        from inventory_writer_support import WRITER_MODE_AUTHORITATIVE, resolve_writer_mode

        force_postgres_status(self.admin, STATUS_CUTOVER_IN_PROGRESS)
        force_postgres_status(self.admin, STATUS_AUTHORITATIVE, epoch=2)
        with official_temp_db() as env:
            conn = env.connect()
            try:
                self.assertEqual(load_cutover_state(conn).status, STATUS_PRE_CUTOVER)
                observed = observe_cutover_state(conn, pg_conn=self.admin)
                self.assertEqual(observed.status, STATUS_AUTHORITATIVE)
                self.assertEqual(observed.source, "postgres")
                self.assertEqual(load_cutover_state(conn).status, STATUS_AUTHORITATIVE)
                self.assertEqual(
                    resolve_writer_mode(
                        sqlite_conn=conn, connection_factory=app_factory()
                    ),
                    WRITER_MODE_AUTHORITATIVE,
                )
            finally:
                conn.close()

    def test_02_remote_unavailable_fail_closed_writers(self):
        from inventory_cutover import CUTOVER_STATE_UNAVAILABLE_MSG

        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=20)
                insert_usuario(conn)
                conn.commit()
                before = stock_of(conn)
            finally:
                conn.close()
            factory = broken_factory()
            ok, msg, venta = ventas_service(env).registrar_venta(
                items=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 1000}],
                inventory_connection_factory=factory,
            )
            self.assertFalse(ok)
            self.assertIsNone(venta)
            self.assertIn("CUTOVER_STATE_UNAVAILABLE", msg)
            self.assertIn("retryable", msg.lower())
            ok2, msg2, cid = ComprasRepository(env.db).crear_compra(
                proveedor_id=1,
                productos=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 10}],
                numero_factura="FC-1",
                inventory_connection_factory=factory,
            )
            self.assertFalse(ok2)
            self.assertIn("CUTOVER_STATE_UNAVAILABLE", msg2)
            ok3, msg3 = InventarioRepository(env.db).ajustar_stock_directo(
                1, 1, "fc", 1, inventory_connection_factory=factory
            )
            self.assertFalse(ok3)
            self.assertIn("CUTOVER_STATE_UNAVAILABLE", msg3)
            handler = lan_create_sale(
                env,
                [{"producto_id": 1, "cantidad": 1, "descuento": 0}],
                inventory_connection_factory=factory,
            )
            self.assertEqual(handler.status, 503)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), before)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0], 0)
            finally:
                conn.close()
            self.assertIn("CUTOVER_STATE_UNAVAILABLE", CUTOVER_STATE_UNAVAILABLE_MSG)

    def test_03_fleet_freeze_blocks_stale_station(self):
        from inventory_cutover import STATUS_CUTOVER_IN_PROGRESS, freeze_inventory_writes

        with official_temp_db() as env_a, official_temp_db() as env_b:
            conn_a = env_a.connect()
            try:
                freeze_inventory_writes(conn_a, admin_conn=self.admin)
            finally:
                conn_a.close()
            conn_b = env_b.connect()
            try:
                seed_producto(conn_b, env_b, stock=20)
                insert_usuario(conn_b)
                conn_b.commit()
                from inventory_cutover import STATUS_PRE_CUTOVER, load_cutover_state

                self.assertEqual(load_cutover_state(conn_b).status, STATUS_PRE_CUTOVER)
                before = stock_of(conn_b)
            finally:
                conn_b.close()
            factory = app_factory()
            ok, msg, venta = ventas_service(env_b).registrar_venta(
                items=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 1000}],
                inventory_connection_factory=factory,
            )
            self.assertFalse(ok)
            self.assertIsNone(venta)
            self.assertIn("congelado", msg.lower())
            ok2, msg2, cid = ComprasRepository(env_b.db).crear_compra(
                proveedor_id=1,
                productos=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 10}],
                numero_factura="FZ-B",
                inventory_connection_factory=factory,
            )
            self.assertFalse(ok2)
            self.assertIn("congelado", msg2.lower())
            ok3, msg3 = InventarioRepository(env_b.db).ajustar_stock_directo(
                1, 1, "fz", 1, inventory_connection_factory=factory
            )
            self.assertFalse(ok3)
            self.assertIn("congelado", msg3.lower())
            handler = lan_create_sale(
                env_b,
                [{"producto_id": 1, "cantidad": 1, "descuento": 0}],
                inventory_connection_factory=factory,
            )
            self.assertIn(handler.status, (409, 503))
            conn_b = env_b.connect()
            try:
                self.assertEqual(stock_of(conn_b), before)
            finally:
                conn_b.close()
            from inventory_cutover import load_postgres_cutover_state

            self.assertEqual(
                load_postgres_cutover_state(self.admin).status, STATUS_CUTOVER_IN_PROGRESS
            )

    def test_05_legacy_reconciliation_required(self):
        from inventory_cutover import run_cutover

        lid = str(uuid.uuid4())
        insert_producto(self.admin, local_id=lid, stock=10)
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=99, local_id=lid, codigo=f"DIV-{uuid.uuid4().hex[:6]}")
                insert_usuario(conn)
                conn.commit()
                result = run_cutover(
                    conn,
                    admin_conn=self.admin,
                    app_factory=app_factory(),
                    environ=_app_environ(),
                )
                self.assertTrue(result.aborted)
                self.assertEqual(result.error, "legacy_reconciliation")
                self.assertNotEqual(result.state.status, "AUTHORITATIVE")
            finally:
                conn.close()

    def test_06_07_08_09_10_snapshot_seed_mismatch_activation(self):
        from inventory_coordinator import InventoryCoordinatorClient, fetch_inventory_balance
        from inventory_cutover import (
            STATUS_AUTHORITATIVE,
            build_cutover_snapshot,
            load_cutover_snapshot,
            run_cutover,
            snapshot_checksum,
        )

        with official_temp_db() as env:
            conn = env.connect()
            try:
                lids = []
                stocks = (0, 50, 2.5, 10)
                env.insert_proveedor(conn)
                for i, stock in enumerate(stocks, start=1):
                    lid = str(uuid.uuid4())
                    env.insert_producto(
                        conn,
                        producto_id=i,
                        stock=stock,
                        local_id=lid,
                        codigo=f"1E4-S-{i}-{uuid.uuid4().hex[:6]}",
                    )
                    insert_producto(self.admin, local_id=lid, stock=stock, nombre=f"P{i}")
                    lids.append(lid)
                insert_usuario(conn)
                conn.commit()
                result = run_cutover(
                    conn,
                    admin_conn=self.admin,
                    app_factory=app_factory(),
                    device_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                    environ=_app_environ(),
                )
                self.assertFalse(result.aborted, msg=result.error or repr(result.preconditions))
                self.assertIsNotNone(result.snapshot)
                self.assertTrue(result.reconciliation.ok)
                self.assertEqual(result.state.status, STATUS_AUTHORITATIVE)
                snap = result.snapshot
                identity = {
                    "cutover_id": snap.cutover_id,
                    "epoch": snap.epoch,
                    "source": snap.source,
                    "lines": [
                        {
                            "producto_local_id": line.producto_local_id,
                            "quantity_scaled": line.quantity_scaled,
                        }
                        for line in snap.lines
                    ],
                }
                self.assertEqual(snapshot_checksum(identity), snap.checksum)
                loaded = load_cutover_snapshot(conn, snap.cutover_id)
                self.assertEqual(loaded.checksum, snap.checksum)
                self.assertEqual(loaded.quantity_identity(), snap.quantity_identity())
                mutated = build_cutover_snapshot(
                    [(lids[1], 1)], epoch=snap.epoch, cutover_id=snap.cutover_id
                )
                self.assertNotEqual(mutated.checksum, snap.checksum)
                client = InventoryCoordinatorClient(self.admin)
                self.assertEqual(client.get_balance(lids[0]), 0)
                self.assertEqual(client.get_balance(lids[1]), 50000)
                self.assertEqual(fetch_inventory_balance(self.admin, lids[2]), 2500)
            finally:
                conn.close()

        reset_lab_balances(self.admin)
        lid = str(uuid.uuid4())
        insert_producto(self.admin, local_id=lid, stock=10)
        from inventory_coordinator import seed_inventory_balance
        from inventory_cutover import run_cutover as run_cutover_mismatch

        seed_inventory_balance(self.admin, lid, 9999)
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10, local_id=lid, codigo=f"MM-{uuid.uuid4().hex[:6]}")
                insert_usuario(conn)
                conn.commit()
                result = run_cutover_mismatch(
                    conn,
                    admin_conn=self.admin,
                    app_factory=app_factory(),
                    environ=_app_environ(),
                )
                self.assertTrue(result.aborted)
                self.assertEqual(result.error, "reconciliation")
                self.assertNotEqual(result.state.status, "AUTHORITATIVE")
            finally:
                conn.close()

    def test_11_restart_new_process_resolves_global(self):
        from inventory_coordinator import InventoryCoordinatorClient
        from inventory_cutover import (
            STATUS_AUTHORITATIVE,
            observe_cutover_state,
            run_cutover,
        )
        from inventory_gateway import InventoryGateway
        from inventory_writer_support import WRITER_MODE_AUTHORITATIVE, resolve_writer_mode

        lid = str(uuid.uuid4())
        insert_producto(self.admin, local_id=lid, stock=8)
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=8, local_id=lid, codigo=f"RS-{uuid.uuid4().hex[:6]}")
                insert_usuario(conn)
                conn.commit()
                result = run_cutover(
                    conn,
                    admin_conn=self.admin,
                    app_factory=app_factory(),
                    environ=_app_environ(),
                )
                self.assertFalse(result.aborted, msg=result.error)
            finally:
                conn.close()
        pg3 = connect()
        factory = app_factory()
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=8, local_id=lid, codigo=f"RS2-{uuid.uuid4().hex[:6]}")
                insert_usuario(conn)
                conn.commit()
                state = observe_cutover_state(conn, connection_factory=factory)
                self.assertEqual(state.status, STATUS_AUTHORITATIVE)
                self.assertEqual(
                    resolve_writer_mode(sqlite_conn=conn, connection_factory=factory),
                    WRITER_MODE_AUTHORITATIVE,
                )
                gw = InventoryGateway(conn, connection_factory=factory)
                self.assertTrue(gw.cutover_is_on)
                ok, msg, venta = ventas_service(env).registrar_venta(
                    items=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 1000}],
                    inventory_connection_factory=factory,
                )
                self.assertTrue(ok, msg)
                self.assertEqual(InventoryCoordinatorClient(pg3).get_balance(lid), 7000)
            finally:
                conn.close()
                pg3.close()

    def test_12_w08_stale_base_cas(self):
        from inventory_coordinator import InventoryCoordinatorClient
        from inventory_cutover import STATUS_AUTHORITATIVE, STATUS_CUTOVER_IN_PROGRESS

        lid = insert_producto(self.admin, stock=50)
        InventoryCoordinatorClient(self.admin).seed_balance(lid, 40000)
        force_postgres_status(self.admin, STATUS_CUTOVER_IN_PROGRESS)
        force_postgres_status(self.admin, STATUS_AUTHORITATIVE, epoch=1)
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=50, local_id=lid, codigo=f"W8-{uuid.uuid4().hex[:6]}")
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            prod = make_producto(id=1, nombre="StaleSet", stock=30)
            ok, msg = ProductosRepository(env.db).actualizar_producto(
                prod,
                inventory_connection_factory=app_factory(),
                inventory_stock_base_scaled=50000,
            )
            self.assertFalse(ok)
            self.assertIn("STALE_BALANCE", msg)
            self.assertEqual(InventoryCoordinatorClient(self.admin).get_balance(lid), 40000)
            ok2, msg2 = ProductosRepository(env.db).actualizar_producto(
                prod,
                inventory_connection_factory=app_factory(),
            )
            self.assertTrue(ok2, msg2)
            self.assertEqual(InventoryCoordinatorClient(self.admin).get_balance(lid), 30000)

    def test_13_14_15_projection_metadata_lww(self):
        from inventory_coordinator import InventoryCoordinatorClient
        from inventory_cutover import STATUS_AUTHORITATIVE, STATUS_CUTOVER_IN_PROGRESS
        from local_sync import SupabaseSyncService, _lww_excluded_fields

        lid = insert_producto(self.admin, stock=50, nombre="StaleA")
        client = InventoryCoordinatorClient(self.admin)
        client.seed_balance(lid, 50000)
        force_postgres_status(self.admin, STATUS_CUTOVER_IN_PROGRESS)
        force_postgres_status(self.admin, STATUS_AUTHORITATIVE, epoch=1)
        with official_temp_db() as env:
            pin_env_db(env)
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=50, local_id=lid, codigo=f"LW-{uuid.uuid4().hex[:6]}")
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            ok, msg, venta = ventas_service(env).registrar_venta(
                items=[{"producto_id": 1, "cantidad": 10, "precio_unitario": 1000}],
                inventory_connection_factory=app_factory(),
            )
            self.assertTrue(ok, msg)
            self.assertEqual(client.get_balance(lid), 40000)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 40)
                self.assertEqual(
                    _lww_excluded_fields(conn, "productos", self.admin), {"stock"}
                )
                svc = SupabaseSyncService(db_path=str(env.db_path))
                svc._upsert(
                    self.admin,
                    conn,
                    "productos",
                    {"local_id": lid, "nombre": "StaleRenamed", "stock": 50},
                    {},
                )
                self.admin.commit()
            finally:
                conn.close()
            self.assertEqual(client.get_balance(lid), 40000)
            with self.admin.cursor() as cur:
                cur.execute(
                    "SELECT nombre, stock FROM productos WHERE local_id = %s", (lid,)
                )
                nombre, stock_remoto = cur.fetchone()
            self.assertEqual(nombre, "StaleRenamed")
            self.assertEqual(float(stock_remoto), 50.0)
            self.admin.rollback()
            conn = env.connect()
            try:
                campos = {"nombre": "FromRemote", "stock": 50}
                for field in _lww_excluded_fields(conn, "productos", self.admin):
                    campos.pop(field, None)
                sets = ", ".join(f"{k} = ?" for k in campos)
                conn.execute(
                    f"UPDATE productos SET {sets} WHERE local_id = ?",
                    (*campos.values(), lid),
                )
                conn.commit()
                self.assertEqual(stock_of(conn), 40)
                row = conn.execute(
                    "SELECT nombre FROM productos WHERE local_id = ?", (lid,)
                ).fetchone()
                self.assertEqual(row[0], "FromRemote")
            finally:
                conn.close()
            self.assertEqual(client.get_balance(lid), 40000)

    def test_16_17_command_id_survives_restart_unknown(self):
        from inventory_cutover import (
            ACT_KIND_POS_CHECKOUT,
            begin_or_resume_open_act,
            STATUS_AUTHORITATIVE,
            STATUS_CUTOVER_IN_PROGRESS,
        )

        force_postgres_status(self.admin, STATUS_CUTOVER_IN_PROGRESS)
        force_postgres_status(self.admin, STATUS_AUTHORITATIVE, epoch=1)
        items = [{"producto_id": 1, "cantidad": 1, "precio_unitario": 1000}]
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=20)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            transport = transport_unknown()
            factory = app_factory()
            svc = ventas_service(env)
            ok, msg, venta = svc.registrar_venta(
                items=items,
                inventory_connection_factory=factory,
                inventory_transport=transport,
            )
            self.assertFalse(ok)
            self.assertIsNone(venta)
            self.assertIn("INVENTORY_UNKNOWN", msg)
            cid = svc.last_inventory_command_id
            self.assertTrue(cid)
            conn = env.connect()
            try:
                resumed = begin_or_resume_open_act(conn, ACT_KIND_POS_CHECKOUT)
            finally:
                conn.close()
            self.assertEqual(resumed, cid)
            svc2 = ventas_service(env)
            ok2, msg2, venta2 = svc2.registrar_venta(
                items=items,
                inventory_connection_factory=factory,
                inventory_transport=transport,
            )
            self.assertFalse(ok2)
            self.assertEqual(svc2.last_inventory_command_id, cid)
            conn = env.connect()
            try:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM inventory_commands").fetchone()[0],
                    1,
                )
            finally:
                conn.close()
            handler = lan_create_sale(
                env,
                [{"producto_id": 1, "cantidad": 1, "descuento": 0}],
                inventory_connection_factory=factory,
                inventory_transport=transport,
            )
            self.assertEqual(handler.status, 503)
            data = json.loads(handler.wfile.getvalue().decode("utf-8"))
            lan_cid = data.get("command_id")
            self.assertTrue(lan_cid)
            handler2 = lan_create_sale(
                env,
                [{"producto_id": 1, "cantidad": 1, "descuento": 0}],
                inventory_connection_factory=factory,
                inventory_transport=transport,
            )
            self.assertEqual(handler2.status, 503)
            data2 = json.loads(handler2.wfile.getvalue().decode("utf-8"))
            self.assertEqual(data2.get("command_id"), lan_cid)

    def test_18_two_station_last_stock(self):
        from inventory_coordinator import InventoryCoordinatorClient
        from inventory_cutover import STATUS_AUTHORITATIVE, STATUS_CUTOVER_IN_PROGRESS

        lid = insert_producto(self.admin, stock=50)
        InventoryCoordinatorClient(self.admin).seed_balance(lid, 50000)
        force_postgres_status(self.admin, STATUS_CUTOVER_IN_PROGRESS)
        force_postgres_status(self.admin, STATUS_AUTHORITATIVE, epoch=1)
        results = []
        barrier = threading.Barrier(2)

        def worker(env):
            pin_env_db(env)
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=50, local_id=lid, codigo=f"TS-{uuid.uuid4().hex[:6]}")
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            barrier.wait(timeout=15)
            ok, msg, venta = ventas_service(env).registrar_venta(
                items=[{"producto_id": 1, "cantidad": 50, "precio_unitario": 1000}],
                inventory_command_id=str(uuid.uuid4()),
                inventory_connection_factory=app_factory(),
            )
            conn = env.connect()
            try:
                n_ventas = conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0]
            finally:
                conn.close()
            results.append((ok, venta is not None, msg, n_ventas))

        with official_temp_db() as env_a, official_temp_db() as env_b:
            t1 = threading.Thread(target=worker, args=(env_a,))
            t2 = threading.Thread(target=worker, args=(env_b,))
            t1.start()
            t2.start()
            t1.join(timeout=30)
            t2.join(timeout=30)
        for ok, has_venta, msg, n_ventas in results:
            if not (ok and has_venta):
                self.assertEqual(n_ventas, 0, msg=repr(results))
        applied = [r for r in results if r[0] and r[1]]
        rejected = [r for r in results if not r[0]]
        self.assertEqual(len(results), 2, msg=repr(results))
        self.assertEqual(len(applied), 1, msg=repr(results))
        self.assertEqual(len(rejected), 1, msg=repr(results))
        self.assertEqual(InventoryCoordinatorClient(self.admin).get_balance(lid), 0)

    def test_19_cross_writer_venta_vs_ajuste(self):
        from inventory_coordinator import InventoryCoordinatorClient
        from inventory_cutover import STATUS_AUTHORITATIVE, STATUS_CUTOVER_IN_PROGRESS

        lid = insert_producto(self.admin, stock=50)
        InventoryCoordinatorClient(self.admin).seed_balance(lid, 50000)
        force_postgres_status(self.admin, STATUS_CUTOVER_IN_PROGRESS)
        force_postgres_status(self.admin, STATUS_AUTHORITATIVE, epoch=1)
        results = []
        barrier = threading.Barrier(2)

        def sale_worker(env):
            pin_env_db(env)
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=50, local_id=lid, codigo=f"CV-{uuid.uuid4().hex[:6]}")
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            barrier.wait(timeout=15)
            ok, msg, venta = ventas_service(env).registrar_venta(
                items=[{"producto_id": 1, "cantidad": 50, "precio_unitario": 1000}],
                inventory_command_id=str(uuid.uuid4()),
                inventory_connection_factory=app_factory(),
            )
            results.append(("venta", ok))

        def adjust_worker(env):
            pin_env_db(env)
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=50, local_id=lid, codigo=f"CA-{uuid.uuid4().hex[:6]}")
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            barrier.wait(timeout=15)
            ok, msg = InventarioRepository(env.db).ajustar_stock_directo(
                1, 0, "race", 1,
                inventory_connection_factory=app_factory(),
                inventory_stock_base_scaled=50000,
            )
            results.append(("ajuste", ok))

        with official_temp_db() as env_a, official_temp_db() as env_b:
            t1 = threading.Thread(target=sale_worker, args=(env_a,))
            t2 = threading.Thread(target=adjust_worker, args=(env_b,))
            t1.start()
            t2.start()
            t1.join(timeout=30)
            t2.join(timeout=30)
        applied = [r for r in results if r[1]]
        self.assertEqual(len(applied), 1, msg=repr(results))
        self.assertEqual(InventoryCoordinatorClient(self.admin).get_balance(lid), 0)

    def test_20_w03_vs_w16(self):
        from inventory_coordinator import InventoryCoordinatorClient
        from inventory_cutover import STATUS_AUTHORITATIVE, STATUS_CUTOVER_IN_PROGRESS

        lid = insert_producto(self.admin, stock=50)
        InventoryCoordinatorClient(self.admin).seed_balance(lid, 50000)
        force_postgres_status(self.admin, STATUS_CUTOVER_IN_PROGRESS)
        force_postgres_status(self.admin, STATUS_AUTHORITATIVE, epoch=1)
        results = []
        barrier = threading.Barrier(2)

        def sale_worker(env):
            pin_env_db(env)
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=50, local_id=lid, codigo=f"W3-{uuid.uuid4().hex[:6]}")
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            barrier.wait(timeout=15)
            ok, msg, venta = ventas_service(env).registrar_venta(
                items=[{"producto_id": 1, "cantidad": 50, "precio_unitario": 1000}],
                inventory_command_id=str(uuid.uuid4()),
                inventory_connection_factory=app_factory(),
            )
            results.append(("w03", ok))

        def lan_worker(env):
            pin_env_db(env)
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=50, local_id=lid, codigo=f"W6-{uuid.uuid4().hex[:6]}")
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            barrier.wait(timeout=15)
            handler = lan_create_sale(
                env,
                [{"producto_id": 1, "cantidad": 50, "descuento": 0}],
                inventory_connection_factory=app_factory(),
            )
            results.append(("w16", handler.status == 201))

        with official_temp_db() as env_a, official_temp_db() as env_b:
            t1 = threading.Thread(target=sale_worker, args=(env_a,))
            t2 = threading.Thread(target=lan_worker, args=(env_b,))
            t1.start()
            t2.start()
            t1.join(timeout=30)
            t2.join(timeout=30)
        applied = [r for r in results if r[1]]
        self.assertEqual(len(applied), 1, msg=repr(results))
        self.assertEqual(InventoryCoordinatorClient(self.admin).get_balance(lid), 0)

    def test_21_backlog_blocked(self):
        from inventory_gateway import (
            InventoryGateway,
            command_is_transmittable,
            list_transmittable_command_ids,
        )
        from inventory_ledger import INTENT_CLASS_LEGACY_OBSERVED

        lid = insert_producto(self.admin, stock=10)
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10, local_id=lid, codigo=f"LO-{uuid.uuid4().hex[:6]}")
                insert_usuario(conn)
                conn.commit()
                gw = InventoryGateway(conn, cutover_enabled=False)
                result = gw.submit(
                    tipo="VENTA",
                    operations=[{
                        "operation_id": str(uuid.uuid4()),
                        "producto_local_id": lid,
                        "line_no": 1,
                        "delta_scaled": -1000,
                    }],
                    device_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                )
                self.assertEqual(result.record.intent_class, INTENT_CLASS_LEGACY_OBSERVED)
                self.assertFalse(command_is_transmittable(result.record))
                from inventory_cutover import run_cutover

                cut = run_cutover(
                    conn,
                    admin_conn=self.admin,
                    app_factory=app_factory(),
                    environ=_app_environ(),
                )
                self.assertFalse(cut.aborted, msg=cut.error)
                self.assertEqual(list_transmittable_command_ids(conn), ())
                gw2 = InventoryGateway(
                    conn, connection_factory=app_factory(), cutover_enabled=True
                )
                again = gw2.submit(
                    tipo="VENTA",
                    command_id=result.command_id,
                    operations=[{
                        "operation_id": str(uuid.uuid4()),
                        "producto_local_id": lid,
                        "line_no": 1,
                        "delta_scaled": -1000,
                    }],
                    device_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                )
                self.assertEqual(again.outcome, "LEGACY_OBSERVED")
            finally:
                conn.close()

    def test_22_23_rollback_two_stations(self):
        from inventory_cutover import (
            STATUS_AUTHORITATIVE,
            STATUS_CUTOVER_IN_PROGRESS,
            STATUS_ROLLBACK_SAFE,
            UnsafeRollbackError,
            abort_pre_activation,
            freeze_inventory_writes,
            load_postgres_cutover_state,
        )

        with official_temp_db() as env_a, official_temp_db() as env_b:
            conn_a = env_a.connect()
            try:
                freeze_inventory_writes(conn_a, admin_conn=self.admin)
                state = abort_pre_activation(conn_a, admin_conn=self.admin, reason="lab")
                self.assertEqual(state.status, STATUS_ROLLBACK_SAFE)
                self.assertEqual(
                    load_postgres_cutover_state(self.admin).status, STATUS_ROLLBACK_SAFE
                )
            finally:
                conn_a.close()
            conn_b = env_b.connect()
            try:
                from inventory_cutover import observe_cutover_state

                observed = observe_cutover_state(conn_b, pg_conn=self.admin)
                self.assertEqual(observed.status, STATUS_ROLLBACK_SAFE)
            finally:
                conn_b.close()

        reset_lab_balances(self.admin)
        lid = insert_producto(self.admin, stock=5)
        from inventory_coordinator import InventoryCoordinatorClient

        InventoryCoordinatorClient(self.admin).seed_balance(lid, 5000)
        force_postgres_status(self.admin, STATUS_CUTOVER_IN_PROGRESS)
        force_postgres_status(self.admin, STATUS_AUTHORITATIVE, epoch=1)
        with official_temp_db() as env_a, official_temp_db() as env_b:
            pin_env_db(env_a)
            conn_a = env_a.connect()
            try:
                seed_producto(conn_a, env_a, stock=5, local_id=lid, codigo=f"RB-{uuid.uuid4().hex[:6]}")
                insert_usuario(conn_a)
                conn_a.commit()
                self.assertIsNotNone(
                    conn_a.execute("SELECT id FROM productos WHERE id = 1").fetchone()
                )
            finally:
                conn_a.close()
            ok, msg, venta = ventas_service(env_a).registrar_venta(
                items=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 1000}],
                inventory_connection_factory=app_factory(),
            )
            self.assertTrue(ok, msg)
            conn_b = env_b.connect()
            try:
                with self.assertRaises(UnsafeRollbackError):
                    abort_pre_activation(conn_b, admin_conn=self.admin)
                self.assertEqual(
                    load_postgres_cutover_state(self.admin).status, STATUS_AUTHORITATIVE
                )
            finally:
                conn_b.close()

    def test_24_no_owner_operation(self):
        from inventory_coordinator import InventoryCoordinatorClient
        from inventory_cutover import (
            STATUS_AUTHORITATIVE,
            STATUS_CUTOVER_IN_PROGRESS,
            assert_non_owner_app_role,
        )

        with self.assertRaises(Exception):
            assert_non_owner_app_role(self.admin)
        factory = app_factory()
        app = factory()
        try:
            self.assertEqual(current_session_user(app), ALLOWED_ROLE)
            assert_non_owner_app_role(app)
        finally:
            app.close()
        lid = insert_producto(self.admin, stock=50)
        InventoryCoordinatorClient(self.admin).seed_balance(lid, 50000)
        force_postgres_status(self.admin, STATUS_CUTOVER_IN_PROGRESS)
        force_postgres_status(self.admin, STATUS_AUTHORITATIVE, epoch=1)
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=50, local_id=lid, codigo=f"NO-{uuid.uuid4().hex[:6]}")
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            ok, msg, venta = ventas_service(env).registrar_venta(
                items=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 1000}],
                inventory_connection_factory=factory,
            )
            self.assertTrue(ok, msg)
            self.assertEqual(InventoryCoordinatorClient(self.admin).get_balance(lid), 49000)

    def test_25_scanner_no_bypass(self):
        from inventory_cutover import verify_preconditions
        from inventory_writer_contract import PREPARED_DIRECT_WRITER_IDS

        src = Path(REPO_ROOT / "inventory_cutover.py").read_text(encoding="utf-8")
        self.assertNotIn("from tests.fase0.stock_writers", src)
        self.assertNotIn("scan_stock_writes_by_function", src)
        hits = scan_stock_writes_by_function()
        untracked = [h for h in hits if h["status"] == UNTRACKED_DIRECT_WRITER]
        self.assertFalse(untracked, msg=repr(untracked))
        self.assertEqual(PREPARED_DIRECT_WRITER_IDS, GATEWAY_PREPARED_IDS)
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=1)
                failures = verify_preconditions(
                    conn, require_app_dsn=False, app_factory=None
                )
                self.assertFalse(
                    any("contrato writers" in f for f in failures), msg=repr(failures)
                )
            finally:
                conn.close()

    def test_26_post_authoritative_error_keeps_global_authority(self):
        from unittest.mock import patch

        from inventory_cutover import (
            STATUS_AUTHORITATIVE,
            STATUS_FAILED,
            load_postgres_cutover_state,
        )
        import inventory_cutover as ic

        lid = str(uuid.uuid4())
        insert_producto(self.admin, local_id=lid, stock=4)
        real_activate = ic.activate_authority

        def boom(*args, **kwargs):
            real_activate(*args, **kwargs)
            raise RuntimeError("post-AUTHORITATIVE")

        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(
                    conn, env, stock=4, local_id=lid,
                    codigo=f"FA-{uuid.uuid4().hex[:6]}",
                )
                insert_usuario(conn)
                conn.commit()
                with patch.object(ic, "activate_authority", boom):
                    result = ic.run_cutover(
                        conn,
                        admin_conn=self.admin,
                        app_factory=app_factory(),
                        environ=_app_environ(),
                    )
                remote = load_postgres_cutover_state(self.admin)
                self.assertEqual(remote.status, STATUS_AUTHORITATIVE)
                self.assertNotEqual(remote.status, STATUS_FAILED)
                self.assertFalse(result.aborted)
                self.assertEqual(result.state.status, STATUS_AUTHORITATIVE)
            finally:
                conn.close()


class Fase1E4StabilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_pg()

    def test_stability_three_times(self):
        from inventory_coordinator import InventoryCoordinatorClient
        from inventory_cutover import (
            STATUS_AUTHORITATIVE,
            STATUS_CUTOVER_IN_PROGRESS,
            freeze_inventory_writes,
            run_cutover,
        )

        for i in range(3):
            admin = connect()
            try:
                reset_lab_balances(admin)
                lid = insert_producto(admin, stock=50, nombre=f"ST{i}")
                with official_temp_db() as env:
                    conn = env.connect()
                    try:
                        seed_producto(
                            conn, env, stock=50, local_id=lid,
                            codigo=f"ST-{i}-{uuid.uuid4().hex[:6]}",
                        )
                        insert_usuario(conn)
                        conn.commit()
                        result = run_cutover(
                            conn,
                            admin_conn=admin,
                            app_factory=app_factory(),
                            environ=_app_environ(),
                        )
                        self.assertFalse(
                            result.aborted,
                            msg=f"iter {i}: {result.error} {result.preconditions}",
                        )
                        self.assertTrue(result.reconciliation.ok)
                        self.assertIsNotNone(result.snapshot)
                    finally:
                        conn.close()
                reset_lab_balances(admin)
                with official_temp_db() as env_a, official_temp_db() as env_b:
                    conn_a = env_a.connect()
                    try:
                        freeze_inventory_writes(conn_a, admin_conn=admin)
                    finally:
                        conn_a.close()
                    conn_b = env_b.connect()
                    try:
                        seed_producto(
                            conn_b, env_b, stock=50, local_id=lid,
                            codigo=f"FZB-{i}-{uuid.uuid4().hex[:6]}",
                        )
                        insert_usuario(conn_b)
                        conn_b.commit()
                    finally:
                        conn_b.close()
                    ok, msg, venta = ventas_service(env_b).registrar_venta(
                        items=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 1000}],
                        inventory_connection_factory=app_factory(),
                    )
                    self.assertFalse(ok, msg=f"freeze iter {i}: {msg}")
                    self.assertIn("congelado", msg.lower())
                reset_lab_balances(admin)
                insert_producto(admin, local_id=lid, stock=50, nombre=f"ST{i}")
                InventoryCoordinatorClient(admin).seed_balance(lid, 50000)
                force_postgres_status(admin, STATUS_CUTOVER_IN_PROGRESS)
                force_postgres_status(admin, STATUS_AUTHORITATIVE, epoch=1)
                results = []
                barrier = threading.Barrier(2)

                def worker(env):
                    pin_env_db(env)
                    conn = env.connect()
                    try:
                        seed_producto(
                            conn, env, stock=50, local_id=lid,
                            codigo=f"2S-{i}-{uuid.uuid4().hex[:6]}",
                        )
                        insert_usuario(conn)
                        conn.commit()
                    finally:
                        conn.close()
                    barrier.wait(timeout=15)
                    ok, msg, venta = ventas_service(env).registrar_venta(
                        items=[{"producto_id": 1, "cantidad": 50, "precio_unitario": 1000}],
                        inventory_command_id=str(uuid.uuid4()),
                        inventory_connection_factory=app_factory(),
                    )
                    results.append(ok)

                with official_temp_db() as env_a, official_temp_db() as env_b:
                    t1 = threading.Thread(target=worker, args=(env_a,))
                    t2 = threading.Thread(target=worker, args=(env_b,))
                    t1.start()
                    t2.start()
                    t1.join(timeout=30)
                    t2.join(timeout=30)
                self.assertEqual(sum(1 for r in results if r), 1, msg=f"iter {i} {results}")
                self.assertEqual(InventoryCoordinatorClient(admin).get_balance(lid), 0)
            finally:
                admin.close()


if __name__ == "__main__":
    unittest.main()
