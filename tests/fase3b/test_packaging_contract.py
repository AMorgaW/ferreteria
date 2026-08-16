# -*- coding: utf-8 -*-
"""Contrato de empaque general: no asume CAJA. POS y compras el mismo converter."""
from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from packaging_conversion import (
    PACKAGING_BLOCKED,
    PRESENTATION_HALF_PACKAGE,
    PackagingConversionBlocked,
    get_base_units_per_package,
    quantity_in_base_units,
)
from repositories.product_barcodes_repo import PACKAGE_ROLE_FULL_PACKAGE
from repositories.productos_repo import ProductosRepository
from services.pos_cart import PosCart
from services.purchase_cart import PurchaseCart
from tests.fase3b.helpers import phase3b_env, seed_purchase_product


def _pkg(
    *,
    presentacion,
    unidad_base,
    cantidad,
    vende_empaque=True,
    vende_medio=False,
    permite_decimales=0,
    **extra,
):
    product = {
        "id": extra.pop("id", 1),
        "nombre": extra.pop("nombre", presentacion),
        "unidad_base": unidad_base,
        "unidad_medida": unidad_base,
        "presentacion_empaque": presentacion,
        "presentacion": presentacion,
        "cantidad_base_por_empaque": cantidad,
        "vende_empaque_completo": 1 if vende_empaque else 0,
        "vende_por_empaque": 1 if vende_empaque else 0,
        "vende_medio_empaque": 1 if vende_medio else 0,
        "permite_decimales": permite_decimales,
    }
    product.update(extra)
    return product


