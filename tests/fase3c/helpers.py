# -*- coding: utf-8 -*-
"""Helpers Fase 3C. SQLite temporal + fixtures. Nunca ferreteria.db comercial."""
from __future__ import annotations

import uuid

from repositories.productos_repo import ProductosRepository
from services.returns_service import ReturnsService
from tests.fase1e.helpers import AuthPermitido
from tests.fase1e1.helpers import transport_applied, ventas_service
from tests.fase3a.helpers import (
    PACKAGE_ROLE_BASE_UNIT,
    assert_not_commercial_db,
    create_product,
    phase3a_env,
    seed_pos_product,
)
from tests.fase3b.helpers import compras_service, seed_purchase_product

phase3c_env = phase3a_env

__all__ = [
    "PACKAGE_ROLE_BASE_UNIT",
    "assert_not_commercial_db",
    "complete_receipt",
    "complete_sale",
    "compras_service",
    "create_product",
    "phase3c_env",
    "returns_service",
    "seed_pos_product",
    "seed_purchase_product",
]


def returns_service(env):
    return ReturnsService(
        env.db, auth=AuthPermitido(), productos_repo=ProductosRepository(env.db)
    )


def complete_sale(env, items=None, **kwargs):
    items = items or [{"producto_id": 1, "cantidad": 5, "precio_unitario": 1000}]
    kwargs.setdefault("inventory_mode", "authoritative")
    kwargs.setdefault("inventory_command_id", str(uuid.uuid4()))
    kwargs.setdefault("inventory_transport", transport_applied())
    ok, msg, venta = ventas_service(env).registrar_venta(items=items, **kwargs)
    if not ok:
        raise AssertionError(msg)
    return venta


def complete_receipt(env, productos=None, **kwargs):
    productos = productos or [
        {"producto_id": 1, "cantidad": 10, "precio_unitario": 50}
    ]
    kwargs.setdefault("inventory_mode", "authoritative")
    kwargs.setdefault("inventory_command_id", str(uuid.uuid4()))
    kwargs.setdefault("inventory_transport", transport_applied())
    kwargs.setdefault("numero_factura", f"R-{uuid.uuid4().hex[:8]}")
    ok, msg, cid = compras_service(env).confirmar_recepcion(
        proveedor_id=1, productos=productos, **kwargs
    )
    if not ok:
        raise AssertionError(msg)
    return cid
