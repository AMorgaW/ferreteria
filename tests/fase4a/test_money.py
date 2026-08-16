# -*- coding: utf-8 -*-
"""Pagos, crédito, caja 3D, rentabilidad y Decimal."""
from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase1e.helpers import insert_usuario
from tests.fase3d.helpers import complete_sale_cash, open_caja
from tests.fase4a.helpers import (
    complete_sale,
    phase4a_env,
    reportes_service,
    seed_pos_product,
)


class MoneyReportingTest(unittest.TestCase):
    def test_13_cash_vs_noncash(self):
        with phase4a_env() as env:
            seed_pos_product(env, stock=20)
            complete_sale(
                env,
                [{"producto_id": 1, "cantidad": 1, "precio_unitario": 50}],
                metodo_pago="EFECTIVO",
            )
            complete_sale(
                env,
                [{"producto_id": 1, "cantidad": 1, "precio_unitario": 30}],
                metodo_pago="TARJETA_DEBITO",
            )
            hoy = __import__("datetime").date.today().isoformat()
            data = reportes_service(env).ventas_por_metodo_pago(hoy, hoy)
            self.assertEqual(data["efectivo_fisico"], Decimal("50.00"))
            self.assertEqual(data["no_efectivo"], Decimal("30.00"))
            tarjeta = next(
                row
                for row in data["por_metodo"]
                if row["metodo_pago"] == "TARJETA_DEBITO"
            )
            self.assertFalse(tarjeta["es_caja_fisica"])

    def test_14_credit_invoiced_collected_pending(self):
        with phase4a_env() as env:
            seed_pos_product(env, stock=20)
            venta = complete_sale(
                env,
                [{"producto_id": 1, "cantidad": 1, "precio_unitario": 100}],
                metodo_pago="CREDITO",
            )
            conn = env.connect()
            try:
                conn.execute(
                    "UPDATE ventas SET monto_pagado=40, estado_pago='PENDIENTE' WHERE id=?",
                    (venta.id,),
                )
                conn.commit()
            finally:
                conn.close()
            hoy = __import__("datetime").date.today().isoformat()
            data = reportes_service(env).ventas_por_metodo_pago(hoy, hoy)
            info = data["credito_info"]
            self.assertEqual(info["total_facturado"], Decimal("100.00"))
            self.assertEqual(info["total_cobrado"], Decimal("40.00"))
            self.assertEqual(info["pendiente"], Decimal("60.00"))
            self.assertEqual(data["efectivo_fisico"], Decimal("0.00"))

    def test_15_caja_uses_fase3d_source(self):
        with phase4a_env() as env:
            conn = env.connect()
            try:
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            seed_pos_product(env, stock=20)
            caja = open_caja(env, Decimal("1000"))
            complete_sale_cash(
                env, [{"producto_id": 1, "cantidad": 1, "precio_unitario": 80}]
            )
            hoy = __import__("datetime").date.today().isoformat()
            flujo = reportes_service(env).flujo_caja(hoy, hoy)
            periodo = caja.obtener_resumen_periodo(hoy, hoy)
            self.assertEqual(flujo["cash_source"], "cash_movements")
            self.assertEqual(flujo["caja"]["cash_in"], periodo["cash_in"])
            self.assertEqual(flujo["flujo_neto"], periodo["esperado"])
            self.assertGreater(periodo["cash_in"], Decimal("0.00"))

    def test_16_profitability_historical_contract(self):
        with phase4a_env() as env:
            seed_pos_product(env, stock=20)
            conn = env.connect()
            try:
                conn.execute("UPDATE productos SET precio_compra=40 WHERE id=1")
                conn.commit()
            finally:
                conn.close()
            venta = complete_sale(
                env, [{"producto_id": 1, "cantidad": 1, "precio_unitario": 100}]
            )
            hoy = str(venta.fecha)[:10]
            data = reportes_service(env).reporte_rentabilidad(hoy, hoy)
            self.assertIn(
                data["profitability_contract"], ("ESTIMATED", "LEGACY_UNVERIFIED")
            )
            self.assertNotEqual(data["cost_basis"], "HISTORICAL_SNAPSHOT")

    def test_17_legacy_cost_not_false_exact(self):
        with phase4a_env() as env:
            seed_pos_product(env, stock=20)
            conn = env.connect()
            try:
                conn.execute("UPDATE productos SET precio_compra=40 WHERE id=1")
                conn.commit()
            finally:
                conn.close()
            venta = complete_sale(
                env, [{"producto_id": 1, "cantidad": 1, "precio_unitario": 100}]
            )
            conn = env.connect()
            try:
                conn.execute("UPDATE productos SET precio_compra=90 WHERE id=1")
                conn.commit()
            finally:
                conn.close()
            hoy = str(venta.fecha)[:10]
            data = reportes_service(env).reporte_rentabilidad(hoy, hoy)
            self.assertEqual(data["cost_basis"], "LEGACY_UNVERIFIED")
            self.assertEqual(data["profitability_contract"], "ESTIMATED")
            self.assertEqual(data["costo_ventas"], Decimal("90.00"))

    def test_18_decimal_exactness(self):
        with phase4a_env() as env:
            seed_pos_product(env, stock=20)
            conn = env.connect()
            try:
                conn.execute(
                    """
                    INSERT INTO ventas (
                        numero_factura, fecha, subtotal, descuento, iva, total,
                        metodo_pago, estado, estado_pago, monto_pagado
                    ) VALUES (?, ?, ?, 0, 0, ?, 'EFECTIVO', 'COMPLETADA', 'PAGADO', ?)
                    """,
                    ("F-DEC", "2026-08-16 12:00:00", "10.10", "10.10", "10.10"),
                )
                conn.commit()
            finally:
                conn.close()
            resumen = reportes_service(env).reporte_ventas_periodo(
                "2026-08-16", "2026-08-16"
            )["resumen"]
            self.assertIsInstance(resumen["gross_sales"], Decimal)
            self.assertIsInstance(resumen["net_sales"], Decimal)
            self.assertEqual(resumen["gross_sales"], Decimal("10.10"))
            self.assertNotIsInstance(resumen["gross_sales"], float)

    def test_19_cost_column_does_not_claim_unimplemented_snapshot(self):
        with phase4a_env() as env:
            seed_pos_product(env, stock=20)
            venta = complete_sale(
                env, [{"producto_id": 1, "cantidad": 1, "precio_unitario": 100}]
            )
            conn = env.connect()
            try:
                conn.execute("ALTER TABLE detalle_ventas ADD COLUMN costo_unitario TEXT")
                conn.execute("UPDATE detalle_ventas SET costo_unitario='40.00'")
                conn.commit()
            finally:
                conn.close()
            hoy = str(venta.fecha)[:10]
            data = reportes_service(env).reporte_rentabilidad(hoy, hoy)
            self.assertEqual(data["cost_basis"], "LEGACY_UNVERIFIED")
            self.assertEqual(data["profitability_contract"], "ESTIMATED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
