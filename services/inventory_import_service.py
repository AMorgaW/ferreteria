# -*- coding: utf-8 -*-
"""Orquestación de staging, matching y dry-run para inventario físico."""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Optional

from inventory_excel_importer import ImportIssue, InventoryExcelImporter
from product_inventory_contract import normalized_text
from repositories.inventory_import_repository import (
    InventoryImportRepository,
    StagedBatch,
)


@dataclass(frozen=True)
class ImportPreviewResult:
    batch: StagedBatch
    rows: tuple[dict, ...]


@dataclass(frozen=True)
class InventoryImportApplyPlan:
    batch_id: str
    new_products: tuple[dict, ...] = ()
    metadata_updates: tuple[dict, ...] = ()
    inventory_adjustments: tuple[dict, ...] = ()
    barcode_candidates: tuple[dict, ...] = ()
    blocked_rows: tuple[dict, ...] = ()
    positive_adjustments: int = 0
    negative_adjustments: int = 0
    unchanged: int = 0
    authority_sources: tuple[str, ...] = ()

    @property
    def summary(self) -> dict[str, int]:
        return {
            "new_products": len(self.new_products),
            "existing_products": len(self.inventory_adjustments),
            "metadata_updates": len(self.metadata_updates),
            "positive_adjustments": self.positive_adjustments,
            "negative_adjustments": self.negative_adjustments,
            "unchanged": self.unchanged,
            "barcode_pending": sum(1 for item in self.barcode_candidates if item["status"] == "BARCODE_PENDING"),
            "barcode_candidates": sum(1 for item in self.barcode_candidates if item["status"] == "BARCODE_EXCEL_CANDIDATE"),
            "blocking_rows": len(self.blocked_rows),
        }


