# -*- coding: utf-8 -*-
"""Ledger local de comandos de inventario (Fase 1C).

Persiste una intención empresarial (command) y sus operaciones por producto.
No aplica stock. No es autoridad. No entra al sync LWW genérico.

request_hash (SHA-256 hex) cubre exactamente:

* command_id
* tipo
* documento_tipo
* documento_local_id
* operations ordenadas por line_no: operation_id, producto_local_id, delta_scaled

Excluidos: device_id, usuario_id, timestamps, estado, resultado, motivo.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, List, Mapping, Optional, Sequence, Tuple, Union

import schema_bootstrap
from schema_bootstrap import SchemaBootstrapError


QUANTITY_SCALE = 1000

COMMAND_TYPES = (
    "VENTA",
    "COMPRA",
    "DEVOLUCION",
    "AJUSTE",
    "MEZCLA",
    "RECEPCION",
)
COMMAND_STATES = ("PERSISTED", "APPLIED", "REJECTED")
LEDGER_STATE_PERSISTED = "PERSISTED"
LEDGER_STATE_APPLIED = "APPLIED"

# Clase de intención local (SQLite). No es un estado de CHECK.
# AUTHORITATIVE: puede enviarse al coordinador cuando el cutover está ON.
# LEGACY_OBSERVED: observación pre-cutover; NUNCA se transmite, ni después
# del cutover. Evita que un backlog de ventas legacy se aplique dos veces
# tras sembrar inventory_balances desde el stock actual (1E.3).
INTENT_CLASS_AUTHORITATIVE = "AUTHORITATIVE"
INTENT_CLASS_LEGACY_OBSERVED = "LEGACY_OBSERVED"
INTENT_CLASSES = (INTENT_CLASS_AUTHORITATIVE, INTENT_CLASS_LEGACY_OBSERVED)

# Mapa documental comando → kardex legado. 1C no aplica el signo; solo lo
# documenta. delta_scaled == 0 se rechaza: no hay línea de inventario vacía.
COMMAND_SIGN_POLICY = {
    "VENTA": "negativo (kardex SALIDA_VENTA)",
    "COMPRA": "positivo (kardex ENTRADA_COMPRA)",
    "RECEPCION": "positivo; mismo sentido que COMPRA (ADR-0002 RECEPCION)",
    "DEVOLUCION": "positivo si reingresa stock (kardex ENTRADA_DEVOLUCION); "
    "negativo si sale stock",
    "AJUSTE": "positivo o negativo (ENTRADA_AJUSTE / SALIDA_AJUSTE)",
    "MEZCLA": "mixto: consumo negativo y producción positiva en el mismo comando",
}

REMOTE_LEDGER_MIGRATION_FILENAME = "supabase_inventory_ledger.sql"

QuantityInput = Union[int, str, Decimal]


class InventoryLedgerError(Exception):
    """Error de validación o persistencia del ledger. La TX no queda a medias."""


class IdempotencyConflictError(InventoryLedgerError):
    """Mismo command_id con payload semántico distinto."""


class QuantityScaleError(InventoryLedgerError):
    """Cantidad no representable en fixed-point de 3 decimales."""


class UnknownProductError(InventoryLedgerError):
    """producto_local_id no existe como identidad global de productos."""


class ZeroDeltaError(InventoryLedgerError):
    """delta_scaled == 0 no tiene razón de dominio en 1C."""


class DuplicateOperationError(InventoryLedgerError):
    """operation_id ya pertenece a otro comando."""


@dataclass(frozen=True)
class InventoryOperationRecord:
    operation_id: str
    command_id: str
    producto_local_id: str
    delta_scaled: int
    line_no: int
    expected_base_scaled: Optional[int] = None


@dataclass(frozen=True)
class InventoryCommandRecord:
    command_id: str
    tipo: str
    documento_tipo: Optional[str]
    documento_local_id: Optional[str]
    device_id: str
    usuario_id: Optional[int]
    request_hash: str
    estado: str
    resultado: str
    motivo: Optional[str]
    created_at: str
    updated_at: str
    operations: Tuple[InventoryOperationRecord, ...]
    replayed: bool
    intent_class: str = INTENT_CLASS_LEGACY_OBSERVED


def quantity_to_scaled(value: QuantityInput) -> int:
    """Convierte cantidad comercial a entero escalado (1000 = 1 unidad).

    Rechaza ``float``. Parsea con Decimal; máximo 3 decimales.
    """
    if isinstance(value, float):
        raise QuantityScaleError(
            "El ledger no acepta float; use Decimal, str o int"
        )
    if isinstance(value, bool) or not isinstance(value, (int, str, Decimal)):
        raise QuantityScaleError(
            f"Cantidad de tipo no admitido: {type(value).__name__}"
        )
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise QuantityScaleError(f"Cantidad no numérica: {value!r}") from exc
    if not decimal_value.is_finite():
        raise QuantityScaleError(f"Cantidad no finita: {value!r}")
    exponent = decimal_value.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -3:
        raise QuantityScaleError(
            "Más de 3 decimales no caben en la escala 1000"
        )
    scaled = decimal_value * QUANTITY_SCALE
    if scaled != scaled.to_integral_value():
        raise QuantityScaleError(
            f"No se pudo convertir exactamente a entero escalado: {value!r}"
        )
    return int(scaled)


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def command_request_hash(
    *,
    command_id: str,
    tipo: str,
    documento_tipo: Optional[str],
    documento_local_id: Optional[str],
    operations: Sequence[Mapping[str, Any]],
) -> str:
    """Fingerprint determinístico del payload semántico."""
    normalized_ops = sorted(
        (
            {
                "delta_scaled": int(op["delta_scaled"]),
                "line_no": int(op["line_no"]),
                "operation_id": str(op["operation_id"]),
                "producto_local_id": str(op["producto_local_id"]),
            }
            for op in operations
        ),
        key=lambda item: item["line_no"],
    )
    payload = {
        "command_id": str(command_id),
        "documento_local_id": documento_local_id,
        "documento_tipo": documento_tipo,
        "operations": normalized_ops,
        "tipo": str(tipo),
    }
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8"))
    return digest.hexdigest()


def _require_uuid(value: Any, field: str) -> str:
    text = str(value or "").strip()
    try:
        parsed = uuid.UUID(text)
    except (ValueError, AttributeError, TypeError) as exc:
        raise InventoryLedgerError(f"{field} debe ser un UUID: {value!r}") from exc
    return str(parsed)


def _optional_uuid(value: Any, field: str) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_uuid(value, field)


def _normalize_tipo(tipo: Any) -> str:
    text = str(tipo or "").strip().upper()
    if text not in COMMAND_TYPES:
        raise InventoryLedgerError(
            f"tipo de comando desconocido: {tipo!r}. "
            f"Admitidos: {', '.join(COMMAND_TYPES)}"
        )
    return text


def _normalize_operations(
    command_id: str, operations: Sequence[Mapping[str, Any]]
) -> List[dict]:
    if not operations:
        raise InventoryLedgerError("El comando debe tener al menos una operación")
    normalized: List[dict] = []
    seen_line = set()
    seen_op = set()
    for raw in operations:
        if not isinstance(raw, Mapping):
            raise InventoryLedgerError("Cada operación debe ser un mapeo")
        operation_id = _require_uuid(raw.get("operation_id"), "operation_id")
        producto_local_id = _require_uuid(
            raw.get("producto_local_id"), "producto_local_id"
        )
        try:
            line_no = int(raw["line_no"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InventoryLedgerError("line_no debe ser un entero") from exc
        if line_no < 1:
            raise InventoryLedgerError("line_no debe ser >= 1")
        if line_no in seen_line:
            raise InventoryLedgerError(
                f"line_no duplicado en el comando: {line_no}"
            )
        if operation_id in seen_op:
            raise InventoryLedgerError(
                f"operation_id duplicado en el comando: {operation_id}"
            )
        seen_line.add(line_no)
        seen_op.add(operation_id)
        if "delta_scaled" in raw and raw["delta_scaled"] is not None:
            if isinstance(raw["delta_scaled"], float) or isinstance(
                raw.get("delta"), float
            ):
                raise QuantityScaleError(
                    "El ledger no acepta float; use Decimal, str o int"
                )
            if isinstance(raw["delta_scaled"], bool):
                raise QuantityScaleError("delta_scaled no puede ser bool")
            try:
                scaled_decimal = (
                    raw["delta_scaled"]
                    if isinstance(raw["delta_scaled"], Decimal)
                    else Decimal(str(raw["delta_scaled"]))
                )
            except (InvalidOperation, ValueError) as exc:
                raise QuantityScaleError("delta_scaled debe ser entero") from exc
            if scaled_decimal != scaled_decimal.to_integral_value():
                raise QuantityScaleError("delta_scaled debe ser entero exacto")
            delta_scaled = int(scaled_decimal)
        else:
            if "delta" not in raw:
                raise InventoryLedgerError(
                    "Cada operación requiere delta o delta_scaled"
                )
            delta_scaled = quantity_to_scaled(raw["delta"])
        if delta_scaled == 0:
            raise ZeroDeltaError(
                "delta 0 no tiene razón de dominio en el ledger; "
                "una línea de inventario vacía no se persiste"
            )
        expected_base = raw.get("expected_base_scaled")
        if expected_base is not None:
            if isinstance(expected_base, bool) or isinstance(expected_base, float):
                raise QuantityScaleError(
                    "expected_base_scaled debe ser entero; no float"
                )
            try:
                expected_base = int(expected_base)
            except (TypeError, ValueError) as exc:
                raise QuantityScaleError(
                    "expected_base_scaled debe ser entero"
                ) from exc
        normalized.append(
            {
                "operation_id": operation_id,
                "command_id": command_id,
                "producto_local_id": producto_local_id,
                "delta_scaled": delta_scaled,
                "line_no": line_no,
                "expected_base_scaled": expected_base,
            }
        )
    normalized.sort(key=lambda item: item["line_no"])
    return normalized


def sqlite_ledger_statements() -> Tuple[str, ...]:
    """DDL SQLite idempotente. No es SQL PostgreSQL."""
    return (
        """
        CREATE TABLE IF NOT EXISTS inventory_commands (
            command_id TEXT PRIMARY KEY,
            tipo TEXT NOT NULL CHECK (
                tipo IN (
                    'VENTA', 'COMPRA', 'DEVOLUCION',
                    'AJUSTE', 'MEZCLA', 'RECEPCION'
                )
            ),
            documento_tipo TEXT,
            documento_local_id TEXT,
            device_id TEXT NOT NULL,
            usuario_id INTEGER,
            request_hash TEXT NOT NULL,
            estado TEXT NOT NULL CHECK (
                estado IN ('PERSISTED', 'APPLIED', 'REJECTED')
            ),
            resultado TEXT NOT NULL CHECK (
                resultado IN ('PERSISTED', 'APPLIED', 'REJECTED')
            ),
            motivo TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            intent_class TEXT NOT NULL DEFAULT 'LEGACY_OBSERVED' CHECK (
                intent_class IN ('AUTHORITATIVE', 'LEGACY_OBSERVED')
            )
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS inventory_operations (
            operation_id TEXT PRIMARY KEY,
            command_id TEXT NOT NULL,
            producto_local_id TEXT NOT NULL,
            delta_scaled INTEGER NOT NULL,
            line_no INTEGER NOT NULL,
            expected_base_scaled INTEGER,
            FOREIGN KEY (command_id) REFERENCES inventory_commands(command_id),
            UNIQUE (command_id, line_no)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_inventory_operations_command "
        "ON inventory_operations(command_id)",
        "CREATE INDEX IF NOT EXISTS idx_inventory_operations_producto "
        "ON inventory_operations(producto_local_id)",
        "CREATE INDEX IF NOT EXISTS idx_inventory_commands_hash "
        "ON inventory_commands(request_hash)",
        "CREATE INDEX IF NOT EXISTS idx_inventory_commands_intent "
        "ON inventory_commands(intent_class)",
    )


def postgres_ledger_sql() -> str:
    """DDL PostgreSQL del ledger. Nunca ejecutar contra SQLite.

    UUID como TEXT: paridad con productos.local_id (gen_random_uuid()::text).
    delta_scaled es BIGINT. Sin FK a productos(local_id). Sin RPC de stock.
    """
    return """\
-- FERREPRO Fase 1C — ledger de comandos de inventario.
-- SOLO PostgreSQL/Supabase. Nunca ejecutar contra SQLite.
-- Idempotente. No modifica productos.stock. No crea RPC.
-- Identidades UUID como TEXT (paridad con productos.local_id).
-- Tablas append-only/idempotentes: no entran al sync LWW genérico.

CREATE TABLE IF NOT EXISTS inventory_commands (
    command_id TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (
        tipo IN (
            'VENTA', 'COMPRA', 'DEVOLUCION',
            'AJUSTE', 'MEZCLA', 'RECEPCION'
        )
    ),
    documento_tipo TEXT,
    documento_local_id TEXT,
    device_id TEXT NOT NULL,
    usuario_id INTEGER,
    request_hash TEXT NOT NULL,
    estado TEXT NOT NULL CHECK (
        estado IN ('PERSISTED', 'APPLIED', 'REJECTED')
    ),
    resultado TEXT NOT NULL CHECK (
        resultado IN ('PERSISTED', 'APPLIED', 'REJECTED')
    ),
    motivo TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CONSTRAINT pk_inventory_commands PRIMARY KEY (command_id)
);

CREATE TABLE IF NOT EXISTS inventory_operations (
    operation_id TEXT NOT NULL,
    command_id TEXT NOT NULL,
    producto_local_id TEXT NOT NULL,
    delta_scaled BIGINT NOT NULL,
    line_no INTEGER NOT NULL,
    CONSTRAINT pk_inventory_operations PRIMARY KEY (operation_id),
    CONSTRAINT fk_inventory_operations_command
        FOREIGN KEY (command_id) REFERENCES inventory_commands(command_id),
    CONSTRAINT uq_inventory_operations_command_line UNIQUE (command_id, line_no)
);

CREATE INDEX IF NOT EXISTS idx_inventory_operations_command
    ON inventory_operations(command_id);
CREATE INDEX IF NOT EXISTS idx_inventory_operations_producto
    ON inventory_operations(producto_local_id);
CREATE INDEX IF NOT EXISTS idx_inventory_commands_hash
    ON inventory_commands(request_hash);

-- Compatibilidad con bases ya creadas por Fase 1C/1D (nombres implícitos).
DO $ferrepro_ledger_rename$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM pg_catalog.pg_constraint c
          JOIN pg_catalog.pg_class t ON t.oid = c.conrelid
          JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
         WHERE n.nspname = 'public'
           AND t.relname = 'inventory_commands'
           AND c.conname = 'inventory_commands_pkey'
    ) THEN
        ALTER TABLE public.inventory_commands
            RENAME CONSTRAINT inventory_commands_pkey TO pk_inventory_commands;
    END IF;
    IF EXISTS (
        SELECT 1
          FROM pg_catalog.pg_constraint c
          JOIN pg_catalog.pg_class t ON t.oid = c.conrelid
          JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
         WHERE n.nspname = 'public'
           AND t.relname = 'inventory_operations'
           AND c.conname = 'inventory_operations_pkey'
    ) THEN
        ALTER TABLE public.inventory_operations
            RENAME CONSTRAINT inventory_operations_pkey TO pk_inventory_operations;
    END IF;
    IF EXISTS (
        SELECT 1
          FROM pg_catalog.pg_constraint c
          JOIN pg_catalog.pg_class t ON t.oid = c.conrelid
          JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
         WHERE n.nspname = 'public'
           AND t.relname = 'inventory_operations'
           AND c.conname = 'inventory_operations_command_id_line_no_key'
    ) THEN
        ALTER TABLE public.inventory_operations
            RENAME CONSTRAINT inventory_operations_command_id_line_no_key
            TO uq_inventory_operations_command_line;
    END IF;
    IF EXISTS (
        SELECT 1
          FROM pg_catalog.pg_constraint c
          JOIN pg_catalog.pg_class t ON t.oid = c.conrelid
          JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
         WHERE n.nspname = 'public'
           AND t.relname = 'inventory_operations'
           AND c.conname = 'inventory_operations_command_id_fkey'
    ) THEN
        ALTER TABLE public.inventory_operations
            RENAME CONSTRAINT inventory_operations_command_id_fkey
            TO fk_inventory_operations_command;
    END IF;
END
$ferrepro_ledger_rename$;
"""


def ensure_inventory_ledger_schema(conn) -> None:
    """Crea las tablas del ledger en SQLite. Idempotente. No toca stock."""
    if not schema_bootstrap.is_sqlite_connection(conn):
        raise SchemaBootstrapError(
            "ensure_inventory_ledger_schema solo aplica a SQLite"
        )
    for statement in sqlite_ledger_statements():
        if "inventory_commands(intent_class)" in statement:
            continue
        conn.execute(statement)
    _ensure_intent_class_column(conn)
    _ensure_expected_base_column(conn)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_inventory_commands_intent "
        "ON inventory_commands(intent_class)"
    )


