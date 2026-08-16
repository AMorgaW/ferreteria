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
import sys
from dataclasses import dataclass
from pathlib import Path
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


def coordinator_sql_path() -> Path:
    """Resuelve ``supabase_inventory_coordinator.sql`` sin depender del cwd.

    En repo: junto a este módulo. En PyInstaller: ``sys._MEIPASS`` y, si
    hace falta, la carpeta del ejecutable. No re-embebe el SQL.
    """
    name = REMOTE_COORDINATOR_MIGRATION_FILENAME
    candidates = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / name)
        candidates.append(Path(sys.executable).resolve().parent / name)
    candidates.append(Path(__file__).resolve().parent / name)
    seen = []
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.append(key)
        if path.is_file():
            return path
    searched = ", ".join(seen) if seen else name
    raise CoordinatorError(
        f"No se encontró {name} (recurso del coordinador). Buscado en: {searched}"
    )


def postgres_coordinator_sql() -> str:
    """DDL + RPC PostgreSQL del coordinador. Nunca ejecutar contra SQLite."""
    return coordinator_sql_path().read_text(encoding="utf-8")


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
    orig_by_op = {}
    orig_cmd_by_op = {}
    for raw in operations:
        if not isinstance(raw, Mapping):
            continue
        op_id = str(raw.get("operation_id") or "")
        orig_id = raw.get("original_documento_local_id")
        orig_tipo = raw.get("original_documento_tipo")
        orig_cmd = raw.get("original_command_id")
        if orig_id:
            orig_by_op[op_id] = (orig_tipo, orig_id)
        if orig_cmd:
            orig_cmd_by_op[op_id] = orig_cmd
        if raw.get("expected_base_scaled") is None:
            continue
        try:
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
        extra = orig_by_op.get(str(op["operation_id"]))
        if extra:
            orig_tipo, orig_id = extra
            if orig_tipo:
                item["original_documento_tipo"] = str(orig_tipo)
            item["original_documento_local_id"] = str(orig_id)
        orig_cmd = orig_cmd_by_op.get(str(op["operation_id"]))
        if orig_cmd:
            item["original_command_id"] = str(orig_cmd)
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
                "SELECT public.fetch_inventory_balance(%s)",
                (producto_local_id,),
            )
            row = cur.fetchone()
        conn.rollback()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT quantity_scaled FROM public.inventory_balances "
                    "WHERE producto_local_id = %s",
                    (producto_local_id,),
                )
                row = cur.fetchone()
            conn.rollback()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
    if row is None or row[0] is None:
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
