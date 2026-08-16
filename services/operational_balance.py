# -*- coding: utf-8 -*-
"""Saldo operacional canónico 4B (CxC / CxP). No es contabilidad.

NET_OBLIGATION = ORIGINAL COMPLETED − REVERSALS
BALANCE        = NET_OBLIGATION − VALID PAYMENTS  (nunca negativo silencioso)
CREDIT         = PAYMENTS − NET_OBLIGATION si PAYMENTS > NET

Fuente: documentos COMPLETED + reversal_documents COMPLETED + abonos.
ventas.monto_pagado / compras.saldo_pendiente / cuentas_por_cobrar son proyección.
"""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import schema_bootstrap
from balance_schema import LEGACY_PAYMENT_TABLE
from returns_schema import (
    ESTADO_COMPLETED,
    KIND_CUSTOMER_RETURN,
    KIND_SALE_VOID,
    KIND_SUPPLIER_RETURN,
    ORIGINAL_TIPO_COMPRA,
    ORIGINAL_TIPO_VENTA,
)
from services.caja_service import money

PAYMENT_EXCEEDS_BALANCE = "PAYMENT_EXCEEDS_BALANCE"
FINANCIAL_WRITER_FENCE = "FINANCIAL_WRITER_FENCE"
CUSTOMER_CREDIT = "CUSTOMER_CREDIT"
SUPPLIER_CREDIT = "SUPPLIER_CREDIT"
ESTADO_PENDIENTE = "PENDIENTE"
ESTADO_PARCIAL = "PARCIAL"
ESTADO_PAGADO = "PAGADO"
ESTADO_CREDITO_A_FAVOR = "CREDITO_A_FAVOR"

SALES_COMPLETED_SQL = (
    "UPPER(COALESCE({alias}.estado, 'COMPLETADA')) IN ('COMPLETADA', 'COMPLETED')"
)
PURCHASES_COMPLETED_SQL = (
    "UPPER(COALESCE({alias}.estado, '')) IN ('COMPLETADA', 'COMPLETED')"
)


class PaymentError(ValueError):
    def __init__(self, code: str, message: str = None):
        self.code = code
        super().__init__(message or code)


@dataclass
class BalanceSnapshot:
    document_tipo: str
    document_id: int
    original: Decimal
    reversals: Decimal
    net_obligation: Decimal
    payments: Decimal
    balance: Decimal
    credit_balance: Decimal
    credit_kind: Optional[str]
    estado_pago: str
    fecha: Optional[str] = None
    projection_stale: bool = False
    projected_paid: Optional[Decimal] = None
    projected_balance: Optional[Decimal] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "original": self.original,
            "reversals": self.reversals,
            "net_obligation": self.net_obligation,
            "monto_pagado": self.payments,
            "saldo_pendiente": self.balance,
            "credito_a_favor": self.credit_balance,
            "credit_kind": self.credit_kind,
            "estado_pago": self.estado_pago,
            "projection_stale": self.projection_stale,
        }


def connect_local(db_path: Optional[str] = None):
    """SQLite local-first. No abre PostgreSQL remoto."""
    import pg_compat

    mode = str(getattr(pg_compat, "DB_MODE", "local") or "local").strip().lower()
    if mode not in ("local", "sqlite", "server"):
        raise RuntimeError(
            "Cuentas por cobrar/pagar requieren SQLite local-first; "
            "no se abre PostgreSQL remoto"
        )
    path = _resolve_sqlite_path(db_path, pg_compat.LOCAL_DB_PATH)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _resolve_sqlite_path(db_path, fallback) -> str:
    if db_path and str(db_path) not in ("", "ferreteria.db"):
        return str(db_path)
    return str(fallback)


def durable_payment_id(value=None) -> str:
    """Devuelve una identidad UUID canónica; rechaza identidades ad-hoc."""
    if value in (None, ""):
        return str(uuid.uuid4())
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise PaymentError(
            "INVALID_PAYMENT_ID", "local_id del abono debe ser un UUID"
        ) from exc


def new_payment_id() -> str:
    return durable_payment_id()


def _as_money(value) -> Decimal:
    if value is None or value == "":
        return Decimal("0.00")
    return money(value)


def _row(row) -> dict:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    return dict(row)


def _table(conn, name: str) -> bool:
    return schema_bootstrap.table_exists(conn, name)


