from __future__ import annotations

import sqlite3
import unittest

from repositories.product_barcodes_repo import (
    BarcodeConflictError,
    ProductBarcodesRepository,
)
from tests.fase2c.helpers import create_product, phase2c_env


class BarcodeDataModelTest(unittest.TestCase):
    def test_14_one_product_one_barcode(self):
        with phase2c_env() as env:
            _pid, lid = create_product(env, "Uno")
            repo = ProductBarcodesRepository(env.db)
            record = repo.assign_barcode(producto_local_id=lid, barcode="7700000000001")
            self.assertEqual(record.producto_local_id, lid)
            self.assertEqual(len(repo.list_for_product(lid)), 1)

    def test_15_one_product_multiple_barcodes_same_stock(self):
        with phase2c_env() as env:
            pid, lid = create_product(env, "Múltiple")
            repo = ProductBarcodesRepository(env.db)
            repo.assign_barcode(producto_local_id=lid, barcode="A")
            repo.assign_barcode(producto_local_id=lid, barcode="B")
            self.assertEqual(len(repo.list_for_product(lid)), 2)
            conn = env.connect()
            try:
                self.assertEqual(conn.execute("SELECT stock FROM productos WHERE id=?", (pid,)).fetchone()[0], 0)
            finally:
                conn.close()

    def test_16_same_barcode_cannot_belong_to_two_products(self):
        with phase2c_env() as env:
            _a, lid_a = create_product(env, "A")
            _b, lid_b = create_product(env, "B")
            repo = ProductBarcodesRepository(env.db)
            repo.assign_barcode(producto_local_id=lid_a, barcode="DUP")
            with self.assertRaisesRegex(BarcodeConflictError, "Código ya asignado a: A"):
                repo.assign_barcode(producto_local_id=lid_b, barcode="DUP")

    def test_17_inactive_history_is_not_recyclable(self):
        with phase2c_env() as env:
            _a, lid_a = create_product(env, "Histórico A")
            _b, lid_b = create_product(env, "Histórico B")
            repo = ProductBarcodesRepository(env.db)
            rec = repo.assign_barcode(producto_local_id=lid_a, barcode="HISTORY")
            conn = env.connect()
            try:
                conn.execute("UPDATE product_barcodes SET active=0 WHERE local_id=?", (rec.local_id,))
                conn.commit()
            finally:
                conn.close()
            with self.assertRaises(BarcodeConflictError):
                repo.assign_barcode(producto_local_id=lid_b, barcode="HISTORY")

    def test_18_only_one_active_primary_per_product(self):
        with phase2c_env() as env:
            _pid, lid = create_product(env, "Primary")
            repo = ProductBarcodesRepository(env.db)
            first = repo.assign_barcode(producto_local_id=lid, barcode="P1", is_primary=True)
            second = repo.assign_barcode(producto_local_id=lid, barcode="P2", is_primary=True)
            records = repo.list_for_product(lid)
            self.assertEqual(sum(item.is_primary for item in records), 1)
            self.assertTrue(repo.get_by_local_id(second.local_id).is_primary)
            self.assertFalse(repo.get_by_local_id(first.local_id).is_primary)

    def test_19_lookup_resolves_product(self):
        with phase2c_env() as env:
            pid, lid = create_product(env, "Lookup")
            repo = ProductBarcodesRepository(env.db)
            repo.assign_barcode(producto_local_id=lid, barcode="LOOK")
            self.assertEqual(repo.lookup_product("LOOK")["id"], pid)

    def test_20_secondary_barcode_resolves_same_product(self):
        with phase2c_env() as env:
            pid, lid = create_product(env, "Secondary")
            repo = ProductBarcodesRepository(env.db)
            repo.assign_barcode(producto_local_id=lid, barcode="MAIN")
            repo.assign_barcode(producto_local_id=lid, barcode="SECONDARY")
            self.assertEqual(repo.lookup_product("MAIN")["id"], pid)
            self.assertEqual(repo.lookup_product("SECONDARY")["id"], pid)


if __name__ == "__main__":
    unittest.main()

