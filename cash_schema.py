# -*- coding: utf-8 -*-
"""Esquema mínimo 3D: sesión de caja por estación + ledger operacional."""
from __future__ import annotations

import uuid

import schema_bootstrap

SQLITE_MIGRATION_VERSION = "20260816_009"

ESTADO_OPEN = "OPEN"
ESTADO_CLOSED = "CLOSED"

DIRECTION_IN = "IN"
DIRECTION_OUT = "OUT"

EFFECT_DRAWER_IN = "DRAWER_IN"
EFFECT_DRAWER_OUT = "DRAWER_OUT"
EFFECT_INFORMATIONAL = "INFORMATIONAL"

KIND_SALE = "SALE"
KIND_CUSTOMER_PAYMENT = "CUSTOMER_PAYMENT"
KIND_SUPPLIER_PAYMENT = "SUPPLIER_PAYMENT"
KIND_EXPENSE = "EXPENSE"
KIND_REFUND = "REFUND"
KIND_REINFORCEMENT = "REINFORCEMENT"

SOURCE_VENTA = "venta"
SOURCE_ABONO_VENTA = "abono_venta"
SOURCE_ABONO_COMPRA = "abono_compra"
SOURCE_EGRESO = "egreso_caja"
SOURCE_REVERSAL = "reversal"
SOURCE_INGRESO = "ingreso_manual"

METHOD_CASH = "EFECTIVO"
METHOD_CARD_DEBIT = "TARJETA_DEBITO"
METHOD_CARD_CREDIT = "TARJETA_CREDITO"
METHOD_TRANSFER = "TRANSFERENCIA"
METHOD_CREDIT = "CREDITO"

EXISTING_OPEN_SESSION = "EXISTING_OPEN_SESSION"
NO_OPEN_SESSION = "NO_OPEN_SESSION"
ALREADY_CLOSED = "ALREADY_CLOSED"
CLOSED_SESSION = "CLOSED_SESSION"

_METHOD_ALIASES = {
    "EFECTIVO": METHOD_CASH,
    "CASH": METHOD_CASH,
    "TARJETA": METHOD_CARD_DEBIT,
    "TARJETA_DEBITO": METHOD_CARD_DEBIT,
    "TARJETA_CREDITO": METHOD_CARD_CREDIT,
    "DEBITO": METHOD_CARD_DEBIT,
    "CREDITO_TARJETA": METHOD_CARD_CREDIT,
    "TRANSFERENCIA": METHOD_TRANSFER,
    "TRANSFER": METHOD_TRANSFER,
    "CREDITO": METHOD_CREDIT,
    "CHEQUE": "CHEQUE",
    "DEPOSITO": METHOD_TRANSFER,
    "DEPÓSITO": METHOD_TRANSFER,
}


def normalize_payment_method(raw) -> str:
    token = str(raw or "").strip().upper().replace(" ", "_")
    token = token.replace("Á", "A").replace("É", "E").replace("Í", "I")
    token = token.replace("Ó", "O").replace("Ú", "O")
    return _METHOD_ALIASES.get(token, token or METHOD_CASH)


def is_cash_method(method) -> bool:
    return normalize_payment_method(method) == METHOD_CASH


def new_local_id() -> str:
    return str(uuid.uuid4())


def ensure_sqlite_cash_operational_schema(conn) -> None:
    """Materializa 3D sin commit; el MigrationRunner es atómico."""
    if not schema_bootstrap.is_sqlite_connection(conn):
        raise schema_bootstrap.SchemaBootstrapError(
            "El esquema SQLite de caja no admite PostgreSQL"
        )

    has_sessions = schema_bootstrap.table_exists(conn, "cierres_caja")
    if has_sessions:
        schema_bootstrap.add_column_if_missing(
            conn, "cierres_caja", "local_id", "TEXT"
        )
        schema_bootstrap.add_column_if_missing(
            conn, "cierres_caja", "station_id", "TEXT"
        )
        schema_bootstrap.add_column_if_missing(
            conn, "cierres_caja", "estado", "TEXT"
        )
        schema_bootstrap.add_column_if_missing(
            conn, "cierres_caja", "usuario_cierre_id", "INTEGER"
        )
        _backfill_sessions(conn)
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_cierres_caja_open_station
            ON cierres_caja(station_id)
            WHERE fecha_cierre IS NULL
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_cierres_caja_local_id
            ON cierres_caja(local_id)
            WHERE local_id IS NOT NULL
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cierres_caja_station "
            "ON cierres_caja(station_id, fecha_apertura)"
        )

    fk = ""
    if has_sessions:
        fk = (
            ", FOREIGN KEY (cash_session_id) REFERENCES cierres_caja(id)"
        )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS cash_movements (
            id INTEGER PRIMARY KEY,
            local_id TEXT NOT NULL UNIQUE,
            cash_session_id INTEGER,
            station_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            cash_effect_kind TEXT NOT NULL,
            direction TEXT NOT NULL,
            amount TEXT NOT NULL,
            payment_method TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            source_identity TEXT NOT NULL,
            usuario TEXT,
            descripcion TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            {fk}
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_cash_movements_source
        ON cash_movements(source_kind, source_identity, cash_effect_kind)
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cash_movements_session "
        "ON cash_movements(cash_session_id, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cash_movements_station "
        "ON cash_movements(station_id, cash_session_id)"
    )


def _backfill_sessions(conn) -> None:
    rows = conn.execute(
        "SELECT id, local_id, station_id, estado, fecha_cierre FROM cierres_caja"
    ).fetchall()
    for row in rows:
        session_id = row["id"]
        local_id = row["local_id"]
        station_id = row["station_id"]
        estado = row["estado"]
        closed = row["fecha_cierre"] is not None
        updates = []
        values = []
        if not local_id:
            updates.append("local_id = ?")
            values.append(new_local_id())
        if not station_id:
            updates.append("station_id = ?")
            values.append(f"LEGACY-{session_id}")
        expected_estado = ESTADO_CLOSED if closed else ESTADO_OPEN
        if str(estado or "") != expected_estado:
            updates.append("estado = ?")
            values.append(expected_estado)
        if updates:
            values.append(session_id)
            conn.execute(
                f"UPDATE cierres_caja SET {', '.join(updates)} WHERE id = ?",
                values,
            )
