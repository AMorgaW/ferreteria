# -*- coding: utf-8 -*-
"""Helpers Fase 5. SQLite temporal. Nunca ferreteria.db comercial."""
from __future__ import annotations

import hashlib
from pathlib import Path

from tests.fase0.harness import REPO_FERRETERIA_DB
from tests.fase1e.helpers import AuthPermitido, ClientesRepoDummy
from tests.fase3d.helpers import (
    assert_not_commercial_db,
    caja_service,
    complete_sale_cash,
    count_movements,
    open_caja,
    phase3d_env,
    pos_service,
    seed_pos_product,
)

phase5_env = phase3d_env

__all__ = [
    "assert_not_commercial_db",
    "caja_service",
    "commercial_sha256",
    "complete_sale_cash",
    "count_movements",
    "open_caja",
    "phase5_env",
    "pos_service",
    "pos_service_as",
    "seed_pos_product",
]


def commercial_sha256() -> str:
    if not REPO_FERRETERIA_DB.exists():
        return ""
    return hashlib.sha256(REPO_FERRETERIA_DB.read_bytes()).hexdigest()


def pos_service_as(env, rol="VENDEDOR", station_id="W01"):
    from repositories.productos_repo import ProductosRepository
    from services.ventas_service import VentasService

    svc = VentasService(
        env.db,
        ProductosRepository(env.db),
        ClientesRepoDummy(),
        AuthPermitido(rol=rol),
    )
    svc.cash_station_id = station_id
    return svc


def complete_sale_as(env, rol="VENDEDOR", items=None, station_id="W01", **kwargs):
    import uuid

    from tests.fase1e1.helpers import transport_applied

    svc = pos_service_as(env, rol=rol, station_id=station_id)
    items = items or [{"producto_id": 1, "cantidad": 1, "precio_unitario": 1000}]
    kwargs.setdefault("metodo_pago", "EFECTIVO")
    kwargs.setdefault("inventory_mode", "authoritative")
    kwargs.setdefault("inventory_command_id", str(uuid.uuid4()))
    kwargs.setdefault("inventory_transport", transport_applied())
    ok, msg, venta = svc.registrar_venta(items=items, **kwargs)
    if not ok:
        raise AssertionError(msg)
    return venta
