# -*- coding: utf-8 -*-
"""Documentos operacionales 4C: venta, compra, reversos, caja, Decimal, reprint."""
from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from returns_schema import KIND_CUSTOMER_RETURN, KIND_SALE_VOID, KIND_SUPPLIER_RETURN
from services.document_service import (
    NON_FISCAL_LABEL,
    DocumentNotFinal,
    format_money,
    render_operational_text,
)
from tests.fase1e.helpers import insert_usuario
from tests.fase3d.helpers import complete_sale_cash, open_caja
from tests.fase4c.helpers import (
    business_fingerprint,
    complete_receipt,
    complete_sale,
    confirm_return,
    credit_sale,
    docs,
    ensure_proveedor,
    pay_customer,
    pay_supplier,
    phase4c_env,
    seed_cliente,
    seed_ops,
    seed_pos_product,
    seed_purchase_product,
)


def _flat(text: str) -> str:
    return " ".join(text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ").split())


class SaleDocumentTest(unittest.TestCase):
    def test_01_sale_completed_render(self):
        with phase4c_env() as env:
            seed_pos_product(env, stock=20, name="Tornillo")
            venta = complete_sale(
                env,
                [{"producto_id": 1, "cantidad": 2, "precio_unitario": 100.10}],
            )
            doc = docs(env).load_sale(venta.id)
            text = _flat(render_operational_text(doc))
            self.assertEqual(doc.kind, "SALE")
            self.assertTrue(doc.identity)
            self.assertIn("Tornillo", text)
            self.assertIn("100.10", text)
            self.assertIn("200.20", text)
            self.assertIn(NON_FISCAL_LABEL, text)
            self.assertIn("Consumidor final", text)
            self.assertIn("NO FISCAL", text)
            self.assertNotIn("autorización DIAN", text.lower())

    def test_02_sale_draft_not_final(self):
        with phase4c_env() as env:
            seed_pos_product(env, stock=5)
            conn = env.connect()
            try:
                conn.execute(
                    """
                    INSERT INTO ventas (
                        numero_factura, fecha, subtotal, descuento, iva, total,
                        metodo_pago, estado, estado_pago, monto_pagado
                    ) VALUES ('D-1', '2026-08-16 10:00:00', 10, 0, 0, 10,
                              'EFECTIVO', 'DRAFT', 'PENDIENTE', 0)
                    """
                )
                conn.commit()
                draft_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            finally:
                conn.close()
            with self.assertRaises(DocumentNotFinal):
                docs(env).load_sale(draft_id)

    def test_03_sale_durable_prices(self):
        with phase4c_env() as env:
            seed_pos_product(env, stock=20, name="Broca", precio_venta=30)
            venta = complete_sale(
                env, [{"producto_id": 1, "cantidad": 1, "precio_unitario": 30.20}]
            )
            conn = env.connect()
            try:
                conn.execute("UPDATE productos SET precio_venta=9999, stock=0 WHERE id=1")
                conn.commit()
            finally:
                conn.close()
            doc = docs(env).load_sale(venta.numero_factura)
            text = _flat(render_operational_text(doc))
            self.assertIn("30.20", text)
            self.assertNotIn("9999", text)

    def test_04_sale_reprint_no_writes(self):
        with phase4c_env() as env:
            seed_pos_product(env, stock=10)
            venta = complete_sale(
                env, [{"producto_id": 1, "cantidad": 1, "precio_unitario": 50}]
            )
            svc = docs(env)
            before = business_fingerprint(env)
            first = svc.load_sale(venta.id)
            second = svc.load_sale(venta.id)
            after = business_fingerprint(env)
            self.assertEqual(before, after)
            self.assertEqual(first.fingerprint(), second.fingerprint())


class PurchaseDocumentTest(unittest.TestCase):
    def test_06_purchase_completed(self):
        with phase4c_env() as env:
            seed_purchase_product(env, stock=0, precio_compra=40)
            ensure_proveedor(env)
            cid = complete_receipt(
                env,
                [{"producto_id": 1, "cantidad": 3, "precio_unitario": Decimal("69.90")}],
            )
            doc = docs(env).load_purchase(cid)
            text = _flat(render_operational_text(doc))
            self.assertEqual(doc.kind, "PURCHASE")
            self.assertIn("69.90", text)
            self.assertIn("209.70", text)
            self.assertIn(NON_FISCAL_LABEL, text)
            self.assertIn("Mercancía recibida", text)

    def test_07_purchase_draft_excluded(self):
        from tests.fase3b.helpers import compras_service

        with phase4c_env() as env:
            seed_purchase_product(env, stock=0)
            ensure_proveedor(env)
            ok, msg, cid = compras_service(env).guardar_borrador(
                proveedor_id=1,
                productos=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 10}],
            )
            self.assertTrue(ok, msg)
            with self.assertRaises(DocumentNotFinal):
                docs(env).load_purchase(cid)

    def test_08_purchase_durable_costs(self):
        with phase4c_env() as env:
            seed_purchase_product(env, stock=0, precio_compra=40)
            ensure_proveedor(env)
            cid = complete_receipt(
                env, [{"producto_id": 1, "cantidad": 1, "precio_unitario": Decimal("100.10")}]
            )
            conn = env.connect()
            try:
                conn.execute("UPDATE productos SET precio_compra=1 WHERE id=1")
                conn.commit()
            finally:
                conn.close()
            text = _flat(render_operational_text(docs(env).load_purchase(cid)))
            self.assertIn("100.10", text)
            self.assertNotIn("9999", text)


