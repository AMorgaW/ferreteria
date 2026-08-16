# -*- coding: utf-8 -*-
"""Pantalla operacional Fase 2F para regularización de barcodes."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QThreadPool
from PySide6.QtGui import QColor, QCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from repositories.barcode_queue_repo import (
    FILTER_ALL,
    QUEUE_FILTERS,
    BarcodeQueueRepository,
)
from repositories.product_barcodes_repo import (
    PACKAGE_ROLE_BASE_UNIT,
    PACKAGE_ROLE_CUSTOM_PRESENTATION,
    PACKAGE_ROLE_FULL_PACKAGE,
    ProductBarcodesRepository,
)
from services.barcode_regularization_service import (
    ContinuousRegularizationController,
    ScannerTrialSession,
    ScannerTrialState,
)
from services.barcode_service import BarcodeSaveState
from ui_config import COLORS, FONTS, make_font
from ui.async_worker import FunctionWorker
from performance_trace import mark
import time


class BarcodeRegularizationUI(QWidget):
    """Cola DB-derived, doble scan continuo y prueba HID sin persistencia."""

    def __init__(self, parent, db_manager, auth_manager=None):
        super().__init__(parent)
        self.auth = auth_manager
        self.queue_repository = BarcodeQueueRepository(db_manager)
        self.barcode_repository = ProductBarcodesRepository(db_manager)
        self.controller = ContinuousRegularizationController(
            self.queue_repository,
            self.barcode_repository,
            actor=self._actor_name(),
        )
        self.trial = ScannerTrialSession()
        self._rows = []
        self._thread_pool = QThreadPool.globalInstance()
        self._refresh_seq = 0
        self._build_ui()
        self.refresh_queue()

    def _actor_name(self):
        user = getattr(self.auth, "usuario_actual", None) if self.auth else None
        return str(
            getattr(user, "username", None)
            or getattr(user, "id", None)
            or "UI_OPERATOR"
        )

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 15)
        root.setSpacing(12)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("Productos sin código de barras")
        title.setFont(make_font(("Segoe UI", 18, "bold")))
        title.setStyleSheet(f"color: {COLORS['text_primary']};")
        subtitle = QLabel(
            "Cola reconstruida desde DB · doble escaneo · verificación de persistencia"
        )
        subtitle.setFont(make_font(FONTS["body"]))
        subtitle.setStyleSheet(f"color: {COLORS['text_secondary']};")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles)
        header.addStretch()
        badge = QLabel("NO MODIFICA INVENTARIO")
        badge.setStyleSheet(
            f"background: {COLORS['accent_light']}; color: {COLORS['accent_dark']}; "
            f"border: 1px solid {COLORS['accent']}; border-radius: 8px; "
            "padding: 8px 12px; font-weight: 600;"
        )
        header.addWidget(badge)
        root.addLayout(header)

        tools = QHBoxLayout()
        tools.addWidget(QLabel("Filtro:"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(QUEUE_FILTERS)
        self.filter_combo.currentTextChanged.connect(self.refresh_queue)
        tools.addWidget(self.filter_combo)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Buscar nombre, marca, categoría o barcode")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._schedule_refresh)
        tools.addWidget(self.search_input, 1)
        refresh = self._button("Actualizar desde DB", primary=False)
        refresh.clicked.connect(self.refresh_queue)
        tools.addWidget(refresh)
        root.addLayout(tools)

        body = QHBoxLayout()
        body.setSpacing(12)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ("Producto", "Marca", "Categoría", "Presentación", "Estado", "Origen", "Barcode", "Acción")
        )
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setStretchLastSection(True)
        for index, width in enumerate((220, 105, 125, 115, 155, 105, 145, 175)):
            self.table.setColumnWidth(index, width)
        self.table.setStyleSheet(f"""
            QTableWidget {{ background: white; border: 1px solid {COLORS['border']}; border-radius: 10px; }}
            QTableWidget::item {{ padding: 6px 7px; }}
            QTableWidget::item:selected {{ background: {COLORS['table_selection']}; color: {COLORS['text_primary']}; }}
            QHeaderView::section {{ background: {COLORS['table_header']}; color: {COLORS['table_header_fg']};
                border: none; padding: 9px 7px; font-weight: 500; }}
        """)
        self.table.itemSelectionChanged.connect(self._select_row)
        body.addWidget(self.table, 3)

        self.tabs = QTabWidget()
        self.tabs.setMinimumWidth(390)
        self.tabs.addTab(self._build_operational_tab(), "Regularización continua")
        self.tabs.addTab(self._build_trial_tab(), "Prueba de scanner")
        self.tabs.currentChanged.connect(self._tab_changed)
        body.addWidget(self.tabs, 2)
        root.addLayout(body, 1)

    def _build_operational_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(10)
        self.product_label = QLabel("Seleccione un producto de la cola")
        self.product_label.setFont(make_font(FONTS["body_bold"]))
        self.product_label.setWordWrap(True)
        self.product_label.setStyleSheet(f"color: {COLORS['primary']};")
        layout.addWidget(self.product_label)

        self.candidate_label = QLabel("Candidate Excel: —")
        self.candidate_label.setWordWrap(True)
        self.candidate_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        layout.addWidget(self.candidate_label)

        role_row = QHBoxLayout()
        role_row.addWidget(QLabel("Presentación física:"))
        self.role_combo = QComboBox()
        self.role_combo.addItems((
            PACKAGE_ROLE_BASE_UNIT,
            PACKAGE_ROLE_FULL_PACKAGE,
            PACKAGE_ROLE_CUSTOM_PRESENTATION,
        ))
        self.role_combo.currentTextChanged.connect(self._restart_selected_session)
        role_row.addWidget(self.role_combo, 1)
        layout.addLayout(role_row)

        self.scan_input = QLineEdit()
        self.scan_input.setPlaceholderText("Enfoque aquí · escanee y confirme con el mismo código")
        self.scan_input.setMinimumHeight(44)
        self.scan_input.setFont(make_font(FONTS["body"]))
        self.scan_input.setStyleSheet(
            f"QLineEdit {{ border: 2px solid {COLORS['primary_border']}; border-radius: 8px; "
            "padding: 8px; background: white; }}"
            f"QLineEdit:focus {{ border-color: {COLORS['accent']}; }}"
        )
        self.scan_input.returnPressed.connect(self._submit_operational_scan)
        layout.addWidget(self.scan_input)

        self.operation_status = QLabel("WAITING_FIRST_SCAN")
        self.operation_status.setWordWrap(True)
        self.operation_status.setStyleSheet(
            f"background: {COLORS['primary_light']}; color: {COLORS['primary']}; "
            "border-radius: 8px; padding: 10px; font-weight: 600;"
        )
        layout.addWidget(self.operation_status)

        action_row = QHBoxLayout()
        self.frp_generate = self._button("Generar FRP", primary=False)
        self.frp_generate.clicked.connect(self._generate_frp)
        action_row.addWidget(self.frp_generate)
        self.frp_confirm = self._button("Confirmar FRP", primary=True)
        self.frp_confirm.setEnabled(False)
        self.frp_confirm.clicked.connect(self._confirm_frp)
        action_row.addWidget(self.frp_confirm)
        layout.addLayout(action_row)

        layout.addWidget(QLabel("Barcodes activos del producto:"))
        self.barcodes_combo = QComboBox()
        layout.addWidget(self.barcodes_combo)
        primary = self._button("Marcar seleccionado como PRIMARY", primary=False)
        primary.clicked.connect(self._mark_primary)
        layout.addWidget(primary)
        additional = self._button("Agregar barcode secundario", primary=False)
        additional.clicked.connect(self._begin_additional)
        layout.addWidget(additional)
        layout.addStretch()
        return tab

    def _build_trial_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(10)
        warning = QLabel("MODO TEST · 0 INSERT · 0 UPDATE · 0 PERSISTENCIA")
        warning.setWordWrap(True)
        warning.setStyleSheet(
            f"background: {COLORS['accent_light']}; color: {COLORS['accent_dark']}; "
            "border-radius: 8px; padding: 10px; font-weight: 700;"
        )
        layout.addWidget(warning)
        self.trial_input = QLineEdit()
        self.trial_input.setPlaceholderText("Enfoque aquí y escanee dos veces")
        self.trial_input.setMinimumHeight(44)
        self.trial_input.returnPressed.connect(self._submit_trial_scan)
        layout.addWidget(self.trial_input)
        self.trial_labels = {}
        for key, caption in (
            ("barcode", "Barcode"), ("length", "Longitud"),
            ("terminator", "Terminador"), ("first", "Primer scan"),
            ("second", "Segundo scan"), ("result", "Resultado"),
        ):
            label = QLabel(f"{caption}: —")
            label.setWordWrap(True)
            label.setStyleSheet(f"color: {COLORS['text_body']};")
            self.trial_labels[key] = label
            layout.addWidget(label)
        reset = self._button("Reiniciar prueba", primary=False)
        reset.clicked.connect(self._reset_trial)
        layout.addWidget(reset)
        layout.addStretch()
        return tab

    def _button(self, text, *, primary):
        button = QPushButton(text)
        button.setCursor(QCursor(Qt.PointingHandCursor))
        button.setMinimumHeight(36)
        if primary:
            button.setStyleSheet(
                f"QPushButton {{ background: {COLORS['primary']}; color: white; border: none; border-radius: 7px; padding: 7px 11px; font-weight: 600; }}"
                f"QPushButton:hover {{ background: {COLORS['primary_dark']}; }} QPushButton:disabled {{ background: #9CA3AF; }}"
            )
        else:
            button.setStyleSheet(
                f"QPushButton {{ background: white; color: {COLORS['text_body']}; border: 1px solid {COLORS['border_input']}; border-radius: 7px; padding: 7px 11px; }}"
                f"QPushButton:hover {{ background: {COLORS['bg_hover']}; }}"
            )
        return button

    def _schedule_refresh(self):
        QTimer.singleShot(180, self.refresh_queue)

    def refresh_queue(self):
        queue_filter = self.filter_combo.currentText() or FILTER_ALL
        search = self.search_input.text()
        self.controller.queue_filter = queue_filter
        self.controller.search = search
        self._refresh_seq += 1
        seq = self._refresh_seq
        started_at = time.perf_counter()
        worker = FunctionWorker(self.queue_repository.list_queue, queue_filter, search)
        worker.signals.result.connect(
            lambda rows, s=seq, started=started_at: self._apply_refreshed_queue(rows, s, started))
        worker.signals.error.connect(self._refresh_queue_error)
        self._thread_pool.start(worker)

    def _refresh_queue_error(self, error):
        self.operation_status.setText(f"ERROR DE COLA: {error}")

    def _apply_refreshed_queue(self, rows, seq, started_at):
        try:
            self.table.objectName()
        except RuntimeError:
            return
        if seq != self._refresh_seq:
            return
        self._rows = list(rows)
        self.controller.queue = self._rows
        mark("ui.barcodes.load", started_at, gui_thread=True)
        selected_key = self.controller.current_item.key if self.controller.current_item else None
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._rows))
        selected_row = None
        for row_index, item in enumerate(self._rows):
            values = (
                item.nombre, item.marca or "—", item.categoria or "—",
                item.presentacion or item.unidad_base or "—", item.barcode_status,
                item.origen, item.primary_barcode or item.excel_candidate or "—", item.accion,
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                cell.setData(Qt.UserRole, item.key)
                if item.barcode_status == "BARCODE_CONFLICT":
                    cell.setForeground(QColor(COLORS["danger"]))
                self.table.setItem(row_index, column, cell)
            if item.key == selected_key:
                selected_row = row_index
        self.table.blockSignals(False)
        if selected_row is not None:
            self.table.selectRow(selected_row)

    def _select_row(self):
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return
        item = self._rows[indexes[0].row()]
        if not item.selectable:
            self.product_label.setText(f"{item.nombre} · staging pendiente de APPLY")
            self.operation_status.setText("Esta fila aún no es un producto materializado")
            self.scan_input.setEnabled(False)
            return
        if not self.controller.select(item.key, package_role=self.role_combo.currentText()):
            return
        self.scan_input.setEnabled(True)
        self.product_label.setText(f"{item.nombre} · {item.marca or 'Sin marca'}")
        self.candidate_label.setText(
            "Candidate Excel: " + (item.excel_candidate or "— (sin referencia)")
        )
        self.operation_status.setText("WAITING_FIRST_SCAN · escanee el código")
        self._load_active_barcodes(item.producto_local_id)
        self.frp_confirm.setEnabled(False)
        self.scan_input.clear()
        self.scan_input.setFocus(Qt.OtherFocusReason)

    def _restart_selected_session(self):
        item = self.controller.current_item
        if item is not None:
            self.controller.select(item.key, package_role=self.role_combo.currentText())
            self.operation_status.setText("WAITING_FIRST_SCAN · presentación actualizada")
            self.scan_input.setFocus(Qt.OtherFocusReason)

    def _submit_operational_scan(self):
        raw = self.scan_input.text()
        self.scan_input.clear()
        step = self.controller.submit_scan(raw)
        result = step.save_result
        if step.excel_candidate_match is True:
            candidate = "Candidate Excel: MATCH (solo referencia)"
        elif step.excel_candidate_match is False:
            candidate = "WARNING: el scan difiere del candidate Excel"
        else:
            candidate = None
        if candidate:
            self.candidate_label.setText(candidate)
        self.operation_status.setText(f"{result.state.value} · {result.message}")
        if result.state in (BarcodeSaveState.ERROR, BarcodeSaveState.MISMATCH):
            self.operation_status.setStyleSheet(
                f"background: {COLORS['danger_light']}; color: {COLORS['danger']}; border-radius: 8px; padding: 10px; font-weight: 600;"
            )
        elif result.success:
            self.operation_status.setStyleSheet(
                f"background: #E8F5F0; color: {COLORS['success_dark']}; border-radius: 8px; padding: 10px; font-weight: 700;"
            )
            self.refresh_queue()
            if self.controller.current_item:
                self._select_controller_item()
        else:
            self.operation_status.setStyleSheet(
                f"background: {COLORS['warning_light']}; color: {COLORS['warning_dark']}; border-radius: 8px; padding: 10px; font-weight: 600;"
            )
        self.scan_input.setFocus(Qt.OtherFocusReason)

    def _select_controller_item(self):
        key = self.controller.current_item.key
        for row, item in enumerate(self._rows):
            if item.key == key:
                self.table.selectRow(row)
                return

    def _begin_additional(self):
        if self.controller.begin_additional_barcode(package_role=self.role_combo.currentText()):
            self.operation_status.setText("WAITING_FIRST_SCAN · barcode secundario")
            self.scan_input.setEnabled(True)
            self.scan_input.setFocus(Qt.OtherFocusReason)

    def _generate_frp(self):
        try:
            candidate = self.controller.generate_frp_candidate()
        except Exception as exc:
            self.operation_status.setText(f"ERROR: {exc}")
            return
        self.operation_status.setText(
            f"FRP PROPUESTO: {candidate} · confirme explícitamente para persistir"
        )
        self.frp_confirm.setEnabled(True)

    def _confirm_frp(self):
        step = self.controller.confirm_frp()
        self.frp_confirm.setEnabled(False)
        self.operation_status.setText(
            f"{step.save_result.state.value} · {step.save_result.message}"
        )
        self.refresh_queue()
        if self.controller.current_item:
            self._select_controller_item()

    def _load_active_barcodes(self, producto_local_id):
        self.barcodes_combo.clear()
        try:
            records = self.barcode_repository.list_for_product(producto_local_id)
        except Exception:
            records = []
        for record in records:
            suffix = " · PRIMARY" if record.is_primary else " · secundario"
            self.barcodes_combo.addItem(record.barcode + suffix, record.local_id)

    def _mark_primary(self):
        local_id = self.barcodes_combo.currentData()
        if not local_id:
            return
        try:
            record = self.controller.mark_primary(local_id)
        except Exception as exc:
            QMessageBox.warning(self, "Barcode", str(exc))
            return
        self._load_active_barcodes(record.producto_local_id)
        self.operation_status.setText("PRIMARY_SET · verificado desde DB")

    def _submit_trial_scan(self):
        raw = self.trial_input.text()
        self.trial_input.clear()
        results = self.trial.feed_text(raw + "\r")
        if not results:
            return
        result = results[-1]
        self.trial_labels["barcode"].setText(f"Barcode: {result.barcode or '—'}")
        self.trial_labels["length"].setText(f"Longitud: {result.length}")
        self.trial_labels["terminator"].setText(f"Terminador: {result.terminator or 'ENTER'}")
        if result.state == ScannerTrialState.WAITING_CONFIRMATION:
            self.trial_labels["first"].setText(f"Primer scan: {result.barcode}")
            self.trial_labels["result"].setText("Resultado: WAITING_CONFIRMATION")
        else:
            self.trial_labels["second"].setText(f"Segundo scan: {result.barcode or '—'}")
            visible = "MATCH" if result.match is True else "MISMATCH" if result.match is False else "ERROR"
            self.trial_labels["result"].setText(f"Resultado: {visible}")
        self.trial_input.setFocus(Qt.OtherFocusReason)

    def _reset_trial(self):
        self.trial.reset()
        for key, caption in (
            ("barcode", "Barcode"), ("length", "Longitud"),
            ("terminator", "Terminador"), ("first", "Primer scan"),
            ("second", "Segundo scan"), ("result", "Resultado"),
        ):
            self.trial_labels[key].setText(f"{caption}: —")
        self.trial_input.clear()
        self.trial_input.setFocus(Qt.OtherFocusReason)

    def _tab_changed(self, index):
        if index == 1:
            self.trial_input.setFocus(Qt.OtherFocusReason)
        else:
            self.scan_input.setFocus(Qt.OtherFocusReason)
