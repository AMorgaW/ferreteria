# -*- coding: utf-8 -*-
"""Helpers Fase 3D. SQLite temporal. Nunca ferreteria.db comercial."""
from __future__ import annotations

from decimal import Decimal

from models import Abono, AbonoVenta
from services.caja_service import CajaService, money
from tests.fase1e.helpers import AuthPermitido
from tests.fase1e1.helpers import ventas_service
from tests.fase3a.helpers import assert_not_commercial_db, phase3a_env, seed_pos_product
from tests.fase3c.helpers import complete_receipt, complete_sale, returns_service

phase3d_env = phase3a_env

__all__ = [
    "assert_not_commercial_db",
    "caja_service",
    "complete_receipt",
    "complete_sale_cash",
    "count_movements",
    "money",
    "open_caja",
    "phase3d_env",
    "pos_service",
    "returns_on",
    "seed_pos_product",
]


def caja_service(env, station_id="W01", rol="ADMIN"):
    svc = CajaService(env.db, AuthPermitido(rol=rol), station_id=station_id)
    return svc


def open_caja(env, monto=Decimal("100000"), station_id="W01"):
    svc = caja_service(env, station_id=station_id)
    ok, msg = svc.abrir_caja(monto)
    if not ok:
        raise AssertionError(msg)
    return svc


def pos_service(env, station_id="W01"):
    svc = ventas_service(env)
    svc.cash_station_id = station_id
    return svc


def complete_sale_cash(env, items=None, station_id="W01", **kwargs):
    svc = pos_service(env, station_id)
    items = items or [{"producto_id": 1, "cantidad": 1, "precio_unitario": 1000}]
    kwargs.setdefault("metodo_pago", "EFECTIVO")
    kwargs.setdefault("inventory_mode", "authoritative")
    kwargs.setdefault("inventory_command_id", str(__import__("uuid").uuid4()))
    from tests.fase1e1.helpers import transport_applied

    kwargs.setdefault("inventory_transport", transport_applied())
    ok, msg, venta = svc.registrar_venta(items=items, **kwargs)
    if not ok:
        raise AssertionError(msg)
    return venta


def returns_on(env, station_id="W01"):
    svc = returns_service(env)
    svc.cash_station_id = station_id
    return svc


def count_movements(env, session_id=None, source_kind=None):
    conn = env.connect()
    try:
        sql = "SELECT COUNT(*) FROM cash_movements WHERE 1=1"
        params = []
        if session_id is not None:
            sql += " AND cash_session_id = ?"
            params.append(session_id)
        if source_kind is not None:
            sql += " AND source_kind = ?"
            params.append(source_kind)
        return conn.execute(sql, params).fetchone()[0]
    finally:
        conn.close()


def registrar_abono_cliente(env, venta_id, monto, tipo_pago="EFECTIVO"):
    from datetime import datetime
    from repositories.abonos_ventas_repo import AbonosVentasRepository

    repo = AbonosVentasRepository(str(env.db_path))
    return repo.crear_abono(
        AbonoVenta(
            id_venta=venta_id,
            monto_abono=monto,
            fecha_abono=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            tipo_pago=tipo_pago,
            usuario="tester",
        )
    )


def registrar_abono_proveedor(env, compra_id, monto, tipo_pago="EFECTIVO"):
    from datetime import datetime
    from repositories.abonos_compras_repo import registrar_abono_compra_en_transaccion

    conn = env.connect()
    try:
        abono_id = registrar_abono_compra_en_transaccion(
            conn,
            conn.cursor(),
            Abono(
                id_compra=compra_id,
                monto_abono=monto,
                fecha_abono=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                tipo_pago=tipo_pago,
                usuario="tester",
            ),
        )
        conn.commit()
        return abono_id
    finally:
        conn.close()