def _ensure_intent_class_column(conn) -> None:
    """Migración idempotente 1E.1: columna local que no viaja a PostgreSQL."""
    rows = conn.execute("PRAGMA table_info(inventory_commands)").fetchall()
    cols = {
        (row["name"] if hasattr(row, "keys") else row[1])
        for row in rows
    }
    if "intent_class" in cols:
        return
    conn.execute(
        "ALTER TABLE inventory_commands "
        "ADD COLUMN intent_class TEXT NOT NULL DEFAULT 'LEGACY_OBSERVED'"
    )


def _ensure_expected_base_column(conn) -> None:
    """1E.2: CAS absoluto. No forma parte del request_hash."""
    rows = conn.execute("PRAGMA table_info(inventory_operations)").fetchall()
    cols = {
        (row["name"] if hasattr(row, "keys") else row[1])
        for row in rows
    }
    if "expected_base_scaled" in cols:
        return
    conn.execute(
        "ALTER TABLE inventory_operations "
        "ADD COLUMN expected_base_scaled INTEGER"
    )


def _normalize_intent_class(value: Any) -> str:
    """Fail-closed: ausencia/vacío = LEGACY_OBSERVED (no transmissible).

    AUTHORITATIVE solo cuando el caller lo pide de forma explícita.
    """
    if value is None:
        return INTENT_CLASS_LEGACY_OBSERVED
    text = str(value).strip().upper()
    if text == "":
        return INTENT_CLASS_LEGACY_OBSERVED
    if text not in INTENT_CLASSES:
        raise InventoryLedgerError(
            f"intent_class desconocido: {value!r}. "
            f"Admitidos: {', '.join(INTENT_CLASSES)}"
        )
    return text


