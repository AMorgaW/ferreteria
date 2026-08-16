# -*- coding: utf-8 -*-
"""
Sistema de Inventario para Ferretería
Punto de entrada principal – PySide6
"""
import sys
import os
import logging

# Logs Unicode-safe en consolas Windows (cp1252) y modo congelado sin consola.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                                QHBoxLayout, QLabel, QLineEdit, QPushButton,
                                QStackedWidget, QFrame, QMessageBox, QDialog,
                                QSizePolicy, QSpacerItem, QGridLayout, QScrollArea,
                                QGraphicsOpacityEffect)
from PySide6.QtCore import Qt, QTimer, QSize, QThreadPool, QPropertyAnimation, QEasingCurve
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

from ui_config import COLORS, FONTS, DIMENSIONS, GLOBAL_QSS, make_font
from ui.widgets import make_line_icon
from ui.async_worker import FunctionWorker
from local_first_config import load_config
from local_server_manager import LocalServerManager


# ────────────────────────────────────────────────────────────
#  Login Dialog
# ────────────────────────────────────────────────────────────
class LoginDialog(QDialog):
    """Ventana de inicio de sesión"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Iniciar Sesión - FERREPRO")
        self.setFixedSize(440, 600)
        self.setStyleSheet(f"QDialog {{ background: {COLORS['sidebar_bg']}; }}")
        self.username = ""
        self.password = ""

        self._build_ui()

    def _build_ui(self):
        C = COLORS
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 30, 36, 28)
        layout.setSpacing(0)

        # ── Marca FERREPRO ──
        logo = QLabel("⬡")
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet(f"font-size: 46pt; color: {C['accent']}; background: transparent;")
        layout.addWidget(logo)

        brand = QLabel("FERRE<span style='color:%s'>PRO</span>" % C['accent'])
        brand.setTextFormat(Qt.RichText)
        brand.setAlignment(Qt.AlignCenter)
        brand.setStyleSheet("font-size: 26pt; font-weight: 800; color: white; "
                            "letter-spacing: 2px; background: transparent;")
        layout.addWidget(brand)

        tagline = QLabel("S I S T E M A   D E   I N V E N T A R I O")
        tagline.setAlignment(Qt.AlignCenter)
        tagline.setStyleSheet(f"font-size: 7pt; font-weight: 600; color: {C['sidebar_fg']}; "
                              "letter-spacing: 1px; background: transparent;")
        layout.addWidget(tagline)
        layout.addSpacing(26)

        # ── Tarjeta del formulario ──
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{ background: {C['sidebar_bg_alt']}; border: 1px solid {C['sidebar_border']};
                      border-radius: 16px; }}
        """)
        fl = QVBoxLayout(card)
        fl.setContentsMargins(28, 26, 28, 26)
        fl.setSpacing(8)

        input_qss = f"""
            QLineEdit {{ background: {C['sidebar_bg']}; color: white;
                border: 1px solid {C['sidebar_border']}; border-radius: 10px;
                padding: 11px 14px; font-size: 11pt; }}
            QLineEdit:focus {{ border: 2px solid {C['accent']}; padding: 10px 13px; }}
        """

        fl.addWidget(self._field_label("👤  Usuario"))
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Ingresa tu usuario")
        self.username_input.setStyleSheet(input_qss)
        self.username_input.setMinimumHeight(44)
        fl.addWidget(self.username_input)
        fl.addSpacing(8)

        fl.addWidget(self._field_label("🔒  Contraseña"))
        pwd_row = QFrame()
        pwd_row.setStyleSheet("background: transparent; border: none;")
        prl = QHBoxLayout(pwd_row)
        prl.setContentsMargins(0, 0, 0, 0)
        prl.setSpacing(0)
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Ingresa tu contraseña")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setStyleSheet(input_qss)
        self.password_input.setMinimumHeight(44)
        prl.addWidget(self.password_input)
        self.toggle_pwd = QPushButton("🙈")
        self.toggle_pwd.setCursor(Qt.PointingHandCursor)
        self.toggle_pwd.setFixedSize(38, 44)
        self.toggle_pwd.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; color: {C['sidebar_fg']}; font-size: 12pt; }}"
            f"QPushButton:hover {{ color: {C['accent']}; }}")
        self.toggle_pwd.clicked.connect(self._toggle_password)
        prl.addWidget(self.toggle_pwd)
        fl.addWidget(pwd_row)
        fl.addSpacing(18)

        btn = QPushButton("Iniciar Sesión")
        btn.setObjectName("primaryBtn")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setMinimumHeight(48)
        btn.setStyleSheet(
            f"QPushButton {{ background: {C['accent']}; color: {C['on_accent']}; border: none; "
            f"border-radius: 11px; font-size: 12pt; font-weight: 800; }}"
            f"QPushButton:hover {{ background: {C['accent_hover']}; }}"
            f"QPushButton:pressed {{ background: {C['accent_dark']}; }}")
        btn.clicked.connect(self._on_login)
        fl.addWidget(btn)
        fl.addSpacing(10)

        forgot = QLabel("🛡  ¿Olvidaste tu contraseña?")
        forgot.setAlignment(Qt.AlignCenter)
        forgot.setStyleSheet(f"color: {C['accent']}; font-size: 9pt; font-weight: 600; background: transparent; border: none;")
        fl.addWidget(forgot)

        layout.addWidget(card)
        layout.addStretch()

        try:
            from version import __version__ as _ver
        except Exception:
            _ver = ""
        hint = QLabel(f"Acceso restringido · Use sus credenciales asignadas   ·   v{_ver}")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(f"color: {C['text_light']}; font-size: 8pt; background: transparent;")
        layout.addWidget(hint)

        self.password_input.returnPressed.connect(self._on_login)
        self.username_input.returnPressed.connect(lambda: self.password_input.setFocus())
        self.username_input.setFocus()

    def _field_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {COLORS['accent']}; font-size: 11pt; font-weight: 700; "
                          "background: transparent; border: none;")
        return lbl

    def _toggle_password(self):
        if self.password_input.echoMode() == QLineEdit.Password:
            self.password_input.setEchoMode(QLineEdit.Normal)
            self.toggle_pwd.setText("👁")
        else:
            self.password_input.setEchoMode(QLineEdit.Password)
            self.toggle_pwd.setText("🙈")

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

    def __init__(self, auth_manager=None, server_manager=None):
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
        # Permitir que el repositorio de productos registre auditoría
        self.productos_repo.auth = self.auth
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
        self._thread_pool = QThreadPool.globalInstance()
        self.local_first_config = load_config()
        # Reutiliza el manager que ya pudo haberse arrancado antes del login.
        self.local_server_manager = server_manager or LocalServerManager(self.local_first_config)
        self._servicios_retry = 0

        # ── Referencias a UIs para conectar callbacks ──
        self.ventas_ui_modern = None
        self.caja_ui = None

        # ── Sincronización periódica: rastrear la sección visible para poder
        #    refrescarla automáticamente tras descargar cambios de la nube. Se
        #    envuelven los mostrar_* (sin tocar cada método). ──
        self._seccion_actual_fn = None
        self._pull_en_curso = False
        self._pull_timer = None
        for _nombre in ('mostrar_dashboard', 'mostrar_productos', 'mostrar_clientes',
                        'mostrar_proveedores', 'mostrar_compras', 'mostrar_ventas',
                        'mostrar_movimientos', 'mostrar_caja', 'mostrar_reportes',
                        'mostrar_usuarios', 'mostrar_configuracion'):
            _orig = getattr(self, _nombre, None)
            if _orig is None:
                continue

            def _wrap(*a, _orig=_orig, **k):
                self._seccion_actual_fn = _orig
                return _orig(*a, **k)

            setattr(self, _nombre, _wrap)

        # ── Build UI ──
        self._build_ui()

        # ── Timers ──
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(1000)

        self._alert_timer = QTimer(self)
        self._alert_timer.timeout.connect(self._update_alert_count_async)
        self._alert_timer.start(60000)

        self._update_clock()
        QTimer.singleShot(300, self._iniciar_servicios_local_first)
        QTimer.singleShot(800, self._auto_backup_async)
        QTimer.singleShot(500, self._preload_common_caches)
        QTimer.singleShot(1200, self._update_alert_count_async)
        QTimer.singleShot(2500, self._run_initial_checks_async)
        QTimer.singleShot(4500, self._show_important_alerts)

        # Default view by permission. Employees/sellers must enter directly
        # into POS and must not see the administrator dashboard.
        self._mostrar_vista_inicial()

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

    def _mostrar_vista_inicial(self):
        if self.auth.tiene_permiso('ver_dashboard'):
            self.mostrar_dashboard()
            return
        if self.auth.tiene_permiso('realizar_ventas'):
            self.mostrar_ventas()
            self._highlight_menu_button("Ventas")
            return
        self.mostrar_productos()

    def _build_header(self, parent_layout):
        C = COLORS
        header = QFrame()
        header.setFixedHeight(DIMENSIONS['header_height'])
        header.setStyleSheet(
            f"background: {C['sidebar_bg']}; border: none;"
            f" border-bottom: 1px solid {C['sidebar_border']};"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 0, 22, 0)
        hl.setSpacing(10)

        hl.addStretch()

        # Chip de fecha
        from datetime import datetime as _dt
        meses = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
        hoy = _dt.now()
        fecha_txt = f"{hoy.day} {meses[hoy.month - 1]} {hoy.year}"
        date_chip = QFrame()
        date_chip.setStyleSheet(f"""
            QFrame {{ background: {C['sidebar_hover_bg']};
                      border: 1px solid {C['sidebar_border']}; border-radius: 8px; }}
        """)
        date_layout = QHBoxLayout(date_chip)
        date_layout.setContentsMargins(11, 6, 12, 6)
        date_layout.setSpacing(7)
        date_icon = QLabel()
        date_icon.setPixmap(make_line_icon('calendar', '#D8E1EC', 18).pixmap(18, 18))
        date_icon.setStyleSheet("background: transparent; border: none;")
        date_text = QLabel(fecha_txt)
        date_text.setStyleSheet(
            "color: #E5EBF3; background: transparent; border: none;"
            " font-size: 9pt; font-weight: 500;"
        )
        date_layout.addWidget(date_icon)
        date_layout.addWidget(date_text)
        hl.addWidget(date_chip)

        # Campana de alertas
        self.alertas_btn = QPushButton("")
        self.alertas_btn.setIcon(make_line_icon('alertas', '#D8E1EC', 20))
        self.alertas_btn.setIconSize(QSize(20, 20))
        self.alertas_btn.setFixedHeight(36)
        self.alertas_btn.setStyleSheet(f"""
            QPushButton {{ font-size: 8pt; color: white; border: none;
                           background: transparent; padding: 6px 9px; border-radius: 8px; }}
            QPushButton:hover {{ background: {C['sidebar_hover_bg']}; }}
            QPushButton:pressed {{ background: {C['primary_dark']}; }}
        """)
        self.alertas_btn.setCursor(Qt.PointingHandCursor)
        self.alertas_btn.clicked.connect(self.mostrar_alertas)
        hl.addWidget(self.alertas_btn)

        # Ajustes
        gear = QPushButton("")
        gear.setIcon(make_line_icon('settings', '#D8E1EC', 21))
        gear.setIconSize(QSize(21, 21))
        gear.setFixedSize(38, 36)
        gear.setCursor(Qt.PointingHandCursor)
        gear.setStyleSheet(f"""
            QPushButton {{ border: none; background: transparent; padding: 6px; border-radius: 8px; }}
            QPushButton:hover {{ background: {C['sidebar_hover_bg']}; }}
            QPushButton:pressed {{ background: {C['primary_dark']}; }}
        """)
        gear.clicked.connect(self.mostrar_configuracion)
        hl.addWidget(gear)

        # Usuario (nombre + rol + avatar)
        if self.auth.usuario_actual:
            nombre = self.auth.usuario_actual.nombre_completo or 'Usuario'
            rol = (self.auth.usuario_actual.rol or '').capitalize()
            initials = ''.join([p[0].upper() for p in nombre.split()[:2]]) or 'U'
        else:
            nombre, rol, initials = "Usuario", "", "U"

        user_box = QWidget()
        user_box.setStyleSheet("background: transparent;")
        ubl = QHBoxLayout(user_box)
        ubl.setContentsMargins(12, 0, 0, 0)
        ubl.setSpacing(10)
        name_w = QWidget()
        name_w.setStyleSheet("background: transparent;")
        nwl = QVBoxLayout(name_w)
        nwl.setContentsMargins(0, 0, 0, 0)
        nwl.setSpacing(0)
        n_lbl = QLabel(nombre)
        n_lbl.setStyleSheet("font-size: 9pt; font-weight: 500; color: #ffffff; background: transparent; border: none;")
        n_lbl.setAlignment(Qt.AlignRight)
        r_lbl = QLabel(rol)
        r_lbl.setStyleSheet("font-size: 7pt; color: #AEBBCB; background: transparent; border: none;")
        r_lbl.setAlignment(Qt.AlignRight)
        nwl.addWidget(n_lbl)
        nwl.addWidget(r_lbl)
        ubl.addWidget(name_w)

        avatar = QLabel(initials)
        avatar.setFixedSize(34, 34)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet(f"""
            background: {C['accent']}; color: white;
            border-radius: 17px; font-size: 9pt; font-weight: 500;
        """)
        ubl.addWidget(avatar)
        hl.addWidget(user_box)

        parent_layout.addWidget(header)

    def _build_sidebar(self, parent_layout):
        C = COLORS
        sidebar = QFrame()
        sidebar.setFixedWidth(DIMENSIONS['sidebar_width'])
        sidebar.setStyleSheet(f"background: {C['sidebar_bg']}; border: none;")
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)

        # Identidad Ferretería El Adobe
        brand_w = QWidget()
        brand_w.setStyleSheet("background: transparent;")
        bl = QHBoxLayout(brand_w)
        bl.setContentsMargins(18, 18, 16, 14)
        bl.setSpacing(12)

        avatar = QLabel()
        avatar.setPixmap(make_line_icon('brand', C['accent'], 46).pixmap(46, 46))
        avatar.setFixedSize(46, 46)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet("background: transparent; border: none;")
        bl.addWidget(avatar)

        brand_txt = QWidget()
        brand_txt.setStyleSheet("background: transparent;")
        btl = QVBoxLayout(brand_txt)
        btl.setContentsMargins(0, 0, 0, 0)
        btl.setSpacing(1)
        brand_lbl = QLabel("FERRETERÍA\nEL ADOBE")
        brand_lbl.setStyleSheet("font-size: 12pt; font-weight: 500; color: white; "
                                "letter-spacing: 0.7px; background: transparent; border: none;")
        btl.addWidget(brand_lbl)
        btl.addWidget(self._side_label("INVENTARIO Y GESTIÓN", 6, False, C['sidebar_fg']))
        bl.addWidget(brand_txt)
        bl.addStretch()
        sl.addWidget(brand_w)

        # Separator
        sl.addWidget(self._side_line())

        # Menu items
        from ui.widgets import HoverButton
        self.menu_buttons = []

        menus = [
            ("dashboard", "Dashboard", self.mostrar_dashboard, 'ver_dashboard'),
            ("productos", "Productos", self.mostrar_productos, 'gestionar_productos'),
            ("productos", "Regularizar barcodes", self.mostrar_regularizar_barcodes, 'gestionar_productos'),
            ("movimientos", "Importar inventario", self.mostrar_importar_inventario, 'gestionar_productos'),
            ("clientes", "Clientes", self.mostrar_clientes, 'gestionar_clientes'),
            ("proveedores", "Proveedores", self.mostrar_proveedores, 'gestionar_proveedores'),
            ("compras", "Compras", self.mostrar_compras, 'gestionar_proveedores'),
            ("ventas", "Ventas", self.mostrar_ventas, 'realizar_ventas'),
            ("movimientos", "Movimientos", self.mostrar_movimientos, 'gestionar_movimientos'),
            ("caja", "Caja", self.mostrar_caja, 'realizar_ventas'),
            ("reportes", "Reportes", self.mostrar_reportes, 'ver_reportes'),
            ("usuarios", "Usuarios", self.mostrar_usuarios, 'crear_usuario'),
            ("configuracion", "Configuración", self.mostrar_configuracion, 'configurar_sistema'),
        ]

        menu_container = QWidget()
        menu_container.setStyleSheet("background: transparent;")
        mcl = QVBoxLayout(menu_container)
        mcl.setContentsMargins(12, 6, 12, 6)
        mcl.setSpacing(3)

        for icon, texto, comando, permiso in menus:
            if permiso and not self.auth.tiene_permiso(permiso):
                continue

            def make_cmd(cmd=comando, txt=texto):
                def wrapped():
                    self._highlight_menu_button(txt)
                    cmd()
                return wrapped

            btn = HoverButton(menu_container, text=texto, icon=icon,
                              font_size=10,
                              bg='transparent', fg=C['sidebar_fg'],
                              hover_bg=C['sidebar_hover_bg'], hover_fg=C['sidebar_hover_fg'],
                              active_bg=C['sidebar_active_bg'], active_fg=C['sidebar_active_fg'],
                              padx=14, pady=10,
                              command=make_cmd())
            mcl.addWidget(btn)
            self.menu_buttons.append((texto, btn))
            if texto == "Dashboard":
                btn.set_active(True)

        sl.addWidget(menu_container)
        sl.addStretch()

        # Bottom separator
        sl.addWidget(self._side_line())

        # Nueva Requisición (CTA naranja de marca)
        btn_new = QPushButton("＋  Nueva Requisición")
        btn_new.setCursor(Qt.PointingHandCursor)
        btn_new.setStyleSheet(f"""
            QPushButton {{
                background: {C['accent']}; color: {C['on_accent']};
                border: 1px solid #F07A56; border-radius: 9px;
                padding: 11px; font-weight: 500; font-size: 9pt;
                margin: 10px 14px 8px 14px;
            }}
            QPushButton:hover {{ background: {C['accent_hover']}; }}
            QPushButton:pressed {{ background: {C['accent_dark']}; }}
        """)
        btn_new.clicked.connect(self.mostrar_compras)
        sl.addWidget(btn_new)

        # Soporte + Cerrar Sesión
        for icon_key, text, cmd in [("support", "Soporte", None),
                                    ("salir", "Cerrar Sesión", self.cerrar_sesion)]:
            b = HoverButton(sidebar, text=text, icon=icon_key,
                            font_size=9, bg='transparent', fg=C['sidebar_fg'],
                            hover_bg=C['sidebar_hover_bg'], hover_fg='white',
                            padx=14, pady=8, command=cmd)
            b.setContentsMargins(12, 0, 12, 0)
            sl.addWidget(b)

        sl.addSpacing(8)
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
        bar.setFixedHeight(DIMENSIONS['statusbar_height'])
        bar.setStyleSheet(f"background: white;")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(15, 0, 15, 0)

        self.status_label = QLabel("✓ Sistema listo")
        self.status_label.setStyleSheet(f"font-size: 8pt; color: {COLORS['success_dark']}; background: transparent;")
        bl.addWidget(self.status_label)
        bl.addStretch()

        self.clock_label = QLabel("")
        self.clock_label.setStyleSheet(f"font-size: 8pt; color: {COLORS['text_secondary']}; background: transparent;")
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

    def _side_line(self):
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {COLORS['sidebar_border']}; margin: 6px 14px;")
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
        self._fade_in(widget)

        # Repintado forzado diferido: en secciones pesadas (Reportes) el layout
        # puede terminar DESPUÉS del fade; en equipos con compositor/GPU
        # defectuoso eso deja un fotograma viejo en pantalla aunque el contenido
        # ya sea el nuevo. Forzamos un repaint real cuando todo se ha asentado.
        def _forzar_repaint():
            try:
                widget.setGraphicsEffect(None)
                widget.repaint()
                widget.update()
                self.content_stack.repaint()
            except RuntimeError:
                pass
        QTimer.singleShot(350, _forzar_repaint)

    def _fade_in(self, widget):
        """Desvanecimiento sutil al cargar una sección (220ms). El efecto se
        retira al terminar para no interferir con las sombras de las tarjetas."""
        try:
            effect = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(effect)
            effect.setOpacity(0.0)
            anim = QPropertyAnimation(effect, b"opacity", self)
            anim.setDuration(220)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)

            def _cleanup():
                try:
                    widget.setGraphicsEffect(None)
                    # Forzar un repintado REAL tras retirar el efecto. En equipos
                    # con compositor/GPU defectuoso el QGraphicsOpacityEffect puede
                    # dejar un fotograma viejo cacheado (sobre todo en la sección
                    # más pesada, Reportes); este repaint garantiza que la pantalla
                    # muestre el contenido actual y no un frame obsoleto.
                    widget.repaint()
                    widget.update()
                    self.content_stack.repaint()
                except RuntimeError:
                    pass

            anim.finished.connect(_cleanup)
            self._content_anim = anim  # mantener referencia viva
            anim.start()
        except Exception:
            pass

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
            count = self.alertas_service.contar_no_leidas()
            if count > 0:
                self.alertas_btn.setIcon(make_line_icon('alertas', '#FFFFFF', 20))
                self.alertas_btn.setText(str(count))
                if count > 10:
                    self.alertas_btn.setStyleSheet(f"""
                        QPushButton {{ font-size: 8pt; border: none; background: {COLORS['danger']};
                                     padding: 5px 8px; color: white; border-radius: 8px; }}
                        QPushButton:hover {{ background: {COLORS['danger_dark']}; }}
                    """)
                else:
                    self.alertas_btn.setStyleSheet(f"""
                        QPushButton {{ font-size: 8pt; border: none; background: {COLORS['accent']};
                                     padding: 5px 8px; color: white; border-radius: 8px; }}
                        QPushButton:hover {{ background: {COLORS['accent_hover']}; }}
                    """)
            else:
                self.alertas_btn.setIcon(make_line_icon('alertas', '#D8E1EC', 20))
                self.alertas_btn.setText("")
        except Exception as e:
            print(f"Error actualizando alertas: {e}")

    # ── Respaldo automático de la base de datos al iniciar ──
    def _auto_backup_async(self):
        def _run():
            try:
                import backup_manager
                creado = backup_manager.auto_backup(keep=10, max_por_dia=1)
                return creado
            except Exception as exc:
                print(f"[BACKUP] No se pudo crear respaldo: {exc}")
                return None
        worker = FunctionWorker(_run)
        worker.signals.result.connect(
            lambda ruta: print(f"[BACKUP] Respaldo creado: {ruta}") if ruta else None)
        self._thread_pool.start(worker)

    # ── Local-first: sincronización con Supabase (push cada 10 s) ──
    def _iniciar_servicios_local_first(self):
        """Arranca la sincronización con Supabase DENTRO de la app (push de la
        cola cada 10 s), sin servidor LAN ni IP. La descarga inicial (pull) ya
        se hizo al iniciar sesión. Nunca bloquea la interfaz."""
        modo = os.environ.get("DB_MODE", "local").strip().lower()
        if modo not in ("local", "sqlite", "server"):
            # Modo remoto (diagnóstico): la app ya va directo a Supabase.
            self.status_label.setText("✓ Conectado a la base central (Supabase)")
            return
        if not (self.local_first_config.get("cloud_sync_enabled", True)
                and os.environ.get("SUPABASE_URI")):
            self.status_label.setText("Modo local (sin sincronización con la nube)")
            return
        try:
            from local_sync import get_service
            from local_first_db import DEFAULT_DB_PATH
            get_service(DEFAULT_DB_PATH).start_background()  # PUSH cada 10 s
            self.status_label.setText(
                "✓ Local-first activo — cambios se suben a Supabase cada 10 s")
        except Exception as exc:
            self.status_label.setText(f"⚠ Sincronización no disponible: {exc}")

        # ── PULL periódico: descarga automática de cambios de la nube ──
        if self._pull_timer is None:
            try:
                seg = int(self.local_first_config.get("pull_interval_seconds", 45))
            except Exception:
                seg = 45
            self._pull_timer = QTimer(self)
            self._pull_timer.setInterval(max(15, seg) * 1000)
            self._pull_timer.timeout.connect(self._chequear_cambios_nube)
            self._pull_timer.start()
            # Primer chequeo pronto (por si el admin ya hizo cambios recién).
            QTimer.singleShot(8000, self._chequear_cambios_nube)

    def _chequear_cambios_nube(self):
        """Descarga (en 2º plano) solo los cambios nuevos de Supabase. Si trae
        filas, refresca la sección abierta. Nunca bloquea ni molesta si no hay
        conexión (se reintenta en el siguiente ciclo)."""
        if self._pull_en_curso:
            return
        if os.environ.get("DB_MODE", "local").strip().lower() not in (
                "local", "sqlite", "server"):
            return
        if not os.environ.get("SUPABASE_URI"):
            return
        self._pull_en_curso = True

        def _run():
            from local_sync import get_service
            from local_first_db import DEFAULT_DB_PATH
            return get_service(DEFAULT_DB_PATH).pull_delta()

        worker = FunctionWorker(_run)
        worker.signals.result.connect(self._on_pull_delta)
        worker.signals.error.connect(self._on_pull_delta_error)
        self._thread_pool.start(worker)

    def _on_pull_delta_error(self, _err):
        self._pull_en_curso = False  # sin conexión: se reintenta luego

    def _on_pull_delta(self, res):
        self._pull_en_curso = False
        if not (res and res.get("ok")):
            return  # error/sin conexión → silencioso, se reintenta
        if res.get("rows", 0) > 0:
            # El pull escribió directo en SQLite (fuera de los repos): invalidar
            # los cachés en memoria para que la vista cargue los datos nuevos.
            for repo in (getattr(self, "productos_repo", None),
                         getattr(self, "clientes_repo", None),
                         getattr(self, "proveedores_repo", None)):
                try:
                    if repo and hasattr(repo, "invalidar_cache"):
                        repo.invalidar_cache()
                except Exception:
                    pass
            # Llegaron cambios de la nube → refrescar la ventana abierta.
            self._refrescar_seccion_actual()
            try:
                self.status_label.setText(
                    f"✓ {res['rows']} cambio(s) descargado(s) de la nube")
            except Exception:
                pass

    def _refrescar_seccion_actual(self):
        """Re-renderiza la sección visible para reflejar datos nuevos, salvo que
        haya un diálogo modal abierto (para no interrumpir al usuario)."""
        if QApplication.activeModalWidget() is not None:
            return
        fn = getattr(self, "_seccion_actual_fn", None)
        if not fn:
            return
        try:
            fn()
        except Exception as exc:
            print(f"[SYNC] No se pudo refrescar la sección: {exc}")

    def _verificar_servicios_local_first(self):
        """(Hilo) Arranca el servidor si hace falta, espera a que responda y
        comprueba la conectividad con Supabase. Nunca lanza excepción hacia la app."""
        estado = self.local_server_manager.ensure_running(wait_ready=True, timeout=8.0)
        resultado = {
            "server": bool(estado.get("active")),
            "url": estado.get("url"),
            "sync_enabled": self.local_server_manager.sync_enabled(),
            "supabase": None,
        }
        if resultado["server"] and resultado["sync_enabled"]:
            try:
                from local_sync import SupabaseSyncService
                from local_first_db import DEFAULT_DB_PATH
                resultado["supabase"] = SupabaseSyncService(
                    db_path=DEFAULT_DB_PATH).test_connection()
            except Exception as exc:
                resultado["supabase"] = {"ok": False, "message": str(exc)}
        return resultado

    def _aplicar_estado_servicios(self, resultado):
        """(Hilo UI) Traduce el estado a un mensaje claro y reintenta una vez
        si el servidor no respondió. La app nunca se bloquea si Supabase falla."""
        if not resultado.get("server"):
            if self._servicios_retry < 1:
                self._servicios_retry += 1
                self.status_label.setText("⚠ Servidor local no respondió, reintentando…")
                QTimer.singleShot(1500, self._iniciar_servicios_local_first)
            else:
                self.status_label.setText(
                    "⚠ Servidor local no disponible — operando en modo solo-local")
                print("[LOCAL-FIRST] Servidor local no disponible; la app funciona localmente.")
            return

        if not resultado.get("sync_enabled"):
            msg = "✓ Servidor local activo · Sincronización deshabilitada en configuración"
        else:
            supa = resultado.get("supabase") or {}
            if supa.get("ok"):
                msg = "✓ Servidor local y sincronización con Supabase activos"
            else:
                msg = "✓ Servidor local activo · Supabase sin conexión (se sincronizará al reconectar)"
        self.status_label.setText(msg)
        print(f"[LOCAL-FIRST] {msg} · {resultado.get('url')}")

    def _update_alert_count_async(self):
        worker = FunctionWorker(self.alertas_service.contar_no_leidas)
        worker.signals.result.connect(self._apply_alert_count)
        worker.signals.error.connect(lambda e: print(f"Error actualizando alertas: {e}"))
        self._thread_pool.start(worker)

    def _apply_alert_count(self, count):
        try:
            if count > 0:
                self.alertas_btn.setText(f"🔔 {count}")
            else:
                self.alertas_btn.setText("🔔")
        except Exception as e:
            print(f"Error aplicando alertas: {e}")

    def _run_initial_checks(self):
        try:
            resultados = self.alertas_service.ejecutar_verificaciones_diarias()
            total = sum(resultados.values())
            if total > 0:
                self.status_label.setText(f"⚠ {total} nuevas alertas detectadas")
                self._update_alert_count()
        except Exception as e:
            print(f"Error en verificaciones: {e}")

    def _run_initial_checks_async(self):
        worker = FunctionWorker(self.alertas_service.ejecutar_verificaciones_diarias)
        worker.signals.result.connect(self._on_initial_checks_done)
        worker.signals.error.connect(lambda e: print(f"Error en verificaciones: {e}"))
        self._thread_pool.start(worker)

    def _on_initial_checks_done(self, resultados):
        total = sum(resultados.values())
        if total > 0:
            self.status_label.setText(f"âš  {total} nuevas alertas detectadas")
            self._update_alert_count_async()

    def _preload_common_caches(self):
        for loader in (
            self.productos_repo.precargar_cache,
            self.clientes_repo.precargar_cache,
            self.proveedores_repo.precargar_cache,
        ):
            worker = FunctionWorker(loader)
            worker.signals.error.connect(lambda e: print(f"Error precargando cache: {e}"))
            self._thread_pool.start(worker)

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
        if not self.auth.tiene_permiso('ver_dashboard'):
            if self.auth.tiene_permiso('realizar_ventas'):
                self.mostrar_ventas()
            else:
                self.mostrar_productos()
            return
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

    def mostrar_importar_inventario(self):
        from ui.inventory_import_ui import InventoryImportUI
        w = InventoryImportUI(
            self.content_stack, self.db, self.productos_repo, self.auth
        )
        self._set_content(w)

    def mostrar_regularizar_barcodes(self):
        from ui.barcode_regularization_ui import BarcodeRegularizationUI
        w = BarcodeRegularizationUI(self.content_stack, self.db, self.auth)
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
        from ui.local_first_admin_ui import LocalFirstAdminUI
        w = LocalFirstAdminUI(self.content_stack, self.local_server_manager)
        self._set_content(w)
        return
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


