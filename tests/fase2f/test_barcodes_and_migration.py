from __future__ import annotations

import sqlite3
import unittest

from barcode_schema import ensure_sqlite_barcode_package_role
from migration_runner import default_runner
from repositories.barcode_queue_repo import BarcodeQueueRepository
from repositories.product_barcodes_repo import (
    PACKAGE_ROLE_BASE_UNIT,
    PACKAGE_ROLE_FULL_PACKAGE,
    BarcodeConflictError,
    ProductBarcodesRepository,
)
from services.barcode_regularization_service import ContinuousRegularizationController
from tests.fase0.harness import official_temp_db
from tests.fase2f.helpers import create_product, phase2c_env


class BarcodeMetadataTest(unittest.TestCase):
    def test_15_duplicate_same_product_is_idempotent(self):
        with phase2c_env() as env:
            _pid, lid = create_product(env, "Mismo")
            repo = ProductBarcodesRepository(env.db)
            first = repo.assign_barcode(producto_local_id=lid, barcode="SAME")
            second = repo.assign_barcode(producto_local_id=lid, barcode="SAME")
            self.assertEqual(first.local_id, second.local_id)
            self.assertEqual(len(repo.list_for_product(lid)), 1)

    def test_16_duplicate_other_product_is_conflict(self):
        with phase2c_env() as env:
            _a, a = create_product(env, "Dueño")
            _b, b = create_product(env, "Otro")
            repo = ProductBarcodesRepository(env.db)
            repo.assign_barcode(producto_local_id=a, barcode="GLOBAL")
            with self.assertRaises(BarcodeConflictError):
                repo.assign_barcode(producto_local_id=b, barcode="GLOBAL")

    def test_17_secondary_and_explicit_primary_keep_one_primary(self):
        with phase2c_env() as env:
            _pid, lid = create_product(env, "Multi")
            repo = ProductBarcodesRepository(env.db)
            first = repo.assign_barcode(producto_local_id=lid, barcode="UNIT")
            second = repo.assign_barcode(producto_local_id=lid, barcode="BOX")
            self.assertTrue(first.is_primary); self.assertFalse(second.is_primary)
            repo.set_primary(second.local_id)
            self.assertEqual(sum(row.is_primary for row in repo.list_for_product(lid)), 1)
            self.assertTrue(repo.get_by_local_id(second.local_id).is_primary)

    def test_18_package_roles_share_product_and_stock(self):
        with phase2c_env() as env:
            pid, lid = create_product(env, "Bombillo")
            repo = ProductBarcodesRepository(env.db)
            unit = repo.assign_barcode(producto_local_id=lid, barcode="U", package_role=PACKAGE_ROLE_BASE_UNIT)
            box = repo.assign_barcode(producto_local_id=lid, barcode="C", package_role=PACKAGE_ROLE_FULL_PACKAGE)
            self.assertEqual((unit.package_role, box.package_role), ("BASE_UNIT", "FULL_PACKAGE"))
            self.assertEqual(repo.lookup_product("U")["id"], repo.lookup_product("C")["id"])
            conn = env.connect()
            try:
                self.assertEqual(conn.execute("SELECT stock FROM productos WHERE id=?", (pid,)).fetchone()[0], 0)
            finally:
                conn.close()

    def test_19_frp_is_only_generated_by_explicit_action(self):
        with phase2c_env() as env:
            _pid, lid = create_product(env, "FRP")
            repo = ProductBarcodesRepository(env.db)
            controller = ContinuousRegularizationController(BarcodeQueueRepository(env.db), repo)
            controller.refresh_queue(); controller.select(lid)
            self.assertEqual(repo.list_for_product(lid), [])
            candidate = controller.generate_frp_candidate(token_hex=lambda _n: "a1" * 8)
            self.assertEqual(candidate, "FRP-A1A1A1A1A1A1A1A1")
            self.assertEqual(repo.list_for_product(lid), [])

    def test_20_frp_confirmation_persists_with_readback(self):
        with phase2c_env() as env:
            _pid, lid = create_product(env, "FRP Confirm")
            repo = ProductBarcodesRepository(env.db)
            controller = ContinuousRegularizationController(BarcodeQueueRepository(env.db), repo)
            controller.refresh_queue(); controller.select(lid)
            candidate = controller.generate_frp_candidate(token_hex=lambda _n: "0f" * 8)
            result = controller.confirm_frp()
            self.assertTrue(result.success)
            self.assertEqual(repo.get_by_barcode(candidate).barcode, candidate)


class PackageRoleMigrationTest(unittest.TestCase):
    def test_21_migration_006_preserves_phase2c_rows_with_default(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                migrations = default_runner().migrations
                for migration in migrations[:-1]:
                    migration.apply(conn)
                lid = "00000000-0000-0000-0000-000000000021"
                conn.execute(
                    "INSERT INTO productos(local_id,nombre,precio_venta,stock) "
                    "VALUES(?, 'Previo 2C', 1000, 0)",
                    (lid,),
                )
                conn.execute("INSERT INTO product_barcodes(local_id,producto_local_id,barcode,is_primary) VALUES('b',?,'OLD-2C',1)", (lid,))
                conn.commit()
                ensure_sqlite_barcode_package_role(conn)
                ensure_sqlite_barcode_package_role(conn)
                conn.commit()
                row = conn.execute("SELECT barcode,package_role FROM product_barcodes WHERE local_id='b'").fetchone()
                self.assertEqual(tuple(row), ("OLD-2C", "BASE_UNIT"))
            finally:
                conn.close()

    def test_22_runner_006_is_checksum_idempotent(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                first = default_runner().run(conn, dry_run=False)
                second = default_runner().run(conn, dry_run=False)
                self.assertTrue(
                    all(item.status in ("APPLIED", "SKIPPED_APPLIED") for item in first)
                )
                self.assertTrue(all(item.status == "SKIPPED_APPLIED" for item in second))
                self.assertEqual(first[-1].checksum, second[-1].checksum)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
