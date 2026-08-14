# -*- coding: utf-8 -*-
"""Helpers 1E.1."""
from __future__ import annotations

import json

from tests.fase1e.helpers import (
    AuthPermitido,
    ClientesRepoDummy,
    DEVICE,
    FakeHTTPHandler,
)


def applied_record(command_id, request_hash, *, estado="APPLIED", motivo=None):
    from inventory_ledger import InventoryCommandRecord

    return InventoryCommandRecord(
        command_id=command_id,
        tipo="VENTA",
        documento_tipo=None,
        documento_local_id=None,
        device_id=DEVICE,
        usuario_id=None,
        request_hash=request_hash,
        estado=estado,
        resultado=estado,
        motivo=motivo,
        created_at="t",
        updated_at="t",
        operations=(),
        replayed=False,
    )


def transport_applied(calls=None):
    bag = calls if calls is not None else []

    def transport(**kwargs):
        bag.append(kwargs)
        return applied_record(kwargs["command_id"], kwargs["request_hash"])

    transport.calls = bag
    return transport


def transport_rejected(motivo="INSUFFICIENT_STOCK", calls=None):
    bag = calls if calls is not None else []

    def transport(**kwargs):
        bag.append(kwargs)
        return applied_record(
            kwargs["command_id"],
            kwargs["request_hash"],
            estado="REJECTED",
            motivo=motivo,
        )

    transport.calls = bag
    return transport


def transport_unknown(exc=None, calls=None):
    from inventory_coordinator import CoordinatorUnknownOutcomeError

    bag = calls if calls is not None else []
    error = exc or CoordinatorUnknownOutcomeError("lost after persist")

    def transport(**kwargs):
        bag.append(kwargs)
        raise error

    transport.calls = bag
    return transport


def ventas_service(env):
    from services.ventas_service import VentasService
    from repositories.productos_repo import ProductosRepository

    return VentasService(
        env.db, ProductosRepository(env.db), ClientesRepoDummy(), AuthPermitido()
    )


def command_count(conn, *, intent_class=None):
    if intent_class is None:
        row = conn.execute("SELECT COUNT(*) FROM inventory_commands").fetchone()
        return row[0]
    row = conn.execute(
        "SELECT COUNT(*) FROM inventory_commands WHERE intent_class = ?",
        (intent_class,),
    ).fetchone()
    return row[0]


def load_ops(conn, command_id):
    return list(
        conn.execute(
            """
            SELECT operation_id, producto_local_id, delta_scaled, line_no
              FROM inventory_operations
             WHERE command_id = ?
             ORDER BY line_no
            """,
            (command_id,),
        ).fetchall()
    )


def lan_create_sale(env, items, **kwargs):
    from local_server import LocalFerreteriaAPI

    body = json.dumps({"items": items, "metodo_pago": "EFECTIVO"}).encode("utf-8")
    handler = FakeHTTPHandler(env.db_path, body)
    LocalFerreteriaAPI.create_sale(handler, {"usuario_id": 1}, **kwargs)
    return handler
