# -*- coding: utf-8 -*-
"""Carrito de compra/recepción local-first. El draft no mueve stock."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from barcode_scanner import BarcodeScanError, normalize_barcode
from packaging_conversion import (
    PACKAGING_BLOCKED,
    PRESENTATION_HALF_PACKAGE,
    PackagingConversionBlocked,
    PackagingError,
    as_decimal,
    quantity_in_base_units,
    sqlite_number,
    validate_cost,
    validate_quantity,
)
from repositories.product_barcodes_repo import PACKAGE_ROLE_BASE_UNIT
from services.pos_cart import OFFLINE_FINALIZE_BLOCKED, pos_finalize_allowed

ESTADO_DRAFT = "DRAFT"
ESTADO_COMPLETADA = "COMPLETADA"
ESTADO_CANCELADA = "CANCELADA"
COMPLETED_IMMUTABLE = "Una recepción COMPLETED no se edita; use una operación posterior."
receipt_finalize_allowed = pos_finalize_allowed


class PurchaseCartError(ValueError):
    pass


def line_subtotal(quantity: Any, cost: Any) -> Decimal:
    return as_decimal(quantity) * as_decimal(cost)


def format_min_receipt(
    *,
    compra_id: Any,
    fecha: Any,
    proveedor: Any,
    numero_factura: Any,
    lines: Sequence[Mapping[str, Any]],
    total: Any,
) -> str:
    rows = [
        "FERREPRO — RECEPCIÓN DE MERCANCÍA",
        f"compra_id: {compra_id}",
        f"proveedor: {proveedor}",
        f"factura: {numero_factura}",
        f"fecha: {fecha}",
        "--------------------------------",
    ]
    for line in lines:
        rows.append(
            f"{line.get('producto_nombre', 'Producto')}  "
            f"cant={line.get('cantidad_presentacion', line.get('cantidad'))}  "
            f"base={line.get('cantidad')}  "
            f"costo={line.get('precio_unitario')}  "
            f"subtotal={line.get('subtotal')}"
        )
    rows.append("--------------------------------")
    rows.append(f"total: {total}")
    return "\n".join(rows)


@dataclass
class ScanResult:
    ok: bool
    product: Optional[dict] = None
    barcode: Optional[str] = None
    package_role: str = PACKAGE_ROLE_BASE_UNIT
    error: Optional[str] = None
    receipt_confirmed: bool = False
    via_supplier_alias: bool = False


@dataclass
class PurchaseCart:
    lines: List[dict] = field(default_factory=list)
    confirm_in_flight: bool = False
    last_scan: Optional[ScanResult] = None
    proveedor_id: Optional[int] = None

    def clear(self) -> None:
        self.lines = []
        self.confirm_in_flight = False

    def begin_confirm(self) -> bool:
        if self.confirm_in_flight:
            return False
        if not self.lines:
            return False
        self.confirm_in_flight = True
        return True

    def end_confirm(self) -> None:
        self.confirm_in_flight = False

    def add_scan(
        self,
        productos_repo,
        raw_barcode: str,
        *,
        aliases_repo=None,
        proveedor_id: Optional[int] = None,
        costo_unitario: Any = None,
    ) -> ScanResult:
        try:
            barcode = normalize_barcode(raw_barcode)
        except BarcodeScanError as exc:
            result = ScanResult(ok=False, error=str(exc), receipt_confirmed=False)
            self.last_scan = result
            return result
        product = productos_repo.obtener_por_codigo(barcode)
        via_alias = False
        if product is None and aliases_repo is not None and proveedor_id:
            product = aliases_repo.lookup_product(proveedor_id, barcode)
            via_alias = product is not None
        if not product:
            result = ScanResult(
                ok=False,
                barcode=barcode,
                error=f"No se encontró producto: {barcode}",
                receipt_confirmed=False,
            )
            self.last_scan = result
            return result
        role = PACKAGE_ROLE_BASE_UNIT if via_alias else str(
            product.get("matched_package_role") or PACKAGE_ROLE_BASE_UNIT
        )
        try:
            self.add_line(
                product,
                Decimal("1"),
                package_role=role,
                costo_unitario=costo_unitario,
                barcode=None if via_alias else barcode,
                supplier_alias=barcode if via_alias else None,
            )
        except (PackagingConversionBlocked, PackagingError, PurchaseCartError) as exc:
            result = ScanResult(
                ok=False,
                product=product,
                barcode=barcode,
                package_role=role,
                error=str(exc),
                receipt_confirmed=False,
                via_supplier_alias=via_alias,
            )
            self.last_scan = result
            return result
        result = ScanResult(
            ok=True,
            product=product,
            barcode=barcode,
            package_role=role,
            receipt_confirmed=False,
            via_supplier_alias=via_alias,
        )
        self.last_scan = result
        return result

    def add_line(
        self,
        product: Mapping[str, Any],
        quantity: Any,
        *,
        package_role: str = PACKAGE_ROLE_BASE_UNIT,
        costo_unitario: Any = None,
        barcode: Optional[str] = None,
        supplier_alias: Optional[str] = None,
    ) -> dict:
        qty_pres = validate_quantity(product, quantity)
        try:
            qty_base = quantity_in_base_units(product, package_role, qty_pres)
        except PackagingError as exc:
            raise PurchaseCartError(str(exc)) from exc
        if costo_unitario is None:
            costo_unitario = product.get("precio_compra", 0)
        cost = validate_cost(costo_unitario)
        prod_id = product.get("id")
        role = str(package_role or PACKAGE_ROLE_BASE_UNIT)
        alias = str(supplier_alias or "").strip() or None
        if prod_id is not None:
            for line in self.lines:
                same_product = line.get("producto", {}).get("id") == prod_id
                same_role = str(line.get("package_role") or PACKAGE_ROLE_BASE_UNIT) == role
                same_alias = (line.get("supplier_alias") or None) == alias
                if same_product and same_role and same_alias:
                    line["cantidad_presentacion"] = (
                        as_decimal(line["cantidad_presentacion"]) + qty_pres
                    )
                    line["cantidad"] = as_decimal(line["cantidad"]) + qty_base
                    return line
        line = {
            "producto": dict(product),
            "cantidad_presentacion": qty_pres,
            "cantidad": qty_base,
            "precio_unitario": cost,
            "package_role": role,
            "matched_barcode": barcode,
            "supplier_alias": alias,
        }
        self.lines.append(line)
        return line

    def set_quantity(self, index: int, quantity: Any) -> None:
        if index < 0 or index >= len(self.lines):
            raise PurchaseCartError("Línea de recepción inexistente")
        line = self.lines[index]
        product = line.get("producto") or {}
        qty_pres = validate_quantity(product, quantity)
        line["cantidad_presentacion"] = qty_pres
        line["cantidad"] = quantity_in_base_units(
            product, line.get("package_role"), qty_pres
        )

    def set_cost(self, index: int, cost: Any) -> None:
        if index < 0 or index >= len(self.lines):
            raise PurchaseCartError("Línea de recepción inexistente")
        self.lines[index]["precio_unitario"] = validate_cost(cost)

    def remove_line(self, index: int) -> None:
        if index < 0 or index >= len(self.lines):
            raise PurchaseCartError("Línea de recepción inexistente")
        del self.lines[index]

    def totals(self) -> Tuple[Decimal, Decimal]:
        subtotal = sum(
            (
                line_subtotal(line.get("cantidad_presentacion"), line.get("precio_unitario"))
                for line in self.lines
            ),
            Decimal("0"),
        )
        return subtotal, subtotal

    def to_purchase_items(self) -> List[dict]:
        items = []
        for line in self.lines:
            subtotal = line_subtotal(
                line.get("cantidad_presentacion"), line.get("precio_unitario")
            )
            items.append(
                {
                    "producto_id": line["producto"]["id"],
                    "cantidad": sqlite_number(line["cantidad"]),
                    "cantidad_presentacion": sqlite_number(line["cantidad_presentacion"]),
                    "precio_unitario": sqlite_number(line["precio_unitario"]),
                    "subtotal": sqlite_number(subtotal),
                    "package_role": line.get("package_role") or PACKAGE_ROLE_BASE_UNIT,
                    "supplier_alias": line.get("supplier_alias"),
                }
            )
        return items
