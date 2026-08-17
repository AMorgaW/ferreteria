# -*- coding: utf-8 -*-
"""Fase 5C: LAN writer fail-closed + auth rehash warning. SQLite temporal."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from local_first_config import DEFAULT_CONFIG, lan_auto_start_enabled, load_config
from local_server import LAN_SALES_WRITES_DISABLED, LocalFerreteriaAPI
from schema_lifecycle import schema_is_latest
from services.caja_service import CASH_ADMIN_DENIED
from tests.fase0.harness import REPO_FERRETERIA_DB
from tests.fase1e.helpers import FakeHTTPHandler, insert_usuario, stock_of
from tests.fase1e1.helpers import lan_create_sale
from tests.fase1e3.helpers import mark_authoritative
from tests.fase5.helpers import (
    assert_not_commercial_db,
    caja_service,
    commercial_sha256,
    count_movements,
    open_caja,
    phase5_env,
    pos_service_as,
    seed_pos_product,
)


def _payload(handler):
    raw = handler.wfile.getvalue().decode("utf-8")
    return json.loads(raw) if raw else {}


class LanDefaultAndAutostartTest(unittest.TestCase):
    def test_01_default_auto_start_server_is_false(self):
        self.assertFalse(DEFAULT_CONFIG["auto_start_server"])
        self.assertFalse(lan_auto_start_enabled({}))
        self.assertFalse(lan_auto_start_enabled({"auto_start_server": False}))
        self.assertFalse(lan_auto_start_enabled({"auto_start_server": "true"}))
        self.assertTrue(lan_auto_start_enabled({"auto_start_server": True}))

    def test_02_load_config_missing_key_stays_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "station.db"
            db_path.write_bytes(b"")
            cfg_dir = Path(tmp) / "config"
            cfg_dir.mkdir()
            (cfg_dir / "local_first_config.json").write_text(
                json.dumps({"app_mode": "admin"}), encoding="utf-8"
            )
            with mock.patch.dict(os.environ, {"LOCAL_DB_PATH": str(db_path)}):
                cfg = load_config()
            self.assertFalse(cfg["auto_start_server"])
            self.assertFalse(lan_auto_start_enabled(cfg))

    def test_02b_lan_does_not_autostart_unless_explicit(self):
        import main

        manager = mock.Mock()
        app = main.SistemaFerreteriaApp.__new__(main.SistemaFerreteriaApp)
        app.local_first_config = {"auto_start_server": False}
        app.local_server_manager = manager
        result = main.SistemaFerreteriaApp._verificar_servicios_local_first(app)
        manager.ensure_running.assert_not_called()
        manager.start.assert_not_called()
        self.assertTrue(result.get("disabled") or not result.get("server"))

    def test_11_local_first_startup_does_not_depend_on_lan(self):
        import main
        from PySide6.QtWidgets import QApplication, QDialog, QLabel

        QApplication.instance() or QApplication([])

        class FakeLogin:
            username = "local"
            password = "local"

            def exec(self):
                return QDialog.Accepted

        class FakeAuth:
            def __init__(self, _db):
                pass

            def login(self, _username, _password):
                user = type("User", (), {
                    "nombre_completo": "Operador local", "rol": "EMPLEADO",
                })()
                return True, "ok", user

        class FakeWindow:
            def __init__(self, **_kwargs):
                self.status_label = QLabel()

            def show(self):
                return None

        with mock.patch.object(
            main, "load_config",
            return_value={"auto_start_server": False, "db_mode": "local"},
        ), mock.patch.object(main, "LocalServerManager") as lsm, \
             mock.patch.object(main, "DatabaseManager", return_value=object()), \
             mock.patch.object(main, "AuthManager", FakeAuth), \
             mock.patch.object(main, "LoginDialog", FakeLogin), \
             mock.patch.object(main, "SistemaFerreteriaApp", FakeWindow):
            main.show_login_and_run(
                reuse_app=True, server_manager=None, modo_emergencia=None,
            )
        lsm.assert_not_called()


class LanWriterFailClosedTest(unittest.TestCase):
    def test_03_lan_sale_does_not_update_productos_stock(self):
        self.assertTrue(LAN_SALES_WRITES_DISABLED)
        with phase5_env() as env:
            assert_not_commercial_db(env)
            conn = env.connect()
            try:
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            seed_pos_product(env, stock=20, precio_venta=1000)
            conn = env.connect()
            try:
                before = stock_of(conn)
                ventas_before = conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0]
            finally:
                conn.close()
            handler = lan_create_sale(
                env, [{"producto_id": 1, "cantidad": 3, "descuento": 0}]
            )
            self.assertEqual(handler.status, 403)
            self.assertIn("LAN_SALES_DISABLED", _payload(handler).get("error", ""))
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), before)
                ventas_after = conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0]
                self.assertEqual(ventas_after, ventas_before)
            finally:
                conn.close()

    def test_05_post_cutover_lan_cannot_write_stock_as_authority(self):
        with phase5_env() as env:
            conn = env.connect()
            try:
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            seed_pos_product(env, stock=20, precio_venta=1000)
            conn = env.connect()
            try:
                mark_authoritative(conn)
                before = stock_of(conn)
            finally:
                conn.close()
            handler = lan_create_sale(
                env, [{"producto_id": 1, "cantidad": 1, "descuento": 0}],
                inventory_mode="authoritative",
            )
            self.assertNotEqual(handler.status, 201)
            self.assertEqual(handler.status, 403)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), before)
            finally:
                conn.close()
            auth_handler = FakeHTTPHandler(
                env.db_path,
                json.dumps({
                    "items": [{"producto_id": 1, "cantidad": 1, "descuento": 0}],
                    "metodo_pago": "EFECTIVO",
                }).encode("utf-8"),
            )
            LocalFerreteriaAPI._create_sale_authoritative(
                auth_handler,
                {"usuario_id": 1},
                data={"items": [], "metodo_pago": "EFECTIVO"},
                items=[{"producto_id": 1, "cantidad": 1}],
                inventory_command_id=None,
                inventory_gateway=None,
                inventory_transport=None,
                inventory_connection_factory=None,
            )
            self.assertEqual(auth_handler.status, 403)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), before)
            finally:
                conn.close()

    def test_10_readonly_lan_list_products_works(self):
        with phase5_env() as env:
            seed_pos_product(env, stock=7, precio_venta=1000)
            handler = FakeHTTPHandler(env.db_path, b"")
            LocalFerreteriaAPI.list_products(
                handler, {"search": [""], "limit": ["10"], "offset": ["0"]}
            )
            self.assertEqual(handler.status, 200)
            products = _payload(handler)["products"]
            self.assertTrue(products)
            self.assertEqual(int(products[0]["stock"]), 7)


class CanonicalPosTest(unittest.TestCase):
    def test_04_pre_cutover_modern_pos_still_works(self):
        with phase5_env() as env:
            conn = env.connect()
            try:
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            seed_pos_product(env, stock=20, precio_venta=1000)
            open_caja(env, Decimal("0"))
            svc = pos_service_as(env, rol="VENDEDOR")
            ok, msg, venta = svc.registrar_venta(
                items=[{"producto_id": 1, "cantidad": 2, "precio_unitario": 1000}],
                metodo_pago="EFECTIVO",
            )
            self.assertTrue(ok, msg)
            self.assertIsNotNone(venta)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 18)
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0], 1
                )
            finally:
                conn.close()
            self.assertEqual(count_movements(env, source_kind="venta"), 1)

    def test_09_decimal_remains_on_commercial_authority(self):
        from inventory_writer_support import commercial_quantity_to_scaled

        self.assertEqual(commercial_quantity_to_scaled(Decimal("1.5")), 1500)
        self.assertEqual(commercial_quantity_to_scaled("1.5"), 1500)
        self.assertEqual(commercial_quantity_to_scaled(1.5), 1500)
        self.assertEqual(
            commercial_quantity_to_scaled(Decimal(str(0.1))),
            100,
        )


class Fase5RegressionSmokesTest(unittest.TestCase):
    def test_12_fase5a_caja_admin_not_broken(self):
        with phase5_env() as env:
            conn = env.connect()
            try:
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            seed_pos_product(env, stock=5, precio_venta=1000)
            svc = caja_service(env, rol="ADMIN")
            ok, msg = svc.abrir_caja(Decimal("10000"))
            self.assertTrue(ok, msg)
            self.assertIsNotNone(svc.obtener_caja_abierta())

    def test_13_fase5a_caja_empleado_not_broken(self):
        with phase5_env() as env:
            conn = env.connect()
            try:
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            open_caja(env, Decimal("10000"))
            svc = caja_service(env, rol="EMPLEADO")
            ok, msg = svc.abrir_caja(Decimal("1"))
            self.assertFalse(ok)
            self.assertEqual(msg, CASH_ADMIN_DENIED)

    def test_14_fase5b_migrations_not_broken(self):
        with phase5_env() as env:
            self.assertTrue(schema_is_latest(str(env.db_path)))

    def test_18_commercial_db_untouched(self):
        before = commercial_sha256()
        mtime = REPO_FERRETERIA_DB.stat().st_mtime if REPO_FERRETERIA_DB.exists() else None
        with phase5_env() as env:
            assert_not_commercial_db(env)
            self.assertNotEqual(
                Path(env.db_path).resolve(), REPO_FERRETERIA_DB.resolve()
            )
        self.assertEqual(commercial_sha256(), before)
        if REPO_FERRETERIA_DB.exists():
            self.assertEqual(REPO_FERRETERIA_DB.stat().st_mtime, mtime)


class _CursorFail:
    def __init__(self, cur):
        self._cur = cur
        self.connection = cur.connection

    def execute(self, sql, params=()):
        if isinstance(sql, str) and "SET password_hash" in sql:
            raise sqlite3.OperationalError("simulated rehash failure")
        return self._cur.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self._cur, name)


class _RehashFailDb:
    def __init__(self, inner):
        self.inner = inner

    def conectar(self):
        conn = self.inner.conectar()
        return _ConnProxy(conn)


class _ConnProxy:
    def __init__(self, conn):
        self._conn = conn

    def cursor(self):
        return _CursorFail(self._conn.cursor())

    def __getattr__(self, name):
        return getattr(self._conn, name)
    def test_15_16_17_rehash_failure_keeps_login_and_safe_warning(self):
        from auth import AuthManager

        password = "correct-horse-battery-staple"
        legacy = hashlib.sha256(password.encode("utf-8")).hexdigest()
        with phase5_env() as env:
            conn = env.connect()
            try:
                conn.execute(
                    "INSERT INTO usuarios "
                    "(username, password_hash, nombre_completo, rol, activo) "
                    "VALUES (?, ?, ?, 'ADMIN', 1)",
                    ("rehash_user", legacy, "Rehash User"),
                )
                conn.commit()
            finally:
                conn.close()

            auth = AuthManager(_RehashFailDb(env.db))
            with self.assertLogs("auth", level="WARNING") as cm:
                ok, msg, user = auth.login("rehash_user", password)
            self.assertTrue(ok, msg)
            self.assertIsNotNone(user)
            self.assertEqual(user.username, "rehash_user")
            blob = "\n".join(cm.output)
            self.assertIn("rehash", blob.lower())
            self.assertIn("usuario_id=", blob)
            lowered = blob.lower()
            self.assertNotIn(password.lower(), lowered)
            self.assertNotIn(legacy.lower(), lowered)
            self.assertNotIn("password_hash", lowered)
            self.assertNotIn("postgresql", lowered)
            self.assertNotIn("sqlite://", lowered)
            conn = env.connect()
            try:
                stored = conn.execute(
                    "SELECT password_hash FROM usuarios WHERE username = ?",
                    ("rehash_user",),
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(stored, legacy)


if __name__ == "__main__":
    unittest.main(verbosity=2)
