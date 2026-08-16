# -*- coding: utf-8 -*-
"""Helpers Fase 3B. SQLite temporal + fixtures. Nunca ferreteria.db comercial."""
from __future__ import annotations

from pathlib import Path

from repositories.proveedores_repo import ProveedoresRepository
from services.compras_service import ComprasService
from tests.fase0.harness import REPO_FERRETERIA_DB
from tests.fase1e.helpers import AuthPermitido, insert_usuario
from tests.fase3a.helpers import (
    PACKAGE_ROLE_BASE_UNIT,
    assert_not_commercial_db,
    create_product,
    phase3a_env,
    seed_pos_product,
)

phase3b_env = phase3a_env

__all__ = [
    "PACKAGE_ROLE_BASE_UNIT",
    "assert_not_commercial_db",
    "compras_service",
    "create_product",
    "phase3b_env",
    "seed_pos_product",
    "seed_purchase_product",
]


def compras_service(env):
    return ComprasService(env.db, auth=AuthPermitido())


def seed_purchase_product(env, **kwargs):
    precio_compra = kwargs.pop("precio_compra", 500)
    pid, lid, product = seed_pos_product(env, **kwargs)
    conn = env.connect()
    try:
        conn.execute(
            "UPDATE productos SET precio_compra=? WHERE id=?",
            (precio_compra, pid),
        )
        conn.commit()
    finally:
        conn.close()
    return pid, lid, product
