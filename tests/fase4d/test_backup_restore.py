# -*- coding: utf-8 -*-
"""Backup consistente, manifest/checksum, restore con safety backup."""
from __future__ import annotations

import os
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase4c.helpers import BUSINESS_TABLES, business_fingerprint
from tests.fase4d.helpers import (
    assert_commercial_untouched,
    commercial_db_mtime,
    credit_purchase,
    credit_sale,
    pay_customer,
    pay_supplier,
    phase4d_env,
    seed_cliente,
    seed_ops,
    station_context,
)


class BackupRestoreTest(unittest.TestCase):
    def setUp(self):
        self._mtime = commercial_db_mtime()

    def tearDown(self):
        assert_commercial_untouched(self._mtime)

    def _seed(self, env):
        seed_ops(env)
        cid = seed_cliente(env)
        venta = credit_sale(env, total=70, cliente_id=cid)
        compra_id = credit_purchase(env, total=40)
        with station_context(current="W01", writer="W01"):
            pay_customer(env, venta.id, 10)
            pay_supplier(env, compra_id, 5)
        return business_fingerprint(env)

    def test_06_07_backup_consistent_with_manifest(self):
        import backup_manager

        with phase4d_env() as env:
            self._seed(env)
            dest_dir = str(Path(env.db_path).parent / "backups")
            result = backup_manager.crear_backup_result(
                motivo="test",
                db_path=str(env.db_path),
                dest_dir=dest_dir,
            )
            self.assertIsNotNone(result)
            self.assertTrue(Path(result.db_path).is_file())
            self.assertTrue(Path(result.manifest_path).is_file())
            self.assertEqual(len(result.sha256), 64)
            self.assertTrue(result.schema_version)
            manifest = backup_manager.read_manifest(result.db_path)
            self.assertEqual(manifest["sha256"], result.sha256)
            self.assertTrue(manifest["sqlite_backup_api"])
            self.assertNotIn("C:\\Users\\alex", str(manifest))
            conn = sqlite3.connect(result.db_path)
            try:
                check = conn.execute("PRAGMA integrity_check").fetchone()[0]
                self.assertEqual(str(check).lower(), "ok")
            finally:
                conn.close()

    def test_08_restore_preserves_core_tables(self):
        import backup_manager

        with phase4d_env() as env:
            fingerprint = self._seed(env)
            dest_dir = str(Path(env.db_path).parent / "backups")
            result = backup_manager.crear_backup_result(
                motivo="preserve",
                db_path=str(env.db_path),
                dest_dir=dest_dir,
            )
            conn = env.connect()
            try:
                conn.execute("DELETE FROM abonos_ventas")
                conn.commit()
            finally:
                conn.close()
            self.assertNotEqual(business_fingerprint(env), fingerprint)
            ok, msg = backup_manager.restaurar_backup(
                result.db_path,
                db_path=str(env.db_path),
                dest_dir=dest_dir,
            )
            self.assertTrue(ok, msg)
            self.assertEqual(business_fingerprint(env), fingerprint)
            conn = env.connect()
            try:
                present = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
            finally:
                conn.close()
            for table in BUSINESS_TABLES:
                if table == "inventory_balances" and table not in present:
                    continue
                self.assertIn(table, present)

    def test_09_restore_creates_safety_backup(self):
        import backup_manager

        with phase4d_env() as env:
            self._seed(env)
            dest_dir = Path(env.db_path).parent / "backups"
            result = backup_manager.crear_backup_result(
                motivo="orig",
                db_path=str(env.db_path),
                dest_dir=str(dest_dir),
            )
            conn = env.connect()
            try:
                conn.execute("UPDATE abonos_ventas SET observaciones='DESTINO-UNICO'")
                conn.commit()
            finally:
                conn.close()
            before = list(dest_dir.glob("backup_*.db"))
            ok, msg = backup_manager.restaurar_backup(
                result.db_path,
                db_path=str(env.db_path),
                dest_dir=str(dest_dir),
            )
            self.assertTrue(ok, msg)
            after = list(dest_dir.glob("backup_*.db"))
            self.assertGreater(len(after), len(before))
            conn = env.connect()
            try:
                row = conn.execute(
                    "SELECT observaciones FROM abonos_ventas LIMIT 1"
                ).fetchone()
                self.assertNotEqual(row[0], "DESTINO-UNICO")
            finally:
                conn.close()

    def test_10_corrupted_backup_rejected(self):
        import backup_manager

        with phase4d_env() as env:
            fingerprint = self._seed(env)
            dest_dir = Path(env.db_path).parent / "backups"
            dest_dir.mkdir(exist_ok=True)
            bad = dest_dir / "backup_corrupt.db"
            bad.write_bytes(b"not a sqlite database")
            ok, msg = backup_manager.restaurar_backup(
                str(bad),
                db_path=str(env.db_path),
                dest_dir=str(dest_dir),
            )
            self.assertFalse(ok)
            self.assertTrue(msg)
            self.assertEqual(business_fingerprint(env), fingerprint)

    def test_checksum_mismatch_rejected(self):
        import backup_manager

        with phase4d_env() as env:
            fingerprint = self._seed(env)
            dest_dir = str(Path(env.db_path).parent / "backups")
            result = backup_manager.crear_backup_result(
                motivo="tamper",
                db_path=str(env.db_path),
                dest_dir=dest_dir,
            )
            payload = backup_manager.read_manifest(result.db_path)
            payload["sha256"] = "0" * 64
            Path(result.manifest_path).write_text(
                __import__("json").dumps(payload), encoding="utf-8"
            )
            ok, msg = backup_manager.restaurar_backup(
                result.db_path,
                db_path=str(env.db_path),
                dest_dir=dest_dir,
            )
            self.assertFalse(ok)
            self.assertIn("checksum", msg.lower())
            self.assertEqual(business_fingerprint(env), fingerprint)

    def test_backup_file_tampered_after_manifest_is_rejected(self):
        import backup_manager

        with phase4d_env() as env:
            fingerprint = self._seed(env)
            dest_dir = str(Path(env.db_path).parent / "backups")
            result = backup_manager.crear_backup_result(
                motivo="tamper-db", db_path=str(env.db_path), dest_dir=dest_dir
            )
            conn = sqlite3.connect(result.db_path)
            try:
                conn.execute("CREATE TABLE tamper_after_manifest (id INTEGER)")
                conn.commit()
            finally:
                conn.close()
            ok, msg = backup_manager.restaurar_backup(
                result.db_path, db_path=str(env.db_path), dest_dir=dest_dir
            )
            self.assertFalse(ok)
            self.assertIn("checksum", msg.lower())
            self.assertEqual(business_fingerprint(env), fingerprint)

    def test_missing_or_invalid_manifest_fails_closed(self):
        import backup_manager

        with phase4d_env() as env:
            fingerprint = self._seed(env)
            dest_dir = str(Path(env.db_path).parent / "backups")
            result = backup_manager.crear_backup_result(
                motivo="manifest", db_path=str(env.db_path), dest_dir=dest_dir
            )
            Path(result.manifest_path).unlink()
            ok, msg = backup_manager.restaurar_backup(
                result.db_path, db_path=str(env.db_path), dest_dir=dest_dir
            )
            self.assertFalse(ok)
            self.assertIn("manifest requerido", msg.lower())
            self.assertEqual(business_fingerprint(env), fingerprint)

            Path(result.manifest_path).write_text("[]", encoding="utf-8")
            ok, msg = backup_manager.restaurar_backup(
                result.db_path, db_path=str(env.db_path), dest_dir=dest_dir
            )
            self.assertFalse(ok)
            self.assertIn("manifest inválido", msg.lower())
            self.assertEqual(business_fingerprint(env), fingerprint)

    def test_restore_failure_recovers_destination_from_safety_backup(self):
        import backup_manager

        with phase4d_env() as env:
            self._seed(env)
            dest_dir = str(Path(env.db_path).parent / "backups")
            result = backup_manager.crear_backup_result(
                motivo="recovery", db_path=str(env.db_path), dest_dir=dest_dir
            )
            conn = env.connect()
            try:
                conn.execute("UPDATE abonos_ventas SET observaciones='DESTINO-SEGURO'")
                conn.commit()
            finally:
                conn.close()
            destination_fingerprint = business_fingerprint(env)

            original = backup_manager._sqlite_backup
            calls = {"count": 0}

            def fail_primary_restore(source, destination):
                calls["count"] += 1
                if calls["count"] == 2:
                    raise sqlite3.OperationalError("fallo simulado post-safety")
                return original(source, destination)

            with mock.patch.object(
                backup_manager, "_sqlite_backup", side_effect=fail_primary_restore
            ):
                ok, msg = backup_manager.restaurar_backup(
                    result.db_path, db_path=str(env.db_path), dest_dir=dest_dir
                )
            self.assertFalse(ok)
            self.assertIn("RECUPERADO", msg)
            self.assertIn("safety backup", msg)
            self.assertEqual(business_fingerprint(env), destination_fingerprint)
