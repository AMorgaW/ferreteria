# -*- coding: utf-8 -*-
"""
Sistema de Inventario para Ferretería
Punto de entrada principal – PySide6
"""
import sys
import os
import logging

from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                                QHBoxLayout, QLabel, QLineEdit, QPushButton,
                                QStackedWidget, QFrame, QMessageBox, QDialog,
                                QSizePolicy, QSpacerItem, QGridLayout, QScrollArea)
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QFont, QIcon, QPainter, QColor

# Importar componentes del sistema
from database import DatabaseManager
from auth import AuthManager
from repositories.productos_repo import ProductosRepository
from repositories.clientes_repo import ClientesRepository
from repositories.proveedores_repo import ProveedoresRepository
from repositories.inventario_repository import InventarioRepository
from repositories.compras_repo import ComprasRepository

from services.reportes_compras_service import ReportesComprasService
from services.ventas_service import VentasService
from services.alertas_service import AlertasService
from services.reportes_service import ReportesService
from services.caja_service import CajaService
from services.movimientos_service import MovimientosService
from services.deudas_service import DeudasService
from services.cuentas_por_cobrar_service import CuentasPorCobrarService
from services.mezclas_service import MezclasService

from repositories.abonos_compras_repo import AbonosaComprasRepository
from repositories.abonos_ventas_repo import AbonosVentasRepository

from ui_config import COLORS, FONTS, GLOBAL_QSS, make_font


