# -*- coding: utf-8 -*-
"""Inventario reporting: no productos.stock como autoridad; SCALE=1000."""
from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from inventory_ledger import QUANTITY_SCALE, scaled_to_decimal
from services.alertas_service import AlertasService
from tests.fase0.harness import REPO_FERRETERIA_DB
from tests.fase1e.helpers import insert_usuario
from tests.fase4a.helpers import (
    assert_not_commercial_db,
    commercial_db_mtime,
    ensure_inventory_balance,
    phase4a_env,
    reportes_service,
    seed_pos_product,
)


class InventoryReportingTest(unittest.TestCase):
    def test_01_inventory_ignores_productos_stock(self):
        with phase4a_env() as env:
            assert_not_commercial_db(env)
            pid, lid, _p = seed_pos_product(env, stock=10, name="Clavo")
            conn = env.connect()
            try:
                conn.execute(
                    "UPDATE productos SET stock_minimo=5, precio_compra=100 WHERE id=?",
                    (pid,),
                )
                ensure_inventory_balance(conn, lid, 2000)
                conn.commit()
            finally:
                conn.close()
            svc = reportes_service(env)
            rows = svc.reporte_inventario_actual()
            item = next(row for row in rows if row["id"] == pid)
            self.assertEqual(item["quantity_source"], "inventory_balances")
            self.assertEqual(item["quantity_scaled"], 2000)
            self.assertEqual(item["cantidad_actual"], Decimal("2"))
            self.assertNotEqual(item["cantidad_actual"], Decimal("10"))
            self.assertEqual(item["stock"], Decimal("2"))

    def test_02_stock_critico_uses_canonical_source(self):
        with phase4a_env() as env:
            pid, lid, _p = seed_pos_product(env, stock=80, name="Tornillo")
            conn = env.connect()
            try:
                conn.execute(
                    "UPDATE productos SET stock_minimo=5, precio_compra=50 WHERE id=?",
                    (pid,),
                )
                ensure_inventory_balance(conn, lid, 3000)
                conn.commit()
            finally:
                conn.close()
            svc = reportes_service(env)
            dash = svc.dashboard_principal()
            criticos = svc.productos_stock_critico()
            self.assertEqual(dash["stock_critico"], len(criticos))
            self.assertEqual(len(criticos), 1)
            self.assertEqual(criticos[0]["id"], pid)
            self.assertEqual(criticos[0]["stock_actual"], Decimal("3"))
            self.assertEqual(criticos[0]["quantity_source"], "inventory_balances")

    def test_03_scale_1000_exact_no_double_scaling(self):
        self.assertEqual(QUANTITY_SCALE, 1000)
        self.assertEqual(scaled_to_decimal(1500), Decimal("1.5"))
        self.assertEqual(scaled_to_decimal(1), Decimal("0.001"))
        self.assertEqual(scaled_to_decimal(1000), Decimal("1"))
        with phase4a_env() as env:
            pid, lid, _p = seed_pos_product(env, stock=9, name="Arandela")
            conn = env.connect()
            try:
                conn.execute(
                    "UPDATE productos SET stock_minimo=0, precio_compra=10 WHERE id=?",
                    (pid,),
                )
                ensure_inventory_balance(conn, lid, 1500)
                conn.commit()
            finally:
                conn.close()
            item = next(
                row
                for row in reportes_service(env).reporte_inventario_actual()
                if row["id"] == pid
            )
            self.assertEqual(item["cantidad_actual"], Decimal("1.5"))
            self.assertNotEqual(item["cantidad_actual"], Decimal("1500"))
            self.assertNotEqual(item["cantidad_actual"], Decimal("1500000"))

    def test_22_local_first_no_network(self):
        with phase4a_env() as env:
            pid, lid, _p = seed_pos_product(env, stock=4)
            conn = env.connect()
            try:
                ensure_inventory_balance(conn, lid, 4000)
                conn.commit()
            finally:
                conn.close()

            def boom(*_a, **_k):
                raise AssertionError("network")

            with mock.patch("psycopg2.connect", side_effect=boom):
                rows = reportes_service(env).reporte_inventario_actual()
            item = next(row for row in rows if row["id"] == pid)
            self.assertEqual(item["cantidad_actual"], Decimal("4"))

    def test_24_commercial_db_untouched(self):
        before = commercial_db_mtime()
        with phase4a_env() as env:
            assert_not_commercial_db(env)
            conn = env.connect()
            try:
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            reportes_service(env).reporte_inventario_actual()
            self.assertNotEqual(Path(env.db_path).resolve(), REPO_FERRETERIA_DB.resolve())
        if REPO_FERRETERIA_DB.exists():
            self.assertEqual(REPO_FERRETERIA_DB.stat().st_mtime, before)

    def test_25_legacy_fallback_is_explicit_even_without_critical_rows(self):
        with phase4a_env() as env:
            pid, _lid, _p = seed_pos_product(env, stock=9, name="Legacy")
            conn = env.connect()
            try:
                conn.execute("UPDATE productos SET stock_minimo=1 WHERE id=?", (pid,))
                conn.commit()
            finally:
                conn.close()
            svc = reportes_service(env)
            item = next(row for row in svc.reporte_inventario_actual() if row["id"] == pid)
            self.assertEqual(item["cantidad_actual"], Decimal("9"))
            self.assertEqual(item["quantity_source"], "LEGACY_PROJECTION")
            self.assertEqual(svc.dashboard_principal()["stock_critico_source"], "LEGACY_PROJECTION")

    def test_26_alert_writer_uses_canonical_critical_quantity(self):
        with phase4a_env() as env:
            pid, lid, _p = seed_pos_product(env, stock=80, name="Canónico")
            conn = env.connect()
            try:
                conn.execute("UPDATE productos SET stock_minimo=5 WHERE id=?", (pid,))
                ensure_inventory_balance(conn, lid, 3000)
                conn.commit()
            finally:
                conn.close()
            service = AlertasService(env.db, productos_repo=None, clientes_repo=None)
            self.assertEqual(service.verificar_stock_bajo(), 1)
            conn = env.connect()
            try:
                alerta = conn.execute(
                    "SELECT mensaje FROM alertas WHERE relacionado_id=?", (pid,)
                ).fetchone()
            finally:
                conn.close()
            self.assertIn("stock 3", alerta["mensaje"])
            self.assertNotIn("stock 80", alerta["mensaje"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
