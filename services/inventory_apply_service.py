# -*- coding: utf-8 -*-
"""Apply engine controlado y recuperable para inventario físico (Fase 2E)."""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Iterable, Mapping, Optional

from inventory_gateway import (
    OUTCOME_APPLIED,
    OUTCOME_REJECTED,
    OUTCOME_UNKNOWN,
    InventoryGateway,
    connection_factory_from_env,
)
from inventory_writer_support import stable_operation_id
from models import Producto
from product_inventory_contract import NO_PACKAGE_VALUE, normalized_text
from repositories.inventory_import_repository import (
    InventoryImportRepository,
    InventoryImportRepositoryError,
)
from repositories.productos_repo import PRODUCT_CREATION_STAGING, ProductosRepository


INVENTORY_REASON = "INVENTARIO_FISICO"
DOCUMENT_TYPE = "inventory_reconciliation"
APPLY_NAMESPACE = uuid.UUID("81c2e27d-2d75-4fc4-a70b-81a2d417aa1f")


class InventoryApplyError(RuntimeError):
    pass


class ApprovalBlockedError(InventoryApplyError):
    def __init__(self, blockers: Iterable[Mapping[str, Any]]):
        self.blockers = tuple(dict(item) for item in blockers)
        message = "; ".join(
            f"fila {item.get('excel_row_number', '?')}: {item.get('reason')}"
            for item in self.blockers
        ) or "Batch no aprobable"
        super().__init__(message)


class ApprovedPlanChangedError(InventoryApplyError):
    pass


class StaleBalanceError(InventoryApplyError):
    pass


class ApplyVerificationError(InventoryApplyError):
    pass


@dataclass(frozen=True)
class ApplyProgress:
    batch_id: str
    apply_id: str
    state: str
    processed: int
    total: int
    verified: int
    failed: int
    unknown: int


def _json_default(value: Any):
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(f"No serializable: {type(value)!r}")


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        default=_json_default,
    )


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _as_decimal(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value or 0))


def _number(value: Any):
    dec = _as_decimal(value)
    return int(dec) if dec == dec.to_integral_value() else float(dec)


def _same(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float, Decimal)) or isinstance(right, (int, float, Decimal)):
        try:
            return _as_decimal(left) == _as_decimal(right)
        except Exception:
            pass
    return normalized_text(left) == normalized_text(right)


