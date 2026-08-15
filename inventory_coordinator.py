# -*- coding: utf-8 -*-
"""Coordinador autoritativo de inventario en PostgreSQL (Fase 1D).

Una entrada RPC ``apply_inventory_command`` aplica un InventoryCommand
completo en una sola transacción PostgreSQL:

* autoridad online = ``inventory_balances.quantity_scaled`` (BIGINT, escala 1000)
* ``productos.stock`` no se lee ni se escribe
* APPLIED solo tras commit del balance; REJECTED no muta balances
* mismo command_id + mismo request_hash → replay del resultado; no re-aplica
* mismo command_id + request_hash distinto → IdempotencyConflictError

No migra POS/compras. No es autoridad offline. No entra al sync LWW.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple

import psycopg2
from psycopg2 import errorcodes
from psycopg2.errors import DeadlockDetected, QueryCanceled

import schema_bootstrap
from inventory_ledger import (
    DuplicateOperationError,
    INTENT_CLASS_AUTHORITATIVE,
    IdempotencyConflictError,
    InventoryCommandRecord,
    InventoryLedgerError,
    InventoryOperationRecord,
    QUANTITY_SCALE,
    QuantityScaleError,
    _normalize_operations,
    _normalize_tipo,
    _optional_uuid,
    _require_uuid,
    command_request_hash,
)

BIGINT_MIN = -9223372036854775808
BIGINT_MAX = 9223372036854775807

# Rol PostgreSQL de aplicación (NOLOGIN). Los tests crean un LOGIN miembro.
# No es un rol comercial SQLite (ADMIN/GERENTE/VENDEDOR/…).
INVENTORY_APP_ROLE = "ferrepro_inventory_app"

CONSTRAINT_PK_INVENTORY_COMMANDS = "pk_inventory_commands"
CONSTRAINT_PK_INVENTORY_COMMANDS_LEGACY = "inventory_commands_pkey"
CONSTRAINT_PK_INVENTORY_OPERATIONS = "pk_inventory_operations"
CONSTRAINT_PK_INVENTORY_OPERATIONS_LEGACY = "inventory_operations_pkey"
CONSTRAINT_UQ_INVENTORY_OPERATIONS_LINE = "uq_inventory_operations_command_line"
CONSTRAINT_UQ_INVENTORY_OPERATIONS_LINE_LEGACY = (
    "inventory_operations_command_id_line_no_key"
)
CONSTRAINT_PK_INVENTORY_BALANCES = "pk_inventory_balances"
CONSTRAINT_PK_INVENTORY_BALANCES_LEGACY = "inventory_balances_pkey"
CONSTRAINT_PK_INVENTORY_BALANCE_INIT = "pk_inventory_balance_init"
CONSTRAINT_PK_INVENTORY_BALANCE_INIT_LEGACY = "inventory_balance_init_pkey"
CONSTRAINT_PK_INVENTORY_BALANCE_INIT_STATE = "pk_inventory_balance_init_state"
CONSTRAINT_PK_INVENTORY_BALANCE_INIT_STATE_LEGACY = (
    "inventory_balance_init_state_pkey"
)

# Reglas estructurales de signo. No son cupos comerciales.
COMMAND_DELTA_SIGN_RULES = {
    "VENTA": "all_negative",
    "COMPRA": "all_positive",
    "RECEPCION": "all_positive",
    "DEVOLUCION": "uniform_sign",
    "AJUSTE": "any_nonzero",
    "MEZCLA": "mixed",
}

_LOST_CONNECTION_MARKERS = (
    "connection already closed",
    "cursor already closed",
    "server closed the connection",
    "connection reset",
    "eof detected",
    "ssl syscall",
    "could not receive data",
    "could not send data",
    "terminating connection",
    "connection not open",
    "connection timed out",
    "timeout expired",
    "broken pipe",
    "admin_shutdown",
    "crash_shutdown",
)


REMOTE_COORDINATOR_MIGRATION_FILENAME = "supabase_inventory_coordinator.sql"

STATE_APPLIED = "APPLIED"
STATE_REJECTED = "REJECTED"

MOTIVO_INSUFFICIENT_STOCK = "INSUFFICIENT_STOCK"
MOTIVO_BALANCE_NOT_FOUND = "BALANCE_NOT_FOUND"
MOTIVO_UNKNOWN_PRODUCT = "UNKNOWN_PRODUCT"
MOTIVO_QUANTITY_OVERFLOW = "QUANTITY_OVERFLOW"

APPLY_RPC_ARGTYPES = (
    "text",
    "text",
    "text",
    "text",
    "text",
    "integer",
    "text",
    "jsonb",
)
SEED_RPC_ARGTYPES = ("text", "bigint")
LEGACY_INIT_RPC_ARGTYPES: Tuple[str, ...] = ()

# Reexport for callers/tests that pin the 1C scale.
assert QUANTITY_SCALE == 1000


class CoordinatorError(InventoryLedgerError):
    """Fallo del coordinador que no deja un resultado de negocio persistido."""


class CoordinatorTimeoutError(CoordinatorError):
    """Timeout de red/statement. El cliente debe reintentar el mismo command_id."""


class CoordinatorDeadlockError(CoordinatorError):
    """Deadlock PostgreSQL agotó reintentos. Reintentar el mismo command_id."""


class CoordinatorUnknownOutcomeError(CoordinatorError):
    """La conexión se perdió; el COMMIT puede haber ocurrido o no.

    El caller debe abrir una conexión PostgreSQL **nueva** y reintentar el
    **mismo** command_id / request_hash / payload. Nunca generar otro id.
    """

    outcome = "UNKNOWN"
    retryable = True


class InvalidDeltaSignError(InventoryLedgerError):
    """Tipo de comando con signos de delta estructuralmente imposibles."""


ConnectionFactory = Callable[[], Any]


@dataclass(frozen=True)
class SeedBalanceResult:
    producto_local_id: str
    quantity_scaled: int
    created: bool


def _as_json(value: Any) -> dict:
    if value is None:
        raise CoordinatorError("RPC del coordinador devolvió NULL")
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return json.loads(value)
    if isinstance(value, memoryview):
        return json.loads(bytes(value).decode("utf-8"))
    if isinstance(value, (bytes, bytearray)):
        return json.loads(bytes(value).decode("utf-8"))
    raise CoordinatorError(
        f"RPC del coordinador devolvió tipo no JSON: {type(value).__name__}"
    )


def _record_from_rpc(payload: Mapping[str, Any]) -> InventoryCommandRecord:
    operations = tuple(
        InventoryOperationRecord(
            operation_id=str(op["operation_id"]),
            command_id=str(payload["command_id"]),
            producto_local_id=str(op["producto_local_id"]),
            delta_scaled=int(op["delta_scaled"]),
            line_no=int(op["line_no"]),
        )
        for op in (payload.get("operations") or ())
    )
    return InventoryCommandRecord(
        command_id=str(payload["command_id"]),
        tipo=str(payload["tipo"]),
        documento_tipo=payload.get("documento_tipo"),
        documento_local_id=payload.get("documento_local_id"),
        device_id=str(payload["device_id"]),
        usuario_id=(
            None if payload.get("usuario_id") is None else int(payload["usuario_id"])
        ),
        request_hash=str(payload["request_hash"]),
        estado=str(payload["estado"]),
        resultado=str(payload["resultado"]),
        motivo=payload.get("motivo"),
        created_at=str(payload["created_at"]),
        updated_at=str(payload["updated_at"]),
        operations=operations,
        replayed=bool(payload.get("replayed")),
        intent_class=INTENT_CLASS_AUTHORITATIVE,
    )


def postgres_coordinator_sql() -> str:
    """DDL + RPC PostgreSQL del coordinador. Nunca ejecutar contra SQLite."""
    return _POSTGRES_COORDINATOR_SQL


def coordinator_apply_sql(sql: Optional[str] = None) -> str:
    """Cuerpo SQL de apply_inventory_command (para auditoría estática)."""
    text = postgres_coordinator_sql() if sql is None else sql
    return _extract_marked(text, "apply_inventory_command")


def coordinator_seed_sql(sql: Optional[str] = None) -> str:
    text = postgres_coordinator_sql() if sql is None else sql
    return _extract_marked(text, "seed_inventory_balance")


def coordinator_legacy_init_sql(sql: Optional[str] = None) -> str:
    text = postgres_coordinator_sql() if sql is None else sql
    return _extract_marked(text, "initialize_inventory_balances_from_legacy")


def _extract_marked(sql: str, name: str) -> str:
    begin = f"-- FASE1D-BEGIN {name}"
    end = f"-- FASE1D-END {name}"
    start = sql.find(begin)
    stop = sql.find(end)
    if start < 0 or stop < 0 or stop <= start:
        raise CoordinatorError(f"No se encontró el marcador SQL de {name}")
    return sql[start:stop]


def assert_command_delta_signs(
    tipo: str, operations: Sequence[Mapping[str, Any]]
) -> None:
    """Impide combinaciones de signo imposibles. No inventa cupos comerciales."""
    tipo = _normalize_tipo(tipo)
    deltas = [int(op["delta_scaled"]) for op in operations]
    rule = COMMAND_DELTA_SIGN_RULES.get(tipo)
    if rule == "all_negative":
        if any(delta >= 0 for delta in deltas):
            raise InvalidDeltaSignError(
                "INVALID_DELTA_SIGN: VENTA exige todas las líneas con delta < 0"
            )
    elif rule == "all_positive":
        if any(delta <= 0 for delta in deltas):
            raise InvalidDeltaSignError(
                f"INVALID_DELTA_SIGN: {tipo} exige todas las líneas con delta > 0"
            )
    elif rule == "uniform_sign":
        signs = {1 if delta > 0 else -1 for delta in deltas}
        if len(signs) > 1:
            raise InvalidDeltaSignError(
                "INVALID_DELTA_SIGN: DEVOLUCION no admite signos mixtos "
                "en el mismo comando"
            )
    elif rule == "mixed":
        if not any(delta < 0 for delta in deltas) or not any(
            delta > 0 for delta in deltas
        ):
            raise InvalidDeltaSignError(
                "INVALID_DELTA_SIGN: MEZCLA exige al menos un delta < 0 y uno > 0"
            )


def _is_lost_connection(exc: BaseException) -> bool:
    if isinstance(exc, QueryCanceled) or isinstance(exc, DeadlockDetected):
        return False
    pgcode = getattr(exc, "pgcode", None)
    if pgcode in (errorcodes.QUERY_CANCELED, errorcodes.DEADLOCK_DETECTED):
        return False
    if isinstance(exc, (psycopg2.OperationalError, psycopg2.InterfaceError)):
        return True
    message = str(exc).lower()
    return any(marker in message for marker in _LOST_CONNECTION_MARKERS)


def _discard_connection(conn) -> None:
    if conn is None:
        return
    try:
        if not getattr(conn, "closed", 1):
            try:
                conn.rollback()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
    except Exception:
        pass


def _connection_is_dead(conn) -> bool:
    if conn is None:
        return True
    closed = getattr(conn, "closed", 0)
    if isinstance(closed, bool) and closed:
        return True
    if isinstance(closed, int) and not isinstance(closed, bool) and closed != 0:
        return True
    get_status = getattr(conn, "get_transaction_status", None)
    if get_status is None or not callable(get_status):
        return False
    try:
        status = get_status()
    except Exception:
        return True
    if not isinstance(status, int):
        return False
    return status == psycopg2.extensions.TRANSACTION_STATUS_UNKNOWN


def _raise_from_pg(exc: BaseException) -> None:
    message = str(exc)
    pgcode = getattr(exc, "pgcode", None)
    if _is_lost_connection(exc):
        raise CoordinatorUnknownOutcomeError(
            "Conexión PostgreSQL perdida (UNKNOWN); reintente el mismo "
            "command_id en una conexión nueva"
        ) from exc
    if "INVENTORY_FORBIDDEN" in message or pgcode == errorcodes.INSUFFICIENT_PRIVILEGE:
        raise CoordinatorError(message) from exc
    if "INVALID_DELTA_SIGN" in message:
        raise InvalidDeltaSignError(message) from exc
    if "IDEMPOTENCY_CONFLICT" in message:
        raise IdempotencyConflictError(message) from exc
    if "DUPLICATE_OPERATION" in message:
        raise DuplicateOperationError(message) from exc
    if pgcode == errorcodes.QUERY_CANCELED or isinstance(exc, QueryCanceled):
        raise CoordinatorTimeoutError(
            "Timeout del coordinador; reintente el mismo command_id"
        ) from exc
    if pgcode == errorcodes.DEADLOCK_DETECTED or isinstance(exc, DeadlockDetected):
        raise CoordinatorDeadlockError(
            "Deadlock en el coordinador; reintente el mismo command_id"
        ) from exc
    raise CoordinatorError(message) from exc


def _prepare_command(
    *,
    command_id: str,
    tipo: str,
    operations: Sequence[Mapping[str, Any]],
    documento_tipo: Optional[str] = None,
    documento_local_id: Optional[str] = None,
    device_id: Optional[str] = None,
    usuario_id: Optional[int] = None,
    request_hash: Optional[str] = None,
) -> Tuple[str, str, Optional[str], Optional[str], str, Optional[int], str, list]:
    if command_id is None or str(command_id).strip() == "":
        raise InventoryLedgerError(
            "command_id es obligatorio; un retry no debe generar uno nuevo"
        )
    command_id = _require_uuid(command_id, "command_id")
    tipo = _normalize_tipo(tipo)
    documento_tipo = (
        str(documento_tipo).strip() if documento_tipo else None
    ) or None
    documento_local_id = _optional_uuid(documento_local_id, "documento_local_id")
    if device_id is None or device_id == "":
        raise InventoryLedgerError("device_id es obligatorio en el coordinador")
    device_id = _require_uuid(device_id, "device_id")
    if usuario_id is not None:
        try:
            usuario_id = int(usuario_id)
        except (TypeError, ValueError) as exc:
            raise InventoryLedgerError("usuario_id debe ser entero") from exc
    normalized_ops = _normalize_operations(command_id, operations)
    for op in normalized_ops:
        delta = int(op["delta_scaled"])
        if delta < BIGINT_MIN or delta > BIGINT_MAX:
            raise QuantityScaleError(
                f"delta_scaled fuera de rango BIGINT: {delta}"
            )
    assert_command_delta_signs(tipo, normalized_ops)
    computed_hash = command_request_hash(
        command_id=command_id,
        tipo=tipo,
        documento_tipo=documento_tipo,
        documento_local_id=documento_local_id,
        operations=normalized_ops,
    )
    if request_hash is not None and str(request_hash).strip() != "":
        provided = str(request_hash).strip().lower()
        if provided != computed_hash:
            raise IdempotencyConflictError(
                f"request_hash no coincide con el payload de {command_id}"
            )
    expected_by_op = {}
    for raw in operations:
        if not isinstance(raw, Mapping):
            continue
        if raw.get("expected_base_scaled") is None:
            continue
        try:
            op_id = str(raw.get("operation_id") or "")
            expected_by_op[op_id] = int(raw["expected_base_scaled"])
        except (TypeError, ValueError) as exc:
            raise QuantityScaleError(
                "expected_base_scaled debe ser entero"
            ) from exc
    ops_payload = []
    for op in normalized_ops:
        item = {
            "operation_id": op["operation_id"],
            "producto_local_id": op["producto_local_id"],
            "delta_scaled": int(op["delta_scaled"]),
            "line_no": int(op["line_no"]),
        }
        expected = expected_by_op.get(str(op["operation_id"]))
        if expected is not None:
            item["expected_base_scaled"] = int(expected)
        ops_payload.append(item)
    return (
        command_id,
        tipo,
        documento_tipo,
        documento_local_id,
        device_id,
        usuario_id,
        computed_hash,
        ops_payload,
    )


def apply_inventory_command(
    conn=None,
    *,
    command_id: str,
    tipo: str,
    operations: Sequence[Mapping[str, Any]],
    documento_tipo: Optional[str] = None,
    documento_local_id: Optional[str] = None,
    device_id: Optional[str] = None,
    usuario_id: Optional[int] = None,
    request_hash: Optional[str] = None,
    timeout_seconds: float = 8.0,
    retry_on_timeout: bool = True,
    max_deadlock_retries: int = 3,
    connection_factory: Optional[ConnectionFactory] = None,
    max_reconnect_retries: int = 1,
) -> InventoryCommandRecord:
    """Invoca el RPC autoritativo. No genera un command_id nuevo en retry.

    Timeout/deadlock/UNKNOWN reintentan el **mismo** command_id y request_hash.
    Si la conexión se pierde, ``connection_factory`` abre una sesión nueva.
    Sin factory, el UNKNOWN se propaga para que el caller reconecte.
    """
    prepared = _prepare_command(
        command_id=command_id,
        tipo=tipo,
        operations=operations,
        documento_tipo=documento_tipo,
        documento_local_id=documento_local_id,
        device_id=device_id,
        usuario_id=usuario_id,
        request_hash=request_hash,
    )
    if conn is not None and schema_bootstrap.is_sqlite_connection(conn):
        raise CoordinatorError(
            "apply_inventory_command del coordinador solo opera sobre PostgreSQL"
        )
    if conn is None and connection_factory is None:
        raise CoordinatorError(
            "apply_inventory_command requiere conn o connection_factory"
        )
    timeout_ms = max(1, int(float(timeout_seconds) * 1000))
    timeout_attempts = 2 if retry_on_timeout else 1
    timeout_retries_left = timeout_attempts - 1
    deadlock_retries_left = max(0, int(max_deadlock_retries))
    reconnect_retries_left = max(0, int(max_reconnect_retries))
    active = conn

    def _acquire() -> Any:
        nonlocal active
        if active is not None and not _connection_is_dead(active):
            _require_idle_transaction(active)
            return active
        if connection_factory is None:
            if active is None:
                raise CoordinatorUnknownOutcomeError(
                    "sin conexión usable; abra una nueva y reintente el mismo command_id"
                )
            _require_idle_transaction(active)
            return active
        _discard_connection(active)
        active = connection_factory()
        if active is not None and schema_bootstrap.is_sqlite_connection(active):
            raise CoordinatorError(
                "apply_inventory_command del coordinador solo opera sobre PostgreSQL"
            )
        _require_idle_transaction(active)
        return active

    while True:
        try:
            current = _acquire()
            return _invoke_apply_rpc(current, prepared, timeout_ms=timeout_ms)
        except CoordinatorTimeoutError:
            if timeout_retries_left <= 0:
                raise
            timeout_retries_left -= 1
            if _connection_is_dead(active):
                _discard_connection(active)
                active = None
            continue
        except CoordinatorDeadlockError:
            if deadlock_retries_left <= 0:
                raise
            deadlock_retries_left -= 1
            if _connection_is_dead(active):
                _discard_connection(active)
                active = None
            continue
        except CoordinatorUnknownOutcomeError:
            _discard_connection(active)
            active = None
            if connection_factory is None or reconnect_retries_left <= 0:
                raise
            reconnect_retries_left -= 1
            continue


def _invoke_apply_rpc(
    conn, prepared: tuple, *, timeout_ms: int
) -> InventoryCommandRecord:
    (
        command_id,
        tipo,
        documento_tipo,
        documento_local_id,
        device_id,
        usuario_id,
        request_hash,
        ops_payload,
    ) = prepared
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = %s", (timeout_ms,))
            cur.execute(
                """
                SELECT public.apply_inventory_command(
                    %s, %s, %s, %s, %s, %s, %s, %s::jsonb
                )
                """,
                (
                    command_id,
                    tipo,
                    documento_tipo,
                    documento_local_id,
                    device_id,
                    usuario_id,
                    request_hash,
                    json.dumps(ops_payload, ensure_ascii=False, separators=(",", ":")),
                ),
            )
            row = cur.fetchone()
        conn.commit()
    except Exception as exc:
        lost = _is_lost_connection(exc)
        try:
            conn.rollback()
        except Exception as rollback_exc:
            lost = lost or _is_lost_connection(rollback_exc)
            _discard_connection(conn)
        if lost:
            raise CoordinatorUnknownOutcomeError(
                "Conexión PostgreSQL perdida (UNKNOWN); reintente el mismo "
                "command_id en una conexión nueva"
            ) from exc
        if isinstance(exc, psycopg2.Error):
            _raise_from_pg(exc)
        raise
    if not row:
        raise CoordinatorError("RPC apply_inventory_command no devolvió fila")
    return _record_from_rpc(_as_json(row[0]))


def seed_inventory_balance(
    conn,
    producto_local_id: str,
    quantity_scaled: int,
) -> SeedBalanceResult:
    """Inicializa un balance de forma explícita. No sobrescribe uno existente.

    No lee ``productos.stock``. quantity_scaled es BIGINT de escala 1000.
    """
    if schema_bootstrap.is_sqlite_connection(conn):
        raise CoordinatorError("seed_inventory_balance solo opera sobre PostgreSQL")
    _require_idle_transaction(conn)
    producto_local_id = _require_uuid(producto_local_id, "producto_local_id")
    try:
        quantity_scaled = int(quantity_scaled)
    except (TypeError, ValueError) as exc:
        raise QuantityScaleError("quantity_scaled debe ser entero") from exc
    if isinstance(quantity_scaled, bool) or quantity_scaled < 0:
        raise QuantityScaleError(
            "La semilla de balance no admite negativos ni bool"
        )
    if quantity_scaled > BIGINT_MAX:
        raise QuantityScaleError("quantity_scaled fuera de rango BIGINT")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT public.seed_inventory_balance(%s, %s)",
                (producto_local_id, quantity_scaled),
            )
            row = cur.fetchone()
        conn.commit()
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        if isinstance(exc, psycopg2.Error):
            _raise_from_pg(exc)
        raise
    payload = _as_json(row[0] if row else None)
    return SeedBalanceResult(
        producto_local_id=str(payload["producto_local_id"]),
        quantity_scaled=int(payload["quantity_scaled"]),
        created=bool(payload.get("created")),
    )


def initialize_inventory_balances_from_legacy(conn) -> dict:
    """One-shot opt-in. NO lo llama el arranque ni el sync.

    Copia productos.stock * 1000 solo hacia filas de inventory_balances que
    aún no existen. Nunca sobrescribe un balance más nuevo.
    """
    if schema_bootstrap.is_sqlite_connection(conn):
        raise CoordinatorError(
            "initialize_inventory_balances_from_legacy solo opera sobre PostgreSQL"
        )
    _require_idle_transaction(conn)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT public.initialize_inventory_balances_from_legacy()")
            row = cur.fetchone()
        conn.commit()
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        if isinstance(exc, psycopg2.Error):
            _raise_from_pg(exc)
        raise
    return _as_json(row[0] if row else None)


def fetch_inventory_balance(conn, producto_local_id: str) -> Optional[int]:
    """Lee quantity_scaled autoritativo. None si no hay fila."""
    _require_idle_transaction(conn)
    producto_local_id = _require_uuid(producto_local_id, "producto_local_id")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT quantity_scaled FROM public.inventory_balances "
                "WHERE producto_local_id = %s",
                (producto_local_id,),
            )
            row = cur.fetchone()
        # psycopg2 abre una transacción incluso para SELECT. Como este adapter
        # exige recibir una conexión idle, se cierra aquí sin confirmar nada.
        conn.rollback()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    if row is None:
        return None
    return int(row[0])


class InventoryCoordinatorClient:
    """Adapter mínimo para invocar el coordinador desde Python.

    No conecta POS ni compras. Un retry debe reutilizar command_id.
    No revive una conexión muerta: si hay ``connection_factory``, abre
    una sesión PostgreSQL nueva y reintenta el mismo comando preparado.
    """

    def __init__(
        self,
        conn=None,
        *,
        connection_factory: Optional[ConnectionFactory] = None,
        timeout_seconds: float = 8.0,
    ):
        if conn is None and connection_factory is None:
            raise CoordinatorError(
                "InventoryCoordinatorClient requiere conn o connection_factory"
            )
        self.conn = conn
        self.connection_factory = connection_factory
        self.timeout_seconds = timeout_seconds

    def _factory(self) -> Any:
        if self.connection_factory is None:
            raise CoordinatorUnknownOutcomeError(
                "sin connection_factory; no se reutiliza una conexión muerta"
            )
        self.conn = self.connection_factory()
        return self.conn

    def apply_command(self, **kwargs) -> InventoryCommandRecord:
        kwargs.setdefault("timeout_seconds", self.timeout_seconds)
        factory = self._factory if self.connection_factory is not None else None
        return apply_inventory_command(
            self.conn, connection_factory=factory, **kwargs
        )

    def seed_balance(
        self, producto_local_id: str, quantity_scaled: int
    ) -> SeedBalanceResult:
        return seed_inventory_balance(self.conn, producto_local_id, quantity_scaled)

    def get_balance(self, producto_local_id: str) -> Optional[int]:
        return fetch_inventory_balance(self.conn, producto_local_id)


def _require_idle_transaction(conn) -> None:
    """Evita que el adapter confirme una transacción ajena al RPC."""
    if conn is None or _connection_is_dead(conn):
        raise CoordinatorUnknownOutcomeError(
            "conexión cerrada o desconocida; abra una nueva y reintente "
            "el mismo command_id"
        )
    if getattr(conn, "autocommit", False) is True:
        raise CoordinatorError(
            "El coordinador requiere una conexión PostgreSQL con autocommit=False"
        )
    get_status = getattr(conn, "get_transaction_status", None)
    if get_status is None:
        return
    try:
        status = get_status()
    except Exception as exc:
        raise CoordinatorUnknownOutcomeError(
            "No se pudo verificar el estado transaccional de la conexión"
        ) from exc
    if status == psycopg2.extensions.TRANSACTION_STATUS_INERROR:
        try:
            conn.rollback()
            status = get_status()
        except Exception as exc:
            raise CoordinatorUnknownOutcomeError(
                "conexión abortada irrecuperable; abra una nueva y reintente "
                "el mismo command_id"
            ) from exc
    if status != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
        raise CoordinatorError(
            "El coordinador requiere una conexión sin transacción activa"
        )


_POSTGRES_COORDINATOR_SQL = r"""-- FERREPRO Fase 1D — coordinador autoritativo de inventario.
-- SOLO PostgreSQL/Supabase. Nunca ejecutar contra SQLite.
-- Idempotente. No modifica productos.stock. No entra al sync LWW.
-- Autoridad online: inventory_balances.quantity_scaled (BIGINT, escala 1000).
-- apply_inventory_command: una RPC → una transacción.
-- Fase 1D.3: gate session_user + constraints nombradas.

