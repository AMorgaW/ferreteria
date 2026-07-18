# -*- coding: utf-8 -*-
from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from local_first_config import load_config, save_config
from local_first_db import DEFAULT_DB_PATH, connect, get_sync_status, row_to_dict
from local_server_manager import LocalServerManager
from local_sync import get_service
from ui.async_worker import FunctionWorker
from ui_config import COLORS


class LocalFirstAdminUI(QWidget):
    def __init__(self, parent=None, server_manager=None):
        super().__init__(parent)
        self.config = load_config()
        self.server_manager = server_manager or LocalServerManager(self.config)
        self.sync_service = get_service(DEFAULT_DB_PATH)
        self.pool = QThreadPool.globalInstance()
        self._build_ui()
        self.refresh_all()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_all)
        self.timer.start(10000)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        title = QLabel("Servidor local y sincronizacion")
        title.setStyleSheet(f"font-size: 18pt; font-weight: 500; color: {COLORS['text_primary']};")
        root.addWidget(title)

        self.banner = QLabel("")
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet(
            f"background: {COLORS['primary_light']}; color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['primary_border']}; padding: 10px;"
        )
        root.addWidget(self.banner)

        tabs = QTabWidget()
        tabs.addTab(self._build_sync_tab(), "Sincronizacion")
        tabs.addTab(self._build_server_tab(), "Servidor LAN")
        root.addWidget(tabs, 1)

    def _build_sync_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)

        stats = QGridLayout()
        self.stat_labels = {}
        for idx, (key, label) in enumerate([
            ("pending", "Pendientes"),
            ("failed", "Fallidos"),
            ("synced", "Sincronizados"),
            ("conflicts", "Conflictos"),
        ]):
            card = QFrame()
            card.setStyleSheet(f"background: white; border: 1px solid {COLORS['border']};")
            card_layout = QVBoxLayout(card)
            caption = QLabel(label)
            caption.setStyleSheet(f"color: {COLORS['text_secondary']};")
            value = QLabel("0")
            value.setStyleSheet(f"font-size: 20pt; font-weight: 500; color: {COLORS['text_primary']};")
            card_layout.addWidget(caption)
            card_layout.addWidget(value)
            stats.addWidget(card, 0, idx)
            self.stat_labels[key] = value
        layout.addLayout(stats)

        meta = QHBoxLayout()
        self.last_attempt = QLabel("Ultimo intento: -")
        self.last_success = QLabel("Ultimo exito: -")
        meta.addWidget(self.last_attempt)
        meta.addWidget(self.last_success)
        meta.addStretch()
        layout.addLayout(meta)

        actions = QHBoxLayout()
        actions.addWidget(self._button("Sincronizar ahora", self.run_sync, primary=True))
        actions.addWidget(self._button("Reintentar fallidos", self.retry_failed))
        actions.addWidget(self._button("Probar Supabase", self.test_supabase))
        actions.addWidget(self._button("Actualizar", self.refresh_all))
        actions.addStretch()
        layout.addLayout(actions)

        self.queue_table = QTableWidget()
        self.queue_table.setColumnCount(8)
        self.queue_table.setHorizontalHeaderLabels([
            "ID", "Entidad", "Operacion", "Estado", "Intentos", "Ultimo error", "Creado", "Sincronizado"
        ])
        self.queue_table.horizontalHeader().setStretchLastSection(True)
        self.queue_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.queue_table, 1)

        self.conflicts_table = QTableWidget()
        self.conflicts_table.setColumnCount(6)
        self.conflicts_table.setHorizontalHeaderLabels([
            "ID", "Entidad", "Registro", "Motivo", "Estado", "Fecha"
        ])
        self.conflicts_table.horizontalHeader().setStretchLastSection(True)
        self.conflicts_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.conflicts_table)
        return tab

    def _build_server_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)
        self.server_status = QLabel("Servidor: verificando...")
        self.server_status.setStyleSheet("font-size: 13pt; font-weight: 500;")
        self.server_port = QLabel("")
        self.server_url = QLabel("")
        self.server_url.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.server_url.setStyleSheet("font-size: 12pt; font-weight: 500;")
        self.server_host = QLabel("")
        layout.addWidget(self.server_status)
        layout.addWidget(self.server_port)
        layout.addWidget(self.server_url)
        layout.addWidget(self.server_host)

        actions = QHBoxLayout()
        actions.addWidget(self._button("Iniciar servidor", self.start_server, primary=True))
        actions.addWidget(self._button("Detener servidor", self.stop_server))
        actions.addWidget(self._button("Probar conexion", self.refresh_server))
        actions.addWidget(self._button("Copiar URL", self.copy_url))
        actions.addStretch()
        layout.addLayout(actions)

        note = QLabel("Conecta las PCs trabajadoras a la misma red WiFi o LAN y usa esta direccion en modo cliente.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {COLORS['text_secondary']};")
        layout.addWidget(note)
        layout.addStretch()
        return tab

    def _button(self, text, callback, primary=False):
        from ui.widgets import button_qss
        button = QPushButton(text)
        button.setCursor(Qt.PointingHandCursor)
        button.setMinimumHeight(38)
        button.setStyleSheet(button_qss('primary' if primary else 'ghost'))
        button.clicked.connect(callback)
        return button

    def _run_worker(self, fn, on_result=None):
        worker = FunctionWorker(fn)
        if on_result:
            worker.signals.result.connect(on_result)
        worker.signals.error.connect(lambda err: QMessageBox.warning(self, "Error", err))
        self.pool.start(worker)

    def refresh_all(self):
        self._run_worker(self._load_snapshot, self._apply_snapshot)
        self.refresh_server()

    def _load_snapshot(self):
        status = get_sync_status(DEFAULT_DB_PATH)
        conn = connect(DEFAULT_DB_PATH)
        try:
            queue = [
                row_to_dict(row)
                for row in conn.execute(
                    "SELECT * FROM sync_queue ORDER BY created_at DESC, id DESC LIMIT 100"
                )
            ]
            conflicts = [
                row_to_dict(row)
                for row in conn.execute(
                    "SELECT * FROM sync_conflicts ORDER BY created_at DESC, id DESC LIMIT 50"
                )
            ]
            return status, queue, conflicts
        finally:
            conn.close()

    def _apply_snapshot(self, snapshot):
        status, queue, conflicts = snapshot
        for key, label in self.stat_labels.items():
            label.setText(str(status.get(key, 0)))
        self.last_attempt.setText(f"Ultimo intento: {status.get('last_attempt') or '-'}")
        self.last_success.setText(f"Ultimo exito: {status.get('last_success') or '-'}")

        if status.get("failed"):
            self.banner.setText("Hay errores de sincronizacion. Las ventas siguen guardandose localmente.")
        elif status.get("pending"):
            self.banner.setText(f"Trabajando localmente. Hay {status['pending']} cambio(s) pendientes por subir.")
        else:
            self.banner.setText("Sistema local-first activo. La cola no tiene pendientes.")

        self._fill_table(
            self.queue_table,
            queue,
            ["id", "entity_type", "operation", "status", "attempts", "last_error", "created_at", "synced_at"],
        )
        self._fill_table(
            self.conflicts_table,
            conflicts,
            ["id", "entity_type", "entity_id", "conflict_reason", "status", "created_at"],
        )

    def _fill_table(self, table, rows, keys):
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column, key in enumerate(keys):
                table.setItem(row_index, column, QTableWidgetItem(str(row.get(key) or "")))
        table.resizeColumnsToContents()

    def refresh_server(self):
        self._run_worker(self.server_manager.status, self._apply_server_status)

    def _apply_server_status(self, status):
        active = status.get("active", False)
        self.server_status.setText("● Servidor LAN: ACTIVO" if active else "○ Servidor LAN: INACTIVO")
        self.server_status.setStyleSheet(
            f"font-size: 13pt; font-weight: 500; color: {COLORS['success'] if active else COLORS['danger']};"
        )
        self.server_port.setText(
            f"Puerto: {self.server_manager.port}    ·    Escucha en: {self.server_manager.host} "
            f"(todas las interfaces)" if self.server_manager.host == "0.0.0.0" else
            f"Puerto: {self.server_manager.port}    ·    Escucha en: {self.server_manager.host}")
        self.server_url.setText(f"Dirección para empleados: {status.get('url', self.server_manager.lan_url)}")
        self.server_host.setText(
            "Pasos: en cada caja, abrir la app en modo Cliente y escribir esta dirección.")

    def start_server(self):
        result = self.server_manager.start()
        QTimer.singleShot(1200, self.refresh_server)
        if result.get("starting"):
            QMessageBox.information(self, "Servidor local", "El servidor local esta iniciando.")

    def stop_server(self):
        result = self.server_manager.stop()
        QMessageBox.information(self, "Servidor local", result.get("message") or "Servidor detenido.")
        QTimer.singleShot(300, self.refresh_server)

    def copy_url(self):
        QApplication.clipboard().setText(self.server_manager.lan_url)
        QMessageBox.information(self, "Servidor local", "URL copiada.")

    def run_sync(self):
        self._run_worker(self.sync_service.sync_once, self._sync_done)

    def retry_failed(self):
        self._run_worker(self.sync_service.retry_failed, self._sync_done)

    def test_supabase(self):
        self._run_worker(self.sync_service.test_connection, self._supabase_tested)

    def _sync_done(self, result):
        self.refresh_all()
        QMessageBox.information(self, "Sincronizacion", str(result))

    def _supabase_tested(self, result):
        title = "Supabase conectado" if result.get("ok") else "Supabase no disponible"
        QMessageBox.information(self, title, result.get("message", ""))