def _has_column(conn, table: str, column: str) -> bool:
    try:
        return schema_bootstrap.column_exists(conn, table, column)
    except Exception:
        return False


def _is_completed(document_tipo: str, document: dict) -> bool:
    default = "COMPLETADA" if document_tipo == ORIGINAL_TIPO_VENTA else ""
    return str(document.get("estado") or default).strip().upper() in (
        "COMPLETADA",
        "COMPLETED",
    )


def begin_immediate(conn) -> None:
    if not getattr(conn, "in_transaction", False):
        conn.execute("BEGIN IMMEDIATE")


def days_outstanding(fecha_str, now: Optional[datetime] = None) -> int:
    if not fecha_str:
        return 0
    now = now or datetime.now()
    try:
        raw = str(fecha_str).replace("Z", "").replace("T", " ")
        fecha = datetime.fromisoformat(raw.split("+")[0].strip()[:19])
        return max(0, (now - fecha).days)
    except Exception:
        return 0


def aging_bucket(days: int) -> str:
    if days <= 30:
        return "0-30"
    if days <= 60:
        return "31-60"
    if days <= 90:
        return "61-90"
    return "90+"


def empty_aging() -> Dict[str, Decimal]:
    zero = Decimal("0.00")
    return {
        "aging_0_30": zero,
        "aging_31_60": zero,
        "aging_61_90": zero,
        "aging_90_plus": zero,
        "deuda_30": zero,
        "deuda_60": zero,
        "deuda_90": zero,
    }


def add_aging(buckets: Dict[str, Decimal], days: int, amount: Decimal) -> None:
    if amount <= 0:
        return
    key = aging_bucket(days)
    if key == "0-30":
        buckets["aging_0_30"] += amount
        buckets["deuda_30"] += amount
    elif key == "31-60":
        buckets["aging_31_60"] += amount
        buckets["deuda_60"] += amount
    elif key == "61-90":
        buckets["aging_61_90"] += amount
        buckets["deuda_90"] += amount
    else:
        buckets["aging_90_plus"] += amount
        buckets["deuda_90"] += amount


def _estado_from(net: Decimal, paid: Decimal, balance: Decimal, credit: Decimal) -> str:
    if credit > 0:
        return ESTADO_CREDITO_A_FAVOR
    if balance <= 0 and paid >= net:
        return ESTADO_PAGADO
    if paid > 0:
        return ESTADO_PARCIAL
    return ESTADO_PENDIENTE


def _sum_reversals(conn, original_tipo: str, original_id: int, kinds: Tuple[str, ...]) -> Decimal:
    if not _table(conn, "reversal_documents") or not _table(conn, "reversal_lines"):
        return Decimal("0.00")
    placeholders = ",".join("?" * len(kinds))
    rows = conn.execute(
        f"""
        SELECT l.subtotal
          FROM reversal_lines l
          JOIN reversal_documents d ON d.id = l.reversal_id
         WHERE d.original_tipo = ?
           AND d.original_id = ?
           AND d.estado = ?
           AND d.kind IN ({placeholders})
        """,
        (original_tipo, original_id, ESTADO_COMPLETED, *kinds),
    ).fetchall()
    total = Decimal("0.00")
    for row in rows:
        total += _as_money(_row(row).get("subtotal"))
    return total


def _sum_payments(conn, table: str, fk: str, document_id: int) -> Decimal:
    if not _table(conn, table):
        return Decimal("0.00")
    rows = conn.execute(
        f"SELECT monto_abono FROM {table} WHERE {fk} = ?",
        (document_id,),
    ).fetchall()
    total = Decimal("0.00")
    for row in rows:
        total += _as_money(_row(row).get("monto_abono"))
    return total


def _legacy_payment_baseline(conn, document_tipo: str, document_id: int) -> Decimal:
    if not _table(conn, LEGACY_PAYMENT_TABLE):
        return Decimal("0.00")
    row = conn.execute(
        f"SELECT amount FROM {LEGACY_PAYMENT_TABLE} "
        "WHERE document_tipo = ? AND document_id = ?",
        (document_tipo, document_id),
    ).fetchone()
    return _as_money(_row(row).get("amount")) if row else Decimal("0.00")


