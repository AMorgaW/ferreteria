# -*- coding: utf-8 -*-
"""Helpers 1E.4. Laboratorio ferrepro-pg-test. No SUPABASE_URI."""
from __future__ import annotations

from tests.fase1e3.helpers import (
    ALLOWED_PASSWORD,
    ALLOWED_ROLE,
    app_factory,
    force_postgres_status,
    lan_create_sale,
    mark_authoritative,
    pin_env_db,
    prepare_pg,
    reset_lab_balances,
    require_pg,
    seed_sqlite_producto,
)

__all__ = [
    "ALLOWED_PASSWORD",
    "ALLOWED_ROLE",
    "app_factory",
    "force_postgres_status",
    "lan_create_sale",
    "mark_authoritative",
    "pin_env_db",
    "prepare_pg",
    "reset_lab_balances",
    "require_pg",
    "seed_sqlite_producto",
]


def broken_factory():
    def factory():
        raise ConnectionError("postgresql unreachable")

    return factory
