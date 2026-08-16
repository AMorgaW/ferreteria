# -*- coding: utf-8 -*-
"""Draft, confirmación, atomicidad, idempotencia y recovery 3B."""
from __future__ import annotations

import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.purchase_cart import COMPLETED_IMMUTABLE, ESTADO_COMPLETADA, ESTADO_DRAFT, PurchaseCart
from tests.fase0.harness import official_temp_db
from tests.fase1e.helpers import insert_usuario, seed_producto, stock_of
from tests.fase1e1.helpers import command_count, load_ops, transport_applied, transport_rejected, transport_unknown
from tests.fase3b.helpers import assert_not_commercial_db, compras_service, phase3b_env, seed_purchase_product


class ReceivingCheckoutTest(unittest.TestCase):
    def test_02_draft_does_not_change_inventory(self):
        with phase3b_env() as env:
            assert_not_commercial_db(env)
            pid, _lid, _p = seed_purchase_product(env, stock=80)
            conn = env.connect()
            try:
                env.insert_proveedor(conn)
                conn.commit()
            finally:
                conn.close()
            svc = compras_service(env)
            ok, msg, cid = svc.guardar_borrador(
                proveedor_id=1,
                productos=[{"producto_id": pid, "cantidad": 20, "precio_unitario": 100}],
                numero_factura="DRAFT-1",
            )
            self.assertTrue(ok, msg)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn, pid), 80)
                estado = conn.execute(
                    "SELECT estado FROM compras WHERE id=?", (cid,)
                ).fetchone()["estado"]
                self.assertEqual(estado, ESTADO_DRAFT)
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM movimientos").fetchone()[0], 0
                )
            finally:
                conn.close()

    def test_12_explicit_confirmation_increments(self):
        with phase3b_env() as env:
            pid, _lid, _p = seed_purchase_product(env, stock=80)
            conn = env.connect()
            try:
                env.insert_proveedor(conn)
                conn.commit()
            finally:
                conn.close()
            svc = compras_service(env)
            command_id = str(uuid.uuid4())
            ok, msg, cid = svc.confirmar_recepcion(
                proveedor_id=1,
                productos=[{"producto_id": pid, "cantidad": 20, "precio_unitario": 100}],
                numero_factura="CONF-1",
                inventory_mode="authoritative",
                inventory_command_id=command_id,
                inventory_transport=transport_applied(),
            )
            self.assertTrue(ok, msg)
            conn = env.connect()
            try:
                estado = conn.execute(
                    "SELECT estado FROM compras WHERE id=?", (cid,)
                ).fetchone()["estado"]
                self.assertEqual(estado, ESTADO_COMPLETADA)
                ops = load_ops(conn, command_id)
                self.assertEqual(len(ops), 1)
                self.assertEqual(int(ops[0]["delta_scaled"]), 20000)
            finally:
                conn.close()

    def test_13_duplicate_confirm_protection_on_cart(self):
        cart = PurchaseCart()
        cart.lines.append(
            {
                "producto": {"id": 1, "nombre": "X"},
                "cantidad_presentacion": Decimal("1"),
                "cantidad": Decimal("1"),
                "precio_unitario": Decimal("100"),
            }
        )
        self.assertTrue(cart.begin_confirm())
        self.assertFalse(cart.begin_confirm())
        cart.end_confirm()
        self.assertTrue(cart.begin_confirm())

    def test_14_exact_inventory_increment_ops(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=80)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = compras_service(env)
            command_id = str(uuid.uuid4())
            ok, msg, _cid = svc.confirmar_recepcion(
                proveedor_id=1,
                productos=[{"producto_id": 1, "cantidad": 20, "precio_unitario": 50}],
                numero_factura="INC-1",
                inventory_mode="authoritative",
                inventory_command_id=command_id,
                inventory_transport=transport_applied(),
            )
            self.assertTrue(ok, msg)
            conn = env.connect()
            try:
                ops = load_ops(conn, command_id)
                self.assertEqual(int(ops[0]["delta_scaled"]), 20000)
            finally:
                conn.close()

    def test_15_multi_line_atomicity(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10, producto_id=1)
                env.insert_producto(
                    conn,
                    producto_id=2,
                    nombre="Producto B",
                    stock=10,
                    codigo="PROD-B",
                    precio_venta=1000,
                    local_id=str(uuid.uuid4()),
                )
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = compras_service(env)
            ok, _msg, cid = svc.confirmar_recepcion(
                proveedor_id=1,
                productos=[
                    {"producto_id": 1, "cantidad": 10, "precio_unitario": 100},
                    {"producto_id": 2, "cantidad": 5, "precio_unitario": 100},
                ],
                numero_factura="ATOM-1",
                inventory_mode="authoritative",
                inventory_command_id=str(uuid.uuid4()),
                inventory_transport=transport_rejected("INVALID_LINE_B"),
            )
            self.assertFalse(ok)
            self.assertIsNone(cid)
            conn = env.connect()
            try:
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM compras WHERE estado=?",
                        (ESTADO_COMPLETADA,),
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(stock_of(conn, 1), 10)
                self.assertEqual(stock_of(conn, 2), 10)
            finally:
                conn.close()

    def test_16_idempotent_retry_one_receipt(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=80)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = compras_service(env)
            command_id = str(uuid.uuid4())
            items = [{"producto_id": 1, "cantidad": 10, "precio_unitario": 50}]
            transport = transport_applied()
            ok1, msg1, cid1 = svc.confirmar_recepcion(
                proveedor_id=1,
                productos=items,
                numero_factura="IDEM-1",
                inventory_mode="authoritative",
                inventory_command_id=command_id,
                inventory_transport=transport,
            )
            self.assertTrue(ok1, msg1)
            ok2, msg2, cid2 = svc.confirmar_recepcion(
                compra_id=cid1,
                inventory_mode="authoritative",
                inventory_command_id=command_id,
                inventory_transport=transport,
            )
            self.assertTrue(ok2, msg2)
            self.assertEqual(cid1, cid2)
            conn = env.connect()
            try:
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM compras WHERE estado=?",
                        (ESTADO_COMPLETADA,),
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(command_count(conn), 1)
                ops = load_ops(conn, command_id)
                self.assertEqual(len(ops), 1)
                self.assertEqual(int(ops[0]["delta_scaled"]), 10000)
            finally:
                conn.close()

    def test_17_recovery_after_lost_response(self):
        import inventory_writer_support as iws

        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=80)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = compras_service(env)
            command_id = str(uuid.uuid4())

            def crash(_cid):
                raise RuntimeError("crash after apply")

            iws.after_remote_apply_hook = crash
            try:
                ok, msg, cid = svc.confirmar_recepcion(
                    proveedor_id=1,
                    productos=[{"producto_id": 1, "cantidad": 10, "precio_unitario": 50}],
                    numero_factura="REC-1",
                    inventory_mode="authoritative",
                    inventory_command_id=command_id,
                    inventory_transport=transport_applied(),
                )
            finally:
                iws.after_remote_apply_hook = None
            self.assertFalse(ok)
            self.assertIn("INVENTORY_UNKNOWN", msg)
            conn = env.connect()
            try:
                estado = conn.execute(
                    "SELECT estado FROM compras WHERE inventory_command_id=?",
                    (command_id,),
                ).fetchone()
                self.assertIsNotNone(estado)
                self.assertEqual(estado["estado"], ESTADO_DRAFT)
                draft_id = conn.execute(
                    "SELECT id FROM compras WHERE inventory_command_id=?",
                    (command_id,),
                ).fetchone()["id"]
            finally:
                conn.close()
            ok2, msg2, cid2 = svc.confirmar_recepcion(
                compra_id=draft_id,
                inventory_mode="authoritative",
                inventory_command_id=command_id,
                inventory_transport=transport_applied(),
            )
            self.assertTrue(ok2, msg2)
            conn = env.connect()
            try:
                self.assertEqual(
                    conn.execute(
                        "SELECT estado FROM compras WHERE id=?", (cid2,)
                    ).fetchone()["estado"],
                    ESTADO_COMPLETADA,
                )
                self.assertEqual(command_count(conn), 1)
                ops = load_ops(conn, command_id)
                self.assertEqual(len(ops), 1)
                self.assertEqual(int(ops[0]["delta_scaled"]), 10000)
            finally:
                conn.close()

    def test_19_offline_draft_allowed(self):
        from services.purchase_cart import OFFLINE_FINALIZE_BLOCKED, receipt_finalize_allowed

        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = compras_service(env)
            ok, msg, cid = svc.guardar_borrador(
                proveedor_id=1,
                productos=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 10}],
                numero_factura="OFF-1",
            )
            self.assertTrue(ok, msg)
            allowed, reason = receipt_finalize_allowed(
                env.db, inventory_mode="authoritative"
            )
            self.assertFalse(allowed)
            self.assertEqual(reason, OFFLINE_FINALIZE_BLOCKED)

    def test_21_completed_receipt_immutable(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = compras_service(env)
            ok, msg, cid = svc.confirmar_recepcion(
                proveedor_id=1,
                productos=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 10}],
                numero_factura="IMM-1",
                inventory_mode="authoritative",
                inventory_command_id=str(uuid.uuid4()),
                inventory_transport=transport_applied(),
            )
            self.assertTrue(ok, msg)
            ok2, msg2, _ = svc.guardar_borrador(
                proveedor_id=1,
                productos=[{"producto_id": 1, "cantidad": 99, "precio_unitario": 10}],
                numero_factura="IMM-1",
                compra_id=cid,
            )
            self.assertFalse(ok2)
            self.assertIn("COMPLETED", msg2)
            ok3, msg3 = svc.eliminar_borrador(cid)
            self.assertFalse(ok3)
            self.assertEqual(msg3, COMPLETED_IMMUTABLE)

    def test_22_commercial_db_untouched(self):
        from tests.fase0.harness import REPO_FERRETERIA_DB

        with official_temp_db() as env:
            assert_not_commercial_db(env)
            self.assertNotEqual(Path(env.db_path).resolve(), REPO_FERRETERIA_DB.resolve())


if __name__ == "__main__":
    unittest.main(verbosity=2)
