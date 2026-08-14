# -*- coding: utf-8 -*-
"""Gateway de aplicación para comandos de inventario (Fase 1E.0 / 1E.1).

Separa persistencia local del intent (ledger 1C) del envío al coordinador
PostgreSQL (1D). No es autoridad. No aplica ``productos.stock``.

Orden obligatorio (camino AUTHORITATIVE, cutover ON):

1. persistir ``create_inventory_command`` en SQLite (obtiene command_id)
2. conservar command_id / request_hash / payload
3. si el cutover está ON **y** intent_class=AUTHORITATIVE, enviar
4. resolver APPLIED / REJECTED / UNKNOWN

UNKNOWN es conocimiento del cliente: el ledger local permanece PERSISTED.
No se añade UNKNOWN al CHECK de ``inventory_commands.estado``.

Cutover DEFAULT OFF: el gateway persiste el intent como
``LEGACY_OBSERVED`` y **no** envía APPLY remoto. Esos comandos **nunca**
se transmiten, ni si el cutover se enciende después. No hay cola
PERSISTED autoritativa que pueda atravesar el seed de 1E.3.

Tras un APPLIED futuro, ``productos.stock`` sería proyección/caché
reconstruible; este módulo no escribe stock ni hace dual-write.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple

import schema_bootstrap
from inventory_coordinator import (
    ConnectionFactory,
    CoordinatorDeadlockError,
    CoordinatorError,
    CoordinatorTimeoutError,
    CoordinatorUnknownOutcomeError,
    InventoryCoordinatorClient,
    apply_inventory_command,
)
from inventory_ledger import (
    INTENT_CLASS_AUTHORITATIVE,
    INTENT_CLASS_LEGACY_OBSERVED,
    InventoryCommandRecord,
    InventoryLedgerError,
    create_inventory_command,
    get_inventory_command,
)

# Cutover único futuro (1E.3). DEFAULT OFF en 1E.0: no hay autoridad
# writer-por-writer. Activar esto no autoriza conectar POS/compras.
INVENTORY_CUTOVER_ENABLED = False

INVENTORY_DSN_ENV = "FERREPRO_INVENTORY_DSN"

OUTCOME_PENDING_CUTOVER = "PENDING_CUTOVER"
OUTCOME_LEGACY_OBSERVED = "LEGACY_OBSERVED"
OUTCOME_APPLIED = "APPLIED"
OUTCOME_REJECTED = "REJECTED"
OUTCOME_UNKNOWN = "UNKNOWN"

GATEWAY_OUTCOMES = (
    OUTCOME_PENDING_CUTOVER,
    OUTCOME_LEGACY_OBSERVED,
    OUTCOME_APPLIED,
    OUTCOME_REJECTED,
    OUTCOME_UNKNOWN,
)

LEDGER_STATE_PERSISTED = "PERSISTED"
LEDGER_STATE_APPLIED = "APPLIED"
LEDGER_STATE_REJECTED = "REJECTED"

TransportFn = Callable[..., InventoryCommandRecord]


class InventoryGatewayError(InventoryLedgerError):
    """Fallo del gateway que no finge APPLIED ni REJECTED."""


class InventoryGatewayConfigError(InventoryGatewayError):
    """DSN / factory mal configurados. Nunca hay fallback a SUPABASE_URI."""


class GatewayPreCutoverBacklogError(InventoryGatewayError):
    """Un command LEGACY_OBSERVED no puede aplicarse tras el cutover.

    Garantiza: una venta observada en pre-cutover (cuando productos.stock
    ya descontó) no se reenvía a inventory_balances después del seed.
    """


class MissingProductLocalIdError(InventoryGatewayError):
    """Producto activo sin local_id: el camino autoritativo falla cerrado."""


@dataclass(frozen=True)
class GatewaySubmitResult:
    command_id: str
    request_hash: str
    estado_local: str
    outcome: str
    record: Optional[InventoryCommandRecord] = None
    error: Optional[str] = None


def read_inventory_dsn(*, environ: Optional[Mapping[str, str]] = None) -> str:
    """Lee el DSN no-owner. Nunca hace fallback silencioso a SUPABASE_URI.

    No imprime el valor. No lee ``SUPABASE_URI``.
    """
    env = environ if environ is not None else os.environ
    dsn = str(env.get(INVENTORY_DSN_ENV, "") or "").strip()
    if not dsn:
        raise InventoryGatewayConfigError(
            f"{INVENTORY_DSN_ENV} no está definido. "
            "No se usa SUPABASE_URI como DSN del gateway."
        )
    return dsn


def connection_factory_from_env(
    *, environ: Optional[Mapping[str, str]] = None
) -> ConnectionFactory:
    """Factory no-owner. Exige FERREPRO_INVENTORY_DSN. No usa SUPABASE_URI."""
    dsn = read_inventory_dsn(environ=environ)

    def factory():
        import psycopg2

        conn = psycopg2.connect(dsn)
        conn.autocommit = False
        return conn

    return factory


def _require_uuid(value: Any, field: str) -> str:
    text = str(value or "").strip()
    try:
        parsed = uuid.UUID(text)
    except (ValueError, AttributeError, TypeError) as exc:
        raise InventoryGatewayError(f"{field} debe ser un UUID: {value!r}") from exc
    return str(parsed)


def _command_exists(conn, command_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM inventory_commands WHERE command_id = ? LIMIT 1",
        (command_id,),
    ).fetchone()
    return row is not None


def _prepare_operations(
    operations: Sequence[Mapping[str, Any]],
    *,
    generate_missing_ids: bool,
) -> Tuple[dict, ...]:
    if not operations:
        raise InventoryGatewayError("El comando debe tener al menos una operación")
    prepared = []
    for raw in operations:
        if not isinstance(raw, Mapping):
            raise InventoryGatewayError("Cada operación debe ser un mapeo")
        item = dict(raw)
        op_id = item.get("operation_id")
        if not op_id:
            if not generate_missing_ids:
                raise InventoryGatewayError(
                    "Retry no genera operation_id; reenvíe el payload original"
                )
            item["operation_id"] = str(uuid.uuid4())
        else:
            item["operation_id"] = _require_uuid(op_id, "operation_id")
        prepared.append(item)
    return tuple(prepared)


def command_is_transmittable(record: InventoryCommandRecord) -> bool:
    """Solo AUTHORITATIVE + PERSISTED/APPLIED puede ir al coordinador."""
    intent = getattr(record, "intent_class", INTENT_CLASS_AUTHORITATIVE)
    return intent == INTENT_CLASS_AUTHORITATIVE


def assert_command_transmittable(record: InventoryCommandRecord) -> None:
    if command_is_transmittable(record):
        return
    raise GatewayPreCutoverBacklogError(
        f"command_id {record.command_id} es {record.intent_class}; "
        "un command pre-cutover/LEGACY_OBSERVED no se transmite nunca"
    )


def list_transmittable_command_ids(conn) -> Tuple[str, ...]:
    """Comandos locales que un drain post-cutover podría enviar.

    Excluye LEGACY_OBSERVED. Un seed 1E.3 + replay de esta lista no incluye
    ventas que ya descontaron productos.stock en legacy.
    """
    rows = conn.execute(
        """
        SELECT command_id
          FROM inventory_commands
         WHERE estado = ?
           AND COALESCE(intent_class, ?) = ?
         ORDER BY created_at, command_id
        """,
        (LEDGER_STATE_PERSISTED, INTENT_CLASS_LEGACY_OBSERVED, INTENT_CLASS_AUTHORITATIVE),
    ).fetchall()
    ids = []
    for row in rows:
        ids.append(row["command_id"] if hasattr(row, "keys") else row[0])
    return tuple(ids)


def _is_ambiguous_transport_error(exc: BaseException) -> bool:
    """Tras persistir, el caller no puede saber si el COMMIT remoto ocurrió."""
    if isinstance(
        exc,
        (
            CoordinatorUnknownOutcomeError,
            CoordinatorTimeoutError,
            CoordinatorDeadlockError,
        ),
    ):
        return True
    try:
        import psycopg2

        if isinstance(exc, (psycopg2.OperationalError, psycopg2.InterfaceError)):
            return True
    except ImportError:
        pass
    return False


class InventoryGateway:
    """Orquesta persistencia local + transporte al coordinador.

    ``sqlite_conn`` es el ledger local (1C). Nunca es la autoridad online.
    El transporte PostgreSQL usa ``connection_factory`` (reconnect 1D.3)
    o un ``transport`` inyectado en tests. No hardcodea credenciales.
    """

    def __init__(
        self,
        sqlite_conn,
        *,
        connection_factory: Optional[ConnectionFactory] = None,
        cutover_enabled: Optional[bool] = None,
        coordinator_client: Optional[InventoryCoordinatorClient] = None,
        transport: Optional[TransportFn] = None,
        pg_conn=None,
    ):
        if sqlite_conn is None:
            raise InventoryGatewayError("InventoryGateway requiere sqlite_conn")
        if not schema_bootstrap.is_sqlite_connection(sqlite_conn):
            raise InventoryGatewayError(
                "InventoryGateway persiste el intent en SQLite; "
                "sqlite_conn no es una conexión SQLite"
            )
        self.sqlite_conn = sqlite_conn
        self.connection_factory = connection_factory
        self.cutover_enabled = (
            INVENTORY_CUTOVER_ENABLED if cutover_enabled is None else bool(cutover_enabled)
        )
        self.coordinator_client = coordinator_client
        self._transport = transport
        self._pg_conn = pg_conn
        if pg_conn is not None:
            self._assert_not_sqlite_authority(pg_conn)

    def _unknown_result(
        self, record: InventoryCommandRecord, exc: BaseException
    ) -> GatewaySubmitResult:
        local = get_inventory_command(self.sqlite_conn, record.command_id)
        return GatewaySubmitResult(
            command_id=local.command_id,
            request_hash=local.request_hash,
            estado_local=local.estado,
            outcome=OUTCOME_UNKNOWN,
            record=local,
            error=str(exc),
        )

    @property
    def cutover_is_on(self) -> bool:
        return bool(self.cutover_enabled)

    def _assert_not_sqlite_authority(self, conn) -> None:
        if conn is not None and schema_bootstrap.is_sqlite_connection(conn):
            raise InventoryGatewayError(
                "El gateway no usa SQLite como autoridad online"
            )

    def _mark_local_outcome(
        self,
        command_id: str,
        estado: str,
        motivo: Optional[str] = None,
    ) -> InventoryCommandRecord:
        from local_first_db import now_iso

        if estado not in (LEDGER_STATE_APPLIED, LEDGER_STATE_REJECTED):
            raise InventoryGatewayError(
                f"No se persiste outcome {estado!r} en el ledger local"
            )
        stamp = now_iso()
        self.sqlite_conn.execute(
            """
            UPDATE inventory_commands
               SET estado = ?, resultado = ?, motivo = ?, updated_at = ?
             WHERE command_id = ?
            """,
            (estado, estado, motivo, stamp, command_id),
        )
        self.sqlite_conn.commit()
        return get_inventory_command(self.sqlite_conn, command_id)

    def _send_to_coordinator(
        self,
        record: InventoryCommandRecord,
        operations: Sequence[Mapping[str, Any]],
        *,
        documento_tipo: Optional[str],
        documento_local_id: Optional[str],
        device_id: str,
        usuario_id: Optional[int],
    ) -> InventoryCommandRecord:
        assert_command_transmittable(record)
        payload = dict(
            command_id=record.command_id,
            tipo=record.tipo,
            operations=list(operations),
            documento_tipo=documento_tipo,
            documento_local_id=documento_local_id,
            device_id=device_id,
            usuario_id=usuario_id,
            request_hash=record.request_hash,
        )
        if self._transport is not None:
            return self._transport(**payload)
        if self.coordinator_client is not None:
            return self.coordinator_client.apply_command(**payload)

        factory = self.connection_factory
        pg_conn = self._pg_conn
        if factory is None and pg_conn is None:
            raise InventoryGatewayError(
                "Cutover ON requiere connection_factory o coordinator_client; "
                "no se usa SUPABASE_URI"
            )
        if pg_conn is not None:
            self._assert_not_sqlite_authority(pg_conn)
        if factory is not None:
            wrapped = factory

            def guarded_factory():
                conn = wrapped()
                self._assert_not_sqlite_authority(conn)
                return conn

            factory = guarded_factory
        return apply_inventory_command(
            pg_conn, connection_factory=factory, **payload
        )

    def submit(
        self,
        *,
        tipo: str,
        operations: Sequence[Mapping[str, Any]],
        command_id: Optional[str] = None,
        documento_tipo: Optional[str] = None,
        documento_local_id: Optional[str] = None,
        device_id: Optional[str] = None,
        usuario_id: Optional[int] = None,
    ) -> GatewaySubmitResult:
        """Persiste el intent y, si el cutover está ON, lo envía.

        Retry: el caller reutiliza el mismo command_id / operaciones.
        El gateway no genera IDs en retry.

        Cutover OFF: persiste como LEGACY_OBSERVED y no transmite.
        Un retry posterior con cutover ON **tampoco** transmite ese id.
        """
        generate_ids = True
        existing_record = None
        if command_id:
            command_id = _require_uuid(command_id, "command_id")
            if _command_exists(self.sqlite_conn, command_id):
                generate_ids = False
                existing_record = get_inventory_command(self.sqlite_conn, command_id)
        else:
            command_id = str(uuid.uuid4())
            generate_ids = True

        if existing_record is not None and not command_is_transmittable(
            existing_record
        ):
            return GatewaySubmitResult(
                command_id=existing_record.command_id,
                request_hash=existing_record.request_hash,
                estado_local=existing_record.estado,
                outcome=OUTCOME_LEGACY_OBSERVED,
                record=existing_record,
                error="LEGACY_OBSERVED: no transmissible tras cutover",
            )

        prepared_ops = _prepare_operations(
            operations, generate_missing_ids=generate_ids
        )
        persist_class = (
            INTENT_CLASS_AUTHORITATIVE
            if self.cutover_enabled
            else INTENT_CLASS_LEGACY_OBSERVED
        )
        if existing_record is not None:
            persist_class = existing_record.intent_class

        record = create_inventory_command(
            self.sqlite_conn,
            command_id=command_id,
            tipo=tipo,
            operations=prepared_ops,
            documento_tipo=documento_tipo,
            documento_local_id=documento_local_id,
            device_id=device_id,
            usuario_id=usuario_id,
            intent_class=persist_class,
        )

        if not command_is_transmittable(record):
            return GatewaySubmitResult(
                command_id=record.command_id,
                request_hash=record.request_hash,
                estado_local=record.estado,
                outcome=OUTCOME_LEGACY_OBSERVED,
                record=record,
                error=None,
            )

        if not self.cutover_enabled:
            return GatewaySubmitResult(
                command_id=record.command_id,
                request_hash=record.request_hash,
                estado_local=record.estado,
                outcome=OUTCOME_LEGACY_OBSERVED,
                record=record,
                error=None,
            )

        try:
            remote = self._send_to_coordinator(
                record,
                prepared_ops,
                documento_tipo=documento_tipo,
                documento_local_id=documento_local_id,
                device_id=record.device_id,
                usuario_id=usuario_id,
            )
        except GatewayPreCutoverBacklogError:
            raise
        except InventoryGatewayError:
            raise
        except Exception as exc:
            if _is_ambiguous_transport_error(exc) or isinstance(exc, CoordinatorError):
                return self._unknown_result(record, exc)
            raise

        if remote.estado == LEDGER_STATE_APPLIED:
            local = self._mark_local_outcome(
                record.command_id, LEDGER_STATE_APPLIED, remote.motivo
            )
            return GatewaySubmitResult(
                command_id=local.command_id,
                request_hash=local.request_hash,
                estado_local=local.estado,
                outcome=OUTCOME_APPLIED,
                record=local,
                error=None,
            )
        if remote.estado == LEDGER_STATE_REJECTED:
            local = self._mark_local_outcome(
                record.command_id, LEDGER_STATE_REJECTED, remote.motivo
            )
            return GatewaySubmitResult(
                command_id=local.command_id,
                request_hash=local.request_hash,
                estado_local=local.estado,
                outcome=OUTCOME_REJECTED,
                record=local,
                error=remote.motivo,
            )
        local = get_inventory_command(self.sqlite_conn, record.command_id)
        return GatewaySubmitResult(
            command_id=local.command_id,
            request_hash=local.request_hash,
            estado_local=local.estado,
            outcome=OUTCOME_UNKNOWN,
            record=local,
            error=f"resultado remoto no clasificable: {remote.estado!r}",
        )
