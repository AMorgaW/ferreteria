# -*- coding: utf-8 -*-
"""1E.4C PostgreSQL real: freeze-wins y writer-wins en W06/W08/W09/W10/W12/W17/W18."""
from __future__ import annotations

import sys
import threading
import unittest
import uuid
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from models import MovimientoInventario
from repositories.inventario_repository import InventarioRepository
from repositories.productos_repo import ProductosRepository
from services.movimientos_service import MovimientosService
from tests.fase0.harness import official_temp_db
from tests.fase1d.pg_harness import connect
from tests.fase1e.helpers import AuthPermitido, insert_usuario, seed_producto, stock_of
from tests.fase1e1.helpers import ventas_service
from tests.fase1e2.helpers import make_producto
from tests.fase1e4c.helpers import (
    app_factory,
    pin_env_db,
    prepare_pg,
    reset_lab_balances,
    require_pg,
)


def _credit_sale(env, factory, *, cantidad=5):
    svc = ventas_service(env)
    ok, msg, venta = svc.registrar_venta(
        items=[{"producto_id": 1, "cantidad": cantidad, "precio_unitario": 1000}],
        metodo_pago="CREDITO",
        inventory_connection_factory=factory,
    )
    if not ok:
        raise AssertionError(msg)
    conn = env.connect()
    try:
        detalle_id = conn.execute(
            "SELECT id FROM detalle_ventas WHERE venta_id = ?",
            (venta.id,),
        ).fetchone()[0]
    finally:
        conn.close()
    return venta, detalle_id


