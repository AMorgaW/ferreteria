# -*- coding: utf-8 -*-
"""Packaging, frozen resources, local-first offline smoke."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from inventory_coordinator import (
    CoordinatorError,
    REMOTE_COORDINATOR_MIGRATION_FILENAME,
    coordinator_sql_path,
)
from tests.fase4a.helpers import reportes_service
from tests.fase4c.helpers import docs
from tests.fase4d.helpers import (
    assert_commercial_untouched,
    commercial_db_mtime,
    credit_sale,
    cxc,
    phase4d_env,
    seed_cliente,
    seed_ops,
)
from tests.fase3d.helpers import open_caja


class PackagingFrozenOfflineTest(unittest.TestCase):
    def setUp(self):
        self._mtime = commercial_db_mtime()

    def tearDown(self):
        assert_commercial_untouched(self._mtime)

    def test_15_coordinator_sql_packaged(self):
        spec = (REPO_ROOT / "Ferreteria.spec").read_text(encoding="utf-8")
        self.assertIn("supabase_inventory_coordinator.sql", spec)
        self.assertIn("datas.append", spec)
        self.assertNotIn('("ferreteria.db"', spec)
        self.assertNotIn('(".env"', spec)
        self.assertNotIn('("docs/', spec)
        self.assertNotIn('("tests/', spec)
        self.assertIn("services.financial_writer_fence", spec)
        self.assertIn("services.deployment_readiness", spec)
        self.assertIn("services.operational_balance", spec)
        self.assertIn("services.document_service", spec)
        self.assertIn("services.inventory_reporting_adapter", spec)
        self.assertTrue((REPO_ROOT / REMOTE_COORDINATOR_MIGRATION_FILENAME).is_file())

    def test_16_no_absolute_developer_path(self):
        files = [
            REPO_ROOT / "inventory_coordinator.py",
            REPO_ROOT / "services" / "deployment_readiness.py",
            REPO_ROOT / "services" / "financial_writer_fence.py",
            REPO_ROOT / "backup_manager.py",
            REPO_ROOT / "local_first_config.py",
            REPO_ROOT / "launcher.py",
        ]
        for path in files:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(r"C:\Users\alex", text)
            self.assertNotIn("C:/Users/alex", text)

    def test_17_frozen_resource_resolver(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundled = Path(tmp) / REMOTE_COORDINATOR_MIGRATION_FILENAME
            bundled.write_text("-- bundled 4d\n", encoding="utf-8")
            with mock.patch("inventory_coordinator.sys") as fake_sys:
                fake_sys.frozen = True
                fake_sys._MEIPASS = tmp
                fake_sys.executable = str(Path(tmp) / "Ferreteria.exe")
                self.assertEqual(coordinator_sql_path().resolve(), bundled.resolve())

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("inventory_coordinator.sys") as fake_sys:
                fake_sys.frozen = True
                fake_sys._MEIPASS = tmp
                fake_sys.executable = str(Path(tmp) / "Ferreteria.exe")
                with self.assertRaises(CoordinatorError) as ctx:
                    coordinator_sql_path()
                self.assertIn("No se encontró", str(ctx.exception))
                self.assertNotIn(str(REPO_ROOT), str(ctx.exception))

    def test_18_startup_without_network(self):
        import main
        from local_sync import SupabaseSyncService

        with mock.patch.object(
            SupabaseSyncService,
            "validar_arranque",
            side_effect=AssertionError("remote"),
        ) as remote:
            result = main._gate_supabase()
        self.assertFalse(result)
        remote.assert_not_called()
        src = (REPO_ROOT / "main.py").read_text(encoding="utf-8")
        self.assertNotIn("restaurar_backup", src)

    def test_19_reporting_offline(self):
        with phase4d_env() as env:
            seed_ops(env)
            with mock.patch("socket.create_connection", side_effect=OSError("offline")):
                service = reportes_service(env)
                rows = service.reporte_inventario_actual()
            self.assertIsInstance(rows, list)

    def test_20_document_render_offline(self):
        from services.document_service import render_operational_text

        with phase4d_env() as env:
            seed_ops(env)
            venta = credit_sale(env, total=25)
            with mock.patch("socket.create_connection", side_effect=OSError("offline")):
                doc = docs(env).load_sale(venta.id)
                text = " ".join(render_operational_text(doc).split())
            self.assertTrue(text)
            self.assertIn("NO FISCAL", text)

    def test_21_balance_read_offline(self):
        with phase4d_env() as env:
            seed_ops(env)
            cid = seed_cliente(env)
            venta = credit_sale(env, total=33, cliente_id=cid)
            with mock.patch("socket.create_connection", side_effect=OSError("offline")):
                snap = cxc(env).obtener_saldo_venta(venta.id)
            self.assertEqual(str(snap["saldo_pendiente"]), "33.00")

    def test_22_cash_read_offline(self):
        with phase4d_env() as env:
            seed_ops(env)
            with mock.patch("socket.create_connection", side_effect=OSError("offline")):
                svc = open_caja(env)
                opened = svc.obtener_caja_abierta()
            self.assertIsNotNone(opened)
            self.assertEqual(opened["station_id"], "W01")
