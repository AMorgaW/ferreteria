# -*- coding: utf-8 -*-
"""Esquema SQLite local y durable para staging de inventario físico."""
from __future__ import annotations

import schema_bootstrap


def ensure_inventory_import_schema(conn) -> None:
    """Materializa solo staging; el MigrationRunner controla transacción/commit."""
    if not schema_bootstrap.is_sqlite_connection(conn):
        raise RuntimeError("El staging Fase 2D es local SQLite")
    if not schema_bootstrap.table_exists(conn, "productos"):
        raise RuntimeError("schema_bootstrap incompleto: falta productos")
    if "local_id" not in schema_bootstrap.column_names(conn, "productos"):
        raise RuntimeError("schema_bootstrap incompleto: falta productos.local_id")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_import_batches (
            batch_id TEXT PRIMARY KEY NOT NULL,
            source_filename TEXT NOT NULL,
            source_sha256 TEXT NOT NULL UNIQUE,
            source_size_bytes INTEGER NOT NULL CHECK (source_size_bytes >= 0),
            sheet_name TEXT NOT NULL,
            header_row INTEGER NOT NULL CHECK (header_row >= 1),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            status TEXT NOT NULL CHECK (status IN (
                'READY', 'REVIEW_REQUIRED', 'INVALID', 'APPLIED'
            )),
            row_count INTEGER NOT NULL DEFAULT 0 CHECK (row_count >= 0),
            valid_count INTEGER NOT NULL DEFAULT 0 CHECK (valid_count >= 0),
            warning_count INTEGER NOT NULL DEFAULT 0 CHECK (warning_count >= 0),
            error_count INTEGER NOT NULL DEFAULT 0 CHECK (error_count >= 0),
            applied_at TEXT,
            workbook_warnings TEXT NOT NULL DEFAULT '[]'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_import_rows (
            row_id TEXT PRIMARY KEY NOT NULL,
            batch_id TEXT NOT NULL,
            excel_row_number INTEGER NOT NULL CHECK (excel_row_number >= 1),
            normalized_payload TEXT NOT NULL,
            raw_payload TEXT NOT NULL,
            cantidad_contada_scaled INTEGER,
            match_status TEXT NOT NULL CHECK (match_status IN (
                'MATCH_EXACT', 'MATCH_CANDIDATE', 'NEW_PRODUCT',
                'AMBIGUOUS', 'INVALID'
            )),
            matched_producto_local_id TEXT,
            matched_product_name TEXT,
            barcode_status TEXT NOT NULL CHECK (barcode_status IN (
                'BARCODE_PENDING', 'BARCODE_EXCEL_CANDIDATE',
                'BARCODE_ERROR', 'CONFLICT_BARCODE_PRODUCT'
            )),
            barcode_candidate TEXT,
            validation_status TEXT NOT NULL CHECK (validation_status IN (
                'VALID', 'WARNING', 'ERROR'
            )),
            validation_errors TEXT NOT NULL DEFAULT '[]',
            validation_warnings TEXT NOT NULL DEFAULT '[]',
            validation_info TEXT NOT NULL DEFAULT '[]',
            row_hash TEXT NOT NULL,
            duplicate_candidate INTEGER NOT NULL DEFAULT 0 CHECK (duplicate_candidate IN (0, 1)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (batch_id) REFERENCES inventory_import_batches(batch_id)
                ON DELETE CASCADE,
            UNIQUE (batch_id, excel_row_number)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_inventory_import_rows_batch_status "
        "ON inventory_import_rows(batch_id, validation_status, match_status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_inventory_import_rows_hash "
        "ON inventory_import_rows(batch_id, row_hash)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_inventory_import_rows_match "
        "ON inventory_import_rows(matched_producto_local_id)"
    )
