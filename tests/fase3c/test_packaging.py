# -*- coding: utf-8 -*-
"""Packaging canónico en reversos 3C. Reutiliza packaging_conversion.py."""
from __future__ import annotations

import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from packaging_conversion import quantity_in_base_units
from repositories.product_barcodes_repo import (
    PACKAGE_ROLE_CUSTOM_PRESENTATION,
    PACKAGE_ROLE_FULL_PACKAGE,
)
from returns_schema import (
    KIND_CUSTOMER_RETURN,
    KIND_SUPPLIER_RETURN,
    ORIGINAL_TIPO_COMPRA,
    ORIGINAL_TIPO_VENTA,
)
from tests.fase1e.helpers import insert_usuario, seed_producto
from tests.fase1e1.helpers import load_ops, transport_applied
from tests.fase3c.helpers import (
    complete_receipt,
    complete_sale,
    phase3c_env,
    returns_service,
    seed_pos_product,
)


class ReturnsPackagingTest(unittest.TestCase):
    def test_12_base_unit_conversion(self):
        with phase3c_env() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=20)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            venta = complete_sale(env, [{"producto_id": 1, "cantidad": 3, "precio_unitario": 10}])
            svc = returns_service(env)
            command_id = str(uuid.uuid4())
            ok, msg, rid = svc.guardar_borrador(
                kind=KIND_CUSTOMER_RETURN,
                original_tipo=ORIGINAL_TIPO_VENTA,
                original_id=venta.id,
                items=[{"producto_id": 1, "cantidad": 1, "package_role": "BASE_UNIT"}],
            )
            self.assertTrue(ok, msg)
            self.assertTrue(
                svc.confirmar(
                    rid,
                    inventory_mode="authoritative",
                    inventory_command_id=command_id,
                    inventory_transport=transport_applied(),
                )[0]
            )
            conn = env.connect()
            try:
                self.assertEqual(int(load_ops(conn, command_id)[0]["delta_scaled"]), 1000)
            finally:
                conn.close()

    def test_13_full_package_conversion(self):
        with phase3c_env() as env:
            pid, _lid, product = seed_pos_product(
                env,
                stock=200,
                unidades_por_caja=50,
                viene_en_caja=1,
                vende_por_empaque=1,
            )
            self.assertEqual(
                quantity_in_base_units(product, PACKAGE_ROLE_FULL_PACKAGE, 1),
                Decimal("50"),
            )
            venta = complete_sale(
                env, [{"producto_id": pid, "cantidad": 50, "precio_unitario": 10}]
            )
            svc = returns_service(env)
            command_id = str(uuid.uuid4())
            ok, msg, rid = svc.guardar_borrador(
                kind=KIND_CUSTOMER_RETURN,
                original_tipo=ORIGINAL_TIPO_VENTA,
                original_id=venta.id,
                items=[
                    {
                        "producto_id": pid,
                        "cantidad_presentacion": 1,
                        "package_role": PACKAGE_ROLE_FULL_PACKAGE,
                    }
                ],
            )
            self.assertTrue(ok, msg)
            self.assertTrue(
                svc.confirmar(
                    rid,
                    inventory_mode="authoritative",
                    inventory_command_id=command_id,
                    inventory_transport=transport_applied(),
                )[0]
            )
            conn = env.connect()
            try:
                self.assertEqual(int(load_ops(conn, command_id)[0]["delta_scaled"]), 50000)
            finally:
                conn.close()

    def test_14_half_and_custom_use_canonical_converter(self):
        with phase3c_env() as env:
            pid, _lid, product = seed_pos_product(
                env,
                stock=200,
                unidades_por_caja=12,
                viene_en_caja=1,
                vende_por_empaque=1,
                unidades_venta_custom='[{"nombre":"PACK","factor":3}]',
            )
            conn = env.connect()
            try:
                env.insert_proveedor(conn)
                conn.commit()
            finally:
                conn.close()
            product = {**dict(product), "vende_medio_empaque": 1}
            from packaging_conversion import PRESENTATION_HALF_PACKAGE

            self.assertEqual(
                quantity_in_base_units(product, PRESENTATION_HALF_PACKAGE, 1),
                Decimal("6"),
            )
            self.assertEqual(
                quantity_in_base_units(product, PACKAGE_ROLE_CUSTOM_PRESENTATION, 1),
                Decimal("3"),
            )
            cid = complete_receipt(
                env, [{"producto_id": pid, "cantidad": 24, "precio_unitario": 10}]
            )
            svc = returns_service(env)
            command_id = str(uuid.uuid4())
            ok, msg, rid = svc.guardar_borrador(
                kind=KIND_SUPPLIER_RETURN,
                original_tipo=ORIGINAL_TIPO_COMPRA,
                original_id=cid,
                items=[
                    {
                        "producto_id": pid,
                        "cantidad_presentacion": 1,
                        "package_role": PACKAGE_ROLE_CUSTOM_PRESENTATION,
                    }
                ],
            )
            self.assertTrue(ok, msg)
            self.assertTrue(
                svc.confirmar(
                    rid,
                    inventory_mode="authoritative",
                    inventory_command_id=command_id,
                    inventory_transport=transport_applied(),
                )[0]
            )
            conn = env.connect()
            try:
                self.assertEqual(int(load_ops(conn, command_id)[0]["delta_scaled"]), -3000)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