def _canonical_payments(
    conn, document_tipo: str, table: str, fk: str, document_id: int
) -> Decimal:
    # El baseline solo existe para documentos sin abonos al momento del cutover;
    # por eso sumarlo a abonos posteriores no duplica el histórico.
    return _legacy_payment_baseline(conn, document_tipo, document_id) + _sum_payments(
        conn, table, fk, document_id
    )


def _finish_snapshot(
    *,
    document_tipo: str,
    document_id: int,
    original: Decimal,
    reversals: Decimal,
    payments: Decimal,
    fecha=None,
    projected_paid=None,
    projected_balance=None,
) -> BalanceSnapshot:
    net = original - reversals
    if net < 0:
        net = Decimal("0.00")
    credit = payments - net if payments > net else Decimal("0.00")
    balance = net - payments if payments < net else Decimal("0.00")
    projected_paid_m = None if projected_paid is None else _as_money(projected_paid)
    projected_balance_m = None if projected_balance is None else _as_money(projected_balance)
    stale = False
    if projected_paid_m is not None and projected_paid_m != payments:
        stale = True
    if projected_balance_m is not None and projected_balance_m != balance:
        stale = True
    credit_kind = None
    if credit > 0:
        credit_kind = (
            CUSTOMER_CREDIT if document_tipo == ORIGINAL_TIPO_VENTA else SUPPLIER_CREDIT
        )
    return BalanceSnapshot(
        document_tipo=document_tipo,
        document_id=document_id,
        original=original,
        reversals=reversals,
        net_obligation=net,
        payments=payments,
        balance=balance,
        credit_balance=credit,
        credit_kind=credit_kind,
        estado_pago=_estado_from(net, payments, balance, credit),
        fecha=fecha,
        projection_stale=stale,
        projected_paid=projected_paid_m,
        projected_balance=projected_balance_m,
    )


def compute_receivable(conn, venta_id: int) -> Optional[BalanceSnapshot]:
    if not _table(conn, "ventas"):
        return None
    row = conn.execute("SELECT * FROM ventas WHERE id = ?", (venta_id,)).fetchone()
    if not row:
        return None
    venta = _row(row)
    if not _is_completed(ORIGINAL_TIPO_VENTA, venta):
        return None
    original = _as_money(venta.get("total"))
    reversals = _sum_reversals(
        conn,
        ORIGINAL_TIPO_VENTA,
        venta_id,
        (KIND_CUSTOMER_RETURN, KIND_SALE_VOID),
    )
    payments = _canonical_payments(
        conn, ORIGINAL_TIPO_VENTA, "abonos_ventas", "id_venta", venta_id
    )
    return _finish_snapshot(
        document_tipo=ORIGINAL_TIPO_VENTA,
        document_id=int(venta_id),
        original=original,
        reversals=reversals,
        payments=payments,
        fecha=venta.get("fecha"),
        projected_paid=venta.get("monto_pagado"),
        projected_balance=_as_money(venta.get("total")) - _as_money(venta.get("monto_pagado")),
    )


def compute_payable(conn, compra_id: int) -> Optional[BalanceSnapshot]:
    if not _table(conn, "compras"):
        return None
    row = conn.execute("SELECT * FROM compras WHERE id = ?", (compra_id,)).fetchone()
    if not row:
        return None
    compra = _row(row)
    if not _is_completed(ORIGINAL_TIPO_COMPRA, compra):
        return None
    original = _as_money(compra.get("total"))
    reversals = _sum_reversals(
        conn,
        ORIGINAL_TIPO_COMPRA,
        compra_id,
        (KIND_SUPPLIER_RETURN,),
    )
    payments = _canonical_payments(
        conn, ORIGINAL_TIPO_COMPRA, "abonos_compras", "id_compra", compra_id
    )
    projected_balance = compra.get("saldo_pendiente")
    if projected_balance is None:
        projected_balance = _as_money(compra.get("total")) - _as_money(
            compra.get("monto_pagado")
        )
    return _finish_snapshot(
        document_tipo=ORIGINAL_TIPO_COMPRA,
        document_id=int(compra_id),
        original=original,
        reversals=reversals,
        payments=payments,
        fecha=compra.get("fecha"),
        projected_paid=compra.get("monto_pagado"),
        projected_balance=projected_balance,
    )