def _product_exists(conn, producto_local_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM productos WHERE local_id = ? LIMIT 1",
        (producto_local_id,),
    ).fetchone()
    return row is not None


def _load_command(conn, command_id: str, *, replayed: bool) -> InventoryCommandRecord:
    command_row = conn.execute(
        "SELECT * FROM inventory_commands WHERE command_id = ?",
        (command_id,),
    ).fetchone()
    if command_row is None:
        raise InventoryLedgerError(f"Comando no encontrado: {command_id}")
    command = dict(command_row)
    op_rows = conn.execute(
        """
        SELECT *
        FROM inventory_operations
        WHERE command_id = ?
        ORDER BY line_no
        """,
        (command_id,),
    ).fetchall()
    operations = []
    for row in op_rows:
        mapping = dict(row)
        expected = mapping.get("expected_base_scaled")
        operations.append(
            InventoryOperationRecord(
                operation_id=mapping["operation_id"],
                command_id=mapping["command_id"],
                producto_local_id=mapping["producto_local_id"],
                delta_scaled=int(mapping["delta_scaled"]),
                line_no=int(mapping["line_no"]),
                expected_base_scaled=(
                    None if expected is None else int(expected)
                ),
            )
        )
    operations = tuple(operations)
    return InventoryCommandRecord(
        command_id=command["command_id"],
        tipo=command["tipo"],
        documento_tipo=command["documento_tipo"],
        documento_local_id=command["documento_local_id"],
        device_id=command["device_id"],
        usuario_id=command["usuario_id"],
        request_hash=command["request_hash"],
        estado=command["estado"],
        resultado=command["resultado"],
        motivo=command["motivo"],
        created_at=command["created_at"],
        updated_at=command["updated_at"],
        operations=operations,
        replayed=replayed,
        intent_class=_normalize_intent_class(command.get("intent_class")),
    )


