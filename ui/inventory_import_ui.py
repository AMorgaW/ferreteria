# -*- coding: utf-8 -*-
"""Preview de staging para inventario físico; no contiene acciones de APPLY."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import time

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QColor, QCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from repositories.inventory_import_repository import InventoryImportRepository
from services.inventory_import_service import InventoryImportService
from services.inventory_apply_service import (
    ApprovalBlockedError,
    InventoryImportApplyService,
)
from ui.async_worker import FunctionWorker
from ui_config import COLORS, FONTS, make_font
from performance_trace import mark


def _quantity(scaled) -> str:
    if scaled is None:
        return "—"
    value = Decimal(int(scaled)) / Decimal(1000)
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


class InventoryImportUI(QWidget):
    FILTERS = ("TODOS", "VÁLIDOS", "ERRORES", "NUEVOS", "MATCH", "REVISAR")

    def __init__(self, parent, db_manager, product_repository=None, auth_manager=None):
        started_at = time.perf_counter()
        super().__init__(parent)
        self.auth = auth_manager
        self.service = InventoryImportService(InventoryImportRepository(db_manager))
        self.apply_service = InventoryImportApplyService(
            InventoryImportRepository(db_manager),
            product_repository=product_repository,
            actor_provider=self._actor_name,
        )
        self._thread_pool = QThreadPool.globalInstance()
        self._rows: list[dict] = []
        self._batch_id = None
        self._selected_path = ""
        self._build_ui()
        mark("ui.inventory_import.open", started_at, gui_thread=True)

    def _actor_name(self):
        user = getattr(self.auth, "usuario_actual", None) if self.auth else None
        if user is None:
            return "UI_OPERATOR"
        return str(
            getattr(user, "id", None)
            or getattr(user, "username", None)
            or getattr(user, "nombre_completo", None)
            or "UI_OPERATOR"
        )

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 15)
        layout.setSpacing(12)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("Importar inventario físico")
        title.setFont(make_font(("Segoe UI", 18, "bold")))
        title.setStyleSheet(f"color: {COLORS['text_primary']};")
        subtitle = QLabel("XLSX → staging → revisión humana → aprobación → apply verificable")
        subtitle.setFont(make_font(FONTS["body"]))
        subtitle.setStyleSheet(f"color: {COLORS['text_secondary']};")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles)
        header.addStretch()
        safety = QLabel("APPLY CONTROLADO · REQUIERE APROBACIÓN FUERTE")
        safety.setStyleSheet(
            f"background: {COLORS['warning_light']}; color: {COLORS['warning_dark']}; "
            f"border: 1px solid {COLORS['warning']}; border-radius: 8px; padding: 8px 12px; font-weight: 600;"
        )
        header.addWidget(safety)
        layout.addLayout(header)

        source = QFrame()
        source.setStyleSheet(
            f"QFrame {{ background: white; border: 1px solid {COLORS['border']}; border-radius: 10px; }}"
        )
        source_layout = QHBoxLayout(source)
        source_layout.setContentsMargins(12, 10, 12, 10)
        self.file_label = QLabel("Seleccione el XLSX operacional de 18 columnas")
        self.file_label.setStyleSheet(f"color: {COLORS['text_secondary']}; border: none;")
        source_layout.addWidget(self.file_label, 1)
        choose = self._button("Seleccionar XLSX", primary=False)
        choose.clicked.connect(self._choose_file)
        source_layout.addWidget(choose)
        self.import_button = self._button("Validar e importar a staging", primary=True)
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self._import)
        source_layout.addWidget(self.import_button)
        layout.addWidget(source)

        self.cards_layout = QHBoxLayout()
        self.cards = {}
        for key, label in (
            ("total", "Filas"), ("valid", "Válidas"), ("warnings", "Warnings"),
            ("errors", "Errores"), ("exact", "Match exacto"),
            ("candidate", "Candidatos"), ("new", "Nuevos"),
            ("ambiguous", "Ambiguos"), ("pending", "Barcode pending"),
        ):
            card = QFrame()
            card.setMinimumWidth(105)
            card.setStyleSheet(
                f"QFrame {{ background: white; border: 1px solid {COLORS['border']}; border-radius: 9px; }}"
            )
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 7, 10, 7)
            value = QLabel("0")
            value.setFont(make_font(("Segoe UI", 15, "bold")))
            value.setStyleSheet(f"color: {COLORS['primary']}; border: none;")
            caption = QLabel(label)
            caption.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 8pt; border: none;")
            card_layout.addWidget(value)
            card_layout.addWidget(caption)
            self.cards[key] = value
            self.cards_layout.addWidget(card)
        layout.addLayout(self.cards_layout)

        tools = QHBoxLayout()
        tools.addWidget(QLabel("Filtro:"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(self.FILTERS)
        self.filter_combo.currentTextChanged.connect(self._render)
        tools.addWidget(self.filter_combo)
        tools.addStretch()
        self.batch_label = QLabel("Sin batch")
        self.batch_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        tools.addWidget(self.batch_label)
        self.dry_run_button = self._button("Ver dry-run", primary=False)
        self.dry_run_button.setEnabled(False)
        self.dry_run_button.clicked.connect(self._dry_run)
        tools.addWidget(self.dry_run_button)
        layout.addLayout(tools)

        apply_tools = QHBoxLayout()
        self.workflow_label = QLabel("REVISAR → APROBAR → APLICAR")
        self.workflow_label.setStyleSheet(
            f"color: {COLORS['primary']}; font-weight: 600;"
        )
        apply_tools.addWidget(self.workflow_label)
        apply_tools.addStretch()
        self.confirm_match_button = self._button("Confirmar match seleccionado", primary=False)
        self.confirm_match_button.setEnabled(False)
        self.confirm_match_button.clicked.connect(self._confirm_match)
        apply_tools.addWidget(self.confirm_match_button)
        self.review_button = self._button("Revisar aprobación", primary=False)
        self.review_button.setEnabled(False)
        self.review_button.clicked.connect(self._review_for_approval)
        apply_tools.addWidget(self.review_button)
        self.approve_button = self._button("Aprobar plan", primary=False)
        self.approve_button.setEnabled(False)
        self.approve_button.clicked.connect(self._approve)
        apply_tools.addWidget(self.approve_button)
        self.cancel_button = self._button("Cancelar batch", primary=False)
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_batch)
        apply_tools.addWidget(self.cancel_button)
        self.apply_button = self._button("APLICAR INVENTARIO", primary=True)
        self.apply_button.setAutoDefault(False)
        self.apply_button.setDefault(False)
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self._apply_inventory)
        apply_tools.addWidget(self.apply_button)
        layout.addLayout(apply_tools)

        self.progress_label = QLabel("Sin operaciones reales iniciadas")
        self.progress_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        layout.addWidget(self.progress_label)

        columns = (
            "Fila", "Producto", "Marca", "Categoría", "Presentación",
            "Cantidad", "Match", "Producto FERREPRO", "Barcode", "Estado", "Errores / revisión",
        )
        self.table = QTableWidget(0, len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        widths = (55, 210, 105, 150, 115, 85, 125, 180, 145, 90, 310)
        for index, width in enumerate(widths):
            self.table.setColumnWidth(index, width)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setStyleSheet(f"""
            QTableWidget {{ background: white; border: 1px solid {COLORS['border']}; border-radius: 10px; }}
            QTableWidget::item {{ padding: 6px 7px; }}
            QTableWidget::item:selected {{ background: {COLORS['table_selection']}; color: {COLORS['text_primary']}; }}
            QHeaderView::section {{ background: {COLORS['table_header']}; color: {COLORS['table_header_fg']};
                border: none; padding: 9px 7px; font-weight: 500; }}
        """)
        layout.addWidget(self.table, 1)

    def _button(self, text: str, *, primary: bool) -> QPushButton:
        button = QPushButton(text)
        button.setCursor(QCursor(Qt.PointingHandCursor))
        button.setMinimumHeight(38)
        if primary:
            button.setStyleSheet(
                f"QPushButton {{ background: {COLORS['primary']}; color: white; border: none; border-radius: 8px; padding: 8px 15px; font-weight: 600; }}"
                f"QPushButton:hover {{ background: {COLORS['primary_dark']}; }} QPushButton:disabled {{ background: #9CA3AF; }}"
            )
        else:
            button.setStyleSheet(
                f"QPushButton {{ background: white; color: {COLORS['text_body']}; border: 1px solid {COLORS['border_input']}; border-radius: 8px; padding: 8px 14px; font-weight: 500; }}"
                f"QPushButton:hover {{ background: {COLORS['bg_hover']}; }} QPushButton:disabled {{ color: #9CA3AF; }}"
            )
        return button

    def _choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Seleccionar inventario físico", "", "Excel seguro (*.xlsx)")
        if not path:
            return
        self._selected_path = path
        self.file_label.setText(Path(path).name)
        self.import_button.setEnabled(True)

    def _import(self):
        if not self._selected_path:
            return
        self.import_button.setEnabled(False)
        self.file_label.setText(f"Validando {Path(self._selected_path).name}…")
        worker = FunctionWorker(self.service.import_to_staging, self._selected_path)
        worker.signals.result.connect(self._imported)
        worker.signals.error.connect(self._import_error)
        self._thread_pool.start(worker)

    def _imported(self, result):
        self._rows = list(result.rows)
        self._batch_id = result.batch.batch_id
        reused = " · archivo ya importado, batch reutilizado" if result.batch.reused else ""
        self.file_label.setText(f"{result.batch.source_filename}{reused}")
        self.batch_label.setText(f"Batch {result.batch.batch_id[:8]} · {result.batch.status}")
        self.import_button.setEnabled(True)
        self.dry_run_button.setEnabled(True)
        self.confirm_match_button.setEnabled(True)
        self.review_button.setEnabled(True)
        self.approve_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self._refresh_workflow()
        self._update_cards()
        self._render()

    def _import_error(self, error):
        self.import_button.setEnabled(True)
        self.file_label.setText(Path(self._selected_path).name)
        QMessageBox.critical(self, "Importación rechazada", str(error))

    def _update_cards(self):
        rows = self._rows
        counts = {
            "total": len(rows),
            "valid": sum(row["validation_status"] == "VALID" for row in rows),
            "warnings": sum(row["validation_status"] == "WARNING" for row in rows),
            "errors": sum(row["validation_status"] == "ERROR" for row in rows),
            "exact": sum(row["match_status"] == "MATCH_EXACT" for row in rows),
            "candidate": sum(row["match_status"] == "MATCH_CANDIDATE" for row in rows),
            "new": sum(row["match_status"] == "NEW_PRODUCT" for row in rows),
            "ambiguous": sum(row["match_status"] == "AMBIGUOUS" for row in rows),
            "pending": sum(row["barcode_status"] == "BARCODE_PENDING" for row in rows),
        }
        for key, value in counts.items():
            self.cards[key].setText(str(value))

    def _filtered(self):
        selected = self.filter_combo.currentText()
        for row in self._rows:
            if selected == "VÁLIDOS" and row["validation_status"] != "VALID":
                continue
            if selected == "ERRORES" and row["validation_status"] != "ERROR":
                continue
            if selected == "NUEVOS" and row["match_status"] != "NEW_PRODUCT":
                continue
            if selected == "MATCH" and row["match_status"] not in ("MATCH_EXACT", "MATCH_CANDIDATE"):
                continue
            if selected == "REVISAR" and row["validation_status"] == "VALID" and row["match_status"] not in ("MATCH_CANDIDATE", "AMBIGUOUS"):
                continue
            yield row

    def _render(self, *_args):
        rows = list(self._filtered())
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            payload = row["normalized_payload"]
            issues = [*row["validation_errors"], *row["validation_warnings"]]
            issue_text = " · ".join(f"{item['code']}: {item['message']}" for item in issues) or "—"
            values = (
                row["excel_row_number"], payload.get("nombre") or "—",
                payload.get("marca") or "—", payload.get("categoria") or "—",
                payload.get("presentacion_empaque") or "—", _quantity(row.get("cantidad_contada_scaled")),
                row["match_status"], row.get("matched_product_name") or "—",
                row["barcode_status"], row["validation_status"], issue_text,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.UserRole, row.get("row_id"))
                if column in (0, 5):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if row["validation_status"] == "ERROR":
                    item.setForeground(QColor(COLORS["danger_dark"]))
                elif row["validation_status"] == "WARNING":
                    item.setForeground(QColor(COLORS["warning_dark"]))
                self.table.setItem(index, column, item)

    def _dry_run(self):
        if not self._batch_id:
            return
        try:
            plan = self.service.dry_run(self._batch_id)
            s = plan.summary
            authority = ", ".join(plan.authority_sources) or "No aplica (solo productos nuevos/bloqueados)"
            QMessageBox.information(
                self,
                "Dry-run — cero mutaciones",
                f"Productos nuevos propuestos: {s['new_products']}\n"
                f"Productos existentes: {s['existing_products']}\n"
                f"Actualizaciones metadata: {s['metadata_updates']}\n"
                f"Ajustes positivos: {s['positive_adjustments']}\n"
                f"Ajustes negativos: {s['negative_adjustments']}\n"
                f"Sin cambio: {s['unchanged']}\n"
                f"Barcode pending: {s['barcode_pending']}\n"
                f"Filas bloqueadas: {s['blocking_rows']}\n\n"
                f"Autoridad: {authority}\n\n"
                "Productos creados: 0 · Stock mutado: 0 · Barcodes persistidos: 0",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Dry-run bloqueado", str(exc))

    def _refresh_workflow(self):
        if not self._batch_id:
            return
        try:
            batch = self.apply_service.repository.ensure_apply_controls(self._batch_id)
        except Exception as exc:
            self.progress_label.setText(f"Coordinador 2E no disponible: {exc}")
            self.apply_button.setEnabled(False)
            return
        state = batch["workflow_state"]
        self.workflow_label.setText(f"Batch {self._batch_id[:8]} · {state}")
        approved = state == "APPROVED"
        recoverable = state in ("APPLYING", "PARTIALLY_FAILED")
        self.apply_button.setText(
            "REANUDAR / RECONCILIAR" if recoverable else "APLICAR INVENTARIO"
        )
        self.apply_button.setEnabled(approved or recoverable)
        self.approve_button.setEnabled(state not in ("APPLYING", "APPLIED", "COMPLETED", "CANCELLED"))
        self.review_button.setEnabled(state not in ("APPLIED", "COMPLETED", "CANCELLED"))
        self.cancel_button.setText("Detener nuevas filas" if state == "APPLYING" else "Cancelar batch")
        self.cancel_button.setEnabled(state not in ("APPLIED", "COMPLETED", "CANCELLED"))

    def _selected_row_id(self):
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        item = self.table.item(selected[0].row(), 0)
        return item.data(Qt.UserRole) if item else None

    def _confirm_match(self):
        row_id = self._selected_row_id()
        if not row_id:
            QMessageBox.warning(self, "Confirmar match", "Seleccione una fila candidata o ambigua.")
            return
        row = next((item for item in self._rows if item.get("row_id") == row_id), None)
        if not row or row["match_status"] not in ("MATCH_CANDIDATE", "AMBIGUOUS"):
            QMessageBox.warning(self, "Confirmar match", "La fila seleccionada no requiere confirmación.")
            return
        products = self.apply_service.repository.list_products()
        labels = [
            f"{item.get('nombre') or 'Sin nombre'} · {item.get('marca') or 'Sin marca'} · {item['local_id']}"
            for item in products
        ]
        selected, ok = QInputDialog.getItem(
            self, "CONFIRM MATCH", "Producto FERREPRO correcto:", labels, 0, False
        )
        if not ok:
            return
        index = labels.index(selected)
        try:
            self.apply_service.repository.confirm_match(
                row_id, products[index]["local_id"], actor=self._actor_name()
            )
            self._refresh_workflow()
            QMessageBox.information(self, "Match confirmado", "La resolución quedó persistida y sobrevivirá un reinicio.")
        except Exception as exc:
            QMessageBox.critical(self, "No se pudo confirmar", str(exc))

    def _review_for_approval(self):
        if not self._batch_id:
            return
        try:
            review = self.apply_service.build_review_plan(self._batch_id)
            warning_block = any(
                item["reason"] in ("WARNING_NOT_APPROVED", "WORKBOOK_WARNING_NOT_APPROVED")
                for item in review["blockers"]
            )
            if warning_block:
                answer = QMessageBox.warning(
                    self, "Warnings requieren confirmación",
                    f"Hay {review['summary']['warnings']} warnings. ¿Confirma que fueron revisados?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
                )
                if answer == QMessageBox.Yes:
                    self.apply_service.repository.acknowledge_batch_warnings(
                        self._batch_id, actor=self._actor_name()
                    )
                    review = self.apply_service.build_review_plan(self._batch_id)
            for blocker in list(review["blockers"]):
                if blocker["reason"] != "METADATA_APPROVAL_REQUIRED":
                    continue
                fields = blocker.get("fields") or []
                answer = QMessageBox.question(
                    self, "Cambio de metadata",
                    f"Fila {blocker['excel_row_number']}: {', '.join(fields)}\n\n"
                    "Sí: aplicar cambios del Excel.\nNo: conservar valores actuales.",
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                    QMessageBox.Cancel,
                )
                if answer == QMessageBox.Cancel:
                    continue
                self.apply_service.repository.decide_metadata(
                    blocker["row_id"],
                    "APPLY" if answer == QMessageBox.Yes else "KEEP_CURRENT",
                    fields=fields if answer == QMessageBox.Yes else (),
                    actor=self._actor_name(),
                )
            review = self.apply_service.build_review_plan(self._batch_id)
            s = review["summary"]
            self.progress_label.setText(
                f"Revisión: {s['products']} productos · {s['blocking_rows']} bloqueos · "
                f"{s['barcode_pending']} barcodes pending"
            )
            if review["blockers"]:
                reasons = "\n".join(
                    f"• fila {item.get('excel_row_number', 'batch')}: {item['reason']}"
                    for item in review["blockers"][:12]
                )
                QMessageBox.warning(self, "Aprobación bloqueada", reasons)
            else:
                QMessageBox.information(
                    self, "Listo para aprobación",
                    f"{s['products']} productos serán procesados\n"
                    f"{s['existing_products']} existentes · {s['new_products']} nuevos\n"
                    f"{s['inventory_adjustments']} ajustes de stock\n"
                    f"{s['metadata_changes']} cambios de metadata\n"
                    f"{s['warnings']} warnings aprobados\n"
                    f"{s['barcode_pending']} barcodes pending",
                )
            self._refresh_workflow()
        except Exception as exc:
            QMessageBox.critical(self, "Revisión fallida", str(exc))

    def _approve(self):
        try:
            batch = self.apply_service.approve_batch(
                self._batch_id, actor=self._actor_name()
            )
            self.progress_label.setText(
                f"Plan aprobado e inmutable · {batch['approval_plan_hash'][:12]}"
            )
            self._refresh_workflow()
        except ApprovalBlockedError as exc:
            QMessageBox.warning(self, "No se puede aprobar", str(exc))
        except Exception as exc:
            QMessageBox.critical(self, "Aprobación fallida", str(exc))

    def _apply_inventory(self):
        try:
            batch = self.apply_service.repository.get_apply_batch(self._batch_id)
            summary = (batch.get("approved_plan") or {}).get("summary") or {}
            phrase, ok = QInputDialog.getText(
                self, "Confirmación fuerte",
                f"{summary.get('products', 0)} productos serán procesados\n"
                f"{summary.get('existing_products', 0)} existentes · {summary.get('new_products', 0)} nuevos\n"
                f"{summary.get('inventory_adjustments', 0)} ajustes de stock\n"
                f"{summary.get('metadata_changes', 0)} cambios de metadata\n"
                f"{summary.get('barcode_pending', 0)} barcodes pendientes\n\n"
                "Escriba APLICAR INVENTARIO para continuar:",
            )
            if not ok or phrase.strip() != "APLICAR INVENTARIO":
                return
        except Exception as exc:
            QMessageBox.critical(self, "Apply bloqueado", str(exc))
            return
        self.apply_button.setEnabled(False)
        self.apply_button.setText("APLICANDO...")
        self.progress_label.setText("APLICANDO... no cierre la aplicación")
        worker = FunctionWorker(
            self.apply_service.apply_batch, self._batch_id,
            actor=self._actor_name(),
        )
        worker.signals.result.connect(self._apply_finished)
        worker.signals.error.connect(self._apply_error)
        self._thread_pool.start(worker)

    def _apply_finished(self, progress):
        self.progress_label.setText(
            f"{progress.state} · {progress.verified}/{progress.total} verificadas · "
            f"{progress.unknown} unknown · {progress.failed} fallidas"
        )
        self._refresh_workflow()

    def _apply_error(self, error):
        self.progress_label.setText(f"Requiere revisión: {error}")
        self._refresh_workflow()
        QMessageBox.critical(self, "Apply detenido de forma segura", str(error))

    def _cancel_batch(self):
        try:
            state = self.apply_service.repository.get_apply_batch(self._batch_id)["workflow_state"]
        except Exception as exc:
            QMessageBox.critical(self, "Estado no disponible", str(exc))
            return
        if state == "APPLYING":
            answer = QMessageBox.question(
                self, "Detener nuevas filas",
                "Se detendrán filas nuevas. Las operaciones ya aplicadas NO se revierten. ¿Continuar?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer == QMessageBox.Yes:
                try:
                    self.apply_service.request_stop(self._batch_id, actor=self._actor_name())
                    self.progress_label.setText("Detención solicitada · sin rollback automático")
                except Exception as exc:
                    QMessageBox.critical(self, "No se pudo detener", str(exc))
            return
        answer = QMessageBox.question(
            self, "Cancelar batch", "¿Cancelar este batch antes de APPLY?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.apply_service.cancel_batch(self._batch_id, actor=self._actor_name())
            self.progress_label.setText("Batch cancelado antes de operaciones reales")
            self._refresh_workflow()
        except Exception as exc:
            QMessageBox.critical(self, "No se puede cancelar", str(exc))