class InventoryImportApplyService:
    """Coordina revisión, aprobación, saga, CAS y verificación.

    El plan aprobado es el único input de APPLY. Staging se usa solo para
    comprobar que ese snapshot todavía es vigente.
    """

    def __init__(
        self,
        repository: InventoryImportRepository,
        *,
        product_repository=None,
        gateway=None,
        gateway_factory: Optional[Callable[[object], Any]] = None,
        authority_reader: Optional[Callable[[str], Optional[int]]] = None,
        connection_factory=None,
        actor_provider: Optional[Callable[[], Any]] = None,
        remote_product_ready: Optional[Callable[[Mapping[str, Any]], bool]] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> None:
        self.repository = repository
        source = repository.source
        self.product_repository = product_repository
        if self.product_repository is None and hasattr(source, "conectar"):
            self.product_repository = ProductosRepository(source)
        self.gateway = gateway
        self.gateway_factory = gateway_factory
        self.authority_reader = authority_reader
        self.connection_factory = connection_factory
        self.actor_provider = actor_provider
        self.remote_product_ready = remote_product_ready
        self.progress_callback = progress_callback

    def _actor(self, actor) -> Optional[str]:
        if actor is None and self.actor_provider:
            actor = self.actor_provider()
        return None if actor is None else str(actor)

    @staticmethod
    def _source_payload(rows: Iterable[Mapping[str, Any]], batch: Mapping[str, Any]) -> dict:
        material = []
        for row in rows:
            material.append({
                "row_id": row["row_id"],
                "row_hash": row["row_hash"],
                "payload": row["normalized_payload"],
                "count": row.get("cantidad_contada_scaled"),
                "validation": row["validation_status"],
                "errors": row["validation_errors"],
                "warnings": row["validation_warnings"],
                "match": row["match_status"],
                "matched": row.get("matched_producto_local_id"),
                "barcode_status": row["barcode_status"],
                "barcode_candidate": row.get("barcode_candidate"),
                "duplicate_candidate": int(row.get("duplicate_candidate") or 0),
                "identity_resolution": row["identity_resolution"],
                "resolved": row.get("resolved_producto_local_id"),
                "duplicate_resolution": row["duplicate_resolution"],
                "warning_approved": int(row["warning_approved"] or 0),
                "metadata_decision": row["metadata_decision"],
                "metadata_fields": row.get("metadata_fields") or [],
            })
        return {
            "rows": material,
            "workbook_warnings": batch.get("workbook_warnings") or [],
            "workbook_warnings_approved": int(batch.get("workbook_warnings_approved") or 0),
        }

    @staticmethod
    def _resolved_local_id(row: Mapping[str, Any]) -> Optional[str]:
        if row["match_status"] in ("MATCH_CANDIDATE", "AMBIGUOUS"):
            if row["identity_resolution"] == "CONFIRMED":
                return str(row.get("resolved_producto_local_id") or "") or None
            return None
        value = row.get("matched_producto_local_id")
        return str(value) if value else None

    @staticmethod
    def _mapped_product(payload: Mapping[str, Any]) -> dict:
        package_size = max(1, int(_as_decimal(payload.get("cantidad_base_por_empaque") or 1)))
        presentation = str(payload.get("presentacion_empaque") or "").strip()
        packaged = normalized_text(presentation) != normalized_text(NO_PACKAGE_VALUE)
        sell_base = normalized_text(payload.get("vende_unidad_base")) == "si"
        sell_half = normalized_text(payload.get("vende_medio_empaque")) == "si"
        sell_full = normalized_text(payload.get("vende_empaque_completo")) == "si"
        sales_forms = []
        if sell_base:
            sales_forms.append({"nombre": "Unidad base", "factor": 1})
        if sell_half:
            sales_forms.append({"nombre": "Medio empaque", "factor": package_size / 2})
        if sell_full:
            sales_forms.append({"nombre": "Empaque completo", "factor": package_size})
        return {
            "nombre": str(payload.get("nombre") or "").strip(),
            "categoria": str(payload.get("categoria") or "").strip(),
            "marca": str(payload.get("marca") or "").strip() or None,
            "presentacion": presentation or None,
            "precio_compra": _number(payload.get("precio_compra")),
            "precio_venta": _number(payload.get("precio_venta")),
            "stock_minimo": int(_as_decimal(payload.get("stock_minimo"))),
            "unidad_medida": str(payload.get("unidad_base") or "UNIDAD").strip(),
            "viene_en_caja": 1 if packaged else 0,
            "unidades_por_caja": package_size,
            "unidades_por_media_caja": max(1, package_size // 2),
            "vende_por_empaque": 1 if sell_half or sell_full else 0,
            "permite_decimales": 1 if normalized_text(payload.get("permite_decimales")) == "si" else 0,
            "usar_unidades_categoria": 0,
            "unidades_venta_custom": _canonical(sales_forms),
            "unidad_base_producto": str(payload.get("unidad_base") or "UNIDAD").strip(),
        }

    @staticmethod
    def _product_subset(product: Mapping[str, Any]) -> dict:
        keys = (
            "nombre", "categoria", "marca", "presentacion", "precio_compra",
            "precio_venta", "stock_minimo", "unidad_medida", "viene_en_caja",
            "unidades_por_caja", "unidades_por_media_caja", "vende_por_empaque",
            "permite_decimales", "usar_unidades_categoria",
            "unidades_venta_custom", "unidad_base_producto",
        )
        return {key: product.get(key) for key in keys}

    def _products(self) -> dict[str, dict]:
        return {
            str(item.get("local_id")): item
            for item in self.repository.list_products()
            if item.get("local_id")
        }

    def build_review_plan(self, batch_id: str) -> dict:
        self.repository.ensure_apply_controls(batch_id)
        rows = self.repository.list_apply_rows(batch_id)
        batch_2d = self.repository.get_batch(batch_id)
        batch = self.repository.get_apply_batch(batch_id)
        products = self._products()
        blockers = []
        plans = []
        warnings = 0
        metadata_changes = 0
        positive = negative = unchanged = 0
        existing = new = barcode_pending = 0
        positive_net = negative_net = 0

        if int(batch_2d.get("error_count") or 0):
            blockers.append({"reason": "BATCH_HAS_ERRORS"})
        workbook_warnings = batch_2d.get("workbook_warnings") or []
        if workbook_warnings and not int(batch.get("workbook_warnings_approved") or 0):
            blockers.append({"reason": "WORKBOOK_WARNING_NOT_APPROVED"})
        warnings += len(workbook_warnings)

        for row in rows:
            excel_no = int(row["excel_row_number"])
            base = {"row_id": row["row_id"], "excel_row_number": excel_no}
            if row["validation_status"] == "ERROR":
                blockers.append({**base, "reason": "VALIDATION_ERROR"})
                continue
            if row["match_status"] == "INVALID":
                blockers.append({**base, "reason": "INVALID"})
                continue
            if row["barcode_status"] in ("BARCODE_ERROR", "CONFLICT_BARCODE_PRODUCT"):
                blockers.append({**base, "reason": row["barcode_status"]})
                continue
            if row["match_status"] in ("MATCH_CANDIDATE", "AMBIGUOUS") and row["identity_resolution"] != "CONFIRMED":
                blockers.append({**base, "reason": "MATCH_CONFIRMATION_REQUIRED"})
                continue
            if int(row.get("duplicate_candidate") or 0) and row["duplicate_resolution"] == "PENDING":
                blockers.append({**base, "reason": "DUPLICATE_CANDIDATE_UNRESOLVED"})
                continue
            if row["duplicate_resolution"] == "REJECTED":
                blockers.append({**base, "reason": "DUPLICATE_REJECTED"})
                continue
            row_warnings = row["validation_warnings"] or []
            warnings += len(row_warnings)
            if row_warnings and not int(row["warning_approved"] or 0):
                blockers.append({**base, "reason": "WARNING_NOT_APPROVED"})
                continue
            counted = row.get("cantidad_contada_scaled")
            if counted is None:
                blockers.append({**base, "reason": "COUNT_UNAVAILABLE"})
                continue

            payload = row["normalized_payload"]
            proposed = self._mapped_product(payload)
            barcode_pending += 1
            local_id = self._resolved_local_id(row)
            if row["match_status"] == "NEW_PRODUCT":
                new += 1
                plan = {
                    **base,
                    "kind": "NEW_PRODUCT",
                    "producto_local_id": None,
                    "product": proposed,
                    "metadata_before": {},
                    "metadata_after": proposed,
                    "old_balance_scaled": 0,
                    "physical_count_scaled": int(counted),
                    "delta_scaled": int(counted),
                    "barcode_status": "BARCODE_PENDING",
                    "barcode_candidate_persist": False,
                    "metadata_decision": "APPLY",
                }
                if int(counted) > 0:
                    positive += 1
                    positive_net += int(counted)
                else:
                    unchanged += 1
                plans.append(plan)
                continue

            if not local_id or local_id not in products:
                blockers.append({**base, "reason": "RESOLVED_PRODUCT_MISSING"})
                continue
            existing += 1
            current_product = self._product_subset(products[local_id])
            changes = {
                key: {"current": current_product.get(key), "proposed": value}
                for key, value in proposed.items()
                if not _same(current_product.get(key), value)
            }
            decision = row["metadata_decision"]
            if changes and decision == "PENDING":
                blockers.append({**base, "reason": "METADATA_APPROVAL_REQUIRED", "fields": sorted(changes)})
                continue
            selected = set(row.get("metadata_fields") or [])
            if decision == "APPLY":
                if not selected:
                    selected = set(changes)
                unknown = selected - set(changes)
                if unknown:
                    blockers.append({**base, "reason": "INVALID_METADATA_FIELDS", "fields": sorted(unknown)})
                    continue
                metadata_after = dict(current_product)
                for key in selected:
                    metadata_after[key] = changes[key]["proposed"]
                metadata_changes += len(selected)
            else:
                metadata_after = dict(current_product)
            current_qty, source = self.repository.current_quantity_scaled(
                local_id, authority_reader=self.authority_reader
            )
            delta = int(counted) - int(current_qty)
            if delta > 0:
                positive += 1
                positive_net += delta
            elif delta < 0:
                negative += 1
                negative_net += abs(delta)
            else:
                unchanged += 1
            plans.append({
                **base,
                "kind": "EXISTING_PRODUCT",
                "producto_local_id": local_id,
                "product": proposed,
                "metadata_changes": changes,
                "metadata_before": current_product,
                "metadata_after": metadata_after,
                "metadata_decision": decision if changes else "NOT_REQUIRED",
                "old_balance_scaled": int(current_qty),
                "physical_count_scaled": int(counted),
                "delta_scaled": delta,
                "authority_source": source,
                "barcode_status": row["barcode_status"],
                "barcode_candidate_persist": False,
            })

        source = self._source_payload(rows, {**batch_2d, **batch})
        return {
            "batch_id": batch_id,
            "revision": int(batch["revision"]),
            "source_hash": _hash(source),
            "rows": plans,
            "blockers": blockers,
            "summary": {
                "products": len(plans), "existing_products": existing,
                "new_products": new, "inventory_adjustments": positive + negative,
                "positive_adjustments": positive, "negative_adjustments": negative,
                "unchanged": unchanged, "positive_net_scaled": positive_net,
                "negative_net_scaled": negative_net,
                "metadata_changes": metadata_changes, "warnings": warnings,
                "barcode_pending": barcode_pending, "blocking_rows": len(blockers),
            },
        }

    def approve_batch(self, batch_id: str, *, actor=None) -> dict:
        actor = self._actor(actor)
        review = self.build_review_plan(batch_id)
        if review["blockers"]:
            raise ApprovalBlockedError(review["blockers"])
        approved_rows = []
        try:
            batch_uuid = uuid.UUID(batch_id)
        except ValueError:
            batch_uuid = uuid.uuid5(APPLY_NAMESPACE, batch_id)
        for row in review["rows"]:
            item = dict(row)
            row_key = str(row["row_id"])
            if item["kind"] == "NEW_PRODUCT":
                item["producto_local_id"] = str(uuid.uuid5(batch_uuid, f"product:{row_key}"))
            command_id = str(uuid.uuid5(batch_uuid, f"inventory:{row_key}"))
            item["inventory_command_id"] = command_id if item["delta_scaled"] else None
            item["inventory_operation_id"] = (
                stable_operation_id(command_id, 1) if item["delta_scaled"] else None
            )
            approved_rows.append(item)
        plan = {
            "contract": "FERREPRO_INVENTORY_APPLY_V1",
            "batch_id": batch_id,
            "revision": review["revision"],
            "reason": INVENTORY_REASON,
            "summary": review["summary"],
            "rows": approved_rows,
        }
        plan_hash = _hash(plan)
        return self.repository.save_approval(
            batch_id, plan=plan, plan_hash=plan_hash,
            source_hash=review["source_hash"], actor=actor,
            row_snapshots=approved_rows,
        )

    def _assert_approved_plan_current(self, batch_id: str) -> dict:
        current = self.repository.get_apply_batch(batch_id)
        if current["workflow_state"] not in ("APPROVED", "PARTIALLY_FAILED", "APPLYING"):
            raise InventoryApplyError(f"Batch no está APPROVED: {current['workflow_state']}")
        plan = current.get("approved_plan")
        if not plan or _hash(plan) != current.get("approval_plan_hash"):
            raise ApprovedPlanChangedError("Plan aprobado ausente o alterado")
        rows = self.repository.list_apply_rows(batch_id)
        batch_2d = self.repository.get_batch(batch_id)
        actual_source = _hash(self._source_payload(rows, {**batch_2d, **current}))
        if actual_source != current.get("approval_source_hash"):
            self.repository.mark_review_required(
                batch_id, "STAGING_CHANGED_AFTER_APPROVAL",
                event_type="APPROVAL_INVALIDATED_STAGING_CHANGED",
            )
            raise ApprovedPlanChangedError("Staging cambió después de aprobar; requiere nueva aprobación")
        return current

    def final_preflight(self, batch_id: str) -> tuple[dict, ...]:
        current = self._assert_approved_plan_current(batch_id)
        conflicts = []
        states = {row["row_id"]: row["apply_state"] for row in self.repository.list_apply_rows(batch_id)}
        for row in current["approved_plan"]["rows"]:
            if states.get(row["row_id"]) in (
                "VERIFIED", "NO_CHANGE_VERIFIED", "INVENTORY_UNKNOWN",
                "INVENTORY_APPLIED", "VERIFYING",
            ):
                continue
            if row["kind"] != "EXISTING_PRODUCT":
                continue
            actual, _source = self.repository.current_quantity_scaled(
                row["producto_local_id"], authority_reader=self.authority_reader
            )
            if int(actual) != int(row["old_balance_scaled"]):
                conflicts.append({
                    "row_id": row["row_id"],
                    "excel_row_number": row["excel_row_number"],
                    "producto_local_id": row["producto_local_id"],
                    "approved_base_scaled": int(row["old_balance_scaled"]),
                    "actual_base_scaled": int(actual),
                    "physical_count_scaled": int(row["physical_count_scaled"]),
                    "new_delta_scaled": int(row["physical_count_scaled"]) - int(actual),
                    "reason": "STALE_BALANCE",
                })
        return tuple(conflicts)

    def _gateway_for(self, conn):
        if self.gateway_factory:
            return self.gateway_factory(conn)
        if self.gateway is not None:
            return self.gateway
        factory = self.connection_factory or connection_factory_from_env()
        return InventoryGateway(conn, connection_factory=factory, cutover_enabled=True)

    @staticmethod
    def _producto_from_values(values: Mapping[str, Any], *, product_id=None, stock=0) -> Producto:
        return Producto(
            id=product_id,
            codigo_barras=None,
            nombre=values.get("nombre") or "",
            categoria=values.get("categoria"), marca=values.get("marca"),
            presentacion=values.get("presentacion"),
            precio_compra=float(values.get("precio_compra") or 0),
            precio_venta=float(values.get("precio_venta") or 0),
            stock=float(stock), stock_minimo=int(values.get("stock_minimo") or 0),
            unidad_medida=values.get("unidad_medida") or "UNIDAD",
            viene_en_caja=bool(values.get("viene_en_caja")),
            unidades_por_caja=int(values.get("unidades_por_caja") or 1),
            unidades_por_media_caja=int(values.get("unidades_por_media_caja") or 1),
            vende_por_empaque=int(values.get("vende_por_empaque") or 0),
            usar_unidades_categoria=bool(values.get("usar_unidades_categoria", 0)),
            unidades_venta_custom=values.get("unidades_venta_custom"),
            unidad_base_producto=values.get("unidad_base_producto"),
            permite_decimales=bool(values.get("permite_decimales")),
            iva=0, activo=True,
        )

    def _get_product_by_local_id(self, local_id: str) -> Optional[dict]:
        for item in self.repository.list_products():
            if str(item.get("local_id") or "") == str(local_id):
                return item
        return None

    def _product_ready_for_inventory_rpc(self, product: Mapping[str, Any]) -> bool:
        """Evita persistir un REJECTED/UNKNOWN_PRODUCT antes del push canónico."""
        if self.remote_product_ready is not None:
            return bool(self.remote_product_ready(product))
        # Transportes inyectados controlan su propia autoridad en tests/lab.
        if self.gateway is not None or self.gateway_factory is not None:
            return True
        if "sync_status" not in product:
            return True
        return normalized_text(product.get("sync_status")) == "synced"

    def _ensure_new_product(self, batch_id: str, row: Mapping[str, Any], actor: Optional[str]) -> dict:
        existing = self._get_product_by_local_id(row["producto_local_id"])
        if existing:
            return existing
        if self.product_repository is None:
            raise InventoryApplyError("No hay servicio canónico de productos configurado")
        self.repository.update_apply_row(row["row_id"], "PRODUCT_CREATING")
        product = self._producto_from_values(row["metadata_after"], stock=0)
        ok, message, product_id = self.product_repository.crear_producto(
            product,
            inventory_mode="AUTHORITATIVE",
            producto_local_id=row["producto_local_id"],
            creation_policy=PRODUCT_CREATION_STAGING,
            verified_barcode=None,
        )
        if not ok:
            raise InventoryApplyError(message)
        reread = self.product_repository.obtener_por_id(product_id)
        if not reread or str(reread.get("local_id")) != row["producto_local_id"]:
            raise ApplyVerificationError("Producto creado no coincide al releer local_id")
        if reread.get("codigo_barras"):
            raise ApplyVerificationError("Producto staging recibió barcode no autorizado")
        if reread.get("barcode_status") != "BARCODE_PENDING":
            raise ApplyVerificationError("Producto staging no quedó BARCODE_PENDING")
        self.repository.update_apply_row(
            row["row_id"], "PRODUCT_CREATED", producto_id=product_id,
            producto_local_id=row["producto_local_id"],
        )
        self.repository.append_audit(
            batch_id, "PRODUCT_CREATED", actor=actor, row_id=row["row_id"],
            producto_local_id=row["producto_local_id"],
            after={"producto_id": product_id, "barcode_status": "BARCODE_PENDING"},
        )
        return reread

    def _apply_metadata(self, batch_id: str, row: Mapping[str, Any], product: Mapping[str, Any], actor: Optional[str]) -> dict:
        if row.get("metadata_decision") != "APPLY" or row.get("metadata_before") == row.get("metadata_after"):
            return dict(product)
        if self.product_repository is None:
            raise InventoryApplyError("No hay servicio canónico para metadata")
        self.repository.update_apply_row(row["row_id"], "METADATA_APPLYING")
        target = self._producto_from_values(
            row["metadata_after"], product_id=product.get("id"),
            stock=Decimal(int(row["old_balance_scaled"])) / Decimal(1000),
        )
        ok, message = self.product_repository.actualizar_producto(
            target,
            inventory_mode="AUTHORITATIVE",
            inventory_stock_base_scaled=int(row["old_balance_scaled"]),
        )
        if not ok:
            raise InventoryApplyError(message)
        reread = self.product_repository.obtener_por_id(product.get("id"))
        self.repository.update_apply_row(row["row_id"], "METADATA_APPLIED")
        self.repository.append_audit(
            batch_id, "METADATA_APPLIED", actor=actor, row_id=row["row_id"],
            producto_local_id=row["producto_local_id"],
            before=row["metadata_before"], after=row["metadata_after"],
        )
        return reread or dict(product)

    def _submit_inventory(self, batch_id: str, row: Mapping[str, Any], actor: Optional[str]):
        if int(row["delta_scaled"]) == 0:
            return None
        operation = {
            "operation_id": row["inventory_operation_id"],
            "producto_local_id": row["producto_local_id"],
            "line_no": 1,
            "delta_scaled": int(row["delta_scaled"]),
            "expected_base_scaled": int(row["old_balance_scaled"]),
        }
        self.repository.update_apply_row(row["row_id"], "INVENTORY_SUBMITTING")
        with self.repository.connection() as conn:
            gateway = self._gateway_for(conn)
            result = gateway.submit(
                tipo="AJUSTE", operations=[operation],
                command_id=row["inventory_command_id"],
                documento_tipo=DOCUMENT_TYPE, documento_local_id=batch_id,
                device_id=None, usuario_id=None,
            )
        payload = {
            "outcome": result.outcome,
            "command_id": result.command_id,
            "reason": INVENTORY_REASON,
            "adjustment_kind": (
                "INITIAL_INVENTORY" if row["kind"] == "NEW_PRODUCT"
                else "INVENTORY_RECONCILIATION"
            ),
            "old_balance_scaled": row["old_balance_scaled"],
            "physical_count_scaled": row["physical_count_scaled"],
            "delta_scaled": row["delta_scaled"],
            "error": result.error,
        }
        self.repository.append_audit(
            batch_id, "INVENTORY_COMMAND_RESULT", actor=actor,
            row_id=row["row_id"], producto_local_id=row["producto_local_id"],
            inventory_command_id=row["inventory_command_id"], result=payload,
            error=result.error,
        )
        if result.outcome == OUTCOME_APPLIED:
            self.repository.update_apply_row(
                row["row_id"], "INVENTORY_APPLIED", apply_result_json=payload,
                applied_at=datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            )
            return result
        if result.outcome == OUTCOME_UNKNOWN:
            self.repository.update_apply_row(
                row["row_id"], "INVENTORY_UNKNOWN", apply_result_json=payload,
                last_error=result.error or "UNKNOWN",
            )
            return result
        error = result.error or "Inventario rechazado"
        if result.outcome == OUTCOME_REJECTED and "STALE_BALANCE" in error.upper():
            self.repository.update_apply_row(row["row_id"], "STALE_BALANCE", last_error=error)
            raise StaleBalanceError(error)
        self.repository.update_apply_row(row["row_id"], "FAILED_RETRYABLE", last_error=error)
        raise InventoryApplyError(error)

    def _verify_row(self, batch_id: str, row: Mapping[str, Any], actor: Optional[str]) -> None:
        self.repository.update_apply_row(row["row_id"], "VERIFYING")
        product = self._get_product_by_local_id(row["producto_local_id"])
        if product is None:
            raise ApplyVerificationError("Producto ausente en read-back")
        expected_metadata = row.get("metadata_after") or {}
        for key, expected in expected_metadata.items():
            if key in product and not _same(product.get(key), expected):
                raise ApplyVerificationError(
                    f"Metadata read-back incorrecta: {key}"
                )
        # El candidato del Excel jamás se promueve: solo se acepta pending o
        # un barcode previamente verificado fuera de este engine.
        if row["kind"] == "NEW_PRODUCT":
            if product.get("codigo_barras"):
                raise ApplyVerificationError("Barcode Excel persistido en productos")
            if product.get("barcode_status") != "BARCODE_PENDING":
                raise ApplyVerificationError("Barcode pending no verificable")
        actual, _source = self.repository.current_quantity_scaled(
            row["producto_local_id"], authority_reader=self.authority_reader
        )
        if int(actual) != int(row["physical_count_scaled"]):
            raise ApplyVerificationError(
                f"Balance read-back {actual} != {row['physical_count_scaled']}"
            )
        final_state = "NO_CHANGE_VERIFIED" if int(row["delta_scaled"]) == 0 else "VERIFIED"
        self.repository.update_apply_row(
            row["row_id"], final_state,
            verified_at=datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            apply_result_json={"verified_balance_scaled": int(actual)},
        )
        self.repository.append_audit(
            batch_id, "ROW_VERIFIED", actor=actor, row_id=row["row_id"],
            producto_local_id=row["producto_local_id"],
            inventory_command_id=row.get("inventory_command_id"),
            result={"balance_scaled": int(actual), "metadata_verified": True},
        )

    def apply_batch(self, batch_id: str, *, actor=None, lease_ttl_seconds=120) -> ApplyProgress:
        actor = self._actor(actor)
        approved = self._assert_approved_plan_current(batch_id)
        conflicts = self.final_preflight(batch_id)
        if conflicts:
            for conflict in conflicts:
                self.repository.update_apply_row(
                    conflict["row_id"], "STALE_BALANCE",
                    last_error=_canonical(conflict),
                )
            self.repository.mark_review_required(
                batch_id, _canonical(conflicts), event_type="STALE_BALANCE_PREFLIGHT",
            )
            raise StaleBalanceError("STALE_BALANCE: el plan requiere nueva aprobación")

        lease = self.repository.acquire_apply_lease(
            batch_id, ttl_seconds=lease_ttl_seconds
        )
        token = lease["lease_token"]
        plan_rows = approved["approved_plan"]["rows"]
        total = len(plan_rows)
        try:
            for index, row in enumerate(plan_rows, start=1):
                if int(self.repository.get_apply_batch(batch_id).get("stop_requested") or 0):
                    self.repository.finish_apply(
                        batch_id, token, "PARTIALLY_FAILED",
                        error="STOP_REQUESTED / NEEDS_RECONCILIATION",
                    )
                    return self.status(batch_id)
                current_rows = {item["row_id"]: item for item in self.repository.list_apply_rows(batch_id)}
                state = current_rows[row["row_id"]]["apply_state"]
                if state in ("VERIFIED", "NO_CHANGE_VERIFIED"):
                    continue
                if self.progress_callback:
                    self.progress_callback(index, total, state)
                self.repository.renew_apply_lease(
                    batch_id, token, ttl_seconds=lease_ttl_seconds
                )
                try:
                    if row["kind"] == "NEW_PRODUCT":
                        product = self._ensure_new_product(batch_id, row, actor)
                        if int(row["delta_scaled"]) and not self._product_ready_for_inventory_rpc(product):
                            message = (
                                "PRODUCT_SYNC_PENDING: producto creado localmente; "
                                "reanudar después de confirmar su alta central"
                            )
                            self.repository.update_apply_row(
                                row["row_id"], "FAILED_RETRYABLE", last_error=message
                            )
                            self.repository.append_audit(
                                batch_id, "PRODUCT_SYNC_PENDING", actor=actor,
                                row_id=row["row_id"],
                                producto_local_id=row["producto_local_id"], error=message,
                            )
                            self.repository.finish_apply(
                                batch_id, token, "PARTIALLY_FAILED", error=message
                            )
                            return self.status(batch_id)
                    else:
                        product = self._get_product_by_local_id(row["producto_local_id"])
                        if product is None:
                            raise InventoryApplyError("Producto existente desapareció")
                        product = self._apply_metadata(batch_id, row, product, actor)

                    if state not in ("INVENTORY_APPLIED", "VERIFYING"):
                        result = self._submit_inventory(batch_id, row, actor)
                        if result is not None and result.outcome == OUTCOME_UNKNOWN:
                            self.repository.finish_apply(
                                batch_id, token, "PARTIALLY_FAILED",
                                error=f"UNKNOWN command_id={row['inventory_command_id']}",
                            )
                            return self.status(batch_id)
                    self._verify_row(batch_id, row, actor)
                except StaleBalanceError:
                    self.repository.finish_apply(batch_id, token, "REVIEW_REQUIRED", error="STALE_BALANCE")
                    self.repository.mark_review_required(
                        batch_id, "STALE_BALANCE", event_type="STALE_BALANCE_REMOTE_CAS",
                    )
                    raise
                except ApplyVerificationError as exc:
                    self.repository.update_apply_row(
                        row["row_id"], "FAILED_BLOCKING", last_error=str(exc)
                    )
                    self.repository.append_audit(
                        batch_id, "VERIFY_FAILED", actor=actor, row_id=row["row_id"],
                        producto_local_id=row["producto_local_id"], error=str(exc),
                    )
                    self.repository.finish_apply(batch_id, token, "PARTIALLY_FAILED", error=str(exc))
                    return self.status(batch_id)
                except Exception as exc:
                    latest = {item["row_id"]: item for item in self.repository.list_apply_rows(batch_id)}[row["row_id"]]
                    if latest["apply_state"] not in ("INVENTORY_UNKNOWN", "FAILED_BLOCKING"):
                        self.repository.update_apply_row(
                            row["row_id"], "FAILED_RETRYABLE", last_error=str(exc)
                        )
                    self.repository.append_audit(
                        batch_id, "ROW_FAILED", actor=actor, row_id=row["row_id"],
                        producto_local_id=row.get("producto_local_id"), error=str(exc),
                    )
                    self.repository.finish_apply(batch_id, token, "PARTIALLY_FAILED", error=str(exc))
                    return self.status(batch_id)
            rows = self.repository.list_apply_rows(batch_id)
            if all(item["apply_state"] in ("VERIFIED", "NO_CHANGE_VERIFIED") for item in rows):
                self.repository.finish_apply(batch_id, token, "COMPLETED")
            else:
                self.repository.finish_apply(
                    batch_id, token, "PARTIALLY_FAILED",
                    error="Existen filas sin verificación",
                )
            return self.status(batch_id)
        except Exception:
            # Las rutas manejadas liberan el lease. Si una excepción inesperada
            # conserva APPLYING, el lease expira y Recovery UI puede reanudar.
            raise

    def status(self, batch_id: str) -> ApplyProgress:
        batch = self.repository.get_apply_batch(batch_id)
        rows = self.repository.list_apply_rows(batch_id)
        verified = sum(item["apply_state"] in ("VERIFIED", "NO_CHANGE_VERIFIED") for item in rows)
        failed = sum(item["apply_state"] in (
            "FAILED_RETRYABLE", "FAILED_BLOCKING", "STALE_BALANCE"
        ) for item in rows)
        unknown = sum(item["apply_state"] == "INVENTORY_UNKNOWN" for item in rows)
        return ApplyProgress(
            batch_id=batch_id, apply_id=batch.get("apply_id") or "",
            state=batch["workflow_state"], processed=verified + failed + unknown,
            total=len(rows), verified=verified, failed=failed, unknown=unknown,
        )

    def cancel_batch(self, batch_id: str, *, actor=None) -> None:
        self.repository.cancel_batch(batch_id, actor=self._actor(actor))

    def request_stop(self, batch_id: str, *, actor=None) -> None:
        self.repository.request_stop(batch_id, actor=self._actor(actor))