def get_inventory_command(conn, command_id: str) -> InventoryCommandRecord:
    return _load_command(conn, _require_uuid(command_id, "command_id"), replayed=False)


def get_inventory_command_or_none(conn, command_id: str):
    """None si el command_id no existe. No crea identidad nueva."""
    if command_id is None or str(command_id).strip() == "":
        return None
    cid = _require_uuid(command_id, "command_id")
    row = conn.execute(
        "SELECT 1 FROM inventory_commands WHERE command_id = ?",
        (cid,),
    ).fetchone()
    if row is None:
        return None
    return _load_command(conn, cid, replayed=False)


def bind_inventory_command_documento(conn, command_id: str, documento_local_id: str) -> None:
    """Liga el documento comercial al command ya persistido.

    Idempotente si el UUID es el mismo. No cambia estado/resultado.
    Un retry posterior puede recuperar la venta sin insertar otra.
    """
    from local_first_db import now_iso

    cid = _require_uuid(command_id, "command_id")
    doc = _require_uuid(documento_local_id, "documento_local_id")
    row = conn.execute(
        "SELECT documento_local_id FROM inventory_commands WHERE command_id = ?",
        (cid,),
    ).fetchone()
    if row is None:
        raise InventoryLedgerError(f"Comando no encontrado: {cid}")
    current = row["documento_local_id"] if hasattr(row, "keys") else row[0]
    if current and str(current) != doc:
        raise InventoryLedgerError(
            f"command_id {cid} ya está ligado a otro documento"
        )
    if current == doc:
        return
    conn.execute(
        """
        UPDATE inventory_commands
           SET documento_local_id = ?, updated_at = ?
         WHERE command_id = ?
        """,
        (doc, now_iso(), cid),
    )


