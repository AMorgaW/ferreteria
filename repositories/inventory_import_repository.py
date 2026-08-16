# -*- coding: utf-8 -*-
"""Persistencia local de staging para importación de inventario físico."""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, Iterator, Mapping, Optional

import schema_bootstrap
from inventory_excel_importer import ParsedInventoryWorkbook, decimal_to_scaled


class InventoryImportRepositoryError(RuntimeError):
    pass


class InventoryImportSchemaMissing(InventoryImportRepositoryError):
    pass


class InventoryAuthorityUnavailable(InventoryImportRepositoryError):
    pass


@dataclass(frozen=True)
class StagedBatch:
    batch_id: str
    source_filename: str
    source_sha256: str
    status: str
    row_count: int
    valid_count: int
    warning_count: int
    error_count: int
    reused: bool = False


def _json_default(value: Any):
    if isinstance(value, Decimal):
        text = format(value, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text
    raise TypeError(f"No serializable: {type(value)!r}")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default)


class InventoryImportRepository:
    """Persistencia durable de staging, revisión y saga local de APPLY."""

    def __init__(self, db_or_connection) -> None:
        self.source = db_or_connection

    @contextmanager
    def connection(self) -> Iterator[object]:
        if hasattr(self.source, "conectar"):
            conn = self.source.conectar()
            owned = True
        elif callable(self.source) and not hasattr(self.source, "execute"):
            conn = self.source()
            owned = True
        else:
            conn = self.source
            owned = False
        try:
            yield conn
        finally:
            if owned:
                conn.close()

    @staticmethod
    def _dict(row) -> Optional[dict]:
        if row is None:
            return None
        if isinstance(row, dict):
            return dict(row)
        if hasattr(row, "keys"):
            return {key: row[key] for key in row.keys()}
        return None

    @staticmethod
    def _require_schema(conn) -> None:
        if not schema_bootstrap.table_exists(conn, "inventory_import_batches") or not schema_bootstrap.table_exists(conn, "inventory_import_rows"):
            raise InventoryImportSchemaMissing(
                "Falta migración 20260815_004 inventory_import_staging"
            )

    def find_batch_by_sha(self, source_sha256: str) -> Optional[StagedBatch]:
        with self.connection() as conn:
            self._require_schema(conn)
            row = conn.execute(
                "SELECT * FROM inventory_import_batches WHERE source_sha256 = ?",
                (source_sha256,),
            ).fetchone()
            return self._batch(row, reused=True) if row else None

    @classmethod
    def _batch(cls, row, *, reused: bool = False) -> StagedBatch:
        data = cls._dict(row) or {}
        return StagedBatch(
            batch_id=str(data["batch_id"]),
            source_filename=str(data["source_filename"]),
            source_sha256=str(data["source_sha256"]),
            status=str(data["status"]),
            row_count=int(data["row_count"]),
            valid_count=int(data["valid_count"]),
            warning_count=int(data["warning_count"]),
            error_count=int(data["error_count"]),
            reused=reused,
        )

    def persist(self, parsed: ParsedInventoryWorkbook, matched_rows: Iterable[Mapping[str, Any]]) -> StagedBatch:
        prepared = list(matched_rows)
        with self.connection() as conn:
            self._require_schema(conn)
            existing = conn.execute(
                "SELECT * FROM inventory_import_batches WHERE source_sha256 = ?",
                (parsed.source_sha256,),
            ).fetchone()
            if existing:
                return self._batch(existing, reused=True)
            batch_id = str(uuid.uuid4())
            valid = sum(1 for item in prepared if item["row"].validation_status == "VALID")
            warning = sum(1 for item in prepared if item["row"].validation_status == "WARNING")
            errors = sum(1 for item in prepared if item["row"].validation_status == "ERROR")
            status = "INVALID" if errors else "REVIEW_REQUIRED" if warning else "READY"
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    INSERT INTO inventory_import_batches (
                        batch_id, source_filename, source_sha256, source_size_bytes,
                        sheet_name, header_row, status, row_count, valid_count,
                        warning_count, error_count, workbook_warnings
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        batch_id, parsed.source_filename, parsed.source_sha256,
                        parsed.source_path.stat().st_size, parsed.sheet_name,
                        parsed.header_row, status, len(prepared), valid, warning,
                        errors, _json([issue.as_dict() for issue in parsed.workbook_warnings]),
                    ),
                )
                for item in prepared:
                    row = item["row"]
                    conn.execute(
                        """
                        INSERT INTO inventory_import_rows (
                            row_id, batch_id, excel_row_number, normalized_payload,
                            raw_payload, cantidad_contada_scaled, match_status,
                            matched_producto_local_id, matched_product_name,
                            barcode_status, barcode_candidate, validation_status,
                            validation_errors, validation_warnings, validation_info,
                            row_hash, duplicate_candidate
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid.uuid4()), batch_id, row.excel_row_number,
                            _json(row.values), _json(row.raw_payload),
                            row.quantity_counted_scaled, item["match_status"],
                            item.get("matched_producto_local_id"),
                            item.get("matched_product_name"), item["barcode_status"],
                            row.barcode_candidate, row.validation_status,
                            _json([issue.as_dict() for issue in row.errors]),
                            _json([issue.as_dict() for issue in row.warnings]),
                            _json([issue.as_dict() for issue in row.infos]),
                            row.row_hash, 1 if row.duplicate_candidate else 0,
                        ),
                    )
                conn.commit()
            except sqlite3.IntegrityError:
                conn.rollback()
                existing = conn.execute(
                    "SELECT * FROM inventory_import_batches WHERE source_sha256 = ?",
                    (parsed.source_sha256,),
                ).fetchone()
                if existing:
                    return self._batch(existing, reused=True)
                raise
            except Exception:
                conn.rollback()
                raise
            return StagedBatch(
                batch_id, parsed.source_filename, parsed.source_sha256, status,
                len(prepared), valid, warning, errors, False,
            )

    def list_rows(self, batch_id: str) -> list[dict]:
        with self.connection() as conn:
            self._require_schema(conn)
            rows = conn.execute(
                "SELECT * FROM inventory_import_rows WHERE batch_id = ? ORDER BY excel_row_number",
                (batch_id,),
            ).fetchall()
            result = []
            for row in rows:
                item = self._dict(row) or {}
                for key in ("normalized_payload", "raw_payload", "validation_errors", "validation_warnings", "validation_info"):
                    item[key] = json.loads(item[key] or "[]")
                result.append(item)
            return result

    def get_batch(self, batch_id: str) -> dict:
        with self.connection() as conn:
            self._require_schema(conn)
            row = conn.execute(
                "SELECT * FROM inventory_import_batches WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()
            if row is None:
                raise InventoryImportRepositoryError("Batch inexistente")
            data = self._dict(row) or {}
            data["workbook_warnings"] = json.loads(data.get("workbook_warnings") or "[]")
            return data

    @staticmethod
    def _require_apply_schema(conn) -> None:
        for table in (
            "inventory_import_apply_batches",
            "inventory_import_apply_rows",
            "inventory_import_apply_audit",
        ):
            if not schema_bootstrap.table_exists(conn, table):
                raise InventoryImportSchemaMissing(
                    "Falta migración 20260815_005 controlled_inventory_apply"
                )

    def ensure_apply_controls(self, batch_id: str) -> dict:
        """Inicializa sidecars sin aprobar ni mutar negocio."""
        with self.connection() as conn:
            self._require_schema(conn)
            self._require_apply_schema(conn)
            batch = conn.execute(
                "SELECT * FROM inventory_import_batches WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()
            if batch is None:
                raise InventoryImportRepositoryError("Batch inexistente")
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    INSERT OR IGNORE INTO inventory_import_apply_batches (
                        batch_id, workflow_state
                    ) VALUES (?, ?)
                    """,
                    (
                        batch_id,
                        "REVIEW_REQUIRED" if batch["status"] != "READY"
                        else "VALIDATED",
                    ),
                )
                rows = conn.execute(
                    """
                    SELECT row_id, match_status, duplicate_candidate
                      FROM inventory_import_rows WHERE batch_id = ?
                    """,
                    (batch_id,),
                ).fetchall()
                for row in rows:
                    identity = (
                        "NOT_REQUIRED"
                        if row["match_status"] in ("MATCH_EXACT", "NEW_PRODUCT", "INVALID")
                        else "PENDING"
                    )
                    duplicate = "PENDING" if int(row["duplicate_candidate"] or 0) else "NOT_DUPLICATE"
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO inventory_import_apply_rows (
                            row_id, batch_id, identity_resolution,
                            duplicate_resolution
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (row["row_id"], batch_id, identity, duplicate),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            return self.get_apply_batch(batch_id)

    def get_apply_batch(self, batch_id: str) -> dict:
        with self.connection() as conn:
            self._require_apply_schema(conn)
            row = conn.execute(
                "SELECT * FROM inventory_import_apply_batches WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()
            if row is None:
                raise InventoryImportRepositoryError("Batch 2E no inicializado")
            data = self._dict(row) or {}
            if data.get("approved_plan_json"):
                data["approved_plan"] = json.loads(data["approved_plan_json"])
            else:
                data["approved_plan"] = None
            return data

    def list_apply_rows(self, batch_id: str) -> list[dict]:
        with self.connection() as conn:
            self._require_apply_schema(conn)
            rows = conn.execute(
                """
                SELECT r.*, c.identity_resolution, c.resolved_producto_local_id,
                       c.resolved_product_name, c.duplicate_resolution,
                       c.warning_approved, c.metadata_decision,
                       c.metadata_fields_json, c.apply_state,
                       c.approved_snapshot_json, c.producto_local_id,
                       c.producto_id, c.inventory_command_id,
                       c.inventory_operation_id, c.old_balance_scaled,
                       c.physical_count_scaled, c.delta_scaled,
                       c.metadata_before_json, c.metadata_after_json,
                       c.apply_result_json, c.last_error, c.apply_attempts,
                       c.applied_at, c.verified_at
                  FROM inventory_import_rows r
                  JOIN inventory_import_apply_rows c ON c.row_id = r.row_id
                 WHERE r.batch_id = ?
                 ORDER BY r.excel_row_number
                """,
                (batch_id,),
            ).fetchall()
            result = []
            for row in rows:
                item = self._dict(row) or {}
                for key, default in (
                    ("normalized_payload", {}), ("raw_payload", {}),
                    ("validation_errors", []), ("validation_warnings", []),
                    ("validation_info", []), ("metadata_fields_json", []),
                    ("approved_snapshot_json", None),
                    ("metadata_before_json", None), ("metadata_after_json", None),
                    ("apply_result_json", None),
                ):
                    raw = item.get(key)
                    item[key[:-5] if key.endswith("_json") else key] = (
                        json.loads(raw) if raw else default
                    )
                result.append(item)
            return result

    def _invalidate_approval_in_connection(self, conn, batch_id: str) -> None:
        conn.execute(
            """
            UPDATE inventory_import_apply_batches
               SET revision = revision + 1,
                   workflow_state = 'REVIEW_REQUIRED',
                   approval_invalidated_at = CASE WHEN approval_id IS NOT NULL
                       THEN CURRENT_TIMESTAMP ELSE approval_invalidated_at END,
                   approval_id = NULL, approval_plan_hash = NULL,
                   approval_source_hash = NULL, approved_plan_json = NULL,
                   approved_by = NULL, approved_at = NULL,
                   updated_at = CURRENT_TIMESTAMP
             WHERE batch_id = ? AND workflow_state NOT IN ('APPLYING', 'APPLIED')
            """,
            (batch_id,),
        )
        conn.execute(
            """
            UPDATE inventory_import_apply_rows
               SET apply_state='PENDING', approved_snapshot_json=NULL,
                   last_error=NULL, updated_at=CURRENT_TIMESTAMP
             WHERE batch_id=? AND apply_state IN ('APPROVED','STALE_BALANCE')
            """,
            (batch_id,),
        )

    def confirm_match(self, row_id: str, producto_local_id: str, *, actor: Optional[str] = None) -> None:
        with self.connection() as conn:
            self._require_apply_schema(conn)
            product = conn.execute(
                "SELECT local_id, nombre FROM productos WHERE local_id = ? AND activo = 1",
                (producto_local_id,),
            ).fetchone()
            row = conn.execute(
                "SELECT batch_id, match_status FROM inventory_import_rows WHERE row_id = ?",
                (row_id,),
            ).fetchone()
            if row is None or product is None:
                raise InventoryImportRepositoryError("Fila o producto de resolución inexistente")
            if row["match_status"] not in ("MATCH_CANDIDATE", "AMBIGUOUS"):
                raise InventoryImportRepositoryError("La fila no requiere CONFIRM MATCH")
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    UPDATE inventory_import_apply_rows
                       SET identity_resolution='CONFIRMED',
                           resolved_producto_local_id=?, resolved_product_name=?,
                           resolved_by=?, resolved_at=CURRENT_TIMESTAMP,
                           updated_at=CURRENT_TIMESTAMP
                     WHERE row_id=? AND apply_state='PENDING'
                    """,
                    (producto_local_id, product["nombre"], actor, row_id),
                )
                self._invalidate_approval_in_connection(conn, row["batch_id"])
                self._audit_in_connection(
                    conn, row["batch_id"], "MATCH_CONFIRMED", actor=actor,
                    row_id=row_id, producto_local_id=producto_local_id,
                    after={"producto_local_id": producto_local_id, "nombre": product["nombre"]},
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def resolve_duplicate(self, row_id: str, decision: str, *, actor: Optional[str] = None) -> None:
        decision = str(decision or "").strip().upper()
        if decision not in ("NOT_DUPLICATE", "CONFIRMED_MATCH", "REJECTED"):
            raise InventoryImportRepositoryError("Resolución de duplicado inválida")
        self._set_review_decision(
            row_id, "duplicate_resolution", decision,
            "DUPLICATE_RESOLVED", actor=actor,
        )

    def acknowledge_warning(self, row_id: str, *, actor: Optional[str] = None) -> None:
        self._set_review_decision(
            row_id, "warning_approved", 1, "WARNING_APPROVED", actor=actor,
            extra=("warning_approved_by", "warning_approved_at"),
        )

    def acknowledge_batch_warnings(self, batch_id: str, *, actor: Optional[str] = None) -> None:
        """Confirmación humana explícita para warnings de workbook y filas."""
        with self.connection() as conn:
            self._require_apply_schema(conn)
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    UPDATE inventory_import_apply_batches
                       SET workbook_warnings_approved=1,
                           workbook_warnings_approved_by=?,
                           workbook_warnings_approved_at=CURRENT_TIMESTAMP,
                           updated_at=CURRENT_TIMESTAMP
                     WHERE batch_id=? AND workflow_state NOT IN ('APPLYING','APPLIED')
                    """,
                    (actor, batch_id),
                )
                conn.execute(
                    """
                    UPDATE inventory_import_apply_rows
                       SET warning_approved=1, warning_approved_by=?,
                           warning_approved_at=CURRENT_TIMESTAMP,
                           updated_at=CURRENT_TIMESTAMP
                     WHERE batch_id=? AND apply_state='PENDING'
                    """,
                    (actor, batch_id),
                )
                self._invalidate_approval_in_connection(conn, batch_id)
                self._audit_in_connection(
                    conn, batch_id, "WARNINGS_APPROVED", actor=actor,
                    after={"explicit_confirmation": True},
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def decide_metadata(
        self,
        row_id: str,
        decision: str,
        *,
        fields: Iterable[str] = (),
        actor: Optional[str] = None,
    ) -> None:
        decision = str(decision or "").strip().upper()
        if decision not in ("APPLY", "KEEP_CURRENT"):
            raise InventoryImportRepositoryError("Decisión metadata inválida")
        with self.connection() as conn:
            self._require_apply_schema(conn)
            row = conn.execute(
                "SELECT batch_id FROM inventory_import_rows WHERE row_id=?",
                (row_id,),
            ).fetchone()
            if row is None:
                raise InventoryImportRepositoryError("Fila inexistente")
            try:
                conn.execute("BEGIN IMMEDIATE")
                changed = conn.execute(
                    """
                    UPDATE inventory_import_apply_rows
                       SET metadata_decision=?, metadata_fields_json=?,
                           metadata_decided_by=?, metadata_decided_at=CURRENT_TIMESTAMP,
                           updated_at=CURRENT_TIMESTAMP
                     WHERE row_id=? AND apply_state='PENDING'
                    """,
                    (decision, _json(sorted(set(fields))), actor, row_id),
                ).rowcount
                if changed != 1:
                    raise InventoryImportRepositoryError("Fila ya no admite revisión")
                self._invalidate_approval_in_connection(conn, row["batch_id"])
                self._audit_in_connection(
                    conn, row["batch_id"], "METADATA_DECIDED", actor=actor,
                    row_id=row_id, after={"decision": decision, "fields": sorted(set(fields))},
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def _set_review_decision(
        self, row_id: str, column: str, value: Any, event_type: str, *,
        actor: Optional[str], extra: tuple[str, str] | None = None,
    ) -> None:
        allowed = {"duplicate_resolution", "warning_approved"}
        if column not in allowed:
            raise InventoryImportRepositoryError("Columna de revisión no permitida")
        with self.connection() as conn:
            self._require_apply_schema(conn)
            row = conn.execute(
                "SELECT batch_id FROM inventory_import_rows WHERE row_id=?",
                (row_id,),
            ).fetchone()
            if row is None:
                raise InventoryImportRepositoryError("Fila inexistente")
            try:
                conn.execute("BEGIN IMMEDIATE")
                assignments = f"{column}=?, updated_at=CURRENT_TIMESTAMP"
                params: list[Any] = [value]
                if extra:
                    assignments += f", {extra[0]}=?, {extra[1]}=CURRENT_TIMESTAMP"
                    params.append(actor)
                params.append(row_id)
                changed = conn.execute(
                    f"UPDATE inventory_import_apply_rows SET {assignments} "
                    "WHERE row_id=? AND apply_state='PENDING'",
                    params,
                ).rowcount
                if changed != 1:
                    raise InventoryImportRepositoryError("Fila ya no admite revisión")
                self._invalidate_approval_in_connection(conn, row["batch_id"])
                self._audit_in_connection(
                    conn, row["batch_id"], event_type, actor=actor,
                    row_id=row_id, after={column: value},
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    @staticmethod
    def _audit_in_connection(
        conn, batch_id: str, event_type: str, *, actor=None, row_id=None,
        apply_id=None, producto_local_id=None, inventory_command_id=None,
        before=None, after=None, result=None, error=None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO inventory_import_apply_audit (
                audit_id,batch_id,row_id,apply_id,producto_local_id,
                inventory_command_id,event_type,actor,before_json,after_json,
                result_json,error
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                str(uuid.uuid4()), batch_id, row_id, apply_id,
                producto_local_id, inventory_command_id, event_type, actor,
                None if before is None else _json(before),
                None if after is None else _json(after),
                None if result is None else _json(result), error,
            ),
        )

    def append_audit(self, batch_id: str, event_type: str, **kwargs) -> None:
        with self.connection() as conn:
            self._require_apply_schema(conn)
            self._audit_in_connection(conn, batch_id, event_type, **kwargs)
            conn.commit()

    def save_approval(
        self, batch_id: str, *, plan: Mapping[str, Any], plan_hash: str,
        source_hash: str, actor: Optional[str], row_snapshots: Iterable[Mapping[str, Any]],
    ) -> dict:
        approval_id = str(uuid.uuid4())
        apply_id = str(uuid.uuid4())
        snapshots = list(row_snapshots)
        with self.connection() as conn:
            self._require_apply_schema(conn)
            try:
                conn.execute("BEGIN IMMEDIATE")
                current = conn.execute(
                    "SELECT workflow_state FROM inventory_import_apply_batches WHERE batch_id=?",
                    (batch_id,),
                ).fetchone()
                if current is None or current["workflow_state"] in ("APPLYING", "APPLIED", "COMPLETED", "CANCELLED"):
                    raise InventoryImportRepositoryError("Transición a APPROVED no autorizada")
                conn.execute(
                    """
                    UPDATE inventory_import_apply_batches
                       SET workflow_state='APPROVED', approval_id=?,
                           approval_plan_hash=?, approval_source_hash=?,
                           approved_plan_json=?, approved_by=?,
                           approved_at=CURRENT_TIMESTAMP,
                           approval_invalidated_at=NULL, apply_id=?,
                           stop_requested=0, last_error=NULL,
                           updated_at=CURRENT_TIMESTAMP
                     WHERE batch_id=?
                    """,
                    (approval_id, plan_hash, source_hash, _json(plan), actor, apply_id, batch_id),
                )
                for snapshot in snapshots:
                    conn.execute(
                        """
                        UPDATE inventory_import_apply_rows
                           SET apply_state='APPROVED', approved_snapshot_json=?,
                               producto_local_id=?, inventory_command_id=?,
                               inventory_operation_id=?, old_balance_scaled=?,
                               physical_count_scaled=?, delta_scaled=?,
                               metadata_before_json=?, metadata_after_json=?,
                               last_error=NULL, updated_at=CURRENT_TIMESTAMP
                         WHERE row_id=? AND batch_id=?
                        """,
                        (
                            _json(snapshot), snapshot.get("producto_local_id"),
                            snapshot.get("inventory_command_id"),
                            snapshot.get("inventory_operation_id"),
                            snapshot.get("old_balance_scaled"),
                            snapshot.get("physical_count_scaled"),
                            snapshot.get("delta_scaled"),
                            _json(snapshot.get("metadata_before") or {}),
                            _json(snapshot.get("metadata_after") or {}),
                            snapshot["row_id"], batch_id,
                        ),
                    )
                self._audit_in_connection(
                    conn, batch_id, "BATCH_APPROVED", actor=actor,
                    apply_id=apply_id, after={"approval_id": approval_id, "plan_hash": plan_hash},
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self.get_apply_batch(batch_id)

    def mark_review_required(self, batch_id: str, error: str, *, event_type="APPROVAL_INVALIDATED") -> None:
        with self.connection() as conn:
            self._require_apply_schema(conn)
            try:
                conn.execute("BEGIN IMMEDIATE")
                self._invalidate_approval_in_connection(conn, batch_id)
                conn.execute(
                    "UPDATE inventory_import_apply_batches SET last_error=? WHERE batch_id=?",
                    (error, batch_id),
                )
                self._audit_in_connection(conn, batch_id, event_type, error=error)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def acquire_apply_lease(self, batch_id: str, *, ttl_seconds: int = 120) -> dict:
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=max(15, int(ttl_seconds)))
        token = str(uuid.uuid4())
        now_text = now.isoformat(timespec="microseconds")
        expires_text = expires.isoformat(timespec="microseconds")
        with self.connection() as conn:
            self._require_apply_schema(conn)
            try:
                conn.execute("BEGIN IMMEDIATE")
                changed = conn.execute(
                    """
                    UPDATE inventory_import_apply_batches
                       SET workflow_state='APPLYING', lease_token=?,
                           lease_expires_at=?, apply_started_at=COALESCE(apply_started_at, ?),
                           updated_at=?, last_error=NULL
                     WHERE batch_id=?
                       AND (
                           workflow_state='APPROVED'
                           OR (workflow_state IN ('APPLYING','PARTIALLY_FAILED')
                               AND (lease_token IS NULL OR lease_expires_at IS NULL
                                    OR lease_expires_at < ?))
                       )
                    """,
                    (token, expires_text, now_text, now_text, batch_id, now_text),
                ).rowcount
                if changed != 1:
                    current = conn.execute(
                        "SELECT workflow_state, lease_expires_at FROM inventory_import_apply_batches WHERE batch_id=?",
                        (batch_id,),
                    ).fetchone()
                    state = current["workflow_state"] if current else "MISSING"
                    raise InventoryImportRepositoryError(f"ALREADY_APPLYING / CONFLICT ({state})")
                current = conn.execute(
                    "SELECT * FROM inventory_import_apply_batches WHERE batch_id=?",
                    (batch_id,),
                ).fetchone()
                self._audit_in_connection(
                    conn, batch_id, "APPLY_LEASE_ACQUIRED",
                    apply_id=current["apply_id"], result={"lease_token": token},
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return {"lease_token": token, "lease_expires_at": expires_text}

    def renew_apply_lease(self, batch_id: str, token: str, *, ttl_seconds: int = 120) -> None:
        expires = (datetime.now(timezone.utc) + timedelta(seconds=max(15, int(ttl_seconds)))).isoformat(timespec="microseconds")
        with self.connection() as conn:
            changed = conn.execute(
                """
                UPDATE inventory_import_apply_batches
                   SET lease_expires_at=?, updated_at=CURRENT_TIMESTAMP
                 WHERE batch_id=? AND workflow_state='APPLYING' AND lease_token=?
                """,
                (expires, batch_id, token),
            ).rowcount
            conn.commit()
            if changed != 1:
                raise InventoryImportRepositoryError("Lease de APPLY perdido")

    def update_apply_row(self, row_id: str, state: str, **values) -> None:
        allowed = {
            "producto_local_id", "producto_id", "apply_result_json", "last_error",
            "applied_at", "verified_at", "old_balance_scaled",
            "physical_count_scaled", "delta_scaled",
        }
        unknown = set(values) - allowed
        if unknown:
            raise InventoryImportRepositoryError("Campos de estado no permitidos: " + ", ".join(sorted(unknown)))
        from inventory_apply_schema import ROW_APPLY_STATES
        if state not in ROW_APPLY_STATES:
            raise InventoryImportRepositoryError("Estado de fila inválido")
        assignments = ["apply_state=?", "updated_at=CURRENT_TIMESTAMP", "apply_attempts=apply_attempts+1"]
        params: list[Any] = [state]
        for key, value in values.items():
            assignments.append(f"{key}=?")
            params.append(_json(value) if key == "apply_result_json" and value is not None else value)
        params.append(row_id)
        with self.connection() as conn:
            changed = conn.execute(
                f"UPDATE inventory_import_apply_rows SET {', '.join(assignments)} WHERE row_id=?",
                params,
            ).rowcount
            conn.commit()
            if changed != 1:
                raise InventoryImportRepositoryError("Fila apply inexistente")

    def finish_apply(self, batch_id: str, token: str, state: str, *, error: Optional[str] = None) -> None:
        if state not in ("APPLIED", "COMPLETED", "PARTIALLY_FAILED", "FAILED", "REVIEW_REQUIRED"):
            raise InventoryImportRepositoryError("Estado final de APPLY inválido")
        with self.connection() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                changed = conn.execute(
                    """
                    UPDATE inventory_import_apply_batches
                       SET workflow_state=?, lease_token=NULL, lease_expires_at=NULL,
                           apply_finished_at=CASE WHEN ? IN ('APPLIED','COMPLETED') THEN CURRENT_TIMESTAMP
                               ELSE apply_finished_at END,
                           last_error=?, updated_at=CURRENT_TIMESTAMP
                     WHERE batch_id=? AND lease_token=?
                    """,
                    (state, state, error, batch_id, token),
                ).rowcount
                if changed != 1:
                    raise InventoryImportRepositoryError("Lease perdido al finalizar APPLY")
                if state in ("APPLIED", "COMPLETED"):
                    conn.execute(
                        """
                        UPDATE inventory_import_batches
                           SET status='APPLIED', applied_at=CURRENT_TIMESTAMP
                         WHERE batch_id=?
                        """,
                        (batch_id,),
                    )
                self._audit_in_connection(
                    conn, batch_id, "BATCH_" + state, error=error,
                    result={"state": state},
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def request_stop(self, batch_id: str, *, actor: Optional[str] = None) -> None:
        """Detiene nuevas filas; nunca revierte comandos ya aplicados."""
        with self.connection() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                changed = conn.execute(
                    """
                    UPDATE inventory_import_apply_batches
                       SET stop_requested=1, updated_at=CURRENT_TIMESTAMP
                     WHERE batch_id=? AND workflow_state='APPLYING'
                    """,
                    (batch_id,),
                ).rowcount
                if changed != 1:
                    raise InventoryImportRepositoryError("Batch no está APPLYING")
                self._audit_in_connection(
                    conn, batch_id, "STOP_REQUESTED", actor=actor,
                    after={"stop_new_rows": True, "rollback": False},
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def cancel_batch(self, batch_id: str, *, actor: Optional[str] = None) -> None:
        """Cancelación pre-APPLY; nunca intenta compensar filas aplicadas."""
        with self.connection() as conn:
            self._require_apply_schema(conn)
            try:
                conn.execute("BEGIN IMMEDIATE")
                applied = conn.execute(
                    """
                    SELECT COUNT(*) FROM inventory_import_apply_rows
                     WHERE batch_id=? AND apply_state IN (
                         'INVENTORY_APPLIED','VERIFYING','VERIFIED','NO_CHANGE_VERIFIED'
                     )
                    """,
                    (batch_id,),
                ).fetchone()[0]
                if applied:
                    raise InventoryImportRepositoryError(
                        "No se cancela: ya existen operaciones reales; use reconciliación"
                    )
                changed = conn.execute(
                    """
                    UPDATE inventory_import_apply_batches
                       SET workflow_state='CANCELLED', lease_token=NULL,
                           lease_expires_at=NULL, updated_at=CURRENT_TIMESTAMP
                     WHERE batch_id=? AND workflow_state NOT IN (
                         'APPLYING','APPLIED','COMPLETED','CANCELLED'
                     )
                    """,
                    (batch_id,),
                ).rowcount
                if changed != 1:
                    raise InventoryImportRepositoryError("Batch no admite cancelación")
                conn.execute(
                    "UPDATE inventory_import_apply_rows SET apply_state='CANCELLED' "
                    "WHERE batch_id=? AND apply_state IN ('PENDING','APPROVED')",
                    (batch_id,),
                )
                self._audit_in_connection(conn, batch_id, "BATCH_CANCELLED", actor=actor)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def list_audit(self, batch_id: str) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM inventory_import_apply_audit WHERE batch_id=? ORDER BY created_at,audit_id",
                (batch_id,),
            ).fetchall()
            return [self._dict(row) or {} for row in rows]

    def list_products(self) -> list[dict]:
        with self.connection() as conn:
            fields = schema_bootstrap.column_names(conn, "productos")
            wanted = [
                name for name in (
                    "id", "local_id", "nombre", "categoria", "marca", "presentacion",
                    "unidad_medida", "precio_compra", "precio_venta", "stock_minimo",
                    "stock", "activo", "viene_en_caja", "unidades_por_caja",
                    "unidades_por_media_caja", "vende_por_empaque",
                    "permite_decimales", "usar_unidades_categoria",
                    "unidades_venta_custom", "unidad_base_producto", "barcode_status",
                    "remote_id", "sync_status", "last_synced_at",
                ) if name in fields
            ]
            if "local_id" not in wanted:
                raise InventoryImportRepositoryError("productos.local_id es obligatorio para matching")
            sql = "SELECT " + ", ".join(wanted) + " FROM productos"
            if "activo" in fields:
                sql += " WHERE activo = 1"
            return [self._dict(row) or {} for row in conn.execute(sql).fetchall()]

    def verified_barcode_owners(self) -> dict[str, dict]:
        with self.connection() as conn:
            if not schema_bootstrap.table_exists(conn, "product_barcodes"):
                return {}
            rows = conn.execute(
                """
                SELECT b.barcode, b.producto_local_id, p.nombre
                FROM product_barcodes b
                LEFT JOIN productos p ON p.local_id = b.producto_local_id
                WHERE b.active = 1
                """
            ).fetchall()
            return {
                str((self._dict(row) or {})["barcode"]): self._dict(row) or {}
                for row in rows
            }

    def cutover_status(self) -> str:
        with self.connection() as conn:
            for table in ("inventory_cutover_control", "inventory_cutover_state"):
                if schema_bootstrap.table_exists(conn, table):
                    try:
                        row = conn.execute(f"SELECT status FROM {table} ORDER BY id LIMIT 1").fetchone()
                        if row:
                            data = self._dict(row)
                            return str(data["status"] if data else row[0]).upper()
                    except Exception:
                        continue
            return "PRE_CUTOVER"

    def current_quantity_scaled(
        self,
        producto_local_id: str,
        *,
        authority_reader=None,
    ) -> tuple[int, str]:
        if authority_reader is not None:
            value = authority_reader(producto_local_id)
            return (0 if value is None else int(value), "inventory_balances")
        status = self.cutover_status()
        if status == "AUTHORITATIVE":
            with self.connection() as conn:
                if schema_bootstrap.table_exists(conn, "inventory_balances"):
                    row = conn.execute(
                        "SELECT quantity_scaled FROM inventory_balances WHERE producto_local_id = ?",
                        (producto_local_id,),
                    ).fetchone()
                    return (0 if row is None else int(row[0]), "inventory_balances")
            raise InventoryAuthorityUnavailable(
                "Modo AUTHORITATIVE requiere inventory_balances; no se usa productos.stock"
            )
        with self.connection() as conn:
            row = conn.execute(
                "SELECT stock FROM productos WHERE local_id = ?",
                (producto_local_id,),
            ).fetchone()
            value = Decimal(str(0 if row is None or row[0] is None else row[0]))
            return decimal_to_scaled(value), "productos.stock (PRE_CUTOVER)"