def _gate_supabase():
    """Validación obligatoria de Supabase al iniciar (ETAPA 11).

    Devuelve:
      False -> Supabase OK, modo normal (lanza sync de pendientes).
      True  -> Supabase caído, el usuario eligió MODO LOCAL DE EMERGENCIA
               (luego solo un Administrador podrá ingresar).
      None  -> el usuario eligió Salir.
    """
    from local_sync import SupabaseSyncService
    while True:
        svc = SupabaseSyncService()
        try:
            res = svc.validar_arranque()
        except Exception as exc:
            res = {"ok": False, "mensaje": f"Error validando Supabase: {exc}"}

        if res.get("ok"):
            # Conexión válida: sincronizar lo pendiente en segundo plano.
            try:
                import threading
                threading.Thread(target=lambda: svc.sync_once(limit=1000),
                                 daemon=True).start()
            except Exception:
                pass
            return False

        # Supabase no disponible: ventana de decisión.
        box = QMessageBox()
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Conexión con Supabase")
        box.setText("No fue posible conectarse a Supabase.")
        box.setInformativeText(
            f"{res.get('mensaje','')}\n\n"
            "El sistema puede continuar únicamente en MODO LOCAL DE EMERGENCIA.\n"
            "Todos los cambios quedarán almacenados en SQLite y en la cola de "
            "sincronización hasta recuperar la conexión (no se pierde nada).\n\n"
            "Solo un usuario Administrador puede autorizar el modo local.")
        b_retry = box.addButton("Reintentar conexión", QMessageBox.AcceptRole)
        b_local = box.addButton("Trabajar en modo local (Admin)",
                                QMessageBox.DestructiveRole)
        b_exit = box.addButton("Salir", QMessageBox.RejectRole)
        box.exec()
        clic = box.clickedButton()
        if clic is b_retry:
            continue
        if clic is b_local:
            return True
        return None