def _begin_or_savepoint(conn) -> str:
    if conn.in_transaction:
        conn.execute("SAVEPOINT ferrepro_inventory_command")
        return "savepoint"
    conn.execute("BEGIN IMMEDIATE")
    return "begin"


def _finish_ok(conn, mode: str) -> None:
    if mode == "savepoint":
        conn.execute("RELEASE SAVEPOINT ferrepro_inventory_command")
    else:
        conn.commit()


def _finish_fail(conn, mode: str) -> None:
    if mode == "savepoint":
        conn.execute("ROLLBACK TO SAVEPOINT ferrepro_inventory_command")
        conn.execute("RELEASE SAVEPOINT ferrepro_inventory_command")
    else:
        conn.rollback()


def create_inventory_command(
    conn,
    *,
    command_id: str,
    tipo: str,
    operations: Sequence[Mapping[str, Any]],
    documento_tipo: Optional[str] = None,
    documento_local_id: Optional[str] = None,
    device_id: Optional[str] = None,
    usuario_id: Optional[int] = None,
    intent_class: Optional[str] = None,
) -> InventoryCommandRecord:
    """Persiste command + operaciones en una sola transacción SQLite.

    No modifica productos.stock. estado/resultado en 1C: PERSISTED.
    Retry con el mismo payload recupera el registro original.
    Default local = LEGACY_OBSERVED (fail-closed, no transmissible).
    AUTHORITATIVE solo si el caller lo solicita explícitamente.
    """
    if not schema_bootstrap.is_sqlite_connection(conn):
        raise InventoryLedgerError(
            "create_inventory_command solo opera sobre SQLite en esta fase"
        )
    command_id = _require_uuid(command_id, "command_id")
    tipo = _normalize_tipo(tipo)
    intent_class = _normalize_intent_class(intent_class)
    documento_tipo = (
        str(documento_tipo).strip() if documento_tipo else None
    ) or None
    documento_local_id = _optional_uuid(documento_local_id, "documento_local_id")
    if device_id is None or device_id == "":
        from local_first_config import get_or_create_device_id

        device_id = get_or_create_device_id()
    else:
        device_id = _require_uuid(device_id, "device_id")
    if usuario_id is not None:
        try:
            usuario_id = int(usuario_id)
        except (TypeError, ValueError) as exc:
            raise InventoryLedgerError("usuario_id debe ser entero") from exc
    normalized_ops = _normalize_operations(command_id, operations)
    request_hash = command_request_hash(
        command_id=command_id,
        tipo=tipo,
        documento_tipo=documento_tipo,
        documento_local_id=documento_local_id,
        operations=normalized_ops,
    )
    from local_first_db import now_iso

    stamp = now_iso()
    mode = _begin_or_savepoint(conn)
    finished = False
    try:
        existing = conn.execute(
            "SELECT request_hash FROM inventory_commands WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        if existing is not None:
            if existing["request_hash"] != request_hash:
                raise IdempotencyConflictError(
                    f"command_id {command_id} ya existe con otro payload"
                )
            record = _load_command(conn, command_id, replayed=True)
            _finish_ok(conn, mode)
            finished = True
            return record
        missing = [
            op["producto_local_id"]
            for op in normalized_ops
            if not _product_exists(conn, op["producto_local_id"])
        ]
        if missing:
            raise UnknownProductError(
                "Producto inexistente por local_id: " + ", ".join(missing)
            )
        try:
            conn.execute(
                """
                INSERT INTO inventory_commands (
                    command_id, tipo, documento_tipo, documento_local_id,
                    device_id, usuario_id, request_hash, estado, resultado,
                    motivo, created_at, updated_at, intent_class
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
                """,
                (
                    command_id,
                    tipo,
                    documento_tipo,
                    documento_local_id,
                    device_id,
                    usuario_id,
                    request_hash,
                    LEDGER_STATE_PERSISTED,
                    LEDGER_STATE_PERSISTED,
                    stamp,
                    stamp,
                    intent_class,
                ),
            )
            for op in normalized_ops:
                conn.execute(
                    """
                    INSERT INTO inventory_operations (
                        operation_id, command_id, producto_local_id,
                        delta_scaled, line_no, expected_base_scaled
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        op["operation_id"],
                        command_id,
                        op["producto_local_id"],
                        op["delta_scaled"],
                        op["line_no"],
                        op.get("expected_base_scaled"),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            for op in normalized_ops:
                owner = conn.execute(
                    "SELECT command_id FROM inventory_operations "
                    "WHERE operation_id = ?",
                    (op["operation_id"],),
                ).fetchone()
                if owner is not None and owner["command_id"] != command_id:
                    raise DuplicateOperationError(
                        f"operation_id {op['operation_id']} ya pertenece a "
                        f"otro comando ({owner['command_id']})"
                    ) from exc
            raise InventoryLedgerError(
                f"No se pudo persistir el comando de inventario: {exc}"
            ) from exc
        record = _load_command(conn, command_id, replayed=False)
        _finish_ok(conn, mode)
        finished = True
        return record
    except Exception:
        if not finished:
            try:
                _finish_fail(conn, mode)
            except sqlite3.Error:
                pass
        raise
