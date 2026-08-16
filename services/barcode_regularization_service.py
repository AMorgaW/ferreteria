# -*- coding: utf-8 -*-
"""Flujo operacional de regularización de barcodes (Fase 2F).

Incluye:

- ``ScannerTrialSession``: modo PRUEBA DE SCANNER. No recibe repository ni
  conexión; es estructuralmente imposible que escriba en la base de datos.
- ``ContinuousRegularizationController``: modo REGULARIZACIÓN CONTINUA.
  Producto pendiente → doble scan → persistir → read-back → éxito → siguiente
  pendiente. Un fallo (mismatch, duplicado, error DB, read-back) nunca avanza.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, List, Optional

from barcode_scanner import HidBarcodeScanner, normalize_barcode, BarcodeScanError
from repositories.barcode_queue_repo import (
    FILTER_ALL,
    BarcodeQueueItem,
    BarcodeQueueRepository,
    QUEUE_STATUS_LEGACY,
    QUEUE_STATUS_PENDING,
)
from repositories.product_barcodes_repo import (
    BARCODE_TYPE_INTERNAL_FRP,
    PACKAGE_ROLE_BASE_UNIT,
    PACKAGE_ROLES,
    SOURCE_EXPLICIT_FRP,
    BarcodeRecord,
    BarcodeRepositoryError,
    FrpBarcodeGenerator,
    ProductBarcodesRepository,
)
from services.barcode_service import (
    BarcodeAssignmentSession,
    BarcodeSaveResult,
    BarcodeSaveState,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Modo prueba de scanner (nunca persiste)
# ---------------------------------------------------------------------------


class ScannerTrialState(str, Enum):
    WAITING_FIRST_SCAN = "WAITING_FIRST_SCAN"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    ERROR = "ERROR"


@dataclass(frozen=True)
class ScannerTrialResult:
    state: ScannerTrialState
    message: str
    barcode: Optional[str] = None
    length: int = 0
    terminator: Optional[str] = None
    match: Optional[bool] = None


class ScannerTrialSession:
    """Doble escaneo de diagnóstico para el DIG-X6266.

    Deliberadamente no acepta repository, db_manager ni conexión: 0 INSERT,
    0 UPDATE y 0 cambios en ``product_barcodes`` aunque ambos scans coincidan.
    """

    def __init__(self) -> None:
        self.hid = HidBarcodeScanner()
        self.state = ScannerTrialState.WAITING_FIRST_SCAN
        self.first_barcode: Optional[str] = None
        self.first_terminator: Optional[str] = None
        self.second_terminator: Optional[str] = None

    def reset(self) -> None:
        self.hid.reset()
        self.state = ScannerTrialState.WAITING_FIRST_SCAN
        self.first_barcode = None
        self.first_terminator = None
        self.second_terminator = None

    def feed_key(self, key: str) -> Optional[ScannerTrialResult]:
        event = self.hid.feed_key(key)
        if event is None:
            return None
        terminator = self.hid.last_terminator
        if event.error:
            return ScannerTrialResult(
                ScannerTrialState.ERROR,
                event.error,
                terminator=terminator,
            )
        barcode = event.barcode
        if self.state == ScannerTrialState.WAITING_FIRST_SCAN or self.first_barcode is None:
            self.first_barcode = barcode
            self.first_terminator = terminator
            self.state = ScannerTrialState.WAITING_CONFIRMATION
            return ScannerTrialResult(
                ScannerTrialState.WAITING_CONFIRMATION,
                "Primer scan recibido; escanee nuevamente",
                barcode,
                len(barcode),
                terminator,
            )
        self.second_terminator = terminator
        if barcode == self.first_barcode:
            self.state = ScannerTrialState.MATCH
            return ScannerTrialResult(
                ScannerTrialState.MATCH,
                "MATCH: ambos códigos coinciden (no se guardó nada)",
                barcode,
                len(barcode),
                terminator,
                match=True,
            )
        self.state = ScannerTrialState.MISMATCH
        result = ScannerTrialResult(
            ScannerTrialState.MISMATCH,
            "MISMATCH: los códigos no coinciden (no se guardó nada)",
            barcode,
            len(barcode),
            terminator,
            match=False,
        )
        # La siguiente prueba arranca limpia; el resultado ya fue entregado.
        self.first_barcode = None
        self.first_terminator = None
        self.state = ScannerTrialState.WAITING_FIRST_SCAN
        return result

    def feed_text(self, text: str) -> List[ScannerTrialResult]:
        results = []
        for char in text:
            result = self.feed_key(char)
            if result is not None:
                results.append(result)
        # ``HidBarcodeScanner`` reconoce CRLF al consumir el LF posterior. El
        # resultado del CR ya fue emitido, por lo que se corrige aquí solo la
        # metadata diagnóstica; el barcode nunca se vuelve a procesar.
        if (
            results
            and results[-1].terminator == "CR"
            and self.hid.last_terminator == "CRLF"
        ):
            results[-1] = replace(results[-1], terminator="CRLF")
            if len(results) == 1 and self.state == ScannerTrialState.WAITING_CONFIRMATION:
                self.first_terminator = "CRLF"
            else:
                self.second_terminator = "CRLF"
        return results


# ---------------------------------------------------------------------------
# Modo continuo de regularización
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegularizationStepResult:
    """Resultado de un scan/confirmación dentro del modo continuo."""

    save_result: BarcodeSaveResult
    excel_candidate_match: Optional[bool] = None
    advanced: bool = False
    completed_producto_local_id: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.save_result.success


class ContinuousRegularizationController:
    """Orquesta la cola y el doble scan sin depender de Qt."""

    def __init__(
        self,
        queue_repository: BarcodeQueueRepository,
        barcode_repository: ProductBarcodesRepository,
        *,
        audit_hook: Optional[Callable[[dict], None]] = None,
        actor: Optional[str] = None,
        queue_filter: str = FILTER_ALL,
        search: str = "",
    ) -> None:
        self.queue_repository = queue_repository
        self.barcode_repository = barcode_repository
        self.audit_hook = audit_hook
        self.actor = actor
        self.queue_filter = queue_filter
        self.search = search
        self.queue: List[BarcodeQueueItem] = []
        self.current_item: Optional[BarcodeQueueItem] = None
        self.current_session: Optional[BarcodeAssignmentSession] = None
        self._pending_frp: Optional[str] = None

    # ------------------------------------------------------------------
    # Cola y selección
    # ------------------------------------------------------------------
    def refresh_queue(self) -> List[BarcodeQueueItem]:
        self.queue = self.queue_repository.list_queue(self.queue_filter, self.search)
        return self.queue

    def select(self, key: str, *, package_role: str = PACKAGE_ROLE_BASE_UNIT) -> bool:
        """Selecciona un producto de la cola y arma su sesión de doble scan."""
        if package_role not in PACKAGE_ROLES:
            raise BarcodeRepositoryError(f"package_role inválido: {package_role}")
        item = next((entry for entry in self.queue if entry.key == key), None)
        if item is None or not item.selectable:
            return False
        self.current_item = item
        self.current_session = BarcodeAssignmentSession(
            self.barcode_repository,
            item.producto_local_id,
            package_role=package_role,
        )
        self._pending_frp = None
        return True

    def begin_additional_barcode(self, *, package_role: str = PACKAGE_ROLE_BASE_UNIT) -> bool:
        """AGREGAR BARCODE ADICIONAL: misma exigencia de doble scan."""
        if self.current_item is None or not self.current_item.selectable:
            return False
        return self.select(self.current_item.key, package_role=package_role)

    # ------------------------------------------------------------------
    # Doble scan operacional
    # ------------------------------------------------------------------
    def submit_scan(self, raw: str) -> RegularizationStepResult:
        if self.current_session is None or self.current_item is None:
            return RegularizationStepResult(
                BarcodeSaveResult(
                    BarcodeSaveState.ERROR,
                    "Seleccione un producto pendiente antes de escanear",
                )
            )

        excel_match: Optional[bool] = None
        if self.current_session.verifier.first_scan is None:
            try:
                scanned = normalize_barcode(raw)
            except BarcodeScanError:
                scanned = None
            candidate = self.current_item.excel_candidate
            if scanned is not None and candidate:
                # El candidate Excel es solo referencia; jamás se auto-verifica.
                excel_match = scanned == candidate

        result = self.current_session.submit_scan(raw)
        if result.success:
            completed = self.current_item
            self._audit(result, completed, resultado="PERSISTENCE_VERIFIED")
            self.refresh_queue()
            self._advance_to_next_pending(exclude=completed.producto_local_id)
            return RegularizationStepResult(
                result,
                excel_candidate_match=excel_match,
                advanced=True,
                completed_producto_local_id=completed.producto_local_id,
            )

        if result.state in (BarcodeSaveState.MISMATCH, BarcodeSaveState.ERROR):
            # Seguridad del modo continuo: no avanzar; el producto queda
            # seleccionado y el buffer vuelve a WAITING_FIRST_SCAN.
            self.current_session.reset()
            self._pending_frp = None
        return RegularizationStepResult(
            result, excel_candidate_match=excel_match, advanced=False
        )

    def _advance_to_next_pending(self, *, exclude: Optional[str]) -> None:
        """Solo se llama tras PERSISTENCE_VERIFIED; nunca antes del read-back."""
        self.current_session = None
        self.current_item = None
        for item in self.queue:
            if not item.selectable or item.producto_local_id == exclude:
                continue
            if item.barcode_status in (QUEUE_STATUS_PENDING, QUEUE_STATUS_LEGACY):
                self.select(item.key)
                return

    # ------------------------------------------------------------------
    # FRP explícito: generar → confirmar → persistir → read-back
    # ------------------------------------------------------------------
    def generate_frp_candidate(self, *, token_hex=None) -> str:
        """Propone un FRP sin persistirlo. Nunca se invoca automáticamente."""
        if self.current_item is None or not self.current_item.selectable:
            raise BarcodeRepositoryError(
                "Seleccione un producto antes de generar un código FERREPRO"
            )
        generator = FrpBarcodeGenerator(
            self.barcode_repository.barcode_exists,
            **({"token_hex": token_hex} if token_hex is not None else {}),
        )
        self._pending_frp = generator.generate()
        return self._pending_frp

    def confirm_frp(self) -> RegularizationStepResult:
        """CONFIRMAR Y GUARDAR el FRP propuesto; éxito solo tras read-back."""
        if self.current_item is None or not self.current_item.selectable:
            return RegularizationStepResult(
                BarcodeSaveResult(
                    BarcodeSaveState.ERROR,
                    "Seleccione un producto antes de confirmar el FRP",
                )
            )
        candidate = self._pending_frp
        if not candidate:
            return RegularizationStepResult(
                BarcodeSaveResult(
                    BarcodeSaveState.ERROR,
                    "Genere primero el código FERREPRO; no hay FRP pendiente",
                )
            )
        try:
            record = self.barcode_repository.assign_barcode(
                producto_local_id=self.current_item.producto_local_id,
                barcode=candidate,
                barcode_type=BARCODE_TYPE_INTERNAL_FRP,
                source=SOURCE_EXPLICIT_FRP,
                package_role=(
                    self.current_session.package_role
                    if self.current_session is not None
                    else PACKAGE_ROLE_BASE_UNIT
                ),
            )
        except BarcodeRepositoryError as exc:
            self._pending_frp = None
            return RegularizationStepResult(
                BarcodeSaveResult(BarcodeSaveState.ERROR, str(exc), candidate)
            )
        except Exception as exc:
            self._pending_frp = None
            return RegularizationStepResult(
                BarcodeSaveResult(
                    BarcodeSaveState.ERROR,
                    f"Error al persistir FRP: {exc}",
                    candidate,
                )
            )

        persisted = self.barcode_repository.get_by_local_id(record.local_id)
        if persisted is None or persisted.barcode != candidate:
            self._pending_frp = None
            return RegularizationStepResult(
                BarcodeSaveResult(
                    BarcodeSaveState.ERROR,
                    "ERROR: la relectura de DB no coincide con el FRP confirmado",
                    candidate,
                    record.local_id,
                )
            )
        self._pending_frp = None
        result = BarcodeSaveResult(
            BarcodeSaveState.PERSISTENCE_VERIFIED,
            "CÓDIGO GUARDADO Y VERIFICADO",
            candidate,
            record.local_id,
        )
        completed = self.current_item
        self._audit(result, completed, resultado="PERSISTENCE_VERIFIED")
        self.refresh_queue()
        self._advance_to_next_pending(exclude=completed.producto_local_id)
        return RegularizationStepResult(
            result,
            advanced=True,
            completed_producto_local_id=completed.producto_local_id,
        )

    # ------------------------------------------------------------------
    # Barcode principal
    # ------------------------------------------------------------------
    def mark_primary(self, barcode_local_id: str) -> BarcodeRecord:
        """MARCAR COMO PRINCIPAL; el repo garantiza máximo 1 PRIMARY activo."""
        record = self.barcode_repository.set_primary(barcode_local_id)
        self._audit_record(
            record,
            resultado="PRIMARY_SET",
        )
        self.refresh_queue()
        return record

    # ------------------------------------------------------------------
    # Auditoría (infraestructura existente vía hook)
    # ------------------------------------------------------------------
    def _audit(
        self,
        result: BarcodeSaveResult,
        item: Optional[BarcodeQueueItem],
        *,
        resultado: str,
    ) -> None:
        if self.audit_hook is None:
            return
        payload = {
            "producto_local_id": item.producto_local_id if item else None,
            "barcode_local_id": result.barcode_local_id,
            "barcode": result.barcode,
            "source": (
                self.current_session.source
                if self.current_session is not None
                else SOURCE_EXPLICIT_FRP
            ),
            "actor": self.actor,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "resultado": resultado,
        }
        try:
            self.audit_hook(payload)
        except Exception:
            logger.exception("No se pudo registrar auditoría de barcode")

    def _audit_record(self, record: BarcodeRecord, *, resultado: str) -> None:
        if self.audit_hook is None:
            return
        try:
            self.audit_hook(
                {
                    "producto_local_id": record.producto_local_id,
                    "barcode_local_id": record.local_id,
                    "barcode": record.barcode,
                    "source": record.source,
                    "actor": self.actor,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "resultado": resultado,
                }
            )
        except Exception:
            logger.exception("No se pudo registrar auditoría de barcode")
