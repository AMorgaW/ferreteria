# -*- coding: utf-8 -*-
"""Diálogo mínimo 3C: devolver / anular. ENTER del scanner no confirma."""
from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from returns_schema import (
    KIND_CUSTOMER_RETURN,
    KIND_SALE_VOID,
    KIND_SUPPLIER_RETURN,
    ORIGINAL_TIPO_COMPRA,
    ORIGINAL_TIPO_VENTA,
)
from services.return_cart import ReturnCart, return_finalize_allowed
from ui.async_worker import FunctionWorker
from ui_config import COLORS, FONTS, make_font


class ReversalDialog(QDialog):
    def __init__(
        self,
        parent,
        *,
        kind: str,
        original_tipo: str,
        original_id: int,
        returns_service,
        db_manager=None,
        auto_exec: bool = True,
    ):
        super().__init__(parent)
        self.kind = kind
        self.original_tipo = original_tipo
        self.original_id = original_id
        self.returns_service = returns_service
        self.db_manager = db_manager
        self.cart = ReturnCart(
            kind=kind, original_tipo=original_tipo, original_id=original_id
        )
        self.spinboxes = []
        titles = {
            KIND_CUSTOMER_RETURN: "Devolver a cliente",
            KIND_SALE_VOID: "Anular venta",
            KIND_SUPPLIER_RETURN: "Devolver a proveedor",
        }
        self.setWindowTitle(titles.get(kind, "Reverso"))
        self.resize(860, 520)
        self.setModal(True)
        self.setStyleSheet(f"background: {COLORS['bg_primary']};")
        self._build()
        self._load_preview()
        if auto_exec:
            self.exec()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QLabel(self.windowTitle())
        header.setFixedHeight(52)
        header.setAlignment(Qt.AlignCenter)
        header.setFont(make_font(FONTS["large"]))
        header.setStyleSheet(
            f"background: {COLORS['primary']}; color: white; border: none;"
        )
        layout.addWidget(header)

        self.meta = QLabel("")
        self.meta.setWordWrap(True)
        self.meta.setStyleSheet(
            f"color: {COLORS['text_primary']}; background: white; padding: 12px 18px;"
        )
        layout.addWidget(self.meta)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            [
                "Producto",
                "Original",
                "Ya devuelto",
                "Disponible",
                "Solicitado",
            ]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        layout.addWidget(self.table, 1)

        self.scan_entry = QLineEdit()
        self.scan_entry.setPlaceholderText("Scanner: no confirma el reverso")
        self.scan_entry.returnPressed.connect(self._ignore_scanner_enter)
        layout.addWidget(self.scan_entry)

        btns = QHBoxLayout()
        btns.setContentsMargins(16, 8, 16, 16)
        self.btn_confirm = QPushButton("CONFIRMAR DEVOLUCIÓN")
        if self.kind == KIND_SALE_VOID:
            self.btn_confirm.setText("CONFIRMAR ANULACIÓN")
        elif self.kind == KIND_SUPPLIER_RETURN:
            self.btn_confirm.setText("CONFIRMAR DEVOLUCIÓN A PROVEEDOR")
        self.btn_confirm.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_confirm.setDefault(False)
        self.btn_confirm.setAutoDefault(False)
        self.btn_confirm.clicked.connect(self._confirm)
        self.btn_confirm.setStyleSheet(
            f"QPushButton {{ background: {COLORS['accent']}; color: white; border: none; "
            f"border-radius: 6px; padding: 10px 18px; font-weight: 600; }}"
            f"QPushButton:disabled {{ background: {COLORS['secondary']}; }}"
        )
        cancel = QPushButton("Cancelar")
        cancel.setDefault(False)
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        btns.addWidget(self.btn_confirm)
        btns.addStretch()
        btns.addWidget(cancel)
        wrap = QWidget()
        wrap.setLayout(btns)
        layout.addWidget(wrap)

    def _ignore_scanner_enter(self):
        self.scan_entry.clear()

    def _load_preview(self):
        data = self.returns_service.preview(
            original_tipo=self.original_tipo, original_id=self.original_id
        )
        original = data.get("original") or {}
        self.cart.original_local_id = original.get("local_id")
        self.cart.lines = data.get("lines") or []
        status = data.get("derived_status") or "COMPLETED"
        self.meta.setText(
            f"Documento original: {self.original_tipo} #{self.original_id}\n"
            f"Estado histórico: {original.get('estado', 'COMPLETADA')}  ·  "
            f"Reverso derivado: {status}"
        )
        self.table.setRowCount(0)
        self.spinboxes = []
        for line in self.cart.lines:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                str(line.get("producto_nombre") or line["producto_id"]),
                str(line.get("original_qty")),
                str(line.get("returned_qty")),
                str(line.get("available_qty")),
            ]
            for col, val in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(val))
            spin = QDoubleSpinBox()
            spin.setDecimals(3)
            spin.setMinimum(0)
            spin.setMaximum(float(line.get("available_qty") or 0))
            if self.kind == KIND_SALE_VOID:
                spin.setValue(float(line.get("available_qty") or 0))
                line["requested_qty"] = line.get("available_qty") or Decimal("0")
            spin.valueChanged.connect(lambda _v, idx=row: self._on_qty(idx))
            self.table.setCellWidget(row, 4, spin)
            self.spinboxes.append(spin)

    def _on_qty(self, index: int):
        if 0 <= index < len(self.spinboxes):
            self.cart.lines[index]["requested_qty"] = Decimal(
                str(self.spinboxes[index].value())
            )

    def _set_busy(self, busy: bool):
        self.btn_confirm.setEnabled(not busy)
        self.btn_confirm.setText(
            "PROCESANDO..." if busy else self._idle_label()
        )

    def _idle_label(self) -> str:
        if self.kind == KIND_SALE_VOID:
            return "CONFIRMAR ANULACIÓN"
        if self.kind == KIND_SUPPLIER_RETURN:
            return "CONFIRMAR DEVOLUCIÓN A PROVEEDOR"
        return "CONFIRMAR DEVOLUCIÓN"

    def _confirm(self):
        if not self.cart.begin_confirm():
            return
        for index, spin in enumerate(self.spinboxes):
            self.cart.lines[index]["requested_qty"] = Decimal(str(spin.value()))
        try:
            items = self.cart.requested_items()
        except Exception as exc:
            self.cart.end_confirm()
            QMessageBox.warning(self, "Reverso", str(exc))
            return
        allowed, reason = return_finalize_allowed(
            self.db_manager or getattr(self.returns_service, "db", None)
        )
        if not allowed:
            self.cart.end_confirm()
            QMessageBox.warning(self, "CONFIRMAR bloqueado", reason or "")
            return
        reply = QMessageBox.question(
            self,
            "Confirmar reverso",
            "Esta operación crea un documento inverso nuevo.\n"
            "El documento original no se edita.\n¿Confirmar?",
        )
        if reply != QMessageBox.Yes:
            self.cart.end_confirm()
            return
        self._set_busy(True)

        def _run():
            ok, msg, rid = self.returns_service.guardar_borrador(
                kind=self.kind,
                original_tipo=self.original_tipo,
                original_id=self.original_id,
                items=items,
            )
            if not ok:
                return False, msg, rid
            return self.returns_service.confirmar(rid)

        worker = FunctionWorker(_run)
        worker.signals.result.connect(self._on_done)
        worker.signals.error.connect(self._on_error)
        from PySide6.QtCore import QThreadPool

        QThreadPool.globalInstance().start(worker)

    def _on_done(self, result):
        self.cart.end_confirm()
        self._set_busy(False)
        ok, msg, _rid = result
        if ok:
            QMessageBox.information(self, "Reverso", msg)
            self.accept()
            return
        QMessageBox.warning(self, "Reverso", msg)

    def _on_error(self, message: str):
        self.cart.end_confirm()
        self._set_busy(False)
        QMessageBox.critical(self, "Reverso", message)


def open_customer_return(parent, venta_id, returns_service, db_manager=None):
    return ReversalDialog(
        parent,
        kind=KIND_CUSTOMER_RETURN,
        original_tipo=ORIGINAL_TIPO_VENTA,
        original_id=int(venta_id),
        returns_service=returns_service,
        db_manager=db_manager,
    )


def open_sale_void(parent, venta_id, returns_service, db_manager=None):
    return ReversalDialog(
        parent,
        kind=KIND_SALE_VOID,
        original_tipo=ORIGINAL_TIPO_VENTA,
        original_id=int(venta_id),
        returns_service=returns_service,
        db_manager=db_manager,
    )


def open_supplier_return(parent, compra_id, returns_service, db_manager=None):
    return ReversalDialog(
        parent,
        kind=KIND_SUPPLIER_RETURN,
        original_tipo=ORIGINAL_TIPO_COMPRA,
        original_id=int(compra_id),
        returns_service=returns_service,
        db_manager=db_manager,
    )
