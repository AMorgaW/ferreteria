# -*- coding: utf-8 -*-
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QWidget

import local_first_db
import main
from local_sync import SupabaseSyncService


BASE_DIR = Path(__file__).resolve().parents[2]


class _FixtureDB:
    def __init__(self, path):
        self.path = str(path)

    def conectar(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn


class LocalFirstResponsivenessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "responsiveness.db"
        shutil.copy2(BASE_DIR / "ferreteria.db", cls.db_path)
        local_first_db.ensure_local_first_schema(str(cls.db_path))

    @classmethod
    def tearDownClass(cls):
        QThreadPool.globalInstance().waitForDone(5000)
        cls.temp_dir.cleanup()

    def _drain_workers(self):
        QThreadPool.globalInstance().waitForDone(5000)
        self.app.processEvents()

    def test_01_startup_does_not_call_remote_gate_or_pre_ui_pull(self):
        shown = threading.Event()

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
                    "nombre_completo": "Operador local", "rol": "EMPLEADO"
                })()
                return True, "ok", user

        class FakeWindow:
            def __init__(self, **_kwargs):
                self.status_label = QLabel()

            def show(self):
                shown.set()

        with mock.patch.object(main, "DatabaseManager", return_value=object()), \
             mock.patch.object(main, "AuthManager", FakeAuth), \
             mock.patch.object(main, "LoginDialog", FakeLogin), \
             mock.patch.object(main, "SistemaFerreteriaApp", FakeWindow), \
             mock.patch.object(main, "_gate_supabase", side_effect=AssertionError("remote gate")) as gate, \
             mock.patch.object(main, "_pull_inicial_desde_nube", side_effect=AssertionError("pre-ui pull")) as pull:
            main.show_login_and_run(
                reuse_app=True,
                server_manager=object(),
                modo_emergencia=None,
            )

        self.assertTrue(shown.is_set())
        gate.assert_not_called()
        pull.assert_not_called()

    def test_02_legacy_gate_is_now_local_and_non_blocking(self):
        with mock.patch.object(
            SupabaseSyncService,
            "validar_arranque",
            side_effect=lambda: time.sleep(0.3),
        ) as remote:
            started = time.perf_counter()
            result = main._gate_supabase()
            elapsed = time.perf_counter() - started
        self.assertFalse(result)
        self.assertLess(elapsed, 0.08)
        remote.assert_not_called()

    def test_03_slow_initial_pull_is_scheduled_off_gui_thread(self):
        called_from = []

        class SlowService:
            def pull_from_remote(self):
                called_from.append(threading.get_ident())
                time.sleep(0.25)
                return {"ok": True, "rows": 0, "watermark": "2026-01-01"}

            def set_pull_watermark(self, _watermark):
                pass

        with mock.patch.object(main, "load_config", return_value={"cloud_sync_enabled": True}), \
             mock.patch.dict(os.environ, {
                 "DB_MODE": "local", "SUPABASE_URI": "synthetic://slow"
             }), \
             mock.patch("local_sync.get_service", return_value=SlowService()):
            gui_thread = threading.get_ident()
            started = time.perf_counter()
            worker = main._pull_inicial_desde_nube(False)
            elapsed = time.perf_counter() - started
            self.assertIsNotNone(worker)
            self.assertLess(elapsed, 0.10)
            self._drain_workers()
        self.assertTrue(called_from)
        self.assertNotEqual(called_from[0], gui_thread)

    def test_04_sync_worker_start_is_immediate_with_slow_remote(self):
        entered = threading.Event()
        release = threading.Event()

        class SlowService(SupabaseSyncService):
            def sync_once(self, limit=50):
                entered.set()
                release.wait(2)
                return {"processed": 0, "synced": 0, "failed": 0}

        service = SlowService(db_path=str(self.db_path), database_url="synthetic", interval=60)
        started = time.perf_counter()
        self.assertTrue(service.start_background())
        elapsed = time.perf_counter() - started
        self.assertTrue(entered.wait(1))
        self.assertLess(elapsed, 0.10)
        release.set()
        self.assertTrue(service.stop(timeout=2))

    def test_05_reconnect_and_backoff_run_outside_gui_thread(self):
        called_from = []
        entered = threading.Event()

        class FailingService(SupabaseSyncService):
            def sync_once(self, limit=50):
                called_from.append(threading.get_ident())
                entered.set()
                return {"processed": 1, "synced": 0, "failed": 1}

        service = FailingService(db_path=str(self.db_path), database_url="synthetic", interval=1)
        gui_thread = threading.get_ident()
        service.start_background()
        self.assertTrue(entered.wait(1))
        self.assertNotEqual(called_from[0], gui_thread)
        self.assertTrue(service.stop(timeout=2))

    def test_06_sqlite_remains_readable_while_remote_connect_waits(self):
        entered = threading.Event()
        release = threading.Event()

        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT INTO sync_queue "
                "(entity_type, entity_id, table_name, operation, payload, status) "
                "VALUES ('producto', 'fixture', 'productos', 'update', '{}', 'pending')"
            )
            conn.commit()
        finally:
            conn.close()

        class WaitingService(SupabaseSyncService):
            def _remote_connect(self):
                entered.set()
                release.wait(2)
                raise RuntimeError("synthetic offline")

        service = WaitingService(db_path=str(self.db_path), database_url="synthetic")
        worker = threading.Thread(target=service.sync_once, name="synthetic-reconnect")
        worker.start()
        self.assertTrue(entered.wait(1))
        local = sqlite3.connect(self.db_path, timeout=0.2)
        try:
            count = local.execute("SELECT COUNT(*) FROM productos").fetchone()[0]
        finally:
            local.close()
        release.set()
        worker.join(2)
        self.assertGreaterEqual(count, 0)
        self.assertFalse(worker.is_alive())

    def test_07_sqlite_connection_guard_rejects_cross_thread_use(self):
        conn = local_first_db.connect(str(self.db_path))
        errors = []

        def misuse():
            try:
                conn.execute("SELECT 1").fetchone()
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=misuse)
        worker.start()
        worker.join(1)
        conn.close()
        self.assertTrue(errors)
        self.assertIsInstance(errors[0], sqlite3.ProgrammingError)

    def test_08_schema_bootstrap_is_not_repeated_per_sync_cycle(self):
        second_path = Path(self.temp_dir.name) / "schema-once.db"
        shutil.copy2(BASE_DIR / "ferreteria.db", second_path)
        original = local_first_db._ensure_local_first_schema_uncached
        with mock.patch.object(
            local_first_db,
            "_ensure_local_first_schema_uncached",
            wraps=original,
        ) as bootstrap:
            local_first_db.ensure_local_first_schema(str(second_path))
            local_first_db.ensure_local_first_schema(str(second_path))
        self.assertEqual(bootstrap.call_count, 1)

    def test_09_worker_shutdown_and_restart_do_not_leak_threads(self):
        entered = threading.Event()

        class IdleService(SupabaseSyncService):
            def sync_once(self, limit=50):
                entered.set()
                return {"processed": 0, "synced": 0, "failed": 0}

        service = IdleService(db_path=str(self.db_path), database_url="synthetic", interval=60)
        for _ in range(3):
            entered.clear()
            self.assertTrue(service.start_background())
            self.assertTrue(entered.wait(1))
            self.assertTrue(service.stop(timeout=2))
        self.assertFalse(any(
            thread.is_alive() and thread.name == "supabase-sync"
            for thread in threading.enumerate()
        ))

    def test_10_productos_opens_from_local_data_without_network(self):
        from ui.productos_ui import ProductosUI

        class Products:
            db = _FixtureDB(self.db_path)

            def cache_disponible(self):
                return False

            def buscar_productos(self, *_args, **_kwargs):
                return []

        class Providers:
            def listar_proveedores(self, **_kwargs):
                return []

        with mock.patch("psycopg2.connect", side_effect=AssertionError("network")) as network:
            parent = QWidget()
            widget = ProductosUI(parent, Products(), object(), Providers())
            self._drain_workers()
        self.assertIsNotNone(widget.table)
        network.assert_not_called()
        widget.deleteLater()

    def test_11_barcode_regularization_still_opens_locally(self):
        from ui.barcode_regularization_ui import BarcodeRegularizationUI

        with mock.patch("psycopg2.connect", side_effect=AssertionError("network")) as network:
            parent = QWidget()
            widget = BarcodeRegularizationUI(parent, _FixtureDB(self.db_path), object())
            self._drain_workers()
        self.assertIsNotNone(widget.table)
        network.assert_not_called()
        widget.deleteLater()

    def test_12_inventory_import_still_opens_locally(self):
        from ui.inventory_import_ui import InventoryImportUI

        with mock.patch("psycopg2.connect", side_effect=AssertionError("network")) as network:
            parent = QWidget()
            widget = InventoryImportUI(parent, _FixtureDB(self.db_path), None, object())
        self.assertIsNotNone(widget.table)
        network.assert_not_called()
        widget.deleteLater()

    def test_13_compras_navigation_uses_local_repository_only(self):
        from ui.compras_ui import ComprasUI

        compras = mock.MagicMock()
        compras.obtener_estadisticas_compras.return_value = {
            "total_compras": 0,
            "total_monto": 0,
            "promedio_compra": 0,
            "total_proveedores": 0,
        }
        compras.listar_compras_recientes.return_value = []
        parent = QWidget()
        with mock.patch("psycopg2.connect", side_effect=AssertionError("network")) as network:
            widget = ComprasUI(
                parent,
                _FixtureDB(self.db_path),
                compras,
                mock.MagicMock(),
                mock.MagicMock(),
                mock.MagicMock(),
                deudas_service=None,
                abonos_repo=None,
            )
        self.assertIsNotNone(widget.tree)
        network.assert_not_called()
        widget.deleteLater()

    def test_14_ventas_navigation_uses_local_cache_only(self):
        from ui.ventas_ui_modern import VentasUIModern

        productos = mock.MagicMock()
        productos.cache_disponible.return_value = True
        productos.buscar_productos_cache.return_value = []
        productos.obtener_categorias.return_value = []
        auth = mock.MagicMock()
        auth.tiene_permiso.return_value = True
        parent = QWidget()
        with mock.patch("psycopg2.connect", side_effect=AssertionError("network")) as network, \
             mock.patch("ui.ventas_ui_modern.QMessageBox.information"):
            widget = VentasUIModern(
                parent,
                mock.MagicMock(),
                productos,
                mock.MagicMock(),
                auth,
                _FixtureDB(self.db_path),
            )
        self.assertIsNotNone(widget.productos_container)
        network.assert_not_called()
        widget.deleteLater()


if __name__ == "__main__":
    unittest.main(verbosity=2)
