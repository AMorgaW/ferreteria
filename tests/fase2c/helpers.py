from __future__ import annotations

from contextlib import contextmanager

from migration_runner import default_runner
from models import Producto
from repositories.productos_repo import PRODUCT_CREATION_STAGING, ProductosRepository
from tests.fase0.harness import official_temp_db


@contextmanager
def phase2c_env():
    with official_temp_db() as env:
        conn = env.connect()
        try:
            default_runner().run(conn, dry_run=False)
        finally:
            conn.close()
        yield env


def create_product(env, name: str):
    repo = ProductosRepository(env.db)
    ok, message, product_id = repo.crear_producto(
        Producto(nombre=name, precio_venta=1000, stock=0),
        creation_policy=PRODUCT_CREATION_STAGING,
    )
    if not ok:
        raise AssertionError(message)
    product = repo.obtener_por_id(product_id)
    return product_id, product["local_id"]