class Fase1E4CPostgresTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_pg()
        admin = connect()
        try:
            from inventory_cutover import ensure_postgres_cutover_schema

            ensure_postgres_cutover_schema(admin)
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
        try:
            self.admin.close()
        except Exception:
            pass

    def _assert_stock(self, env, expected, extra=None):
        conn = env.connect()
        try:
            self.assertEqual(int(stock_of(conn)), int(expected))
            if extra is not None:
                extra(conn)
        finally:
            conn.close()

    def _freeze_wins(self, *, setup, action, expected_stock, extra=None, rounds=5):
        from inventory_cutover import (
            STATUS_CUTOVER_IN_PROGRESS,
            freeze_inventory_writes,
            load_postgres_cutover_state,
            set_after_legacy_allow_hook,
            set_after_postgres_freeze_hook,
        )

        factory = app_factory()
        for _round in range(rounds):
            reset_lab_balances(self.admin)
            started = threading.Event()
            freeze_published = threading.Event()
            errors = []

            def hook(_state):
                started.set()
                self.assertTrue(
                    freeze_published.wait(15), "freeze PG no publicó a tiempo"
                )

            def after_pg_freeze():
                freeze_published.set()

            with official_temp_db() as env:
                pin_env_db(env)
                conn = env.connect()
                try:
                    seed_producto(conn, env, stock=50)
                    insert_usuario(conn)
                    conn.commit()
                finally:
                    conn.close()
                ctx = setup(env, factory)
                set_after_legacy_allow_hook(hook)
                set_after_postgres_freeze_hook(after_pg_freeze)

                def freeze_station():
                    sqlite = None
                    admin = None
                    try:
                        self.assertTrue(started.wait(15))
                        sqlite = env.connect()
                        admin = connect()
                        freeze_inventory_writes(
                            sqlite, admin_conn=admin, device_id="freeze-1e4c"
                        )
                    except Exception as exc:
                        errors.append(exc)
                    finally:
                        freeze_published.set()
                        for item in (sqlite, admin):
                            if item is None:
                                continue
                            try:
                                item.close()
                            except Exception:
                                pass

                t_freeze = threading.Thread(target=freeze_station, daemon=True)
                t_freeze.start()
                result = action(env, factory, ctx)
                t_freeze.join(20)
                self.assertFalse(errors, errors)
                ok = result[0] if isinstance(result, tuple) else result
                msg = result[1] if isinstance(result, tuple) and len(result) > 1 else ""
                self.assertFalse(ok, msg)
                remote = load_postgres_cutover_state(self.admin, ensure_schema=False)
                self.assertEqual(remote.status, STATUS_CUTOVER_IN_PROGRESS)
                self._assert_stock(env, expected_stock, extra=extra)
            set_after_legacy_allow_hook(None)
            set_after_postgres_freeze_hook(None)

    def _writer_wins(self, *, setup, action, expected_stock, rounds=5):
        from inventory_cutover import (
            freeze_inventory_writes,
            set_after_legacy_share_hook,
        )

        factory = app_factory()
        for _round in range(rounds):
            reset_lab_balances(self.admin)
            holding = threading.Event()
            proceed = threading.Event()
            freeze_errors = []
            freeze_done = threading.Event()
            action_result = {}

            def after_share(_status, _epoch):
                holding.set()
                self.assertTrue(proceed.wait(15))

            with official_temp_db() as env:
                pin_env_db(env)
                conn = env.connect()
                try:
                    seed_producto(conn, env, stock=50)
                    insert_usuario(conn)
                    conn.commit()
                finally:
                    conn.close()
                ctx = setup(env, factory)
                set_after_legacy_share_hook(after_share)

                def freeze_station():
                    sqlite = None
                    admin = None
                    try:
                        self.assertTrue(holding.wait(15))
                        sqlite = env.connect()
                        admin = connect()
                        freeze_inventory_writes(
                            sqlite, admin_conn=admin, device_id="wait-writer-1e4c"
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

                def do_action():
                    try:
                        result = action(env, factory, ctx)
                        action_result["result"] = result
                    except Exception as exc:
                        action_result["result"] = (False, str(exc))

                t_action = threading.Thread(target=do_action, daemon=True)
                t_action.start()
                self.assertTrue(
                    holding.wait(20),
                    f"writer no tomó el fence central: {action_result}",
                )
                t_freeze = threading.Thread(target=freeze_station, daemon=True)
                t_freeze.start()
                self.assertFalse(freeze_done.wait(0.3), "freeze no debe ganar el fence")
                proceed.set()
                t_action.join(20)
                t_freeze.join(20)
                result = action_result.get("result") or (False, "sin resultado")
                self.assertTrue(result[0], result[1] if len(result) > 1 else result)
                self.assertFalse(freeze_errors, freeze_errors)
                self._assert_stock(env, expected_stock)
            set_after_legacy_share_hook(None)

    def test_w06_started_before_freeze_cannot_commit(self):
        def setup(env, factory):
            venta, _detalle = _credit_sale(env, factory, cantidad=5)
            return venta

        def action(env, factory, venta):
            return ventas_service(env).agregar_productos_a_factura(
                venta.id,
                [{"producto_id": 1, "cantidad": 3, "precio_unitario": 1000}],
                inventory_connection_factory=factory,
            )

        self._freeze_wins(setup=setup, action=action, expected_stock=45)

    def test_w08_started_before_freeze_cannot_commit(self):
        def setup(_env, _factory):
            return None

        def action(env, factory, _ctx):
            repo = ProductosRepository(env.db)
            prod = make_producto(id=1, nombre="Stock edit", stock=40)
            return repo.actualizar_producto(
                prod, inventory_connection_factory=factory
            )

        self._freeze_wins(setup=setup, action=action, expected_stock=50)

    def test_w09_started_before_freeze_cannot_commit(self):
        def setup(_env, _factory):
            return None

        def action(env, factory, _ctx):
            repo = ProductosRepository(env.db)
            prod = make_producto(
                nombre=f"Alta {uuid.uuid4().hex[:8]}",
                stock=7,
            )
            return repo.crear_producto(
                prod, inventory_connection_factory=factory
            )

        def extra(conn):
            n = conn.execute("SELECT COUNT(*) FROM productos").fetchone()[0]
            self.assertEqual(n, 1)

        self._freeze_wins(
            setup=setup, action=action, expected_stock=50, extra=extra
        )

    def test_w10_started_before_freeze_cannot_commit(self):
        def setup(_env, _factory):
            return None

        def action(env, factory, _ctx):
            svc = MovimientosService(
                env.db, ProductosRepository(env.db), None, AuthPermitido()
            )
            return svc.registrar_movimiento(
                "ENTRADA_AJUSTE",
                1,
                5,
                inventory_connection_factory=factory,
            )

        self._freeze_wins(setup=setup, action=action, expected_stock=50)

    def test_w12_started_before_freeze_cannot_commit(self):
        def setup(_env, _factory):
            return None

        def action(env, factory, _ctx):
            repo = InventarioRepository(env.db)
            mov = MovimientoInventario(
                tipo_movimiento="SALIDA_AJUSTE",
                producto_id=1,
                cantidad=2,
                precio_unitario=0,
                usuario_id=1,
                fecha=datetime.now(),
                observaciones="1e4c",
            )
            return repo.registrar_movimiento(
                mov, inventory_connection_factory=factory
            )

        self._freeze_wins(setup=setup, action=action, expected_stock=50)

    def test_w17_started_before_freeze_cannot_commit(self):
        def setup(env, factory):
            return _credit_sale(env, factory, cantidad=5)

        def action(env, factory, ctx):
            venta, detalle_id = ctx
            return ventas_service(env).editar_linea_factura(
                venta.id,
                detalle_id,
                8,
                1000,
                inventory_connection_factory=factory,
            )

        self._freeze_wins(setup=setup, action=action, expected_stock=45)

    def test_w18_started_before_freeze_cannot_commit(self):
        def setup(env, factory):
            return _credit_sale(env, factory, cantidad=5)

        def action(env, factory, ctx):
            venta, detalle_id = ctx
            return ventas_service(env).eliminar_linea_factura(
                venta.id,
                detalle_id,
                inventory_connection_factory=factory,
            )

        self._freeze_wins(setup=setup, action=action, expected_stock=45)

    def test_writer_wins_fence_sample_w06(self):
        def setup(env, factory):
            venta, _detalle = _credit_sale(env, factory, cantidad=5)
            return venta

        def action(env, factory, venta):
            return ventas_service(env).agregar_productos_a_factura(
                venta.id,
                [{"producto_id": 1, "cantidad": 3, "precio_unitario": 1000}],
                inventory_connection_factory=factory,
            )

        self._writer_wins(setup=setup, action=action, expected_stock=42)

    def test_writer_wins_fence_sample_w08(self):
        def setup(_env, _factory):
            return None

        def action(env, factory, _ctx):
            repo = ProductosRepository(env.db)
            prod = make_producto(id=1, nombre="Writer wins", stock=40)
            return repo.actualizar_producto(
                prod, inventory_connection_factory=factory
            )

        self._writer_wins(setup=setup, action=action, expected_stock=40)

    def test_writer_wins_fence_sample_w10(self):
        def setup(_env, _factory):
            return None

        def action(env, factory, _ctx):
            svc = MovimientosService(
                env.db, ProductosRepository(env.db), None, AuthPermitido()
            )
            return svc.registrar_movimiento(
                "ENTRADA_AJUSTE",
                1,
                5,
                inventory_connection_factory=factory,
            )

        self._writer_wins(setup=setup, action=action, expected_stock=55)


if __name__ == "__main__":
    unittest.main()
