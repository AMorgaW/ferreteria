# -*- coding: utf-8 -*-
"""Helpers Fase 3A. SQLite temporal + fixtures. Nunca ferreteria.db comercial."""
from __future__ import annotations

from pathlib import Path

from repositories.product_barcodes_repo import (
    PACKAGE_ROLE_BASE_UNIT,
    ProductBarcodesRepository,
)
from repositories.productos_repo import ProductosRepository
from tests.fase0.harness import REPO_FERRETERIA_DB
from tests.fase1e.helpers import insert_usuario
from tests.fase2c.helpers import create_product, phase2c_env

__all__ = [
    "PACKAGE_ROLE_BASE_UNIT",
    "assert_not_commercial_db",
    "create_product",
    "phase3a_env",
    "seed_pos_product",
]


phase3a_env = phase2c_env


def assert_not_commercial_db(env) -> None:
    resolved = Path(env.db_path).resolve()
    if resolved == REPO_FERRETERIA_DB.resolve():
        raise AssertionError("El test apuntó a ferreteria.db comercial")


def seed_pos_product(
    env,
    *,
    name: str = "Tornillo POS",
    stock=10,
    barcode: str = "7700000000001",
    package_role: str = PACKAGE_ROLE_BASE_UNIT,
    precio_venta=1000,
    permite_decimales: int = 0,
    unidades_por_caja=None,
    viene_en_caja: int = 0,
    vende_por_empaque: int = 0,
    unidades_venta_custom=None,
    extra_barcodes=(),
):
    pid, lid = create_product(env, name)
    conn = env.connect()
    try:
        if conn.execute("SELECT 1 FROM usuarios WHERE id = 1").fetchone() is None:
            insert_usuario(conn)
        conn.execute(
            "UPDATE productos SET stock=?, precio_venta=?, permite_decimales=? WHERE id=?",
            (stock, precio_venta, permite_decimales, pid),
        )
        if unidades_por_caja is not None:
            conn.execute(
                "UPDATE productos SET unidades_por_caja=?, viene_en_caja=?, "
                "vende_por_empaque=? WHERE id=?",
                (unidades_por_caja, viene_en_caja, vende_por_empaque, pid),
            )
        if unidades_venta_custom is not None:
            conn.execute(
                "UPDATE productos SET unidades_venta_custom=? WHERE id=?",
                (unidades_venta_custom, pid),
            )
        conn.commit()
    finally:
        conn.close()
    repo = ProductBarcodesRepository(env.db)
    repo.assign_barcode(
        producto_local_id=lid,
        barcode=barcode,
        is_primary=True,
        package_role=package_role,
    )
    for extra in extra_barcodes:
        extra_code, extra_role = extra if isinstance(extra, tuple) else (extra, PACKAGE_ROLE_BASE_UNIT)
        repo.assign_barcode(
            producto_local_id=lid,
            barcode=extra_code,
            is_primary=False,
            package_role=extra_role,
        )
    product = ProductosRepository(env.db).obtener_por_id(pid)
    return pid, lid, product
