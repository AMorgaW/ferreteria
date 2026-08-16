# -*- coding: utf-8 -*-
"""Migraciones legacy→latest y preflight READY/NOT_READY."""
from __future__ import annotations

import sqlite3
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from migration_runner import default_runner
from services.deployment_readiness import evaluate_readiness
from tests.fase0.harness import official_temp_db
from tests.fase4d.helpers import (
    assert_commercial_untouched,
    commercial_db_mtime,
    phase4d_env,
    station_context,
)


class MigrationReadinessTest(unittest.TestCase):
    def setUp(self):
        self._mtime = commercial_db_mtime()

    def tearDown(self):
        assert_commercial_untouched(self._mtime)

    def test_11_legacy_migrates_to_009_010(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(
                "CREATE TABLE compras (id INTEGER PRIMARY KEY, proveedor_id INTEGER, numero_factura TEXT, total REAL)"
            )
            conn.execute(
                "CREATE TABLE productos (id INTEGER PRIMARY KEY, local_id TEXT UNIQUE, stock REAL)"
            )
            conn.execute(
                "CREATE TABLE abonos_ventas (id INTEGER PRIMARY KEY, id_venta INTEGER, monto_abono REAL)"
            )
            conn.execute(
                "CREATE TABLE abonos_compras (id INTEGER PRIMARY KEY, id_compra INTEGER, monto_abono REAL)"
            )
            conn.execute(
                "INSERT INTO compras (proveedor_id, numero_factura, total) VALUES (1, 'L-1', 10)"
            )
            conn.commit()
            first = default_runner().run(conn, dry_run=False)
            versions = {item.version: item.status for item in first}
            self.assertEqual(versions.get("20260816_009"), "APPLIED")
            self.assertEqual(versions.get("20260816_010"), "APPLIED")
            cols_v = {row["name"] for row in conn.execute("PRAGMA table_info(abonos_ventas)")}
            cols_c = {row["name"] for row in conn.execute("PRAGMA table_info(abonos_compras)")}
            self.assertIn("local_id", cols_v)
            self.assertIn("local_id", cols_c)
            cash = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='cash_movements'"
            ).fetchone()
            self.assertIsNotNone(cash)
            row = conn.execute("SELECT numero_factura FROM compras").fetchone()
            self.assertEqual(row["numero_factura"], "L-1")
        finally:
            conn.close()

    def test_12_migrations_rerunnable(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                first = default_runner().run(conn, dry_run=False)
                second = default_runner().run(conn, dry_run=False)
                self.assertTrue(all(item.status == "APPLIED" for item in first))
                self.assertTrue(all(item.status == "SKIPPED_APPLIED" for item in second))
            finally:
                conn.close()

    def test_backup_then_migrate_then_read(self):
        import backup_manager

        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE TABLE productos (id INTEGER PRIMARY KEY, nombre TEXT)")
            conn.execute("INSERT INTO productos (nombre) VALUES ('legacy')")
            conn.commit()
        finally:
            conn.close()

        with phase4d_env() as env:
            dest_dir = str(Path(env.db_path).parent / "backups")
            result = backup_manager.crear_backup_result(
                motivo="pre-migrate",
                db_path=str(env.db_path),
                dest_dir=dest_dir,
            )
            conn = sqlite3.connect(result.db_path)
            try:
                plan = default_runner().run(conn, dry_run=False)
                self.assertTrue(
                    all(item.status in ("APPLIED", "SKIPPED_APPLIED") for item in plan)
                )
                versions = [
                    row[0]
                    for row in conn.execute(
                        "SELECT version FROM schema_migrations ORDER BY version"
                    )
                ]
                self.assertIn("20260816_009", versions)
                self.assertIn("20260816_010", versions)
            finally:
                conn.close()

    def test_04_missing_production_fence_fails_readiness(self):
        with phase4d_env() as env:
            with station_context(
                current="W01",
                writer=None,
                expected=["W01", "W02"],
                profile="production",
            ):
                report = evaluate_readiness(
                    db_path=str(env.db_path),
                    production=True,
                )
            self.assertFalse(report.ready)
            self.assertEqual(report.status, "NOT_READY")
            self.assertIn("FINANCIAL_WRITER_FENCE_REQUIRED", report.blockers)
            self.assertNotIn("REAL_INVENTORY_APPLIED", report.text())

    def test_05_single_configured_writer_readiness_pass(self):
        with phase4d_env() as env:
            with station_context(
                current="W01",
                writer="W01",
                expected=["W01"],
                profile="production",
            ):
                report = evaluate_readiness(
                    db_path=str(env.db_path),
                    production=True,
                    backup_dir=str(Path(env.db_path).parent / "backups"),
                )
            self.assertTrue(report.ready, report.text())
            self.assertEqual(report.status, "READY")
            self.assertEqual(report.blockers, [])
            self.assertEqual(
                report.inventory_commercial_status, "PENDING FINAL DEPLOYMENT"
            )
            self.assertEqual(report.cash_commercial_status, "NOT EXECUTED")

    def test_13_14_readiness_offline_and_reports_blocker(self):
        with phase4d_env() as env:
            with station_context(current="W01", writer="W01", profile="dev"):
                ok = evaluate_readiness(
                    db_path=str(env.db_path),
                    production=False,
                    backup_dir=str(Path(env.db_path).parent / "backups"),
                )
            self.assertTrue(ok.ready, ok.text())
            with station_context(
                current="LOCAL",
                writer=None,
                expected=["W01", "W02"],
                profile="production",
            ):
                bad = evaluate_readiness(
                    db_path=str(env.db_path),
                    production=True,
                )
            self.assertFalse(bad.ready)
            self.assertGreaterEqual(len(bad.blockers), 1)
            self.assertTrue(
                any(
                    item in bad.blockers
                    for item in (
                        "FINANCIAL_WRITER_FENCE_REQUIRED",
                        "STATION_ID_INVALID",
                    )
                )
            )

    def test_23_secrets_not_emitted(self):
        with phase4d_env() as env:
            config = {
                "db_mode": "local",
                "financial_writer_station_id": "W01",
                "expected_station_ids": ["W01"],
                "deployment_profile": "production",
                "supabase_service_role": "super-secret-role-key",
                "password": "hunter2",
                "database_url": "postgres://user:secret@host/db",
            }
            with station_context(current="W01", writer="W01", profile="production"):
                report = evaluate_readiness(
                    db_path=str(env.db_path),
                    config=config,
                    production=True,
                    backup_dir=str(Path(env.db_path).parent / "backups"),
                )
            text = report.text() + str(report.as_dict())
            self.assertNotIn("super-secret-role-key", text)
            self.assertNotIn("hunter2", text)
            self.assertNotIn("postgres://user:secret", text)
            self.assertNotIn("REAL_INVENTORY_APPLIED", text)

    def test_documented_preflight_cli_runs_from_repo_root(self):
        with phase4d_env() as env:
            cli_env = os.environ.copy()
            cli_env.update(
                {
                    "LOCAL_DB_PATH": str(env.db_path),
                    "FERREPRO_STATION_ID": "W01",
                    "FINANCIAL_WRITER_STATION_ID": "W01",
                    "FERREPRO_EXPECTED_STATION_IDS": "W01,W02",
                    "FERREPRO_DEPLOYMENT_PROFILE": "production",
                }
            )
            completed = subprocess.run(
                [sys.executable, "services/deployment_readiness.py", "--production"],
                cwd=REPO_ROOT,
                env=cli_env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            output = completed.stdout + completed.stderr
            self.assertEqual(completed.returncode, 0, output)
            self.assertTrue(output.startswith("READY"), output)
            self.assertNotIn("Traceback", output)

    def test_preflight_missing_db_does_not_create_it(self):
        with phase4d_env() as env:
            missing = Path(env.db_path).parent / "missing" / "ferreteria.db"
            with station_context(current="W01", writer="W01", profile="production"):
                report = evaluate_readiness(
                    db_path=str(missing),
                    production=True,
                    backup_dir=str(Path(env.db_path).parent / "backups"),
                )
            self.assertFalse(report.ready)
            self.assertIn("SQLITE_NOT_FOUND", report.blockers)
            self.assertFalse(missing.exists())
            self.assertFalse(missing.parent.exists())