def _pull_inicial_desde_nube(modo_emergencia=False):
    """Local-first: descarga los datos de Supabase a la BD local ANTES de abrir
    la app, para arrancar con el estado de la nube. Muestra un diálogo de
    progreso y corre el pull en un hilo (no congela). Si Supabase no responde,
    continúa con los datos locales (no bloquea el ingreso)."""
    try:
        cfg = load_config()
    except Exception:
        cfg = {}
    modo = os.environ.get("DB_MODE", "local").strip().lower()
    if (modo_emergencia or modo not in ("local", "sqlite", "server")
            or not cfg.get("cloud_sync_enabled", True)
            or not os.environ.get("SUPABASE_URI")):
        return  # remoto/emergencia/sin credenciales → no hay pull

    from PySide6.QtWidgets import QProgressDialog
    import threading
    dlg = QProgressDialog("Cargando datos de la nube…", None, 0, 0)
    dlg.setWindowTitle("Sincronizando")
    dlg.setWindowModality(Qt.ApplicationModal)
    dlg.setCancelButton(None)
    dlg.setMinimumDuration(0)
    dlg.show()
    QApplication.processEvents()

    resultado = {}

    def _run():
        try:
            from local_sync import get_service
            from local_first_db import DEFAULT_DB_PATH
            svc = get_service(DEFAULT_DB_PATH)
            res = svc.pull_from_remote()
            # Sembrar la marca de deltas: los pull periódicos siguientes solo
            # descargarán lo que cambie DESPUÉS de esta carga inicial.
            if res.get("ok") and res.get("watermark"):
                svc.set_pull_watermark(res["watermark"])
            resultado.update(res)
        except Exception as exc:
            resultado.update({"ok": False, "error": str(exc)})

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    while t.is_alive():
        QApplication.processEvents()
        t.join(0.05)
    dlg.close()
    QApplication.processEvents()
    if not resultado.get("ok"):
        print(f"[PULL] No se pudo descargar de la nube: {resultado.get('error')}")