class InventoryImportService:
    def __init__(
        self,
        repository: InventoryImportRepository,
        *,
        importer: Optional[InventoryExcelImporter] = None,
        authority_reader=None,
    ) -> None:
        self.repository = repository
        self.importer = importer or InventoryExcelImporter()
        self.authority_reader = authority_reader

    @staticmethod
    def _identity(values: dict) -> tuple[str, str, str, str]:
        return tuple(
            normalized_text(values.get(key))
            for key in ("nombre", "marca", "presentacion_empaque", "categoria")
        )

    @staticmethod
    def _product_identity(product: dict) -> tuple[str, str, str, str]:
        return tuple(
            normalized_text(product.get(key))
            for key in ("nombre", "marca", "presentacion", "categoria")
        )

    def _match_rows(self, parsed) -> list[dict]:
        products = self.repository.list_products()
        products_by_local = {
            str(product.get("local_id")): product
            for product in products if product.get("local_id")
        }
        strong: dict[tuple[str, str, str, str], list[dict]] = {}
        for product in products:
            strong.setdefault(self._product_identity(product), []).append(product)
        barcode_owners = self.repository.verified_barcode_owners()
        result = []
        for row in parsed.rows:
            if row.errors:
                result.append({
                    "row": row,
                    "match_status": "INVALID",
                    "matched_producto_local_id": None,
                    "matched_product_name": None,
                    "barcode_status": row.barcode_status,
                })
                continue
            identity_matches = strong.get(self._identity(row.values), [])
            barcode_owner = barcode_owners.get(row.barcode_candidate or "")
            if barcode_owner:
                owner_id = str(barcode_owner.get("producto_local_id") or "")
                conflicting = [
                    item for item in identity_matches
                    if str(item.get("local_id") or "") != owner_id
                ]
                if conflicting:
                    row.errors.append(ImportIssue(
                        "ERROR", "CONFLICT_BARCODE_PRODUCT", "barcode_primero",
                        "Barcode existente y datos fuertes señalan productos diferentes",
                    ))
                    row.validation_status = "ERROR"
                    result.append({
                        "row": row,
                        "match_status": "AMBIGUOUS",
                        "matched_producto_local_id": None,
                        "matched_product_name": None,
                        "barcode_status": "CONFLICT_BARCODE_PRODUCT",
                    })
                    continue
                owner = products_by_local.get(owner_id, barcode_owner)
                result.append({
                    "row": row,
                    "match_status": "MATCH_EXACT",
                    "matched_producto_local_id": owner_id,
                    "matched_product_name": owner.get("nombre") or barcode_owner.get("nombre"),
                    "barcode_status": row.barcode_status,
                })
                continue
            if len(identity_matches) == 1:
                product = identity_matches[0]
                result.append({
                    "row": row,
                    "match_status": "MATCH_EXACT",
                    "matched_producto_local_id": product.get("local_id"),
                    "matched_product_name": product.get("nombre"),
                    "barcode_status": row.barcode_status,
                })
                continue
            if len(identity_matches) > 1:
                result.append({
                    "row": row,
                    "match_status": "AMBIGUOUS",
                    "matched_producto_local_id": None,
                    "matched_product_name": None,
                    "barcode_status": row.barcode_status,
                })
                continue
            name = normalized_text(row.values.get("nombre"))
            scored = sorted(
                [
                    (
                    SequenceMatcher(None, name, normalized_text(product.get("nombre"))).ratio(),
                    product,
                    )
                    for product in products if name and product.get("nombre")
                ],
                key=lambda item: item[0],
            )
            scored.reverse()
            if scored and scored[0][0] >= 0.80:
                product = scored[0][1]
                result.append({
                    "row": row,
                    "match_status": "MATCH_CANDIDATE",
                    "matched_producto_local_id": product.get("local_id"),
                    "matched_product_name": product.get("nombre"),
                    "barcode_status": row.barcode_status,
                })
            else:
                result.append({
                    "row": row,
                    "match_status": "NEW_PRODUCT",
                    "matched_producto_local_id": None,
                    "matched_product_name": None,
                    "barcode_status": row.barcode_status,
                })
        return result

    def import_to_staging(self, source) -> ImportPreviewResult:
        parsed = self.importer.parse(source)
        existing = self.repository.find_batch_by_sha(parsed.source_sha256)
        if existing:
            return ImportPreviewResult(existing, tuple(self.repository.list_rows(existing.batch_id)))
        matched = self._match_rows(parsed)
        batch = self.repository.persist(parsed, matched)
        return ImportPreviewResult(batch, tuple(self.repository.list_rows(batch.batch_id)))

    def preview(self, batch_id: str) -> ImportPreviewResult:
        rows = self.repository.list_rows(batch_id)
        if not rows:
            raise ValueError("Batch inexistente o sin filas")
        # El caller normalmente ya conserva el batch de import_to_staging; para
        # preview directo solo se requiere la colección durable de filas.
        batch = StagedBatch(batch_id, "", "", "READY", len(rows), 0, 0, 0)
        return ImportPreviewResult(batch, tuple(rows))

    def build_apply_plan(self, batch_id: str) -> InventoryImportApplyPlan:
        rows = self.repository.list_rows(batch_id)
        products = {
            str(item.get("local_id")): item for item in self.repository.list_products()
            if item.get("local_id")
        }
        new_products: list[dict] = []
        metadata_updates: list[dict] = []
        adjustments: list[dict] = []
        barcodes: list[dict] = []
        blocked: list[dict] = []
        authority_sources: set[str] = set()
        positive = negative = unchanged = 0

        for row in rows:
            payload = row["normalized_payload"]
            barcodes.append({
                "excel_row_number": row["excel_row_number"],
                "status": row["barcode_status"],
                "candidate": row.get("barcode_candidate"),
            })
            if row["validation_status"] == "ERROR" or row["match_status"] in ("INVALID", "AMBIGUOUS", "MATCH_CANDIDATE"):
                blocked.append({
                    "excel_row_number": row["excel_row_number"],
                    "reason": row["match_status"] if row["validation_status"] != "ERROR" else "VALIDATION_ERROR",
                })
                continue
            counted = row.get("cantidad_contada_scaled")
            if counted is None:
                blocked.append({"excel_row_number": row["excel_row_number"], "reason": "COUNT_UNAVAILABLE"})
                continue
            if row["match_status"] == "NEW_PRODUCT":
                new_products.append({
                    "excel_row_number": row["excel_row_number"],
                    "action": "PROPOSE_CREATE_PRODUCT",
                    "product": payload,
                    "initial_balance_scaled": int(counted),
                    "balance_action": "PROPOSE_INITIAL_BALANCE",
                    "producto_local_id": None,
                })
                continue
            local_id = str(row.get("matched_producto_local_id") or "")
            current, source = self.repository.current_quantity_scaled(
                local_id, authority_reader=self.authority_reader
            )
            authority_sources.add(source)
            delta = int(counted) - int(current)
            if delta > 0:
                positive += 1
            elif delta < 0:
                negative += 1
            else:
                unchanged += 1
            adjustments.append({
                "excel_row_number": row["excel_row_number"],
                "action": "PROPOSE_INVENTORY_ADJUSTMENT",
                "producto_local_id": local_id,
                "current_quantity_scaled": int(current),
                "counted_quantity_scaled": int(counted),
                "delta_scaled": delta,
                "authority_source": source,
            })
            product = products.get(local_id, {})
            changes = {}
            for source_key, product_key in (
                ("categoria", "categoria"), ("marca", "marca"),
                ("presentacion_empaque", "presentacion"),
                ("unidad_base", "unidad_medida"),
            ):
                proposed = payload.get(source_key) or ""
                current_value = product.get(product_key) or ""
                if normalized_text(proposed) != normalized_text(current_value):
                    changes[product_key] = {"current": current_value, "proposed": proposed}
            if changes:
                metadata_updates.append({
                    "excel_row_number": row["excel_row_number"],
                    "producto_local_id": local_id,
                    "changes": changes,
                })

        return InventoryImportApplyPlan(
            batch_id=batch_id,
            new_products=tuple(new_products),
            metadata_updates=tuple(metadata_updates),
            inventory_adjustments=tuple(adjustments),
            barcode_candidates=tuple(barcodes),
            blocked_rows=tuple(blocked),
            positive_adjustments=positive,
            negative_adjustments=negative,
            unchanged=unchanged,
            authority_sources=tuple(sorted(authority_sources)),
        )

    def dry_run(self, batch_id: str) -> InventoryImportApplyPlan:
        """Alias explícito: construir el plan no realiza INSERT/UPDATE/DELETE."""
        return self.build_apply_plan(batch_id)
