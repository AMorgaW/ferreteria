# -*- coding: utf-8 -*-
"""Runner mínimo de migraciones SQLite versionadas.

No se ejecuta al importar. El arranque productivo llama
``schema_lifecycle.ensure_sqlite_schema_current``, que invoca ``run``
explícitamente con ``dry_run=False``. El caller de ``run`` entrega una
conexión explícita. Cada migración es atómica y se registra solo después
de completar su savepoint. ``dry_run=True`` sigue siendo el default de
``run`` para que las herramientas de diagnóstico no muten.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Callable, Iterable, Optional, Tuple

import schema_bootstrap
from barcode_schema import (
    ensure_sqlite_barcode_package_role,
    ensure_sqlite_barcode_schema,
)
from inventory_import_schema import ensure_inventory_import_schema
from inventory_apply_schema import ensure_inventory_apply_schema
from purchase_schema import ensure_sqlite_purchase_receiving_schema
from cash_schema import ensure_sqlite_cash_operational_schema
from returns_schema import ensure_sqlite_returns_reversals_schema
from balance_schema import ensure_sqlite_operational_balance_schema


class MigrationError(RuntimeError):
    """Error visible: nunca se traga una migración parcial o incompatible."""


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    signature: str
    apply: Callable[[object], None]

    @property
    def checksum(self) -> str:
        material = f"{self.version}\n{self.name}\n{self.signature}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MigrationStatus:
    version: str
    name: str
    status: str
    checksum: str


def _migration_table_exists(conn) -> bool:
    return schema_bootstrap.table_exists(conn, "schema_migrations")


def _require_sqlite(conn) -> None:
    if not schema_bootstrap.is_sqlite_connection(conn):
        raise MigrationError(
            "el runner de Fase 2A solo admite SQLite; "
            "las migraciones PostgreSQL requieren un catálogo separado"
        )


def _ensure_migration_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            checksum TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()


class MigrationRunner:
    def __init__(self, migrations: Iterable[Migration]):
        ordered = tuple(sorted(migrations, key=lambda item: item.version))
        versions = [item.version for item in ordered]
        if len(versions) != len(set(versions)):
            raise MigrationError("versiones de migración duplicadas")
        self.migrations: Tuple[Migration, ...] = ordered

    def _applied(self, conn) -> dict:
        if not _migration_table_exists(conn):
            return {}
        return {
            str(row[0]): (str(row[1]), str(row[2]))
            for row in conn.execute(
                "SELECT version, name, checksum FROM schema_migrations"
            ).fetchall()
        }

    def plan(self, conn) -> Tuple[MigrationStatus, ...]:
        _require_sqlite(conn)
        applied = self._applied(conn)
        result = []
        for migration in self.migrations:
            previous = applied.get(migration.version)
            if previous is None:
                status = "PENDING"
            elif previous != (migration.name, migration.checksum):
                status = "CHECKSUM_MISMATCH"
            else:
                status = "APPLIED"
            result.append(
                MigrationStatus(
                    migration.version,
                    migration.name,
                    status,
                    migration.checksum,
                )
            )
        return tuple(result)

    def run(self, conn, *, dry_run: bool = True) -> Tuple[MigrationStatus, ...]:
        before = self.plan(conn)
        mismatches = [item for item in before if item.status == "CHECKSUM_MISMATCH"]
        if mismatches:
            raise MigrationError(
                "migración aplicada cambió de checksum: "
                + ", ".join(item.version for item in mismatches)
            )
        if dry_run:
            return before

        _ensure_migration_table(conn)
        applied = self._applied(conn)
        result = []
        for migration in self.migrations:
            if migration.version in applied:
                result.append(
                    MigrationStatus(
                        migration.version,
                        migration.name,
                        "SKIPPED_APPLIED",
                        migration.checksum,
                    )
                )
                continue
            savepoint = "ferrepro_migration"
            conn.execute(f"SAVEPOINT {savepoint}")
            try:
                migration.apply(conn)
                conn.execute(
                    "INSERT INTO schema_migrations "
                    "(version, name, checksum) VALUES (?, ?, ?)",
                    (migration.version, migration.name, migration.checksum),
                )
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                conn.commit()
            except Exception as exc:
                try:
                    conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                finally:
                    conn.rollback()
                raise MigrationError(
                    f"migración {migration.version}/{migration.name} falló: {exc}"
                ) from exc
            result.append(
                MigrationStatus(
                    migration.version,
                    migration.name,
                    "APPLIED",
                    migration.checksum,
                )
            )
        return tuple(result)


def _add_purchase_normalization_columns(conn) -> None:
    if not schema_bootstrap.table_exists(conn, "compras"):
        raise MigrationError(
            "tabla compras ausente; ejecutar schema_bootstrap antes del runner"
        )
    schema_bootstrap.add_column_if_missing(
        conn, "compras", "documento_tipo_normalizado", "TEXT"
    )
    schema_bootstrap.add_column_if_missing(
        conn, "compras", "numero_factura_normalizada", "TEXT"
    )


def _add_purchase_detection_index(conn) -> None:
    if not schema_bootstrap.table_exists(conn, "compras"):
        raise MigrationError(
            "tabla compras ausente; ejecutar schema_bootstrap antes del runner"
        )
    required = {
        "proveedor_id",
        "documento_tipo_normalizado",
        "numero_factura_normalizada",
    }
    missing = required - schema_bootstrap.column_names(conn, "compras")
    if missing:
        raise MigrationError(
            "schema previo de compras incompleto: " + ", ".join(sorted(missing))
        )
    schema_bootstrap.create_index_if_missing(
        conn,
        "CREATE INDEX IF NOT EXISTS idx_compras_proveedor_factura_norm "
        "ON compras(proveedor_id, documento_tipo_normalizado, numero_factura_normalizada)",
    )


DEFAULT_MIGRATIONS = (
    Migration(
        version="20260815_001",
        name="purchase_normalization_columns",
        signature=(
            "compras.documento_tipo_normalizado TEXT nullable;"
            "compras.numero_factura_normalizada TEXT nullable;no backfill"
        ),
        apply=_add_purchase_normalization_columns,
    ),
    Migration(
        version="20260815_002",
        name="purchase_duplicate_detection_index",
        signature=(
            "non-unique index compras(proveedor_id,documento_tipo_normalizado,"
            "numero_factura_normalizada)"
        ),
        apply=_add_purchase_detection_index,
    ),
    Migration(
        version="20260815_003",
        name="product_barcodes_model",
        signature=(
            "productos.barcode_status;product_barcodes(local_id PK,"
            "producto_local_id->productos.local_id,barcode UNIQUE binary,"
            "barcode_type,source,is_primary,active,timestamps,sync metadata);"
            "one active primary per product;no backfill;no FRP generation"
        ),
        apply=ensure_sqlite_barcode_schema,
    ),
    Migration(
        version="20260815_004",
        name="inventory_import_staging",
        signature=(
            "inventory_import_batches(source_sha256 UNIQUE,status,counters);"
            "inventory_import_rows(batch_id FK,excel_row_number,payload snapshots,"
            "cantidad_contada_scaled,match,barcode,validation,row_hash);"
            "local durable staging only;no product/stock/barcode mutation"
        ),
        apply=ensure_inventory_import_schema,
    ),
    Migration(
        version="20260815_005",
        name="controlled_inventory_apply",
        signature=(
            "inventory_import_apply_batches(workflow,revision,immutable approval,"
            "apply identity,lease);inventory_import_apply_rows(resolutions,warning and "
            "metadata decisions,durable command ids,row saga,before-after,verification);"
            "inventory_import_apply_audit;staging mutation invalidates approval;"
            "staging locked while applying/completed;"
            "local coordinator only;no stock/product/barcode mutation"
        ),
        apply=ensure_inventory_apply_schema,
    ),
    Migration(
        version="20260815_006",
        name="barcode_package_role",
        signature=(
            "product_barcodes.package_role TEXT NOT NULL DEFAULT 'BASE_UNIT' "
            "CHECK (BASE_UNIT,FULL_PACKAGE,CUSTOM_PRESENTATION);"
            "existing 2C barcodes preserved;no backfill beyond column default;"
            "no stock derivation;no half-package barcode;no FRP generation"
        ),
        apply=ensure_sqlite_barcode_package_role,
    ),
    Migration(
        version="20260816_007",
        name="purchase_receiving_draft_and_supplier_aliases",
        signature=(
            "compras.inventory_command_id;detalle_compras.package_role,"
            "cantidad_presentacion,supplier_alias;"
            "supplier_product_aliases(local_id PK,proveedor_id,producto_local_id,"
            "alias_codigo UNIQUE per supplier);not product_barcodes"
        ),
        apply=ensure_sqlite_purchase_receiving_schema,
    ),
    Migration(
        version="20260816_008",
        name="returns_reversals_documents",
        signature=(
            "reversal_documents(local_id UNIQUE,kind CUSTOMER_RETURN/SALE_VOID/"
            "SUPPLIER_RETURN,original_tipo/id,estado DRAFT/APPLYING/COMPLETED/"
            "REJECTED,inventory_command_id);reversal_lines(original_line_id,"
            "package_role,cantidad_presentacion,cantidad_base);"
            "never mutates completed ventas/compras"
        ),
        apply=ensure_sqlite_returns_reversals_schema,
    ),
    Migration(
        version="20260816_009",
        name="cash_session_ledger",
        signature=(
            "cierres_caja.local_id,station_id,estado,usuario_cierre_id;"
            "unique one OPEN session per station_id;"
            "cash_movements(local_id UNIQUE,cash_session_id nullable pending OPEN,station_id,kind,"
            "cash_effect_kind,direction,amount TEXT,payment_method,"
            "source_kind+source_identity+cash_effect_kind UNIQUE);"
            "local-first operational cash ledger;no double-entry"
        ),
        apply=ensure_sqlite_cash_operational_schema,
    ),
    Migration(
        version="20260816_010",
        name="operational_balance_payment_identity",
        signature=(
            "abonos_ventas.local_id UNIQUE;abonos_compras.local_id UNIQUE;"
            "payments identified by UUID not ROWID;no REAL rewrite;"
            "legacy payment baseline captured only for documents without abonos;"
            "legacy monto_pagado/saldo_pendiente remain projection after cutover"
        ),
        apply=ensure_sqlite_operational_balance_schema,
    ),
)


def default_runner() -> MigrationRunner:
    return MigrationRunner(DEFAULT_MIGRATIONS)
