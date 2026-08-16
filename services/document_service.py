# -*- coding: utf-8 -*-
"""Documentos operacionales 4C: carga read-only + render. No escribe negocio."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from services.caja_service import money

DOC_SALE = "SALE"
DOC_PURCHASE = "PURCHASE"
DOC_CUSTOMER_RETURN = "CUSTOMER_RETURN"
DOC_SALE_VOID = "SALE_VOID"
DOC_SUPPLIER_RETURN = "SUPPLIER_RETURN"
DOC_CASH_CLOSE = "CASH_CLOSE"
DOC_CUSTOMER_PAYMENT = "CUSTOMER_PAYMENT"
DOC_SUPPLIER_PAYMENT = "SUPPLIER_PAYMENT"

NON_FISCAL_LABEL = "DOCUMENTO OPERACIONAL / NO FISCAL"
TICKET_WIDTH = 28

_FINAL_SALE = {"COMPLETADA", "COMPLETED"}
_FINAL_PURCHASE = {"COMPLETADA", "COMPLETED"}
_FINAL_REVERSAL = {"COMPLETED"}
_FINAL_CASH = {"CLOSED"}

_PDF_PREFIX = {
    DOC_SALE: "VENTA",
    DOC_PURCHASE: "RECEPCION",
    DOC_CUSTOMER_RETURN: "DEVOLUCION",
    DOC_SALE_VOID: "ANULACION",
    DOC_SUPPLIER_RETURN: "DEVOLUCION_PROVEEDOR",
    DOC_CASH_CLOSE: "CIERRE_CAJA",
    DOC_CUSTOMER_PAYMENT: "ABONO_CLIENTE",
    DOC_SUPPLIER_PAYMENT: "PAGO_PROVEEDOR",
}

_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class DocumentError(ValueError):
    """Error de carga o render de documento operacional."""


class DocumentNotFinal(DocumentError):
    """El documento no está COMPLETED/CLOSED; no se emite comprobante final."""


@dataclass(frozen=True)
class DocumentLine:
    description: str
    quantity: Decimal
    unit_price: Decimal
    subtotal: Decimal
    extra: Tuple[str, ...] = ()


@dataclass(frozen=True)
class OperationalDocument:
    kind: str
    identity: str
    title: str
    issued_at: str
    author: str
    fields: Tuple[Tuple[str, str], ...]
    lines: Tuple[DocumentLine, ...]
    totals: Tuple[Tuple[str, Decimal], ...]
    notes: Tuple[str, ...] = ()
    secondary_id: str = ""
    numero: str = ""
    is_final: bool = True

    def fingerprint(self) -> str:
        parts = [
            self.kind,
            self.identity,
            self.issued_at,
            self.author,
            self.numero,
            "|".join(f"{k}={v}" for k, v in self.fields),
            "|".join(
                f"{ln.description}:{ln.quantity}:{ln.unit_price}:{ln.subtotal}"
                for ln in self.lines
            ),
            "|".join(f"{k}={format_money(v)}" for k, v in self.totals),
            "|".join(self.notes),
        ]
        return "\n".join(parts)


def format_money(value) -> str:
    """Formato de exhibición. Calcula con Decimal; no usa float aritmético."""
    amount = money(value)
    negative = amount < 0
    text = format(abs(amount), "f")
    whole, frac = text.split(".")
    grouped = _group_thousands(whole)
    rendered = f"${grouped}.{frac}"
    return f"-{rendered}" if negative else rendered


def format_qty(value) -> str:
    raw = Decimal(str(value if value is not None else 0))
    if raw == raw.to_integral_value():
        return str(int(raw))
    text = format(raw, "f").rstrip("0").rstrip(".")
    return text or "0"


def suggested_pdf_filename(document: OperationalDocument) -> str:
    prefix = _PDF_PREFIX.get(document.kind, "DOCUMENTO")
    ident = document.identity or document.numero or "sin_id"
    safe = _UNSAFE_FILENAME.sub("_", str(ident)).strip(" .")
    safe = safe.replace(" ", "_") or "sin_id"
    if len(safe) > 80:
        safe = safe[:80]
    return f"{prefix}_{safe}.pdf"


def sale_document_from_payload(venta_data: dict, detalles: list) -> OperationalDocument:
    """Adaptador de payload ya cargado. No consulta precios actuales."""
    data = dict(venta_data or {})
    lines = []
    for det in detalles or []:
        qty = _qty(det.get("cantidad"))
        price = money(det.get("precio_unitario") or 0)
        sub = det.get("subtotal")
        extra = []
        if det.get("es_mezcla"):
            extra.append("MEZCLA PERSONALIZADA")
        lines.append(
            DocumentLine(
                description=str(det.get("producto_nombre") or "Producto"),
                quantity=qty,
                unit_price=price,
                subtotal=money(sub) if sub not in (None, "") else money(qty * price),
                extra=tuple(extra),
            )
        )
    method = str(data.get("metodo_pago") or "EFECTIVO").replace("_", " ")
    totals = [
        ("Subtotal", money(data.get("subtotal") or data.get("total") or 0)),
        ("Descuento", money(data.get("descuento") or 0)),
        ("TOTAL", money(data.get("total") or 0)),
    ]
    identity = str(
        data.get("local_id")
        or data.get("sale_id")
        or data.get("numero_factura")
        or ""
    )
    notes = [NON_FISCAL_LABEL, "No es factura electrónica ni DIAN."]
    if str(data.get("metodo_pago") or "").upper() == "CREDITO":
        notes.append("Crédito: no cobrado en efectivo.")
    return OperationalDocument(
        kind=DOC_SALE,
        identity=identity,
        title="COMPROBANTE DE VENTA",
        issued_at=_fmt_ts(data.get("fecha")),
        author=str(data.get("vendedor") or ""),
        fields=(
            ("Cliente", data.get("cliente_nombre") or "Consumidor final"),
            ("Vendedor", data.get("vendedor") or ""),
            ("Pago", method),
        ),
        lines=tuple(lines),
        totals=tuple(totals),
        notes=tuple(notes),
        numero=str(data.get("numero_factura") or ""),
    )


def render_operational_text(
    document: OperationalDocument,
    *,
    business_name: str = "FERRETERÍA EL ADOBE",
) -> str:
    w = TICKET_WIDTH
    sep = "=" * w
    sep2 = "-" * w
    lines: List[str] = [sep]
    lines.extend(_wrap(_ascii_fold_keep_spanish(business_name), w))
    lines.extend(_wrap(document.title, w))
    lines.append(sep)
    lines.extend(_wrap(NON_FISCAL_LABEL, w))
    if document.identity:
        lines.extend(_kv("ID", document.identity, w))
    if document.numero and document.numero != document.identity:
        lines.extend(_kv("Numero", document.numero, w))
    if document.issued_at:
        lines.extend(_kv("Fecha", document.issued_at, w))
    if document.author:
        lines.extend(_kv("Usuario", document.author, w))
    for label, value in document.fields:
        if value in (None, ""):
            continue
        lines.extend(_kv(label, value, w))
    if document.lines:
        lines.append(sep2)
        for item in document.lines:
            lines.extend(_wrap(item.description, w))
            left = f"{format_qty(item.quantity)} x {format_money(item.unit_price)}"
            right = format_money(item.subtotal)
            lines.append(_align_item(left, right, w))
            for extra in item.extra:
                lines.extend(_wrap(str(extra), w))
    if document.totals:
        lines.append(sep2)
        for label, amount in document.totals:
            lines.append(_align(f"{label}:", format_money(amount), w))
    lines.append(sep)
    for note in document.notes:
        lines.extend(_wrap(note, w))
    if document.notes:
        lines.append(sep)
    return "\r\n".join(lines)


class DocumentService:
    """Carga documentos COMPLETED/CLOSED y arma un read model inmutable."""

    def __init__(self, db_manager):
        self.db = db_manager

    def load(self, kind: str, identity) -> OperationalDocument:
        kind = str(kind or "").upper()
        if kind == DOC_SALE:
            return self.load_sale(identity)
        if kind == DOC_PURCHASE:
            return self.load_purchase(identity)
        if kind in (DOC_CUSTOMER_RETURN, DOC_SALE_VOID, DOC_SUPPLIER_RETURN):
            return self.load_reversal(identity)
        if kind == DOC_CASH_CLOSE:
            return self.load_cash_close(identity)
        if kind == DOC_CUSTOMER_PAYMENT:
            return self.load_customer_payment(identity)
        if kind == DOC_SUPPLIER_PAYMENT:
            return self.load_supplier_payment(identity)
        raise DocumentError(f"tipo de documento no soportado: {kind}")

    def load_sale(self, identity) -> OperationalDocument:
        conn = self.db.conectar()
        try:
            venta = self._find_header(
                conn,
                table="ventas",
                alias="v",
                identity=identity,
                extra_select=(
                    "c.nombre as cliente_nombre, "
                    "u.nombre_completo as vendedor"
                ),
                extra_join=(
                    "LEFT JOIN clientes c ON v.cliente_id = c.id "
                    "LEFT JOIN usuarios u ON v.usuario_id = u.id"
                ),
                numero_col="numero_factura",
            )
            if not venta:
                raise DocumentError("Venta no encontrada")
            estado = str(venta.get("estado") or "").upper()
            if estado not in _FINAL_SALE:
                raise DocumentNotFinal(
                    "La venta no está COMPLETED; no es documento final"
                )
            details = conn.execute(
                """
                SELECT dv.cantidad, dv.precio_unitario, dv.subtotal,
                       dv.descuento, p.nombre as producto_nombre
                  FROM detalle_ventas dv
                  LEFT JOIN productos p ON dv.producto_id = p.id
                 WHERE dv.venta_id = ?
                 ORDER BY dv.id
                """,
                (venta["id"],),
            ).fetchall()
            lines = tuple(
                DocumentLine(
                    description=str(_row(d).get("producto_nombre") or "Producto"),
                    quantity=_qty(_row(d).get("cantidad")),
                    unit_price=money(_row(d).get("precio_unitario") or 0),
                    subtotal=money(_row(d).get("subtotal") or 0),
                )
                for d in details
            )
            identity_value = _durable_id(venta, fallback=venta.get("numero_factura"))
            method = str(venta.get("metodo_pago") or "EFECTIVO").replace("_", " ")
            cliente = venta.get("cliente_nombre") or "Consumidor final"
            fields = [
                ("Cliente", cliente),
                ("Vendedor", venta.get("vendedor") or ""),
                ("Pago", method),
            ]
            notes = [NON_FISCAL_LABEL, "No es factura electrónica ni DIAN."]
            method_token = str(venta.get("metodo_pago") or "").upper()
            if method_token == "CREDITO":
                fields.append(("Facturado", format_money(venta.get("total") or 0)))
                notes.append("Crédito: no cobrado en efectivo.")
                notes.append(
                    "Pagado/pendiente inicial no se reconstruye: monto_pagado es proyección."
                )
            totals = [
                ("Subtotal", money(venta.get("subtotal") or 0)),
                ("Descuento", money(venta.get("descuento") or 0)),
                ("TOTAL", money(venta.get("total") or 0)),
            ]
            if money(venta.get("descuento") or 0) == money(0):
                totals = [totals[0], totals[2]]
            return OperationalDocument(
                kind=DOC_SALE,
                identity=str(identity_value),
                title="COMPROBANTE DE VENTA",
                issued_at=_fmt_ts(venta.get("fecha")),
                author=str(venta.get("vendedor") or ""),
                fields=tuple(fields),
                lines=lines,
                totals=tuple(totals),
                notes=tuple(notes),
                numero=str(venta.get("numero_factura") or ""),
                secondary_id=str(venta.get("id") or ""),
            )
        finally:
            conn.close()

    def load_purchase(self, identity) -> OperationalDocument:
        conn = self.db.conectar()
        try:
            compra = self._find_header(
                conn,
                table="compras",
                alias="c",
                identity=identity,
                extra_select=(
                    "p.nombre as proveedor_nombre, "
                    "u.nombre_completo as usuario_nombre"
                ),
                extra_join=(
                    "LEFT JOIN proveedores p ON c.proveedor_id = p.id "
                    "LEFT JOIN usuarios u ON c.usuario_id = u.id"
                ),
                numero_col="numero_factura",
            )
            if not compra:
                raise DocumentError("Recepción no encontrada")
            estado = str(compra.get("estado") or "").upper()
            if estado not in _FINAL_PURCHASE:
                raise DocumentNotFinal(
                    "La recepción no está COMPLETED; no es documento final"
                )
            details = conn.execute(
                """
                SELECT dc.cantidad, dc.precio_unitario, dc.subtotal,
                       p.nombre as producto_nombre
                  FROM detalle_compras dc
                  LEFT JOIN productos p ON dc.producto_id = p.id
                 WHERE dc.compra_id = ?
                 ORDER BY dc.id
                """,
                (compra["id"],),
            ).fetchall()
            lines = tuple(
                DocumentLine(
                    description=str(_row(d).get("producto_nombre") or "Producto"),
                    quantity=_qty(_row(d).get("cantidad")),
                    unit_price=money(_row(d).get("precio_unitario") or 0),
                    subtotal=money(_row(d).get("subtotal") or 0),
                )
                for d in details
            )
            tipo = str(compra.get("tipo_compra") or "")
            estado_pago = str(compra.get("estado_pago") or "")
            fields = [
                ("Proveedor", compra.get("proveedor_nombre") or ""),
                ("Fact. proveedor", compra.get("numero_factura") or ""),
                ("Tipo", tipo),
                ("Estado pago", estado_pago),
            ]
            notes = [
                NON_FISCAL_LABEL,
                "Mercancía recibida. No afirma que el dinero fue pagado.",
            ]
            return OperationalDocument(
                kind=DOC_PURCHASE,
                identity=str(_durable_id(compra)),
                title="RECEPCIÓN / COMPRA",
                issued_at=_fmt_ts(compra.get("fecha")),
                author=str(compra.get("usuario_nombre") or ""),
                fields=tuple(fields),
                lines=lines,
                totals=(("TOTAL", money(compra.get("total") or 0)),),
                notes=tuple(notes),
                numero=str(compra.get("numero_factura") or ""),
                secondary_id=str(compra.get("id") or ""),
            )
        finally:
            conn.close()

    def load_reversal(self, identity) -> OperationalDocument:
        conn = self.db.conectar()
        try:
            doc = self._find_reversal(conn, identity)
            if not doc:
                raise DocumentError("Reverso no encontrado")
            estado = str(doc.get("estado") or "").upper()
            if estado not in _FINAL_REVERSAL:
                raise DocumentNotFinal(
                    "El reverso no está COMPLETED; no es documento final"
                )
            kind = str(doc.get("kind") or "").upper()
            lines_rows = conn.execute(
                """
                SELECT rl.cantidad_base, rl.precio_unitario, rl.subtotal,
                       p.nombre as producto_nombre
                  FROM reversal_lines rl
                  LEFT JOIN productos p ON rl.producto_id = p.id
                 WHERE rl.reversal_id = ?
                 ORDER BY rl.id
                """,
                (doc["id"],),
            ).fetchall()
            lines = []
            total = money(0)
            for raw in lines_rows:
                item = _row(raw)
                qty = _qty(item.get("cantidad_base"))
                price = money(item.get("precio_unitario") or 0)
                sub = item.get("subtotal")
                subtotal = money(sub) if sub not in (None, "") else money(qty * price)
                total += subtotal
                lines.append(
                    DocumentLine(
                        description=str(item.get("producto_nombre") or "Producto"),
                        quantity=qty,
                        unit_price=price,
                        subtotal=subtotal,
                    )
                )
            original_ref = self._original_reference(conn, doc)
            author = self._usuario_nombre(conn, doc.get("usuario_id"))
            fields = [
                ("Tipo", kind),
                ("Doc. reverso", str(doc.get("local_id") or doc.get("id"))),
                ("Doc. original", original_ref),
                ("Motivo", str(doc.get("motivo") or "")),
            ]
            notes = [NON_FISCAL_LABEL]
            if kind == DOC_SUPPLIER_RETURN:
                notes.append("Devolución de mercancía a proveedor.")
                notes.append("No afirma cobro ni ingreso de caja.")
                title = "DEVOLUCIÓN A PROVEEDOR"
            elif kind == DOC_SALE_VOID:
                title = "ANULACIÓN DE VENTA"
                refund = self._refund_method(conn, doc)
                if refund:
                    fields.append(("Método reembolso", refund))
            else:
                title = "DEVOLUCIÓN CLIENTE"
                refund = self._refund_method(conn, doc)
                if refund:
                    fields.append(("Método reembolso", refund))
            return OperationalDocument(
                kind=kind or DOC_CUSTOMER_RETURN,
                identity=str(doc.get("local_id") or doc.get("id")),
                title=title,
                issued_at=_fmt_ts(doc.get("fecha") or doc.get("created_at")),
                author=author,
                fields=tuple(fields),
                lines=tuple(lines),
                totals=(("TOTAL", total),),
                notes=tuple(notes),
                secondary_id=str(doc.get("id") or ""),
            )
        finally:
            conn.close()

    def load_cash_close(self, identity) -> OperationalDocument:
        conn = self.db.conectar()
        try:
            row = self._find_cash_session(conn, identity)
            if not row:
                raise DocumentError("Cierre de caja no encontrado")
            estado = str(row.get("estado") or "").upper()
            closed = row.get("fecha_cierre") not in (None, "")
            if estado not in _FINAL_CASH and not closed:
                raise DocumentNotFinal(
                    "La caja no está CLOSED; no es documento de cierre"
                )
            cash_in, cash_out = self._session_cash_io(conn, row.get("id"))
            opener = self._usuario_nombre(conn, row.get("usuario_id"))
            closer = self._usuario_nombre(conn, row.get("usuario_cierre_id"))
            author = closer or opener
            fields = [
                ("Estación", str(row.get("station_id") or "")),
                ("Estado", estado or "CLOSED"),
                ("Apertura", _fmt_ts(row.get("fecha_apertura"))),
                ("Cierre", _fmt_ts(row.get("fecha_cierre"))),
                ("Abrió", opener),
                ("Cerró", closer),
                ("Observación", str(row.get("observaciones") or "")),
            ]
            totals = [
                ("Apertura", money(row.get("monto_inicial") or 0)),
                ("Cash IN", cash_in),
                ("Cash OUT", cash_out),
                ("Esperado", money(row.get("monto_esperado") or 0)),
                ("Contado", money(row.get("monto_real") or 0)),
                ("Diferencia", money(row.get("diferencia") or 0)),
            ]
            notes = [
                NON_FISCAL_LABEL,
                "Snapshot de cierre. No recalcula ventas actuales.",
            ]
            return OperationalDocument(
                kind=DOC_CASH_CLOSE,
                identity=str(_durable_id(row)),
                title="CIERRE / ARQUEO DE CAJA",
                issued_at=_fmt_ts(row.get("fecha_cierre") or row.get("fecha_apertura")),
                author=author,
                fields=tuple(fields),
                lines=(),
                totals=tuple(totals),
                notes=tuple(notes),
                secondary_id=str(row.get("id") or ""),
            )
        finally:
            conn.close()

    def load_customer_payment(self, identity) -> OperationalDocument:
        return self._load_payment(
            identity,
            table="abonos_ventas",
            fk="id_venta",
            kind=DOC_CUSTOMER_PAYMENT,
            title="COMPROBANTE DE ABONO CLIENTE",
            doc_kind="venta",
        )

    def load_supplier_payment(self, identity) -> OperationalDocument:
        return self._load_payment(
            identity,
            table="abonos_compras",
            fk="id_compra",
            kind=DOC_SUPPLIER_PAYMENT,
            title="COMPROBANTE DE PAGO PROVEEDOR",
            doc_kind="compra",
        )

    def _load_payment(
        self, identity, *, table, fk, kind, title, doc_kind
    ) -> OperationalDocument:
        conn = self.db.conectar()
        try:
            row = self._find_payment(conn, table, identity)
            if not row:
                raise DocumentError("Abono no encontrado")
            amount = money(row.get("monto_abono") or 0)
            doc_id = row.get(fk)
            resulting = self._resulting_balance(conn, doc_kind, doc_id, table, fk, row["id"])
            parent_id = self._parent_identity(conn, doc_kind, doc_id)
            fields = [
                ("Pago ID", str(row.get("local_id") or row.get("id"))),
                ("Documento", parent_id),
                ("Método", str(row.get("tipo_pago") or "")),
                ("Saldo resultante", format_money(resulting)),
            ]
            return OperationalDocument(
                kind=kind,
                identity=str(row.get("local_id") or row.get("id")),
                title=title,
                issued_at=_fmt_ts(row.get("fecha_abono") or row.get("created_at")),
                author=str(row.get("usuario") or ""),
                fields=tuple(fields),
                lines=(),
                totals=(("Monto", amount),),
                notes=(NON_FISCAL_LABEL,),
                secondary_id=str(row.get("id") or ""),
            )
        finally:
            conn.close()

    def _find_header(
        self,
        conn,
        *,
        table: str,
        alias: str,
        identity,
        extra_select: str,
        extra_join: str,
        numero_col: str,
    ) -> Optional[dict]:
        ident = str(identity or "").strip()
        if not ident:
            return None
        base = f"SELECT {alias}.*, {extra_select} FROM {table} {alias} {extra_join}"
        row = conn.execute(
            f"{base} WHERE {alias}.local_id = ?", (ident,)
        ).fetchone()
        if row:
            return _row(row)
        row = conn.execute(
            f"{base} WHERE {alias}.{numero_col} = ?", (ident,)
        ).fetchone()
        if row:
            return _row(row)
        if ident.isdigit():
            row = conn.execute(
                f"{base} WHERE {alias}.id = ?", (int(ident),)
            ).fetchone()
            if row:
                return _row(row)
        return None

    def _find_reversal(self, conn, identity) -> Optional[dict]:
        ident = str(identity or "").strip()
        if not ident:
            return None
        row = conn.execute(
            "SELECT * FROM reversal_documents WHERE local_id = ?", (ident,)
        ).fetchone()
        if row:
            return _row(row)
        if ident.isdigit():
            row = conn.execute(
                "SELECT * FROM reversal_documents WHERE id = ?", (int(ident),)
            ).fetchone()
            if row:
                return _row(row)
        return None

    def _find_cash_session(self, conn, identity) -> Optional[dict]:
        ident = str(identity or "").strip()
        if not ident:
            return None
        row = conn.execute(
            "SELECT * FROM cierres_caja WHERE local_id = ?", (ident,)
        ).fetchone()
        if row:
            return _row(row)
        if ident.isdigit():
            row = conn.execute(
                "SELECT * FROM cierres_caja WHERE id = ?", (int(ident),)
            ).fetchone()
            if row:
                return _row(row)
        return None

    def _find_payment(self, conn, table, identity) -> Optional[dict]:
        ident = str(identity or "").strip()
        if not ident:
            return None
        row = conn.execute(
            f"SELECT * FROM {table} WHERE local_id = ?", (ident,)
        ).fetchone()
        if row:
            return _row(row)
        if ident.isdigit():
            row = conn.execute(
                f"SELECT * FROM {table} WHERE id = ?", (int(ident),)
            ).fetchone()
            if row:
                return _row(row)
        return None

    def _original_reference(self, conn, doc: dict) -> str:
        parts = []
        if doc.get("original_local_id"):
            parts.append(str(doc["original_local_id"]))
        tipo = str(doc.get("original_tipo") or "")
        oid = doc.get("original_id")
        if tipo == "venta" and oid:
            venta = conn.execute(
                "SELECT local_id, numero_factura FROM ventas WHERE id = ?",
                (oid,),
            ).fetchone()
            if venta:
                venta = _row(venta)
                if venta.get("numero_factura"):
                    parts.append(f"Fact {venta['numero_factura']}")
                if venta.get("local_id") and venta["local_id"] not in parts:
                    parts.append(str(venta["local_id"]))
        elif tipo == "compra" and oid:
            compra = conn.execute(
                "SELECT local_id, numero_factura FROM compras WHERE id = ?",
                (oid,),
            ).fetchone()
            if compra:
                compra = _row(compra)
                if compra.get("numero_factura"):
                    parts.append(f"Fact {compra['numero_factura']}")
                if compra.get("local_id") and compra["local_id"] not in parts:
                    parts.append(str(compra["local_id"]))
        if oid is not None:
            parts.append(f"{tipo}#{oid}")
        return " / ".join(dict.fromkeys(parts))

    def _refund_method(self, conn, doc: dict) -> str:
        ident = str(doc.get("local_id") or "")
        if not ident:
            return ""
        row = conn.execute(
            """
            SELECT payment_method FROM cash_movements
             WHERE source_kind = 'reversal' AND source_identity = ?
             ORDER BY id LIMIT 1
            """,
            (ident,),
        ).fetchone()
        if not row:
            return ""
        return str(_row(row).get("payment_method") or "")

    def _session_cash_io(self, conn, session_id) -> Tuple[Decimal, Decimal]:
        """Ledger de ESA sesión. No usa ventas de otros días/sesiones."""
        cash_in = money(0)
        cash_out = money(0)
        if session_id is None:
            return cash_in, cash_out
        try:
            rows = conn.execute(
                """
                SELECT cash_effect_kind, amount FROM cash_movements
                 WHERE cash_session_id = ?
                """,
                (session_id,),
            ).fetchall()
        except Exception:
            return cash_in, cash_out
        for raw in rows:
            item = _row(raw)
            amount = money(item.get("amount") or 0)
            effect = str(item.get("cash_effect_kind") or "")
            if effect == "DRAWER_IN":
                cash_in += amount
            elif effect == "DRAWER_OUT":
                cash_out += amount
        return cash_in, cash_out

    def _usuario_nombre(self, conn, usuario_id) -> str:
        if not usuario_id:
            return ""
        row = conn.execute(
            "SELECT nombre_completo FROM usuarios WHERE id = ?",
            (usuario_id,),
        ).fetchone()
        if not row:
            return ""
        return str(_row(row).get("nombre_completo") or "")

    def _parent_identity(self, conn, doc_kind: str, doc_id) -> str:
        table = "ventas" if doc_kind == "venta" else "compras"
        row = conn.execute(
            f"SELECT local_id, numero_factura FROM {table} WHERE id = ?",
            (doc_id,),
        ).fetchone()
        if not row:
            return f"{doc_kind}#{doc_id}"
        data = _row(row)
        return str(data.get("local_id") or data.get("numero_factura") or f"{doc_kind}#{doc_id}")

    def _resulting_balance(
        self, conn, doc_kind, doc_id, table, fk, payment_id
    ) -> Decimal:
        from services.operational_balance import compute_payable, compute_receivable

        snap = (
            compute_receivable(conn, doc_id)
            if doc_kind == "venta"
            else compute_payable(conn, doc_id)
        )
        net = money(snap.net_obligation) if snap else money(0)
        paid = money(0)
        rows = conn.execute(
            f"SELECT id, monto_abono FROM {table} WHERE {fk} = ? ORDER BY id",
            (doc_id,),
        ).fetchall()
        for raw in rows:
            item = _row(raw)
            paid += money(item.get("monto_abono") or 0)
            if item.get("id") == payment_id:
                break
        remaining = net - paid
        if remaining < 0:
            return money(0)
        return remaining


def _row(row) -> dict:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    return dict(row)


def _durable_id(row: dict, fallback=None) -> str:
    for key in ("local_id", "inventory_command_id"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    if fallback not in (None, ""):
        return str(fallback)
    return str(row.get("id") or "")


def _qty(value) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _fmt_ts(value) -> str:
    if value in (None, ""):
        return ""
    text = str(value).replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text[:19], fmt) if len(fmt) > 10 else datetime.strptime(text[:10], fmt)
            return dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    return text[:16]


def _group_thousands(whole: str) -> str:
    if len(whole) <= 3:
        return whole
    grouped = ""
    while len(whole) > 3:
        grouped = "," + whole[-3:] + grouped
        whole = whole[:-3]
    return whole + grouped


def _wrap(text: str, width: int) -> List[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    out = []
    while len(raw) > width:
        cut = raw.rfind(" ", 0, width)
        if cut < 1:
            cut = width
        out.append(raw[:cut].rstrip())
        raw = raw[cut:].lstrip()
    if raw:
        out.append(raw)
    return out


def _kv(label: str, value: str, width: int) -> List[str]:
    value = str(value or "").strip()
    if not value:
        return []
    prefix = f"{label}: "
    if len(prefix) + len(value) <= width:
        return [f"{prefix}{value}"]
    lines = [prefix.rstrip()]
    lines.extend(_wrap(value, width))
    return lines


def _align(label: str, value: str, width: int) -> str:
    left = label.strip()
    right = value.strip()
    gap = width - len(left) - len(right)
    if gap < 1:
        gap = 1
    return f"{left}{' ' * gap}{right}"


def _align_item(left: str, right: str, width: int) -> str:
    left = left.strip()
    right = right.strip()
    max_left = max(1, width - len(right) - 1)
    if len(left) > max_left:
        left = left[:max_left]
    gap = width - len(left) - len(right)
    if gap < 1:
        gap = 1
    return f"{left}{' ' * gap}{right}"


def _ascii_fold_keep_spanish(text: str) -> str:
    return str(text or "")
