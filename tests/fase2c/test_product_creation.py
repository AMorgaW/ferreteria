from __future__ import annotations

import unittest

from models import Producto
from repositories.product_barcodes_repo import (
    BARCODE_TYPE_INTERNAL_FRP,
    SOURCE_EXPLICIT_FRP,
    ProductBarcodesRepository,
)
from repositories.productos_repo import (
    PRODUCT_CREATION_FINAL,
    PRODUCT_CREATION_LEGACY_COMPAT,
    PRODUCT_CREATION_STAGING,
    ProductosRepository,
)
from tests.fase2c.helpers import phase2c_env


def _product(name):
    return Producto(nombre=name, precio_venta=1000, stock=0)


class ProductCreationBarcodePolicyTest(unittest.TestCase):
    def test_29_new_final_product_without_barcode_rejected(self):
        with phase2c_env() as env:
            repo = ProductosRepository(env.db)
            ok, message, pid = repo.crear_producto(
                _product("Sin barcode"), creation_policy=PRODUCT_CREATION_FINAL
            )
            self.assertFalse(ok)
            self.assertIsNone(pid)
            self.assertIn("requiere", message)
            conn = env.connect()
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM productos WHERE nombre='Sin barcode'").fetchone()[0], 0)
            finally:
                conn.close()

    def test_30_staging_may_remain_barcode_pending(self):
        with phase2c_env() as env:
            repo = ProductosRepository(env.db)
            ok, message, pid = repo.crear_producto(
                _product("Staging"), creation_policy=PRODUCT_CREATION_STAGING
            )
            self.assertTrue(ok, message)
            self.assertEqual(repo.obtener_por_id(pid)["barcode_status"], "BARCODE_PENDING")

    def test_31_legacy_without_barcode_remains_accessible(self):
        with phase2c_env() as env:
            repo = ProductosRepository(env.db)
            ok, message, pid = repo.crear_producto(
                _product("Legacy"), creation_policy=PRODUCT_CREATION_LEGACY_COMPAT
            )
            self.assertTrue(ok, message)
            product = repo.obtener_por_id(pid)
            self.assertEqual(product["barcode_status"], "BARCODE_MISSING_LEGACY")
            self.assertIsNotNone(product)

    def test_32_final_with_verified_manufacturer_barcode_succeeds(self):
        with phase2c_env() as env:
            repo = ProductosRepository(env.db)
            ok, message, pid = repo.crear_producto(
                _product("Manufacturer final"),
                creation_policy=PRODUCT_CREATION_FINAL,
                verified_barcode="0012345678905",
            )
            self.assertTrue(ok, message)
            product = repo.obtener_por_id(pid)
            self.assertEqual(product["barcode_status"], "BARCODE_VERIFIED")
            self.assertIsNone(product["codigo_barras"])
            self.assertEqual(
                ProductBarcodesRepository(env.db).lookup_product("0012345678905")["id"],
                pid,
            )

    def test_33_final_with_explicit_frp_succeeds(self):
        with phase2c_env() as env:
            repo = ProductosRepository(env.db)
            frp = "FRP-A4D81C390D14FA72"
            ok, message, pid = repo.crear_producto(
                _product("FRP final"),
                creation_policy=PRODUCT_CREATION_FINAL,
                verified_barcode=frp,
                verified_barcode_type=BARCODE_TYPE_INTERNAL_FRP,
                verified_barcode_source=SOURCE_EXPLICIT_FRP,
            )
            self.assertTrue(ok, message)
            record = ProductBarcodesRepository(env.db).get_by_barcode(frp)
            self.assertEqual(record.barcode_type, BARCODE_TYPE_INTERNAL_FRP)


if __name__ == "__main__":
    unittest.main()

