from __future__ import annotations

import re
import sqlite3
import unittest

from repositories.product_barcodes_repo import (
    BarcodeRepositoryError,
    FrpBarcodeGenerator,
    FrpGenerationError,
    ProductBarcodesRepository,
)
from tests.fase2c.helpers import create_product, phase2c_env


class FrpTest(unittest.TestCase):
    def test_21_frp_prefix(self):
        value = FrpBarcodeGenerator(lambda _value: False).generate()
        self.assertTrue(value.startswith("FRP-"))

    def test_22_exactly_16_uppercase_hex(self):
        value = FrpBarcodeGenerator(lambda _value: False).generate()
        self.assertRegex(value, r"^FRP-[0-9A-F]{16}$")

    def test_23_secrets_contract_requests_eight_bytes(self):
        calls = []

        def token_hex(size):
            calls.append(size)
            return "a" * 16

        value = FrpBarcodeGenerator(lambda _value: False, token_hex=token_hex).generate()
        self.assertEqual(calls, [8])
        self.assertEqual(value, "FRP-AAAAAAAAAAAAAAAA")

    def test_24_collision_retry(self):
        tokens = iter(("1" * 16, "2" * 16))
        generator = FrpBarcodeGenerator(
            lambda value: value == "FRP-1111111111111111",
            token_hex=lambda _size: next(tokens),
        )
        self.assertEqual(generator.generate(), "FRP-2222222222222222")

    def test_25_bounded_retry_failure(self):
        calls = []

        def token(_size):
            calls.append(1)
            return "f" * 16

        with self.assertRaises(FrpGenerationError):
            FrpBarcodeGenerator(lambda _value: True, max_attempts=3, token_hex=token).generate()
        self.assertEqual(len(calls), 3)

    def test_26_frp_unique_constraint(self):
        with phase2c_env() as env:
            _a, lid_a = create_product(env, "FRP A")
            _b, lid_b = create_product(env, "FRP B")
            repo = ProductBarcodesRepository(env.db)
            record = repo.assign_barcode(
                producto_local_id=lid_a, barcode="FRP-AAAAAAAAAAAAAAAA"
            )
            conn = env.connect()
            try:
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        "INSERT INTO product_barcodes(local_id,producto_local_id,barcode) VALUES(?,?,?)",
                        ("new-local-id", lid_b, record.barcode),
                    )
            finally:
                conn.close()

    def test_27_no_automatic_mass_frp_generation(self):
        with phase2c_env() as env:
            create_product(env, "Legacy 1")
            create_product(env, "Legacy 2")
            conn = env.connect()
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM product_barcodes").fetchone()[0], 0)
            finally:
                conn.close()

    def test_28_no_frp_when_manufacturer_barcode_exists_without_override(self):
        with phase2c_env() as env:
            _pid, lid = create_product(env, "Manufacturer")
            repo = ProductBarcodesRepository(env.db)
            repo.assign_barcode(producto_local_id=lid, barcode="MFG")
            with self.assertRaises(BarcodeRepositoryError):
                repo.generate_and_assign_internal(lid)


if __name__ == "__main__":
    unittest.main()

