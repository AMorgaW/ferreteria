from __future__ import annotations

import sqlite3
import unittest

from migration_runner import Migration, MigrationError, MigrationRunner, default_runner
from tests.fase0.harness import official_temp_db


class MigrationRunnerTest(unittest.TestCase):
    def test_fresh_db_apply_and_rerun(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                first = default_runner().run(conn, dry_run=False)
                self.assertEqual(
                    [item.status for item in first],
                    [
                        "APPLIED", "APPLIED", "APPLIED",
                        "APPLIED", "APPLIED", "APPLIED",
                    ],
                )
                cols = {row["name"] for row in conn.execute("PRAGMA table_info(compras)")}
                self.assertIn("documento_tipo_normalizado", cols)
                self.assertIn("numero_factura_normalizada", cols)
                index = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='index' "
                    "AND name='idx_compras_proveedor_factura_norm'"
                ).fetchone()
                self.assertIsNotNone(index)
                second = default_runner().run(conn, dry_run=False)
                self.assertEqual(
                    [item.status for item in second],
                    [
                        "SKIPPED_APPLIED", "SKIPPED_APPLIED",
                        "SKIPPED_APPLIED", "SKIPPED_APPLIED",
                        "SKIPPED_APPLIED", "SKIPPED_APPLIED",
                    ],
                )
            finally:
                conn.close()

    def test_dry_run_does_not_mutate(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                before = conn.total_changes
                plan = default_runner().run(conn, dry_run=True)
                self.assertTrue(all(item.status == "PENDING" for item in plan))
                self.assertEqual(conn.total_changes, before)
                self.assertIsNone(
                    conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE name='schema_migrations'"
                    ).fetchone()
                )
                cols = {row["name"] for row in conn.execute("PRAGMA table_info(compras)")}
                self.assertNotIn("documento_tipo_normalizado", cols)
            finally:
                conn.close()

    def test_legacy_fixture_missing_columns_is_upgraded(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(
                "CREATE TABLE compras (id INTEGER PRIMARY KEY, proveedor_id INTEGER, numero_factura TEXT)"
            )
            conn.execute(
                "CREATE TABLE productos (id INTEGER PRIMARY KEY, local_id TEXT UNIQUE)"
            )
            conn.execute(
                "INSERT INTO compras (proveedor_id, numero_factura) VALUES (1, ' A-1 ')"
            )
            conn.commit()
            default_runner().run(conn, dry_run=False)
            row = conn.execute("SELECT * FROM compras").fetchone()
            self.assertEqual(row["numero_factura"], " A-1 ")
            self.assertIsNone(row["documento_tipo_normalizado"])
            self.assertIsNone(row["numero_factura_normalizada"])
        finally:
            conn.close()

    def test_partial_failure_rolls_back_only_failed_migration(self):
        conn = sqlite3.connect(":memory:")
        try:
            def good(db):
                db.execute("CREATE TABLE good_table (id INTEGER)")

            def bad(db):
                db.execute("CREATE TABLE must_rollback (id INTEGER)")
                raise RuntimeError("boom")

            runner = MigrationRunner((
                Migration("001", "good", "good-v1", good),
                Migration("002", "bad", "bad-v1", bad),
            ))
            with self.assertRaisesRegex(MigrationError, "002/bad"):
                runner.run(conn, dry_run=False)
            self.assertIsNotNone(
                conn.execute("SELECT 1 FROM sqlite_master WHERE name='good_table'").fetchone()
            )
            self.assertIsNone(
                conn.execute("SELECT 1 FROM sqlite_master WHERE name='must_rollback'").fetchone()
            )
            versions = [row[0] for row in conn.execute("SELECT version FROM schema_migrations")]
            self.assertEqual(versions, ["001"])
        finally:
            conn.close()

    def test_applied_checksum_change_is_rejected(self):
        conn = sqlite3.connect(":memory:")
        try:
            original = Migration("001", "one", "v1", lambda db: db.execute("CREATE TABLE x(id)"))
            MigrationRunner((original,)).run(conn, dry_run=False)
            changed = Migration("001", "one", "v2", lambda db: None)
            with self.assertRaisesRegex(MigrationError, "checksum"):
                MigrationRunner((changed,)).run(conn, dry_run=False)
        finally:
            conn.close()

    def test_non_sqlite_connection_is_rejected_explicitly(self):
        class FakePostgres:
            __module__ = "psycopg2.extensions"

        with self.assertRaisesRegex(MigrationError, "solo admite SQLite"):
            default_runner().plan(FakePostgres())

    def test_missing_base_bootstrap_is_not_recorded_as_applied(self):
        conn = sqlite3.connect(":memory:")
        try:
            with self.assertRaisesRegex(MigrationError, "schema_bootstrap"):
                default_runner().run(conn, dry_run=False)
            versions = list(conn.execute("SELECT version FROM schema_migrations"))
            self.assertEqual(versions, [])
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
