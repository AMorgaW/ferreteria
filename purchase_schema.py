# -*- coding: utf-8 -*-
"""Esquema mínimo 3B: borrador de recepción y aliases de proveedor.

Los aliases NO viven en product_barcodes.
"""
from __future__ import annotations

import schema_bootstrap
from repositories.product_barcodes_repo import PACKAGE_ROLE_BASE_UNIT

SQLITE_MIGRATION_VERSION = "20260816_007"


def ensure_sqlite_purchase_receiving_schema(conn) -> None:
    """Materializa columnas/tabla 3B sin commit; el MigrationRunner es atómico."""
    if not schema_bootstrap.is_sqlite_connection(conn):
        raise schema_bootstrap.SchemaBootstrapError(
            "El esquema SQLite de compras/recepción no admite PostgreSQL"
        )
    if not schema_bootstrap.table_exists(conn, "compras"):
        raise schema_bootstrap.SchemaBootstrapError(
            "schema_bootstrap incompleto: falta compras"
        )
    schema_bootstrap.add_column_if_missing(
        conn, "compras", "inventory_command_id", "TEXT"
    )
    if schema_bootstrap.table_exists(conn, "detalle_compras"):
        schema_bootstrap.add_column_if_missing(
            conn,
            "detalle_compras",
            "package_role",
            f"TEXT DEFAULT '{PACKAGE_ROLE_BASE_UNIT}'",
        )
        schema_bootstrap.add_column_if_missing(
            conn, "detalle_compras", "cantidad_presentacion", "TEXT"
        )
        schema_bootstrap.add_column_if_missing(
            conn, "detalle_compras", "supplier_alias", "TEXT"
        )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS supplier_product_aliases (
            local_id TEXT PRIMARY KEY NOT NULL,
            proveedor_id INTEGER NOT NULL,
            producto_local_id TEXT NOT NULL,
            alias_codigo TEXT NOT NULL COLLATE BINARY,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK (length(alias_codigo) > 0),
            UNIQUE (proveedor_id, alias_codigo),
            FOREIGN KEY (proveedor_id) REFERENCES proveedores(id),
            FOREIGN KEY (producto_local_id) REFERENCES productos(local_id)
                ON UPDATE CASCADE ON DELETE RESTRICT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_supplier_alias_producto "
        "ON supplier_product_aliases(producto_local_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_supplier_alias_proveedor "
        "ON supplier_product_aliases(proveedor_id)"
    )