CREATE TABLE IF NOT EXISTS inventory_balances (
    producto_local_id TEXT NOT NULL,
    quantity_scaled BIGINT NOT NULL CHECK (quantity_scaled >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CONSTRAINT pk_inventory_balances PRIMARY KEY (producto_local_id)
);

CREATE TABLE IF NOT EXISTS inventory_balance_init (
    producto_local_id TEXT NOT NULL,
    quantity_scaled BIGINT NOT NULL,
    source TEXT NOT NULL,
    initialized_at TEXT NOT NULL,
    CONSTRAINT pk_inventory_balance_init PRIMARY KEY (producto_local_id)
);

CREATE TABLE IF NOT EXISTS inventory_balance_init_state (
    init_key TEXT NOT NULL CHECK (init_key = 'legacy_cutover'),
    initialized_at TEXT NOT NULL,
    CONSTRAINT pk_inventory_balance_init_state PRIMARY KEY (init_key)
);

CREATE INDEX IF NOT EXISTS idx_inventory_balances_updated
    ON inventory_balances(updated_at);

-- Compatibilidad con bases ya creadas por Fase 1D (nombres implícitos).
DO $ferrepro_rename$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM pg_catalog.pg_constraint c
          JOIN pg_catalog.pg_class t ON t.oid = c.conrelid
          JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
         WHERE n.nspname = 'public'
           AND t.relname = 'inventory_balances'
           AND c.conname = 'inventory_balances_pkey'
    ) THEN
        ALTER TABLE public.inventory_balances
            RENAME CONSTRAINT inventory_balances_pkey TO pk_inventory_balances;
    END IF;
    IF EXISTS (
        SELECT 1
          FROM pg_catalog.pg_constraint c
          JOIN pg_catalog.pg_class t ON t.oid = c.conrelid
          JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
         WHERE n.nspname = 'public'
           AND t.relname = 'inventory_balance_init'
           AND c.conname = 'inventory_balance_init_pkey'
    ) THEN
        ALTER TABLE public.inventory_balance_init
            RENAME CONSTRAINT inventory_balance_init_pkey TO pk_inventory_balance_init;
    END IF;
    IF EXISTS (
        SELECT 1
          FROM pg_catalog.pg_constraint c
          JOIN pg_catalog.pg_class t ON t.oid = c.conrelid
          JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
         WHERE n.nspname = 'public'
           AND t.relname = 'inventory_balance_init_state'
           AND c.conname = 'inventory_balance_init_state_pkey'
    ) THEN
        ALTER TABLE public.inventory_balance_init_state
            RENAME CONSTRAINT inventory_balance_init_state_pkey
            TO pk_inventory_balance_init_state;
    END IF;
