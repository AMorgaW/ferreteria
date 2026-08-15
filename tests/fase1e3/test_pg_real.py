# -*- coding: utf-8 -*-
"""PostgreSQL real 1E.3. Laboratorio ferrepro-pg-test:55432. No SUPABASE_URI."""
from __future__ import annotations

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
from tests.fase0.harness import official_temp_db
from tests.fase1d.pg_harness import connect, current_session_user, insert_producto
from tests.fase1e.helpers import insert_usuario, seed_producto, stock_of
from tests.fase1e1.pg_dsn import ensure_pg_test_dsn
from tests.fase1e2.helpers import ventas_service
from tests.fase1e3.helpers import (
    ALLOWED_PASSWORD,
    ALLOWED_ROLE,
    app_factory,
    force_postgres_status,
    lan_create_sale,
    mark_authoritative,
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


class Fase1E3PostgresTest(unittest.TestCase):
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

    def test_seed_one_shot_reconcile_activate_restart(self):
        from inventory_coordinator import InventoryCoordinatorClient, fetch_inventory_balance
        from inventory_cutover import (
            STATUS_AUTHORITATIVE,
            is_cutover_authoritative,
            load_cutover_state,
            run_cutover,
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
                        codigo=f"1E3-S-{i}-{uuid.uuid4().hex[:6]}",
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
                    require_app_dsn=True,
                )
                self.assertFalse(result.aborted, msg=result.error or repr(result.preconditions))
                self.assertTrue(result.reconciliation.ok, msg=repr(result.reconciliation.as_dict()))
                self.assertGreaterEqual(result.reconciliation.seeded, 4)
                self.assertEqual(result.reconciliation.missing, ())
                self.assertEqual(result.reconciliation.mismatch, ())
                self.assertEqual(result.state.status, STATUS_AUTHORITATIVE)
                client = InventoryCoordinatorClient(self.admin)
                self.assertEqual(client.get_balance(lids[0]), 0)
                self.assertEqual(client.get_balance(lids[1]), 50000)
                self.assertEqual(client.get_balance(lids[2]), 2500)
                self.assertEqual(client.get_balance(lids[3]), 10000)
                with self.admin.cursor() as cur:
                    cur.execute("UPDATE productos SET stock = 99 WHERE local_id = %s", (lids[1],))
                self.admin.commit()
                from inventory_coordinator import initialize_inventory_balances_from_legacy
                second = initialize_inventory_balances_from_legacy(self.admin)
                self.assertTrue(second.get("already_initialized"))
                self.assertEqual(client.get_balance(lids[1]), 50000)
            finally:
                conn.close()
            conn2 = env.connect()
            try:
                self.assertTrue(is_cutover_authoritative(conn2))
                self.assertEqual(load_cutover_state(conn2).status, STATUS_AUTHORITATIVE)
                self.assertGreaterEqual(load_cutover_state(conn2).epoch, 1)
            finally:
                conn2.close()

    def test_mismatch_aborta(self):
        from inventory_cutover import reconcile_seed, run_cutover

        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = seed_producto(conn, env, stock=10, codigo=f"MM-{uuid.uuid4().hex[:6]}")
                insert_producto(self.admin, local_id=lid, stock=10)
                insert_usuario(conn)
                conn.commit()
                from inventory_coordinator import seed_inventory_balance
                seed_inventory_balance(self.admin, lid, 9999)
                result = run_cutover(
                    conn,
                    admin_conn=self.admin,
                    app_factory=app_factory(),
                    environ=_app_environ(),
                )
                self.assertTrue(result.aborted)
                self.assertEqual(result.error, "reconciliation")
                self.assertFalse(result.reconciliation.ok)
                self.assertTrue(result.reconciliation.mismatch)
                self.assertNotEqual(result.state.status, "AUTHORITATIVE")
            finally:
                conn.close()

    def test_no_owner_writer_y_owner_rechazado(self):
        from inventory_coordinator import InventoryCoordinatorClient
        from inventory_cutover import assert_non_owner_app_role

        with self.assertRaises(Exception):
            assert_non_owner_app_role(self.admin)
        factory = app_factory()
        app = factory()
        try:
            session = current_session_user(app)
            self.assertEqual(session, ALLOWED_ROLE)
            assert_non_owner_app_role(app)
        finally:
            app.close()
        lid = insert_producto(self.admin, stock=50)
        client = InventoryCoordinatorClient(self.admin)
        client.seed_balance(lid, 50000)
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=50, local_id=lid, codigo=f"NO-{uuid.uuid4().hex[:6]}")
                insert_usuario(conn)
                conn.commit()
                mark_authoritative(conn, admin_conn=self.admin)
            finally:
                conn.close()
            ok, msg, venta = ventas_service(env).registrar_venta(
                items=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 1000}],
                inventory_connection_factory=factory,
            )
            self.assertTrue(ok, msg)
            self.assertIsNotNone(venta)
            self.assertEqual(client.get_balance(lid), 49000)

    def test_proyeccion_post_apply(self):
        from inventory_coordinator import InventoryCoordinatorClient

        lid = insert_producto(self.admin, stock=20)
        InventoryCoordinatorClient(self.admin).seed_balance(lid, 20000)
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=20, local_id=lid, codigo=f"PR-{uuid.uuid4().hex[:6]}")
                insert_usuario(conn)
                conn.commit()
                mark_authoritative(conn, admin_conn=self.admin)
            finally:
                conn.close()
            ok, msg, venta = ventas_service(env).registrar_venta(
                items=[{"producto_id": 1, "cantidad": 5, "precio_unitario": 1000}],
                inventory_connection_factory=app_factory(),
            )
            self.assertTrue(ok, msg)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 15)
            finally:
                conn.close()

    def test_legacy_observed_no_replay(self):
        from inventory_gateway import (
            GatewayPreCutoverBacklogError,
            InventoryGateway,
            command_is_transmittable,
            list_transmittable_command_ids,
        )
        from inventory_ledger import INTENT_CLASS_LEGACY_OBSERVED, create_inventory_command

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
                mark_authoritative(conn, admin_conn=self.admin)
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

    def test_dos_cajas_writer_level(self):
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
                seed_producto(conn, env, stock=50, local_id=lid, codigo=f"DC-{uuid.uuid4().hex[:6]}")
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            barrier.wait(timeout=15)
            ok, msg, venta = ventas_service(env).registrar_venta(
                items=[{"producto_id": 1, "cantidad": 50, "precio_unitario": 1000}],
                inventory_connection_factory=app_factory(),
            )
            results.append((ok, venta is not None, msg))

        with official_temp_db() as env_a, official_temp_db() as env_b:
            t1 = threading.Thread(target=worker, args=(env_a,))
            t2 = threading.Thread(target=worker, args=(env_b,))
            t1.start()
            t2.start()
            t1.join(timeout=30)
            t2.join(timeout=30)
        applied = [r for r in results if r[0] and r[1]]
        rejected = [r for r in results if not r[0]]
        self.assertEqual(len(results), 2, msg=repr(results))
        self.assertEqual(len(applied), 1, msg=repr(results))
        self.assertEqual(len(rejected), 1, msg=repr(results))
        self.assertEqual(InventoryCoordinatorClient(self.admin).get_balance(lid), 0)

    def test_cross_writer_venta_vs_ajuste(self):
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
                inventory_connection_factory=app_factory(),
            )
            results.append(("venta", ok, venta is not None))

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
            results.append(("ajuste", ok, False))

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

    def test_cross_writer_venta_vs_w16(self):
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

    def test_compra_applied_y_ajuste_cas(self):
        from inventory_coordinator import InventoryCoordinatorClient

        lid = insert_producto(self.admin, stock=0)
        client = InventoryCoordinatorClient(self.admin)
        client.seed_balance(lid, 0)
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=0, local_id=lid, codigo=f"CP-{uuid.uuid4().hex[:6]}")
                insert_usuario(conn)
                conn.commit()
                mark_authoritative(conn, admin_conn=self.admin)
            finally:
                conn.close()
            ok, msg, compra_id = ComprasRepository(env.db).crear_compra(
                proveedor_id=1,
                productos=[{"producto_id": 1, "cantidad": 4, "precio_unitario": 10}],
                numero_factura="1E3-C",
                inventory_connection_factory=app_factory(),
            )
            self.assertTrue(ok, msg)
            self.assertEqual(client.get_balance(lid), 4000)
            ok2, msg2 = InventarioRepository(env.db).ajustar_stock_directo(
                1, 12, "cas", 1,
                inventory_connection_factory=app_factory(),
                inventory_stock_base_scaled=0,
            )
            self.assertFalse(ok2)
            self.assertIn("STALE_BALANCE", msg2)
            ok3, msg3 = InventarioRepository(env.db).ajustar_stock_directo(
                1, 12, "cas-ok", 1,
                inventory_connection_factory=app_factory(),
                inventory_stock_base_scaled=4000,
            )
            self.assertTrue(ok3, msg3)
            self.assertEqual(client.get_balance(lid), 12000)

    def test_rejected_no_documento(self):
        from inventory_coordinator import InventoryCoordinatorClient

        lid = insert_producto(self.admin, stock=1)
        InventoryCoordinatorClient(self.admin).seed_balance(lid, 1000)
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=1, local_id=lid, codigo=f"RJ-{uuid.uuid4().hex[:6]}")
                insert_usuario(conn)
                conn.commit()
                mark_authoritative(conn, admin_conn=self.admin)
            finally:
                conn.close()
            ok, msg, venta = ventas_service(env).registrar_venta(
                items=[{"producto_id": 1, "cantidad": 5, "precio_unitario": 1000}],
                inventory_connection_factory=app_factory(),
            )
            self.assertFalse(ok)
            self.assertIsNone(venta)
            conn = env.connect()
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0], 0)
                self.assertEqual(stock_of(conn), 1)
            finally:
                conn.close()
            self.assertEqual(InventoryCoordinatorClient(self.admin).get_balance(lid), 1000)

    def test_lww_stale_no_cambia_balances(self):
        """PC B publica caché stale: inventory_balances no cambia; nombre sí sync."""
        from inventory_coordinator import InventoryCoordinatorClient
        from local_sync import SupabaseSyncService, _lww_excluded_fields

        lid = insert_producto(self.admin, stock=50, nombre="StaleA")
        client = InventoryCoordinatorClient(self.admin)
        client.seed_balance(lid, 50000)
        with official_temp_db() as env:
            pin_env_db(env)
            conn = env.connect()
            try:
                seed_producto(
                    conn, env, stock=50, local_id=lid,
                    codigo=f"LW-{uuid.uuid4().hex[:6]}",
                )
                insert_usuario(conn)
                conn.commit()
                mark_authoritative(conn, admin_conn=self.admin)
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
                self.assertEqual(_lww_excluded_fields(conn, "productos"), {"stock"})
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
                    "SELECT nombre, stock FROM productos WHERE local_id = %s",
                    (lid,),
                )
                nombre, stock_remoto = cur.fetchone()
            self.assertEqual(nombre, "StaleRenamed")
            self.assertEqual(float(stock_remoto), 50.0)
            self.admin.rollback()
            conn = env.connect()
            try:
                campos = {"nombre": "FromRemote", "stock": 50}
                for field in _lww_excluded_fields(conn, "productos"):
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


class Fase1E3StabilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_pg()

    def test_repetir_cutover_dos_cajas_tres_veces(self):
        from inventory_coordinator import InventoryCoordinatorClient
        from inventory_cutover import run_cutover

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
                        self.assertFalse(result.aborted, msg=f"iter {i}: {result.error} {result.preconditions}")
                        self.assertTrue(result.reconciliation.ok)
                    finally:
                        conn.close()
                    results = []
                    barrier = threading.Barrier(2)

                    def worker():
                        barrier.wait(timeout=15)
                        ok, msg, venta = ventas_service(env).registrar_venta(
                            items=[{"producto_id": 1, "cantidad": 50, "precio_unitario": 1000}],
                            inventory_connection_factory=app_factory(),
                        )
                        results.append(ok)

                    t1 = threading.Thread(target=worker)
                    t2 = threading.Thread(target=worker)
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