class PackagingContractTest(unittest.TestCase):
    def test_01_caja_12_to_12_base(self):
        product = _pkg(presentacion="CAJA", unidad_base="UNIDAD", cantidad=12)
        self.assertEqual(get_base_units_per_package(product), Decimal("12"))
        self.assertEqual(
            quantity_in_base_units(product, PACKAGE_ROLE_FULL_PACKAGE, 1),
            Decimal("12"),
        )

    def test_02_saco_50_kg_to_50_base(self):
        product = _pkg(presentacion="SACO", unidad_base="KG", cantidad=50)
        self.assertEqual(get_base_units_per_package(product), Decimal("50"))
        self.assertEqual(
            quantity_in_base_units(product, PACKAGE_ROLE_FULL_PACKAGE, 1),
            Decimal("50"),
        )

    def test_03_rollo_100_m_to_100_base(self):
        product = _pkg(presentacion="ROLLO", unidad_base="METRO", cantidad=100)
        self.assertEqual(get_base_units_per_package(product), Decimal("100"))
        self.assertEqual(
            quantity_in_base_units(product, PACKAGE_ROLE_FULL_PACKAGE, 1),
            Decimal("100"),
        )

    def test_04_two_full_packages_times_factor(self):
        product = _pkg(presentacion="BULTO", unidad_base="UNIDAD", cantidad=12)
        self.assertEqual(
            quantity_in_base_units(product, PACKAGE_ROLE_FULL_PACKAGE, 2),
            Decimal("24"),
        )

    def test_05_half_package_general(self):
        caja = _pkg(
            presentacion="CAJA", unidad_base="UNIDAD", cantidad=12, vende_medio=True
        )
        saco = _pkg(
            presentacion="SACO",
            unidad_base="KG",
            cantidad=25,
            vende_medio=True,
            permite_decimales=1,
        )
        self.assertEqual(
            quantity_in_base_units(caja, PRESENTATION_HALF_PACKAGE, 1),
            Decimal("6"),
        )
        self.assertEqual(
            quantity_in_base_units(saco, PRESENTATION_HALF_PACKAGE, 1),
            Decimal("12.5"),
        )

    def test_06_half_not_representable_rejected(self):
        product = _pkg(
            presentacion="SACO",
            unidad_base="KG",
            cantidad=25,
            vende_medio=True,
            permite_decimales=0,
        )
        with self.assertRaises(PackagingConversionBlocked) as ctx:
            quantity_in_base_units(product, PRESENTATION_HALF_PACKAGE, 1)
        self.assertIn(PACKAGING_BLOCKED, str(ctx.exception))
        self.assertIn("representable", str(ctx.exception).lower())

    def test_06b_legacy_half_mismatch_fail_closed(self):
        product = _pkg(
            presentacion="CAJA",
            unidad_base="UNIDAD",
            cantidad=12,
            vende_medio=True,
            unidades_por_media_caja=5,
        )
        with self.assertRaises(PackagingConversionBlocked):
            quantity_in_base_units(product, PRESENTATION_HALF_PACKAGE, 1)

    def test_07_missing_factor_blocked(self):
        product = _pkg(
            presentacion="BOLSA", unidad_base="UNIDAD", cantidad=1, vende_empaque=True
        )
        product["cantidad_base_por_empaque"] = None
        self.assertIsNone(get_base_units_per_package(product))
        with self.assertRaises(PackagingConversionBlocked) as ctx:
            quantity_in_base_units(product, PACKAGE_ROLE_FULL_PACKAGE, 1)
        self.assertIn(PACKAGING_BLOCKED, str(ctx.exception))

    def test_08_pos_uses_canonical_converter(self):
        with phase3b_env() as env:
            pid, _lid, _p = seed_purchase_product(
                env,
                name="Cemento POS",
                barcode="POS-SACO",
                package_role=PACKAGE_ROLE_FULL_PACKAGE,
                unidades_por_caja=50,
                vende_por_empaque=1,
            )
            conn = env.connect()
            try:
                conn.execute(
                    "UPDATE productos SET presentacion=?, unidad_medida=? WHERE id=?",
                    ("SACO", "KG", pid),
                )
                conn.commit()
            finally:
                conn.close()
            product = ProductosRepository(env.db).obtener_por_id(pid)
            self.assertEqual(get_base_units_per_package(product), Decimal("50"))
            cart = PosCart()
            result = cart.add_scan(ProductosRepository(env.db), "POS-SACO")
            self.assertTrue(result.ok, result.error)
            self.assertEqual(cart.lines[0]["cantidad"], Decimal("50"))
            self.assertEqual(cart.lines[0]["producto"]["id"], pid)

    def test_09_purchases_use_same_converter(self):
        with phase3b_env() as env:
            pid, _lid, _p = seed_purchase_product(
                env,
                name="Cable",
                barcode="COM-ROLLO",
                package_role=PACKAGE_ROLE_FULL_PACKAGE,
                unidades_por_caja=100,
                vende_por_empaque=1,
            )
            conn = env.connect()
            try:
                conn.execute(
                    "UPDATE productos SET presentacion=?, unidad_medida=? WHERE id=?",
                    ("ROLLO", "METRO", pid),
                )
                conn.commit()
            finally:
                conn.close()
            product = ProductosRepository(env.db).obtener_por_id(pid)
            expected = quantity_in_base_units(product, PACKAGE_ROLE_FULL_PACKAGE, 2)
            cart = PurchaseCart()
            cart.add_line(
                product, Decimal("2"), package_role=PACKAGE_ROLE_FULL_PACKAGE, costo_unitario=1000
            )
            self.assertEqual(cart.lines[0]["cantidad"], expected)
            self.assertEqual(expected, Decimal("200"))
            self.assertEqual(cart.lines[0]["producto"]["id"], pid)

    def test_10_no_separate_stock_per_presentation(self):
        with phase3b_env() as env:
            pid, lid, product = seed_purchase_product(
                env,
                barcode="SAME-SKU",
                package_role=PACKAGE_ROLE_FULL_PACKAGE,
                unidades_por_caja=12,
                vende_por_empaque=1,
            )
            pos = PosCart()
            pos.add_scan(ProductosRepository(env.db), "SAME-SKU")
            buy = PurchaseCart()
            buy.add_line(
                product, 1, package_role=PACKAGE_ROLE_FULL_PACKAGE, costo_unitario=1
            )
            self.assertEqual(pos.lines[0]["producto"]["id"], pid)
            self.assertEqual(buy.lines[0]["producto"]["id"], pid)
            self.assertEqual(pos.lines[0]["producto"]["local_id"], lid)
            self.assertEqual(pos.lines[0]["cantidad"], Decimal("12"))
            self.assertEqual(buy.lines[0]["cantidad"], Decimal("12"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
