# -*- coding: utf-8 -*-
"""Orquestación de doble scan, persistencia y read-back obligatorio."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from barcode_scanner import BarcodeDoubleScanVerifier, DoubleScanState
from repositories.product_barcodes_repo import (
    BARCODE_TYPE_MANUFACTURER,
    SOURCE_HID_DOUBLE_SCAN,
    BarcodeRepositoryError,
    ProductBarcodesRepository,
)


class BarcodeSaveState(str, Enum):
    SCANNED = "SCANNED"
    VERIFIED = "VERIFIED"
    PERSISTED = "PERSISTED"
    PERSISTENCE_VERIFIED = "PERSISTENCE_VERIFIED"
    MISMATCH = "MISMATCH"
    ERROR = "ERROR"


@dataclass(frozen=True)
class BarcodeSaveResult:
    state: BarcodeSaveState
    message: str
    barcode: Optional[str] = None
    barcode_local_id: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.state == BarcodeSaveState.PERSISTENCE_VERIFIED


class BarcodeAssignmentSession:
    """Una sesión asigna como máximo un barcode confirmado a un producto."""

    def __init__(
        self,
        repository: ProductBarcodesRepository,
        producto_local_id: str,
        *,
        barcode_type: str = BARCODE_TYPE_MANUFACTURER,
        source: str = SOURCE_HID_DOUBLE_SCAN,
        is_primary: Optional[bool] = None,
        package_role: str = "BASE_UNIT",
    ) -> None:
        self.repository = repository
        self.producto_local_id = producto_local_id
        self.barcode_type = barcode_type
        self.source = source
        self.is_primary = is_primary
        self.package_role = package_role
        self.verifier = BarcodeDoubleScanVerifier()
        self.state: Optional[BarcodeSaveState] = None

    def reset(self) -> None:
        self.verifier.reset()
        self.state = None

    def submit_scan(self, raw: str) -> BarcodeSaveResult:
        verification = self.verifier.submit_scan(raw)
        if verification.state == DoubleScanState.WAITING_CONFIRMATION:
            self.state = BarcodeSaveState.SCANNED
            return BarcodeSaveResult(
                BarcodeSaveState.SCANNED,
                verification.message,
                verification.barcode,
            )
        if verification.state == DoubleScanState.MISMATCH:
            self.state = BarcodeSaveState.MISMATCH
            return BarcodeSaveResult(
                BarcodeSaveState.MISMATCH,
                "CÓDIGOS NO COINCIDEN",
            )
        if verification.state != DoubleScanState.VERIFIED:
            self.state = BarcodeSaveState.ERROR
            return BarcodeSaveResult(
                BarcodeSaveState.ERROR,
                verification.message,
            )

        barcode = verification.barcode
        self.state = BarcodeSaveState.VERIFIED
        try:
            record = self.repository.assign_barcode(
                producto_local_id=self.producto_local_id,
                barcode=barcode,
                barcode_type=self.barcode_type,
                source=self.source,
                is_primary=self.is_primary,
                package_role=self.package_role,
            )
        except BarcodeRepositoryError as exc:
            self.state = BarcodeSaveState.ERROR
            return BarcodeSaveResult(BarcodeSaveState.ERROR, str(exc), barcode)
        except Exception as exc:
            self.state = BarcodeSaveState.ERROR
            return BarcodeSaveResult(
                BarcodeSaveState.ERROR,
                f"Error al persistir barcode: {exc}",
                barcode,
            )

        self.state = BarcodeSaveState.PERSISTED
        # assign_barcode ya hizo un read-back; se relee otra vez desde el
        # contrato público para que el estado final dependa inequívocamente de DB.
        persisted = self.repository.get_by_local_id(record.local_id)
        if persisted is None or persisted.barcode != barcode:
            self.state = BarcodeSaveState.ERROR
            return BarcodeSaveResult(
                BarcodeSaveState.ERROR,
                "ERROR: la relectura de DB no coincide con el código confirmado",
                barcode,
                record.local_id,
            )
        self.state = BarcodeSaveState.PERSISTENCE_VERIFIED
        return BarcodeSaveResult(
            BarcodeSaveState.PERSISTENCE_VERIFIED,
            "CÓDIGO GUARDADO Y VERIFICADO",
            barcode,
            record.local_id,
        )
