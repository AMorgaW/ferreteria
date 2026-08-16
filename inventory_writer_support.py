# -*- coding: utf-8 -*-
"""Construcción compartida de InventoryCommand para writers (1E.1 / 1E.2).

No es autoridad. No llama RPC. No escribe productos.stock.
Los writers legacy no deben persistir comandos autoritativos replayables.
Builders: NEGATIVO, POSITIVO, DELTA FIRMADO, SET ABSOLUTO (escala 1000).
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from inventory_gateway import (
    INVENTORY_CUTOVER_ENABLED,
    InventoryGateway,
    InventoryGatewayError,
    MissingProductLocalIdError,
)
from inventory_ledger import (
    QUANTITY_SCALE,
    QuantityScaleError,
    UnknownProductError,
    quantity_to_scaled,
)

WRITER_MODE_LEGACY = "legacy"
WRITER_MODE_AUTHORITATIVE = "authoritative"

DOCUMENTO_TIPO_VENTA = "venta"
DOCUMENTO_TIPO_COMPRA = "compra"
DOCUMENTO_TIPO_MEZCLA = "mezcla"
DOCUMENTO_TIPO_DEVOLUCION = "devolucion"
DOCUMENTO_TIPO_CUSTOMER_RETURN = "customer_return"
DOCUMENTO_TIPO_SALE_VOID = "sale_void"
DOCUMENTO_TIPO_SUPPLIER_RETURN = "supplier_return"
DOCUMENTO_TIPO_MOVIMIENTO = "movimiento"
DOCUMENTO_TIPO_AJUSTE = "ajuste"
DOCUMENTO_TIPO_PRODUCTO = "producto"

UNKNOWN_PREFIX = "INVENTORY_UNKNOWN"
NO_INVENTORY_CHANGE = "NO_INVENTORY_CHANGE"
COMMAND_MARKER_PREFIX = "[invcmd:"

W04_NO_UI_CALLER = (
    "W04 VentasService.cancelar_venta no tiene caller de UI: "
    "ui/ventas_ui_modern.cancelar_venta solo vacía el carrito. "
    "El método permanece preparado; no se borra."
)


def resolve_writer_mode(
    explicit: Optional[str] = None,
    *,
    db=None,
    sqlite_conn=None,
    connection_factory=None,
    pg_conn=None,
    require_remote: Optional[bool] = None,
) -> str:
    """Default = legacy mientras el cutover persistente no es AUTHORITATIVE.

    INVENTORY_CUTOVER_ENABLED sigue False en fuente. ONLINE observa
    PostgreSQL; SQLite es cache. Durante CUTOVER_IN_PROGRESS o si el
    estado global no se puede leer, falla cerrado.
    """
    conn = sqlite_conn
    owned = False
    if conn is None and db is not None and hasattr(db, "conectar"):
        conn = db.conectar()
        owned = True
    try:
        if conn is not None:
            from inventory_cutover import (
                InventoryCutoverError,
                assert_inventory_writes_allowed,
            )

            state = assert_inventory_writes_allowed(
                conn,
                pg_conn=pg_conn,
                connection_factory=connection_factory,
                require_remote=require_remote,
            )
            persistent_auth = state.is_authoritative
        else:
            persistent_auth = False
        if explicit is not None and str(explicit).strip() != "":
            mode = str(explicit).strip().lower()
            if mode not in (WRITER_MODE_LEGACY, WRITER_MODE_AUTHORITATIVE):
                raise ValueError(f"inventory_mode desconocido: {explicit!r}")
            if mode == WRITER_MODE_LEGACY and persistent_auth:
                raise InventoryCutoverError(
                    "inventory_mode=legacy no está permitido en AUTHORITATIVE"
                )
            return mode
        if INVENTORY_CUTOVER_ENABLED:
            return WRITER_MODE_AUTHORITATIVE
        if persistent_auth:
            return WRITER_MODE_AUTHORITATIVE
        return WRITER_MODE_LEGACY
    finally:
        if owned and conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def scaled_to_commercial(quantity_scaled: int) -> float:
    return int(quantity_scaled) / float(QUANTITY_SCALE)


def commercial_quantity_to_scaled(value: Any) -> int:
    """Convierte cantidad comercial a escala 1000. El ledger no ve float.

    Writers legacy pueden tener float interno; aquí se pasa a Decimal/str
    antes de crear InventoryOperation.
    """
    if isinstance(value, float):
        value = Decimal(str(value))
    return quantity_to_scaled(value)


def require_producto_local_id(conn, producto_id: Any) -> str:
    row = conn.execute(
        "SELECT id, local_id FROM productos WHERE id = ?",
        (producto_id,),
    ).fetchone()
    if row is None:
        raise UnknownProductError(f"Producto ID {producto_id} no encontrado")
    lid = row["local_id"] if hasattr(row, "keys") else row[1]
    text = str(lid or "").strip()
    if not text:
        raise MissingProductLocalIdError(
            f"Producto ID {producto_id} no tiene local_id; "
            "el camino autoritativo no improvisa identidad remota"
        )
    try:
        return str(uuid.UUID(text))
    except (ValueError, AttributeError, TypeError) as exc:
        raise MissingProductLocalIdError(
            f"Producto ID {producto_id} tiene local_id inválido: {lid!r}"
        ) from exc


def stable_operation_id(command_id: str, line_no: int) -> str:
    """operation_id determinista por (command_id, line_no). Retry estable."""
    return str(uuid.uuid5(uuid.UUID(str(command_id)), f"line:{int(line_no)}"))


def command_motivo_marker(command_id: str) -> str:
    return f"{COMMAND_MARKER_PREFIX}{command_id}]"


def operations_from_command_record(record) -> List[dict]:
    """Reutiliza operations persistidas. No recalcula delta ni base."""
    operations = []
    for op in record.operations:
        item = {
            "operation_id": op.operation_id,
            "producto_local_id": op.producto_local_id,
            "line_no": op.line_no,
            "delta_scaled": int(op.delta_scaled),
        }
        expected = getattr(op, "expected_base_scaled", None)
        if expected is not None:
            item["expected_base_scaled"] = int(expected)
        operations.append(item)
    return operations


def build_negative_operations(
    conn,
    lines: Sequence[Mapping[str, Any]],
    *,
    command_id: str,
    producto_id_key: str = "producto_id",
    cantidad_key: str = "cantidad",
) -> List[dict]:
    """Un InventoryCommand: N operations, deltas negativos, line_no 1..N."""
    if not lines:
        raise QuantityScaleError("El comando negativo requiere al menos una línea")
    operations = []
    for index, raw in enumerate(lines, start=1):
        qty_scaled = commercial_quantity_to_scaled(raw[cantidad_key])
        if qty_scaled <= 0:
            raise QuantityScaleError(
                f"cantidad debe ser positiva en línea {index}"
            )
        local_id = require_producto_local_id(conn, raw[producto_id_key])
        operations.append(
            {
                "operation_id": stable_operation_id(command_id, index),
                "producto_local_id": local_id,
                "line_no": index,
                "delta_scaled": -int(qty_scaled),
            }
        )
    return operations


def attach_original_document(
    operations: Sequence[Mapping[str, Any]],
    *,
    original_documento_tipo: str,
    original_documento_local_id: str,
    original_command_id: Optional[str] = None,
) -> List[dict]:
    """Enlaza operations al documento original. No entra al request_hash."""
    orig = str(uuid.UUID(str(original_documento_local_id)))
    orig_cmd = None
    if original_command_id:
        orig_cmd = str(uuid.UUID(str(original_command_id)))
    attached = []
    for raw in operations:
        item = dict(raw)
        item["original_documento_tipo"] = str(original_documento_tipo)
        item["original_documento_local_id"] = orig
        if orig_cmd:
            item["original_command_id"] = orig_cmd
        attached.append(item)
    return attached


def build_positive_operations(
    conn,
    lines: Sequence[Mapping[str, Any]],
    *,
    command_id: str,
    producto_id_key: str = "producto_id",
    cantidad_key: str = "cantidad",
) -> List[dict]:
    """Operations con delta positivo (compras, devoluciones, restituciones)."""
    if not lines:
        raise QuantityScaleError("El comando positivo requiere al menos una línea")
    operations = []
    for index, raw in enumerate(lines, start=1):
        qty_scaled = commercial_quantity_to_scaled(raw[cantidad_key])
        if qty_scaled <= 0:
            raise QuantityScaleError(
                f"cantidad debe ser positiva en línea {index}"
            )
        local_id = require_producto_local_id(conn, raw[producto_id_key])
        operations.append(
            {
                "operation_id": stable_operation_id(command_id, index),
                "producto_local_id": local_id,
                "line_no": index,
                "delta_scaled": int(qty_scaled),
            }
        )
    return operations


def build_signed_operations(
    conn,
    lines: Sequence[Mapping[str, Any]],
    *,
    command_id: str,
    producto_id_key: str = "producto_id",
    delta_key: str = "delta",
) -> List[dict]:
    """Delta comercial firmado. Las líneas con delta 0 se omiten.

    Si todas las líneas quedan en 0, devuelve lista vacía
    (NO_INVENTORY_CHANGE). No crea InventoryOperation inválida.
    """
    if not lines:
        return []
    operations = []
    line_no = 0
    for raw in lines:
        qty_scaled = commercial_quantity_to_scaled(raw[delta_key])
        if qty_scaled == 0:
            continue
        line_no += 1
        local_id = require_producto_local_id(conn, raw[producto_id_key])
        operations.append(
            {
                "operation_id": stable_operation_id(command_id, line_no),
                "producto_local_id": local_id,
                "line_no": line_no,
                "delta_scaled": int(qty_scaled),
            }
        )
    return operations


def build_absolute_operations(
    conn,
    *,
    command_id: str,
    producto_id: Any,
    target_qty: Any,
    base_scaled: int,
    line_no: int = 1,
) -> List[dict]:
    """SET stock = target. delta = target_scaled - base_scaled.

    ``base_scaled`` DEBE venir de inventory_balances (o inyección de test).
    Nunca de productos.stock en camino autoritativo.
    Lista vacía si delta 0 (NO_INVENTORY_CHANGE).
    Incluye expected_base_scaled para CAS en el coordinador.
    """
    target_scaled = commercial_quantity_to_scaled(target_qty)
    if target_scaled < 0:
        raise QuantityScaleError("stock absoluto objetivo no puede ser negativo")
    delta = int(target_scaled) - int(base_scaled)
    if delta == 0:
        return []
    local_id = require_producto_local_id(conn, producto_id)
    return [
        {
            "operation_id": stable_operation_id(command_id, line_no),
            "producto_local_id": local_id,
            "line_no": line_no,
            "delta_scaled": int(delta),
            "expected_base_scaled": int(base_scaled),
        }
    ]


def resolve_authoritative_base_scaled(
    producto_local_id: str,
    *,
    explicit_base_scaled: Optional[int] = None,
    connection_factory=None,
    pg_conn=None,
) -> int:
    """Lee quantity_scaled autoritativo. None → 0.

    Nunca lee productos.stock. Fail-closed si no hay base inyectada ni
    conexión PostgreSQL. El CAS expected_base_scaled cubre el race entre
    esta lectura y APPLY.
    """
    if explicit_base_scaled is not None:
        return int(explicit_base_scaled)
    from inventory_coordinator import fetch_inventory_balance

    owned = None
    conn = pg_conn
    if conn is None:
        if connection_factory is None:
            raise InventoryGatewayError(
                "ajuste absoluto autoritativo requiere inventory_balances; "
                "no se usa productos.stock como base"
            )
        owned = connection_factory()
        conn = owned
    try:
        qty = fetch_inventory_balance(conn, producto_local_id)
        return 0 if qty is None else int(qty)
    finally:
        if owned is not None:
            try:
                owned.close()
            except Exception:
                pass


def movement_tipo_to_ledger(tipo: str) -> Tuple[str, int]:
    """Mapea tipo de kardex legado a (InventoryCommand.tipo, signo).

    No usa el texto libre como autoridad: solo prefijos ENTRADA/SALIDA
    y tipos conocidos. El resto falla cerrado.
    """
    text = str(tipo or "").strip().upper()
    if not text:
        raise QuantityScaleError("tipo de movimiento vacío")
    if text.startswith("ENTRADA"):
        if text == "ENTRADA_COMPRA":
            return "COMPRA", 1
        if text == "ENTRADA_DEVOLUCION":
            return "DEVOLUCION", 1
        if text in ("ENTRADA_AJUSTE", "ENTRADA"):
            return "AJUSTE", 1
        return "AJUSTE", 1
    if text.startswith("SALIDA"):
        if text == "SALIDA_VENTA":
            return "VENTA", -1
        return "AJUSTE", -1
    raise QuantityScaleError(
        f"tipo de movimiento no mapeable a InventoryCommand: {tipo!r}"
    )


def unknown_writer_message(command_id: str, detail: Optional[str] = None) -> str:
    extra = f" ({detail})" if detail else ""
    return (
        f"{UNKNOWN_PREFIX} command_id={command_id} "
        "reintente el mismo command_id; no cree otra operación"
        f"{extra}"
    )


after_remote_apply_hook = None


def notify_after_remote_apply(command_id: str) -> None:
    """Hook de test: crash entre APPLY remoto y persistencia local del documento."""
    hook = after_remote_apply_hook
    if callable(hook):
        hook(command_id)


def durable_act_command_id(
    conn,
    act_kind: str,
    *,
    fingerprint: str = "",
    act_key: Optional[str] = None,
    explicit_command_id: Optional[str] = None,
    open_act: bool = False,
) -> str:
    """Identidad durable del acto de negocio ANTES del primer RPC.

    open_act=True: begin_or_resume_open_act (no hay documento aún).
    act_key: identidad derivada del documento (get_or_create_act_command_id).
    """
    from inventory_cutover import begin_or_resume_open_act, get_or_create_act_command_id

    if open_act:
        if explicit_command_id:
            key = act_key or str(explicit_command_id)
            return get_or_create_act_command_id(
                conn, act_kind, key, command_id=explicit_command_id
            )
        return begin_or_resume_open_act(conn, act_kind, fingerprint=fingerprint)
    key = str(act_key or fingerprint or explicit_command_id or "").strip()
    if not key:
        raise InventoryGatewayError(
            f"acto {act_kind} requiere act_key durable antes del RPC"
        )
    return get_or_create_act_command_id(
        conn, act_kind, key, command_id=explicit_command_id
    )


def command_already_applied(
    conn,
    command_id: Optional[str],
    *,
    tipo: Optional[str] = None,
    operations: Optional[Sequence[Mapping[str, Any]]] = None,
    documento_tipo: Optional[str] = None,
    documento_local_id: Optional[str] = None,
):
    """Command local ya APPLIED: el documento no debe mutarse otra vez.

    Si se presenta payload, debe coincidir (hash/ops/expected_base).
    Si no coincide: IdempotencyConflictError. No hay shortcut ciego.
    """
    from inventory_ledger import (
        IdempotencyConflictError,
        LEDGER_STATE_APPLIED,
        command_request_hash,
        get_inventory_command_or_none,
    )

    rec = get_inventory_command_or_none(conn, command_id)
    if rec is None or rec.estado != LEDGER_STATE_APPLIED:
        return None
    if operations is None:
        return rec
    expected_hash = command_request_hash(
        command_id=rec.command_id,
        tipo=tipo or rec.tipo,
        documento_tipo=documento_tipo if documento_tipo is not None else rec.documento_tipo,
        documento_local_id=(
            documento_local_id
            if documento_local_id is not None
            else rec.documento_local_id
        ),
        operations=operations,
    )
    if expected_hash != rec.request_hash:
        raise IdempotencyConflictError(
            f"command_id {rec.command_id} ya APPLIED con payload distinto"
        )
    stored = operations_from_command_record(rec)
    if len(stored) != len(operations):
        raise IdempotencyConflictError(
            f"command_id {rec.command_id} ya APPLIED con operaciones distintas"
        )
    stored_by_op = {str(op["operation_id"]): op for op in stored}
    for raw in operations:
        sid = str(raw.get("operation_id") or "")
        prev = stored_by_op.get(sid)
        if prev is None:
            raise IdempotencyConflictError(
                f"command_id {rec.command_id} ya APPLIED con operation_id nuevo"
            )
        if int(prev["delta_scaled"]) != int(raw["delta_scaled"]):
            raise IdempotencyConflictError(
                f"command_id {rec.command_id} ya APPLIED con delta distinto"
            )
        prev_base = prev.get("expected_base_scaled")
        new_base = raw.get("expected_base_scaled")
        if prev_base is not None or new_base is not None:
            if prev_base is None or new_base is None or int(prev_base) != int(new_base):
                raise IdempotencyConflictError(
                    f"command_id {rec.command_id} ya APPLIED con expected_base distinto"
                )
    return rec


def find_rows_marked_for_command(
    conn,
    command_id: str,
    *,
    table: str,
    column: str = "motivo",
):
    """Side effects locales etiquetados con el command_id."""
    marker = command_motivo_marker(command_id)
    return list(
        conn.execute(
            f"SELECT * FROM {table} WHERE {column} LIKE ?",
            (f"%{marker}%",),
        ).fetchall()
    )


def bind_inventory_gateway(
    sqlite_conn,
    *,
    gateway=None,
    transport=None,
    connection_factory=None,
    cutover_enabled: bool = True,
):
    """Gateway del camino autoritativo. Fail-closed si falta DSN/factory."""
    if gateway is not None:
        return gateway
    kwargs = {"cutover_enabled": bool(cutover_enabled)}
    if transport is not None:
        kwargs["transport"] = transport
    if connection_factory is not None:
        kwargs["connection_factory"] = connection_factory
    elif transport is None:
        from inventory_cutover import app_connection_factory_from_env

        kwargs["connection_factory"] = app_connection_factory_from_env()
    return InventoryGateway(sqlite_conn, **kwargs)


def resolve_writer_mode_or_frozen(
    explicit: Optional[str] = None,
    *,
    db=None,
    sqlite_conn=None,
    connection_factory=None,
    pg_conn=None,
    require_remote: Optional[bool] = None,
):
    """Devuelve (mode, error). error no nulo = freeze o estado global ilegible."""
    from inventory_cutover import CutoverStateUnavailableError, InventoryFrozenError

    try:
        return (
            resolve_writer_mode(
                explicit,
                db=db,
                sqlite_conn=sqlite_conn,
                connection_factory=connection_factory,
                pg_conn=pg_conn,
                require_remote=require_remote,
            ),
            None,
        )
    except (InventoryFrozenError, CutoverStateUnavailableError) as exc:
        return None, str(exc)


assert QUANTITY_SCALE == 1000
