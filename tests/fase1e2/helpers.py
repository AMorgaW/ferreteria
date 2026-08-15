# -*- coding: utf-8 -*-
"""Helpers 1E.2."""
from __future__ import annotations

from models import Producto
from tests.fase1e1.helpers import (  # noqa: F401
    applied_record,
    command_count,
    lan_create_sale,
    load_ops,
    transport_applied,
    transport_rejected,
    transport_unknown,
    ventas_service,
)


def make_producto(**kwargs):
    defaults = dict(
        nombre="Prod 1E2",
        precio_venta=1000,
        precio_compra=500,
        stock=0,
        categoria="test",
        marca="1E2",
        presentacion="u",
        unidad_medida="UNIDAD",
    )
    defaults.update(kwargs)
    return Producto(**defaults)