def show_login_and_run(reuse_app=False, server_manager=None, modo_emergencia=None):
    global _app_instance
    if not reuse_app:
        _app_instance = QApplication(sys.argv)
        _app_instance.setStyleSheet(GLOBAL_QSS)

    # ── Arranque temprano del servidor local (antes del login) ──
    # Solo en modo LOCAL/servidor LAN. En modo REMOTO (Supabase directo) no se
    # arranca ningún servidor local: cada equipo habla con la base central.
    _db_mode = os.environ.get("DB_MODE", "local").strip().lower()
    _es_local = _db_mode in ("local", "sqlite", "server")
    if server_manager is None and _es_local:
        try:
            cfg = load_config()
            if cfg.get("auto_start_server", True):
                server_manager = LocalServerManager(cfg)
                import threading
                threading.Thread(target=server_manager.start, daemon=True).start()
        except Exception as exc:
            print(f"[LOCAL-FIRST] No se pudo iniciar el servidor temprano: {exc}")

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

    # ── ETAPA 11: validación obligatoria de Supabase al iniciar ──
    # Se ejecuta solo en el primer arranque (no en cada reintento de login).
    if modo_emergencia is None:
        decision = _gate_supabase()
        if decision is None:          # el usuario eligió Salir
            if not reuse_app:
                sys.exit(0)
            return
        modo_emergencia = decision    # False = normal, True = emergencia local

    dialog = LoginDialog()
    if dialog.exec() != QDialog.Accepted:
        if not reuse_app:
            sys.exit(0)
        return

    exito, mensaje, usuario = auth.login(dialog.username, dialog.password)
    if not exito:
        QMessageBox.critical(None, "Error", mensaje)
        show_login_and_run(reuse_app=True, server_manager=server_manager,
                           modo_emergencia=modo_emergencia)
        return

    # En modo local de emergencia (Supabase caído) solo entra un Administrador;
    # los empleados quedan bloqueados hasta recuperar la conexión.
    if modo_emergencia and (getattr(usuario, 'rol', '') or '').upper() != 'ADMIN':
        QMessageBox.warning(None, "Modo local de emergencia",
                            "Supabase está desconectado. Solo un Administrador "
                            "puede ingresar en modo local de emergencia.\n"
                            "Contacte al administrador o reintente cuando haya "
                            "conexión.")
        show_login_and_run(reuse_app=True, server_manager=server_manager,
                           modo_emergencia=modo_emergencia)
        return

    # Local-first: descargar el estado actual de la nube ANTES de abrir la app.
    _pull_inicial_desde_nube(modo_emergencia)

    window = SistemaFerreteriaApp(auth_manager=auth, server_manager=server_manager)
    window.show()
    # Bienvenida no bloqueante (sin modal): el nombre/rol ya se ve en el header.
    try:
        window.status_label.setText(
            f"✓ Sesión iniciada — {usuario.nombre_completo} ({usuario.rol})")
    except Exception:
        pass

    if not reuse_app:
        sys.exit(_app_instance.exec())


def main():
    try:
        from app_logging import setup_logging
        from version import __version__
        setup_logging(componente="admin")
        logging.getLogger("main").info("Iniciando FERREPRO v%s (admin)", __version__)
    except Exception:
        pass
    try:
        show_login_and_run()
    except Exception as e:
        logging.getLogger("main").critical("Error fatal al iniciar", exc_info=True)
        QMessageBox.critical(None, "Error Fatal",
                             f"Error al iniciar el sistema:\n{str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
