# -*- coding: utf-8 -*-
"""1E.4B PostgreSQL real: freeze TOCTOU, sets, CAS, W01 crash, inflight, seed."""
from __future__ import annotations

import os
import sys
import threading
import unittest
import uuid
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from repositories.compras_repo import ComprasRepository, registrar_compra_desde_ui
from repositories.inventario_repository import InventarioRepository
from tests.fase0.harness import official_temp_db
from tests.fase1d.pg_harness import connect, insert_producto
from tests.fase1e.helpers import insert_usuario, seed_producto, stock_of
from tests.fase1e1.helpers import transport_applied, ventas_service
from tests.fase1e1.pg_dsn import ensure_pg_test_dsn
from tests.fase1e4b.helpers import (
    ALLOWED_PASSWORD,
    ALLOWED_ROLE,
    app_factory,
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


class Fase1E4BPostgresTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_pg()
        admin = connect()
        try:
            from inventory_cutover import ensure_postgres_cutover_schema

            ensure_postgres_cutover_schema(admin)
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
        from inventory_cutover import (
            set_after_legacy_allow_hook,
            set_after_legacy_share_hook,
            set_after_postgres_freeze_hook,
        )

        set_after_legacy_allow_hook(None)
        set_after_legacy_share_hook(None)
        set_after_postgres_freeze_hook(None)
        import inventory_writer_support as iws

        iws.after_remote_apply_hook = None
        try:
            self.admin.close()
        except Exception:
            pass

    def test_writer_started_before_freeze_cannot_commit_legacy_stock(self):
        from inventory_cutover import (
            STATUS_CUTOVER_IN_PROGRESS,
            freeze_inventory_writes,
            load_postgres_cutover_state,
            set_after_legacy_allow_hook,
            set_after_postgres_freeze_hook,
        )

        factory = app_factory()
        for _round in range(5):
            reset_lab_balances(self.admin)
            started = threading.Event()
            freeze_published = threading.Event()
            freeze_done = threading.Event()
            errors = []

            def hook(_state):
                started.set()
                self.assertTrue(
                    freeze_published.wait(15), "freeze PG no publicó a tiempo"
                )

            def after_pg_freeze():
                freeze_published.set()

            set_after_legacy_allow_hook(hook)
            set_after_postgres_freeze_hook(after_pg_freeze)

            with official_temp_db() as env:
                pin_env_db(env)
                conn = env.connect()
                try:
                    seed_producto(conn, env, stock=50)
                    insert_usuario(conn)
                    conn.commit()
                finally:
                    conn.close()

                def freeze_station():
                    sqlite = None
                    admin = None
                    try:
                        self.assertTrue(started.wait(15))
                        sqlite = env.connect()
                        admin = connect()
                        freeze_inventory_writes(
                            sqlite, admin_conn=admin, device_id="freeze-station"
                        )
                    except Exception as exc:
                        errors.append(exc)
                    finally:
                        freeze_published.set()
                        freeze_done.set()
                        for item in (sqlite, admin):
                            if item is None:
                                continue
                            try:
                                item.close()
                            except Exception:
                                pass

                t_freeze = threading.Thread(target=freeze_station, daemon=True)
                t_freeze.start()
                ok, msg, venta = ventas_service(env).registrar_venta(
                    items=[{"producto_id": 1, "cantidad": 5, "precio_unitario": 1000}],
                    inventory_connection_factory=factory,
                )
                t_freeze.join(20)
                self.assertFalse(errors, errors)
                self.assertFalse(ok, msg)
                self.assertIsNone(venta)
                remote = load_postgres_cutover_state(self.admin, ensure_schema=False)
                self.assertEqual(remote.status, STATUS_CUTOVER_IN_PROGRESS)
                conn = env.connect()
                try:
                    self.assertEqual(int(stock_of(conn)), 50)
                    self.assertEqual(
                        conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0], 0
                    )
                finally:
                    conn.close()
            set_after_legacy_allow_hook(None)
            set_after_postgres_freeze_hook(None)

    def test_writer_that_wins_fence_is_visible_before_snapshot(self):
        from inventory_cutover import (
            freeze_inventory_writes,
            set_after_legacy_share_hook,
        )

        factory = app_factory()
        for _round in range(5):
            reset_lab_balances(self.admin)
            holding = threading.Event()
            proceed = threading.Event()
            freeze_errors = []
            freeze_done = threading.Event()

            def after_share(_status, _epoch):
                holding.set()
                self.assertTrue(proceed.wait(15))

            set_after_legacy_share_hook(after_share)

            with official_temp_db() as env:
                pin_env_db(env)
                conn = env.connect()
                try:
                    seed_producto(conn, env, stock=50)
                    insert_usuario(conn)
                    conn.commit()
                finally:
                    conn.close()

                def freeze_station():
                    sqlite = None
                    admin = None
                    try:
                        self.assertTrue(holding.wait(15))
                        sqlite = env.connect()
                        admin = connect()
                        freeze_inventory_writes(
                            sqlite, admin_conn=admin, device_id="wait-writer"
                        )
                    except Exception as exc:
                        freeze_errors.append(exc)
                    finally:
                        freeze_done.set()
                        for item in (sqlite, admin):
                            if item is None:
                                continue
                            try:
                                item.close()
                            except Exception:
                                pass

                t_sale_result = {}

                def do_sale():
                    try:
                        ok, msg, venta = ventas_service(env).registrar_venta(
                            items=[
                                {
                                    "producto_id": 1,
                                    "cantidad": 5,
                                    "precio_unitario": 1000,
                                }
                            ],
                            inventory_connection_factory=factory,
                        )
                        t_sale_result["ok"] = ok
                        t_sale_result["msg"] = msg
                        t_sale_result["venta"] = venta
                    except Exception as exc:
                        t_sale_result["ok"] = False
                        t_sale_result["msg"] = str(exc)

                t_sale = threading.Thread(target=do_sale, daemon=True)
                t_sale.start()
                self.assertTrue(
                    holding.wait(20),
                    f"writer no tomó el fence central: {t_sale_result}",
                )
                t_freeze = threading.Thread(target=freeze_station, daemon=True)
                t_freeze.start()
                self.assertFalse(freeze_done.wait(0.3), "freeze no debe ganar el fence")
                proceed.set()
                t_sale.join(20)
                t_freeze.join(20)
                self.assertTrue(t_sale_result.get("ok"), t_sale_result.get("msg"))
                self.assertFalse(freeze_errors, freeze_errors)
                conn = env.connect()
                try:
                    self.assertEqual(int(stock_of(conn)), 45)
                finally:
                    conn.close()
            set_after_legacy_share_hook(None)

    def test_cutover_rejects_postgres_products_missing_locally(self):
        from inventory_cutover import reconcile_legacy_sources

        lid_local = str(uuid.uuid4())
        lid_remote_only = str(uuid.uuid4())
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10, local_id=lid_local)
                insert_producto(self.admin, local_id=lid_local, stock=10)
                insert_producto(
                    self.admin, local_id=lid_remote_only, stock=3, nombre="PG-only"
                )
                report = reconcile_legacy_sources(conn, self.admin)
                self.assertFalse(report.ok)
                self.assertIn(lid_remote_only, report.postgres_only)
                self.assertIn(lid_remote_only, report.extra_unexpected)
            finally:
                conn.close()

    def test_cutover_rejects_sqlite_product_missing_remotely(self):
        from inventory_cutover import reconcile_legacy_sources

        lid = str(uuid.uuid4())
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10, local_id=lid)
                report = reconcile_legacy_sources(conn, self.admin)
                self.assertFalse(report.ok)
                self.assertIn(lid, report.sqlite_only)
                self.assertIn(lid, report.missing)
            finally:
                conn.close()

    def test_cutover_rejects_invalid_and_null_local_id(self):
        from inventory_cutover import reconcile_legacy_sources

        lid = str(uuid.uuid4())
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10, local_id=lid)
                insert_producto(self.admin, local_id=lid, stock=10)
                conn.execute(
                    "INSERT INTO productos (id, codigo_barras, nombre, precio_venta, "
                    "stock, activo, proveedor_id, local_id) "
                    "VALUES (99, 'BAD-1E4B', 'invalido', 1, 1, 1, 1, 'not-a-uuid')"
                )
                conn.execute(
                    "INSERT INTO productos (id, codigo_barras, nombre, precio_venta, "
                    "stock, activo, proveedor_id, local_id) "
                    "VALUES (100, 'NULL-1E4B', 'nulo', 1, 1, 1, 1, NULL)"
                )
                conn.commit()
                report = reconcile_legacy_sources(conn, self.admin)
                self.assertFalse(report.ok)
                self.assertTrue(report.invalid_local_id)
                self.assertTrue(report.null_local_id)
            finally:
                conn.close()

    def test_w01_crash_after_apply_ui_retry_same_command(self):
        import inventory_writer_support as iws

        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=1)
            finally:
                conn.close()
            calls = []
            transport = transport_applied(calls)

            def crash(_cid):
                raise RuntimeError("crash after APPLY before local compra")

            iws.after_remote_apply_hook = crash
            try:
                ok, msg, compra_id = registrar_compra_desde_ui(
                    ComprasRepository(env.db),
                    proveedor_id=1,
                    productos=[
                        {"producto_id": 1, "cantidad": 2, "precio_unitario": 10}
                    ],
                    numero_factura="FAC-1E4B-CRASH",
                    inventory_mode="authoritative",
                    inventory_transport=transport,
                )
            finally:
                iws.after_remote_apply_hook = None
            self.assertFalse(ok)
            self.assertIsNone(compra_id)
            first_cid = None
            conn = env.connect()
            try:
                row = conn.execute(
                    "SELECT command_id FROM inventory_commands"
                ).fetchone()
                self.assertIsNotNone(row)
                first_cid = row[0]
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM compras").fetchone()[0], 0
                )
            finally:
                conn.close()

            repo2 = ComprasRepository(env.db)
            ok2, msg2, compra2 = registrar_compra_desde_ui(
                repo2,
                proveedor_id=1,
                productos=[
                    {"producto_id": 1, "cantidad": 2, "precio_unitario": 10}
                ],
                numero_factura="FAC-1E4B-CRASH",
                inventory_mode="authoritative",
                inventory_transport=transport_applied(),
            )
            self.assertTrue(ok2, msg2)
            self.assertEqual(repo2.last_inventory_command_id, first_cid)
            conn = env.connect()
            try:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM compras").fetchone()[0], 1
                )
                n_cmd = conn.execute(
                    "SELECT COUNT(*) FROM inventory_commands"
                ).fetchone()[0]
                self.assertEqual(n_cmd, 1)
                self.assertEqual(len(calls), 1)
            finally:
                conn.close()

    def test_stale_epoch_cannot_overwrite_newer_authoritative(self):
        from inventory_cutover import (
            STATUS_AUTHORITATIVE,
            STATUS_CUTOVER_IN_PROGRESS,
            StaleCutoverStateError,
            activate_authority,
            freeze_inventory_writes,
            load_postgres_cutover_state,
        )

        with official_temp_db() as env:
            conn = env.connect()
            try:
                freeze_inventory_writes(conn, admin_conn=self.admin)
                activate_authority(conn, admin_conn=self.admin)
                remote = load_postgres_cutover_state(self.admin, ensure_schema=False)
                self.assertEqual(remote.status, STATUS_AUTHORITATIVE)
                high_epoch = int(remote.epoch)
                force_postgres_status(
                    self.admin, STATUS_AUTHORITATIVE, epoch=max(high_epoch, 5)
                )
                conn.execute(
                    "UPDATE inventory_cutover_state SET status = ?, epoch = 0 WHERE id = 1",
                    (STATUS_CUTOVER_IN_PROGRESS,),
                )
                conn.commit()
                with self.assertRaises(StaleCutoverStateError):
                    activate_authority(conn, admin_conn=self.admin)
                after = load_postgres_cutover_state(self.admin, ensure_schema=False)
                self.assertEqual(after.status, STATUS_AUTHORITATIVE)
                self.assertGreaterEqual(int(after.epoch), 5)
            finally:
                conn.close()

    def test_concurrent_cutover_cas(self):
        from inventory_cutover import (
            STATUS_CUTOVER_IN_PROGRESS,
            StaleCutoverStateError,
            freeze_inventory_writes,
            load_postgres_cutover_state,
        )

        for _round in range(5):
            reset_lab_balances(self.admin)
            results = []
            barrier = threading.Barrier(2)
            with official_temp_db() as env:
                pin_env_db(env)
                conn_setup = env.connect()
                try:
                    conn_setup.commit()
                finally:
                    conn_setup.close()

                def contest(label):
                    sqlite = None
                    admin = None
                    try:
                        sqlite = env.connect()
                        admin = connect()
                        barrier.wait(10)
                        freeze_inventory_writes(
                            sqlite, admin_conn=admin, device_id=label
                        )
                        results.append(("ok", label))
                    except StaleCutoverStateError:
                        results.append(("stale", label))
                    except Exception as exc:
                        results.append(("err", str(exc)))
                    finally:
                        for item in (sqlite, admin):
                            if item is None:
                                continue
                            try:
                                item.close()
                            except Exception:
                                pass

                t1 = threading.Thread(target=contest, args=("a",), daemon=True)
                t2 = threading.Thread(target=contest, args=("b",), daemon=True)
                t1.start()
                t2.start()
                t1.join(20)
                t2.join(20)
            kinds = [item[0] for item in results]
            self.assertEqual(len(results), 2, results)
            self.assertEqual(kinds.count("ok"), 1, results)
            self.assertEqual(kinds.count("stale"), 1, results)
            remote = load_postgres_cutover_state(self.admin, ensure_schema=False)
            self.assertEqual(remote.status, STATUS_CUTOVER_IN_PROGRESS)

    def test_seed_exact_decimal_from_postgres_numeric(self):
        from inventory_cutover import (
            _postgres_legacy_scaled,
        )

        lid = str(uuid.uuid4())
        with official_temp_db() as env:
            conn = env.connect()
            try:
                with self.admin.cursor() as cur:
                    cur.execute(
                        "INSERT INTO productos (local_id, nombre, stock) "
                        "VALUES (%s, %s, %s::numeric)",
                        (lid, "exact", "9007199254740.993"),
                    )
                self.admin.commit()
                scaled = _postgres_legacy_scaled(self.admin)
                self.assertEqual(scaled[lid], 9007199254740993)
            finally:
                conn.close()

    def test_pg_stat_activity_failure_blocks_cutover(self):
        from inventory_cutover import (
            STATUS_AUTHORITATIVE,
            InventoryCutoverError,
            list_in_flight_inventory,
            load_postgres_cutover_state,
            run_cutover,
        )

        class BoomAdmin:
            def __init__(self, real):
                self._real = real

            def cursor(self):
                return BoomCursor(self._real.cursor())

            def rollback(self):
                return self._real.rollback()

            def commit(self):
                return self._real.commit()

            def __getattr__(self, name):
                return getattr(self._real, name)

        class BoomCursor:
            def __init__(self, real):
                self._real = real

            def execute(self, sql, *args, **kwargs):
                if "pg_stat_activity" in str(sql):
                    raise RuntimeError("permission denied for pg_stat_activity")
                return self._real.execute(sql, *args, **kwargs)

            def __enter__(self):
                self._real.__enter__()
                return self

            def __exit__(self, *exc):
                return self._real.__exit__(*exc)

            def __getattr__(self, name):
                return getattr(self._real, name)

        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=4)
                lid = conn.execute(
                    "SELECT local_id FROM productos WHERE id = 1"
                ).fetchone()[0]
                insert_producto(self.admin, local_id=lid, stock=4)
                with self.assertRaises(InventoryCutoverError) as ctx:
                    list_in_flight_inventory(conn, BoomAdmin(self.admin))
                self.assertIn("pg_stat_activity", str(ctx.exception))
            finally:
                conn.close()

        def exploding(sqlite_conn, admin_conn=None):
            raise InventoryCutoverError(
                "pg_stat_activity no consultable; NO SEED / NO ACTIVATE"
            )

        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=4)
                lid = conn.execute(
                    "SELECT local_id FROM productos WHERE id = 1"
                ).fetchone()[0]
                insert_producto(self.admin, local_id=lid, stock=4)
                with patch(
                    "inventory_cutover.list_in_flight_inventory", exploding
                ):
                    result = run_cutover(
                        conn,
                        admin_conn=self.admin,
                        app_factory=app_factory(),
                        require_app_dsn=False,
                    )
                self.assertTrue(result.aborted)
                remote = load_postgres_cutover_state(self.admin, ensure_schema=False)
                self.assertNotEqual(remote.status, STATUS_AUTHORITATIVE)
            finally:
                conn.close()

    def test_restart_identity_recovery_representative_writers(self):
        from inventory_cutover import ACT_KIND_PURCHASE_CREATE, begin_or_resume_open_act

        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=20)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = ventas_service(env)
            ok, msg, venta = svc.registrar_venta(
                items=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 1000}],
                inventory_mode="authoritative",
                inventory_transport=transport_applied(),
            )
            self.assertTrue(ok, msg)
            cid_pos = svc.last_inventory_command_id
            conn = env.connect()
            try:
                conn.execute("DELETE FROM inventory_open_acts")
                conn.commit()
            finally:
                conn.close()
            svc2 = ventas_service(env)
            ok2, msg2, venta2 = svc2.registrar_venta(
                items=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 1000}],
                inventory_mode="authoritative",
                inventory_command_id=cid_pos,
                inventory_transport=transport_applied(),
            )
            self.assertTrue(ok2, msg2)
            self.assertEqual(svc2.last_inventory_command_id, cid_pos)

            repo = ComprasRepository(env.db)
            okc, msgc, _cid = registrar_compra_desde_ui(
                repo,
                proveedor_id=1,
                productos=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 10}],
                numero_factura="FAC-RESTART",
                inventory_mode="authoritative",
                inventory_transport=transport_applied(),
            )
            self.assertTrue(okc, msgc)
            first_purchase_cmd = repo.last_inventory_command_id
            conn = env.connect()
            try:
                n_open = conn.execute(
                    "SELECT COUNT(*) FROM inventory_open_acts "
                    "WHERE act_kind = ?",
                    (ACT_KIND_PURCHASE_CREATE,),
                ).fetchone()[0]
            finally:
                conn.close()
            repo3 = ComprasRepository(env.db)
            okc2, msgc2, _ = registrar_compra_desde_ui(
                repo3,
                proveedor_id=1,
                productos=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 10}],
                numero_factura="FAC-RESTART",
                inventory_mode="authoritative",
                inventory_transport=transport_applied(),
            )
            if n_open:
                self.assertEqual(repo3.last_inventory_command_id, first_purchase_cmd)
            else:
                self.assertTrue(okc2, msgc2)

            inv = InventarioRepository(env.db)
            ok_adj, msg_adj = inv.ajustar_stock_directo(
                1,
                9,
                "1e4b",
                1,
                inventory_mode="authoritative",
                inventory_transport=transport_applied(),
                inventory_stock_base_scaled=20000,
            )
            self.assertTrue(ok_adj, msg_adj)
            adj_cid = inv.last_inventory_command_id
            inv2 = InventarioRepository(env.db)
            ok_adj2, msg_adj2 = inv2.ajustar_stock_directo(
                1,
                9,
                "1e4b",
                1,
                inventory_mode="authoritative",
                inventory_transport=transport_applied(),
                inventory_stock_base_scaled=20000,
            )
            self.assertTrue(ok_adj2, msg_adj2)
            self.assertEqual(inv2.last_inventory_command_id, adj_cid)

    def test_w01_w03_w13_w16_freeze_primitive(self):
        from inventory_cutover import freeze_inventory_writes

        factory = app_factory()
        with official_temp_db() as env:
            pin_env_db(env)
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=20)
                insert_usuario(conn)
                conn.commit()
                freeze_inventory_writes(conn, admin_conn=self.admin)
            finally:
                conn.close()
            ok_v, msg_v, _venta = ventas_service(env).registrar_venta(
                items=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 1000}],
                inventory_connection_factory=factory,
            )
            self.assertFalse(ok_v)
            self.assertIn("congelado", msg_v.lower() + " " + msg_v)
            ok_c, msg_c, _ = ComprasRepository(env.db).crear_compra(
                1,
                [{"producto_id": 1, "cantidad": 1, "precio_unitario": 10}],
                inventory_connection_factory=factory,
            )
            self.assertFalse(ok_c)
            ok_a, msg_a = InventarioRepository(env.db).ajustar_stock_directo(
                1, 1, "x", 1, inventory_connection_factory=factory
            )
            self.assertFalse(ok_a)
            handler = lan_create_sale(
                env,
                [{"producto_id": 1, "cantidad": 1}],
                inventory_connection_factory=factory,
            )
            self.assertGreaterEqual(handler.status, 400)


if __name__ == "__main__":
    unittest.main()