END
$ferrepro_rename$;

ALTER TABLE inventory_balances ENABLE ROW LEVEL SECURITY;
ALTER TABLE inventory_balance_init ENABLE ROW LEVEL SECURITY;
ALTER TABLE inventory_balance_init_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE inventory_commands ENABLE ROW LEVEL SECURITY;
ALTER TABLE inventory_operations ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION public.ferrepro_inventory_caller_is_allowed()
RETURNS boolean
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $ferrepro_fn$
DECLARE
    v_has_app boolean := false;
BEGIN
    BEGIN
        v_has_app := pg_catalog.pg_has_role(
            session_user,
            'ferrepro_inventory_app',
            'USAGE'
        );
    EXCEPTION
        WHEN undefined_object THEN
            v_has_app := false;
    END;
    RETURN v_has_app
        OR session_user = current_user;
END;
$ferrepro_fn$;

-- FASE1D-BEGIN apply_inventory_command
CREATE OR REPLACE FUNCTION public.apply_inventory_command(
    p_command_id text,
    p_tipo text,
    p_documento_tipo text,
    p_documento_local_id text,
    p_device_id text,
    p_usuario_id integer,
    p_request_hash text,
    p_operations jsonb
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $ferrepro_fn$
DECLARE
    v_command_id text;
    v_device_id text;
    v_doc_id text;
    v_documento_tipo text;
    v_tipo text;
    v_hash text;
    v_canonical text;
    v_computed_hash text;
    v_existing_hash text;
    v_now text;
    v_op jsonb;
    v_parsed jsonb := '[]'::jsonb;
    v_line int;
    v_delta numeric;
    v_opid text;
    v_pid text;
    v_seen_lines int[] := ARRAY[]::int[];
    v_seen_ops text[] := ARRAY[]::text[];
    v_owner text;
    v_missing text[] := ARRAY[]::text[];
    v_pid_list text[];
    v_net numeric;
    v_qty bigint;
    v_next numeric;
    v_failures text := '';
    v_exp_min bigint;
    v_exp_max bigint;
    v_has_expected boolean;
    v_current_base bigint;
    v_balance_found boolean;
    v_plan jsonb := '[]'::jsonb;
    v_item jsonb;
    v_motivo text;
    v_estado text;
    v_constraint text;
    BIGINT_MIN numeric := -9223372036854775808;
    BIGINT_MAX numeric := 9223372036854775807;
    v_pos int := 0;
    v_neg int := 0;
BEGIN
    IF NOT public.ferrepro_inventory_caller_is_allowed() THEN
        RAISE EXCEPTION 'INVENTORY_FORBIDDEN: el caller no está autorizado para apply_inventory_command'
            USING ERRCODE = '42501';
    END IF;
    IF p_command_id IS NULL OR btrim(p_command_id) = '' THEN
        RAISE EXCEPTION 'INVALID_COMMAND: command_id es obligatorio'
            USING ERRCODE = '22023';
    END IF;
    BEGIN
        v_command_id := (btrim(p_command_id))::uuid::text;
    EXCEPTION WHEN invalid_text_representation THEN
        RAISE EXCEPTION 'INVALID_COMMAND: command_id debe ser UUID'
            USING ERRCODE = '22023';
    END;
    IF p_device_id IS NULL OR btrim(p_device_id) = '' THEN
        RAISE EXCEPTION 'INVALID_COMMAND: device_id es obligatorio'
            USING ERRCODE = '22023';
    END IF;
    BEGIN
        v_device_id := (btrim(p_device_id))::uuid::text;
    EXCEPTION WHEN invalid_text_representation THEN
        RAISE EXCEPTION 'INVALID_COMMAND: device_id debe ser UUID'
            USING ERRCODE = '22023';
    END;
    v_documento_tipo := NULLIF(btrim(COALESCE(p_documento_tipo, '')), '');
    IF p_documento_local_id IS NULL OR btrim(p_documento_local_id) = '' THEN
        v_doc_id := NULL;
    ELSE
        BEGIN
            v_doc_id := (btrim(p_documento_local_id))::uuid::text;
        EXCEPTION WHEN invalid_text_representation THEN
            RAISE EXCEPTION 'INVALID_COMMAND: documento_local_id debe ser UUID'
                USING ERRCODE = '22023';
        END;
    END IF;
    v_tipo := upper(btrim(COALESCE(p_tipo, '')));
    IF v_tipo NOT IN ('VENTA', 'COMPRA', 'DEVOLUCION', 'AJUSTE', 'MEZCLA', 'RECEPCION') THEN
        RAISE EXCEPTION USING ERRCODE = '22023',
            MESSAGE = 'INVALID_COMMAND: tipo desconocido ' || coalesce(p_tipo, '');
    END IF;
    v_hash := lower(btrim(COALESCE(p_request_hash, '')));
    IF v_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'INVALID_COMMAND: request_hash debe ser SHA-256 hex'
            USING ERRCODE = '22023';
    END IF;
    IF p_operations IS NULL OR jsonb_typeof(p_operations) <> 'array' THEN
        RAISE EXCEPTION 'INVALID_COMMAND: operations debe ser un array JSON'
            USING ERRCODE = '22023';
    END IF;

    IF jsonb_array_length(p_operations) = 0 THEN
        RAISE EXCEPTION 'EMPTY_COMMAND: el comando debe tener al menos una operación'
            USING ERRCODE = '22023';
    END IF;

    FOR v_op IN
        SELECT value FROM jsonb_array_elements(p_operations)
    LOOP
        IF jsonb_typeof(v_op) <> 'object' THEN
            RAISE EXCEPTION 'INVALID_COMMAND: cada operación debe ser un objeto'
                USING ERRCODE = '22023';
        END IF;
        BEGIN
            v_opid := (v_op->>'operation_id')::uuid::text;
            v_pid := (v_op->>'producto_local_id')::uuid::text;
        EXCEPTION WHEN invalid_text_representation THEN
            RAISE EXCEPTION 'INVALID_COMMAND: operation_id y producto_local_id deben ser UUID'
                USING ERRCODE = '22023';
        END;
        BEGIN
            v_line := (v_op->>'line_no')::int;
        EXCEPTION WHEN others THEN
            RAISE EXCEPTION 'INVALID_COMMAND: line_no debe ser entero'
                USING ERRCODE = '22023';
        END;
        IF v_line IS NULL OR v_line < 1 THEN
            RAISE EXCEPTION 'INVALID_COMMAND: line_no debe ser >= 1'
                USING ERRCODE = '22023';
        END IF;
        IF v_line = ANY (v_seen_lines) THEN
            RAISE EXCEPTION USING ERRCODE = '22023',
                MESSAGE = 'INVALID_COMMAND: line_no duplicado ' || v_line::text;
        END IF;
        IF v_opid = ANY (v_seen_ops) THEN
            RAISE EXCEPTION USING ERRCODE = '22023',
                MESSAGE = 'INVALID_COMMAND: operation_id duplicado ' || v_opid;
        END IF;
        v_seen_lines := array_append(v_seen_lines, v_line);
        v_seen_ops := array_append(v_seen_ops, v_opid);
        BEGIN
            v_delta := (v_op->>'delta_scaled')::numeric;
        EXCEPTION WHEN others THEN
            RAISE EXCEPTION 'INVALID_DELTA: delta_scaled no numérico'
                USING ERRCODE = '22023';
        END;
        IF v_delta IS NULL OR v_delta <> trunc(v_delta) THEN
            RAISE EXCEPTION 'INVALID_DELTA: delta_scaled debe ser entero exacto'
                USING ERRCODE = '22023';
        END IF;
        IF v_delta = 0 THEN
            RAISE EXCEPTION 'ZERO_DELTA: delta 0 no tiene razón de dominio'
                USING ERRCODE = '22023';
        END IF;
        IF v_delta < BIGINT_MIN OR v_delta > BIGINT_MAX THEN
            RAISE EXCEPTION 'INVALID_DELTA: delta_scaled fuera de rango BIGINT'
                USING ERRCODE = '22023';
        END IF;
        SELECT o.command_id
          INTO v_owner
          FROM public.inventory_operations o
         WHERE o.operation_id = v_opid;
        IF FOUND AND v_owner IS DISTINCT FROM v_command_id THEN
            RAISE EXCEPTION USING ERRCODE = '22023',
                MESSAGE = 'DUPLICATE_OPERATION: operation_id ' || v_opid
                    || ' ya pertenece a otro comando (' || v_owner || ')';
        END IF;
        IF v_op ? 'expected_base_scaled' THEN
            BEGIN
                IF (v_op->>'expected_base_scaled') IS NULL
                   OR (v_op->>'expected_base_scaled')::numeric <> trunc((v_op->>'expected_base_scaled')::numeric) THEN
                    RAISE EXCEPTION 'INVALID_DELTA: expected_base_scaled debe ser entero'
                        USING ERRCODE = '22023';
                END IF;
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'INVALID_DELTA: expected_base_scaled debe ser entero'
                    USING ERRCODE = '22023';
            END;
            v_parsed := v_parsed || jsonb_build_array(
                jsonb_build_object(
                    'operation_id', v_opid,
                    'producto_local_id', v_pid,
                    'delta_scaled', v_delta::bigint,
                    'line_no', v_line,
                    'expected_base_scaled', (v_op->>'expected_base_scaled')::bigint
                )
            );
        ELSE
            v_parsed := v_parsed || jsonb_build_array(
                jsonb_build_object(
                    'operation_id', v_opid,
                    'producto_local_id', v_pid,
                    'delta_scaled', v_delta::bigint,
                    'line_no', v_line
                )
            );
        END IF;
    END LOOP;

    v_parsed := COALESCE(
        (
            SELECT jsonb_agg(value ORDER BY (value->>'line_no')::int)
              FROM jsonb_array_elements(v_parsed)
        ),
        '[]'::jsonb
    );

    SELECT
        COUNT(*) FILTER (WHERE (e->>'delta_scaled')::bigint > 0),
        COUNT(*) FILTER (WHERE (e->>'delta_scaled')::bigint < 0)
      INTO v_pos, v_neg
      FROM jsonb_array_elements(v_parsed) e;
    IF v_tipo = 'VENTA' AND v_pos > 0 THEN
        RAISE EXCEPTION 'INVALID_DELTA_SIGN: VENTA exige todas las líneas con delta < 0'
            USING ERRCODE = '22023';
    ELSIF v_tipo IN ('COMPRA', 'RECEPCION') AND v_neg > 0 THEN
        RAISE EXCEPTION USING ERRCODE = '22023',
            MESSAGE = 'INVALID_DELTA_SIGN: ' || v_tipo
                || ' exige todas las líneas con delta > 0';
    ELSIF v_tipo = 'DEVOLUCION' AND v_pos > 0 AND v_neg > 0 THEN
        RAISE EXCEPTION 'INVALID_DELTA_SIGN: DEVOLUCION no admite signos mixtos en el mismo comando'
            USING ERRCODE = '22023';
    ELSIF v_tipo = 'MEZCLA' AND (v_pos = 0 OR v_neg = 0) THEN
        RAISE EXCEPTION 'INVALID_DELTA_SIGN: MEZCLA exige al menos un delta < 0 y uno > 0'
            USING ERRCODE = '22023';
    END IF;

    SELECT
        '{"command_id":' || pg_catalog.to_jsonb(v_command_id)::text
        || ',"documento_local_id":'
        || COALESCE(pg_catalog.to_jsonb(v_doc_id)::text, 'null')
        || ',"documento_tipo":'
        || COALESCE(pg_catalog.to_jsonb(v_documento_tipo)::text, 'null')
        || ',"operations":['
        || COALESCE(
            (
                SELECT string_agg(
                    '{"delta_scaled":' || (e->>'delta_scaled')
                    || ',"line_no":' || (e->>'line_no')
                    || ',"operation_id":'
                    || pg_catalog.to_jsonb(e->>'operation_id')::text
                    || ',"producto_local_id":'
                    || pg_catalog.to_jsonb(e->>'producto_local_id')::text
                    || '}',
                    ',' ORDER BY (e->>'line_no')::int
                )
                  FROM jsonb_array_elements(v_parsed) e
            ),
            ''
        )
        || '],"tipo":' || pg_catalog.to_jsonb(v_tipo)::text
        || '}'
      INTO v_canonical;
    v_computed_hash := encode(
        pg_catalog.sha256(pg_catalog.convert_to(v_canonical, 'UTF8')),
        'hex'
    );
    IF v_computed_hash IS DISTINCT FROM v_hash THEN
        RAISE EXCEPTION USING ERRCODE = '22023',
            MESSAGE = 'INVALID_COMMAND: request_hash no coincide con el payload';
    END IF;

    PERFORM pg_advisory_xact_lock(
        pg_catalog.hashtextextended('ferrepro.invcmd:' || v_command_id, 0)
    );

    SELECT request_hash
      INTO v_existing_hash
      FROM public.inventory_commands
     WHERE command_id = v_command_id
     FOR UPDATE;

    IF FOUND THEN
        IF v_existing_hash IS DISTINCT FROM v_hash THEN
            RAISE EXCEPTION USING ERRCODE = '22023',
                MESSAGE = 'IDEMPOTENCY_CONFLICT: command_id ' || v_command_id
                    || ' ya existe con otro request_hash';
        END IF;
        RETURN public.inventory_command_to_json(v_command_id, true);
    END IF;

    SELECT coalesce(array_agg(pid ORDER BY pid), ARRAY[]::text[])
      INTO v_pid_list
      FROM (
          SELECT DISTINCT e->>'producto_local_id' AS pid
            FROM jsonb_array_elements(v_parsed) e
      ) d;

    SELECT coalesce(array_agg(pid ORDER BY pid), ARRAY[]::text[])
      INTO v_missing
      FROM unnest(v_pid_list) AS pid
     WHERE NOT EXISTS (
        SELECT 1
          FROM public.productos p
         WHERE p.local_id = pid
     );

    v_now := to_char(
        timezone('UTC', clock_timestamp()),
        'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'
    );

    IF array_length(v_missing, 1) IS NOT NULL THEN
        v_motivo := 'UNKNOWN_PRODUCT: ' || array_to_string(v_missing, ', ');
        v_estado := 'REJECTED';
        INSERT INTO public.inventory_commands (
            command_id, tipo, documento_tipo, documento_local_id,
            device_id, usuario_id, request_hash, estado, resultado,
            motivo, created_at, updated_at
        ) VALUES (
            v_command_id, v_tipo, v_documento_tipo, v_doc_id,
            v_device_id, p_usuario_id, v_hash, v_estado, v_estado,
            v_motivo, v_now, v_now
        );
        INSERT INTO public.inventory_operations (
            operation_id, command_id, producto_local_id, delta_scaled, line_no
        )
        SELECT
            e->>'operation_id',
            v_command_id,
            e->>'producto_local_id',
            (e->>'delta_scaled')::bigint,
            (e->>'line_no')::int
        FROM jsonb_array_elements(v_parsed) e;
        RETURN public.inventory_command_to_json(v_command_id, false);
    END IF;

    FOR v_pid, v_net IN
        SELECT e->>'producto_local_id',
               SUM((e->>'delta_scaled')::numeric)
          FROM jsonb_array_elements(v_parsed) e
         GROUP BY 1
         ORDER BY 1
    LOOP
        PERFORM pg_advisory_xact_lock(
            pg_catalog.hashtextextended('ferrepro.invbal:' || v_pid, 0)
        );
        SELECT b.quantity_scaled
          INTO v_qty
          FROM public.inventory_balances b
         WHERE b.producto_local_id = v_pid
         FOR UPDATE;
        v_balance_found := FOUND;
        SELECT MIN((e->>'expected_base_scaled')::bigint),
               MAX((e->>'expected_base_scaled')::bigint),
               bool_or(e ? 'expected_base_scaled')
          INTO v_exp_min, v_exp_max, v_has_expected
          FROM jsonb_array_elements(v_parsed) e
         WHERE e->>'producto_local_id' = v_pid;
        IF COALESCE(v_has_expected, false) THEN
            IF v_exp_min IS DISTINCT FROM v_exp_max THEN
                v_failures := v_failures || 'STALE_BALANCE: expected_base conflict producto='
                    || v_pid || '; ';
                CONTINUE;
            END IF;
            IF v_balance_found THEN
                v_current_base := v_qty;
            ELSE
                v_current_base := 0;
            END IF;
            IF v_current_base IS DISTINCT FROM v_exp_min THEN
                v_failures := v_failures || 'STALE_BALANCE: producto='
                    || v_pid || ' expected=' || v_exp_min::text
                    || ' actual=' || v_current_base::text || '; ';
                CONTINUE;
            END IF;
        END IF;
        IF NOT v_balance_found THEN
            IF v_net < 0 THEN
                v_failures := v_failures || 'BALANCE_NOT_FOUND: producto='
                    || v_pid || '; ';
                CONTINUE;
            END IF;
            v_qty := 0;
            IF v_net > BIGINT_MAX THEN
                v_failures := v_failures || 'QUANTITY_OVERFLOW: producto='
                    || v_pid || '; ';
                CONTINUE;
            END IF;
            v_plan := v_plan || jsonb_build_array(
                jsonb_build_object(
                    'producto_local_id', v_pid,
                    'next_qty', v_net::bigint,
                    'missing', true
                )
            );
        ELSE
            IF v_net > 0 AND v_qty::numeric > BIGINT_MAX - v_net THEN
                v_failures := v_failures || 'QUANTITY_OVERFLOW: producto='
                    || v_pid || '; ';
                CONTINUE;
            END IF;
            v_next := v_qty::numeric + v_net;
            IF v_next < 0 THEN
                v_failures := v_failures || 'INSUFFICIENT_STOCK: producto='
                    || v_pid || ' available=' || v_qty::text
                    || ' required=' || (abs(v_net))::text || '; ';
                CONTINUE;
            END IF;
            IF v_next > BIGINT_MAX THEN
                v_failures := v_failures || 'QUANTITY_OVERFLOW: producto='
                    || v_pid || '; ';
                CONTINUE;
            END IF;
            v_plan := v_plan || jsonb_build_array(
                jsonb_build_object(
                    'producto_local_id', v_pid,
                    'next_qty', v_next::bigint,
                    'missing', false
                )
            );
        END IF;
    END LOOP;

    IF v_failures <> '' THEN
        v_motivo := rtrim(v_failures, '; ');
        v_estado := 'REJECTED';
        INSERT INTO public.inventory_commands (
            command_id, tipo, documento_tipo, documento_local_id,
            device_id, usuario_id, request_hash, estado, resultado,
            motivo, created_at, updated_at
        ) VALUES (
            v_command_id, v_tipo, v_documento_tipo, v_doc_id,
            v_device_id, p_usuario_id, v_hash, v_estado, v_estado,
            v_motivo, v_now, v_now
        );
        INSERT INTO public.inventory_operations (
            operation_id, command_id, producto_local_id, delta_scaled, line_no
        )
        SELECT
            e->>'operation_id',
            v_command_id,
            e->>'producto_local_id',
            (e->>'delta_scaled')::bigint,
            (e->>'line_no')::int
        FROM jsonb_array_elements(v_parsed) e;
        RETURN public.inventory_command_to_json(v_command_id, false);
    END IF;

    v_estado := 'APPLIED';
    BEGIN
        FOR v_item IN SELECT value FROM jsonb_array_elements(v_plan)
        LOOP
            IF (v_item->>'missing')::boolean THEN
                INSERT INTO public.inventory_balances (
                    producto_local_id, quantity_scaled, created_at, updated_at
                ) VALUES (
                    v_item->>'producto_local_id',
                    (v_item->>'next_qty')::bigint,
                    v_now,
                    v_now
                );
            ELSE
                UPDATE public.inventory_balances
                   SET quantity_scaled = (v_item->>'next_qty')::bigint,
                       updated_at = v_now
                 WHERE producto_local_id = v_item->>'producto_local_id';
            END IF;
        END LOOP;

        INSERT INTO public.inventory_commands (
            command_id, tipo, documento_tipo, documento_local_id,
            device_id, usuario_id, request_hash, estado, resultado,
            motivo, created_at, updated_at
        ) VALUES (
            v_command_id, v_tipo, v_documento_tipo, v_doc_id,
            v_device_id, p_usuario_id, v_hash, v_estado, v_estado,
            NULL, v_now, v_now
        );
        INSERT INTO public.inventory_operations (
            operation_id, command_id, producto_local_id, delta_scaled, line_no
        )
        SELECT
            e->>'operation_id',
            v_command_id,
            e->>'producto_local_id',
            (e->>'delta_scaled')::bigint,
            (e->>'line_no')::int
        FROM jsonb_array_elements(v_parsed) e;
    EXCEPTION
        WHEN unique_violation THEN
            GET STACKED DIAGNOSTICS v_constraint = CONSTRAINT_NAME;
            IF v_constraint IN (
                'pk_inventory_commands',
                'inventory_commands_pkey'
            ) THEN
                SELECT request_hash
                  INTO v_existing_hash
                  FROM public.inventory_commands
                 WHERE command_id = v_command_id;
                IF FOUND THEN
                    IF v_existing_hash IS DISTINCT FROM v_hash THEN
                        RAISE EXCEPTION USING ERRCODE = '22023',
                            MESSAGE = 'IDEMPOTENCY_CONFLICT: command_id ' || v_command_id
                                || ' ya existe con otro request_hash';
                    END IF;
                    RETURN public.inventory_command_to_json(v_command_id, true);
                END IF;
                RAISE;
            ELSIF v_constraint IN (
                'pk_inventory_operations',
                'inventory_operations_pkey',
                'uq_inventory_operations_command_line',
                'inventory_operations_command_id_line_no_key'
            ) THEN
                RAISE EXCEPTION
                    'DUPLICATE_OPERATION: operation_id repetido en otro comando'
                    USING ERRCODE = '22023';
            ELSIF v_constraint IN (
                'pk_inventory_balances',
                'inventory_balances_pkey',
                'pk_inventory_balance_init',
                'inventory_balance_init_pkey'
            ) THEN
                RAISE;
            ELSE
                RAISE;
            END IF;
    END;

    RETURN public.inventory_command_to_json(v_command_id, false);
END;
$ferrepro_fn$;
-- FASE1D-END apply_inventory_command

CREATE OR REPLACE FUNCTION public.inventory_command_to_json(
    p_command_id text,
    p_replayed boolean
) RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $ferrepro_fn$
DECLARE
    v_ops jsonb;
    v_json jsonb;
BEGIN
    SELECT jsonb_build_object(
        'command_id', c.command_id,
        'tipo', c.tipo,
        'documento_tipo', c.documento_tipo,
        'documento_local_id', c.documento_local_id,
        'device_id', c.device_id,
        'usuario_id', c.usuario_id,
        'request_hash', c.request_hash,
        'estado', c.estado,
        'resultado', c.resultado,
        'motivo', c.motivo,
        'created_at', c.created_at,
        'updated_at', c.updated_at,
        'replayed', p_replayed
    )
      INTO STRICT v_json
      FROM public.inventory_commands c
     WHERE c.command_id = p_command_id;
    SELECT coalesce(
        jsonb_agg(
            jsonb_build_object(
                'operation_id', o.operation_id,
                'producto_local_id', o.producto_local_id,
                'delta_scaled', o.delta_scaled,
                'line_no', o.line_no
            )
            ORDER BY o.line_no
        ),
        '[]'::jsonb
    )
      INTO v_ops
      FROM public.inventory_operations o
     WHERE o.command_id = p_command_id;
    RETURN v_json || jsonb_build_object('operations', v_ops);
END;
$ferrepro_fn$;

-- FASE1D-BEGIN seed_inventory_balance
CREATE OR REPLACE FUNCTION public.seed_inventory_balance(
    p_producto_local_id text,
    p_quantity_scaled bigint
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $ferrepro_fn$
DECLARE
    v_pid text;
    v_now text;
    v_qty bigint;
    v_n integer := 0;
BEGIN
    IF session_user IS DISTINCT FROM current_user THEN
        RAISE EXCEPTION 'INVENTORY_FORBIDDEN: seed_inventory_balance solo el owner'
            USING ERRCODE = '42501';
    END IF;
    BEGIN
        v_pid := (btrim(p_producto_local_id))::uuid::text;
    EXCEPTION WHEN invalid_text_representation THEN
        RAISE EXCEPTION 'INVALID_COMMAND: producto_local_id debe ser UUID'
            USING ERRCODE = '22023';
    END;
    IF p_quantity_scaled IS NULL OR p_quantity_scaled < 0 THEN
        RAISE EXCEPTION 'INVALID_DELTA: quantity_scaled de semilla debe ser >= 0'
            USING ERRCODE = '22023';
    END IF;
    PERFORM pg_advisory_xact_lock(
        pg_catalog.hashtextextended('ferrepro.invbal:' || v_pid, 0)
    );
    IF NOT EXISTS (
        SELECT 1
          FROM public.productos p
         WHERE p.local_id = v_pid
    ) THEN
        RAISE EXCEPTION 'UNKNOWN_PRODUCT: producto_local_id no existe'
            USING ERRCODE = '22023';
    END IF;
    v_now := to_char(
        timezone('UTC', clock_timestamp()),
        'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'
    );
    INSERT INTO public.inventory_balances (
        producto_local_id, quantity_scaled, created_at, updated_at
    ) VALUES (
        v_pid, p_quantity_scaled, v_now, v_now
    )
    ON CONFLICT (producto_local_id) DO NOTHING;
    GET DIAGNOSTICS v_n = ROW_COUNT;
    INSERT INTO public.inventory_balance_init (
        producto_local_id, quantity_scaled, source, initialized_at
    ) VALUES (
        v_pid, p_quantity_scaled, 'explicit', v_now
    )
    ON CONFLICT (producto_local_id) DO NOTHING;
    SELECT quantity_scaled INTO STRICT v_qty
      FROM public.inventory_balances
     WHERE producto_local_id = v_pid;
    RETURN jsonb_build_object(
        'producto_local_id', v_pid,
        'quantity_scaled', v_qty,
        'created', (v_n > 0)
    );
END;
$ferrepro_fn$;
-- FASE1D-END seed_inventory_balance

-- FASE1D-BEGIN initialize_inventory_balances_from_legacy
-- One-shot de corte. NO la ejecuta el coordinador ni el sync automático.
-- Lee la columna legacy de productos solo para copiar filas AUSENTES.
-- ON CONFLICT DO NOTHING: nunca pisa un balance más nuevo.
CREATE OR REPLACE FUNCTION public.initialize_inventory_balances_from_legacy()
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $ferrepro_fn$
DECLARE
    v_now text;
    v_inserted bigint := 0;
    v_pid text;
    v_inserted_one integer;
BEGIN
    IF session_user IS DISTINCT FROM current_user THEN
        RAISE EXCEPTION 'INVENTORY_FORBIDDEN: initialize_inventory_balances_from_legacy solo el owner'
            USING ERRCODE = '42501';
    END IF;
    PERFORM pg_advisory_xact_lock(
        pg_catalog.hashtextextended('ferrepro.invbal.init:legacy_cutover', 0)
    );
    IF EXISTS (
        SELECT 1
          FROM public.inventory_balance_init_state
         WHERE init_key = 'legacy_cutover'
    ) THEN
        RETURN jsonb_build_object(
            'inserted', 0,
            'source', 'legacy_cutover',
            'already_initialized', true
        );
    END IF;
    v_now := to_char(
        timezone('UTC', clock_timestamp()),
        'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'
    );
    FOR v_pid IN
        SELECT p.local_id
          FROM public.productos p
         WHERE p.local_id IS NOT NULL
           AND btrim(p.local_id) <> ''
         ORDER BY p.local_id
    LOOP
        PERFORM pg_advisory_xact_lock(
            pg_catalog.hashtextextended('ferrepro.invbal:' || v_pid, 0)
        );
        INSERT INTO public.inventory_balances (
            producto_local_id, quantity_scaled, created_at, updated_at
        )
        SELECT
            p.local_id,
            round((COALESCE(p.stock, 0))::numeric * 1000, 0)::bigint,
            v_now,
            v_now
          FROM public.productos p
         WHERE p.local_id = v_pid
        ON CONFLICT (producto_local_id) DO NOTHING;
        GET DIAGNOSTICS v_inserted_one = ROW_COUNT;
        v_inserted := v_inserted + v_inserted_one;
        IF v_inserted_one > 0 THEN
            INSERT INTO public.inventory_balance_init (
                producto_local_id, quantity_scaled, source, initialized_at
            )
            SELECT
                b.producto_local_id,
                b.quantity_scaled,
                'legacy_cutover',
                v_now
              FROM public.inventory_balances b
             WHERE b.producto_local_id = v_pid
            ON CONFLICT (producto_local_id) DO NOTHING;
        END IF;
    END LOOP;
    INSERT INTO public.inventory_balance_init_state (init_key, initialized_at)
    VALUES ('legacy_cutover', v_now);
    RETURN jsonb_build_object(
        'inserted', v_inserted,
        'source', 'legacy_cutover',
        'already_initialized', false
    );
END;
$ferrepro_fn$;
-- FASE1D-END initialize_inventory_balances_from_legacy

REVOKE ALL ON FUNCTION public.apply_inventory_command(text, text, text, text, text, integer, text, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.inventory_command_to_json(text, boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.seed_inventory_balance(text, bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.initialize_inventory_balances_from_legacy() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.ferrepro_inventory_caller_is_allowed() FROM PUBLIC;
REVOKE ALL ON TABLE public.inventory_balances FROM PUBLIC;
REVOKE ALL ON TABLE public.inventory_balance_init FROM PUBLIC;
REVOKE ALL ON TABLE public.inventory_balance_init_state FROM PUBLIC;
REVOKE ALL ON TABLE public.inventory_commands FROM PUBLIC;
REVOKE ALL ON TABLE public.inventory_operations FROM PUBLIC;

DO $ferrepro_do$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON FUNCTION public.apply_inventory_command(text, text, text, text, text, integer, text, jsonb) FROM anon;
        REVOKE ALL ON FUNCTION public.inventory_command_to_json(text, boolean) FROM anon;
        REVOKE ALL ON FUNCTION public.seed_inventory_balance(text, bigint) FROM anon;
        REVOKE ALL ON FUNCTION public.initialize_inventory_balances_from_legacy() FROM anon;
        REVOKE ALL ON FUNCTION public.ferrepro_inventory_caller_is_allowed() FROM anon;
        REVOKE ALL ON TABLE public.inventory_balances FROM anon;
        REVOKE ALL ON TABLE public.inventory_balance_init FROM anon;
        REVOKE ALL ON TABLE public.inventory_balance_init_state FROM anon;
        REVOKE ALL ON TABLE public.inventory_commands FROM anon;
        REVOKE ALL ON TABLE public.inventory_operations FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON FUNCTION public.apply_inventory_command(text, text, text, text, text, integer, text, jsonb) FROM authenticated;
        REVOKE ALL ON FUNCTION public.inventory_command_to_json(text, boolean) FROM authenticated;
        REVOKE ALL ON FUNCTION public.seed_inventory_balance(text, bigint) FROM authenticated;
        REVOKE ALL ON FUNCTION public.initialize_inventory_balances_from_legacy() FROM authenticated;
        REVOKE ALL ON FUNCTION public.ferrepro_inventory_caller_is_allowed() FROM authenticated;
        REVOKE ALL ON TABLE public.inventory_balances FROM authenticated;
        REVOKE ALL ON TABLE public.inventory_balance_init FROM authenticated;
        REVOKE ALL ON TABLE public.inventory_balance_init_state FROM authenticated;
        REVOKE ALL ON TABLE public.inventory_commands FROM authenticated;
        REVOKE ALL ON TABLE public.inventory_operations FROM authenticated;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        REVOKE ALL ON FUNCTION public.apply_inventory_command(text, text, text, text, text, integer, text, jsonb) FROM service_role;
        REVOKE ALL ON FUNCTION public.inventory_command_to_json(text, boolean) FROM service_role;
        REVOKE ALL ON FUNCTION public.seed_inventory_balance(text, bigint) FROM service_role;
        REVOKE ALL ON FUNCTION public.initialize_inventory_balances_from_legacy() FROM service_role;
        REVOKE ALL ON FUNCTION public.ferrepro_inventory_caller_is_allowed() FROM service_role;
        REVOKE ALL ON TABLE public.inventory_balances FROM service_role;
        REVOKE ALL ON TABLE public.inventory_balance_init FROM service_role;
        REVOKE ALL ON TABLE public.inventory_balance_init_state FROM service_role;
        REVOKE ALL ON TABLE public.inventory_commands FROM service_role;
        REVOKE ALL ON TABLE public.inventory_operations FROM service_role;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ferrepro_inventory_app') THEN
        GRANT EXECUTE ON FUNCTION public.apply_inventory_command(text, text, text, text, text, integer, text, jsonb) TO ferrepro_inventory_app;
        GRANT USAGE ON SCHEMA public TO ferrepro_inventory_app;
        REVOKE ALL ON FUNCTION public.inventory_command_to_json(text, boolean) FROM ferrepro_inventory_app;
        REVOKE ALL ON FUNCTION public.seed_inventory_balance(text, bigint) FROM ferrepro_inventory_app;
        REVOKE ALL ON FUNCTION public.initialize_inventory_balances_from_legacy() FROM ferrepro_inventory_app;
        REVOKE ALL ON FUNCTION public.ferrepro_inventory_caller_is_allowed() FROM ferrepro_inventory_app;
        REVOKE ALL ON TABLE public.inventory_balances FROM ferrepro_inventory_app;
        REVOKE ALL ON TABLE public.inventory_balance_init FROM ferrepro_inventory_app;
        REVOKE ALL ON TABLE public.inventory_balance_init_state FROM ferrepro_inventory_app;
        REVOKE ALL ON TABLE public.inventory_commands FROM ferrepro_inventory_app;
        REVOKE ALL ON TABLE public.inventory_operations FROM ferrepro_inventory_app;
    END IF;
END
$ferrepro_do$;
"""
