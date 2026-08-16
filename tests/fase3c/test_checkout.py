# -*- coding: utf-8 -*-
"""Atomicidad, idempotencia, recovery y gate ONLINE 3C."""
from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from returns_schema import (
    ESTADO_COMPLETED,
    KIND_CUSTOMER_RETURN,
    ORIGINAL_TIPO_VENTA,
)
from services.pos_cart import OFFLINE_FINALIZE_BLOCKED
from services.return_cart import ReturnCart, return_finalize_allowed
from tests.fase1e.helpers import insert_usuario, seed_producto
from tests.fase1e1.helpers import (
    command_count,
    load_ops,
    transport_applied,
    transport_rejected,
    transport_unknown,
)
from tests.fase3c.helpers import complete_sale, phase3c_env, returns_service


class ReturnsCheckoutTest(unittest.TestCase):
    def test_15_multi_line_atomicity(self):
        with phase3c_env() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10, producto_id=1)
                env.insert_producto(
                    conn, producto_id=2, nombre="B", stock=10, codigo="B",
                    local_id=str(uuid.uuid4()),
                )
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            venta = complete_sale(
                env,
                [
                    {"producto_id": 1, "cantidad": 1, "precio_unitario": 10},
                    {"producto_id": 2, "cantidad": 1, "precio_unitario": 10},
                ],
            )
            svc = returns_service(env)
            ok, msg, rid = svc.guardar_borrador(
                kind=KIND_CUSTOMER_RETURN,
                original_tipo=ORIGINAL_TIPO_VENTA,
                original_id=venta.id,
            )
            self.assertTrue(ok, msg)
            ok2, msg2, _ = svc.confirmar(
                rid,
                inventory_mode="authoritative",
                inventory_command_id=str(uuid.uuid4()),
                inventory_transport=transport_rejected("INSUFFICIENT_STOCK"),
            )
            self.assertFalse(ok2)
            conn = env.connect()
            try:
                estado = conn.execute(
                    "SELECT estado FROM reversal_documents WHERE id=?", (rid,)
                ).fetchone()["estado"]
                self.assertNotEqual(estado, ESTADO_COMPLETED)
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM movimientos WHERE observaciones=?",
                        (f"Reverso #{rid}",),
                    ).fetchone()[0],
                    0,
                )
            finally:
                conn.close()

    def test_16_idempotent_retry(self):
        with phase3c_env() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            venta = complete_sale(env, [{"producto_id": 1, "cantidad": 1, "precio_unitario": 10}])
            svc = returns_service(env)
            command_id = str(uuid.uuid4())
            transport = transport_applied()
            ok, msg, rid = svc.guardar_borrador(
                kind=KIND_CUSTOMER_RETURN,
                original_tipo=ORIGINAL_TIPO_VENTA,
                original_id=venta.id,
                items=[{"producto_id": 1, "cantidad": 1}],
            )
            self.assertTrue(ok, msg)
            ok1, msg1, _ = svc.confirmar(
                rid,
                inventory_mode="authoritative",
                inventory_command_id=command_id,
                inventory_transport=transport,
            )
            self.assertTrue(ok1, msg1)
            ok2, msg2, _ = svc.confirmar(
                rid,
                inventory_mode="authoritative",
                inventory_command_id=command_id,
                inventory_transport=transport,
            )
            self.assertTrue(ok2, msg2)
            conn = env.connect()
            try:
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM reversal_documents WHERE estado=?",
                        (ESTADO_COMPLETED,),
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(len(load_ops(conn, command_id)), 1)
                self.assertEqual(int(load_ops(conn, command_id)[0]["delta_scaled"]), 1000)
            finally:
                conn.close()

    def test_17_lost_response_recovery(self):
        with phase3c_env() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            venta = complete_sale(env, [{"producto_id": 1, "cantidad": 1, "precio_unitario": 10}])
            svc = returns_service(env)
            command_id = str(uuid.uuid4())
            ok, msg, rid = svc.guardar_borrador(
                kind=KIND_CUSTOMER_RETURN,
                original_tipo=ORIGINAL_TIPO_VENTA,
                original_id=venta.id,
                items=[{"producto_id": 1, "cantidad": 1}],
            )
            self.assertTrue(ok, msg)
            ok1, msg1, _ = svc.confirmar(
                rid,
                inventory_mode="authoritative",
                inventory_command_id=command_id,
                inventory_transport=transport_unknown(),
            )
            self.assertFalse(ok1)
            self.assertIn("INVENTORY_UNKNOWN", msg1)
            self.assertEqual(svc.last_inventory_command_id, command_id)
            ok2, msg2, _ = svc.confirmar(
                rid,
                inventory_mode="authoritative",
                inventory_command_id=command_id,
                inventory_transport=transport_applied(),
            )
            self.assertTrue(ok2, msg2)
            conn = env.connect()
            try:
                self.assertEqual(len(load_ops(conn, command_id)), 1)
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM reversal_documents WHERE estado=?",
                        (ESTADO_COMPLETED,),
                    ).fetchone()[0],
                    1,
                )
            finally:
                conn.close()

    def test_18_duplicate_confirmation(self):
        cart = ReturnCart()
        cart.lines.append(
            {
                "producto_id": 1,
                "available_qty": 1,
                "requested_qty": 1,
                "package_role": "BASE_UNIT",
            }
        )
        self.assertTrue(cart.begin_confirm())
        self.assertFalse(cart.begin_confirm())
        cart.end_confirm()
        self.assertTrue(cart.begin_confirm())

    def test_22_offline_draft_online_commit_gate(self):
        with phase3c_env() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            venta = complete_sale(env, [{"producto_id": 1, "cantidad": 1, "precio_unitario": 10}])
            svc = returns_service(env)
            ok, msg, rid = svc.guardar_borrador(
                kind=KIND_CUSTOMER_RETURN,
                original_tipo=ORIGINAL_TIPO_VENTA,
                original_id=venta.id,
                items=[{"producto_id": 1, "cantidad": 1}],
            )
            self.assertTrue(ok, msg)
            allowed, reason = return_finalize_allowed(
                env.db, inventory_mode="authoritative"
            )
            self.assertFalse(allowed)
            self.assertEqual(reason, OFFLINE_FINALIZE_BLOCKED)


if __name__ == "__main__":
    unittest.main(verbosity=2)
