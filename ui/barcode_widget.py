# -*- coding: utf-8 -*-
"""Componente visual compacto para doble escaneo HID en Productos."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from barcode_scanner import (
    BarcodeDoubleScanVerifier,
    DoubleScanState,
    HidBarcodeScanner,
)
from repositories.product_barcodes_repo import (
    BARCODE_TYPE_INTERNAL_FRP,
    BARCODE_TYPE_MANUFACTURER,
    SOURCE_EXPLICIT_FRP,
    SOURCE_HID_DOUBLE_SCAN,
    FrpBarcodeGenerator,
)
from ui_config import COLORS, FONTS, make_font


class BarcodeCaptureWidget(QFrame):
    """Captura un barcode nuevo; guardar/persistir corresponde al formulario."""

    barcodeVerified = Signal(str)

    def __init__(self, barcode_repository, *, existing_barcodes=(), parent=None):
        super().__init__(parent)
        self.repository = barcode_repository
        self.hid = HidBarcodeScanner()
        self.verifier = BarcodeDoubleScanVerifier()
        self._verified_barcode = None
        self._barcode_type = BARCODE_TYPE_MANUFACTURER
        self._source = SOURCE_HID_DOUBLE_SCAN
        self._pending_frp = None
        self._build_ui(existing_barcodes)

    @property
    def verified_barcode(self):
        return self._verified_barcode

    @property
    def barcode_type(self):
        return self._barcode_type

    @property
    def source(self):
        return self._source

    def _build_ui(self, existing_barcodes):
        self.setStyleSheet(
            "QFrame { background: white; border: 1px solid #dbe3ee; "
            "border-radius: 8px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(7)

        title = QLabel("▥ Código de barras")
        title.setFont(make_font(FONTS["body_bold"]))
        title.setStyleSheet(f"color: {COLORS['primary']}; border: none;")
        layout.addWidget(title)

        self.status_label = QLabel("ESTADO: Esperando primer escaneo")
        self.status_label.setFont(make_font(FONTS["small"]))
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; border: none;"
        )
        layout.addWidget(self.status_label)

        self.first_label = QLabel("Primer código: —")
        self.first_label.setFont(make_font(FONTS["small"]))
        self.first_label.setStyleSheet(
            f"color: {COLORS['text_body']}; border: none;"
        )
        layout.addWidget(self.first_label)

        self.scan_input = QLineEdit()
        self.scan_input.setPlaceholderText("Escanee aquí (el lector envía ENTER)")
        self.scan_input.setFont(make_font(FONTS["body"]))
        self.scan_input.setMinimumHeight(38)
        self.scan_input.setStyleSheet(
            f"QLineEdit {{ border: 2px solid {COLORS['primary_border']}; "
            "border-radius: 7px; padding: 7px; background: #f8fafc; }}"
            f"QLineEdit:focus {{ border-color: {COLORS['accent']}; }}"
        )
        self.scan_input.returnPressed.connect(self._capture_line)
        layout.addWidget(self.scan_input)

        action_row = QHBoxLayout()
        self.frp_button = QPushButton("Generar FRP explícitamente")
        self.frp_button.setCursor(Qt.PointingHandCursor)
        self.frp_button.setStyleSheet(
            f"QPushButton {{ background: {COLORS['primary']}; color: white; "
            "border: none; border-radius: 6px; padding: 7px 10px; }}"
            f"QPushButton:hover {{ background: {COLORS['secondary_dark']}; }}"
        )
        self.frp_button.clicked.connect(self._generate_or_confirm_frp)
        action_row.addWidget(self.frp_button)

        reset_button = QPushButton("Reiniciar")
        reset_button.setCursor(Qt.PointingHandCursor)
        reset_button.setStyleSheet(
            "QPushButton { background: #f8fafc; color: #475569; "
            "border: 1px solid #cbd5e1; border-radius: 6px; padding: 7px 10px; }"
        )
        reset_button.clicked.connect(self.reset)
        action_row.addWidget(reset_button)
        layout.addLayout(action_row)

        values = []
        for record in existing_barcodes:
            suffix = " · PRIMARY" if getattr(record, "is_primary", False) else ""
            values.append(f"{record.barcode}{suffix}")
        existing_text = "Códigos activos: " + ("  |  ".join(values) if values else "Ninguno")
        self.existing_label = QLabel(existing_text)
        self.existing_label.setFont(make_font(FONTS["small"]))
        self.existing_label.setWordWrap(True)
        self.existing_label.setStyleSheet(
            "color: #64748b; background: #f8fafc; border: none; "
            "border-radius: 5px; padding: 6px;"
        )
        layout.addWidget(self.existing_label)

    def _capture_line(self):
        text = self.scan_input.text()
        self.scan_input.clear()
        events = self.hid.feed_text(text + "\r")
        if not events:
            self._show_error("Escaneo vacío")
            return
        event = events[-1]
        if event.error:
            self._show_error(event.error)
            return
        result = self.verifier.submit_scan(event.barcode)
        if result.state == DoubleScanState.WAITING_CONFIRMATION:
            self.first_label.setText("Primer código: " + ("*" * len(result.barcode)))
            self.status_label.setText(
                "ESTADO: Primer scan capturado. Escanee nuevamente para verificar."
            )
            self.status_label.setStyleSheet("color: #9a6700; border: none;")
        elif result.state == DoubleScanState.VERIFIED:
            self._verified_barcode = result.barcode
            self._barcode_type = BARCODE_TYPE_MANUFACTURER
            self._source = SOURCE_HID_DOUBLE_SCAN
            self.status_label.setText("VERIFICADO ✓ · pendiente de guardar en DB")
            self.status_label.setStyleSheet("color: #16803c; border: none; font-weight: 600;")
            self.scan_input.setEnabled(False)
            self.barcodeVerified.emit(result.barcode)
        elif result.state == DoubleScanState.MISMATCH:
            self.first_label.setText("Primer código: —")
            self.status_label.setText(
                "CÓDIGOS NO COINCIDEN · Esperando primer escaneo"
            )
            self.status_label.setStyleSheet("color: #b42318; border: none; font-weight: 600;")
        else:
            self._show_error(result.message)

    def _generate_or_confirm_frp(self):
        if self._pending_frp is None:
            try:
                generator = FrpBarcodeGenerator(self.repository.barcode_exists)
                self._pending_frp = generator.generate()
            except Exception as exc:
                self._show_error(str(exc))
                return
            self.first_label.setText(f"FRP propuesto: {self._pending_frp}")
            self.status_label.setText(
                "Confirme explícitamente el FRP; aún NO se ha guardado."
            )
            self.status_label.setStyleSheet("color: #9a6700; border: none;")
            self.frp_button.setText("Confirmar FRP generado")
            return

        self._verified_barcode = self._pending_frp
        self._barcode_type = BARCODE_TYPE_INTERNAL_FRP
        self._source = SOURCE_EXPLICIT_FRP
        self.status_label.setText("FRP GENERADO Y CONFIRMADO ✓ · pendiente de DB")
        self.status_label.setStyleSheet("color: #16803c; border: none; font-weight: 600;")
        self.scan_input.setEnabled(False)
        self.frp_button.setEnabled(False)
        self.barcodeVerified.emit(self._verified_barcode)

    def _show_error(self, message):
        self.status_label.setText(f"ERROR: {message}")
        self.status_label.setStyleSheet("color: #b42318; border: none; font-weight: 600;")

    def mark_persistence_verified(self):
        self.status_label.setText("GUARDADO Y VERIFICADO ✓")
        self.status_label.setStyleSheet("color: #16803c; border: none; font-weight: 700;")

    def reset(self):
        self.hid.reset()
        self.verifier.reset()
        self._verified_barcode = None
        self._barcode_type = BARCODE_TYPE_MANUFACTURER
        self._source = SOURCE_HID_DOUBLE_SCAN
        self._pending_frp = None
        self.first_label.setText("Primer código: —")
        self.status_label.setText("ESTADO: Esperando primer escaneo")
        self.status_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; border: none;"
        )
        self.scan_input.setEnabled(True)
        self.scan_input.clear()
        self.frp_button.setEnabled(True)
        self.frp_button.setText("Generar FRP explícitamente")