def assert_payment_allowed(snapshot: BalanceSnapshot, amount) -> Decimal:
    monto = _as_money(amount)
    if monto <= 0:
        raise PaymentError("INVALID_AMOUNT", "El monto debe ser mayor a cero")
    if monto > snapshot.balance:
        raise PaymentError(
            PAYMENT_EXCEEDS_BALANCE,
            f"{PAYMENT_EXCEEDS_BALANCE}: pago {monto} excede saldo {snapshot.balance}",
        )
    return monto


def find_payment_by_local_id(conn, table: str, local_id: str) -> Optional[dict]:
    if not local_id or not _table(conn, table) or not _has_column(conn, table, "local_id"):
        return None
    row = conn.execute(
        f"SELECT * FROM {table} WHERE local_id = ?", (local_id,)
    ).fetchone()
    return _row(row) if row else None


def project_receivable(conn, venta_id: int) -> Optional[BalanceSnapshot]:
    snap = compute_receivable(conn, venta_id)
    if not snap:
        return None
    conn.execute(
        "UPDATE ventas SET estado_pago = ?, monto_pagado = ? WHERE id = ?",
        (snap.estado_pago if snap.estado_pago != ESTADO_CREDITO_A_FAVOR else ESTADO_PAGADO,
         format(snap.payments, "f"),
         venta_id),
    )
    if _table(conn, "cuentas_por_cobrar"):
        estado = snap.estado_pago
        conn.execute(
            """
            UPDATE cuentas_por_cobrar
               SET monto_pagado = ?, saldo_pendiente = ?, estado = ?
             WHERE venta_id = ?
            """,
            (format(snap.payments, "f"), format(snap.balance, "f"), estado, venta_id),
        )
    return compute_receivable(conn, venta_id)


def project_payable(conn, compra_id: int) -> Optional[BalanceSnapshot]:
    snap = compute_payable(conn, compra_id)
    if not snap:
        return None
    estado = (
        ESTADO_PAGADO
        if snap.estado_pago == ESTADO_CREDITO_A_FAVOR
        else snap.estado_pago
    )
    conn.execute(
        """
        UPDATE compras
           SET estado_pago = ?, monto_pagado = ?, saldo_pendiente = ?
         WHERE id = ?
        """,
        (estado, format(snap.payments, "f"), format(snap.balance, "f"), compra_id),
    )
    return compute_payable(conn, compra_id)


def project_after_reversal(conn, doc: dict) -> None:
    tipo = str(doc.get("original_tipo") or "")
    original_id = doc.get("original_id")
    if original_id is None:
        return
    if tipo == ORIGINAL_TIPO_VENTA:
        project_receivable(conn, int(original_id))
    elif tipo == ORIGINAL_TIPO_COMPRA:
        project_payable(conn, int(original_id))


def reconcile_receivable(conn, venta_id: int) -> BalanceSnapshot:
    snap = compute_receivable(conn, venta_id)
    if not snap:
        raise PaymentError("NOT_FOUND", f"Venta {venta_id} no encontrada")
    if snap.projection_stale:
        snap = project_receivable(conn, venta_id) or snap
    return snap


def reconcile_payable(conn, compra_id: int) -> BalanceSnapshot:
    snap = compute_payable(conn, compra_id)
    if not snap:
        raise PaymentError("NOT_FOUND", f"Compra {compra_id} no encontrada")
    if snap.projection_stale:
        snap = project_payable(conn, compra_id) or snap
    return snap


def _reversal_index(conn, original_tipo: str, kinds: Tuple[str, ...]) -> Dict[int, Decimal]:
    out: Dict[int, Decimal] = {}
    if not _table(conn, "reversal_documents") or not _table(conn, "reversal_lines"):
        return out
    placeholders = ",".join("?" * len(kinds))
    rows = conn.execute(
        f"""
        SELECT d.original_id, l.subtotal
          FROM reversal_lines l
          JOIN reversal_documents d ON d.id = l.reversal_id
         WHERE d.original_tipo = ?
           AND d.estado = ?
           AND d.kind IN ({placeholders})
        """,
        (original_tipo, ESTADO_COMPLETED, *kinds),
    ).fetchall()
    for row in rows:
        item = _row(row)
        oid = int(item["original_id"])
        out[oid] = out.get(oid, Decimal("0.00")) + _as_money(item.get("subtotal"))
    return out


