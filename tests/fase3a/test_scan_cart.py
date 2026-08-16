# -*- coding: utf-8 -*-
"""Scan → carrito, cantidades, packaging y dinero. Sin ferreteria.db comercial."""
from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from repositories.product_barcodes_repo import (
    PACKAGE_ROLE_BASE_UNIT,
    PACKAGE_ROLE_CUSTOM_PRESENTATION,
    PACKAGE_ROLE_FULL_PACKAGE,
    ProductBarcodesRepository,
)
from repositories.productos_repo import ProductosRepository
from services.pos_cart import (
    PACKAGING_BLOCKED,
    OFFLINE_FINALIZE_BLOCKED,
    PosCart,
    PosCartError,
    pos_finalize_allowed,
)
from tests.fase3a.helpers import (
    assert_not_commercial_db,
    phase3a_env,
    seed_pos_product,
)


class PosScanCartTest(unittest.TestCase):
    def test_01_primary_barcode_lookup(self):
        with phase3a_env() as env:
            assert_not_commercial_db(env)
            pid, _lid, _p = seed_pos_product(env, barcode="PRIMARY-01")
            found = ProductosRepository(env.db).obtener_por_codigo("PRIMARY-01")
            self.assertEqual(found["id"], pid)

    def test_02_secondary_barcode_lookup(self):
        with phase3a_env() as env:
            pid, lid, _p = seed_pos_product(
                env, barcode="PRI", extra_barcodes=("SEC",)
            )
            repo = ProductBarcodesRepository(env.db)
            self.assertEqual(repo.lookup_product("PRI")["id"], pid)
            self.assertEqual(repo.lookup_product("SEC")["id"], pid)
            self.assertEqual(repo.lookup_product("SEC")["local_id"], lid)

    def test_03_leading_zero_barcode(self):
        with phase3a_env() as env:
            pid, _lid, _p = seed_pos_product(env, barcode="0012345")
            cart = PosCart()
            result = cart.add_scan(ProductosRepository(env.db), "0012345\r")
            self.assertTrue(result.ok, result.error)
            self.assertEqual(result.barcode, "0012345")
            self.assertEqual(cart.lines[0]["producto"]["id"], pid)

    def test_04_scan_adds_product_without_sale(self):
        with phase3a_env() as env:
            seed_pos_product(env, barcode="SCAN-ADD")
            cart = PosCart()
            result = cart.add_scan(ProductosRepository(env.db), "SCAN-ADD")
            self.assertTrue(result.ok)
            self.assertFalse(result.sale_registered)
            self.assertEqual(len(cart.lines), 1)
            self.assertEqual(cart.lines[0]["cantidad"], Decimal("1"))

    def test_05_repeated_scan_increments_same_line(self):
        with phase3a_env() as env:
            seed_pos_product(env, barcode="REP")
            cart = PosCart()
            repo = ProductosRepository(env.db)
            cart.add_scan(repo, "REP")
            cart.add_scan(repo, "REP")
            self.assertEqual(len(cart.lines), 1)
            self.assertEqual(cart.lines[0]["cantidad"], Decimal("2"))

    def test_06_manual_add(self):
        with phase3a_env() as env:
            _pid, _lid, product = seed_pos_product(env, barcode="MAN")
            cart = PosCart()
            cart.add_manual(product, Decimal("3"))
            self.assertEqual(cart.lines[0]["cantidad"], Decimal("3"))

    def test_07_quantity_validation(self):
        with phase3a_env() as env:
            _pid, _lid, product = seed_pos_product(env)
            cart = PosCart()
            with self.assertRaises(PosCartError):
                cart.add_manual(product, 0)
            with self.assertRaises(PosCartError):
                cart.add_manual(product, Decimal("-1"))

    def test_08_decimal_quantity_when_allowed(self):
        with phase3a_env() as env:
            _pid, _lid, product = seed_pos_product(
                env, barcode="DEC", permite_decimales=1
            )
            cart = PosCart()
            cart.add_manual(product, Decimal("1.5"))
            self.assertEqual(cart.lines[0]["cantidad"], Decimal("1.5"))
            whole = dict(product)
            whole["permite_decimales"] = 0
            cart2 = PosCart()
            with self.assertRaises(PosCartError):
                cart2.add_manual(whole, Decimal("1.5"))

    def test_09_price_total_exactness(self):
        with phase3a_env() as env:
            _pid, _lid, product = seed_pos_product(
                env, precio_venta="1500.50", permite_decimales=1
            )
            cart = PosCart()
            cart.add_manual(product, Decimal("2"), precio_unitario=Decimal("1500.50"))
            subtotal, total = cart.totals()
            self.assertEqual(subtotal, Decimal("3001.00"))
            self.assertEqual(total, Decimal("3001.00"))
            self.assertNotIsInstance(subtotal, float)

    def test_15_same_sku_via_secondary_barcode(self):
        with phase3a_env() as env:
            pid, lid, _p = seed_pos_product(
                env, barcode="P1", extra_barcodes=("P2",)
            )
            cart = PosCart()
            repo = ProductosRepository(env.db)
            cart.add_scan(repo, "P1")
            cart.add_scan(repo, "P2")
            self.assertEqual(len(cart.lines), 1)
            self.assertEqual(cart.lines[0]["producto"]["id"], pid)
            self.assertEqual(cart.lines[0]["producto"]["local_id"], lid)
            self.assertEqual(cart.lines[0]["cantidad"], Decimal("2"))

    def test_16_package_role_base_and_blocked_full_package(self):
        with phase3a_env() as env:
            seed_pos_product(env, barcode="BASE")
            cart = PosCart()
            repo = ProductosRepository(env.db)
            ok = cart.add_scan(repo, "BASE")
            self.assertTrue(ok.ok)
            self.assertEqual(ok.package_role, PACKAGE_ROLE_BASE_UNIT)

            pid, lid, _p = seed_pos_product(
                env,
                name="Caja sin factor",
                barcode="BOX-NO",
                package_role=PACKAGE_ROLE_FULL_PACKAGE,
            )
            blocked = cart.add_scan(repo, "BOX-NO")
            self.assertFalse(blocked.ok)
            self.assertIn(PACKAGING_BLOCKED, blocked.error)

            conn = env.connect()
            try:
                conn.execute(
                    "UPDATE productos SET unidades_por_caja=12, viene_en_caja=1 WHERE id=?",
                    (pid,),
                )
                conn.commit()
            finally:
                conn.close()
            ProductBarcodesRepository(env.db).assign_barcode(
                producto_local_id=lid,
                barcode="BOX-YES",
                package_role=PACKAGE_ROLE_FULL_PACKAGE,
            )
            cart2 = PosCart()
            converted = cart2.add_scan(ProductosRepository(env.db), "BOX-YES")
            self.assertTrue(converted.ok, converted.error)
            self.assertEqual(cart2.lines[0]["cantidad"], Decimal("12"))

    def test_16b_custom_presentation_without_contract_is_blocked(self):
        with phase3a_env() as env:
            seed_pos_product(
                env,
                barcode="CUST",
                package_role=PACKAGE_ROLE_CUSTOM_PRESENTATION,
            )
            result = PosCart().add_scan(ProductosRepository(env.db), "CUST")
            self.assertFalse(result.ok)
            self.assertIn(PACKAGING_BLOCKED, result.error)

    def test_17_offline_allows_cart_but_blocks_finalize(self):
        with phase3a_env() as env:
            seed_pos_product(env, barcode="OFF")
            cart = PosCart()
            result = cart.add_scan(ProductosRepository(env.db), "OFF")
            self.assertTrue(result.ok)
            allowed, reason = pos_finalize_allowed(
                env.db, inventory_mode="authoritative"
            )
            self.assertFalse(allowed)
            self.assertEqual(reason, OFFLINE_FINALIZE_BLOCKED)
            self.assertEqual(len(cart.lines), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
