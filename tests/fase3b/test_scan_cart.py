# -*- coding: utf-8 -*-
"""Proveedor, barcodes, packaging y totales de recepción 3B."""
from __future__ import annotations

import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from packaging_conversion import PACKAGING_BLOCKED, PackagingConversionBlocked
from repositories.product_barcodes_repo import (
    PACKAGE_ROLE_CUSTOM_PRESENTATION,
    PACKAGE_ROLE_FULL_PACKAGE,
    ProductBarcodesRepository,
)
from repositories.productos_repo import ProductosRepository
from repositories.supplier_product_aliases_repo import SupplierProductAliasesRepository
from services.purchase_cart import PurchaseCart
from tests.fase1e.helpers import insert_usuario
from tests.fase3b.helpers import (
    assert_not_commercial_db,
    phase3b_env,
    seed_purchase_product,
)


class ReceivingScanCartTest(unittest.TestCase):
    def test_01_supplier_selection_required(self):
        from services.compras_service import ComprasService
        from tests.fase1e.helpers import AuthPermitido

        with phase3b_env() as env:
            assert_not_commercial_db(env)
            pid, _lid, _p = seed_purchase_product(env)
            svc = ComprasService(env.db, auth=AuthPermitido())
            ok, msg, cid = svc.guardar_borrador(
                proveedor_id=0,
                productos=[{"producto_id": pid, "cantidad": 1, "precio_unitario": 100}],
                numero_factura="F-1",
            )
            self.assertFalse(ok)
            self.assertIsNone(cid)
            self.assertIn("proveedor", msg.lower())

    def test_03_base_unit_line(self):
        with phase3b_env() as env:
            _pid, _lid, product = seed_purchase_product(env, barcode="BASE-R")
            cart = PurchaseCart()
            cart.add_line(product, Decimal("2"), costo_unitario=Decimal("500"))
            items = cart.to_purchase_items()
            self.assertEqual(Decimal(str(items[0]["cantidad"])), Decimal("2"))
            self.assertEqual(items[0]["package_role"], "BASE_UNIT")

    def test_04_full_package_canonical_conversion(self):
        with phase3b_env() as env:
            _pid, _lid, product = seed_purchase_product(
                env,
                barcode="BOX-OK",
                package_role=PACKAGE_ROLE_FULL_PACKAGE,
                unidades_por_caja=12,
                viene_en_caja=1,
                vende_por_empaque=1,
            )
            cart = PurchaseCart()
            cart.add_scan(ProductosRepository(env.db), "BOX-OK", costo_unitario=12000)
            self.assertEqual(cart.lines[0]["cantidad"], Decimal("12"))
            self.assertEqual(cart.lines[0]["cantidad_presentacion"], Decimal("1"))

    def test_05_missing_package_factor_rejected(self):
        with phase3b_env() as env:
            seed_purchase_product(
                env,
                barcode="BOX-NO",
                package_role=PACKAGE_ROLE_FULL_PACKAGE,
            )
            cart = PurchaseCart()
            result = cart.add_scan(ProductosRepository(env.db), "BOX-NO")
            self.assertFalse(result.ok)
            self.assertIn(PACKAGING_BLOCKED, result.error)

    def test_06_custom_presentation_factor(self):
        with phase3b_env() as env:
            _pid, _lid, product = seed_purchase_product(
                env,
                barcode="CUSTOM-OK",
                package_role=PACKAGE_ROLE_CUSTOM_PRESENTATION,
                unidades_venta_custom=json.dumps([{"factor": 5}]),
            )
            cart = PurchaseCart()
            cart.add_scan(ProductosRepository(env.db), "CUSTOM-OK", costo_unitario=1000)
            self.assertEqual(cart.lines[0]["cantidad"], Decimal("5"))

    def test_07_decimal_quantity(self):
        with phase3b_env() as env:
            _pid, _lid, product = seed_purchase_product(
                env, barcode="DEC-R", permite_decimales=1
            )
            cart = PurchaseCart()
            cart.add_line(product, Decimal("1.5"), costo_unitario=Decimal("10"))
            self.assertEqual(cart.lines[0]["cantidad"], Decimal("1.5"))

    def test_08_exact_purchase_totals(self):
        with phase3b_env() as env:
            _pid, _lid, product = seed_purchase_product(
                env, barcode="TOT", permite_decimales=1
            )
            cart = PurchaseCart()
            cart.add_line(product, Decimal("2"), costo_unitario=Decimal("1500.50"))
            subtotal, total = cart.totals()
            self.assertEqual(subtotal, Decimal("3001.00"))
            self.assertEqual(total, Decimal("3001.00"))
            self.assertNotIsInstance(subtotal, float)

    def test_09_barcode_primary(self):
        with phase3b_env() as env:
            pid, _lid, _p = seed_purchase_product(env, barcode="PRI-R")
            found = ProductosRepository(env.db).obtener_por_codigo("PRI-R")
            self.assertEqual(found["id"], pid)

    def test_10_barcode_secondary(self):
        with phase3b_env() as env:
            pid, lid, _p = seed_purchase_product(
                env, barcode="PRI2", extra_barcodes=("SEC-R",)
            )
            repo = ProductBarcodesRepository(env.db)
            self.assertEqual(repo.lookup_product("PRI2")["id"], pid)
            self.assertEqual(repo.lookup_product("SEC-R")["id"], pid)
            self.assertEqual(repo.lookup_product("SEC-R")["local_id"], lid)

    def test_11_supplier_alias_not_physical_barcode(self):
        with phase3b_env() as env:
            pid, lid, _p = seed_purchase_product(env, barcode="PHYS-1")
            conn = env.connect()
            try:
                env.insert_proveedor(conn, proveedor_id=1)
                conn.commit()
            finally:
                conn.close()
            aliases = SupplierProductAliasesRepository(env.db)
            aliases.assign_alias(
                proveedor_id=1, producto_local_id=lid, alias_codigo="SUP-SKU-99"
            )
            barcodes = ProductBarcodesRepository(env.db)
            self.assertIsNone(barcodes.lookup_product("SUP-SKU-99"))
            self.assertIsNone(ProductosRepository(env.db).obtener_por_codigo("SUP-SKU-99"))
            found = aliases.lookup_product(1, "SUP-SKU-99")
            self.assertEqual(found["id"], pid)
            conn = env.connect()
            try:
                n = conn.execute(
                    "SELECT COUNT(*) FROM product_barcodes WHERE barcode=?",
                    ("SUP-SKU-99",),
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(n, 0)
            cart = PurchaseCart()
            result = cart.add_scan(
                ProductosRepository(env.db),
                "SUP-SKU-99",
                aliases_repo=aliases,
                proveedor_id=1,
                costo_unitario=100,
            )
            self.assertTrue(result.ok, result.error)
            self.assertTrue(result.via_supplier_alias)

    def test_half_package_derives_from_canonical_factor(self):
        from packaging_conversion import (
            PRESENTATION_HALF_PACKAGE,
            quantity_in_base_units,
        )

        with phase3b_env() as env:
            _pid, _lid, product = seed_purchase_product(
                env,
                barcode="HALF",
                unidades_por_caja=12,
                viene_en_caja=1,
                vende_por_empaque=1,
            )
            with self.assertRaises(PackagingConversionBlocked):
                quantity_in_base_units(product, PRESENTATION_HALF_PACKAGE, 1)
            product = dict(product)
            product["vende_medio_empaque"] = 1
            product["presentacion_empaque"] = "CAJA"
            self.assertEqual(
                quantity_in_base_units(product, PRESENTATION_HALF_PACKAGE, 1),
                Decimal("6"),
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
