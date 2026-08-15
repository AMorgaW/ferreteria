# -*- coding: utf-8 -*-
"""1E.4B unitario: Decimal exacto, payload APPLIED, DSN, identidad, CAS sqlite."""
from __future__ import annotations

import os
import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase0.harness import official_temp_db
from tests.fase1e.helpers import insert_usuario, seed_producto, stock_of
from tests.fase1e1.helpers import transport_applied, ventas_service


class SourceGuardTest(unittest.TestCase):
    def test_cutover_does_not_use_float_stock_times_scale(self):
        src = (REPO_ROOT / "inventory_cutover.py").read_text(encoding="utf-8")
        self.assertNotIn("float(stock or 0)", src)
        self.assertNotIn("round(float(stock", src)
        self.assertNotIn("except Exception:\n            active = 0", src)
        self.assertIn("lock_legacy_cutover_fence", src)
        self.assertIn(
            "REVOKE INSERT, UPDATE, DELETE ON TABLE public.inventory_cutover_control",
            src,
        )

    def test_apply_authoritative_exclude_remains_false_in_source(self):
        from sync_registry import APPLY_AUTHORITATIVE_EXCLUDE
        from inventory_gateway import INVENTORY_CUTOVER_ENABLED

        self.assertFalse(INVENTORY_CUTOVER_ENABLED)
        self.assertFalse(APPLY_AUTHORITATIVE_EXCLUDE)


class ExactFixedPointTest(unittest.TestCase):
    def test_seed_exact_decimal_9007199254740_993(self):
        from inventory_cutover import legacy_stock_to_scaled

        exact = legacy_stock_to_scaled(Decimal("9007199254740.993"))
        self.assertEqual(exact, 9007199254740993)
        float_bug = int(round(float(9007199254740.993) * 1000))
        self.assertNotEqual(float_bug, 9007199254740993)
        self.assertNotEqual(exact, 9007199254740992)

    def test_seed_more_than_three_decimals_rejected(self):
        from inventory_cutover import legacy_stock_to_scaled
        from inventory_ledger import QuantityScaleError

        with self.assertRaises(QuantityScaleError):
            legacy_stock_to_scaled(Decimal("1.2345"))
        with self.assertRaises(QuantityScaleError):
            legacy_stock_to_scaled("10.0001")

    def test_bigint_boundary(self):
        from inventory_cutover import legacy_stock_to_scaled
        from inventory_ledger import (
            QUANTITY_SCALE,
            QuantityScaleError,
            SCALED_BIGINT_MAX,
            quantity_to_scaled,
        )

        max_commercial = Decimal(SCALED_BIGINT_MAX) / Decimal(QUANTITY_SCALE)
        self.assertEqual(quantity_to_scaled(max_commercial), SCALED_BIGINT_MAX)
        with self.assertRaises(QuantityScaleError):
            legacy_stock_to_scaled(max_commercial + Decimal("0.001"))
        with self.assertRaises(QuantityScaleError):
            quantity_to_scaled(Decimal("9223372036854776"))

    def test_float_stock_rejected(self):
        from inventory_cutover import legacy_stock_to_scaled
        from inventory_ledger import QuantityScaleError

        with self.assertRaises(QuantityScaleError):
            legacy_stock_to_scaled(9007199254740.993)


class AppliedPayloadConflictUnitTest(unittest.TestCase):
    def test_w06_applied_changed_payload_conflict(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=50)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = ventas_service(env)
            ok, msg, venta = svc.registrar_venta(
                items=[{"producto_id": 1, "cantidad": 2, "precio_unitario": 1000}],
                metodo_pago="CREDITO",
            )
            self.assertTrue(ok, msg)
            cid = str(uuid.uuid4())
            transport = transport_applied()
            ok2, msg2 = svc.agregar_productos_a_factura(
                venta.id,
                [{"producto_id": 1, "cantidad": 3, "precio_unitario": 1000}],
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport,
            )
            self.assertTrue(ok2, msg2)
            stock_after = None
            conn = env.connect()
            try:
                stock_after = stock_of(conn)
            finally:
                conn.close()
            ok3, msg3 = svc.agregar_productos_a_factura(
                venta.id,
                [{"producto_id": 1, "cantidad": 7, "precio_unitario": 1000}],
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport_applied(),
            )
            self.assertFalse(ok3, msg3)
            self.assertIn("APPLIED", msg3.upper() + msg3)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), stock_after)
                n_cmd = conn.execute(
                    "SELECT COUNT(*) FROM inventory_commands WHERE command_id = ?",
                    (cid,),
                ).fetchone()[0]
                self.assertEqual(n_cmd, 1)
            finally:
                conn.close()
            self.assertTrue(
                "distinto" in msg3.lower() or "conflict" in msg3.lower() or "APPLIED" in msg3
            )

    def test_w17_applied_changed_payload_conflict(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=50)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = ventas_service(env)
            ok, msg, venta = svc.registrar_venta(
                items=[{"producto_id": 1, "cantidad": 5, "precio_unitario": 1000}],
                metodo_pago="CREDITO",
            )
            self.assertTrue(ok, msg)
            conn = env.connect()
            try:
                det = conn.execute(
                    "SELECT id FROM detalle_ventas WHERE venta_id = ?", (venta.id,)
                ).fetchone()
                detalle_id = det["id"]
            finally:
                conn.close()
            cid = str(uuid.uuid4())
            ok1, msg1 = svc.editar_linea_factura(
                venta.id,
                detalle_id,
                8,
                1000,
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport_applied(),
            )
            self.assertTrue(ok1, msg1)
            ok2, msg2 = svc.editar_linea_factura(
                venta.id,
                detalle_id,
                2,
                1000,
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport_applied(),
            )
            self.assertFalse(ok2, msg2)
            self.assertTrue(
                "distinto" in msg2.lower() or "APPLIED" in msg2 or "conflict" in msg2.lower()
            )


