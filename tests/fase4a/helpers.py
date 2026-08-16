# -*- coding: utf-8 -*-
"""Helpers Fase 4A. SQLite temporal. Nunca ferreteria.db comercial."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from services.reportes_compras_service import ReportesComprasService
from services.reportes_service import ReportesService
from tests.fase0.harness import REPO_FERRETERIA_DB
from tests.fase3a.helpers import assert_not_commercial_db, phase3a_env, seed_pos_product
from tests.fase3b.helpers import compras_service, seed_purchase_product
from tests.fase3c.helpers import complete_receipt, complete_sale, returns_service
from tests.fase3d.helpers import caja_service, open_caja, pos_service

phase4a_env = phase3a_env

__all__ = [
    "assert_not_commercial_db",
    "caja_service",
    "complete_receipt",
    "complete_sale",
    "compras_service",
    "ensure_inventory_balance",
    "open_caja",
    "phase4a_env",
    "pos_service",
    "reportes_compras",
    "reportes_service",
    "returns_service",
    "seed_pos_product",
    "seed_purchase_product",
]


def reportes_service(env) -> ReportesService:
    return ReportesService(env.db)


def reportes_compras(env) -> ReportesComprasService:
    return ReportesComprasService(env.db, proveedores_repo=None)


def ensure_inventory_balance(conn, producto_local_id: str, quantity_scaled: int) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_balances (
            producto_local_id TEXT PRIMARY KEY,
            quantity_scaled INTEGER NOT NULL,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO inventory_balances (producto_local_id, quantity_scaled)
        VALUES (?, ?)
        ON CONFLICT(producto_local_id) DO UPDATE SET quantity_scaled = excluded.quantity_scaled
        """,
        (producto_local_id, int(quantity_scaled)),
    )


def commercial_db_mtime():
    if REPO_FERRETERIA_DB.exists():
        return REPO_FERRETERIA_DB.stat().st_mtime
    return None


def assert_commercial_untouched(before) -> None:
    resolved_repo = REPO_FERRETERIA_DB.resolve()
    if REPO_FERRETERIA_DB.exists():
        assert REPO_FERRETERIA_DB.stat().st_mtime == before
    assert Path(resolved_repo).name == "ferreteria.db"
