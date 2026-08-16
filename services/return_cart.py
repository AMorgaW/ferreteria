# -*- coding: utf-8 -*-
"""Preparación local de un reverso. El DRAFT no mueve inventario."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from packaging_conversion import as_decimal, sqlite_number
from services.pos_cart import OFFLINE_FINALIZE_BLOCKED, pos_finalize_allowed

return_finalize_allowed = pos_finalize_allowed

KIND_CUSTOMER_RETURN = "CUSTOMER_RETURN"
KIND_SALE_VOID = "SALE_VOID"
KIND_SUPPLIER_RETURN = "SUPPLIER_RETURN"


class ReturnCartError(ValueError):
    pass


def line_subtotal(quantity: Any, price: Any) -> Decimal:
    return as_decimal(quantity) * as_decimal(price)


@dataclass
class ReturnCart:
    kind: str = KIND_CUSTOMER_RETURN
    original_tipo: str = "venta"
    original_id: Optional[int] = None
    original_local_id: Optional[str] = None
    lines: List[dict] = field(default_factory=list)
    confirm_in_flight: bool = False
    motivo: str = ""

    def begin_confirm(self) -> bool:
        if self.confirm_in_flight:
            return False
        self.confirm_in_flight = True
        return True

    def end_confirm(self) -> None:
        self.confirm_in_flight = False

    def set_requested(self, index: int, quantity: Any) -> None:
        if index < 0 or index >= len(self.lines):
            raise ReturnCartError("Línea de reverso inexistente")
        qty = as_decimal(quantity)
        if qty < 0:
            raise ReturnCartError("La cantidad solicitada no puede ser negativa")
        available = as_decimal(self.lines[index].get("available_qty") or 0)
        if qty > available:
            raise ReturnCartError(
                f"No se pueden devolver {qty}: disponibles {available}"
            )
        self.lines[index]["requested_qty"] = qty

    def requested_items(self) -> List[dict]:
        items = []
        for line in self.lines:
            qty = as_decimal(line.get("requested_qty") or 0)
            if qty <= 0:
                continue
            items.append(
                {
                    "producto_id": line["producto_id"],
                    "original_line_id": line.get("original_line_id"),
                    "package_role": line.get("package_role") or "BASE_UNIT",
                    "cantidad_presentacion": sqlite_number(qty),
                    "precio_unitario": line.get("precio_unitario") or 0,
                }
            )
        if not items:
            raise ReturnCartError("Seleccione al menos una cantidad a devolver")
        return items


def format_reversal_preview(
    *,
    kind: str,
    original_tipo: str,
    original_id: Any,
    lines: Sequence[Mapping[str, Any]],
) -> str:
    rows = [
        "FERREPRO — REVERSO CONTROLADO",
        f"tipo: {kind}",
        f"original: {original_tipo} #{original_id}",
        "--------------------------------",
    ]
    for line in lines:
        rows.append(
            f"{line.get('producto_nombre', 'Producto')}  "
            f"orig={line.get('original_qty')}  "
            f"devuelto={line.get('returned_qty')}  "
            f"disponible={line.get('available_qty')}  "
            f"solicitado={line.get('requested_qty')}"
        )
    return "\n".join(rows)
