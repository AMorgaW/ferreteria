# -*- coding: utf-8 -*-
"""Compras COMPLETED, DRAFT excluido, supplier return, neto."""
from __future__ import annotations

import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from returns_schema import KIND_SUPPLIER_RETURN, ORIGINAL_TIPO_COMPRA
from tests.fase1e1.helpers import transport_applied
from tests.fase4a.helpers import (
    complete_receipt,
    compras_service,
    phase4a_env,
    reportes_compras,
    returns_service,
    seed_purchase_product,
)


class PurchasesReportingTest(unittest.TestCase):
    def _proveedor(self, env):
        conn = env.connect()
        try:
            env.insert_proveedor(conn)
            conn.commit()
        finally:
            conn.close()

    def test_09_completed_purchase(self):
        with phase4a_env() as env:
            seed_purchase_product(env, stock=10)
            self._proveedor(env)
            complete_receipt(
                env, [{"producto_id": 1, "cantidad": 4, "precio_unitario": 25}]
            )
            hoy = __import__("datetime").date.today().isoformat()
            resumen = reportes_compras(env).resumen_compras_periodo(hoy, hoy)
            self.assertEqual(resumen["total_compras"], 1)
            self.assertEqual(resumen["gross_purchases"], Decimal("100.00"))
            self.assertEqual(resumen["net_purchases"], Decimal("100.00"))

    def test_10_draft_excluded(self):
        with phase4a_env() as env:
            seed_purchase_product(env, stock=10)
            self._proveedor(env)
            ok, msg, cid = compras_service(env).guardar_borrador(
                proveedor_id=1,
                productos=[{"producto_id": 1, "cantidad": 8, "precio_unitario": 50}],
                numero_factura="DRAFT-4A",
            )
            self.assertTrue(ok, msg)
            self.assertIsNotNone(cid)
            hoy = __import__("datetime").date.today().isoformat()
            resumen = reportes_compras(env).resumen_compras_periodo(hoy, hoy)
            self.assertEqual(resumen["total_compras"], 0)
            self.assertEqual(resumen["gross_purchases"], Decimal("0.00"))
            rows = reportes_compras(env).obtener_compras_por_proveedor(
                fecha_inicio=hoy, fecha_fin=hoy
            )
            self.assertEqual(rows, [])

    def test_11_supplier_return(self):
        with phase4a_env() as env:
            seed_purchase_product(env, stock=10)
            self._proveedor(env)
            cid = complete_receipt(
                env, [{"producto_id": 1, "cantidad": 10, "precio_unitario": 20}]
            )
            svc = returns_service(env)
            ok, msg, rid = svc.guardar_borrador(
                kind=KIND_SUPPLIER_RETURN,
                original_tipo=ORIGINAL_TIPO_COMPRA,
                original_id=cid,
                items=[{"producto_id": 1, "cantidad": 2}],
            )
            self.assertTrue(ok, msg)
            ok2, msg2, _ = svc.confirmar(
                rid,
                inventory_mode="authoritative",
                inventory_command_id=str(uuid.uuid4()),
                inventory_transport=transport_applied(),
            )
            self.assertTrue(ok2, msg2)
            hoy = __import__("datetime").date.today().isoformat()
            resumen = reportes_compras(env).resumen_compras_periodo(hoy, hoy)
            self.assertEqual(resumen["gross_purchases"], Decimal("200.00"))
            self.assertEqual(resumen["supplier_returns"], Decimal("40.00"))

    def test_12_net_purchases(self):
        with phase4a_env() as env:
            seed_purchase_product(env, stock=10)
            self._proveedor(env)
            cid = complete_receipt(
                env, [{"producto_id": 1, "cantidad": 10, "precio_unitario": 20}]
            )
            svc = returns_service(env)
            ok, msg, rid = svc.guardar_borrador(
                kind=KIND_SUPPLIER_RETURN,
                original_tipo=ORIGINAL_TIPO_COMPRA,
                original_id=cid,
                items=[{"producto_id": 1, "cantidad": 2}],
            )
            self.assertTrue(ok, msg)
            ok2, msg2, _ = svc.confirmar(
                rid,
                inventory_mode="authoritative",
                inventory_command_id=str(uuid.uuid4()),
                inventory_transport=transport_applied(),
            )
            self.assertTrue(ok2, msg2)
            hoy = __import__("datetime").date.today().isoformat()
            resumen = reportes_compras(env).resumen_compras_periodo(hoy, hoy)
            self.assertEqual(
                resumen["net_purchases"],
                resumen["gross_purchases"] - resumen["supplier_returns"],
            )
            self.assertEqual(resumen["net_purchases"], Decimal("160.00"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