class ReversalDocumentTest(unittest.TestCase):
    def test_09_10_customer_return(self):
        with phase4c_env() as env:
            seed_ops(env, stock=20, precio=100)
            venta = complete_sale(
                env, [{"producto_id": 1, "cantidad": 1, "precio_unitario": 100}]
            )
            rid = confirm_return(env, venta.id, KIND_CUSTOMER_RETURN, 1)
            doc = docs(env).load_reversal(rid)
            text = _flat(render_operational_text(doc))
            self.assertEqual(doc.kind, KIND_CUSTOMER_RETURN)
            self.assertIn("CUSTOMER_RETURN", text)
            self.assertIn(str(venta.numero_factura), text)
            self.assertIn("100.00", text)
            self.assertIn("Doc. original", text)
            self.assertIn("Doc. reverso", text)

    def test_11_sale_void_references_original(self):
        with phase4c_env() as env:
            seed_ops(env, stock=20, precio=80)
            venta = complete_sale(
                env, [{"producto_id": 1, "cantidad": 1, "precio_unitario": 80}]
            )
            rid = confirm_return(env, venta.id, KIND_SALE_VOID, 1)
            text = _flat(render_operational_text(docs(env).load_reversal(rid)))
            self.assertIn("SALE_VOID", text)
            self.assertIn(str(venta.numero_factura), text)

    def test_12_13_supplier_return_no_cash_claim(self):
        with phase4c_env() as env:
            seed_ops(env, stock=0, precio=50)
            cid = complete_receipt(
                env, [{"producto_id": 1, "cantidad": 2, "precio_unitario": 50}]
            )
            rid = confirm_return(
                env, cid, KIND_SUPPLIER_RETURN, 1, original_tipo="compra"
            )
            doc = docs(env).load_reversal(rid)
            text = _flat(render_operational_text(doc))
            self.assertEqual(doc.kind, KIND_SUPPLIER_RETURN)
            self.assertIn("SUPPLIER_RETURN", text)
            self.assertIn(f"compra#{cid}", text.lower())
            self.assertNotIn("reembolso recibido", text.lower())
            self.assertIn("Devolución de mercancía", text)


