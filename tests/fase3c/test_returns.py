# -*- coding: utf-8 -*-
"""Inmutabilidad, customer/void/supplier returns y trazabilidad 3C."""
from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from returns_schema import (
    COMPLETED_IMMUTABLE,
    ESTADO_COMPLETED,
    KIND_CUSTOMER_RETURN,
    KIND_SALE_VOID,
    KIND_SUPPLIER_RETURN,
    ORIGINAL_TIPO_COMPRA,
    ORIGINAL_TIPO_VENTA,
    OVER_RETURN,
    STATUS_FULLY_RETURNED,
    STATUS_PARTIALLY_RETURNED,
    STATUS_VOIDED,
)
from tests.fase0.harness import REPO_FERRETERIA_DB
from tests.fase1e.helpers import insert_usuario, seed_producto, stock_of
from tests.fase1e1.helpers import command_count, load_ops, transport_applied
from tests.fase3c.helpers import (
    assert_not_commercial_db,
    complete_receipt,
    complete_sale,
    phase3c_env,
    returns_service,
)


class ReturnsCoreTest(unittest.TestCase):
    def test_01_completed_sale_immutable(self):
        with phase3c_env() as env:
            assert_not_commercial_db(env)
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            venta = complete_sale(env, [{"producto_id": 1, "cantidad": 5, "precio_unitario": 1000}])
            svc = returns_service(env)
            ok, msg, _ = svc.edit_completed_original(
                original_tipo=ORIGINAL_TIPO_VENTA, original_id=venta.id, cantidad=99
            )
            self.assertFalse(ok)
            self.assertEqual(msg, COMPLETED_IMMUTABLE)
            ok2, msg2, rid = svc.guardar_borrador(
                kind=KIND_CUSTOMER_RETURN,
                original_tipo=ORIGINAL_TIPO_VENTA,
                original_id=venta.id,
                items=[{"producto_id": 1, "cantidad": 2}],
            )
            self.assertTrue(ok2, msg2)
            ok3, msg3, _ = svc.confirmar(
                rid,
                inventory_mode="authoritative",
                inventory_command_id=str(uuid.uuid4()),
                inventory_transport=transport_applied(),
            )
            self.assertTrue(ok3, msg3)
            conn = env.connect()
            try:
                qty = conn.execute(
                    "SELECT cantidad FROM detalle_ventas WHERE venta_id=?",
                    (venta.id,),
                ).fetchone()["cantidad"]
                estado = conn.execute(
                    "SELECT estado FROM ventas WHERE id=?", (venta.id,)
                ).fetchone()["estado"]
            finally:
                conn.close()
            self.assertEqual(float(qty), 5)
            self.assertEqual(estado, "COMPLETADA")

    def test_02_completed_receipt_immutable(self):
        with phase3c_env() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            cid = complete_receipt(env)
            from tests.fase3b.helpers import compras_service
            from services.purchase_cart import COMPLETED_IMMUTABLE as RECEIPT_IMMUTABLE

            ok, msg, _ = compras_service(env).guardar_borrador(
                proveedor_id=1,
                productos=[{"producto_id": 1, "cantidad": 99, "precio_unitario": 10}],
                numero_factura="X",
                compra_id=cid,
            )
            self.assertFalse(ok)
            self.assertEqual(msg, RECEIPT_IMMUTABLE)

    def test_03_customer_partial_return(self):
        with phase3c_env() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                env.insert_producto(
                    conn, producto_id=2, nombre="B", stock=10, codigo="B",
                    local_id=str(uuid.uuid4()), precio_venta=500,
                )
                conn.commit()
            finally:
                conn.close()
            venta = complete_sale(
                env,
                [
                    {"producto_id": 1, "cantidad": 5, "precio_unitario": 1000},
                    {"producto_id": 2, "cantidad": 2, "precio_unitario": 500},
                ],
            )
            svc = returns_service(env)
            command_id = str(uuid.uuid4())
            ok, msg, rid = svc.guardar_borrador(
                kind=KIND_CUSTOMER_RETURN,
                original_tipo=ORIGINAL_TIPO_VENTA,
                original_id=venta.id,
                items=[{"producto_id": 1, "cantidad": 2}],
            )
            self.assertTrue(ok, msg)
            ok2, msg2, _ = svc.confirmar(
                rid,
                inventory_mode="authoritative",
                inventory_command_id=command_id,
                inventory_transport=transport_applied(),
            )
            self.assertTrue(ok2, msg2)
            conn = env.connect()
            try:
                ops = load_ops(conn, command_id)
                self.assertEqual(len(ops), 1)
                self.assertEqual(int(ops[0]["delta_scaled"]), 2000)
                estado = conn.execute(
                    "SELECT estado FROM reversal_documents WHERE id=?", (rid,)
                ).fetchone()["estado"]
                self.assertEqual(estado, ESTADO_COMPLETED)
            finally:
                conn.close()
            self.assertEqual(
                svc.derived_status(
                    original_tipo=ORIGINAL_TIPO_VENTA, original_id=venta.id
                ),
                STATUS_PARTIALLY_RETURNED,
            )

    def test_04_customer_full_return(self):
        with phase3c_env() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            venta = complete_sale(env)
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
                inventory_transport=transport_applied(),
            )
            self.assertTrue(ok2, msg2)
            self.assertEqual(
                svc.derived_status(
                    original_tipo=ORIGINAL_TIPO_VENTA, original_id=venta.id
                ),
                STATUS_FULLY_RETURNED,
            )

    def test_05_cannot_over_return_sale(self):
        with phase3c_env() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            venta = complete_sale(env)
            svc = returns_service(env)
            ok, msg, _ = svc.guardar_borrador(
                kind=KIND_CUSTOMER_RETURN,
                original_tipo=ORIGINAL_TIPO_VENTA,
                original_id=venta.id,
                items=[{"producto_id": 1, "cantidad": 6}],
            )
            self.assertFalse(ok)
            self.assertIn(OVER_RETURN, msg)

    def test_06_prior_returns_reduce_available(self):
        with phase3c_env() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            venta = complete_sale(env)
            svc = returns_service(env)
            ok, msg, rid = svc.guardar_borrador(
                kind=KIND_CUSTOMER_RETURN,
                original_tipo=ORIGINAL_TIPO_VENTA,
                original_id=venta.id,
                items=[{"producto_id": 1, "cantidad": 2}],
            )
            self.assertTrue(ok, msg)
            self.assertTrue(
                svc.confirmar(
                    rid,
                    inventory_mode="authoritative",
                    inventory_command_id=str(uuid.uuid4()),
                    inventory_transport=transport_applied(),
                )[0]
            )
            ok2, msg2, _ = svc.guardar_borrador(
                kind=KIND_CUSTOMER_RETURN,
                original_tipo=ORIGINAL_TIPO_VENTA,
                original_id=venta.id,
                items=[{"producto_id": 1, "cantidad": 4}],
            )
            self.assertFalse(ok2)
            self.assertIn(OVER_RETURN, msg2)
            preview = svc.preview(
                original_tipo=ORIGINAL_TIPO_VENTA, original_id=venta.id
            )
            self.assertEqual(float(preview["lines"][0]["available_qty"]), 3)

    def test_07_sale_void_explicit_reverse(self):
        with phase3c_env() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            venta = complete_sale(env, [{"producto_id": 1, "cantidad": 5, "precio_unitario": 1000}])
            svc = returns_service(env)
            command_id = str(uuid.uuid4())
            ok, msg, rid = svc.guardar_borrador(
                kind=KIND_SALE_VOID,
                original_tipo=ORIGINAL_TIPO_VENTA,
                original_id=venta.id,
            )
            self.assertTrue(ok, msg)
            ok2, msg2, _ = svc.confirmar(
                rid,
                inventory_mode="authoritative",
                inventory_command_id=command_id,
                inventory_transport=transport_applied(),
            )
            self.assertTrue(ok2, msg2)
            conn = env.connect()
            try:
                ops = load_ops(conn, command_id)
                self.assertEqual(int(ops[0]["delta_scaled"]), 5000)
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0], 1
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT estado FROM ventas WHERE id=?", (venta.id,)
                    ).fetchone()["estado"],
                    "COMPLETADA",
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT kind FROM reversal_documents WHERE id=?", (rid,)
                    ).fetchone()["kind"],
                    KIND_SALE_VOID,
                )
            finally:
                conn.close()
            self.assertEqual(
                svc.derived_status(
                    original_tipo=ORIGINAL_TIPO_VENTA, original_id=venta.id
                ),
                STATUS_VOIDED,
            )

    def test_08_void_after_partial_return_uses_net(self):
        with phase3c_env() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            venta = complete_sale(env)
            svc = returns_service(env)
            ok, msg, rid = svc.guardar_borrador(
                kind=KIND_CUSTOMER_RETURN,
                original_tipo=ORIGINAL_TIPO_VENTA,
                original_id=venta.id,
                items=[{"producto_id": 1, "cantidad": 2}],
            )
            self.assertTrue(ok, msg)
            self.assertTrue(
                svc.confirmar(
                    rid,
                    inventory_mode="authoritative",
                    inventory_command_id=str(uuid.uuid4()),
                    inventory_transport=transport_applied(),
                )[0]
            )
            command_id = str(uuid.uuid4())
            ok2, msg2, rid2 = svc.guardar_borrador(
                kind=KIND_SALE_VOID,
                original_tipo=ORIGINAL_TIPO_VENTA,
                original_id=venta.id,
            )
            self.assertTrue(ok2, msg2)
            ok3, msg3, _ = svc.confirmar(
                rid2,
                inventory_mode="authoritative",
                inventory_command_id=command_id,
                inventory_transport=transport_applied(),
            )
            self.assertTrue(ok3, msg3)
            conn = env.connect()
            try:
                ops = load_ops(conn, command_id)
                self.assertEqual(int(ops[0]["delta_scaled"]), 3000)
            finally:
                conn.close()

    def test_09_supplier_partial_return(self):
        with phase3c_env() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            cid = complete_receipt(
                env, [{"producto_id": 1, "cantidad": 10, "precio_unitario": 50}]
            )
            svc = returns_service(env)
            command_id = str(uuid.uuid4())
            ok, msg, rid = svc.guardar_borrador(
                kind=KIND_SUPPLIER_RETURN,
                original_tipo=ORIGINAL_TIPO_COMPRA,
                original_id=cid,
                items=[{"producto_id": 1, "cantidad": 3}],
            )
            self.assertTrue(ok, msg)
            ok2, msg2, _ = svc.confirmar(
                rid,
                inventory_mode="authoritative",
                inventory_command_id=command_id,
                inventory_transport=transport_applied(),
            )
            self.assertTrue(ok2, msg2)
            conn = env.connect()
            try:
                ops = load_ops(conn, command_id)
                self.assertEqual(int(ops[0]["delta_scaled"]), -3000)
            finally:
                conn.close()

    def test_10_cannot_over_return_receipt(self):
        with phase3c_env() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            cid = complete_receipt(env)
            svc = returns_service(env)
            ok, msg, rid = svc.guardar_borrador(
                kind=KIND_SUPPLIER_RETURN,
                original_tipo=ORIGINAL_TIPO_COMPRA,
                original_id=cid,
                items=[{"producto_id": 1, "cantidad": 4}],
            )
            self.assertTrue(ok, msg)
            self.assertTrue(
                svc.confirmar(
                    rid,
                    inventory_mode="authoritative",
                    inventory_command_id=str(uuid.uuid4()),
                    inventory_transport=transport_applied(),
                )[0]
            )
            ok2, msg2, _ = svc.guardar_borrador(
                kind=KIND_SUPPLIER_RETURN,
                original_tipo=ORIGINAL_TIPO_COMPRA,
                original_id=cid,
                items=[{"producto_id": 1, "cantidad": 7}],
            )
            self.assertFalse(ok2)
            self.assertIn(OVER_RETURN, msg2)

    def test_11_supplier_return_insufficient_stock_no_document(self):
        from tests.fase1e1.helpers import transport_rejected

        with phase3c_env() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            cid = complete_receipt(env)
            svc = returns_service(env)
            ok, msg, rid = svc.guardar_borrador(
                kind=KIND_SUPPLIER_RETURN,
                original_tipo=ORIGINAL_TIPO_COMPRA,
                original_id=cid,
                items=[{"producto_id": 1, "cantidad": 5}],
            )
            self.assertTrue(ok, msg)
            ok2, msg2, _ = svc.confirmar(
                rid,
                inventory_mode="authoritative",
                inventory_command_id=str(uuid.uuid4()),
                inventory_transport=transport_rejected("INSUFFICIENT_STOCK"),
            )
            self.assertFalse(ok2)
            self.assertIn("INSUFFICIENT_STOCK", msg2)
            conn = env.connect()
            try:
                estado = conn.execute(
                    "SELECT estado FROM reversal_documents WHERE id=?", (rid,)
                ).fetchone()["estado"]
                self.assertNotEqual(estado, ESTADO_COMPLETED)
            finally:
                conn.close()

    def test_21_original_reversal_traceability(self):
        with phase3c_env() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            venta = complete_sale(env)
            svc = returns_service(env)
            ok, msg, rid = svc.guardar_borrador(
                kind=KIND_CUSTOMER_RETURN,
                original_tipo=ORIGINAL_TIPO_VENTA,
                original_id=venta.id,
                items=[{"producto_id": 1, "cantidad": 1}],
            )
            self.assertTrue(ok, msg)
            self.assertTrue(
                svc.confirmar(
                    rid,
                    inventory_mode="authoritative",
                    inventory_command_id=str(uuid.uuid4()),
                    inventory_transport=transport_applied(),
                )[0]
            )
            conn = env.connect()
            try:
                doc = conn.execute(
                    "SELECT * FROM reversal_documents WHERE id=?", (rid,)
                ).fetchone()
                self.assertEqual(doc["original_id"], venta.id)
                self.assertEqual(doc["original_tipo"], ORIGINAL_TIPO_VENTA)
                self.assertTrue(doc["local_id"])
                self.assertTrue(doc["inventory_command_id"])
                self.assertEqual(doc["estado"], ESTADO_COMPLETED)
                rev = conn.execute(
                    "SELECT id FROM reversal_documents WHERE original_id=? AND original_tipo=?",
                    (venta.id, ORIGINAL_TIPO_VENTA),
                ).fetchone()
                self.assertEqual(rev["id"], rid)
            finally:
                conn.close()

    def test_original_command_id_durable_from_ledger(self):
        """3A no escribe ventas.inventory_command_id; el UUID del ledger sí basta."""
        with phase3c_env() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            venta = complete_sale(env)
            conn = env.connect()
            try:
                header = dict(
                    conn.execute(
                        "SELECT local_id, inventory_command_id FROM ventas WHERE id=?",
                        (venta.id,),
                    ).fetchone()
                )
                self.assertTrue(header["local_id"])
                self.assertFalse(header["inventory_command_id"])
                ledger = conn.execute(
                    """
                    SELECT command_id FROM inventory_commands
                     WHERE documento_local_id = ? AND estado = 'APPLIED'
                       AND tipo IN ('VENTA', 'COMPRA', 'RECEPCION')
                    """,
                    (header["local_id"],),
                ).fetchone()
                self.assertIsNotNone(ledger)
                sale_cmd = str(ledger["command_id"])
                uuid.UUID(sale_cmd)
                self.assertNotEqual(sale_cmd, str(venta.id))
                svc = returns_service(env)
                recovered = svc._original_command_id(
                    conn, {"original_tipo": ORIGINAL_TIPO_VENTA, "original_id": venta.id},
                    header["local_id"],
                )
                self.assertEqual(recovered, sale_cmd)
            finally:
                conn.close()
            restarted = returns_service(env)
            conn = env.connect()
            try:
                again = restarted._original_command_id(
                    conn,
                    {"original_tipo": ORIGINAL_TIPO_VENTA, "original_id": venta.id},
                    header["local_id"],
                )
            finally:
                conn.close()
            self.assertEqual(again, sale_cmd)

    def test_24_commercial_db_untouched(self):
        before = None
        if REPO_FERRETERIA_DB.exists():
            before = REPO_FERRETERIA_DB.stat().st_mtime
        with phase3c_env() as env:
            assert_not_commercial_db(env)
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            complete_sale(env, [{"producto_id": 1, "cantidad": 1, "precio_unitario": 10}])
        if before is not None:
            self.assertEqual(REPO_FERRETERIA_DB.stat().st_mtime, before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
