# -*- coding: utf-8 -*-
"""Captura HID y verificación de doble escaneo para códigos de barras.

El módulo no depende de Qt ni de la base de datos. El scanner DIG-X6266 se
trata como *keyboard wedge*: entrega caracteres y finaliza con CR/LF/ENTER.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple


class BarcodeScanError(ValueError):
    """Entrada del scanner inválida; nunca debe llegar a persistencia."""


def normalize_barcode(raw: str) -> str:
    """Quita solo terminadores y whitespace exterior permitido.

    No convierte a número, no cambia mayúsculas/minúsculas y no toca el
    contenido interno. Así se conservan ceros iniciales y códigos case-sensitive.
    """
    if not isinstance(raw, str):
        raise BarcodeScanError("El código debe recibirse como texto")
    value = raw.strip(" \t\r\n")
    if not value:
        raise BarcodeScanError("Escaneo vacío")
    return value


@dataclass(frozen=True)
class HidScanEvent:
    barcode: Optional[str] = None
    error: Optional[str] = None

    @property
    def completed(self) -> bool:
        return self.barcode is not None


class HidBarcodeScanner:
    """Acumula teclas hasta ENTER/CR/LF y emite el código completo."""

    TERMINATORS = {"\r", "\n", "ENTER", "RETURN"}

    def __init__(self) -> None:
        self._buffer: List[str] = []
        self._just_emitted = False
        self.last_terminator: Optional[str] = None

    @property
    def buffered_text(self) -> str:
        return "".join(self._buffer)

    def reset(self) -> None:
        self._buffer.clear()
        self._just_emitted = False
        self.last_terminator = None

    @staticmethod
    def _terminator_name(key: str) -> str:
        if key == "\r":
            return "CR"
        if key == "\n":
            return "LF"
        return "ENTER"

    def feed_key(self, key: str) -> Optional[HidScanEvent]:
        if key in self.TERMINATORS:
            if not self._buffer:
                # Un lector puede enviar CRLF. El LF posterior al CR no es un
                # segundo escaneo vacío; un ENTER inicial sí se rechaza.
                if self._just_emitted:
                    self._just_emitted = False
                    if key == "\n" and self.last_terminator == "CR":
                        self.last_terminator = "CRLF"
                    return None
                self.last_terminator = self._terminator_name(key)
                return HidScanEvent(error="Escaneo vacío")
            raw = "".join(self._buffer)
            self._buffer.clear()
            try:
                barcode = normalize_barcode(raw)
            except BarcodeScanError as exc:
                self._just_emitted = False
                return HidScanEvent(error=str(exc))
            self._just_emitted = True
            self.last_terminator = self._terminator_name(key)
            return HidScanEvent(barcode=barcode)

        if not isinstance(key, str):
            return HidScanEvent(error="Tecla HID inválida")
        self._just_emitted = False
        self._buffer.append(key)
        return None

    def feed_text(self, text: str) -> Tuple[HidScanEvent, ...]:
        """Simula una secuencia HID completa, carácter por carácter."""
        events = []
        for char in text:
            event = self.feed_key(char)
            if event is not None:
                events.append(event)
        return tuple(events)


class DoubleScanState(str, Enum):
    WAITING_FIRST_SCAN = "WAITING_FIRST_SCAN"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    VERIFIED = "VERIFIED"
    MISMATCH = "MISMATCH"
    ERROR = "ERROR"


@dataclass(frozen=True)
class DoubleScanResult:
    state: DoubleScanState
    message: str
    barcode: Optional[str] = None


class BarcodeDoubleScanVerifier:
    """Máquina de estados reusable; un mismatch jamás conserva intentos."""

    def __init__(self) -> None:
        self.state = DoubleScanState.WAITING_FIRST_SCAN
        self.first_scan: Optional[str] = None
        self.verified_barcode: Optional[str] = None

    def reset(self) -> None:
        self.state = DoubleScanState.WAITING_FIRST_SCAN
        self.first_scan = None
        self.verified_barcode = None

    def submit_scan(self, raw: str) -> DoubleScanResult:
        try:
            barcode = normalize_barcode(raw)
        except BarcodeScanError as exc:
            self.state = DoubleScanState.ERROR
            result = DoubleScanResult(DoubleScanState.ERROR, str(exc))
            self.reset()
            return result

        if self.state == DoubleScanState.WAITING_FIRST_SCAN:
            self.first_scan = barcode
            self.state = DoubleScanState.WAITING_CONFIRMATION
            return DoubleScanResult(
                self.state,
                "Escanee nuevamente para verificar",
                barcode,
            )

        if self.state == DoubleScanState.WAITING_CONFIRMATION:
            if barcode == self.first_scan:
                self.verified_barcode = barcode
                self.state = DoubleScanState.VERIFIED
                return DoubleScanResult(
                    self.state, "CÓDIGO VERIFICADO", barcode
                )
            result = DoubleScanResult(
                DoubleScanState.MISMATCH,
                "CÓDIGOS NO COINCIDEN",
            )
            # El resultado conserva MISMATCH para UI/tests, pero la máquina ya
            # está lista para que el tercer scan sea un nuevo primer intento.
            self.reset()
            return result

        return DoubleScanResult(
            DoubleScanState.ERROR,
            "Reinicie la verificación antes de escanear otro código",
        )

