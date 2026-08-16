# -*- coding: utf-8 -*-
"""Adapter READ-ONLY de inventario para reporting (Fase 4A).

Fuente local de cantidad actual, en este orden:

1. SQLite ``inventory_balances.quantity_scaled`` (proyección local de la
   autoridad online). Nunca consulta PostgreSQL.
2. Si la tabla no existe: ``LEGACY_PROJECTION`` desde ``productos.stock``
   convertida con ``quantity_to_scaled`` / ``scaled_to_decimal``.

``productos.stock`` nunca se trata como autoridad. Si existe
``inventory_balances``, su valor gana aunque ``productos.stock`` difiera.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import schema_bootstrap
from inventory_ledger import (
    QUANTITY_SCALE,
    quantity_to_scaled,
    scaled_to_decimal,
)
from services.caja_service import money

SOURCE_INVENTORY_BALANCES = "inventory_balances"
SOURCE_LEGACY_PROJECTION = "LEGACY_PROJECTION"
VALOR_BASIS_ESTIMATED = "ESTIMATED"

assert QUANTITY_SCALE == 1000


def _as_decimal_qty(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(str(value))


def _as_money(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0.00")
    return money(value)


def _row_dict(row) -> dict:
    if row is None:
        return {}
    if isinstance(row, dict):
        return row
    try:
        return dict(row)
    except Exception:
        return {}


def local_inventory_balances_exist(conn) -> bool:
    return schema_bootstrap.table_exists(conn, "inventory_balances")


def load_quantity_scaled_index(conn) -> Tuple[Dict[str, int], str]:
    """Mapa producto_local_id → quantity_scaled y etiqueta de fuente.

    No abre red. No lee ``productos.stock`` cuando hay balances locales.
    """
    if local_inventory_balances_exist(conn):
        rows = conn.execute(
            "SELECT producto_local_id, quantity_scaled FROM inventory_balances"
        ).fetchall()
        index = {}
        for raw in rows:
            row = _row_dict(raw)
            lid = str(row.get("producto_local_id") or "").strip()
            if not lid:
                continue
            index[lid] = int(row.get("quantity_scaled") or 0)
        return index, SOURCE_INVENTORY_BALANCES
    return {}, SOURCE_LEGACY_PROJECTION


def _estado_stock(cantidad: Decimal, stock_minimo: Decimal) -> str:
    if cantidad <= 0:
        return "AGOTADO"
    if cantidad <= stock_minimo:
        return "CRITICO"
    if stock_minimo > 0 and cantidad <= (stock_minimo * Decimal("1.5")):
        return "BAJO"
    return "NORMAL"


def _quantity_for_product(product: dict, balances: Dict[str, int], source: str) -> Tuple[int, Decimal]:
    lid = str(product.get("local_id") or "").strip()
    if source == SOURCE_INVENTORY_BALANCES:
        scaled = int(balances.get(lid, 0)) if lid else 0
        return scaled, scaled_to_decimal(scaled)
    stock_legacy = product.get("stock")
    if stock_legacy is None or stock_legacy == "":
        return 0, Decimal("0")
    scaled = quantity_to_scaled(_as_decimal_qty(stock_legacy))
    return scaled, scaled_to_decimal(scaled)


def list_reporting_inventory(conn, *, solo_activos: bool = True) -> List[Dict[str, Any]]:
    """Catálogo + cantidad reporting. Una sola pasada local."""
    balances, source = load_quantity_scaled_index(conn)
    sql = """
        SELECT
            p.id,
            p.local_id,
            p.codigo_barras,
            p.nombre,
            p.categoria,
            p.marca,
            p.presentacion,
            p.stock,
            p.stock_minimo,
            p.precio_compra,
            p.precio_venta,
            p.unidad_medida,
            p.permite_decimales,
            p.activo,
            p.proveedor_id,
            pr.nombre AS proveedor_nombre
        FROM productos p
        LEFT JOIN proveedores pr ON pr.id = p.proveedor_id
    """
    if solo_activos:
        sql += " WHERE COALESCE(p.activo, 1) = 1"
    sql += " ORDER BY p.nombre"
    rows = conn.execute(sql).fetchall()
    result = []
    for raw in rows:
        product = _row_dict(raw)
        scaled, cantidad = _quantity_for_product(product, balances, source)
        stock_minimo = _as_decimal_qty(product.get("stock_minimo") or 0)
        precio_compra = _as_money(product.get("precio_compra") or 0)
        precio_venta = _as_money(product.get("precio_venta") or 0)
        valor = (cantidad * precio_compra)
        estado = _estado_stock(cantidad, stock_minimo)
        result.append(
            {
                "id": product.get("id"),
                "local_id": product.get("local_id"),
                "codigo_barras": product.get("codigo_barras"),
                "nombre": product.get("nombre"),
                "categoria": product.get("categoria"),
                "marca": product.get("marca"),
                "presentacion": product.get("presentacion"),
                "quantity_scaled": scaled,
                "cantidad_actual": cantidad,
                "stock": cantidad,
                "stock_minimo": stock_minimo,
                "unidad_medida": product.get("unidad_medida") or "Unidad",
                "unidad_base": product.get("unidad_medida") or "Unidad",
                "permite_decimales": product.get("permite_decimales"),
                "precio_compra": precio_compra,
                "precio_venta": precio_venta,
                "valor_inventario": valor,
                "estado_stock": estado,
                "activo": product.get("activo"),
                "proveedor_id": product.get("proveedor_id"),
                "proveedor_nombre": product.get("proveedor_nombre"),
                "quantity_source": source,
                "valor_basis": VALOR_BASIS_ESTIMATED,
            }
        )
    return result


def productos_stock_critico(conn) -> List[Dict[str, Any]]:
    rows = []
    for item in list_reporting_inventory(conn, solo_activos=True):
        cantidad = item["cantidad_actual"]
        minimo = item["stock_minimo"]
        if cantidad <= minimo:
            diferencia = minimo - cantidad
            rows.append(
                {
                    "id": item["id"],
                    "nombre": item["nombre"],
                    "categoria": item.get("categoria") or "-",
                    "stock_actual": cantidad,
                    "stock_minimo": minimo,
                    "diferencia": diferencia,
                    "unidad_base": item["unidad_base"],
                    "proveedor_id": item.get("proveedor_id"),
                    "proveedor_nombre": item.get("proveedor_nombre"),
                    "quantity_scaled": item["quantity_scaled"],
                    "quantity_source": item["quantity_source"],
                    "estado_stock": item["estado_stock"],
                }
            )
    rows.sort(key=lambda x: x["diferencia"], reverse=True)
    return rows


def inventory_by_product_id(conn) -> Dict[Any, Dict[str, Any]]:
    return {row["id"]: row for row in list_reporting_inventory(conn, solo_activos=False)}
