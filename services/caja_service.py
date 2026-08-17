# -*- coding: utf-8 -*-
"""Caja operacional: sesión por estación + ledger local-first. SQLite primero."""
from __future__ import annotations

import sqlite3
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Optional, Tuple

from cash_schema import (
    ALREADY_CLOSED,
    CLOSED_SESSION,
    DIRECTION_IN,
    DIRECTION_OUT,
    EFFECT_DRAWER_IN,
    EFFECT_DRAWER_OUT,
    EFFECT_INFORMATIONAL,
    ESTADO_CLOSED,
    ESTADO_OPEN,
    EXISTING_OPEN_SESSION,
    KIND_CUSTOMER_PAYMENT,
    KIND_EXPENSE,
    KIND_REFUND,
    KIND_REINFORCEMENT,
    KIND_SALE,
    KIND_SUPPLIER_PAYMENT,
    METHOD_CARD_CREDIT,
    METHOD_CARD_DEBIT,
    METHOD_CASH,
    METHOD_CREDIT,
    METHOD_TRANSFER,
    NO_OPEN_SESSION,
    SOURCE_ABONO_COMPRA,
    SOURCE_ABONO_VENTA,
    SOURCE_EGRESO,
    SOURCE_INGRESO,
    SOURCE_REVERSAL,
    SOURCE_VENTA,
    ensure_sqlite_cash_operational_schema,
    is_cash_method,
    new_local_id,
    normalize_payment_method,
)

CASH_ADMIN_ROLES = frozenset({"ADMIN", "GERENTE"})
CASH_VIEW_ROLES = frozenset({"ADMIN", "GERENTE", "VENDEDOR", "EMPLEADO"})
CASH_ADMIN_DENIED = (
    "Solo administradores o gerentes pueden ejecutar acciones administrativas de caja"
)

TWOPLACES = Decimal("0.01")


def money(value) -> Decimal:
    """Normaliza montos canónicos. Rechaza basura; no usa float aritmético."""
    if value is None:
        raise ValueError("monto requerido")
    if isinstance(value, bool):
        raise ValueError("monto inválido")
    if isinstance(value, float):
        raw = Decimal(str(value))
    elif isinstance(value, Decimal):
        raw = value
    else:
        try:
            raw = Decimal(str(value).replace(",", ".").strip())
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("monto inválido") from exc
    quantized = raw.quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    return quantized


def _money_text(value) -> str:
    return format(money(value), "f")


def _row_dict(row) -> dict:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    return dict(row)


def resolve_station_id(explicit=None) -> str:
    if explicit:
        return str(explicit)
    try:
        from local_first_config import get_or_create_device_id

        return get_or_create_device_id()
    except Exception:
        return "LOCAL"


def is_cash_admin(usuario) -> bool:
    """ADMIN/GERENTE: comandos administrativos de caja. No usa rol del widget."""
    rol = getattr(usuario, "rol", None) if usuario is not None else None
    return str(rol or "") in CASH_ADMIN_ROLES


def can_view_caja(usuario) -> bool:
    """ADMIN y operador de ventas (VENDEDOR/EMPLEADO) pueden abrir la sección."""
    rol = getattr(usuario, "rol", None) if usuario is not None else None
    return str(rol or "") in CASH_VIEW_ROLES


def _ensure_cash_schema(conn) -> None:
    """Aplica el esquema 3D si falta station_id o cash_movements. Solo SQLite."""
    try:
        import schema_bootstrap
    except Exception:
        return
    if not schema_bootstrap.is_sqlite_connection(conn):
        return
    needs_movements = not schema_bootstrap.table_exists(conn, "cash_movements")
    needs_station = schema_bootstrap.table_exists(
        conn, "cierres_caja"
    ) and not schema_bootstrap.column_exists(conn, "cierres_caja", "station_id")
    if not (needs_movements or needs_station):
        return
    already_in_txn = bool(getattr(conn, "in_transaction", False))
    ensure_sqlite_cash_operational_schema(conn)
    if not already_in_txn:
        conn.commit()


def cash_effect_for(direction: str, payment_method: str) -> str:
    if is_cash_method(payment_method):
        return EFFECT_DRAWER_IN if direction == DIRECTION_IN else EFFECT_DRAWER_OUT
    return EFFECT_INFORMATIONAL


def _table_exists(conn, name: str) -> bool:
    try:
        import schema_bootstrap

        return schema_bootstrap.table_exists(conn, name)
    except Exception:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        return row is not None


def _begin_immediate(conn) -> None:
    """Adquiere el writer lock SQLite antes de cualquier lectura decisoria."""
    conn.execute("BEGIN IMMEDIATE")


def _ensure_immediate_transaction(conn) -> None:
    if not getattr(conn, "in_transaction", False):
        _begin_immediate(conn)