# ────────────────────────────────────────────────────────────
#  Login Dialog
# ────────────────────────────────────────────────────────────
class LoginDialog(QDialog):
    """Ventana de inicio de sesión"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Iniciar Sesión - Sistema Ferretería")
        self.setFixedSize(400, 480)
        self.username = ""
        self.password = ""

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(100)
        header.setStyleSheet(f"background: {COLORS['primary']};")
        h_lay = QVBoxLayout(header)
        h_lay.setAlignment(Qt.AlignCenter)
        icon_lbl = QLabel("🔧")
        icon_lbl.setStyleSheet("font-size: 32pt; color: white; background: transparent;")
        icon_lbl.setAlignment(Qt.AlignCenter)
        h_lay.addWidget(icon_lbl)
        title = QLabel("Sistema Ferretería")
        title.setStyleSheet("font-size: 14pt; font-weight: bold; color: white; background: transparent;")
        title.setAlignment(Qt.AlignCenter)
        h_lay.addWidget(title)
        layout.addWidget(header)

        # Form
        form = QWidget()
        form.setStyleSheet("background: white;")
        fl = QVBoxLayout(form)
        fl.setContentsMargins(40, 30, 40, 30)
        fl.setSpacing(12)

        fl.addWidget(self._label("Iniciar Sesión", 16, True, COLORS['text_primary']))
        fl.addSpacing(10)

        fl.addWidget(self._label("Usuario", 10, False, COLORS['text_secondary']))
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("admin")
        fl.addWidget(self.username_input)

        fl.addWidget(self._label("Contraseña", 10, False, COLORS['text_secondary']))
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("••••••")
        self.password_input.setEchoMode(QLineEdit.Password)
        fl.addWidget(self.password_input)
        fl.addSpacing(10)

        btn = QPushButton("Iniciar Sesión")
        btn.setObjectName("primaryBtn")
        btn.setFixedHeight(42)
        btn.clicked.connect(self._on_login)
        fl.addWidget(btn)
        fl.addSpacing(10)

        info = QLabel("Usuario por defecto:\nusuario: admin\ncontraseña: admin123")
        info.setStyleSheet(f"color: {COLORS['text_light']}; font-size: 9pt; background: transparent;")
        info.setAlignment(Qt.AlignCenter)
        fl.addWidget(info)
        fl.addStretch()

        layout.addWidget(form)

        self.password_input.returnPressed.connect(self._on_login)
        self.username_input.returnPressed.connect(lambda: self.password_input.setFocus())
        self.username_input.setFocus()

    def _label(self, text, size, bold, color):
        lbl = QLabel(text)
        w = "bold" if bold else "normal"
        lbl.setStyleSheet(f"font-size: {size}pt; font-weight: {w}; color: {color}; background: transparent;")
        return lbl

    def _on_login(self):
        self.username = self.username_input.text().strip()
        self.password = self.password_input.text().strip()
        if not self.username or not self.password:
            QMessageBox.warning(self, "Advertencia", "Complete todos los campos")
            return
        self.accept()


# ────────────────────────────────────────────────────────────
#  Main Window
# ────────────────────────────────────────────────────────────
class SistemaFerreteriaApp(QMainWindow):
    """Aplicación principal del sistema"""

    def __init__(self, auth_manager=None):
        super().__init__()
        self.setWindowTitle("Sistema de Inventario - Ferretería Profesional")
        self.resize(1600, 900)
        self.showMaximized()

        # ── Init backend ──
        self.db = DatabaseManager()
        self.productos_repo = ProductosRepository(self.db)
        self.clientes_repo = ClientesRepository(self.db)
        self.proveedores_repo = ProveedoresRepository(self.db)
        self.inventario_repo = InventarioRepository(self.db)
        self.compras_repo = ComprasRepository(self.db)
        self.abonos_repo = AbonosaComprasRepository(self.db.db_name)
        self.auth = auth_manager if auth_manager else AuthManager(self.db)
        self.ventas_service = VentasService(self.db, self.productos_repo,
                                            self.clientes_repo, self.auth)
        self.alertas_service = AlertasService(self.db, self.productos_repo,
                                              self.clientes_repo)
        self.reportes_service = ReportesService(self.db)
        self.reportes_compras_service = ReportesComprasService(self.db, self.proveedores_repo)
        self.deudas_service = DeudasService(self.db.db_name)
        self.cuentas_por_cobrar_service = CuentasPorCobrarService(self.db.db_name)
        self.abonos_ventas_repo = AbonosVentasRepository(self.db.db_name)
        self.caja_service = CajaService(self.db, self.auth)
        self.movimientos_service = MovimientosService(self.db, self.productos_repo,
                                                      self.proveedores_repo, self.auth)
        self.mezclas_service = MezclasService(self.db, self.productos_repo, self.auth)

        # ── Referencias a UIs para conectar callbacks ──
        self.ventas_ui_modern = None
        self.caja_ui = None

        # ── Build UI ──
        self._build_ui()

        # ── Timers ──
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(1000)

        self._alert_timer = QTimer(self)
        self._alert_timer.timeout.connect(self._update_alert_count)
        self._alert_timer.start(60000)

        self._update_clock()
        self._update_alert_count()
        self._run_initial_checks()
        self._show_important_alerts()

        # Default view
        self.mostrar_dashboard()

    # ── UI Construction ──────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Header
        self._build_header(root_layout)

        # Body: sidebar + content
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self._build_sidebar(body)
        self._build_content_area(body)
        root_layout.addLayout(body, 1)

        # Status bar
        self._build_status_bar(root_layout)

    def _build_header(self, parent_layout):
        header = QFrame()
        header.setFixedHeight(48)
        header.setStyleSheet(f"background: {COLORS['bg_primary']}; border-bottom: 1px solid {COLORS['border']};")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 0, 15, 0)
        hl.setSpacing(0)

        # Brand
        brand = QLabel("ProcureFlow")
        brand.setStyleSheet(f"""
            font-size: 13pt; font-weight: bold; color: {COLORS['primary']};
            background: transparent; border: none;
        """)
        hl.addWidget(brand)
        hl.addSpacing(28)

        # Nav links
        nav_items = ['DASHBOARD', 'ORDERS', 'SUPPLIERS', 'INVENTORY', 'ANALYTICS']
        for item in nav_items:
            lbl = QLabel(item)
            if item == 'ORDERS':
                lbl.setStyleSheet(f"""
                    font-size: 8pt; color: {COLORS['text_primary']}; font-weight: 600;
                    padding: 0 10px 0 10px; background: transparent; border: none;
                    border-bottom: 2px solid {COLORS['text_primary']};
                    padding-bottom: 2px;
                """)
            else:
                lbl.setStyleSheet(f"""
                    font-size: 8pt; color: {COLORS['text_light']};
                    padding: 0 10px; background: transparent; border: none;
                """)
            hl.addWidget(lbl)

        hl.addStretch()

        # Alert bell
        self.alertas_btn = QPushButton("🔔")
        self.alertas_btn.setStyleSheet(f"""
            QPushButton {{ font-size: 13pt; border: none; background: transparent; padding: 4px 8px; }}
            QPushButton:hover {{ background: {COLORS['bg_hover']}; border-radius: 6px; }}
        """)
        self.alertas_btn.setCursor(Qt.PointingHandCursor)
        self.alertas_btn.clicked.connect(self.mostrar_alertas)
        hl.addWidget(self.alertas_btn)

        # Settings
        gear = QLabel("⚙")
        gear.setStyleSheet(f"font-size: 13pt; color: {COLORS['text_secondary']}; padding: 0 8px; background: transparent;")
        hl.addWidget(gear)

        # Avatar
        if self.auth.usuario_actual:
            nombre = self.auth.usuario_actual.nombre_completo or 'U'
            initials = ''.join([p[0].upper() for p in nombre.split()[:2]])
        else:
            initials = "U"
        avatar = QLabel(initials)
        avatar.setFixedSize(34, 34)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet(f"""
            background: {COLORS['primary']}; color: white;
            border-radius: 17px; font-size: 9pt; font-weight: 600;
        """)
        hl.addWidget(avatar)

        parent_layout.addWidget(header)

    def _build_sidebar(self, parent_layout):
        sidebar = QFrame()
        sidebar.setFixedWidth(195)
        sidebar.setStyleSheet(f"background: {COLORS['bg_sidebar']}; border-right: 1px solid {COLORS['border']};")
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)

        # Brand section
        brand_w = QWidget()
        brand_w.setStyleSheet("background: transparent;")
        bl = QHBoxLayout(brand_w)
        bl.setContentsMargins(14, 14, 14, 2)

        avatar = QLabel("⚡")
        avatar.setFixedSize(28, 28)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet(f"""
            background: {COLORS['primary']}; color: white;
            border-radius: 14px; font-size: 8pt;
        """)
        bl.addWidget(avatar)

        brand_txt = QWidget()
        brand_txt.setStyleSheet("background: transparent;")
        btl = QVBoxLayout(brand_txt)
        btl.setContentsMargins(7, 0, 0, 0)
        btl.setSpacing(0)
        btl.addWidget(self._side_label("Main Hub", 10, True, COLORS['text_primary']))
        btl.addWidget(self._side_label("Sector 7G", 7, False, COLORS['text_light']))
        bl.addWidget(brand_txt)
        bl.addStretch()
        sl.addWidget(brand_w)

        # Separator
        sl.addWidget(self._h_line())

        # Menu items
        from ui.widgets import HoverButton
        self.menu_buttons = []

        menus = [
            ("📊", "Dashboard", self.mostrar_dashboard, 'ver_dashboard'),
            ("📦", "Productos", self.mostrar_productos, 'gestionar_productos'),
            ("👥", "Clientes", self.mostrar_clientes, 'gestionar_clientes'),
            ("🏪", "Proveedores", self.mostrar_proveedores, 'gestionar_proveedores'),
            ("🛒", "Compras", self.mostrar_compras, 'gestionar_proveedores'),
            ("💰", "Ventas", self.mostrar_ventas, 'realizar_ventas'),
            ("📋", "Movimientos", self.mostrar_movimientos, 'gestionar_movimientos'),
            ("💵", "Caja", self.mostrar_caja, 'realizar_ventas'),
            ("📈", "Reportes", self.mostrar_reportes, 'ver_reportes'),
            ("👤", "Usuarios", self.mostrar_usuarios, 'crear_usuario'),
            ("⚙️", "Configuración", self.mostrar_configuracion, 'configurar_sistema'),
        ]

        menu_container = QWidget()
        menu_container.setStyleSheet("background: transparent;")
        mcl = QVBoxLayout(menu_container)
        mcl.setContentsMargins(6, 4, 6, 4)
        mcl.setSpacing(0)

        for icon, texto, comando, permiso in menus:
            if permiso and not self.auth.tiene_permiso(permiso):
                continue

            def make_cmd(cmd=comando, txt=texto):
                def wrapped():
                    self._highlight_menu_button(txt)
                    cmd()
                return wrapped

            btn = HoverButton(menu_container, text=texto, icon=icon,
                              font_size=9,
                              bg=COLORS['bg_primary'], fg=COLORS['text_secondary'],
                              hover_bg=COLORS['bg_hover'], hover_fg=COLORS['text_primary'],
                              active_bg=COLORS['primary_light'], active_fg=COLORS['primary'],
                              padx=14, pady=7,
                              command=make_cmd())
            mcl.addWidget(btn)
            self.menu_buttons.append((texto, btn))

        sl.addWidget(menu_container)
        sl.addStretch()

        # Bottom separator
        sl.addWidget(self._h_line())

        # New Requisition
        btn_new = QPushButton("  New Requisition")
        btn_new.setObjectName("primaryBtn")
        btn_new.setCursor(Qt.PointingHandCursor)
        btn_new.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['primary']}; color: white;
                border: none; border-radius: 10px;
                padding: 10px; font-weight: 600; font-size: 9pt;
                margin: 8px 12px;
            }}
            QPushButton:hover {{ background: {COLORS['primary_dark']}; }}
        """)
        btn_new.clicked.connect(self.mostrar_compras)
        sl.addWidget(btn_new)

        # Support + Log Out
        for icon_txt, label, cmd in [("🛟 Support", None, None), ("🚪 Log Out", None, self.cerrar_sesion)]:
            b = QPushButton(icon_txt)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {COLORS['text_light']};
                    border: none; text-align: left; padding: 6px 20px; font-size: 8pt;
                }}
                QPushButton:hover {{ background: {COLORS['danger_light']}; color: {COLORS['danger']}; }}
            """)
            if cmd:
                b.clicked.connect(cmd)
            sl.addWidget(b)

        sl.addSpacing(4)
        parent_layout.addWidget(sidebar)

    def _build_content_area(self, parent_layout):
        self.content_stack = QStackedWidget()
        self.content_stack.setStyleSheet(f"background: {COLORS['bg_secondary']};")
        parent_layout.addWidget(self.content_stack, 1)

    def _build_status_bar(self, parent_layout):
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {COLORS['border']};")
        parent_layout.addWidget(line)

        bar = QFrame()
        bar.setFixedHeight(28)
        bar.setStyleSheet(f"background: {COLORS['bg_secondary']};")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(15, 0, 15, 0)

        self.status_label = QLabel("✓ Sistema listo")
        self.status_label.setStyleSheet(f"font-size: 8pt; color: {COLORS['text_light']}; background: transparent;")
        bl.addWidget(self.status_label)
        bl.addStretch()

        self.clock_label = QLabel("")
        self.clock_label.setStyleSheet(f"font-size: 8pt; color: {COLORS['text_light']}; background: transparent;")
        bl.addWidget(self.clock_label)

        parent_layout.addWidget(bar)

    # ── Helpers ──────────────────────────────────────────────
    def _side_label(self, text, size, bold, color):
        lbl = QLabel(text)
        w = "bold" if bold else "normal"
        lbl.setStyleSheet(f"font-size: {size}pt; font-weight: {w}; color: {color}; background: transparent; border: none;")
        return lbl

    def _h_line(self):
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {COLORS['border']}; margin: 6px 12px;")
        return line

    def _highlight_menu_button(self, active_text):
        for texto, btn in self.menu_buttons:
            btn.set_active(texto == active_text)

    def _set_content(self, widget):
        """Reemplaza el contenido actual con un nuevo widget."""
        # Remove old widgets
        while self.content_stack.count():
            old = self.content_stack.widget(0)
            self.content_stack.removeWidget(old)

            # Limpiar referencias a widgets que serán destruidos
            if old is self.ventas_ui_modern:
                self.ventas_ui_modern = None
            if old is self.caja_ui:
                self.caja_ui = None

            old.deleteLater()
        self.content_stack.addWidget(widget)
        self.content_stack.setCurrentWidget(widget)

    def _widget_vivo(self, widget) -> bool:
        """Valida que un widget Qt siga vivo y accesible."""
        if widget is None:
            return False
        try:
            widget.objectName()
            return True
        except RuntimeError:
            return False

    def _conectar_signals_venta_caja(self):
        """Reconecta los signals entre ventas y caja"""
        if not self._widget_vivo(self.ventas_ui_modern):
            self.ventas_ui_modern = None
            return
        if not self._widget_vivo(self.caja_ui):
            self.caja_ui = None
            return

        if self.ventas_ui_modern and self.caja_ui:
            try:
                # Desconectar conexiones antiguas si existen
                self.ventas_ui_modern.venta_completada.disconnect()
            except Exception:
                pass
            # Conectar signal de venta completada a caja
            self.ventas_ui_modern.venta_completada.connect(self.caja_ui.actualizar_resumen)

    # ── Timers ───────────────────────────────────────────────
    def _update_clock(self):
        from datetime import datetime
        self.clock_label.setText(datetime.now().strftime("%d/%m/%Y %H:%M:%S"))

    def _update_alert_count(self):
        try:
            alertas = self.alertas_service.obtener_alertas(solo_no_leidas=True)
            count = len(alertas)
            if count > 0:
                self.alertas_btn.setText(f"🔔 {count}")
                if count > 10:
                    self.alertas_btn.setStyleSheet(f"""
                        QPushButton {{ font-size: 13pt; border: none; background: transparent;
                                     padding: 4px 8px; color: {COLORS['danger']}; }}
                        QPushButton:hover {{ background: {COLORS['bg_hover']}; border-radius: 6px; }}
                    """)
                else:
                    self.alertas_btn.setStyleSheet(f"""
                        QPushButton {{ font-size: 13pt; border: none; background: transparent;
                                     padding: 4px 8px; }}
                        QPushButton:hover {{ background: {COLORS['bg_hover']}; border-radius: 6px; }}
                    """)
            else:
                self.alertas_btn.setText("🔔")
        except Exception as e:
            print(f"Error actualizando alertas: {e}")

    def _run_initial_checks(self):
        try:
            resultados = self.alertas_service.ejecutar_verificaciones_diarias()
            total = sum(resultados.values())
            if total > 0:
                self.status_label.setText(f"⚠ {total} nuevas alertas detectadas")
                self._update_alert_count()
        except Exception as e:
            print(f"Error en verificaciones: {e}")

    def _show_important_alerts(self):
        try:
            from ui.alertas_ui import VentanaAlertasPopup
            VentanaAlertasPopup(self, self.alertas_service)
        except Exception as e:
            print(f"Error mostrando alertas: {e}")

    def cerrar_sesion(self):
        resp = QMessageBox.question(self, "Confirmar",
                                    "¿Está seguro que desea cerrar sesión?",
                                    QMessageBox.Yes | QMessageBox.No)
        if resp == QMessageBox.Yes:
            self.auth.logout()
            self.close()
            show_login_and_run(reuse_app=True)

    # ── Module views ─────────────────────────────────────────
    def mostrar_dashboard(self):
        from ui.dashboard_ui import DashboardUI
        w = DashboardUI(self.content_stack, self.reportes_service,
                        self.alertas_service, self.auth,
                        self.cuentas_por_cobrar_service)
        self._set_content(w)

    def mostrar_productos(self):
        from ui.productos_ui import ProductosUI
        w = ProductosUI(self.content_stack, self.productos_repo, self.auth,
                        self.proveedores_repo)
        self._set_content(w)

    def mostrar_clientes(self):
        from ui.clientes_ui import ClientesUI
        w = ClientesUI(self.content_stack, self.clientes_repo, self.auth,
                       self.cuentas_por_cobrar_service, self.abonos_ventas_repo)
        self._set_content(w)

    def mostrar_proveedores(self):
        from ui.proveedores_ui import ProveedoresUI
        w = ProveedoresUI(self.content_stack, self.proveedores_repo, self.auth)
        self._set_content(w)

    def mostrar_compras(self):
        try:
            from ui.compras_ui import ComprasUI
            w = ComprasUI(self.content_stack, self.db, self.compras_repo,
                          self.proveedores_repo, self.productos_repo, self.auth,
                          deudas_service=self.deudas_service,
                          abonos_repo=self.abonos_repo)
            self._set_content(w)
        except Exception as e:
            QMessageBox.critical(self, "Error",
                                 f"Error al cargar módulo de compras:\n{str(e)}")
            import traceback
            traceback.print_exc()

    def mostrar_ventas(self):
        from ui.ventas_ui_modern import VentasUIModern
        # Crear función para actualizar caja - usar la referencia guardada si existe
        def actualizar_caja_desde_venta():
            if self._widget_vivo(self.caja_ui):
                try:
                    self.caja_ui.actualizar_resumen()
                except RuntimeError as e:
                    # Ignorar si el widget fue eliminado
                    if "already deleted" in str(e):
                        print("[MAIN] Caja UI fue eliminada, ignorando actualización")
                        self.caja_ui = None
                    else:
                        raise
        
        self.ventas_ui_modern = VentasUIModern(self.content_stack, self.ventas_service,
                           self.productos_repo, self.clientes_repo, self.auth,
                           self.db, self.cuentas_por_cobrar_service,
                           self.abonos_ventas_repo, self.mezclas_service,
                           callback_actualizar_caja=actualizar_caja_desde_venta)
        self._set_content(self.ventas_ui_modern)
        self._conectar_signals_venta_caja()

    def mostrar_movimientos(self):
        from ui.movimientos_ui import MovimientosUI
        w = MovimientosUI(self.content_stack, self.movimientos_service,
                          self.productos_repo, self.proveedores_repo, self.auth,
                          self.db, self.inventario_repo, self.alertas_service,
                          self.compras_repo, self.clientes_repo)
        self._set_content(w)

    def mostrar_caja(self):
        from ui.caja_ui import CajaUI
        self.caja_ui = CajaUI(self.content_stack, self.caja_service, self.auth,
                    self.abonos_repo, self.compras_repo)
        self._set_content(self.caja_ui)
        self._conectar_signals_venta_caja()

    def mostrar_reportes(self):
        from ui.reportes_ui import ReportesUI
        w = ReportesUI(self.content_stack, self.reportes_service, self.auth,
                       self.reportes_compras_service, self.proveedores_repo,
                       self.productos_repo)
        self._set_content(w)

    def mostrar_usuarios(self):
        from ui.usuarios_ui import UsuariosUI
        w = UsuariosUI(self.content_stack, self.auth)
        self._set_content(w)

    def mostrar_configuracion(self):
        w = QWidget()
        w.setStyleSheet(f"background: {COLORS['bg_secondary']};")
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("⚙️ Configuración del Sistema"))
        lay.addWidget(QLabel("Módulo en construcción..."))
        lay.addStretch()
        self._set_content(w)

    def mostrar_alertas(self):
        from ui.alertas_ui import AlertasUI
        w = AlertasUI(self.content_stack, self.alertas_service)
        self._set_content(w)


# ────────────────────────────────────────────────────────────
#  Entry point
# ────────────────────────────────────────────────────────────
_app_instance = None


def show_login_and_run(reuse_app=False):
    global _app_instance
    if not reuse_app:
        _app_instance = QApplication(sys.argv)
        _app_instance.setStyleSheet(GLOBAL_QSS)

    try:
        db = DatabaseManager()
        auth = AuthManager(db)
    except Exception as e:
        QMessageBox.critical(None, "Error de Conexión",
                             f"No se pudo conectar a la base de datos:\n\n{str(e)}\n\n"
                             "Verifica que el proyecto de Supabase esté activo en supabase.com")
        if not reuse_app:
            sys.exit(1)
        return

    dialog = LoginDialog()
    if dialog.exec() != QDialog.Accepted:
        if not reuse_app:
            sys.exit(0)
        return

    exito, mensaje, usuario = auth.login(dialog.username, dialog.password)
    if not exito:
        QMessageBox.critical(None, "Error", mensaje)
        show_login_and_run(reuse_app=True)
        return

    QMessageBox.information(None, "Bienvenido",
                            f"Bienvenido, {usuario.nombre_completo}!\nRol: {usuario.rol}")

    window = SistemaFerreteriaApp(auth_manager=auth)
    window.show()

    if not reuse_app:
        sys.exit(_app_instance.exec())


def main():
    try:
        show_login_and_run()
    except Exception as e:
        QMessageBox.critical(None, "Error Fatal",
                             f"Error al iniciar el sistema:\n{str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()