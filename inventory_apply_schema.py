# -*- coding: utf-8 -*-
"""Esquema durable del coordinador local de APPLY de inventario (Fase 2E)."""
from __future__ import annotations

import schema_bootstrap


BATCH_STATES = (
    "STAGED",
    "VALIDATED",
    "REVIEW_REQUIRED",
    "READY_FOR_APPROVAL",
    "APPROVED",
    "APPLYING",
    "APPLIED",
    "COMPLETED",
    "PARTIALLY_FAILED",
    "FAILED",
    "CANCELLED",
)

ROW_APPLY_STATES = (
    "PENDING",
    "APPROVED",
    "PRODUCT_CREATING",
    "PRODUCT_CREATED",
    "METADATA_APPLYING",
    "METADATA_APPLIED",
    "INVENTORY_SUBMITTING",
    "INVENTORY_UNKNOWN",
    "INVENTORY_APPLIED",
    "VERIFYING",
    "VERIFIED",
    "NO_CHANGE_VERIFIED",
    "STALE_BALANCE",
    "FAILED_RETRYABLE",
    "FAILED_BLOCKING",
    "CANCELLED",
)


def _quoted(values) -> str:
    return ", ".join("'" + value + "'" for value in values)


def ensure_inventory_apply_schema(conn) -> None:
    """Crea sidecars 2E sin ampliar el CHECK histórico de staging 2D."""
    if not schema_bootstrap.is_sqlite_connection(conn):
        raise RuntimeError("El coordinador Fase 2E usa staging local SQLite")
    for table in ("inventory_import_batches", "inventory_import_rows"):
        if not schema_bootstrap.table_exists(conn, table):
            raise RuntimeError(f"Falta migración 2D: {table}")

    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS inventory_import_apply_batches (
            batch_id TEXT PRIMARY KEY NOT NULL,
            workflow_state TEXT NOT NULL DEFAULT 'STAGED'
                CHECK (workflow_state IN ({_quoted(BATCH_STATES)})),
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
            approval_id TEXT UNIQUE,
            approval_plan_hash TEXT,
            approval_source_hash TEXT,
            approved_plan_json TEXT,
            approved_by TEXT,
            approved_at TEXT,
            workbook_warnings_approved INTEGER NOT NULL DEFAULT 0
                CHECK (workbook_warnings_approved IN (0, 1)),
            workbook_warnings_approved_by TEXT,
            workbook_warnings_approved_at TEXT,
            approval_invalidated_at TEXT,
            apply_id TEXT UNIQUE,
            lease_token TEXT,
            lease_expires_at TEXT,
            apply_started_at TEXT,
            apply_finished_at TEXT,
            stop_requested INTEGER NOT NULL DEFAULT 0
                CHECK (stop_requested IN (0, 1)),
            last_error TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (batch_id) REFERENCES inventory_import_batches(batch_id)
                ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS inventory_import_apply_rows (
            row_id TEXT PRIMARY KEY NOT NULL,
            batch_id TEXT NOT NULL,
            identity_resolution TEXT NOT NULL DEFAULT 'PENDING'
                CHECK (identity_resolution IN (
                    'PENDING', 'NOT_REQUIRED', 'CONFIRMED', 'REJECTED'
                )),
            resolved_producto_local_id TEXT,
            resolved_product_name TEXT,
            resolved_by TEXT,
            resolved_at TEXT,
            duplicate_resolution TEXT NOT NULL DEFAULT 'PENDING'
                CHECK (duplicate_resolution IN (
                    'PENDING', 'NOT_DUPLICATE', 'CONFIRMED_MATCH', 'REJECTED'
                )),
            warning_approved INTEGER NOT NULL DEFAULT 0
                CHECK (warning_approved IN (0, 1)),
            warning_approved_by TEXT,
            warning_approved_at TEXT,
            metadata_decision TEXT NOT NULL DEFAULT 'PENDING'
                CHECK (metadata_decision IN (
                    'PENDING', 'NOT_REQUIRED', 'APPLY', 'KEEP_CURRENT'
                )),
            metadata_fields_json TEXT NOT NULL DEFAULT '[]',
            metadata_decided_by TEXT,
            metadata_decided_at TEXT,
            apply_state TEXT NOT NULL DEFAULT 'PENDING'
                CHECK (apply_state IN ({_quoted(ROW_APPLY_STATES)})),
            approved_snapshot_json TEXT,
            producto_local_id TEXT,
            producto_id INTEGER,
            inventory_command_id TEXT UNIQUE,
            inventory_operation_id TEXT UNIQUE,
            old_balance_scaled INTEGER,
            physical_count_scaled INTEGER,
            delta_scaled INTEGER,
            metadata_before_json TEXT,
            metadata_after_json TEXT,
            apply_result_json TEXT,
            last_error TEXT,
            apply_attempts INTEGER NOT NULL DEFAULT 0 CHECK (apply_attempts >= 0),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            applied_at TEXT,
            verified_at TEXT,
            FOREIGN KEY (row_id) REFERENCES inventory_import_rows(row_id)
                ON DELETE CASCADE,
            FOREIGN KEY (batch_id) REFERENCES inventory_import_batches(batch_id)
                ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_import_apply_audit (
            audit_id TEXT PRIMARY KEY NOT NULL,
            batch_id TEXT NOT NULL,
            row_id TEXT,
            apply_id TEXT,
            producto_local_id TEXT,
            inventory_command_id TEXT,
            event_type TEXT NOT NULL,
            actor TEXT,
            before_json TEXT,
            after_json TEXT,
            result_json TEXT,
            error TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (batch_id) REFERENCES inventory_import_batches(batch_id)
                ON DELETE CASCADE,
            FOREIGN KEY (row_id) REFERENCES inventory_import_rows(row_id)
                ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_inventory_apply_batch_state "
        "ON inventory_import_apply_batches(workflow_state, lease_expires_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_inventory_apply_rows_batch_state "
        "ON inventory_import_apply_rows(batch_id, apply_state)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_inventory_apply_audit_batch_row "
        "ON inventory_import_apply_audit(batch_id, row_id, created_at)"
    )

    # Cualquier edición material de staging posterior a APPROVED invalida el
    # snapshot. El trigger cubre incluso cambios SQL fuera del repository.
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_inventory_import_rows_lock_during_apply
        BEFORE UPDATE ON inventory_import_rows
        WHEN EXISTS (
            SELECT 1 FROM inventory_import_apply_batches b
             WHERE b.batch_id = OLD.batch_id
               AND b.workflow_state IN ('APPLYING','APPLIED','COMPLETED')
        )
        BEGIN
            SELECT RAISE(ABORT, 'STAGING_LOCKED_DURING_APPLY');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_inventory_import_rows_invalidate_approval
        AFTER UPDATE OF normalized_payload, raw_payload, cantidad_contada_scaled,
            match_status, matched_producto_local_id, barcode_status,
            barcode_candidate, validation_status, validation_errors,
            validation_warnings, row_hash, duplicate_candidate
        ON inventory_import_rows
        BEGIN
            UPDATE inventory_import_apply_rows
               SET apply_state='PENDING', approved_snapshot_json=NULL,
                   last_error=NULL, updated_at=CURRENT_TIMESTAMP
             WHERE batch_id=NEW.batch_id AND apply_state='APPROVED';
            UPDATE inventory_import_apply_batches
               SET revision = revision + 1,
                   workflow_state = CASE
                       WHEN workflow_state IN ('APPROVED', 'READY_FOR_APPROVAL')
                       THEN 'REVIEW_REQUIRED'
                       ELSE workflow_state
                   END,
                   approval_invalidated_at = CASE
                       WHEN approval_id IS NOT NULL THEN CURRENT_TIMESTAMP
                       ELSE approval_invalidated_at
                   END,
                   approval_id = NULL,
                   approval_plan_hash = NULL,
                   approval_source_hash = NULL,
                   approved_plan_json = NULL,
                   approved_by = NULL,
                   approved_at = NULL,
                   updated_at = CURRENT_TIMESTAMP
             WHERE batch_id = NEW.batch_id;
        END
        """
    )
