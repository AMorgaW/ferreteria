# -*- coding: utf-8 -*-
"""Harness PostgreSQL opt-in para Fase 1D.

NUNCA usa SUPABASE_URI (puede ser producción).
NUNCA simula locking con SQLite.

Exportar un DSN desechable:

    FERREPRO_PG_TEST_DSN=postgresql://user:pass@127.0.0.1:5432/ferrepro_test
"""
from __future__ import annotations

import os
import uuid
from contextlib import contextmanager

import psycopg2


POSTGRES_SKIP_REASON = (
    "POSTGRES INTEGRATION opt-in: defina FERREPRO_PG_TEST_DSN a un PostgreSQL "
    "desechable. No se usa SUPABASE_URI. Sin DSN no hay certificación de "
    "locking/concurrencia."
)


def postgres_dsn() -> str:
    current = (os.environ.get("FERREPRO_PG_TEST_DSN") or "").strip()
    if current:
        return current
    try:
        from tests.fase1e1.pg_dsn import ensure_pg_test_dsn

        return (ensure_pg_test_dsn() or "").strip()
    except Exception:
        return ""


def postgres_available() -> bool:
    dsn = postgres_dsn()
    if not dsn:
        return False
    try:
        conn = psycopg2.connect(dsn, connect_timeout=3)
        conn.close()
        return True
    except Exception:
        return False


def connect():
    conn = psycopg2.connect(postgres_dsn(), connect_timeout=8)
    conn.autocommit = False
    return conn


def connect_as(user: str, password: str):
    """Conexión LOGIN no-owner. El DSN de laboratorio solo aporta host/puerto/db."""
    conn = psycopg2.connect(
        postgres_dsn(),
        user=user,
        password=password,
        connect_timeout=8,
    )
    conn.autocommit = False
    return conn


def backend_pid(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_backend_pid()")
        pid = int(cur.fetchone()[0])
    conn.rollback()
    return pid


def current_session_user(conn) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT session_user")
        name = str(cur.fetchone()[0])
    conn.rollback()
    return name


def provision_inventory_test_roles(admin_conn, *, allowed_password: str, denied_password: str) -> dict:
    """Crea roles de laboratorio. No SUPERUSER, no BYPASSRLS, no dueños de tablas."""
    from psycopg2 import sql as pg_sql

    allowed = "ferrepro_inventory_allowed_test"
    denied = "ferrepro_inventory_denied_test"
    app_role = "ferrepro_inventory_app"
    with admin_conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        dbname = cur.fetchone()[0]
        cur.execute("SELECT rolname FROM pg_roles WHERE rolname = %s", (app_role,))
        if cur.fetchone() is None:
            cur.execute(
                pg_sql.SQL(
                    "CREATE ROLE {} NOLOGIN NOSUPERUSER NOBYPASSRLS "
                    "NOCREATEDB NOCREATEROLE INHERIT"
                ).format(pg_sql.Identifier(app_role))
            )
        for role in (allowed, denied):
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
            if cur.fetchone():
                cur.execute(
                    pg_sql.SQL("DROP OWNED BY {}").format(pg_sql.Identifier(role))
                )
                cur.execute(
                    pg_sql.SQL("DROP ROLE IF EXISTS {}").format(pg_sql.Identifier(role))
                )
        cur.execute(
            pg_sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS "
                "NOCREATEDB NOCREATEROLE INHERIT PASSWORD %s"
            ).format(pg_sql.Identifier(allowed)),
            (allowed_password,),
        )
        cur.execute(
            pg_sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS "
                "NOCREATEDB NOCREATEROLE INHERIT PASSWORD %s"
            ).format(pg_sql.Identifier(denied)),
            (denied_password,),
        )
        cur.execute(
            pg_sql.SQL("GRANT {} TO {}").format(
                pg_sql.Identifier(app_role), pg_sql.Identifier(allowed)
            )
        )
        cur.execute(
            pg_sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                pg_sql.Identifier(dbname), pg_sql.Identifier(allowed)
            )
        )
        cur.execute(
            pg_sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                pg_sql.Identifier(dbname), pg_sql.Identifier(denied)
            )
        )
        cur.execute(
            pg_sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
                pg_sql.Identifier(allowed)
            )
        )
        cur.execute(
            pg_sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
                pg_sql.Identifier(denied)
            )
        )
    admin_conn.commit()
    apply_coordinator_schema(admin_conn)
    return {"app": app_role, "allowed": allowed, "denied": denied}


def apply_coordinator_schema(conn) -> None:
    from inventory_coordinator import postgres_coordinator_sql
    from inventory_ledger import postgres_ledger_sql
    from schema_bootstrap import (
        apply_postgres_coordinator_sql,
        apply_postgres_ledger_sql,
    )

    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS productos (
                id SERIAL PRIMARY KEY,
                local_id TEXT UNIQUE,
                nombre TEXT,
                stock INTEGER DEFAULT 0
            )
            """
        )
    apply_postgres_ledger_sql(conn, postgres_ledger_sql())
    apply_postgres_coordinator_sql(conn, postgres_coordinator_sql())
    from inventory_cutover import postgres_cutover_sql

    with conn.cursor() as cur:
        cur.execute(postgres_cutover_sql())
    conn.commit()


def insert_producto(conn, *, local_id=None, stock=0, nombre="Fase1D"):
    lid = local_id or str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO productos (local_id, nombre, stock) VALUES (%s, %s, %s)",
            (lid, nombre, stock),
        )
    conn.commit()
    return lid


@contextmanager
def postgres_env():
    conn = connect()
    try:
        apply_coordinator_schema(conn)
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass
