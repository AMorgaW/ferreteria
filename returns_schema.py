# -*- coding: utf-8 -*-
"""Esquema mínimo 3C: documentos de reverso. No edita ventas/compras COMPLETED."""
from __future__ import annotations

import schema_bootstrap

SQLITE_MIGRATION_VERSION = "20260816_008"

KIND_CUSTOMER_RETURN = "CUSTOMER_RETURN"
KIND_SALE_VOID = "SALE_VOID"
KIND_SUPPLIER_RETURN = "SUPPLIER_RETURN"
REVERSAL_KINDS = (
    KIND_CUSTOMER_RETURN,
    KIND_SALE_VOID,
    KIND_SUPPLIER_RETURN,
)

ORIGINAL_TIPO_VENTA = "venta"
ORIGINAL_TIPO_COMPRA = "compra"

ESTADO_DRAFT = "DRAFT"
ESTADO_APPLYING = "APPLYING"
ESTADO_COMPLETED = "COMPLETED"
ESTADO_REJECTED = "REJECTED"
REVERSAL_STATES = (
    ESTADO_DRAFT,
    ESTADO_APPLYING,
    ESTADO_COMPLETED,
    ESTADO_REJECTED,
)

STATUS_PARTIALLY_RETURNED = "PARTIALLY_RETURNED"
STATUS_FULLY_RETURNED = "FULLY_RETURNED"
STATUS_VOIDED = "VOIDED"

COMPLETED_IMMUTABLE = (
    "Un documento COMPLETED no se edita; use una operación inversa."
)
OVER_RETURN = "RETURNABLE_QTY_EXCEEDED"
ORIGINAL_NOT_FOUND = "ORIGINAL_DOCUMENT_NOT_FOUND"


def ensure_sqlite_returns_reversals_schema(conn) -> None:
    """Materializa tablas 3C sin commit; el MigrationRunner es atómico."""
    if not schema_bootstrap.is_sqlite_connection(conn):
        raise schema_bootstrap.SchemaBootstrapError(
            "El esquema SQLite de reversos no admite PostgreSQL"
        )
    if schema_bootstrap.table_exists(conn, "ventas"):
        schema_bootstrap.add_column_if_missing(
            conn, "ventas", "inventory_command_id", "TEXT"
        )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reversal_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            local_id TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL,
            original_tipo TEXT NOT NULL,
            original_id INTEGER NOT NULL,
            original_local_id TEXT,
            estado TEXT NOT NULL DEFAULT 'DRAFT',
            inventory_command_id TEXT,
            usuario_id INTEGER,
            motivo TEXT,
            fecha TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK (kind IN ('CUSTOMER_RETURN','SALE_VOID','SUPPLIER_RETURN')),
            CHECK (original_tipo IN ('venta','compra')),
            CHECK (estado IN ('DRAFT','APPLYING','COMPLETED','REJECTED'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reversal_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reversal_id INTEGER NOT NULL,
            original_line_id INTEGER,
            producto_id INTEGER NOT NULL,
            package_role TEXT NOT NULL DEFAULT 'BASE_UNIT',
            cantidad_presentacion TEXT NOT NULL,
            cantidad_base TEXT NOT NULL,
            precio_unitario TEXT,
            subtotal TEXT,
            FOREIGN KEY (reversal_id) REFERENCES reversal_documents(id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_reversal_original "
        "ON reversal_documents(original_tipo, original_id)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_reversal_command "
        "ON reversal_documents(inventory_command_id) "
        "WHERE inventory_command_id IS NOT NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_reversal_lines_doc "
        "ON reversal_lines(reversal_id, producto_id)"
    )