def durable_source_identity(conn, table: str, row_id) -> str:
    """Devuelve la identidad UUID persistida de una fuente comercial."""
    if not _table_exists(conn, table):
        raise ValueError(f"fuente de caja inexistente: {table}")
    try:
        from local_first_db import ensure_local_id

        identity = ensure_local_id(conn, table, row_id)
    except Exception as exc:
        raise ValueError(
            f"{table} #{row_id} no tiene identidad durable local_id"
        ) from exc
    if not identity:
        raise ValueError(f"{table} #{row_id} no tiene identidad durable local_id")
    return str(identity)


def fetch_open_session(conn, station_id: Optional[str] = None) -> Optional[dict]:
    if not _table_exists(conn, "cierres_caja"):
        return None
    _ensure_cash_schema(conn)
    if station_id:
        row = conn.execute(
            """
            SELECT * FROM cierres_caja
             WHERE fecha_cierre IS NULL
               AND station_id = ?
             ORDER BY fecha_apertura DESC
             LIMIT 1
            """,
            (station_id,),
        ).fetchone()
        if row:
            return _row_dict(row)
    rows = conn.execute(
        """
        SELECT * FROM cierres_caja
         WHERE fecha_cierre IS NULL
         ORDER BY fecha_apertura DESC
        """
    ).fetchall()
    if not rows:
        return None
    if station_id:
        if len(rows) != 1:
            return None
        only = _row_dict(rows[0])
        current = str(only.get("station_id") or "")
        if current and current != station_id and not current.startswith("LEGACY-"):
            return None
        conn.execute(
            "UPDATE cierres_caja SET station_id = ? WHERE id = ? AND fecha_cierre IS NULL",
            (station_id, only["id"]),
        )
        only["station_id"] = station_id
        return only
    if len(rows) == 1:
        return _row_dict(rows[0])
    return None


def _session_is_open(session: dict) -> bool:
    if not session:
        return False
    if session.get("fecha_cierre"):
        return False
    estado = str(session.get("estado") or ESTADO_OPEN).upper()
    return estado != ESTADO_CLOSED


def claim_pending_cash_effects(conn, session: dict, station_id: str) -> int:
    """Vincula efectos físicos pendientes a una OPEN sin tocar sesiones cerradas."""
    if not _session_is_open(session) or not _table_exists(conn, "cash_movements"):
        return 0
    _ensure_immediate_transaction(conn)
    cursor = conn.execute(
        """
        UPDATE cash_movements
           SET cash_session_id = ?, station_id = ?
         WHERE cash_session_id IS NULL
           AND station_id = ?
           AND cash_effect_kind IN (?, ?)
        """,
        (
            session["id"],
            station_id,
            station_id,
            EFFECT_DRAWER_IN,
            EFFECT_DRAWER_OUT,
        ),
    )
    return max(cursor.rowcount, 0)


