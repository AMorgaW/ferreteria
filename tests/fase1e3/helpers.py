# -*- coding: utf-8 -*-
"""Helpers 1E.3. Laboratorio ferrepro-pg-test. No SUPABASE_URI."""
from __future__ import annotations

import json
import uuid

from tests.fase1d.pg_harness import (
    apply_coordinator_schema,
    connect,
    connect_as,
    insert_producto,
    postgres_available,
    provision_inventory_test_roles,
)
from tests.fase1e.helpers import DEVICE, insert_usuario, seed_producto, stock_of
from tests.fase1e1.pg_dsn import ensure_pg_test_dsn
from tests.fase1e2.helpers import transport_applied, ventas_service


ALLOWED_ROLE = "ferrepro_inventory_allowed_test"
ALLOWED_PASSWORD = "fase1e3-allowed"


def require_pg():
    ensure_pg_test_dsn()
    if not postgres_available():
        raise AssertionError(
            "PostgreSQL ferrepro-pg-test no disponible; no certifica 1E.3"
        )


def prepare_pg():
    require_pg()
    admin = connect()
    try:
        apply_coordinator_schema(admin)
        provision_inventory_test_roles(
            admin,
            allowed_password=ALLOWED_PASSWORD,
            denied_password="fase1e3-denied",
        )
        reset_lab_balances(admin)
    finally:
        admin.close()


def reset_lab_balances(admin_conn):
    try:
        admin_conn.rollback()
    except Exception:
        pass
    with admin_conn.cursor() as cur:
        cur.execute(
            "UPDATE inventory_cutover_control SET status = 'PRE_CUTOVER', "
            "epoch = 0, seed_at = NULL, activated_at = NULL, "
            "reconciliation = NULL, device_id = NULL, "
            "cutover_id = NULL, snapshot = NULL, snapshot_checksum = NULL "
            "WHERE id = 1"
        )
    admin_conn.commit()
    with admin_conn.cursor() as cur:
        cur.execute("DELETE FROM inventory_operations")
        cur.execute("DELETE FROM inventory_commands")
        cur.execute("DELETE FROM inventory_balance_init_state WHERE init_key = 'legacy_cutover'")
        cur.execute("DELETE FROM inventory_balance_init")
        cur.execute("DELETE FROM inventory_balances")
        cur.execute("DELETE FROM productos")
    admin_conn.commit()


def app_factory():
    def factory():
        return connect_as(ALLOWED_ROLE, ALLOWED_PASSWORD)
    return factory


def mark_authoritative(sqlite_conn, *, epoch=1, admin_conn=None):
    from inventory_cutover import (
        activate_authority,
        freeze_inventory_writes,
    )

    freeze_inventory_writes(sqlite_conn, admin_conn=admin_conn, device_id=DEVICE)
    return activate_authority(sqlite_conn, admin_conn=admin_conn, device_id=DEVICE)


def force_postgres_status(admin_conn, status, *, epoch=None, device_id=DEVICE):
    from inventory_cutover import _write_postgres_state

    kwargs = {"status": status, "device_id": device_id}
    if epoch is not None:
        kwargs["epoch"] = epoch
    _write_postgres_state(admin_conn, **kwargs)


def freeze_only(sqlite_conn):
    from inventory_cutover import freeze_inventory_writes

    return freeze_inventory_writes(sqlite_conn, device_id=DEVICE)


def seed_sqlite_producto(env, conn, *, stock, producto_id=1, local_id=None, codigo=None):
    return seed_producto(
        conn,
        env,
        stock=stock,
        producto_id=producto_id,
        local_id=local_id,
        codigo=codigo or f"1E3-{producto_id:03d}-{uuid.uuid4().hex[:6]}",
    )


def insert_pg_product(admin, local_id, stock, nombre="1E3"):
    return insert_producto(admin, local_id=local_id, stock=stock, nombre=nombre)


def pin_env_db(env):
    """Apunta pg_compat al SQLite de este env (dos cajas anidadas)."""
    import local_first_db
    import pg_compat

    pg_compat.DB_MODE = "local"
    pg_compat.LOCAL_DB_PATH = str(env.db_path)
    local_first_db.DEFAULT_DB_PATH = str(env.db_path)


def lan_create_sale(env, items, **kwargs):
    from local_server import LocalFerreteriaAPI
    from tests.fase1e.helpers import FakeHTTPHandler

    body = json.dumps({"items": items, "metodo_pago": "EFECTIVO"}).encode("utf-8")
    extra_id = kwargs.pop("body_command_id", None)
    if extra_id:
        payload = json.loads(body)
        payload["inventory_command_id"] = extra_id
        body = json.dumps(payload).encode("utf-8")
        handler = FakeHTTPHandler(env.db_path, body)
    else:
        handler = FakeHTTPHandler(env.db_path, body)
    LocalFerreteriaAPI.create_sale(handler, {"usuario_id": 1}, **kwargs)
    return handler
