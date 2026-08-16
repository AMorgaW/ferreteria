# -*- coding: utf-8 -*-
"""Helpers Fase 4C. SQLite temporal. Nunca ferreteria.db comercial."""
from __future__ import annotations

from tests.fase4a.helpers import (
    assert_commercial_untouched,
    assert_not_commercial_db,
    commercial_db_mtime,
    complete_receipt,
    complete_sale,
    phase4a_env,
    seed_pos_product,
    seed_purchase_product,
)
from tests.fase4b.helpers import (
    confirm_return,
    credit_sale,
    pay_customer,
    pay_supplier,
    seed_cliente,
    seed_ops,
)
from services.document_service import DocumentService

phase4c_env = phase4a_env

BUSINESS_TABLES = (
    "ventas",
    "detalle_ventas",
    "compras",
    "detalle_compras",
    "reversal_documents",
    "reversal_lines",
    "cash_movements",
    "cierres_caja",
    "abonos_ventas",
    "abonos_compras",
    "inventory_balances",
    "movimientos",
)


def docs(env) -> DocumentService:
    return DocumentService(env.db)


def ensure_proveedor(env, proveedor_id: int = 1) -> None:
    conn = env.connect()
    try:
        if conn.execute(
            "SELECT 1 FROM proveedores WHERE id=?", (proveedor_id,)
        ).fetchone() is None:
            env.insert_proveedor(conn, proveedor_id=proveedor_id)
            conn.commit()
    finally:
        conn.close()


def business_fingerprint(env) -> str:
    conn = env.connect()
    try:
        parts = []
        for table in BUSINESS_TABLES:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if not exists:
                continue
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            parts.append(f"{table}:{count}")
        return "|".join(parts)
    finally:
        conn.close()
