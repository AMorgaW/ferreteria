# -*- coding: utf-8 -*-
import sys
from decimal import Decimal

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QInputDialog,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from local_first_config import load_config, save_config
from services.local_api_client import LocalAPIClient, LocalAPIError
from services.remote_adapters import (
    RemoteDB, RemoteAuth, RemoteProductosRepo, RemoteClientesRepo,
    RemoteVentasService, RemoteCuentasService,
)
from ui.async_worker import FunctionWorker
from ui_config import GLOBAL_QSS


def money(value):
    return f"${Decimal(str(value or 0)):,.0f}"


class ServerConfigDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = dict(config)
        self.setWindowTitle("Conexion al servidor")
        self.setMinimumWidth(430)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.url_input = QLineEdit(self.config.get("last_connected_server") or self.config.get("server_url"))
        self.url_input.setPlaceholderText("http://192.168.1.10:8000")
        form.addRow("Direccion del administrador:", self.url_input)
        layout.addLayout(form)

        self.status_label = QLabel("Ingresa la direccion que muestra el computador administrador.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        row = QHBoxLayout()
        self.test_button = QPushButton("Probar conexion")
        self.test_button.clicked.connect(self.test_connection)
        row.addWidget(self.test_button)
        row.addStretch()
        layout.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def normalized_url(self):
        value = self.url_input.text().strip().rstrip("/")
        if value and not value.startswith(("http://", "https://")):
            value = f"http://{value}"
        return value

    def test_connection(self):
        url = self.normalized_url()
        if not url:
            return
        self.test_button.setEnabled(False)
        self.status_label.setText("Probando conexion...")
        worker = FunctionWorker(lambda: LocalAPIClient(url).health())
        worker.signals.result.connect(
            lambda result: self.status_label.setText(
                f"Conexion correcta. Servidor disponible: {result.get('status', 'ok')}."
            )
        )
        worker.signals.error.connect(lambda error: self.status_label.setText(f"No fue posible conectar: {error}"))
        worker.signals.finished.connect(lambda: self.test_button.setEnabled(True))
        QApplication.instance().thread_pool.start(worker)

    def save(self):
        url = self.normalized_url()
        if not url:
            QMessageBox.warning(self, "Conexion", "Escribe la direccion del computador administrador.")
            return
        self.config["last_connected_server"] = url
        self.config["server_url"] = url
        save_config(self.config)
        self.accept()


class ClientLoginDialog(QDialog):
    def __init__(self, api, parent=None):
        super().__init__(parent)
        self.api = api
        self.user = None
        self.setWindowTitle("Ingreso - Punto de venta remoto")
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        form.addRow("Usuario:", self.username)
        form.addRow("Contrasena:", self.password)
        layout.addLayout(form)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        row = QHBoxLayout()
        row.addStretch()
        self.login_button = QPushButton("Ingresar")
        self.login_button.clicked.connect(self.login)
        row.addWidget(self.login_button)
        layout.addLayout(row)
        self.password.returnPressed.connect(self.login)

    def login(self):
        username = self.username.text().strip()
        password = self.password.text()
        if not username or not password:
            self.status_label.setText("Completa usuario y contrasena.")
            return
        self.login_button.setEnabled(False)
        self.status_label.setText("Validando...")
        worker = FunctionWorker(lambda: self.api.login(username, password))
        worker.signals.result.connect(self.login_success)
        worker.signals.error.connect(self.login_error)
        worker.signals.finished.connect(lambda: self.login_button.setEnabled(True))
        QApplication.instance().thread_pool.start(worker)

    def login_success(self, result):
        user = result.get("user") or {}
        if user.get("rol") not in {"ADMIN", "GERENTE", "VENDEDOR"}:
            self.status_label.setText("Este usuario no tiene permiso para registrar ventas.")
            return
        self.user = user
        self.accept()

    def login_error(self, error):
        self.status_label.setText(f"No fue posible ingresar: {error}")


class RemotePOSWindow(QMainWindow):
    """Ventana del cliente remoto que reutiliza EXACTAMENTE la interfaz moderna
    `VentasUIModern`, alimentada por adaptadores que hablan con el servidor LAN
    por la API. El empleado remoto ve la misma UI FERREPRO que el local."""

    def __init__(self, api, config, user):
        super().__init__()
        self.api = api
        self.config = config
        self.user = user
        self.setWindowTitle(
            f"FERREPRO - Punto de venta (remoto) - {config.get('business_name', 'Ferreteria')}")
        self.resize(1500, 880)

        # Adaptadores: misma interfaz que repos/servicios locales, vía API.
        self._remote_db = RemoteDB()
        auth = RemoteAuth(user)
        productos_repo = RemoteProductosRepo(api)
        clientes_repo = RemoteClientesRepo(api)
        ventas_service = RemoteVentasService(api, self._remote_db)
        cuentas_service = RemoteCuentasService(api)

        from ui.ventas_ui_modern import VentasUIModern
        self.pos = VentasUIModern(
            self, ventas_service, productos_repo, clientes_repo, auth,
            self._remote_db,
            cuentas_por_cobrar_service=cuentas_service,
            abonos_ventas_repo=None,
            mezclas_service=None,
            callback_actualizar_caja=None,
        )
        self.setCentralWidget(self.pos)

        self.statusBar().showMessage("Servidor: verificando...")
        btn_server = QPushButton("Cambiar servidor")
        btn_server.setCursor(Qt.PointingHandCursor)
        btn_server.clicked.connect(self.change_server)
        self.statusBar().addPermanentWidget(btn_server)

        self.health_timer = QTimer(self)
        self.health_timer.setInterval(15000)
        self.health_timer.timeout.connect(self.check_health)
        self.health_timer.start()
        self.check_health()

    def check_health(self):
        worker = FunctionWorker(lambda: self.api.health())
        worker.signals.result.connect(
            lambda _: self.statusBar().showMessage("Servidor: conectado"))
        worker.signals.error.connect(
            lambda _: self.statusBar().showMessage("Servidor: SIN CONEXION"))
        QApplication.instance().thread_pool.start(worker)

    def change_server(self):
        dialog = ServerConfigDialog(self.config, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self.config = load_config()
        self.api.set_base_url(
            self.config.get("last_connected_server") or self.config.get("server_url"))
        self.check_health()
        try:
            self.pos.cargar_productos()
        except Exception:
            pass


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from PySide6.QtCore import QThreadPool

    # Mismo tema FERREPRO que la app local (antes el remoto no lo aplicaba).
    app.setStyleSheet(GLOBAL_QSS)
    app.thread_pool = QThreadPool.globalInstance()
    config = load_config()
    url = config.get("last_connected_server") or config.get("server_url")
    api = LocalAPIClient(url, timeout=config.get("client_timeout_seconds", 4))

    try:
        api.health()
    except LocalAPIError:
        dialog = ServerConfigDialog(config)
        if dialog.exec() != QDialog.Accepted:
            return 0
        config = load_config()
        api.set_base_url(config.get("last_connected_server") or config.get("server_url"))

    login = ClientLoginDialog(api)
    if login.exec() != QDialog.Accepted:
        return 0

    window = RemotePOSWindow(api, config, login.user)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
