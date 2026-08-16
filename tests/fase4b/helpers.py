# -*- coding: utf-8 -*-
"""Helpers Fase 4B. SQLite temporal. Nunca ferreteria.db comercial."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from models import Abono, AbonoVenta
from services.cuentas_por_cobrar_service import CuentasPorCobrarService
from services.deudas_service import DeudasService
from tests.fase0.harness import REPO_FERRETERIA_DB
from tests.fase1e.helpers import insert_usuario
from tests.fase3a.helpers import assert_not_commercial_db, phase3a_env, seed_pos_product
from tests.fase3c.helpers import complete_receipt, complete_sale, returns_service
from tests.fase3d.helpers import caja_service, count_movements, open_caja
from tests.fase4a.helpers import assert_commercial_untouched, commercial_db_mtime

phase4b_env = phase3a_env


def cxc(env) -> CuentasPorCobrarService:
    return CuentasPorCobrarService(str(env.db_path))


def cxp(env) -> DeudasService:
    return DeudasService(str(env.db_path))


def seed_cliente(env, nombre="Cliente 4B", documento="CC-4B-1"):
    conn = env.connect()
    try:
        conn.execute(
            "INSERT INTO clientes (numero_documento, nombre, activo) VALUES (?, ?, 1)",
            (documento, nombre),
        )
        cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        return cid
    finally:
        conn.close()


def seed_ops(env, stock=50, precio=100):
    conn = env.connect()
    try:
        if conn.execute("SELECT 1 FROM usuarios WHERE id=1").fetchone() is None:
            insert_usuario(conn)
        if conn.execute("SELECT 1 FROM proveedores WHERE id=1").fetchone() is None:
            env.insert_proveedor(conn)
        conn.commit()
    finally:
        conn.close()
    return seed_pos_product(env, stock=stock, precio_venta=precio)


def credit_sale(env, total=100, cliente_id=None, cantidad=1):
    return complete_sale(
        env,
        [{"producto_id": 1, "cantidad": cantidad, "precio_unitario": total}],
        metodo_pago="CREDITO",
        cliente_id=cliente_id,
    )


def credit_purchase(env, total=100, cantidad=1):
    return complete_receipt(
        env,
        [{"producto_id": 1, "cantidad": cantidad, "precio_unitario": total}],
        tipo_compra="CREDITO",
        numero_factura=f"P-{uuid.uuid4().hex[:8]}",
    )


def pay_customer(env, venta_id, monto, tipo_pago="EFECTIVO", local_id=None):
    from repositories.abonos_ventas_repo import AbonosVentasRepository

    repo = AbonosVentasRepository(str(env.db_path))
    return repo.crear_abono(
        AbonoVenta(
            id_venta=venta_id,
            monto_abono=monto,
            fecha_abono=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            tipo_pago=tipo_pago,
            usuario="tester",
            local_id=local_id,
        )
    )


def pay_supplier(env, compra_id, monto, tipo_pago="EFECTIVO", local_id=None):
    from repositories.abonos_compras_repo import AbonosaComprasRepository

    repo = AbonosaComprasRepository(str(env.db_path))
    return repo.crear_abono(
        Abono(
            id_compra=compra_id,
            monto_abono=monto,
            fecha_abono=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            tipo_pago=tipo_pago,
            usuario="tester",
            local_id=local_id,
        )
    )


def confirm_return(env, original_id, kind, cantidad, original_tipo="venta"):
    from tests.fase1e1.helpers import transport_applied
    from returns_schema import ORIGINAL_TIPO_COMPRA, ORIGINAL_TIPO_VENTA

    svc = returns_service(env)
    tipo = ORIGINAL_TIPO_COMPRA if original_tipo == "compra" else ORIGINAL_TIPO_VENTA
    ok, msg, rid = svc.guardar_borrador(
        kind=kind,
        original_tipo=tipo,
        original_id=original_id,
        items=[{"producto_id": 1, "cantidad": cantidad}],
    )
    if not ok:
        raise AssertionError(msg)
    ok2, msg2, _ = svc.confirmar(
        rid,
        inventory_mode="authoritative",
        inventory_command_id=str(uuid.uuid4()),
        inventory_transport=transport_applied(),
    )
    if not ok2:
        raise AssertionError(msg2)
    return rid


def money_eq(value, expected):
    from services.caja_service import money

    return money(value) == money(expected)
