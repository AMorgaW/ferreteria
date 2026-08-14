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
    return (os.environ.get("FERREPRO_PG_TEST_DSN") or "").strip()


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