def _payment_index(conn, table: str, fk: str) -> Dict[int, Decimal]:
    out: Dict[int, Decimal] = {}
    if not _table(conn, table):
        return out
    rows = conn.execute(f"SELECT {fk} AS doc_id, monto_abono FROM {table}").fetchall()
    for row in rows:
        item = _row(row)
        oid = int(item["doc_id"])
        out[oid] = out.get(oid, Decimal("0.00")) + _as_money(item.get("monto_abono"))
    return out


def _legacy_payment_index(conn, document_tipo: str) -> Dict[int, Decimal]:
    out: Dict[int, Decimal] = {}
    if not _table(conn, LEGACY_PAYMENT_TABLE):
        return out
    rows = conn.execute(
        f"SELECT document_id, amount FROM {LEGACY_PAYMENT_TABLE} "
        "WHERE document_tipo = ?",
        (document_tipo,),
    ).fetchall()
    for row in rows:
        item = _row(row)
        out[int(item["document_id"])] = _as_money(item.get("amount"))
    return out


def _canonical_payment_index(
    conn, document_tipo: str, table: str, fk: str
) -> Dict[int, Decimal]:
    out = _legacy_payment_index(conn, document_tipo)
    for document_id, amount in _payment_index(conn, table, fk).items():
        out[document_id] = out.get(document_id, Decimal("0.00")) + amount
    return out


def list_receivable_snapshots(conn) -> List[Tuple[dict, BalanceSnapshot]]:
    if not _table(conn, "ventas"):
        return []
    reversals = _reversal_index(
        conn, ORIGINAL_TIPO_VENTA, (KIND_CUSTOMER_RETURN, KIND_SALE_VOID)
    )
    payments = _canonical_payment_index(
        conn, ORIGINAL_TIPO_VENTA, "abonos_ventas", "id_venta"
    )
    has_clientes = _table(conn, "clientes")
    sql = f"""
        SELECT v.*,
               {"c.nombre" if has_clientes else "NULL"} AS cliente_nombre,
               {"c.id" if has_clientes else "NULL"} AS cliente_id_join
          FROM ventas v
          {"LEFT JOIN clientes c ON c.id = v.cliente_id" if has_clientes else ""}
         WHERE UPPER(COALESCE(v.metodo_pago, '')) = 'CREDITO'
           AND {SALES_COMPLETED_SQL.format(alias="v")}
         ORDER BY v.fecha ASC
    """
    rows = conn.execute(sql).fetchall()
    result = []
    for raw in rows:
        venta = _row(raw)
        vid = int(venta["id"])
        snap = _finish_snapshot(
            document_tipo=ORIGINAL_TIPO_VENTA,
            document_id=vid,
            original=_as_money(venta.get("total")),
            reversals=reversals.get(vid, Decimal("0.00")),
            payments=payments.get(vid, Decimal("0.00")),
            fecha=venta.get("fecha"),
            projected_paid=venta.get("monto_pagado"),
            projected_balance=_as_money(venta.get("total"))
            - _as_money(venta.get("monto_pagado")),
        )
        result.append((venta, snap))
    return result


def list_payable_snapshots(conn) -> List[Tuple[dict, BalanceSnapshot]]:
    if not _table(conn, "compras"):
        return []
    reversals = _reversal_index(conn, ORIGINAL_TIPO_COMPRA, (KIND_SUPPLIER_RETURN,))
    payments = _canonical_payment_index(
        conn, ORIGINAL_TIPO_COMPRA, "abonos_compras", "id_compra"
    )
    has_prov = _table(conn, "proveedores")
    sql = f"""
        SELECT c.*,
               {"p.nombre" if has_prov else "NULL"} AS proveedor_nombre
          FROM compras c
          {"LEFT JOIN proveedores p ON p.id = c.proveedor_id" if has_prov else ""}
         WHERE {PURCHASES_COMPLETED_SQL.format(alias="c")}
         ORDER BY c.fecha ASC
    """
    rows = conn.execute(sql).fetchall()
    result = []
    for raw in rows:
        compra = _row(raw)
        cid = int(compra["id"])
        snap = _finish_snapshot(
            document_tipo=ORIGINAL_TIPO_COMPRA,
            document_id=cid,
            original=_as_money(compra.get("total")),
            reversals=reversals.get(cid, Decimal("0.00")),
            payments=payments.get(cid, Decimal("0.00")),
            fecha=compra.get("fecha"),
            projected_paid=compra.get("monto_pagado"),
            projected_balance=compra.get("saldo_pendiente"),
        )
        result.append((compra, snap))
    return result