def record_cash_effect(
    conn,
    *,
    kind: str,
    amount,
    payment_method: str,
    direction: str,
    source_kind: str,
    source_identity,
    station_id: Optional[str] = None,
    usuario=None,
    descripcion: Optional[str] = None,
    require_open: bool = False,
) -> Tuple[bool, str, Optional[int]]:
    """Persiste exactly-once; sin OPEN deja el efecto físico pendiente."""
    _ensure_cash_schema(conn)
    if not _table_exists(conn, "cash_movements"):
        if require_open:
            return False, NO_OPEN_SESSION, None
        return True, "ledger_absent", None
    try:
        monto = money(amount)
    except ValueError as exc:
        return False, str(exc), None
    if monto <= 0:
        return False, "monto de movimiento debe ser > 0", None
    method = normalize_payment_method(payment_method)
    effect = cash_effect_for(direction, method)
    identity = str(source_identity)
    _ensure_immediate_transaction(conn)
    requested = station_id
    station = resolve_station_id(station_id) if station_id else None
    session = fetch_open_session(conn, station)
    if not _session_is_open(session) and not requested:
        session = fetch_open_session(conn, None)
    if not _session_is_open(session):
        if require_open:
            return False, NO_OPEN_SESSION, None
        if effect == EFFECT_INFORMATIONAL:
            return True, CLOSED_SESSION, None
        session = None
    station = (
        session.get("station_id") if session else None
    ) or resolve_station_id(station_id)
    session_id = session["id"] if session else None
    existing = conn.execute(
        """
        SELECT id, cash_session_id FROM cash_movements
         WHERE source_kind = ? AND source_identity = ? AND cash_effect_kind = ?
        """,
        (source_kind, identity, effect),
    ).fetchone()
    if existing:
        if session_id is not None and existing["cash_session_id"] is None:
            conn.execute(
                "UPDATE cash_movements SET cash_session_id=?, station_id=? "
                "WHERE id=? AND cash_session_id IS NULL",
                (session_id, station, existing["id"]),
            )
        return True, "already_recorded", existing["id"]
    try:
        cursor = conn.execute(
            """
            INSERT INTO cash_movements (
                local_id, cash_session_id, station_id, kind, cash_effect_kind,
                direction, amount, payment_method, source_kind, source_identity,
                usuario, descripcion
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_local_id(),
                session_id,
                station,
                kind,
                effect,
                direction,
                _money_text(monto),
                method,
                source_kind,
                identity,
                None if usuario is None else str(usuario),
                descripcion,
            ),
        )
        movement_id = cursor.lastrowid
        try:
            from repositories._outbox import encolar

            encolar(conn, "cash_movement", movement_id, "create", "cash_movements")
        except Exception:
            pass
        return True, "recorded" if session_id is not None else "pending", movement_id
    except sqlite3.IntegrityError:
        row = conn.execute(
            """
            SELECT id FROM cash_movements
             WHERE source_kind = ? AND source_identity = ? AND cash_effect_kind = ?
            """,
            (source_kind, identity, effect),
        ).fetchone()
        return True, "already_recorded", row["id"] if row else None


def attach_sale_cash_effect(
    conn,
    *,
    venta_id,
    metodo_pago,
    total,
    usuario=None,
    station_id=None,
    source_identity=None,
) -> Tuple[bool, str, Optional[int]]:
    method = normalize_payment_method(metodo_pago)
    identity = source_identity or durable_source_identity(conn, "ventas", venta_id)
    return record_cash_effect(
        conn,
        kind=KIND_SALE,
        amount=total,
        payment_method=method,
        direction=DIRECTION_IN,
        source_kind=SOURCE_VENTA,
        source_identity=identity,
        station_id=station_id,
        usuario=usuario,
        descripcion=f"Venta #{venta_id}",
    )


def attach_customer_payment_cash_effect(
    conn,
    *,
    abono_id,
    tipo_pago,
    monto,
    usuario=None,
    station_id=None,
    source_identity=None,
) -> Tuple[bool, str, Optional[int]]:
    identity = source_identity or durable_source_identity(
        conn, "abonos_ventas", abono_id
    )
    method = normalize_payment_method(tipo_pago)
    return record_cash_effect(
        conn,
        kind=KIND_CUSTOMER_PAYMENT,
        amount=monto,
        payment_method=method,
        direction=DIRECTION_IN,
        source_kind=SOURCE_ABONO_VENTA,
        source_identity=identity,
        station_id=station_id,
        usuario=usuario,
        descripcion=f"Abono cliente #{abono_id}",
    )


def attach_supplier_payment_cash_effect(
    conn,
    *,
    abono_id,
    tipo_pago,
    monto,
    usuario=None,
    station_id=None,
    descripcion=None,
    source_identity=None,
) -> Tuple[bool, str, Optional[int]]:
    identity = source_identity or durable_source_identity(
        conn, "abonos_compras", abono_id
    )
    method = normalize_payment_method(tipo_pago)
    return record_cash_effect(
        conn,
        kind=KIND_SUPPLIER_PAYMENT,
        amount=monto,
        payment_method=method,
        direction=DIRECTION_OUT,
        source_kind=SOURCE_ABONO_COMPRA,
        source_identity=identity,
        station_id=station_id,
        usuario=usuario,
        descripcion=descripcion or f"Pago proveedor #{abono_id}",
    )


def attach_reversal_cash_effect(
    conn,
    *,
    reversal_id,
    kind,
    refund_method,
    amount,
    usuario=None,
    station_id=None,
    source_identity=None,
) -> Tuple[bool, str, Optional[int]]:
    from returns_schema import KIND_SUPPLIER_RETURN

    if str(kind or "").upper() == KIND_SUPPLIER_RETURN:
        return True, "supplier_return_no_cash", None
    try:
        monto = money(amount)
    except ValueError:
        return True, "no_refund_amount", None
    if monto <= 0:
        return True, "no_refund_amount", None
    identity = source_identity or durable_source_identity(
        conn, "reversal_documents", reversal_id
    )
    method = normalize_payment_method(refund_method)
    return record_cash_effect(
        conn,
        kind=KIND_REFUND,
        amount=monto,
        payment_method=method,
        direction=DIRECTION_OUT,
        source_kind=SOURCE_REVERSAL,
        source_identity=identity,
        station_id=station_id,
        usuario=usuario,
        descripcion=f"Reverso #{reversal_id}",
    )


def recover_session_movements(conn, session: dict, station_id: str) -> int:
    """Crea exactamente un movimiento por fuente comercial huérfana de la sesión."""
    if not session or not _table_exists(conn, "cash_movements"):
        return 0
    created = claim_pending_cash_effects(conn, session, station_id)
    opened_at = session.get("fecha_apertura")
    if _table_exists(conn, "ventas"):
        rows = conn.execute(
            """
            SELECT v.id, v.local_id, v.metodo_pago, v.total, v.usuario_id
              FROM ventas v
             WHERE UPPER(COALESCE(v.estado, '')) IN ('COMPLETADA', 'COMPLETED')
               AND v.fecha >= ?
               AND NOT EXISTS (
                    SELECT 1 FROM cash_movements m
                     WHERE m.source_kind = ?
                       AND m.source_identity IN (v.local_id, CAST(v.id AS TEXT))
               )
            """,
            (opened_at, SOURCE_VENTA),
        ).fetchall()
        for row in rows:
            ok, _, _ = attach_sale_cash_effect(
                conn,
                venta_id=row["id"],
                metodo_pago=row["metodo_pago"],
                total=row["total"],
                usuario=row["usuario_id"],
                station_id=station_id,
                source_identity=row["local_id"],
            )
            if ok:
                created += 1
    if _table_exists(conn, "abonos_ventas"):
        rows = conn.execute(
            """
            SELECT a.id, a.local_id, a.tipo_pago, a.monto_abono, a.usuario
              FROM abonos_ventas a
             WHERE COALESCE(a.fecha_abono, a.created_at) >= ?
               AND NOT EXISTS (
                    SELECT 1 FROM cash_movements m
                     WHERE m.source_kind = ?
                       AND m.source_identity IN (a.local_id, CAST(a.id AS TEXT))
               )
            """,
            (opened_at, SOURCE_ABONO_VENTA),
        ).fetchall()
        for row in rows:
            ok, _, _ = attach_customer_payment_cash_effect(
                conn,
                abono_id=row["id"],
                tipo_pago=row["tipo_pago"],
                monto=row["monto_abono"],
                usuario=row["usuario"],
                station_id=station_id,
                source_identity=row["local_id"],
            )
            if ok:
                created += 1
    if _table_exists(conn, "abonos_compras"):
        rows = conn.execute(
            """
            SELECT a.id, a.local_id, a.tipo_pago, a.monto_abono, a.usuario
              FROM abonos_compras a
             WHERE COALESCE(a.fecha_abono, a.created_at) >= ?
               AND NOT EXISTS (
                    SELECT 1 FROM cash_movements m
                     WHERE m.source_kind = ?
                       AND m.source_identity IN (a.local_id, CAST(a.id AS TEXT))
               )
            """,
            (opened_at, SOURCE_ABONO_COMPRA),
        ).fetchall()
        for row in rows:
            ok, _, _ = attach_supplier_payment_cash_effect(
                conn,
                abono_id=row["id"],
                tipo_pago=row["tipo_pago"],
                monto=row["monto_abono"],
                usuario=row["usuario"],
                station_id=station_id,
                source_identity=row["local_id"],
            )
            if ok:
                created += 1
    if _table_exists(conn, "egresos_caja"):
        rows = conn.execute(
            """
            SELECT e.id, e.local_id, e.metodo_pago, e.monto, e.usuario, e.descripcion
              FROM egresos_caja e
             WHERE e.fecha_egreso >= ?
               AND LOWER(COALESCE(e.categoria, '')) NOT LIKE '%pago a proveedor%'
               AND NOT EXISTS (
                    SELECT 1 FROM cash_movements m
                     WHERE m.source_kind = ?
                       AND m.source_identity IN (e.local_id, CAST(e.id AS TEXT))
               )
            """,
            (opened_at, SOURCE_EGRESO),
        ).fetchall()
        for row in rows:
            ok, _, _ = record_cash_effect(
                conn,
                kind=KIND_EXPENSE,
                amount=row["monto"],
                payment_method=row["metodo_pago"],
                direction=DIRECTION_OUT,
                source_kind=SOURCE_EGRESO,
                source_identity=row["local_id"],
                station_id=station_id,
                usuario=row["usuario"],
                descripcion=row["descripcion"],
            )
            if ok:
                created += 1
    if _table_exists(conn, "reversal_documents"):
        rows = conn.execute(
            """
            SELECT d.id, d.local_id, d.kind, d.usuario_id, d.original_id, d.original_tipo
              FROM reversal_documents d
             WHERE d.estado = 'COMPLETED'
               AND d.kind IN ('CUSTOMER_RETURN', 'SALE_VOID')
               AND d.updated_at >= ?
               AND NOT EXISTS (
                    SELECT 1 FROM cash_movements m
                     WHERE m.source_kind = ?
                       AND m.source_identity IN (d.local_id, CAST(d.id AS TEXT))
               )
            """,
            (opened_at, SOURCE_REVERSAL),
        ).fetchall()
        for row in rows:
            method = METHOD_CASH
            if str(row["original_tipo"] or "") == "venta":
                venta = conn.execute(
                    "SELECT metodo_pago FROM ventas WHERE id = ?",
                    (row["original_id"],),
                ).fetchone()
                if venta:
                    method = venta["metodo_pago"]
            ok, _, _ = attach_reversal_cash_effect(
                conn,
                reversal_id=row["id"],
                kind=row["kind"],
                refund_method=method,
                amount=_reversal_refund_amount(conn, row["id"]),
                usuario=row["usuario_id"],
                station_id=station_id,
                source_identity=row["local_id"],
            )
            if ok:
                created += 1
    return created


def _reversal_refund_amount(conn, reversal_id) -> Decimal:
    total = Decimal("0.00")
    for line in conn.execute(
        "SELECT subtotal, cantidad_base, precio_unitario FROM reversal_lines "
        "WHERE reversal_id = ?",
        (reversal_id,),
    ).fetchall():
        raw = line["subtotal"]
        if raw not in (None, "", 0, "0"):
            total += money(raw)
            continue
        try:
            total += money(line["cantidad_base"]) * money(line["precio_unitario"] or 0)
        except ValueError:
            continue
    return total


def compute_session_summary(conn, session: dict) -> dict:
    opening = money(session.get("monto_inicial") or 0)
    empty = {
        "monto_inicial": opening,
        "efectivo": Decimal("0.00"),
        "tarjeta": Decimal("0.00"),
        "transferencia": Decimal("0.00"),
        "otros": Decimal("0.00"),
        "credito": Decimal("0.00"),
        "total": Decimal("0.00"),
        "esperado": opening,
        "cash_in": Decimal("0.00"),
        "cash_out": Decimal("0.00"),
        "egresos_efectivo": Decimal("0.00"),
        "egresos_tarjeta": Decimal("0.00"),
        "egresos_transferencia": Decimal("0.00"),
        "egresos_otros": Decimal("0.00"),
        "egresos_total": Decimal("0.00"),
        "abonos_cliente": Decimal("0.00"),
        "pagos_proveedor": Decimal("0.00"),
        "devoluciones": Decimal("0.00"),
        "cantidad_ventas": 0,
        "cantidad_operaciones": 0,
        "total_no_efectivo": Decimal("0.00"),
        "session_id": session.get("id"),
        "station_id": session.get("station_id"),
        "fecha_apertura": session.get("fecha_apertura"),
        "fecha_cierre": session.get("fecha_cierre"),
        "estado": session.get("estado") or ESTADO_OPEN,
    }
    if not _table_exists(conn, "cash_movements"):
        return empty
    rows = conn.execute(
        "SELECT * FROM cash_movements WHERE cash_session_id = ? ORDER BY id",
        (session["id"],),
    ).fetchall()
    summary = dict(empty)
    for raw in rows:
        _apply_cash_movement(summary, _row_dict(raw))
    summary["esperado"] = opening + summary["cash_in"] - summary["cash_out"]
    return summary


def _apply_cash_movement(summary: dict, row: dict) -> None:
    amount = money(row.get("amount") or 0)
    method = normalize_payment_method(row.get("payment_method"))
    effect = row.get("cash_effect_kind")
    kind = row.get("kind")
    direction = row.get("direction")
    summary["cantidad_operaciones"] += 1
    if effect == EFFECT_DRAWER_IN:
        summary["cash_in"] += amount
    elif effect == EFFECT_DRAWER_OUT:
        summary["cash_out"] += amount
    else:
        summary["total_no_efectivo"] += amount
    if kind == KIND_SALE:
        summary["cantidad_ventas"] += 1
        summary["total"] += amount
        if method == METHOD_CASH:
            summary["efectivo"] += amount
        elif method in (METHOD_CARD_DEBIT, METHOD_CARD_CREDIT):
            summary["tarjeta"] += amount
        elif method == METHOD_TRANSFER:
            summary["transferencia"] += amount
        elif method == METHOD_CREDIT:
            summary["credito"] += amount
        else:
            summary["otros"] += amount
    elif kind == KIND_CUSTOMER_PAYMENT:
        summary["abonos_cliente"] += amount
        summary["total"] += amount
        if method == METHOD_CASH:
            summary["efectivo"] += amount
        elif method in (METHOD_CARD_DEBIT, METHOD_CARD_CREDIT):
            summary["tarjeta"] += amount
        elif method == METHOD_TRANSFER:
            summary["transferencia"] += amount
        else:
            summary["otros"] += amount
    elif kind == KIND_SUPPLIER_PAYMENT:
        summary["pagos_proveedor"] += amount
        _add_egreso(summary, method, amount)
    elif kind == KIND_EXPENSE:
        _add_egreso(summary, method, amount)
    elif kind == KIND_REFUND:
        summary["devoluciones"] += amount
        if method == METHOD_CASH:
            summary["egresos_efectivo"] += amount
            summary["egresos_total"] += amount
        elif direction == DIRECTION_OUT:
            _add_egreso(summary, method, amount)
    elif kind == KIND_REINFORCEMENT and method == METHOD_CASH:
        summary["efectivo"] += amount


def compute_period_cash_summary(conn, fecha_inicio: str, fecha_fin: str) -> dict:
    """Agrega cash_movements del período. No recalcula ventas - egresos."""
    summary = _empty_summary()
    summary["fecha_inicio"] = fecha_inicio
    summary["fecha_fin"] = fecha_fin
    if not _table_exists(conn, "cash_movements"):
        return summary
    rows = conn.execute(
        """
        SELECT * FROM cash_movements
         WHERE DATE(datetime(created_at, 'localtime')) >= DATE(?)
           AND DATE(datetime(created_at, 'localtime')) <= DATE(?)
         ORDER BY id
        """,
        (fecha_inicio, fecha_fin),
    ).fetchall()
    for raw in rows:
        _apply_cash_movement(summary, _row_dict(raw))
    summary["esperado"] = summary["cash_in"] - summary["cash_out"]
    return summary


def _add_egreso(summary: dict, method: str, amount: Decimal) -> None:
    summary["egresos_total"] += amount
    if method == METHOD_CASH:
        summary["egresos_efectivo"] += amount
    elif method in (METHOD_CARD_DEBIT, METHOD_CARD_CREDIT):
        summary["egresos_tarjeta"] += amount
    elif method == METHOD_TRANSFER:
        summary["egresos_transferencia"] += amount
    else:
        summary["egresos_otros"] += amount


def _empty_summary() -> dict:
    zero = Decimal("0.00")
    return {
        "monto_inicial": zero,
        "efectivo": zero,
        "tarjeta": zero,
        "transferencia": zero,
        "otros": zero,
        "credito": zero,
        "total": zero,
        "esperado": zero,
        "cash_in": zero,
        "cash_out": zero,
        "egresos_efectivo": zero,
        "egresos_tarjeta": zero,
        "egresos_transferencia": zero,
        "egresos_otros": zero,
        "egresos_total": zero,
        "abonos_cliente": zero,
        "pagos_proveedor": zero,
        "devoluciones": zero,
        "cantidad_ventas": 0,
        "cantidad_operaciones": 0,
        "total_no_efectivo": zero,
        "session_id": None,
        "station_id": None,
        "fecha_apertura": None,
        "fecha_cierre": None,
        "estado": ESTADO_CLOSED,
    }


class CajaService:
    """Autoridad local de caja. Una sesión OPEN por estación."""

    def __init__(self, db_manager, auth_manager, station_id: Optional[str] = None):
        self.db = db_manager
        self.auth = auth_manager
        self.station_id = station_id

    def _station(self) -> str:
        return resolve_station_id(self.station_id)

    def _usuario(self):
        return getattr(self.auth, "usuario_actual", None)

    def _require_admin(self) -> Optional[str]:
        if not is_cash_admin(self._usuario()):
            return CASH_ADMIN_DENIED
        return None

    def _require_admin_read(self) -> None:
        """Impide exponer arqueo e información administrativa por el servicio."""
        denied = self._require_admin()
        if denied:
            raise PermissionError(denied)

    def estacion_actual(self) -> str:
        return self._station()

    def obtener_caja_abierta(self) -> Optional[dict]:
        if not self._usuario():
            return None
        conn = self.db.conectar()
        try:
            session = fetch_open_session(conn, self._station())
            if session:
                if not is_cash_admin(self._usuario()):
                    session = {
                        "id": session.get("id"),
                        "station_id": session.get("station_id") or self._station(),
                        "estado": session.get("estado") or ESTADO_OPEN,
                        "fecha_apertura": session.get("fecha_apertura"),
                    }
                else:
                    session["monto_inicial"] = money(session.get("monto_inicial") or 0)
            try:
                conn.commit()
            except Exception:
                pass
            return session
        finally:
            conn.close()

    def abrir_caja(self, monto_inicial) -> Tuple[bool, str]:
        denied = self._require_admin()
        if denied:
            return False, denied
        try:
            monto = money(monto_inicial)
        except ValueError as exc:
            return False, str(exc)
        if monto < 0:
            return False, "monto_apertura debe ser >= 0"
        station = self._station()
        usuario = self._usuario()
        conn = self.db.conectar()
        try:
            _begin_immediate(conn)
            existing = fetch_open_session(conn, station)
            if existing:
                return False, (
                    f"{EXISTING_OPEN_SESSION}: Ya tiene una caja abierta. "
                    "Debe cerrarla primero."
                )
            cursor = conn.execute(
                """
                INSERT INTO cierres_caja (
                    usuario_id, monto_inicial, fecha_apertura,
                    local_id, station_id, estado
                ) VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?, ?)
                """,
                (usuario.id, _money_text(monto), new_local_id(), station, ESTADO_OPEN),
            )
            caja_id = cursor.lastrowid
            opened_session = fetch_open_session(conn, station)
            claim_pending_cash_effects(conn, opened_session, station)
            from repositories._outbox import encolar

            encolar(conn, "cash_session", caja_id, "create", "cierres_caja")
            conn.commit()
            if hasattr(self.auth, "registrar_auditoria"):
                self.auth.registrar_auditoria(
                    usuario.id,
                    "ABRIR_CAJA",
                    "Caja",
                    f"Caja abierta estación {station} monto {_money_text(monto)}",
                )
            return True, "Caja abierta exitosamente"
        except sqlite3.IntegrityError:
            try:
                conn.rollback()
            except Exception:
                pass
            return False, (
                f"{EXISTING_OPEN_SESSION}: Ya tiene una caja abierta. "
                "Debe cerrarla primero."
            )
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            return False, f"Error al abrir caja: {exc}"
        finally:
            conn.close()

    def obtener_resumen_cierre(self) -> dict:
        self._require_admin_read()
        return self.obtener_resumen_sesion()

    def obtener_resumen_dia(self) -> dict:
        self._require_admin_read()
        return self.obtener_resumen_sesion()

    def obtener_resumen_sesion(self, session: Optional[dict] = None) -> dict:
        self._require_admin_read()
        conn = self.db.conectar()
        try:
            current = session or fetch_open_session(conn, self._station())
            if not current:
                return _empty_summary()
            recover_session_movements(conn, current, current.get("station_id") or self._station())
            try:
                conn.commit()
            except Exception:
                pass
            return compute_session_summary(conn, current)
        finally:
            conn.close()

    def expected_cash(self, session: Optional[dict] = None) -> Decimal:
        self._require_admin_read()
        return money(self.obtener_resumen_sesion(session)["esperado"])

    def cerrar_caja(self, monto_real, observaciones: str = None) -> Tuple[bool, str]:
        denied = self._require_admin()
        if denied:
            return False, denied
        try:
            contado = money(monto_real)
        except ValueError as exc:
            return False, str(exc)
        if contado < 0:
            return False, "monto_contado debe ser >= 0"
        station = self._station()
        usuario = self._usuario()
        conn = self.db.conectar()
        try:
            _begin_immediate(conn)
            session = fetch_open_session(conn, station)
            if not session:
                return False, f"{NO_OPEN_SESSION}: No hay una caja abierta"
            recover_session_movements(conn, session, station)
            resumen = compute_session_summary(conn, session)
            esperado = money(resumen["esperado"])
            diferencia = contado - esperado
            cursor = conn.execute(
                """
                UPDATE cierres_caja SET
                    fecha_cierre = CURRENT_TIMESTAMP,
                    estado = ?,
                    usuario_cierre_id = ?,
                    ventas_efectivo = ?,
                    ventas_tarjeta = ?,
                    ventas_transferencia = ?,
                    ventas_otros = ?,
                    total_ventas = ?,
                    monto_esperado = ?,
                    monto_real = ?,
                    diferencia = ?,
                    observaciones = ?,
                    gastos = ?
                WHERE id = ? AND fecha_cierre IS NULL
                """,
                (
                    ESTADO_CLOSED,
                    usuario.id,
                    _money_text(resumen["efectivo"]),
                    _money_text(resumen["tarjeta"]),
                    _money_text(resumen["transferencia"]),
                    _money_text(resumen["otros"]),
                    _money_text(resumen["total"]),
                    _money_text(esperado),
                    _money_text(contado),
                    _money_text(diferencia),
                    observaciones,
                    _money_text(resumen["egresos_total"]),
                    session["id"],
                ),
            )
            if cursor.rowcount == 0:
                conn.rollback()
                return False, f"{ALREADY_CLOSED}: La caja ya está cerrada"
            from repositories._outbox import encolar

            encolar(conn, "cash_session", session["id"], "update", "cierres_caja")
            conn.commit()
            if hasattr(self.auth, "registrar_auditoria"):
                self.auth.registrar_auditoria(
                    usuario.id,
                    "CERRAR_CAJA",
                    "Caja",
                    f"Caja cerrada. Esperado: {esperado}, Real: {contado}, "
                    f"Diferencia: {diferencia}",
                )
            mensaje = f"Caja cerrada. Diferencia: ${abs(diferencia):,.2f}"
            if diferencia > 0:
                mensaje += " (Sobrante)"
            elif diferencia < 0:
                mensaje += " (Faltante)"
            else:
                mensaje += " (CUADRA)"
            return True, mensaje
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            return False, f"Error al cerrar caja: {exc}"
        finally:
            conn.close()

    def registrar_egreso(
        self,
        monto,
        categoria: str,
        descripcion: str,
        metodo_pago: str,
        usuario: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[int]]:
        if not self._usuario():
            return False, "Usuario no identificado", None
        denied = self._require_admin()
        if denied:
            return False, denied, None
        try:
            valor = money(monto)
        except ValueError as exc:
            return False, str(exc), None
        if valor <= 0:
            return False, "monto de movimiento debe ser > 0", None
        if not str(categoria or "").strip() or not str(descripcion or "").strip():
            return False, "categoría y descripción son obligatorias", None
        station = self._station()
        conn = self.db.conectar()
        try:
            _begin_immediate(conn)
            session = fetch_open_session(conn, station)
            if not _session_is_open(session):
                return False, f"{NO_OPEN_SESSION}: Debe abrir una caja primero", None
            who = usuario or getattr(self._usuario(), "username", None) or str(self._usuario().id)
            cursor = conn.execute(
                """
                INSERT INTO egresos_caja
                    (monto, categoria, descripcion, metodo_pago, fecha_egreso, usuario, id_caja)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?)
                """,
                (
                    _money_text(valor),
                    categoria.strip(),
                    descripcion.strip(),
                    normalize_payment_method(metodo_pago),
                    who,
                    session["id"],
                ),
            )
            egreso_id = cursor.lastrowid
            from repositories._outbox import encolar

            encolar(conn, "cash_expense", egreso_id, "create", "egresos_caja")
            egreso_identity = durable_source_identity(conn, "egresos_caja", egreso_id)
            ok, msg, _ = record_cash_effect(
                conn,
                kind=KIND_EXPENSE,
                amount=valor,
                payment_method=metodo_pago,
                direction=DIRECTION_OUT,
                source_kind=SOURCE_EGRESO,
                source_identity=egreso_identity,
                station_id=station,
                usuario=who,
                descripcion=descripcion.strip(),
                require_open=True,
            )
            if not ok:
                conn.rollback()
                return False, msg, None
            conn.commit()
            return True, "Egreso registrado", egreso_id
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            return False, f"Error al registrar egreso: {exc}", None
        finally:
            conn.close()

    def registrar_ingreso_manual(
        self,
        monto,
        motivo: str,
        usuario: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[int]]:
        if not self._usuario():
            return False, "Usuario no identificado", None
        denied = self._require_admin()
        if denied:
            return False, denied, None
        try:
            valor = money(monto)
        except ValueError as exc:
            return False, str(exc), None
        if valor <= 0:
            return False, "monto de movimiento debe ser > 0", None
        if not str(motivo or "").strip():
            return False, "motivo obligatorio", None
        identity = new_local_id()
        conn = self.db.conectar()
        try:
            _begin_immediate(conn)
            ok, msg, movement_id = record_cash_effect(
                conn,
                kind=KIND_REINFORCEMENT,
                amount=valor,
                payment_method=METHOD_CASH,
                direction=DIRECTION_IN,
                source_kind=SOURCE_INGRESO,
                source_identity=identity,
                station_id=self._station(),
                usuario=usuario or getattr(self._usuario(), "username", None),
                descripcion=str(motivo).strip(),
                require_open=True,
            )
            if not ok:
                conn.rollback()
                return False, msg, None
            conn.commit()
            return True, "Ingreso manual registrado", movement_id
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            return False, f"Error al registrar ingreso: {exc}", None
        finally:
            conn.close()

    def obtener_historial_cierres(self, limite: int = 30) -> list:
        if not self._usuario():
            return []
        self._require_admin_read()
        conn = self.db.conectar()
        try:
            rows = conn.execute(
                """
                SELECT c.*, u.nombre_completo as usuario_nombre
                  FROM cierres_caja c
                  JOIN usuarios u ON c.usuario_id = u.id
                 WHERE c.fecha_cierre IS NOT NULL
                   AND (c.station_id = ? OR c.station_id IS NULL)
                 ORDER BY c.fecha_cierre DESC
                 LIMIT ?
                """,
                (self._station(), limite),
            ).fetchall()
            return [_row_dict(row) for row in rows]
        finally:
            conn.close()

    def obtener_ultimo_cierre_usuario(self) -> Optional[dict]:
        if not self._usuario():
            return None
        self._require_admin_read()
        conn = self.db.conectar()
        try:
            row = conn.execute(
                """
                SELECT * FROM cierres_caja
                 WHERE usuario_id = ?
                   AND fecha_cierre IS NOT NULL
                   AND (station_id = ? OR station_id IS NULL)
                 ORDER BY fecha_cierre DESC
                 LIMIT 1
                """,
                (self._usuario().id, self._station()),
            ).fetchone()
            return _row_dict(row) if row else None
        finally:
            conn.close()

    def obtener_resumen_periodo(self, fecha_inicio: str, fecha_fin: str) -> dict:
        self._require_admin_read()
        conn = self.db.conectar()
        try:
            return compute_period_cash_summary(conn, fecha_inicio, fecha_fin)
        finally:
            conn.close()