class CashCloseDocumentTest(unittest.TestCase):
    def test_14_15_cash_close_snapshot_stable(self):
        with phase4c_env() as env:
            conn = env.connect()
            try:
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            seed_pos_product(env, stock=30)
            caja = open_caja(env, Decimal("100.00"))
            complete_sale_cash(
                env, [{"producto_id": 1, "cantidad": 1, "precio_unitario": 30.20}]
            )
            resumen = caja.obtener_resumen_sesion()
            esperado = resumen["esperado"]
            ok, msg = caja.cerrar_caja(esperado, "cuadra")
            self.assertTrue(ok, msg)
            last = caja.obtener_ultimo_cierre_usuario()
            identity = last.get("local_id") or last["id"]
            first = docs(env).load_cash_close(identity)
            first_text = render_operational_text(first)
            self.assertIn("CIERRE", first_text)
            self.assertIn(format_money(esperado), first_text)
            self.assertIn("100.00", first_text)
            open_caja(env, Decimal("50.00"))
            complete_sale_cash(
                env, [{"producto_id": 1, "cantidad": 1, "precio_unitario": 999}]
            )
            second = docs(env).load_cash_close(identity)
            self.assertEqual(first.fingerprint(), second.fingerprint())
            self.assertNotIn("999.00", render_operational_text(second))


class MoneyReprintPaymentTest(unittest.TestCase):
    def test_16_decimal_money_formatting(self):
        self.assertEqual(format_money("100.10"), "$100.10")
        self.assertEqual(format_money("30.20"), "$30.20")
        self.assertEqual(format_money("69.90"), "$69.90")
        self.assertEqual(format_money(Decimal("100.10") + Decimal("30.20")), "$130.30")
        self.assertNotIn("100.100000", format_money("100.10"))

    def test_17_reprint_twice_idempotent(self):
        with phase4c_env() as env:
            seed_pos_product(env, stock=5)
            venta = complete_sale(
                env, [{"producto_id": 1, "cantidad": 1, "precio_unitario": 12}]
            )
            svc = docs(env)
            a = render_operational_text(svc.load_sale(venta.id))
            b = render_operational_text(svc.load_sale(venta.id))
            self.assertEqual(a, b)

    def test_21_spanish_characters(self):
        with phase4c_env() as env:
            seed_pos_product(env, stock=5, name="Cañón Ñandú")
            venta = complete_sale(
                env, [{"producto_id": 1, "cantidad": 1, "precio_unitario": 10}]
            )
            text = render_operational_text(docs(env).load_sale(venta.id))
            self.assertIn("Cañón Ñandú", text)
            self.assertIn("FERRETERÍA", text)
            self.assertIn("$", text)

    def test_25_26_payment_receipts(self):
        with phase4c_env() as env:
            seed_ops(env, stock=20, precio=100)
            cliente = seed_cliente(env)
            venta = credit_sale(env, total=100, cliente_id=cliente)
            abono_id = pay_customer(env, venta.id, Decimal("40.00"))
            conn = env.connect()
            try:
                local = conn.execute(
                    "SELECT local_id FROM abonos_ventas WHERE id=?", (abono_id,)
                ).fetchone()[0]
            finally:
                conn.close()
            customer = docs(env).load_customer_payment(local)
            ctext = render_operational_text(customer)
            self.assertIn("40.00", ctext)
            self.assertIn("ABONO", ctext)
            sale_txt = _flat(render_operational_text(docs(env).load_sale(venta.id)))
            self.assertIn("CREDITO", sale_txt)
            self.assertIn("no cobrado en efectivo", sale_txt.lower())
            cid = complete_receipt(
                env,
                [{"producto_id": 1, "cantidad": 1, "precio_unitario": 80}],
                tipo_compra="CREDITO",
            )
            pago_id = pay_supplier(env, cid, Decimal("20.00"))
            conn = env.connect()
            try:
                slocal = conn.execute(
                    "SELECT local_id FROM abonos_compras WHERE id=?", (pago_id,)
                ).fetchone()[0]
            finally:
                conn.close()
            supplier = docs(env).load_supplier_payment(slocal)
            stext = render_operational_text(supplier)
            self.assertIn("20.00", stext)
            self.assertIn("PAGO", stext)


if __name__ == "__main__":
    unittest.main(verbosity=2)