class MissingDsnOnlineTest(unittest.TestCase):
    def test_missing_dsn_online_fail_closed(self):
        from inventory_cutover import STATION_MODE_ENV
        from inventory_gateway import INVENTORY_DSN_ENV

        env_patch = {
            STATION_MODE_ENV: "ONLINE",
            INVENTORY_DSN_ENV: "",
        }
        with patch.dict(os.environ, env_patch, clear=False):
            os.environ.pop(INVENTORY_DSN_ENV, None)
            with official_temp_db() as env:
                conn = env.connect()
                try:
                    seed_producto(conn, env, stock=50)
                    insert_usuario(conn)
                    conn.commit()
                finally:
                    conn.close()
                svc = ventas_service(env)
                ok, msg, venta = svc.registrar_venta(
                    items=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 1000}],
                )
                self.assertFalse(ok)
                self.assertIsNone(venta)
                self.assertIn("CUTOVER_STATE_UNAVAILABLE", msg)
                conn = env.connect()
                try:
                    self.assertEqual(stock_of(conn), 50)
                    self.assertEqual(
                        conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0], 0
                    )
                finally:
                    conn.close()


class ClassifyProductSetsUnitTest(unittest.TestCase):
    def test_classify_detects_null_invalid_duplicate_and_both_directions(self):
        from inventory_cutover import _classify_product_rows

        lid_a = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        lid_b = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        sqlite_rows = [
            {"id": 1, "local_id": lid_a, "activo": 1, "is_deleted": 0, "stock": "10"},
            {"id": 2, "local_id": None, "activo": 1, "is_deleted": 0, "stock": "1"},
            {"id": 3, "local_id": "not-a-uuid", "activo": 1, "is_deleted": 0, "stock": "1"},
            {"id": 4, "local_id": lid_a, "activo": 1, "is_deleted": 0, "stock": "10"},
        ]
        local = _classify_product_rows(sqlite_rows, sqlite=True)
        self.assertIn(lid_a, local["valid"])
        self.assertTrue(local["null"])
        self.assertIn("not-a-uuid", local["invalid"])
        self.assertIn(lid_a, local["duplicates"])

        pg_rows = [
            (10, lid_a, True, False, "10"),
            (11, lid_b, True, False, "4"),
        ]
        remote = _classify_product_rows(pg_rows, sqlite=False)
        self.assertIn(lid_b, remote["valid"])
        self.assertNotIn(lid_b, local["valid"])

    def test_w01_open_act_survives_new_connection_without_command_id(self):
        from inventory_cutover import (
            ACT_KIND_PURCHASE_CREATE,
            begin_or_resume_open_act,
            purchase_create_fingerprint,
        )

        productos = [{"producto_id": 1, "cantidad": 2, "precio_unitario": 10}]
        fp = purchase_create_fingerprint(1, "FAC-1E4B", productos)
        with official_temp_db() as env:
            conn = env.connect()
            try:
                first = begin_or_resume_open_act(
                    conn, ACT_KIND_PURCHASE_CREATE, fingerprint=fp
                )
            finally:
                conn.close()
            conn2 = env.connect()
            try:
                resumed = begin_or_resume_open_act(
                    conn2, ACT_KIND_PURCHASE_CREATE, fingerprint=fp
                )
                self.assertEqual(resumed, first)
            finally:
                conn2.close()


class RestartIdentityUnitTest(unittest.TestCase):
    def test_no_new_command_id_after_process_restart_pos(self):
        from inventory_cutover import ACT_KIND_POS_CHECKOUT, begin_or_resume_open_act

        with official_temp_db() as env:
            conn = env.connect()
            try:
                first = begin_or_resume_open_act(conn, ACT_KIND_POS_CHECKOUT)
            finally:
                conn.close()
            conn2 = env.connect()
            try:
                resumed = begin_or_resume_open_act(conn2, ACT_KIND_POS_CHECKOUT)
                self.assertEqual(resumed, first)
            finally:
                conn2.close()


if __name__ == "__main__":
    unittest.main()
