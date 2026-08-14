# -*- coding: utf-8 -*-
"""Construcción compartida de InventoryCommand para writers negativos (1E.1).

No es autoridad. No llama RPC. No escribe productos.stock.
Los writers legacy no deben persistir comandos autoritativos replayables.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, List, Mapping, Optional, Sequence

from inventory_gateway import (
    INVENTORY_CUTOVER_ENABLED,
    InventoryGateway,
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

UNKNOWN_PREFIX = "INVENTORY_UNKNOWN"


def resolve_writer_mode(explicit: Optional[str] = None) -> str:
    """Default = legacy mientras INVENTORY_CUTOVER_ENABLED es False."""
    if explicit is not None and str(explicit).strip() != "":
        mode = str(explicit).strip().lower()
        if mode not in (WRITER_MODE_LEGACY, WRITER_MODE_AUTHORITATIVE):
            raise ValueError(f"inventory_mode desconocido: {explicit!r}")
        return mode
    if INVENTORY_CUTOVER_ENABLED:
        return WRITER_MODE_AUTHORITATIVE
    return WRITER_MODE_LEGACY


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
        producto_id = raw[producto_id_key]
        local_id = require_producto_local_id(conn, producto_id)
        qty_scaled = commercial_quantity_to_scaled(raw[cantidad_key])
        if qty_scaled <= 0:
            raise QuantityScaleError(
                f"cantidad debe ser positiva en línea {index}"
            )
        operations.append(
            {
                "operation_id": stable_operation_id(command_id, index),
                "producto_local_id": local_id,
                "line_no": index,
                "delta_scaled": -int(qty_scaled),
            }
        )
    return operations


def unknown_writer_message(command_id: str, detail: Optional[str] = None) -> str:
    extra = f" ({detail})" if detail else ""
    return (
        f"{UNKNOWN_PREFIX} command_id={command_id} "
        "reintente el mismo command_id; no cree otra operación"
        f"{extra}"
    )


def command_already_applied(conn, command_id: Optional[str]):
    """Command local ya APPLIED: el documento no debe mutarse otra vez."""
    from inventory_ledger import LEDGER_STATE_APPLIED, get_inventory_command_or_none

    rec = get_inventory_command_or_none(conn, command_id)
    if rec is not None and rec.estado == LEDGER_STATE_APPLIED:
        return rec
    return None


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
        from inventory_gateway import connection_factory_from_env

        kwargs["connection_factory"] = connection_factory_from_env()
    return InventoryGateway(sqlite_conn, **kwargs)


assert QUANTITY_SCALE == 1000
