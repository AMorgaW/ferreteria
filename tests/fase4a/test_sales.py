# -*- coding: utf-8 -*-
"""Gross / returns / net sales y top productos netos de devoluciones."""
from __future__ import annotations

import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from returns_schema import KIND_CUSTOMER_RETURN, KIND_SALE_VOID, ORIGINAL_TIPO_VENTA
from tests.fase1e1.helpers import transport_applied
from tests.fase4a.helpers import (
    complete_sale,
    phase4a_env,
    reportes_service,
    returns_service,
    seed_pos_product,
)


def _confirm_return(env, venta_id, kind, cantidad):
    svc = returns_service(env)
    ok, msg, rid = svc.guardar_borrador(
        kind=kind,
        original_tipo=ORIGINAL_TIPO_VENTA,
        original_id=venta_id,
        items=[{"producto_id": 1, "cantidad": cantidad}],
    )
    if not ok:
        raise AssertionError(msg)
    ok2, msg2, _ = svc.confirmar(
        rid,
        inventory_mode="authoritative",
        inventory_command_id=str(uuid.uuid4()),
        inventory_transport=transport_applied(),
    )
    if not ok2:
        raise AssertionError(msg2)
    return rid


class SalesReportingTest(unittest.TestCase):
    def test_04_gross_sale(self):
        with phase4a_env() as env:
            seed_pos_product(env, stock=20)
            venta = complete_sale(
                env, [{"producto_id": 1, "cantidad": 1, "precio_unitario": 100}]
            )
            hoy = str(venta.fecha)[:10]
            resumen = reportes_service(env).reporte_ventas_periodo(hoy, hoy)["resumen"]
            self.assertEqual(resumen["gross_sales"], Decimal("100.00"))
            self.assertEqual(resumen["returns_sales"], Decimal("0.00"))
            self.assertEqual(resumen["net_sales"], Decimal("100.00"))

    def test_05_partial_return(self):
        with phase4a_env() as env:
            seed_pos_product(env, stock=20)
            venta = complete_sale(
                env, [{"producto_id": 1, "cantidad": 10, "precio_unitario": 10}]
            )
            _confirm_return(env, venta.id, KIND_CUSTOMER_RETURN, 3)
            hoy = str(venta.fecha)[:10]
            resumen = reportes_service(env).reporte_ventas_periodo(hoy, hoy)["resumen"]
            self.assertEqual(resumen["gross_sales"], Decimal("100.00"))
            self.assertEqual(resumen["customer_returns"], Decimal("30.00"))
            self.assertEqual(resumen["net_sales"], Decimal("70.00"))
            conn = env.connect()
            try:
                estado = conn.execute(
                    "SELECT estado FROM ventas WHERE id=?", (venta.id,)
                ).fetchone()["estado"]
            finally:
                conn.close()
            self.assertEqual(estado, "COMPLETADA")

    def test_06_sale_void(self):
        with phase4a_env() as env:
            seed_pos_product(env, stock=20)
            venta = complete_sale(
                env, [{"producto_id": 1, "cantidad": 1, "precio_unitario": 100}]
            )
            _confirm_return(env, venta.id, KIND_SALE_VOID, 1)
            hoy = str(venta.fecha)[:10]
            resumen = reportes_service(env).reporte_ventas_periodo(hoy, hoy)["resumen"]
            self.assertEqual(resumen["gross_sales"], Decimal("100.00"))
            self.assertEqual(resumen["sale_voids"], Decimal("100.00"))
            self.assertEqual(resumen["net_sales"], Decimal("0.00"))

    def test_07_net_sales(self):
        with phase4a_env() as env:
            seed_pos_product(env, stock=20)
            venta = complete_sale(
                env, [{"producto_id": 1, "cantidad": 10, "precio_unitario": 10}]
            )
            _confirm_return(env, venta.id, KIND_CUSTOMER_RETURN, 3)
            hoy = str(venta.fecha)[:10]
            resumen = reportes_service(env).reporte_ventas_periodo(hoy, hoy)["resumen"]
            self.assertEqual(
                resumen["net_sales"],
                resumen["gross_sales"] - resumen["returns_sales"],
            )
            self.assertEqual(resumen["monto_total"], resumen["net_sales"])

    def test_08_top_product_net_of_returns(self):
        with phase4a_env() as env:
            seed_pos_product(env, stock=20, name="Perno")
            venta = complete_sale(
                env, [{"producto_id": 1, "cantidad": 5, "precio_unitario": 10}]
            )
            _confirm_return(env, venta.id, KIND_CUSTOMER_RETURN, 2)
            hoy = str(venta.fecha)[:10]
            top = reportes_service(env).reporte_productos_mas_vendidos(hoy, hoy, 5)
            item = top["productos"][0]
            self.assertEqual(item["gross_quantity"], Decimal("5"))
            self.assertEqual(item["returned_quantity"], Decimal("2"))
            self.assertEqual(item["net_quantity"], Decimal("3"))
            self.assertEqual(item["cantidad_vendida"], Decimal("3"))

    def test_19_date_boundary_consistency(self):
        with phase4a_env() as env:
            seed_pos_product(env, stock=20)
            venta = complete_sale(
                env, [{"producto_id": 1, "cantidad": 1, "precio_unitario": 80}]
            )
            conn = env.connect()
            try:
                conn.execute(
                    "UPDATE ventas SET fecha=? WHERE id=?",
                    ("2026-08-15 12:00:00", venta.id),
                )
                conn.commit()
            finally:
                conn.close()
            svc = reportes_service(env)
            inside = svc.reporte_ventas_periodo("2026-08-15", "2026-08-15")["resumen"]
            outside = svc.reporte_ventas_periodo("2026-08-16", "2026-08-16")["resumen"]
            self.assertEqual(inside["gross_sales"], Decimal("80.00"))
            self.assertEqual(outside["gross_sales"], Decimal("0.00"))
            self.assertEqual(inside["total_ventas"], 1)
            self.assertEqual(outside["total_ventas"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
