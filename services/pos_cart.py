# -*- coding: utf-8 -*-
"""Carrito POS local-first. El scan no vende; el commit usa el writer existente."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from barcode_scanner import BarcodeScanError, normalize_barcode
from packaging_conversion import (
    PACKAGING_BLOCKED,
    PackagingConversionBlocked,
    PackagingError,
    as_decimal,
    quantity_in_base_units as _quantity_in_base_units,
    sqlite_number,
    validate_quantity as _validate_quantity,
)
from repositories.product_barcodes_repo import (
    PACKAGE_ROLE_BASE_UNIT,
    PACKAGE_ROLE_CUSTOM_PRESENTATION,
    PACKAGE_ROLE_FULL_PACKAGE,
    PACKAGE_ROLES,
)

OFFLINE_FINALIZE_BLOCKED = (
    "FINALIZAR bloqueado: se requiere autoridad central de inventario. "
    "El carrito puede prepararse en local; no hay stock autoritativo offline."
)


class PosCartError(ValueError):
    pass


def quantity_in_base_units(product, package_role, quantity):
    try:
        return _quantity_in_base_units(product, package_role, quantity)
    except PackagingError as exc:
        raise PosCartError(str(exc)) from exc


def validate_quantity(product, quantity):
    try:
        return _validate_quantity(product, quantity)
    except PackagingError as exc:
        raise PosCartError(str(exc)) from exc


def validate_price(price: Any) -> Decimal:
    value = as_decimal(price)
    if value < 0:
        raise PosCartError("El precio unitario no puede ser negativo")
    return value


def line_subtotal(quantity: Any, price: Any, discount: Any = 0) -> Decimal:
    subtotal = (as_decimal(quantity) * as_decimal(price)) - as_decimal(discount)
    return subtotal


def format_min_receipt(
    *,
    sale_id: Any,
    fecha: Any,
    lines: Sequence[Mapping[str, Any]],
    total: Any,
    numero_factura: Any = "",
) -> str:
    rows = [
        "FERREPRO — COMPROBANTE DE VENTA",
        f"sale_id: {sale_id}",
        f"factura: {numero_factura}",
        f"fecha: {fecha}",
        "--------------------------------",
    ]
    for line in lines:
        rows.append(
            f"{line.get('producto_nombre', 'Producto')}  "
            f"cant={line.get('cantidad')}  "
            f"precio={line.get('precio_unitario')}  "
            f"subtotal={line.get('subtotal')}"
        )
    rows.append("--------------------------------")
    rows.append(f"total: {total}")
    return "\n".join(rows)


def pos_finalize_allowed(
    db=None,
    *,
    sqlite_conn=None,
    inventory_mode: Optional[str] = None,
    inventory_gateway=None,
    inventory_connection_factory=None,
) -> Tuple[bool, Optional[str]]:
    """Gate de COMMIT. No abre PostgreSQL: sqlite + modo de estación."""
    from inventory_cutover import station_mode_is_online
    from inventory_writer_support import (
        WRITER_MODE_AUTHORITATIVE,
        resolve_writer_mode_or_frozen,
    )

    owned = False
    conn = sqlite_conn
    if conn is None and db is not None and hasattr(db, "conectar"):
        conn = db.conectar()
        owned = True
    try:
        mode, frozen = resolve_writer_mode_or_frozen(
            inventory_mode,
            sqlite_conn=conn,
            require_remote=False,
        )
        if frozen:
            return False, frozen
        if mode == WRITER_MODE_AUTHORITATIVE:
            if inventory_gateway is not None or inventory_connection_factory is not None:
                return True, None
            if not station_mode_is_online():
                return False, OFFLINE_FINALIZE_BLOCKED
        return True, None
    finally:
        if owned and conn is not None:
            conn.close()


@dataclass
class ScanResult:
    ok: bool
    product: Optional[dict] = None
    barcode: Optional[str] = None
    package_role: str = PACKAGE_ROLE_BASE_UNIT
    error: Optional[str] = None
    sale_registered: bool = False


@dataclass
class PosCart:
    lines: List[dict] = field(default_factory=list)
    checkout_in_flight: bool = False
    last_scan: Optional[ScanResult] = None

    def clear(self) -> None:
        self.lines = []
        self.checkout_in_flight = False

    def replace_lines(self, lines: Optional[List[dict]]) -> None:
        self.lines = list(lines or [])

    def begin_checkout(self) -> bool:
        if self.checkout_in_flight:
            return False
        if not self.lines:
            return False
        self.checkout_in_flight = True
        return True

    def end_checkout(self) -> None:
        self.checkout_in_flight = False

    def add_scan(self, productos_repo, raw_barcode: str) -> ScanResult:
        """Resuelve barcode y agrega al carrito. Nunca registra una venta."""
        try:
            barcode = normalize_barcode(raw_barcode)
        except BarcodeScanError as exc:
            result = ScanResult(ok=False, error=str(exc), sale_registered=False)
            self.last_scan = result
            return result
        product = productos_repo.obtener_por_codigo(barcode)
        if not product:
            result = ScanResult(
                ok=False,
                barcode=barcode,
                error=f"No se encontró producto: {barcode}",
                sale_registered=False,
            )
            self.last_scan = result
            return result
        role = str(product.get("matched_package_role") or PACKAGE_ROLE_BASE_UNIT)
        try:
            qty_base = quantity_in_base_units(product, role, Decimal("1"))
            qty_base = validate_quantity(product, qty_base)
        except (PackagingConversionBlocked, PosCartError) as exc:
            result = ScanResult(
                ok=False,
                product=product,
                barcode=barcode,
                package_role=role,
                error=str(exc),
                sale_registered=False,
            )
            self.last_scan = result
            return result
        self.add_manual(
            product,
            qty_base,
            package_role=role,
            barcode=barcode,
        )
        result = ScanResult(
            ok=True,
            product=product,
            barcode=barcode,
            package_role=role,
            sale_registered=False,
        )
        self.last_scan = result
        return result

    def add_manual(
        self,
        product: Mapping[str, Any],
        quantity: Any,
        *,
        package_role: str = PACKAGE_ROLE_BASE_UNIT,
        barcode: Optional[str] = None,
        precio_unitario: Any = None,
        descuento: Any = 0,
    ) -> dict:
        qty = validate_quantity(product, quantity)
        price = validate_price(
            product.get("precio_venta", 0) if precio_unitario is None else precio_unitario
        )
        disc = as_decimal(descuento)
        if disc < 0:
            raise PosCartError("El descuento no puede ser negativo")
        prod_id = product.get("id")
        if prod_id is not None:
            for line in self.lines:
                if line.get("es_mezcla"):
                    continue
                same_product = line.get("producto", {}).get("id") == prod_id
                same_role = (
                    str(line.get("package_role") or PACKAGE_ROLE_BASE_UNIT)
                    == str(package_role or PACKAGE_ROLE_BASE_UNIT)
                )
                if same_product and same_role:
                    line["cantidad"] = as_decimal(line["cantidad"]) + qty
                    return line
        line = {
            "producto": dict(product),
            "cantidad": qty,
            "precio_unitario": price,
            "descuento": disc,
            "package_role": package_role or PACKAGE_ROLE_BASE_UNIT,
            "matched_barcode": barcode,
        }
        self.lines.append(line)
        return line

    def set_quantity(self, index: int, quantity: Any) -> None:
        if index < 0 or index >= len(self.lines):
            raise PosCartError("Línea de carrito inexistente")
        line = self.lines[index]
        line["cantidad"] = validate_quantity(line.get("producto") or {}, quantity)

    def remove_line(self, index: int) -> None:
        if index < 0 or index >= len(self.lines):
            raise PosCartError("Línea de carrito inexistente")
        del self.lines[index]

    def totals(self, descuento_general: Any = 0) -> Tuple[Decimal, Decimal]:
        subtotal = sum(
            (
                line_subtotal(
                    line.get("cantidad"),
                    line.get("precio_unitario"),
                    line.get("descuento", 0),
                )
                for line in self.lines
            ),
            Decimal("0"),
        )
        discount = as_decimal(descuento_general)
        if discount < 0:
            raise PosCartError("El descuento general no puede ser negativo")
        if discount > subtotal:
            raise PosCartError("El descuento general no puede superar el subtotal de la venta")
        return subtotal, subtotal - discount

    def to_sale_items(self) -> List[dict]:
        items: List[dict] = []
        for line in self.lines:
            if line.get("es_mezcla"):
                componentes = line.get("mezcla_componentes") or []
                precio_mezcla = as_decimal(line.get("precio_unitario")) * as_decimal(
                    line.get("cantidad")
                )
                costo_total = sum(
                    (as_decimal(c.get("costo", 0)) for c in componentes), Decimal("0")
                )
                for comp in componentes:
                    if costo_total > 0:
                        proporcion = as_decimal(comp.get("costo", 0)) / costo_total
                    else:
                        proporcion = (
                            Decimal("1") / Decimal(len(componentes))
                            if componentes
                            else Decimal("1")
                        )
                    cant = as_decimal(comp.get("cantidad") or 0)
                    precio = (
                        (precio_mezcla * proporcion / cant) if cant > 0 else Decimal("0")
                    )
                    items.append(
                        {
                            "producto_id": comp["producto_id"],
                            "cantidad": sqlite_number(cant),
                            "precio_unitario": sqlite_number(precio),
                            "descuento": 0,
                        }
                    )
                continue
            items.append(
                {
                    "producto_id": line["producto"]["id"],
                    "cantidad": sqlite_number(line["cantidad"]),
                    "precio_unitario": sqlite_number(line["precio_unitario"]),
                    "descuento": sqlite_number(line.get("descuento") or 0),
                }
            )
        return items
