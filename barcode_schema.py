# -*- coding: utf-8 -*-
"""Esquema canónico de barcodes para SQLite y PostgreSQL de laboratorio."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import schema_bootstrap


SQLITE_MIGRATION_VERSION = "20260815_003"
SQLITE_PACKAGE_ROLE_MIGRATION_VERSION = "20260815_006"
POSTGRES_MIGRATION_VERSION = "20260815_003_product_barcodes"
POSTGRES_PACKAGE_ROLE_MIGRATION_VERSION = "20260815_006_product_barcodes_package_role"
POSTGRES_SQL_PATH = Path(__file__).with_name("postgres_product_barcodes.sql")

PACKAGE_ROLE_COLUMN_DEF = (
    "TEXT NOT NULL DEFAULT 'BASE_UNIT' "
    "CHECK (package_role IN ('BASE_UNIT','FULL_PACKAGE','CUSTOM_PRESENTATION'))"
)

POSTGRES_PACKAGE_ROLE_SQL = (
    "ALTER TABLE product_barcodes "
    "ADD COLUMN IF NOT EXISTS package_role TEXT NOT NULL DEFAULT 'BASE_UNIT';\n"
    "ALTER TABLE product_barcodes DROP CONSTRAINT IF EXISTS "
    "product_barcodes_package_role_check;\n"
    "ALTER TABLE product_barcodes ADD CONSTRAINT "
    "product_barcodes_package_role_check "
    "CHECK (package_role IN ('BASE_UNIT','FULL_PACKAGE','CUSTOM_PRESENTATION'));"
)


def ensure_sqlite_barcode_schema(conn) -> None:
    """Materializa el modelo sin commit; el MigrationRunner controla atomicidad."""
    if not schema_bootstrap.is_sqlite_connection(conn):
        raise schema_bootstrap.SchemaBootstrapError(
            "El esquema SQLite de barcodes no admite PostgreSQL"
        )
    if not schema_bootstrap.table_exists(conn, "productos"):
        raise schema_bootstrap.SchemaBootstrapError(
            "schema_bootstrap incompleto: falta productos"
        )
    if "local_id" not in schema_bootstrap.column_names(conn, "productos"):
        raise schema_bootstrap.SchemaBootstrapError(
            "schema_bootstrap incompleto: falta productos.local_id"
        )

    schema_bootstrap.add_column_if_missing(
        conn,
        "productos",
        "barcode_status",
        "TEXT NOT NULL DEFAULT 'BARCODE_MISSING_LEGACY'",
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS product_barcodes (
            local_id TEXT PRIMARY KEY NOT NULL,
            producto_local_id TEXT NOT NULL,
            barcode TEXT NOT NULL UNIQUE COLLATE BINARY,
            barcode_type TEXT NOT NULL DEFAULT 'MANUFACTURER',
            source TEXT NOT NULL DEFAULT 'HID_DOUBLE_SCAN',
            is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0, 1)),
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            remote_id TEXT,
            deleted_at TEXT,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            sync_status TEXT NOT NULL DEFAULT 'pending',
            last_synced_at TEXT,
            version INTEGER NOT NULL DEFAULT 1,
            device_id TEXT,
            created_by INTEGER,
            updated_by INTEGER,
            CHECK (length(barcode) > 0),
            FOREIGN KEY (producto_local_id)
                REFERENCES productos(local_id)
                ON UPDATE CASCADE ON DELETE RESTRICT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_product_barcodes_product "
        "ON product_barcodes(producto_local_id, active)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_product_barcodes_primary_active "
        "ON product_barcodes(producto_local_id) "
        "WHERE active = 1 AND is_primary = 1"
    )


def ensure_sqlite_barcode_package_role(conn) -> None:
    """Añade ``product_barcodes.package_role`` (Fase 2F). Sin commit.

    Idempotente: conserva intactos los barcodes existentes de Fase 2C; todas
    las filas previas quedan con el default BASE_UNIT. No genera FRP ni toca
    stock; medio empaque es una modalidad lógica y nunca obtiene barcode aquí.
    """
    if not schema_bootstrap.is_sqlite_connection(conn):
        raise schema_bootstrap.SchemaBootstrapError(
            "El esquema SQLite de barcodes no admite PostgreSQL"
        )
    if not schema_bootstrap.table_exists(conn, "product_barcodes"):
        raise schema_bootstrap.SchemaBootstrapError(
            "Falta la migración 20260815_003 product_barcodes"
        )
    schema_bootstrap.add_column_if_missing(
        conn, "product_barcodes", "package_role", PACKAGE_ROLE_COLUMN_DEF
    )


def postgres_barcode_sql() -> str:
    return POSTGRES_SQL_PATH.read_text(encoding="utf-8")


def _apply_postgres_versioned(conn, version: str, sql: str) -> PostgresMigrationStatus:
    """Núcleo común: transacción, checksum y rerun sobre el laboratorio PG."""
    checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS ferrepro_schema_migrations (
                    version TEXT PRIMARY KEY,
                    checksum TEXT NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                "SELECT checksum FROM ferrepro_schema_migrations WHERE version = %s",
                (version,),
            )
            row = cur.fetchone()
            if row:
                if str(row[0]) != checksum:
                    raise schema_bootstrap.SchemaBootstrapError(
                        "migración PostgreSQL aplicada cambió de checksum"
                    )
                conn.commit()
                return PostgresMigrationStatus(version, "SKIPPED_APPLIED", checksum)
            cur.execute(sql)
            cur.execute(
                "INSERT INTO ferrepro_schema_migrations(version, checksum) "
                "VALUES (%s, %s)",
                (version, checksum),
            )
        conn.commit()
        return PostgresMigrationStatus(version, "APPLIED", checksum)
    except Exception:
        conn.rollback()
        raise


def apply_postgres_barcode_package_role_migration(conn) -> PostgresMigrationStatus:
    """Fase 2F: package_role en el laboratorio PG. Nunca en Supabase real."""
    if schema_bootstrap.is_sqlite_connection(conn):
        raise schema_bootstrap.SchemaBootstrapError(
            "La migración PostgreSQL de barcodes no admite SQLite"
        )
    return _apply_postgres_versioned(
        conn, POSTGRES_PACKAGE_ROLE_MIGRATION_VERSION, POSTGRES_PACKAGE_ROLE_SQL
    )


@dataclass(frozen=True)
class PostgresMigrationStatus:
    version: str
    status: str
    checksum: str


def apply_postgres_barcode_migration(conn) -> PostgresMigrationStatus:
    """Aplica solo al laboratorio PG, con transacción, rerun y checksum."""
    if schema_bootstrap.is_sqlite_connection(conn):
        raise schema_bootstrap.SchemaBootstrapError(
            "La migración PostgreSQL de barcodes no admite SQLite"
        )
    return _apply_postgres_versioned(
        conn, POSTGRES_MIGRATION_VERSION, postgres_barcode_sql()
    )

