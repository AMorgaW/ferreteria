# -*- coding: utf-8 -*-
"""Conversión canónica presentación → unidad base.

Autoridad única para ventas, compras y barcodes FULL_PACKAGE.
Inventory balance siempre en unidad base. Sin stock por empaque.

Storage legado ``unidades_por_caja`` / ``unidades_por_media_caja`` se lee
solo aquí. Callers usan get_base_units_per_package / quantity_in_base_units.
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any, List, Mapping, Optional

from repositories.product_barcodes_repo import (
    PACKAGE_ROLE_BASE_UNIT,
    PACKAGE_ROLE_CUSTOM_PRESENTATION,
    PACKAGE_ROLE_FULL_PACKAGE,
    PACKAGE_ROLES,
)

PACKAGING_BLOCKED = "BLOCKED_BY_PACKAGING_CONVERSION_CONTRACT"
PRESENTATION_HALF_PACKAGE = "HALF_PACKAGE"
ALLOWED_PRESENTATIONS = frozenset(PACKAGE_ROLES) | {PRESENTATION_HALF_PACKAGE}

# Misma escala que inventory_ledger.QUANTITY_SCALE (1000 → 3 decimales).
QUANTITY_DECIMAL_PLACES = 3
NO_PACKAGE_SENTINELS = frozenset({"SIN EMPAQUE", "SIN_EMPAQUE"})

# Claves canónicas primero; unidades_por_caja es storage legado.
_PACKAGE_SIZE_KEYS = (
    "cantidad_unidad_base_por_empaque",
    "cantidad_base_por_empaque",
    "unidades_por_caja",
)
_PACKAGE_SALE_FLAGS = (
    "vende_empaque_completo",
    "vende_por_empaque",
    "viene_en_caja",
)


class PackagingError(ValueError):
    pass


class PackagingConversionBlocked(ValueError):
    def __init__(self, package_role: str, detail: str = "") -> None:
        self.package_role = package_role
        message = PACKAGING_BLOCKED if not detail else f"{PACKAGING_BLOCKED}: {detail}"
        super().__init__(message)


def as_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def sqlite_number(value: Any):
    """Decimal exacto en memoria; SQLite recibe int o str, nunca float crítico."""
    number = as_decimal(value)
    if number == number.to_integral_value():
        return int(number)
    return format(number, "f")


def _truthy(value: Any) -> bool:
    if value in (None, "", 0, "0", False):
        return False
    if isinstance(value, str) and value.strip().upper() in ("NO", "FALSE", "N"):
        return False
    return bool(value)


def _package_presentation(product: Mapping[str, Any]) -> str:
    raw = (
        product.get("presentacion_empaque")
        or product.get("presentacion")
        or ""
    )
    return str(raw).strip()


def _positive_factor(raw: Any) -> Optional[Decimal]:
    if raw in (None, "", 0, "0"):
        return None
    try:
        factor = as_decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    if factor <= 1:
        return None
    return factor


def sells_full_package(product: Mapping[str, Any]) -> bool:
    return any(_truthy(product.get(flag)) for flag in _PACKAGE_SALE_FLAGS)


def get_base_units_per_package(product: Mapping[str, Any]) -> Optional[Decimal]:
    """Cantidad de unidad base por empaque completo. Independiente del nombre.

    CAJA/BULTO/SACO/ROLLO/… no cambian la fórmula: 1 FULL_PACKAGE = este factor
    de unidad_base. ``unidades_por_caja`` solo se consulta como storage legado.
    """
    if not sells_full_package(product):
        return None
    presentation = _package_presentation(product).upper()
    if presentation in NO_PACKAGE_SENTINELS:
        return None
    for key in _PACKAGE_SIZE_KEYS:
        factor = _positive_factor(product.get(key))
        if factor is not None:
            return factor
    return None


def canonical_full_package_factor(product: Mapping[str, Any]) -> Optional[Decimal]:
    """Alias estable. Preferir get_base_units_per_package."""
    return get_base_units_per_package(product)


def canonical_custom_factor(product: Mapping[str, Any]) -> Optional[Decimal]:
    """Una sola presentación custom inequívoca. Si hay 0 o >1, no inventa."""
    raw = product.get("unidades_venta_custom")
    if not raw:
        return None
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, list):
        return None
    extras: List[Decimal] = []
    for item in data:
        if not isinstance(item, Mapping):
            continue
        try:
            factor = as_decimal(item.get("factor", 1))
        except (InvalidOperation, ValueError):
            return None
        if factor > 1:
            extras.append(factor)
    if len(extras) != 1:
        return None
    return extras[0]


def _exactly_representable(qty: Decimal, product: Mapping[str, Any]) -> bool:
    if not qty.is_finite() or qty <= 0:
        return False
    if not _truthy(product.get("permite_decimales")) and qty != qty.to_integral_value():
        return False
    exponent = qty.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -QUANTITY_DECIMAL_PLACES:
        return False
    scaled = qty * (10 ** QUANTITY_DECIMAL_PLACES)
    return scaled == scaled.to_integral_value()


def _legacy_half_value(product: Mapping[str, Any]) -> Optional[Decimal]:
    raw = product.get("unidades_por_media_caja")
    if raw in (None, "", 0, "0"):
        return None
    try:
        value = as_decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    if value <= 0:
        return None
    return value


def get_half_package_factor(product: Mapping[str, Any]) -> Optional[Decimal]:
    """Medio empaque = factor canónico / 2. No es una autoridad aparte.

    ``unidades_por_media_caja`` legado, si es un valor explícito, debe coincidir
    o la conversión falla cerrada. El default histórico 1 se ignora salvo
    cuando el empaque completo es 2.
    """
    if not _truthy(product.get("vende_medio_empaque")):
        return None
    full = get_base_units_per_package(product)
    if full is None:
        return None
    half = full / 2
    if not _exactly_representable(half, product):
        return None
    legacy = _legacy_half_value(product)
    if legacy is not None:
        placeholder = legacy == 1 and full != 2
        if not placeholder and legacy != half:
            raise PackagingConversionBlocked(
                PRESENTATION_HALF_PACKAGE,
                "unidades_por_media_caja legado no coincide con factor/2",
            )
    return half


def canonical_half_package_factor(product: Mapping[str, Any]) -> Optional[Decimal]:
    return get_half_package_factor(product)


def quantity_in_base_units(
    product: Mapping[str, Any],
    package_role: Optional[str],
    quantity: Any,
) -> Decimal:
    qty = as_decimal(quantity)
    if qty <= 0:
        raise PackagingError("La cantidad de cada producto debe ser mayor a 0")
    role = str(package_role or PACKAGE_ROLE_BASE_UNIT).strip() or PACKAGE_ROLE_BASE_UNIT
    if role not in ALLOWED_PRESENTATIONS:
        raise PackagingConversionBlocked(role, "package_role desconocido")
    if role == PACKAGE_ROLE_BASE_UNIT:
        return qty
    if role == PACKAGE_ROLE_FULL_PACKAGE:
        factor = get_base_units_per_package(product)
        if factor is None:
            raise PackagingConversionBlocked(
                role, "FULL_PACKAGE sin cantidad de unidad base por empaque"
            )
        return qty * factor
    if role == PRESENTATION_HALF_PACKAGE:
        if not _truthy(product.get("vende_medio_empaque")):
            raise PackagingConversionBlocked(
                role, "HALF_PACKAGE requiere vende_medio_empaque"
            )
        full = get_base_units_per_package(product)
        if full is None:
            raise PackagingConversionBlocked(
                role, "HALF_PACKAGE sin factor canónico de empaque completo"
            )
        half = full / 2
        if not _exactly_representable(half, product):
            raise PackagingConversionBlocked(
                role, "HALF_PACKAGE no representable en la escala del producto"
            )
        factor = get_half_package_factor(product)
        if factor is None:
            raise PackagingConversionBlocked(
                role, "HALF_PACKAGE sin factor canónico de medio empaque"
            )
        return qty * factor
    factor = canonical_custom_factor(product)
    if factor is None:
        raise PackagingConversionBlocked(
            role, "CUSTOM_PRESENTATION sin factor canónico inequívoco"
        )
    return qty * factor


def validate_quantity(product: Mapping[str, Any], quantity: Any) -> Decimal:
    qty = as_decimal(quantity)
    if qty <= 0:
        raise PackagingError("La cantidad de cada producto debe ser mayor a 0")
    permite = _truthy(product.get("permite_decimales"))
    if not permite and qty != qty.to_integral_value():
        raise PackagingError("Este producto no permite cantidades decimales")
    return qty


def validate_cost(cost: Any) -> Decimal:
    value = as_decimal(cost)
    if value < 0:
        raise PackagingError("El costo unitario no puede ser negativo")
    return value
