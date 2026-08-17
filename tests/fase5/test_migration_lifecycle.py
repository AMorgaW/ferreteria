# -*- coding: utf-8 -*-
"""Lifecycle de migraciones SQLite. Temp dirs only. Nunca ferreteria.db."""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backup_manager import BackupError, read_manifest
from migration_runner import Migration, MigrationRunner, default_runner
from schema_lifecycle import (
    SchemaLifecycleError,
    SchemaLifecycleResult,
    catalog_latest_version,
    ensure_sqlite_schema_current,
    inspect_sqlite_schema,
    schema_is_latest,
)
from tests.fase0.harness import REPO_FERRETERIA_DB, official_temp_db
from tests.fase5.helpers import (
    EXPECTED_LATEST_TABLES,
    FileDb,
    commercial_sha256,
    make_legacy_station_db,
    table_exists,
)


class RecordingRunner:
    def __init__(self, inner=None):
        self.inner = inner or default_runner()
        self.run_calls = []

    @property
    def migrations(self):
        return self.inner.migrations

    def plan(self, conn):
        return self.inner.plan(conn)

    def run(self, conn, *, dry_run=True):
        self.run_calls.append(dry_run)
        return self.inner.run(conn, dry_run=dry_run)


class MigrationLifecycleTest(unittest.TestCase):
    def setUp(self):
        self._sha = commercial_sha256()
        self._mtime = (
            REPO_FERRETERIA_DB.stat().st_mtime if REPO_FERRETERIA_DB.exists() else None
        )
        self._tmp = tempfile.TemporaryDirectory(prefix="ferrepro-fase5b-")
        self.folder = Path(self._tmp.name)
        self.db_path = self.folder / "station.db"
        self.assertNotEqual(self.db_path.resolve(), REPO_FERRETERIA_DB.resolve())

    def tearDown(self):
        self._tmp.cleanup()
        self.assertEqual(commercial_sha256(), self._sha)
        if REPO_FERRETERIA_DB.exists():
            self.assertEqual(REPO_FERRETERIA_DB.stat().st_mtime, self._mtime)

    def _legacy(self):
        return make_legacy_station_db(self.db_path)

    def test_01_legacy_detects_pending_migrations(self):
        path = self._legacy()
        plan = inspect_sqlite_schema(str(path))
        pending = [item.version for item in plan if item.status == "PENDING"]
        self.assertIn("20260815_001", pending)
        self.assertIn("20260815_004", pending)
        self.assertIn("20260816_008", pending)
        self.assertIn("20260816_009", pending)
        self.assertIn("20260816_010", pending)
        self.assertFalse(schema_is_latest(str(path)))

    def test_02_04_05_backup_then_migrate_dry_run_false_latest(self):
        path = self._legacy()
        runner = RecordingRunner()
        result = ensure_sqlite_schema_current(str(path), runner=runner)
        self.assertIsInstance(result, SchemaLifecycleResult)
        self.assertFalse(result.already_latest)
        self.assertIsNotNone(result.backup)
        self.assertTrue(os.path.isfile(result.backup.db_path))
        self.assertTrue(os.path.isfile(result.backup.manifest_path))
        manifest = read_manifest(result.backup.db_path)
        self.assertEqual(manifest["motivo"], "pre-migration")
        self.assertTrue(manifest["sqlite_backup_api"])
        self.assertEqual(len(manifest["sha256"]), 64)
        self.assertEqual(runner.run_calls, [False])
        self.assertTrue(schema_is_latest(str(path)))
        self.assertEqual(result.latest_version, catalog_latest_version())
        self.assertEqual(result.latest_version, "20260816_010")

    def test_03_backup_failure_prevents_migration(self):
        path = self._legacy()

        def boom(**_kwargs):
            raise BackupError("disco lleno")

        with self.assertRaisesRegex(SchemaLifecycleError, "BACKUP_FAILED"):
            ensure_sqlite_schema_current(str(path), backup_fn=boom)
        conn = sqlite3.connect(str(path))
        try:
            self.assertFalse(table_exists(conn, "schema_migrations"))
            self.assertFalse(table_exists(conn, "inventory_import_batches"))
            self.assertFalse(table_exists(conn, "reversal_documents"))
            self.assertFalse(table_exists(conn, "operational_balance_legacy_payments"))
        finally:
            conn.close()

    def test_06_to_10_required_schema_tables_exist(self):
        path = self._legacy()
        ensure_sqlite_schema_current(str(path))
        conn = sqlite3.connect(str(path))
        try:
            for name in EXPECTED_LATEST_TABLES:
                self.assertTrue(table_exists(conn, name), name)
            versions = [
                row[0]
                for row in conn.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                )
            ]
            self.assertIn("20260815_004", versions)
            self.assertIn("20260816_008", versions)
            self.assertIn("20260816_009", versions)
            self.assertIn("20260816_010", versions)
            cols = {row[1] for row in conn.execute("PRAGMA table_info(cierres_caja)")}
            self.assertIn("station_id", cols)
        finally:
            conn.close()

    def test_16_21_rerun_and_restart_idempotent(self):
        path = self._legacy()
        first = ensure_sqlite_schema_current(str(path))
        self.assertFalse(first.already_latest)
        conn = sqlite3.connect(str(path))
        try:
            migrations = conn.execute(
                "SELECT COUNT(*) FROM schema_migrations"
            ).fetchone()[0]
            cash = conn.execute("SELECT COUNT(*) FROM cash_movements").fetchone()[0]
        finally:
            conn.close()
        second = ensure_sqlite_schema_current(str(path))
        self.assertTrue(second.already_latest)
        self.assertIsNone(second.backup)
        conn = sqlite3.connect(str(path))
        try:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0],
                migrations,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM cash_movements").fetchone()[0],
                cash,
            )
        finally:
            conn.close()
        third = ensure_sqlite_schema_current(str(path))
        self.assertTrue(third.already_latest)
        self.assertTrue(schema_is_latest(str(path)))

    def test_17_fresh_temp_db_reaches_latest(self):
        with official_temp_db() as env:
            self.assertTrue(schema_is_latest(str(env.db_path)))
            conn = env.connect()
            try:
                for name in EXPECTED_LATEST_TABLES:
                    self.assertTrue(table_exists(conn, name), name)
            finally:
                conn.close()

    def test_18_deployment_readiness_no_schema_blocker(self):
        from services.deployment_readiness import evaluate_readiness

        path = self._legacy()
        ensure_sqlite_schema_current(str(path))
        report = evaluate_readiness(
            db_path=str(path),
            production=True,
            backup_dir=str(self.folder / "backups"),
        )
        self.assertNotIn("SCHEMA_MIGRATIONS_PENDING", report.blockers)
        self.assertIn("FINANCIAL_WRITER_FENCE_REQUIRED", report.blockers)
        self.assertFalse(report.ready)

    def test_19_corrupt_db_fails_closed(self):
        self.db_path.write_bytes(b"this is not sqlite")
        with self.assertRaisesRegex(SchemaLifecycleError, "SQLITE_NOT_SQLITE"):
            ensure_sqlite_schema_current(str(self.db_path))

    def test_20_migration_failure_is_explicit(self):
        path = self._legacy()

        def fail(_conn):
            raise RuntimeError("boom sintetico")

        runner = MigrationRunner(
            (Migration("20990101_999", "synthetic_fail", "v1", fail),)
        )
        with self.assertRaisesRegex(SchemaLifecycleError, "MIGRATION_FAILED"):
            ensure_sqlite_schema_current(str(path), runner=runner)
        conn = sqlite3.connect(str(path))
        try:
            applied = [
                row[0]
                for row in conn.execute("SELECT version FROM schema_migrations")
            ]
        finally:
            conn.close()
        self.assertNotIn("20990101_999", applied)

    def test_missing_db_does_not_create(self):
        missing = self.folder / "no-such" / "ferreteria.db"
        with self.assertRaisesRegex(SchemaLifecycleError, "SQLITE_NOT_FOUND"):
            ensure_sqlite_schema_current(str(missing))
        self.assertFalse(missing.exists())
        self.assertFalse(missing.parent.exists())

    def test_already_latest_skips_backup(self):
        path = self._legacy()
        ensure_sqlite_schema_current(str(path))
        called = []

        def must_not_backup(**_kwargs):
            called.append(True)
            raise BackupError("no debio respaldar")

        result = ensure_sqlite_schema_current(str(path), backup_fn=must_not_backup)
        self.assertTrue(result.already_latest)
        self.assertEqual(called, [])

    def test_import_require_schema_passes_after_lifecycle(self):
        from repositories.inventory_import_repository import InventoryImportRepository

        path = self._legacy()
        ensure_sqlite_schema_current(str(path))
        repo = InventoryImportRepository(FileDb(path))
        self.assertIsNone(repo.find_batch_by_sha("deadbeef" * 8))

    def test_returns_layer_does_not_fail_for_missing_schema(self):
        from returns_schema import KIND_CUSTOMER_RETURN, ORIGINAL_TIPO_VENTA
        from services.returns_service import ReturnsService
        from tests.fase1e.helpers import AuthPermitido
        from tests.fase5.helpers import insert_legacy_sale

        path = self._legacy()
        venta_id = insert_legacy_sale(path, total=100, monto_pagado=0)
        ensure_sqlite_schema_current(str(path))
        svc = ReturnsService(FileDb(path), auth=AuthPermitido())
        ok, msg, rid = svc.guardar_borrador(
            kind=KIND_CUSTOMER_RETURN,
            original_tipo=ORIGINAL_TIPO_VENTA,
            original_id=venta_id,
        )
        self.assertNotIn("no such table", str(msg).lower())
        self.assertFalse(
            isinstance(msg, Exception) and "reversal_documents" in str(msg)
        )
        if not ok:
            self.assertNotIn("no such table", str(msg).lower())
        else:
            self.assertIsNotNone(rid)
            conn = sqlite3.connect(str(path))
            try:
                row = conn.execute(
                    "SELECT id FROM reversal_documents WHERE id=?", (rid,)
                ).fetchone()
            finally:
                conn.close()
            self.assertIsNotNone(row)


class FreshBootstrapCashSurvivalTest(unittest.TestCase):
    def setUp(self):
        self._sha = commercial_sha256()

    def tearDown(self):
        self.assertEqual(commercial_sha256(), self._sha)

    def test_22_caja_admin_survives_lifecycle(self):
        from decimal import Decimal

        from tests.fase1e.helpers import insert_usuario
        from tests.fase5.helpers import caja_service, phase5_env, seed_pos_product

        with phase5_env() as env:
            conn = env.connect()
            try:
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            seed_pos_product(env, stock=20, precio_venta=1000)
            svc = caja_service(env, rol="ADMIN")
            ok, msg = svc.abrir_caja(Decimal("20000"))
            self.assertTrue(ok, msg)
            self.assertIsNotNone(svc.obtener_caja_abierta())

    def test_23_caja_empleado_sale_one_drawer_in(self):
        from decimal import Decimal

        from cash_schema import EFFECT_DRAWER_IN
        from tests.fase1e.helpers import insert_usuario
        from tests.fase5.helpers import (
            complete_sale_as,
            count_movements,
            open_caja,
            phase5_env,
            seed_pos_product,
        )

        with phase5_env() as env:
            conn = env.connect()
            try:
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            seed_pos_product(env, stock=20, precio_venta=1000)
            open_caja(env, Decimal("0"))
            complete_sale_as(env, rol="VENDEDOR")
            self.assertEqual(count_movements(env, source_kind="venta"), 1)
            conn = env.connect()
            try:
                row = conn.execute(
                    "SELECT cash_effect_kind FROM cash_movements WHERE source_kind='venta'"
                ).fetchone()
            finally:
                conn.close()
            self.assertEqual(row[0], EFFECT_DRAWER_IN)


if __name__ == "__main__":
    unittest.main(verbosity=2)
