# -*- coding: utf-8 -*-
"""
Interfaz de Usuario para Reportes y Estadísticas (PySide6)
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QDialog,
    QMessageBox, QFrame, QTextEdit, QGridLayout, QGroupBox, QScrollArea,
    QAbstractItemView, QSizePolicy, QDateEdit
)
from PySide6.QtCore import Qt, QDate, QTimer
from PySide6.QtGui import QFont, QColor, QPainter, QPen, QBrush

from datetime import datetime, timedelta
from ui_config import COLORS, FONTS, ICONS, make_font
from formato import formatear_stock


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPER: Simple Bar Chart Widget using QPainter
# ═══════════════════════════════════════════════════════════════════════════════

class BarChartWidget(QWidget):
    """Draws a simple bar chart using QPainter."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bars = []  # list of (label, value, color)
        self._min_height = 180
        self.setMinimumHeight(self._min_height)

    def set_data(self, bars):
        """bars: list of (label, value, color_hex)"""
        self._bars = bars
        self.update()

    def paintEvent(self, event):
        if not self._bars:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        padding_l, padding_r, padding_t, padding_b = 10, 10, 16, 30
        usable_w = w - padding_l - padding_r
        usable_h = h - padding_t - padding_b
        base_y = h - padding_b

        max_val = max((v for _, v, _ in self._bars), default=1) or 1
        n = len(self._bars)
        bar_gap = 8
        bar_w = max(10, min(70, (usable_w - bar_gap * (n - 1)) // n)) if n > 0 else 40
        total_bars_w = n * bar_w + (n - 1) * bar_gap
        offset_x = padding_l + (usable_w - total_bars_w) // 2

        # Baseline
        painter.setPen(QPen(QColor('#e2e8f0'), 1))
        painter.drawLine(padding_l, base_y, w - padding_r, base_y)

        # Reference lines
        pen_ref = QPen(QColor('#f1f5f9'), 1, Qt.DashLine)
        for pct in [0.25, 0.5, 0.75]:
            y = int(base_y - usable_h * pct)
            painter.setPen(pen_ref)
            painter.drawLine(padding_l, y, w - padding_r, y)

        for i, (label, val, color) in enumerate(self._bars):
            x = offset_x + i * (bar_w + bar_gap)
            bar_h = max(int((val / max_val) * usable_h), 4) if max_val > 0 else 4
            y_top = base_y - bar_h

            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(color)))
            painter.drawRect(x, y_top, bar_w, bar_h)

            # Value on top
            painter.setPen(QColor(color))
            painter.setFont(QFont('Segoe UI', 8, QFont.Bold))
            painter.drawText(x, y_top - 12, bar_w, 12, Qt.AlignCenter, self._fmt_short(val))

            # Label below
            painter.setPen(QColor('#64748b'))
            painter.setFont(QFont('Segoe UI', 8))
            painter.drawText(x - 5, base_y + 2, bar_w + 10, 20, Qt.AlignCenter, label)

        painter.end()

    @staticmethod
    def _fmt_short(v):
        try:
            v = float(v)
            if v >= 1_000_000:
                return f"${v/1_000_000:,.1f}M"
            elif v >= 1_000:
                return f"${v:,.0f}"
            return f"${v:,.2f}"
        except (ValueError, TypeError):
            return "$0"


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPER: Mini bar chart for daily sales (Flujo de Caja)
# ═══════════════════════════════════════════════════════════════════════════════

class DailyBarChartWidget(QWidget):
    """Bar chart for daily sales data."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = []  # list of dict with 'dia', 'monto'
        self.setMinimumHeight(120)
        self.setFixedHeight(120)

    def set_data(self, data):
        self._data = data or []
        self.update()

    def paintEvent(self, event):
        if not self._data:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        cw = self.width()
        ch = self.height()
        padding_l, padding_r, padding_t, padding_b = 10, 10, 12, 22
        usable_w = cw - padding_l - padding_r
        usable_h = ch - padding_t - padding_b
        base_y = ch - padding_b

        montos = [float(v.get('monto', 0)) for v in self._data]
        max_m = max(montos) if montos else 1
        if max_m == 0:
            max_m = 1
        n = len(montos)

        bar_gap = 2
        bar_w = max(4, min(30, (usable_w - bar_gap * (n - 1)) // n)) if n > 0 else 20
        total_bars_w = n * bar_w + (n - 1) * bar_gap
        offset_x = padding_l + (usable_w - total_bars_w) // 2

        # Baseline
        painter.setPen(QPen(QColor('#e2e8f0'), 1))
        painter.drawLine(padding_l, base_y, cw - padding_r, base_y)

        # Reference lines
        pen_ref = QPen(QColor('#f1f5f9'), 1, Qt.DashLine)
        for pct in [0.25, 0.5, 0.75]:
            y = int(base_y - usable_h * pct)
            painter.setPen(pen_ref)
            painter.drawLine(padding_l, y, cw - padding_r, y)

        for i, m in enumerate(montos):
            x = offset_x + i * (bar_w + bar_gap)
            h = max(int((m / max_m) * usable_h), 2)
            y_top = base_y - h

            pct = m / max_m
            if pct >= 0.7:
                color = '#059669'
            elif pct >= 0.4:
                color = '#2563eb'
            else:
                color = '#94a3b8'

            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(color)))
            painter.drawRect(x, y_top, bar_w, h)

            if n <= 15:
                dia_label = self._data[i].get('dia', '')[-5:]
                painter.setPen(QColor('#94a3b8'))
                painter.setFont(QFont('Segoe UI', 6))
                painter.drawText(x - 2, base_y + 2, bar_w + 4, 16, Qt.AlignCenter, dia_label)

        painter.end()


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPER: Donut Chart Widget (for VentanaMetodosPago)
# ═══════════════════════════════════════════════════════════════════════════════

class DonutChartWidget(QWidget):
    """Draws a donut chart using QPainter."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._segments = []  # list of (value, color_hex, label)
        self._total_label = ""
        self.setFixedSize(170, 170)

    def set_data(self, segments, total_label=""):
        """segments: list of (value, color_hex, label)"""
        self._segments = segments
        self._total_label = total_label
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        sz = min(self.width(), self.height())
        cx, cy = sz // 2, sz // 2
        r = 72
        inner_r = 38

        if not self._segments:
            painter.setPen(QColor('#64748b'))
            painter.setFont(QFont('Segoe UI', 10))
            painter.drawText(0, 0, sz, sz, Qt.AlignCenter, "Sin datos")
            painter.end()
            return

        total = sum(s[0] for s in self._segments) or 1
        start_angle = 0

        for value, color, label in self._segments:
            pct = value / total
            span = max(pct * 360 * 16, 8)  # Qt uses 1/16th degree
            painter.setPen(QPen(QColor('white'), 2))
            painter.setBrush(QBrush(QColor(color)))
            painter.drawPie(cx - r, cy - r, r * 2, r * 2, int(start_angle), int(span))
            start_angle += span

        # Inner circle (donut hole)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor('white')))
        painter.drawEllipse(cx - inner_r, cy - inner_r, inner_r * 2, inner_r * 2)

        # Center text
        painter.setPen(QColor('#64748b'))
        painter.setFont(QFont('Segoe UI', 8))
        painter.drawText(0, cy - 16, sz, 16, Qt.AlignCenter, "Total")
        painter.setPen(QColor('#0f172a'))
        painter.setFont(QFont('Segoe UI', 10, QFont.Bold))
        painter.drawText(0, cy, sz, 16, Qt.AlignCenter, self._total_label)

        painter.end()


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def _oscurecer(hex_color):
    """Darkens a hex color for hover effect."""
    try:
        r = max(0, int(hex_color[1:3], 16) - 25)
        g = max(0, int(hex_color[3:5], 16) - 25)
        b = max(0, int(hex_color[5:7], 16) - 25)
        return f'#{r:02x}{g:02x}{b:02x}'
    except Exception:
        return hex_color


def _make_header_btn(text, color_bg='white', color_fg='#1e40af', callback=None):
    """Creates a styled header button."""
    btn = QPushButton(text)
    btn.setFont(QFont('Segoe UI', 9))
    btn.setCursor(Qt.PointingHandCursor)
    btn.setStyleSheet(
        f"QPushButton {{ background: {color_bg}; color: {color_fg}; border: none; "
        f"border-radius: 6px; padding: 4px 14px; }}"
        f"QPushButton:hover {{ background: #e0e7ff; }}"
    )
    if callback:
        btn.clicked.connect(callback)
    return btn


def _make_kpi_card(parent_layout, icon, title, value, color, col=None, row=0):
    """Creates a KPI card widget and adds it to a grid layout."""
    card = QFrame()
    card.setStyleSheet(
        "QFrame { background: white; border: 1px solid #e2e8f0; border-radius: 6px; }"
    )
    card_layout = QVBoxLayout(card)
    card_layout.setContentsMargins(14, 8, 14, 8)
    card_layout.setSpacing(2)

    # Color bar
    bar = QFrame()
    bar.setFixedHeight(3)
    bar.setStyleSheet(f"background: {color}; border: none; border-radius: 1px;")
    card_layout.addWidget(bar)

    # Title row
    title_row = QHBoxLayout()
    title_row.setSpacing(4)
    lbl_icon = QLabel(icon)
    lbl_icon.setFont(QFont('Segoe UI', 10))
    lbl_icon.setStyleSheet("border: none;")
    title_row.addWidget(lbl_icon)
    lbl_title = QLabel(title)
    lbl_title.setFont(QFont('Segoe UI', 8))
    lbl_title.setStyleSheet(f"color: #94a3b8; border: none;")
    title_row.addWidget(lbl_title)
    title_row.addStretch()
    card_layout.addLayout(title_row)

    # Value
    fs = 18 if len(str(value)) <= 8 else (14 if len(str(value)) <= 14 else 12)
    lbl_val = QLabel(str(value))
    lbl_val.setFont(QFont('Segoe UI', fs, QFont.Bold))
    lbl_val.setStyleSheet(f"color: {color}; border: none;")
    card_layout.addWidget(lbl_val)

    if isinstance(parent_layout, QGridLayout) and col is not None:
        parent_layout.addWidget(card, row, col)
    else:
        parent_layout.addWidget(card)
    return card


def _create_date_edit(default_date):
    """Creates a QDateEdit with the given default date."""
    de = QDateEdit()
    de.setCalendarPopup(True)
    de.setDisplayFormat('yyyy-MM-dd')
    de.setDate(QDate(default_date.year, default_date.month, default_date.day))
    de.setFont(QFont('Segoe UI', 10))
    de.setStyleSheet(
        "QDateEdit { background: white; border: 1px solid #94a3b8; border-radius: 4px; padding: 3px 8px; }"
    )
    return de


def _setup_table(table, columns, row_height=32):
    """Configure a QTableWidget with columns: list of (heading, width, alignment)."""
    table.setColumnCount(len(columns))
    headers = []
    for i, (heading, width, alignment) in enumerate(columns):
        headers.append(heading)
        table.setColumnWidth(i, width)
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(row_height)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.horizontalHeader().setStretchLastSection(True)
    table.setStyleSheet(
        f"QTableWidget {{ background: white; alternate-background-color: {COLORS['table_row_alt']}; gridline-color: transparent; border: 1px solid {COLORS['border']}; border-radius: 12px; }}"
        "QTableWidget::item { padding: 7px 6px; }"
        f"QTableWidget::item:selected {{ background: {COLORS['table_selection']}; color: {COLORS['text_primary']}; }}"
        f"QHeaderView::section {{ background: {COLORS['table_header']}; color: {COLORS['table_header_fg']}; font-weight: 500; "
        "padding: 10px 8px; border: none; font-size: 10pt; }"
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN CLASS: ReportesUI
# ═══════════════════════════════════════════════════════════════════════════════

class ReportesUI(QWidget):
    """Interfaz para reportes y estadísticas"""

    def __init__(self, parent_frame, reportes_service, auth_manager,
                 reportes_compras_service=None, proveedores_repo=None, productos_repo=None):
        super().__init__(parent_frame)
        self.parent_widget = parent_frame
        self.reportes_service = reportes_service
        self.auth = auth_manager
        self.reportes_compras_service = reportes_compras_service
        self.proveedores_repo = proveedores_repo
        self.productos_repo = productos_repo

        self.crear_interfaz()

    def crear_interfaz(self):
        """Crea la interfaz principal"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        main_frame = QFrame()
        main_frame.setStyleSheet(f"background: {COLORS['bg_secondary']};")
        frame_layout = QVBoxLayout(main_frame)
        frame_layout.setContentsMargins(20, 10, 20, 10)
        frame_layout.setSpacing(10)

        # Header
        header = QHBoxLayout()
        title = QLabel(f"{ICONS['reportes']} Reportes y Estadísticas")
        title.setFont(make_font(FONTS['large']))
        title.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent;")
        header.addWidget(title)
        header.addStretch()
        frame_layout.addLayout(header)

        # Menu de reportes
        menu_frame = QFrame()
        menu_frame.setStyleSheet("background: white; border: 1px solid #d1d5db; border-radius: 8px;")
        menu_layout = QVBoxLayout(menu_frame)
        menu_layout.setContentsMargins(30, 24, 30, 30)
        menu_layout.setAlignment(Qt.AlignTop)

        # Grid de botones
        grid = QGridLayout()
        grid.setSpacing(10)

        reportes = [
            ("📊", "Ventas por período", self.reporte_ventas_periodo, COLORS['primary']),
            ("💰", "Productos más vendidos", self.reporte_top_productos, COLORS['success']),
            ("💳", "Ventas por método de pago", self.reporte_metodos_pago, COLORS['info']),
            ("📈", "Estadísticas generales", self.reporte_estadisticas, COLORS['primary']),
            ("📊", "Comparativa de períodos", self.reporte_comparativa, COLORS['warning']),
            ("💹", "Reporte de rentabilidad", self.reporte_rentabilidad, COLORS['success']),
            ("📋", "Cuentas por cobrar", self.reporte_cuentas_cobrar, '#534ab7'),
            ("🔄", "Rotación de inventario", self.reporte_rotacion, COLORS['danger']),
            ("💵", "Flujo de caja", self.reporte_flujo_caja, '#2f6fb0'),
            ("📅", "Reporte del día", self.reporte_del_dia, '#0f6e56'),
        ]

        row_i = 0
        col_i = 0
        for icono, texto, comando, color in reportes:
            card = self._crear_tarjeta_reporte(icono, texto, color, comando)
            grid.addWidget(card, row_i, col_i)
            col_i += 1
            if col_i > 1:
                col_i = 0
                row_i += 1

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        menu_layout.addLayout(grid)
        frame_layout.addWidget(menu_frame, 1)
        main_layout.addWidget(main_frame)

    def _crear_tarjeta_reporte(self, icono, texto, color, comando):
        """Tarjeta de reporte: barra de acento vertical (4px) a la izquierda,
        ícono + título y chevron a la derecha. Clic abre la misma ventana que
        antes (no cambia comportamiento)."""
        card = QFrame()
        card.setCursor(Qt.PointingHandCursor)
        card.setObjectName("repCard")
        card.setStyleSheet(
            f"#repCard {{ background: {COLORS['bg_primary']};"
            f" border: 1px solid {COLORS['border']}; border-radius: 12px; }}"
            f"#repCard:hover {{ background: {COLORS['bg_hover']}; }}"
        )
        row = QHBoxLayout(card)
        row.setContentsMargins(0, 0, 14, 0)
        row.setSpacing(12)

        # Barra de acento vertical (4px)
        barra = QFrame()
        barra.setFixedWidth(4)
        barra.setStyleSheet(
            f"background: {color}; border-top-left-radius: 12px;"
            f" border-bottom-left-radius: 12px;")
        row.addWidget(barra)

        ico = QLabel(icono)
        ico.setStyleSheet("background: transparent; border: none; font-size: 15pt;")
        row.addSpacing(6)
        row.addWidget(ico)

        lbl = QLabel(texto)
        lbl.setFont(make_font(FONTS['body']))
        lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; background: transparent; border: none;")
        row.addWidget(lbl)
        row.addStretch()

        chevron = QLabel("›")
        chevron.setStyleSheet(
            f"color: {COLORS['text_light']}; background: transparent;"
            f" border: none; font-size: 16pt;")
        row.addWidget(chevron)

        card.setMinimumHeight(58)
        card.mousePressEvent = lambda e, c=comando: c()
        return card

    def _oscurecer(self, hex_color):
        return _oscurecer(hex_color)

    # ==================== REPORTES CONSERVADOS ====================

    def reporte_ventas_periodo(self):
        VentanaVentasPeriodo(self.window(), self.reportes_service)

    def reporte_top_productos(self):
        VentanaTopProductos(self.window(), self.reportes_service)

    def reporte_metodos_pago(self):
        VentanaMetodosPago(self.window(), self.reportes_service)

    def reporte_estadisticas(self):
        VentanaEstadisticasDashboard(self.window(), self.reportes_service)

    # ==================== NUEVOS REPORTES ====================

    def reporte_comparativa(self):
        VentanaComparativa(self.window(), self.reportes_service)

    def reporte_rentabilidad(self):
        VentanaRentabilidadDashboard(self.window(), self.reportes_service)

    def reporte_cuentas_cobrar(self):
        VentanaCuentasCobrar(self.window(), self.reportes_service)

    def reporte_rotacion(self):
        VentanaRotacionInventario(self.window(), self.reportes_service)

    def reporte_flujo_caja(self):
        VentanaFlujoCajaDashboard(self.window(), self.reportes_service)

    def reporte_del_dia(self):
        VentanaReporteDia(self.window(), self.reportes_service)


# ═══════════════════════════════════════════════════════════════════════════════
#  VENTANA TOP PRODUCTOS
# ═══════════════════════════════════════════════════════════════════════════════

class VentanaTopProductos(QDialog):
    """Dashboard de Top Productos Vendidos con KPIs, tabla moderna y alertas de stock"""

    AZUL = '#0f1b30'
    AZUL_CLARO = '#2f6fb0'
    AZUL_HEADER = '#0f1b30'
    VERDE = '#1d9e75'
    VERDE_CLARO = '#10b981'
    NARANJA = '#f59e0b'
    ROJO = '#ef4444'
    GRIS_BG = '#f1f5f9'
    GRIS_FILA = '#f8fafc'
    TEXTO = '#0f172a'
    TEXTO_SEC = '#64748b'

    def __init__(self, parent, reportes_service):
        super().__init__(parent)
        self.reportes_service = reportes_service
        self.datos = None
        self.productos = []
        self.orden_actual = 'cantidad'

        self.setWindowTitle("💰 Top Productos Vendidos")
        self.resize(1150, 720)
        self.setMinimumSize(950, 600)
        self.setStyleSheet(f"background: {self.GRIS_BG};")

        self._crear_interfaz()
        self._cargar_datos()
        self.exec()

    def _crear_interfaz(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # HEADER
        top_bar = QFrame()
        top_bar.setStyleSheet(f"background: {self.AZUL};")
        top_layout = QVBoxLayout(top_bar)
        top_layout.setContentsMargins(25, 12, 25, 12)

        # Title row
        title_row = QHBoxLayout()
        title_lbl = QLabel("💰 Top Productos Vendidos")
        title_lbl.setFont(QFont('Segoe UI', 17, QFont.Bold))
        title_lbl.setStyleSheet(f"color: white; background: transparent;")
        title_row.addWidget(title_lbl)
        title_row.addStretch()

        for txt, cmd in [("📤 Exportar", self._exportar), ("🖨️ Imprimir", self._imprimir)]:
            title_row.addWidget(_make_header_btn(txt, callback=cmd))

        top_layout.addLayout(title_row)

        # Filter row
        filtro_row = QHBoxLayout()
        filtro_row.setSpacing(8)

        hoy = datetime.now()
        inicio_def = hoy - timedelta(days=30)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setFont(QFont('Segoe UI', 10, QFont.Bold))
        lbl_desde.setStyleSheet("color: #93c5fd; background: transparent;")
        filtro_row.addWidget(lbl_desde)
        self.fecha_inicio = _create_date_edit(inicio_def)
        filtro_row.addWidget(self.fecha_inicio)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setFont(QFont('Segoe UI', 10, QFont.Bold))
        lbl_hasta.setStyleSheet("color: #93c5fd; background: transparent;")
        filtro_row.addWidget(lbl_hasta)
        self.fecha_fin = _create_date_edit(hoy)
        filtro_row.addWidget(self.fecha_fin)

        self._generando = False
        self.btn_generar = QPushButton("🔍  Generar")
        self.btn_generar.setFont(QFont('Segoe UI', 10, QFont.Bold))
        self.btn_generar.setCursor(Qt.PointingHandCursor)
        self.btn_generar.setStyleSheet(
            f"QPushButton {{ background: {self.VERDE}; color: white; border: none; "
            f"border-radius: 6px; padding: 5px 16px; }}"
            f"QPushButton:hover {{ background: {self.VERDE_CLARO}; }}"
        )
        self.btn_generar.clicked.connect(self._on_generar)
        filtro_row.addWidget(self.btn_generar)

        filtro_row.addSpacing(20)

        lbl_ord = QLabel("Ordenar por:")
        lbl_ord.setFont(QFont('Segoe UI', 9, QFont.Bold))
        lbl_ord.setStyleSheet("color: #93c5fd; background: transparent;")
        filtro_row.addWidget(lbl_ord)

        self.btn_ord_cant = QPushButton("📦 Cantidad")
        self.btn_ord_cant.setFont(QFont('Segoe UI', 9, QFont.Bold))
        self.btn_ord_cant.setCursor(Qt.PointingHandCursor)
        self.btn_ord_cant.setStyleSheet(
            "QPushButton { background: white; color: #1e3a5f; border: none; border-radius: 4px; padding: 3px 10px; }"
        )
        self.btn_ord_cant.clicked.connect(lambda: self._cambiar_orden('cantidad'))
        filtro_row.addWidget(self.btn_ord_cant)

        self.btn_ord_monto = QPushButton("💵 Monto")
        self.btn_ord_monto.setFont(QFont('Segoe UI', 9))
        self.btn_ord_monto.setCursor(Qt.PointingHandCursor)
        self.btn_ord_monto.setStyleSheet(
            "QPushButton { background: #475569; color: white; border: none; border-radius: 4px; padding: 3px 10px; }"
        )
        self.btn_ord_monto.clicked.connect(lambda: self._cambiar_orden('monto'))
        filtro_row.addWidget(self.btn_ord_monto)

        filtro_row.addStretch()
        top_layout.addLayout(filtro_row)
        layout.addWidget(top_bar)

        # KPI FRAME
        self.kpi_frame = QFrame()
        self.kpi_frame.setStyleSheet("background: transparent;")
        self.kpi_layout = QHBoxLayout(self.kpi_frame)
        self.kpi_layout.setContentsMargins(20, 15, 20, 5)
        layout.addWidget(self.kpi_frame)

        # TABLE
        tabla_container = QFrame()
        tabla_container.setStyleSheet("background: white; border: 1px solid #d1d5db; border-radius: 4px;")
        tabla_layout = QVBoxLayout(tabla_container)
        tabla_layout.setContentsMargins(10, 8, 10, 10)

        self.lbl_conteo = QLabel("")
        self.lbl_conteo.setFont(QFont('Segoe UI', 9))
        self.lbl_conteo.setStyleSheet(f"color: {self.TEXTO_SEC}; border: none;")
        tabla_layout.addWidget(self.lbl_conteo)

        self.table = QTableWidget()
        columns = [
            ('#', 50, 'center'),
            ('Producto', 220, 'left'),
            ('Categoría', 130, 'left'),
            ('Cant. Vendida', 100, 'center'),
            ('Ingreso Total', 120, 'right'),
            ('% Ingresos', 85, 'center'),
            ('Stock Actual', 100, 'center'),
            ('Estado Stock', 95, 'center'),
        ]
        _setup_table(self.table, columns)
        tabla_layout.addWidget(self.table)
        layout.addWidget(tabla_container, 1)

        # BOTTOM BAR
        bottom = QHBoxLayout()
        bottom.setContentsMargins(20, 0, 20, 10)
        self.lbl_alerta = QLabel("")
        self.lbl_alerta.setFont(QFont('Segoe UI', 9, QFont.Bold))
        self.lbl_alerta.setStyleSheet(f"color: {self.ROJO};")
        bottom.addWidget(self.lbl_alerta)
        bottom.addStretch()
        self.lbl_estado = QLabel("")
        self.lbl_estado.setFont(QFont('Segoe UI', 9))
        self.lbl_estado.setStyleSheet(f"color: {self.TEXTO_SEC}; font-style: italic;")
        bottom.addWidget(self.lbl_estado)
        layout.addLayout(bottom)

    def _dibujar_kpis(self, datos):
        # Clear existing
        while self.kpi_layout.count():
            item = self.kpi_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        estrella = datos.get('producto_estrella')
        cat_top = datos.get('categoria_top', {})
        total_u = datos.get('total_unidades', 0)

        kpis = [
            ("🏆", "Producto Estrella",
             estrella['nombre'] if estrella else '-',
             f"{estrella['cantidad_vendida']} uds vendidas" if estrella else '',
             self.AZUL_CLARO),
            ("📂", "Categoría Más Rentable",
             cat_top.get('categoria', '-'),
             f"$ {cat_top.get('total_cat', 0):,.2f}" if cat_top.get('total_cat') else '',
             '#8b5cf6'),
            ("📦", "Unidades Totales Vendidas",
             f"{total_u:,}",
             "en el período",
             self.VERDE),
        ]

        for icon, titulo, valor, subtexto, color in kpis:
            card = QFrame()
            card.setStyleSheet("QFrame { background: white; border: 1px solid #d1d5db; border-radius: 6px; }")
            card_l = QVBoxLayout(card)
            card_l.setContentsMargins(18, 12, 18, 12)

            bar = QFrame()
            bar.setFixedHeight(4)
            bar.setStyleSheet(f"background: {color}; border: none;")
            card_l.addWidget(bar)

            lbl_t = QLabel(f"{icon} {titulo}")
            lbl_t.setFont(QFont('Segoe UI', 9))
            lbl_t.setStyleSheet(f"color: {self.TEXTO_SEC}; border: none;")
            card_l.addWidget(lbl_t)

            lbl_v = QLabel(valor)
            lbl_v.setFont(QFont('Segoe UI', 16, QFont.Bold))
            lbl_v.setStyleSheet(f"color: {color}; border: none;")
            card_l.addWidget(lbl_v)

            if subtexto:
                lbl_s = QLabel(subtexto)
                lbl_s.setFont(QFont('Segoe UI', 8))
                lbl_s.setStyleSheet(f"color: {self.TEXTO_SEC}; border: none;")
                card_l.addWidget(lbl_s)

            self.kpi_layout.addWidget(card)

    def _on_generar(self):
        if self._generando:
            return
        self._generando = True
        self.btn_generar.setText("⏳ ...")
        self.btn_generar.setEnabled(False)
        QTimer.singleShot(50, self._ejecutar)

    def _ejecutar(self):
        try:
            self._cargar_datos()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error:\n{str(e)}")
        finally:
            self._generando = False
            self.btn_generar.setText("🔍  Generar")
            self.btn_generar.setEnabled(True)

    def _cargar_datos(self):
        inicio = self.fecha_inicio.date().toString('yyyy-MM-dd')
        fin = self.fecha_fin.date().toString('yyyy-MM-dd')

        try:
            datetime.strptime(inicio, '%Y-%m-%d')
            datetime.strptime(fin, '%Y-%m-%d')
        except ValueError:
            QMessageBox.warning(self, "Fecha inválida", "Formato: YYYY-MM-DD")
            return

        if inicio > fin:
            QMessageBox.warning(self, "Rango inválido",
                                "La fecha 'Desde' no puede ser mayor que 'Hasta'.")
            return

        self.datos = self.reportes_service.reporte_productos_mas_vendidos(inicio, fin, 20)
        self.productos = self.datos.get('productos', [])

        self._dibujar_kpis(self.datos)
        self._rellenar_tabla()

        alertas = [p for p in self.productos if p.get('estado_stock') in ('BAJO', 'AGOTADO')]
        if alertas:
            nombres = ', '.join(p['nombre'] for p in alertas[:3])
            extra = f" (+{len(alertas)-3} más)" if len(alertas) > 3 else ""
            self.lbl_alerta.setText(
                f"⚠️ ¡Atención! {len(alertas)} producto(s) del Top necesitan reabastecimiento: {nombres}{extra}")
        else:
            self.lbl_alerta.setText("")

        self.lbl_estado.setText(f"✅ Período: {inicio} → {fin}")

    def _cambiar_orden(self, nuevo_orden):
        if nuevo_orden == self.orden_actual:
            return
        self.orden_actual = nuevo_orden
        if nuevo_orden == 'cantidad':
            self.btn_ord_cant.setFont(QFont('Segoe UI', 9, QFont.Bold))
            self.btn_ord_cant.setStyleSheet(
                "QPushButton { background: white; color: #1e3a5f; border: none; border-radius: 4px; padding: 3px 10px; }"
            )
            self.btn_ord_monto.setFont(QFont('Segoe UI', 9))
            self.btn_ord_monto.setStyleSheet(
                "QPushButton { background: #475569; color: white; border: none; border-radius: 4px; padding: 3px 10px; }"
            )
        else:
            self.btn_ord_cant.setFont(QFont('Segoe UI', 9))
            self.btn_ord_cant.setStyleSheet(
                "QPushButton { background: #475569; color: white; border: none; border-radius: 4px; padding: 3px 10px; }"
            )
            self.btn_ord_monto.setFont(QFont('Segoe UI', 9, QFont.Bold))
            self.btn_ord_monto.setStyleSheet(
                "QPushButton { background: white; color: #1e3a5f; border: none; border-radius: 4px; padding: 3px 10px; }"
            )
        self._rellenar_tabla()

    def _rellenar_tabla(self):
        if self.orden_actual == 'monto':
            productos_ord = sorted(self.productos, key=lambda x: x.get('monto_total', 0), reverse=True)
        else:
            productos_ord = list(self.productos)

        total = len(productos_ord)
        self.lbl_conteo.setText(
            f"Mostrando {total} producto{'s' if total != 1 else ''}  •  "
            f"Ordenado por: {'Cantidad' if self.orden_actual == 'cantidad' else 'Monto Total'}")

        self.table.setRowCount(total)
        for idx, p in enumerate(productos_ord):
            rank = idx + 1
            stock = p.get('stock', 0) or 0
            unidad = p.get('unidad_medida', 'u') or 'u'
            estado = p.get('estado_stock', 'OK')

            if estado == 'AGOTADO':
                estado_txt = "❌ Agotado"
                estado_color = self.ROJO
            elif estado == 'BAJO':
                estado_txt = "⚠️ Bajo"
                estado_color = self.NARANJA
            else:
                estado_txt = "✅ OK"
                estado_color = self.VERDE

            if rank == 1:
                rank_txt = "🥇 1"
            elif rank == 2:
                rank_txt = "🥈 2"
            elif rank == 3:
                rank_txt = "🥉 3"
            else:
                rank_txt = str(rank)

            items = [
                (rank_txt, Qt.AlignCenter, None),
                (p.get('nombre', ''), Qt.AlignLeft | Qt.AlignVCenter, None),
                (p.get('categoria', ''), Qt.AlignLeft | Qt.AlignVCenter, None),
                (formatear_stock(p.get('cantidad_vendida', 0)), Qt.AlignCenter, None),
                (f"$ {p.get('monto_total', 0):,.2f}", Qt.AlignRight | Qt.AlignVCenter, None),
                (f"{p.get('porcentaje_ingresos', 0)}%", Qt.AlignCenter, None),
                (f"{formatear_stock(stock, p.get('permite_decimales'))} {unidad}", Qt.AlignCenter, None),
                (estado_txt, Qt.AlignCenter, estado_color),
            ]

            for col, (text, align, color) in enumerate(items):
                item = QTableWidgetItem(text)
                item.setTextAlignment(align)
                if color:
                    item.setForeground(QColor(color))
                self.table.setItem(idx, col, item)

    def _exportar(self):
        from PySide6.QtWidgets import QTableWidget, QFileDialog
        import exportar as _exp
        tabla = self.findChild(QTableWidget)
        if tabla is None or tabla.rowCount() == 0:
            QMessageBox.information(self, "Exportar", "No hay datos para exportar.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar a Excel", _exp.nombre_sugerido("reporte"), "Excel (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            _exp.exportar_tabla_qt(tabla, path)
            QMessageBox.information(self, "Exportación exitosa", f"Exportado a:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Error al exportar", str(exc))

    def _imprimir(self):
        QMessageBox.information(self, "Imprimir", "Funcionalidad de impresión en desarrollo.")


# ═══════════════════════════════════════════════════════════════════════════════
#  VENTANA VENTAS POR MÉTODO DE PAGO
# ═══════════════════════════════════════════════════════════════════════════════

class VentanaMetodosPago(QDialog):
    """Dashboard compacto de Ventas por Método de Pago"""

    AZUL = '#0f1b30'
    AZUL_CLARO = '#2f6fb0'
    AZUL_HEADER = '#0f1b30'
    VERDE = '#1d9e75'
    VERDE_CLARO = '#10b981'
    NARANJA = '#f59e0b'
    ROJO = '#ef4444'
    MORADO = '#8b5cf6'
    GRIS_BG = '#f1f5f9'
    GRIS_FILA = '#f8fafc'
    BORDE = '#edf2f7'
    BORDE_SUTIL = '#f0f4f8'
    TEXTO = '#0f172a'
    TEXTO_SEC = '#64748b'

    METODO_CONFIG = {
        'EFECTIVO':      {'color': '#059669', 'icon': '💵', 'label': 'Efectivo'},
        'TARJETA':       {'color': '#2563eb', 'icon': '💳', 'label': 'Tarjeta'},
        'TRANSFERENCIA': {'color': '#f59e0b', 'icon': '🏦', 'label': 'Transferencia'},
        'CREDITO':       {'color': '#8b5cf6', 'icon': '📋', 'label': 'Crédito'},
        'NEQUI':         {'color': '#e91e63', 'icon': '📱', 'label': 'Nequi'},
        'DAVIPLATA':     {'color': '#ff5722', 'icon': '📱', 'label': 'Daviplata'},
    }
    DEFAULT_CONFIG = {'color': '#64748b', 'icon': '💰', 'label': None}

    def __init__(self, parent, reportes_service):
        super().__init__(parent)
        self.reportes_service = reportes_service
        self.datos = None

        self.setWindowTitle("💳 Ventas por Método de Pago")
        self.resize(1100, 700)
        self.setMinimumSize(960, 600)
        self.setStyleSheet(f"background: {self.GRIS_BG};")

        self._crear_interfaz()
        self._cargar_datos()
        self.exec()

    def _get_metodo_cfg(self, metodo):
        cfg = self.METODO_CONFIG.get(metodo, self.DEFAULT_CONFIG)
        if cfg['label'] is None:
            cfg = dict(cfg)
            cfg['label'] = metodo.title()
        return cfg

    def _crear_interfaz(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # HEADER
        header = QFrame()
        header.setStyleSheet(f"background: {self.AZUL};")
        hdr_layout = QHBoxLayout(header)
        hdr_layout.setContentsMargins(22, 9, 22, 9)

        title = QLabel("💳 Ventas por Método de Pago")
        title.setFont(QFont('Segoe UI', 14, QFont.Bold))
        title.setStyleSheet("color: white; background: transparent;")
        hdr_layout.addWidget(title)

        # Dates
        hoy = datetime.now()
        inicio_def = hoy - timedelta(days=30)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setFont(QFont('Segoe UI', 9))
        lbl_desde.setStyleSheet("color: #93c5fd; background: transparent;")
        hdr_layout.addWidget(lbl_desde)
        self.fecha_inicio = _create_date_edit(inicio_def)
        hdr_layout.addWidget(self.fecha_inicio)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setFont(QFont('Segoe UI', 9))
        lbl_hasta.setStyleSheet("color: #93c5fd; background: transparent;")
        hdr_layout.addWidget(lbl_hasta)
        self.fecha_fin = _create_date_edit(hoy)
        hdr_layout.addWidget(self.fecha_fin)

        self._generando = False
        self.btn_generar = QPushButton("🔍 Generar")
        self.btn_generar.setFont(QFont('Segoe UI', 9, QFont.Bold))
        self.btn_generar.setCursor(Qt.PointingHandCursor)
        self.btn_generar.setStyleSheet(
            f"QPushButton {{ background: {self.VERDE}; color: white; border: none; "
            f"border-radius: 6px; padding: 4px 12px; }}"
            f"QPushButton:hover {{ background: {self.VERDE_CLARO}; }}"
        )
        self.btn_generar.clicked.connect(self._on_generar)
        hdr_layout.addWidget(self.btn_generar)

        hdr_layout.addStretch()

        for txt, cmd in [("🖨 Imprimir", self._imprimir), ("📤 Exportar", self._exportar)]:
            hdr_layout.addWidget(_make_header_btn(txt, callback=cmd))

        layout.addWidget(header)

        # KPI BAR
        self.kpi_bar = QFrame()
        self.kpi_bar.setStyleSheet("background: white; border: 1px solid #edf2f7;")
        self.kpi_bar_layout = QHBoxLayout(self.kpi_bar)
        self.kpi_bar_layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.kpi_bar)

        # MID: Donut + Desglose
        self.mid_frame = QFrame()
        self.mid_frame.setStyleSheet(f"background: {self.GRIS_BG}; border: none;")
        self.mid_layout = QHBoxLayout(self.mid_frame)
        self.mid_layout.setContentsMargins(16, 8, 16, 0)
        layout.addWidget(self.mid_frame, 1)

        # TABLA
        self.tabla_frame = QFrame()
        self.tabla_frame.setStyleSheet("background: white; border: 1px solid #edf2f7;")
        self.tabla_layout = QVBoxLayout(self.tabla_frame)
        self.tabla_layout.setContentsMargins(8, 4, 8, 8)
        layout.addWidget(self.tabla_frame)

    def _dibujar_kpis(self, datos):
        while self.kpi_bar_layout.count():
            item = self.kpi_bar_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        resumen = datos.get('resumen', {})
        predominante = datos.get('metodo_predominante', '-')
        pct_pre = datos.get('pct_predominante', 0)
        cfg_pre = self._get_metodo_cfg(predominante)
        cred = datos.get('credito_info', {})

        pendiente = cred.get('pendiente', 0)
        fact_pend = cred.get('facturas_pendientes', 0)
        fact_total = cred.get('facturas_total', 0)
        sub_cred = f"{fact_pend} de {fact_total} facturas" if fact_total > 0 else "Sin ventas a crédito"

        kpis = [
            ("💰", "Total Recaudado", f"$ {resumen.get('total_monto', 0):,.2f}", None, self.AZUL_CLARO),
            ("🧾", "Transacciones", f"{resumen.get('total_ventas', 0)}", None, self.VERDE),
            ("👑", "Predominante", f"{cfg_pre['icon']} {predominante} ({pct_pre}%)", None, self.MORADO),
            ("⚠", "Pendiente Crédito", f"$ {pendiente:,.2f}", sub_cred, self.NARANJA),
        ]

        grid = QGridLayout()
        for i in range(4):
            card = QFrame()
            card.setStyleSheet("QFrame { background: white; border: none; }")
            card_l = QVBoxLayout(card)
            card_l.setContentsMargins(6, 4, 6, 4)
            card_l.setAlignment(Qt.AlignCenter)

            icon, titulo, valor, subtexto, color = kpis[i]

            bar = QFrame()
            bar.setFixedHeight(3)
            bar.setStyleSheet(f"background: {color}; border: none;")
            card_l.addWidget(bar)

            lbl_t = QLabel(f"{icon} {titulo}")
            lbl_t.setFont(QFont('Segoe UI', 8))
            lbl_t.setAlignment(Qt.AlignCenter)
            lbl_t.setStyleSheet(f"color: {self.TEXTO_SEC}; border: none;")
            card_l.addWidget(lbl_t)

            lbl_v = QLabel(valor)
            lbl_v.setFont(QFont('Segoe UI', 13, QFont.Bold))
            lbl_v.setAlignment(Qt.AlignCenter)
            lbl_v.setStyleSheet(f"color: {color}; border: none;")
            card_l.addWidget(lbl_v)

            if subtexto:
                lbl_s = QLabel(subtexto)
                lbl_s.setFont(QFont('Segoe UI', 7))
                lbl_s.setAlignment(Qt.AlignCenter)
                lbl_s.setStyleSheet(f"color: {self.TEXTO_SEC}; border: none;")
                card_l.addWidget(lbl_s)

            grid.addWidget(card, 0, i)

        self.kpi_bar_layout.addLayout(grid)

    def _dibujar_contenido(self, datos):
        while self.mid_layout.count():
            item = self.mid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        metodos = datos.get('por_metodo', [])

        # LEFT: Donut + Legend
        left = QFrame()
        left.setStyleSheet("QFrame { background: white; border: 1px solid #edf2f7; border-radius: 4px; }")
        left_layout = QHBoxLayout(left)
        left_layout.setContentsMargins(10, 10, 10, 10)

        donut = DonutChartWidget()
        total = sum(m.get('monto_total', 0) for m in metodos) or 1
        segments = []
        for m in metodos:
            cfg = self._get_metodo_cfg(m['metodo_pago'])
            segments.append((m.get('monto_total', 0), cfg['color'], cfg['label']))
        donut.set_data(segments, f"$ {total:,.0f}")
        left_layout.addWidget(donut)

        # Legend
        legend = QVBoxLayout()
        legend.setSpacing(4)
        for m in metodos:
            cfg = self._get_metodo_cfg(m['metodo_pago'])
            row_w = QHBoxLayout()
            row_w.setSpacing(4)
            dot = QFrame()
            dot.setFixedSize(10, 10)
            dot.setStyleSheet(f"background: {cfg['color']}; border: none; border-radius: 2px;")
            row_w.addWidget(dot)
            lbl = QLabel(f"{cfg['icon']} {cfg['label']}")
            lbl.setFont(QFont('Segoe UI', 9))
            lbl.setStyleSheet("border: none;")
            row_w.addWidget(lbl)
            pct_lbl = QLabel(f"{m.get('porcentaje_monto', 0)}%")
            pct_lbl.setFont(QFont('Segoe UI', 9, QFont.Bold))
            pct_lbl.setStyleSheet(f"color: {cfg['color']}; border: none;")
            row_w.addWidget(pct_lbl)
            row_w.addStretch()
            legend.addLayout(row_w)
        legend.addStretch()
        left_layout.addLayout(legend)
        self.mid_layout.addWidget(left)

        # RIGHT: Distribution
        right = QFrame()
        right.setStyleSheet("QFrame { background: white; border: 1px solid #edf2f7; border-radius: 4px; }")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(14, 10, 14, 10)

        dist_title = QLabel("📊 Distribución y Tendencia")
        dist_title.setFont(QFont('Segoe UI', 10, QFont.Bold))
        dist_title.setStyleSheet(f"color: {self.AZUL}; border: none;")
        right_layout.addWidget(dist_title)

        if not metodos:
            no_data = QLabel("Sin datos en este período")
            no_data.setFont(QFont('Segoe UI', 9))
            no_data.setStyleSheet(f"color: {self.TEXTO_SEC}; font-style: italic; border: none;")
            right_layout.addWidget(no_data)
        else:
            max_monto = max((m.get('monto_total', 0) for m in metodos), default=1) or 1

            for idx, m in enumerate(metodos):
                cfg = self._get_metodo_cfg(m['metodo_pago'])
                color = cfg['color']

                item_frame = QFrame()
                item_frame.setStyleSheet("border: none;")
                item_layout = QVBoxLayout(item_frame)
                item_layout.setContentsMargins(0, 4, 0, 4)
                item_layout.setSpacing(2)

                # Info row
                info_row = QHBoxLayout()
                name_lbl = QLabel(f"{cfg['icon']} {cfg['label']}")
                name_lbl.setFont(QFont('Segoe UI', 10, QFont.Bold))
                name_lbl.setStyleSheet("border: none;")
                info_row.addWidget(name_lbl)

                variacion = m.get('variacion')
                if variacion is None:
                    t_txt, t_col = "✦ Nuevo", self.AZUL_CLARO
                elif variacion > 0:
                    t_txt, t_col = f"▲ +{variacion}%", self.VERDE
                elif variacion < 0:
                    t_txt, t_col = f"▼ {variacion}%", self.ROJO
                else:
                    t_txt, t_col = "— 0%", self.TEXTO_SEC

                trend_lbl = QLabel(t_txt)
                trend_lbl.setFont(QFont('Segoe UI', 8, QFont.Bold))
                trend_lbl.setStyleSheet(f"color: {t_col}; border: none;")
                info_row.addWidget(trend_lbl)
                info_row.addStretch()

                detail_lbl = QLabel(
                    f"{m.get('cantidad_ventas', 0)} txn  ·  Prom $ {m.get('promedio_venta', 0):,.0f}")
                detail_lbl.setFont(QFont('Segoe UI', 8))
                detail_lbl.setStyleSheet(f"color: {self.TEXTO_SEC}; border: none;")
                info_row.addWidget(detail_lbl)

                monto_lbl = QLabel(f"$ {m.get('monto_total', 0):>14,.2f}")
                monto_lbl.setFont(QFont('Segoe UI', 10, QFont.Bold))
                monto_lbl.setStyleSheet(f"color: {color}; border: none;")
                info_row.addWidget(monto_lbl)

                item_layout.addLayout(info_row)

                # Progress bar
                pct_width = max(m.get('monto_total', 0) / max_monto, 0.02)
                bar_bg = QFrame()
                bar_bg.setFixedHeight(6)
                bar_bg.setStyleSheet("background: #e9ecef; border: none; border-radius: 3px;")
                bar_fill = QFrame(bar_bg)
                fill_w = int(pct_width * 300)
                bar_fill.setFixedSize(max(fill_w, 2), 6)
                bar_fill.setStyleSheet(f"background: {color}; border: none; border-radius: 3px;")
                bar_fill.move(0, 0)
                item_layout.addWidget(bar_bg)

                # Credit extra info
                is_credito = m.get('metodo_pago') == 'CREDITO' and m.get('pendiente', 0) > 0
                if is_credito:
                    cred_row = QHBoxLayout()
                    cobrado = m.get('cobrado', 0)
                    pendiente_val = m.get('pendiente', 0)
                    pct_c = m.get('pct_cobrado', 0)
                    cob_lbl = QLabel(f"✅ Cobrado: $ {cobrado:,.2f} ({pct_c}%)")
                    cob_lbl.setFont(QFont('Segoe UI', 8))
                    cob_lbl.setStyleSheet(f"color: {self.VERDE}; border: none;")
                    cred_row.addWidget(cob_lbl)
                    cred_row.addStretch()
                    pend_lbl = QLabel(f"🔴 Pendiente: $ {pendiente_val:,.2f} ({round(100 - pct_c, 1)}%)")
                    pend_lbl.setFont(QFont('Segoe UI', 8))
                    pend_lbl.setStyleSheet(f"color: {self.ROJO}; border: none;")
                    cred_row.addWidget(pend_lbl)
                    item_layout.addLayout(cred_row)

                # Separator
                if idx < len(metodos) - 1:
                    sep = QFrame()
                    sep.setFixedHeight(1)
                    sep.setStyleSheet(f"background: {self.BORDE_SUTIL}; border: none;")
                    item_layout.addWidget(sep)

                right_layout.addWidget(item_frame)

        right_layout.addStretch()
        self.mid_layout.addWidget(right, 1)

    def _dibujar_tabla(self, datos):
        while self.tabla_layout.count():
            item = self.tabla_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        metodos = datos.get('por_metodo', [])

        table = QTableWidget()
        columns = [
            ('Método', 160, 'left'),
            ('Transacciones', 90, 'center'),
            ('Monto Total', 130, 'right'),
            ('Promedio', 110, 'right'),
            ('% Total', 70, 'center'),
            ('vs Ant.', 80, 'center'),
            ('Pendiente', 120, 'right'),
        ]
        _setup_table(table, columns, row_height=26)
        table.setRowCount(len(metodos))
        table.setMaximumHeight(min((len(metodos) + 1) * 28 + 30, 200))

        for idx, m in enumerate(metodos):
            cfg = self._get_metodo_cfg(m['metodo_pago'])
            v = m.get('variacion')
            if v is None:
                trend = "✦ Nuevo"
            elif v > 0:
                trend = f"▲ +{v}%"
            elif v < 0:
                trend = f"▼ {v}%"
            else:
                trend = "— 0%"

            pend = m.get('pendiente', 0)
            if m['metodo_pago'] == 'CREDITO' and pend > 0:
                pend_txt = f"$ {pend:,.2f} ⚠"
            else:
                pend_txt = "—"

            values = [
                (f"{cfg['icon']} {cfg['label']}", Qt.AlignLeft | Qt.AlignVCenter),
                (str(m.get('cantidad_ventas', 0)), Qt.AlignCenter),
                (f"$ {m.get('monto_total', 0):,.2f}", Qt.AlignRight | Qt.AlignVCenter),
                (f"$ {m.get('promedio_venta', 0):,.2f}", Qt.AlignRight | Qt.AlignVCenter),
                (f"{m.get('porcentaje_monto', 0)}%", Qt.AlignCenter),
                (trend, Qt.AlignCenter),
                (pend_txt, Qt.AlignRight | Qt.AlignVCenter),
            ]

            for col, (text, align) in enumerate(values):
                item = QTableWidgetItem(text)
                item.setTextAlignment(align)
                table.setItem(idx, col, item)

        self.tabla_layout.addWidget(table)

    def _on_generar(self):
        if self._generando:
            return
        self._generando = True
        self.btn_generar.setText("⏳ ...")
        self.btn_generar.setEnabled(False)
        QTimer.singleShot(50, self._ejecutar)

    def _ejecutar(self):
        try:
            self._cargar_datos()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error:\n{str(e)}")
        finally:
            self._generando = False
            self.btn_generar.setText("🔍 Generar")
            self.btn_generar.setEnabled(True)

    def _cargar_datos(self):
        inicio = self.fecha_inicio.date().toString('yyyy-MM-dd')
        fin = self.fecha_fin.date().toString('yyyy-MM-dd')

        try:
            datetime.strptime(inicio, '%Y-%m-%d')
            datetime.strptime(fin, '%Y-%m-%d')
        except ValueError:
            QMessageBox.warning(self, "Fecha inválida", "Formato: YYYY-MM-DD")
            return

        if inicio > fin:
            QMessageBox.warning(self, "Rango inválido",
                                "La fecha 'Desde' no puede ser mayor que 'Hasta'.")
            return

        self.datos = self.reportes_service.ventas_por_metodo_pago(inicio, fin)
        self._dibujar_kpis(self.datos)
        self._dibujar_contenido(self.datos)
        self._dibujar_tabla(self.datos)

    def _exportar(self):
        from PySide6.QtWidgets import QTableWidget, QFileDialog
        import exportar as _exp
        tabla = self.findChild(QTableWidget)
        if tabla is None or tabla.rowCount() == 0:
            QMessageBox.information(self, "Exportar", "No hay datos para exportar.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar a Excel", _exp.nombre_sugerido("reporte"), "Excel (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            _exp.exportar_tabla_qt(tabla, path)
            QMessageBox.information(self, "Exportación exitosa", f"Exportado a:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Error al exportar", str(exc))

    def _imprimir(self):
        QMessageBox.information(self, "Imprimir", "Funcionalidad de impresión en desarrollo.")


# ═══════════════════════════════════════════════════════════════════════════════
#  VENTANA ESTADÍSTICAS GENERALES – DASHBOARD KPI
# ═══════════════════════════════════════════════════════════════════════════════

class VentanaEstadisticasDashboard(QDialog):
    """Dashboard visual de Estadísticas Generales con tarjetas KPI agrupadas."""

    AZUL_HEADER = '#0f1b30'
    AZUL_COBALT = '#2f6fb0'
    VERDE = '#1d9e75'
    VERDE_CLARO = '#10b981'
    ROJO = '#ef4444'
    NARANJA = '#f59e0b'
    GRIS_BG = '#f1f5f9'
    BLANCO = '#ffffff'
    TEXTO = '#0f172a'
    TEXTO_SEC = '#64748b'
    TEXTO_LIGHT = '#94a3b8'
    SOMBRA = '#e2e8f0'

    PERIODOS = {
        'Última semana': 7,
        'Último mes': 30,
        'Último año': 365,
    }

    def __init__(self, parent, reportes_service):
        super().__init__(parent)
        self.reportes_service = reportes_service

        self.setWindowTitle("Estadísticas Generales")
        self.resize(960, 620)
        self.setStyleSheet(f"background: {self.GRIS_BG};")
        self.setFixedSize(960, 620)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self._crear_header()

        self.body_widget = QWidget()
        self.body = QVBoxLayout(self.body_widget)
        self.main_layout.addWidget(self.body_widget, 1)

        self._cargar_datos()
        self.exec()

    def _crear_header(self):
        header = QFrame()
        header.setFixedHeight(54)
        header.setStyleSheet(f"background: {self.AZUL_HEADER};")
        hdr_layout = QHBoxLayout(header)
        hdr_layout.setContentsMargins(20, 0, 20, 0)

        title = QLabel("📊  Estadísticas Generales")
        title.setFont(QFont('Segoe UI', 14, QFont.Bold))
        title.setStyleSheet(f"color: white; background: transparent;")
        hdr_layout.addWidget(title)
        hdr_layout.addStretch()

        # Period selector
        lbl_periodo = QLabel("Periodo:")
        lbl_periodo.setFont(QFont('Segoe UI', 9))
        lbl_periodo.setStyleSheet("color: #cbd5e1; background: transparent;")
        hdr_layout.addWidget(lbl_periodo)

        self.periodo_combo = QComboBox()
        self.periodo_combo.addItems(list(self.PERIODOS.keys()))
        self.periodo_combo.setCurrentText('Último mes')
        self.periodo_combo.setFont(QFont('Segoe UI', 9))
        self.periodo_combo.setFixedWidth(150)
        self.periodo_combo.currentTextChanged.connect(lambda: self._cargar_datos())
        hdr_layout.addWidget(self.periodo_combo)

        for txt, cmd in [("🖨️ Imprimir", self._imprimir), ("📤 Exportar", self._exportar)]:
            hdr_layout.addWidget(_make_header_btn(txt, callback=cmd))

        self.main_layout.addWidget(header)

    def _cargar_datos(self):
        # Clear body
        while self.body.count():
            item = self.body.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

        dias = self.PERIODOS.get(self.periodo_combo.currentText(), 30)
        hoy = datetime.now()
        fecha_fin = hoy.strftime('%Y-%m-%d')
        fecha_inicio = (hoy - timedelta(days=dias)).strftime('%Y-%m-%d')

        try:
            datos = self.reportes_service.estadisticas_generales(fecha_inicio, fecha_fin)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al obtener estadísticas: {e}")
            return

        # Fila 1 – Inventario
        self._crear_seccion("📦  Inventario", [
            ("🏷️", "Total Productos", str(datos.get('total_productos', 0)), self.AZUL_COBALT),
            ("💲", "Valor Inv. Costo", self._fmt(datos.get('valor_inventario_costo', 0)), self.AZUL_COBALT),
            ("🏪", "Valor Inv. Venta", self._fmt(datos.get('valor_inventario_venta', 0)), self.AZUL_COBALT),
        ])

        # Fila 2 – Ventas y Alcance
        self._crear_seccion("🛒  Ventas y Alcance", [
            ("🧾", "Total Ventas", str(datos.get('total_ventas', 0)), self.AZUL_COBALT),
            ("💰", "Monto Total Ventas", self._fmt(datos.get('monto_total_ventas', 0)), self.AZUL_COBALT),
            ("👥", "Total Clientes", str(datos.get('total_clientes', 0)), self.AZUL_COBALT),
            ("🚚", "Total Proveedores", str(datos.get('total_proveedores', 0)), self.AZUL_COBALT),
        ])

        # Fila 3 – Rendimiento del Periodo
        margen = datos.get('margen_mes', 0)
        color_margen = self.VERDE if margen >= 0 else self.ROJO

        self._crear_seccion("📈  Rendimiento del Periodo", [
            ("💵", "Ingresos", self._fmt(datos.get('ingresos_mes', 0)), self.VERDE),
            ("💸", "Costos", self._fmt(datos.get('costos_mes', 0)), self.NARANJA),
            ("💹", "Utilidad", self._fmt(datos.get('utilidad_mes', 0)), self.VERDE_CLARO),
            ("⬆️", "Margen", f"{margen}%", color_margen),
        ], destacada=True)

        self.body.addStretch()

    def _crear_seccion(self, titulo, tarjetas, destacada=False):
        section = QFrame()
        section.setStyleSheet(f"background: {self.GRIS_BG}; border: none;")
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(24, 6, 24, 0)
        section_layout.setSpacing(4)

        lbl = QLabel(titulo)
        lbl.setFont(QFont('Segoe UI', 10, QFont.Bold))
        lbl.setStyleSheet(f"color: {self.TEXTO}; background: transparent;")
        section_layout.addWidget(lbl)

        cards_grid = QGridLayout()
        cards_grid.setSpacing(8)
        for i, (icono, etiqueta, valor, color_acento) in enumerate(tarjetas):
            cards_grid.setColumnStretch(i, 1)
            self._crear_tarjeta(cards_grid, icono, etiqueta, valor, color_acento, i, destacada)

        section_layout.addLayout(cards_grid)
        self.body.addWidget(section)

    def _crear_tarjeta(self, grid, icono, etiqueta, valor, color_acento, col, destacada):
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: {self.BLANCO}; border: 1px solid {self.SOMBRA}; border-radius: 4px; }}"
        )
        card.setFixedHeight(82)
        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(12, 8, 12, 8)
        card_l.setSpacing(2)

        bar = QFrame()
        bar.setFixedHeight(3)
        bar.setStyleSheet(f"background: {color_acento}; border: none;")
        card_l.addWidget(bar)

        top = QHBoxLayout()
        lbl_icon = QLabel(icono)
        lbl_icon.setFont(QFont('Segoe UI', 10))
        lbl_icon.setStyleSheet("border: none;")
        top.addWidget(lbl_icon)
        lbl_etiq = QLabel(etiqueta)
        lbl_etiq.setFont(QFont('Segoe UI', 8))
        lbl_etiq.setStyleSheet(f"color: {self.TEXTO_LIGHT}; border: none;")
        top.addWidget(lbl_etiq)
        top.addStretch()
        card_l.addLayout(top)

        if destacada:
            fs = 16 if len(valor) <= 8 else (14 if len(valor) <= 12 else 12)
            fg = color_acento
        else:
            fs = 18 if len(valor) <= 8 else (15 if len(valor) <= 12 else 13)
            fg = self.TEXTO

        lbl_val = QLabel(valor)
        lbl_val.setFont(QFont('Segoe UI', fs, QFont.Bold))
        lbl_val.setStyleSheet(f"color: {fg}; border: none;")
        card_l.addWidget(lbl_val)

        grid.addWidget(card, 0, col)

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    @staticmethod
    def _fmt(valor):
        try:
            return f"${float(valor):,.2f}"
        except (ValueError, TypeError):
            return "$0.00"

    def _exportar(self):
        from PySide6.QtWidgets import QTableWidget, QFileDialog
        import exportar as _exp
        tabla = self.findChild(QTableWidget)
        if tabla is None or tabla.rowCount() == 0:
            QMessageBox.information(self, "Exportar", "No hay datos para exportar.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar a Excel", _exp.nombre_sugerido("reporte"), "Excel (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            _exp.exportar_tabla_qt(tabla, path)
            QMessageBox.information(self, "Exportación exitosa", f"Exportado a:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Error al exportar", str(exc))

    def _imprimir(self):
        QMessageBox.information(self, "Imprimir", "Funcionalidad de impresión en desarrollo.")


# ═══════════════════════════════════════════════════════════════════════════════
#  VENTANA REPORTE GENÉRICA
# ═══════════════════════════════════════════════════════════════════════════════

class VentanaReporte(QDialog):
    """Ventana genérica para mostrar reportes sin parámetros"""

    def __init__(self, parent, titulo, funcion_reporte):
        super().__init__(parent)
        self.funcion_reporte = funcion_reporte

        self.setWindowTitle(titulo)
        self.resize(900, 600)

        self.crear_interfaz(titulo)
        self.cargar_reporte()
        self.exec()

    def crear_interfaz(self, titulo):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(60)
        header.setStyleSheet(f"background: {COLORS['primary']};")
        hdr_layout = QHBoxLayout(header)
        hdr_layout.setContentsMargins(20, 0, 20, 0)

        title_lbl = QLabel(titulo)
        title_lbl.setFont(make_font(FONTS['large']))
        title_lbl.setStyleSheet("color: white; background: transparent;")
        hdr_layout.addWidget(title_lbl)
        hdr_layout.addStretch()

        btn_export = _make_header_btn(f"{ICONS['exportar']} Exportar", callback=self.exportar)
        hdr_layout.addWidget(btn_export)
        btn_print = _make_header_btn(f"{ICONS['imprimir']} Imprimir", callback=self.imprimir)
        hdr_layout.addWidget(btn_print)

        layout.addWidget(header)

        # Content
        content = QFrame()
        content.setStyleSheet("background: white;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 20, 20, 20)

        self.text = QTextEdit()
        self.text.setFont(QFont('Courier New', 10))
        self.text.setReadOnly(True)
        self.text.setStyleSheet("background: white; border: none;")
        content_layout.addWidget(self.text)

        layout.addWidget(content, 1)

    def cargar_reporte(self):
        try:
            datos = self.funcion_reporte()
            self.text.clear()

            if isinstance(datos, dict):
                texto = self.formatear_dict(datos)
            elif isinstance(datos, list):
                texto = self.formatear_lista(datos)
            else:
                texto = str(datos)

            self.text.setPlainText(texto)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al generar reporte: {str(e)}")

    def formatear_dict(self, datos, nivel=0):
        texto = ""
        indent = "  " * nivel
        for key, value in datos.items():
            label = str(key).replace('_', ' ').title()
            if isinstance(value, dict):
                texto += f"{indent}{'─' * 40}\n" if nivel == 0 else ""
                texto += f"{indent}{label}:\n"
                texto += self.formatear_dict(value, nivel + 1)
            elif isinstance(value, list):
                texto += f"{indent}{'─' * 40}\n" if nivel == 0 else ""
                texto += f"{indent}{label}: ({len(value)} registros)\n"
                texto += self.formatear_lista(value, nivel + 1)
            else:
                if isinstance(value, float):
                    value = f"{value:,.2f}"
                texto += f"{indent}{label}: {value}\n"
        return texto

    def formatear_lista(self, datos, nivel=0):
        texto = ""
        indent = "  " * nivel
        for i, item in enumerate(datos, 1):
            if isinstance(item, dict):
                texto += f"{indent}{'─' * 30}\n"
                texto += f"{indent}#{i}\n"
                for key, value in item.items():
                    label = str(key).replace('_', ' ').title()
                    if isinstance(value, float):
                        value = f"{value:,.2f}"
                    texto += f"{indent}  {label}: {value}\n"
            else:
                texto += f"{indent}{i}. {item}\n"
        return texto

    def imprimir(self):
        QMessageBox.information(self, "Imprimir", "Funcionalidad de impresión en desarrollo")

    def exportar(self):
        QMessageBox.information(self, "Exportar", "Funcionalidad de exportación en desarrollo")


# ═══════════════════════════════════════════════════════════════════════════════
#  VENTANA RENTABILIDAD – DASHBOARD KPI
# ═══════════════════════════════════════════════════════════════════════════════

class VentanaRentabilidadDashboard(QDialog):
    """Dashboard visual de Rentabilidad con tarjetas KPI + gráfica + top productos."""

    AZUL_HEADER = '#0f1b30'
    AZUL_COBALT = '#2f6fb0'
    VERDE = '#1d9e75'
    VERDE_CLARO = '#10b981'
    NARANJA = '#f59e0b'
    ROJO = '#ef4444'
    GRIS_BG = '#f1f5f9'
    BLANCO = '#ffffff'
    TEXTO = '#0f172a'
    TEXTO_SEC = '#64748b'
    TEXTO_LIGHT = '#94a3b8'
    SOMBRA = '#e2e8f0'

    def __init__(self, parent, reportes_service):
        super().__init__(parent)
        self.reportes_service = reportes_service

        self.setWindowTitle("💹 Reporte de Rentabilidad")
        self.resize(960, 640)
        self.setStyleSheet(f"background: {self.GRIS_BG};")
        self.setFixedSize(960, 640)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        self.main_layout = main_layout

        self._crear_header()
        self._crear_filtros()

        self.body_widget = QWidget()
        self.body = QVBoxLayout(self.body_widget)
        self.body.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.body_widget, 1)

        self._generar()
        self.exec()

    def _crear_header(self):
        header = QFrame()
        header.setFixedHeight(50)
        header.setStyleSheet(f"background: {self.AZUL_HEADER};")
        hdr_layout = QHBoxLayout(header)
        hdr_layout.setContentsMargins(20, 0, 20, 0)

        title = QLabel("💹  Reporte de Rentabilidad")
        title.setFont(QFont('Segoe UI', 14, QFont.Bold))
        title.setStyleSheet("color: white; background: transparent;")
        hdr_layout.addWidget(title)
        hdr_layout.addStretch()

        for txt, cmd in [("🖨️ Imprimir", self._imprimir), ("📤 Exportar", self._exportar)]:
            hdr_layout.addWidget(_make_header_btn(txt, callback=cmd))

        self.main_layout.addWidget(header)

    def _crear_filtros(self):
        wrapper = QFrame()
        wrapper.setStyleSheet(f"background: {self.GRIS_BG}; border: none;")
        w_layout = QHBoxLayout(wrapper)
        w_layout.setContentsMargins(28, 16, 28, 8)

        bar = QFrame()
        bar.setStyleSheet(f"background: {self.BLANCO}; border: none; border-radius: 6px;")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(16, 8, 16, 8)

        hoy = datetime.now()
        inicio_def = hoy - timedelta(days=30)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setFont(QFont('Segoe UI', 9, QFont.Bold))
        bar_layout.addWidget(lbl_desde)
        self.fecha_inicio = _create_date_edit(inicio_def)
        bar_layout.addWidget(self.fecha_inicio)

        bar_layout.addSpacing(16)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setFont(QFont('Segoe UI', 9, QFont.Bold))
        bar_layout.addWidget(lbl_hasta)
        self.fecha_fin = _create_date_edit(hoy)
        bar_layout.addWidget(self.fecha_fin)

        bar_layout.addSpacing(20)

        btn_gen = QPushButton("🔍 Generar Reporte")
        btn_gen.setFont(QFont('Segoe UI', 9, QFont.Bold))
        btn_gen.setCursor(Qt.PointingHandCursor)
        btn_gen.setStyleSheet(
            f"QPushButton {{ background: {self.AZUL_COBALT}; color: white; border: none; "
            f"border-radius: 6px; padding: 6px 16px; }}"
            f"QPushButton:hover {{ background: #1d4ed8; }}"
        )
        btn_gen.clicked.connect(self._generar)
        bar_layout.addWidget(btn_gen)

        w_layout.addWidget(bar)
        w_layout.addStretch()
        self.main_layout.addWidget(wrapper)

    def _generar(self):
        while self.body.count():
            item = self.body.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

        inicio = self.fecha_inicio.date().toString('yyyy-MM-dd')
        fin = self.fecha_fin.date().toString('yyyy-MM-dd')

        try:
            d = self.reportes_service.reporte_rentabilidad(inicio, fin)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al generar reporte: {e}")
            return

        margen = d.get('margen_utilidad', 0)
        utilidad = d.get('utilidad_bruta', 0)
        ingresos = d.get('ingresos_ventas', 0)
        costos = d.get('costo_ventas', 0)
        color_util = self.VERDE_CLARO if utilidad >= 0 else self.ROJO
        color_margen = self.VERDE if margen >= 30 else (self.NARANJA if margen >= 0 else self.ROJO)

        tarjetas = [
            ("💰", "Ingresos Ventas", self._fmt(ingresos), self.VERDE),
            ("🚚", "Costo Ventas", self._fmt(costos), self.NARANJA),
            ("📈", "Utilidad Bruta", self._fmt(utilidad), color_util),
            ("⬆️", "Margen Utilidad", f"{round(margen, 2)}%", color_margen),
        ]

        # KPI cards
        cards_grid = QGridLayout()
        cards_grid.setContentsMargins(28, 4, 28, 0)
        cards_grid.setSpacing(10)
        for i, (icono, etiqueta, valor, color) in enumerate(tarjetas):
            cards_grid.setColumnStretch(i, 1)
            _make_kpi_card(cards_grid, icono, etiqueta, valor, color, col=i)

        cards_widget = QWidget()
        cards_widget.setLayout(cards_grid)
        self.body.addWidget(cards_widget)

        # Period label
        lbl_periodo = QLabel(f"Periodo: {inicio}  a  {fin}")
        lbl_periodo.setFont(QFont('Segoe UI', 8))
        lbl_periodo.setAlignment(Qt.AlignCenter)
        lbl_periodo.setStyleSheet(f"color: {self.TEXTO_LIGHT};")
        self.body.addWidget(lbl_periodo)

        # Bottom row: chart + top 5
        bottom = QHBoxLayout()
        bottom.setContentsMargins(28, 0, 28, 16)

        # Chart
        chart_frame = QFrame()
        chart_frame.setStyleSheet(
            f"QFrame {{ background: {self.BLANCO}; border: 1px solid {self.SOMBRA}; border-radius: 4px; }}"
        )
        chart_layout = QVBoxLayout(chart_frame)
        chart_layout.setContentsMargins(12, 10, 12, 10)

        chart_title = QLabel("Ingresos vs Costos vs Utilidad")
        chart_title.setFont(QFont('Segoe UI', 9, QFont.Bold))
        chart_title.setAlignment(Qt.AlignCenter)
        chart_title.setStyleSheet("border: none;")
        chart_layout.addWidget(chart_title)

        chart = BarChartWidget()
        chart.set_data([
            ("Ingresos", ingresos, self.VERDE),
            ("Costos", costos, self.NARANJA),
            ("Utilidad", utilidad, self.VERDE_CLARO),
        ])
        chart_layout.addWidget(chart)
        bottom.addWidget(chart_frame)

        # Top 5 products
        self._crear_top_productos(bottom, inicio, fin)

        bottom_widget = QWidget()
        bottom_widget.setLayout(bottom)
        self.body.addWidget(bottom_widget, 1)

    def _crear_top_productos(self, parent_layout, inicio, fin):
        panel = QFrame()
        panel.setStyleSheet(
            f"QFrame {{ background: {self.BLANCO}; border: 1px solid {self.SOMBRA}; border-radius: 4px; }}"
        )
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(12, 10, 12, 10)

        title = QLabel("🏆 Top 5 Productos del Periodo")
        title.setFont(QFont('Segoe UI', 9, QFont.Bold))
        title.setStyleSheet("border: none;")
        panel_layout.addWidget(title)

        try:
            datos = self.reportes_service.reporte_productos_mas_vendidos(inicio, fin, limite=5)
            productos = datos.get('productos', datos) if isinstance(datos, dict) else datos
            if isinstance(productos, dict):
                productos = productos.get('productos', [])
        except Exception:
            productos = []

        table = QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(['Producto', 'Cant.', 'Monto'])
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(24)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setStretchLastSection(True)
        table.setColumnWidth(0, 160)
        table.setColumnWidth(1, 50)
        table.setColumnWidth(2, 90)
        table.setStyleSheet(
            "QTableWidget { background: white; alternate-background-color: #f8fafc; border: none; gridline-color: #eef2f7; }"
            "QHeaderView::section { background: #eef2f7; color: #64748b; font-weight: 500; "
            "padding: 3px; border: none; font-size: 8pt; }"
        )

        if not productos:
            table.setRowCount(1)
            item = QTableWidgetItem("Sin datos en este periodo")
            item.setTextAlignment(Qt.AlignCenter)
            table.setItem(0, 0, item)
            table.setSpan(0, 0, 1, 3)
        else:
            prods = productos[:5]
            table.setRowCount(len(prods))
            for i, p in enumerate(prods):
                nombre = p.get('nombre', '?')
                if len(nombre) > 22:
                    nombre = nombre[:20] + '..'
                cant = p.get('cantidad_vendida', 0)
                monto = p.get('monto_total', 0)

                item_name = QTableWidgetItem(nombre)
                table.setItem(i, 0, item_name)

                item_cant = QTableWidgetItem(str(int(cant)))
                item_cant.setTextAlignment(Qt.AlignCenter)
                table.setItem(i, 1, item_cant)

                item_monto = QTableWidgetItem(self._fmt_short(monto))
                item_monto.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                item_monto.setForeground(QColor(self.AZUL_COBALT))
                item_monto.setFont(QFont('Segoe UI', 8, QFont.Bold))
                table.setItem(i, 2, item_monto)

        panel_layout.addWidget(table, 1)
        parent_layout.addWidget(panel)

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    @staticmethod
    def _fmt(v):
        try:
            return f"${float(v):,.2f}"
        except (ValueError, TypeError):
            return "$0.00"

    @staticmethod
    def _fmt_short(v):
        try:
            v = float(v)
            if v >= 1_000_000:
                return f"${v/1_000_000:,.1f}M"
            elif v >= 1_000:
                return f"${v:,.0f}"
            return f"${v:,.2f}"
        except (ValueError, TypeError):
            return "$0"

    def _exportar(self):
        from PySide6.QtWidgets import QTableWidget, QFileDialog
        import exportar as _exp
        tabla = self.findChild(QTableWidget)
        if tabla is None or tabla.rowCount() == 0:
            QMessageBox.information(self, "Exportar", "No hay datos para exportar.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar a Excel", _exp.nombre_sugerido("reporte"), "Excel (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            _exp.exportar_tabla_qt(tabla, path)
            QMessageBox.information(self, "Exportación exitosa", f"Exportado a:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Error al exportar", str(exc))

    def _imprimir(self):
        QMessageBox.information(self, "Imprimir", "Funcionalidad de impresión en desarrollo.")


# ═══════════════════════════════════════════════════════════════════════════════
#  VENTANA CUENTAS POR COBRAR
# ═══════════════════════════════════════════════════════════════════════════════

class VentanaCuentasCobrar(QDialog):
    """Dashboard de Cuentas por Cobrar con KPIs, búsqueda y tabla profesional."""

    AZUL_HEADER = '#0f1b30'
    AZUL_COBALT = '#2f6fb0'
    VERDE = '#1d9e75'
    VERDE_CLARO = '#d1fae5'
    NARANJA = '#f59e0b'
    NARANJA_CLARO = '#fef3c7'
    ROJO = '#ef4444'
    ROJO_CLARO = '#fee2e2'
    GRIS_BG = '#f1f5f9'
    BLANCO = '#ffffff'
    TEXTO = '#0f172a'
    TEXTO_SEC = '#64748b'
    TEXTO_LIGHT = '#94a3b8'
    SOMBRA = '#e2e8f0'
    FILA_ALT = '#f8fafc'

    def __init__(self, parent, reportes_service):
        super().__init__(parent)
        self.reportes_service = reportes_service
        self.datos_raw = []

        self.setWindowTitle("📋 Cuentas por Cobrar")
        self.resize(980, 600)
        self.setStyleSheet(f"background: {self.GRIS_BG};")
        self.setFixedSize(980, 600)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        self.main_layout = main_layout

        self._crear_header()

        self.kpi_frame = QFrame()
        self.kpi_frame.setStyleSheet("background: transparent; border: none;")
        self.kpi_layout = QGridLayout(self.kpi_frame)
        self.kpi_layout.setContentsMargins(24, 12, 24, 4)
        main_layout.addWidget(self.kpi_frame)

        self._crear_busqueda()
        self._crear_tabla()
        self._cargar()
        self.exec()

    def _crear_header(self):
        header = QFrame()
        header.setFixedHeight(50)
        header.setStyleSheet(f"background: {self.AZUL_HEADER};")
        hdr_layout = QHBoxLayout(header)
        hdr_layout.setContentsMargins(20, 0, 20, 0)

        title = QLabel("📋  Cuentas por Cobrar")
        title.setFont(QFont('Segoe UI', 14, QFont.Bold))
        title.setStyleSheet("color: white; background: transparent;")
        hdr_layout.addWidget(title)
        hdr_layout.addStretch()

        for txt, cmd in [("🖨️ Imprimir", self._imprimir), ("📤 Exportar", self._exportar)]:
            hdr_layout.addWidget(_make_header_btn(txt, callback=cmd))

        self.main_layout.addWidget(header)

    def _dibujar_kpis(self, datos):
        while self.kpi_layout.count():
            item = self.kpi_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        total_cobrar = sum(float(r.get('saldo_pendiente', 0) or 0) for r in datos)
        clientes_mora = len(set(r.get('cliente_nombre', '') for r in datos
                                if float(r.get('dias_vencidos', 0) or 0) > 0))

        kpis = [
            ("💰", "Total por Cobrar", f"${total_cobrar:,.2f}", self.ROJO),
            ("⚠️", "Clientes en Mora", str(clientes_mora), self.NARANJA),
            ("📄", "Facturas Pendientes", str(len(datos)), self.AZUL_COBALT),
        ]

        for i, (icono, label, valor, color) in enumerate(kpis):
            self.kpi_layout.setColumnStretch(i, 1)
            _make_kpi_card(self.kpi_layout, icono, label, valor, color, col=i)

    def _crear_busqueda(self):
        bar = QFrame()
        bar.setStyleSheet(f"background: {self.GRIS_BG}; border: none;")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(24, 6, 24, 4)

        lbl_icon = QLabel("🔍")
        lbl_icon.setFont(QFont('Segoe UI', 11))
        bar_layout.addWidget(lbl_icon)

        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText("Buscar por cliente o factura")
        self.search_entry.setFont(QFont('Segoe UI', 10))
        self.search_entry.setFixedWidth(300)
        self.search_entry.setStyleSheet(
            "QLineEdit { background: white; border: 1px solid #d1d5db; border-radius: 4px; padding: 4px 8px; }"
        )
        self.search_entry.textChanged.connect(self._filtrar)
        bar_layout.addWidget(self.search_entry)
        bar_layout.addStretch()

        self.main_layout.addWidget(bar)

    def _crear_tabla(self):
        self.table = QTableWidget()
        columns = [
            ('Factura', 100, 'center'),
            ('Cliente', 160, 'left'),
            ('Vencimiento', 100, 'center'),
            ('Días Venc.', 70, 'center'),
            ('Monto Total', 110, 'right'),
            ('Saldo Pend.', 110, 'right'),
            ('Estado', 80, 'center'),
        ]
        _setup_table(self.table, columns, row_height=32)
        self.table.setStyleSheet(
            self.table.styleSheet() +
            "QTableWidget { border: 1px solid #d1d5db; }"
        )

        container = QFrame()
        container.setStyleSheet("border: none;")
        c_layout = QVBoxLayout(container)
        c_layout.setContentsMargins(24, 2, 24, 16)
        c_layout.addWidget(self.table)
        self.main_layout.addWidget(container, 1)

    def _cargar(self):
        try:
            self.datos_raw = self.reportes_service.reporte_cuentas_por_cobrar()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al cargar datos: {e}")
            self.datos_raw = []
        self._dibujar_kpis(self.datos_raw)
        self._renderizar(self.datos_raw)

    def _filtrar(self):
        q = self.search_entry.text().lower().strip()
        if not q:
            filtrados = self.datos_raw
        else:
            filtrados = [r for r in self.datos_raw
                         if q in str(r.get('cliente_nombre', '')).lower()
                         or q in str(r.get('numero_factura', '')).lower()]
        self._dibujar_kpis(filtrados)
        self._renderizar(filtrados)

    def _renderizar(self, datos):
        self.table.setRowCount(len(datos))

        for i, r in enumerate(datos):
            factura = str(r.get('numero_factura', '-'))
            cliente = str(r.get('cliente_nombre', '-'))
            if len(cliente) > 20:
                cliente = cliente[:18] + '..'
            venc_raw = str(r.get('fecha_vencimiento', ''))
            vencimiento = venc_raw[:10] if len(venc_raw) >= 10 else venc_raw
            dias = float(r.get('dias_vencidos', 0) or 0)
            monto = float(r.get('monto_total', 0) or 0)
            saldo = float(r.get('saldo_pendiente', 0) or 0)
            estado = str(r.get('estado', 'PENDIENTE'))

            if dias > 60:
                dias_color = self.ROJO
            elif dias > 30:
                dias_color = self.NARANJA
            else:
                dias_color = self.TEXTO

            saldo_color = self.ROJO if saldo > 0 else self.VERDE

            if estado == 'PENDIENTE':
                estado_color = self.ROJO
            elif estado == 'PAGADO':
                estado_color = self.VERDE
            else:
                estado_color = self.NARANJA

            values = [
                (factura, Qt.AlignCenter, self.AZUL_COBALT, False),
                (cliente, Qt.AlignLeft | Qt.AlignVCenter, self.TEXTO, False),
                (vencimiento, Qt.AlignCenter, self.TEXTO, False),
                (f"{int(dias)}d", Qt.AlignCenter, dias_color, True),
                (f"${monto:,.2f}", Qt.AlignRight | Qt.AlignVCenter, self.TEXTO, False),
                (f"${saldo:,.2f}", Qt.AlignRight | Qt.AlignVCenter, saldo_color, True),
                (estado, Qt.AlignCenter, estado_color, True),
            ]

            for col, (text, align, fg, bold) in enumerate(values):
                item = QTableWidgetItem(text)
                item.setTextAlignment(align)
                item.setForeground(QColor(fg))
                if bold:
                    f = QFont('Segoe UI', 9, QFont.Bold)
                    item.setFont(f)
                self.table.setItem(i, col, item)

    def _exportar(self):
        from PySide6.QtWidgets import QTableWidget, QFileDialog
        import exportar as _exp
        tabla = self.findChild(QTableWidget)
        if tabla is None or tabla.rowCount() == 0:
            QMessageBox.information(self, "Exportar", "No hay datos para exportar.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar a Excel", _exp.nombre_sugerido("reporte"), "Excel (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            _exp.exportar_tabla_qt(tabla, path)
            QMessageBox.information(self, "Exportación exitosa", f"Exportado a:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Error al exportar", str(exc))

    def _imprimir(self):
        QMessageBox.information(self, "Imprimir", "Funcionalidad de impresión en desarrollo.")


# ═══════════════════════════════════════════════════════════════════════════════
#  VENTANA ROTACIÓN DE INVENTARIO
# ═══════════════════════════════════════════════════════════════════════════════

class VentanaRotacionInventario(QDialog):
    """Dashboard analítico de Rotación de Inventario con KPIs, tabla y semáforo."""

    AZUL_HEADER = '#0f1b30'
    AZUL_COBALT = '#2f6fb0'
    VERDE = '#1d9e75'
    VERDE_BG = '#d1fae5'
    AMARILLO = '#d97706'
    AMARILLO_BG = '#fef3c7'
    ROJO = '#ef4444'
    ROJO_BG = '#fee2e2'
    GRIS_BG = '#f1f5f9'
    BLANCO = '#ffffff'
    TEXTO = '#0f172a'
    TEXTO_SEC = '#64748b'
    TEXTO_LIGHT = '#94a3b8'
    SOMBRA = '#e2e8f0'
    FILA_ALT = '#f8fafc'

    def __init__(self, parent, reportes_service):
        super().__init__(parent)
        self.reportes_service = reportes_service
        self.datos_raw = []
        self.sort_asc = False

        self.setWindowTitle("🔄 Rotación de Inventario")
        self.resize(980, 620)
        self.setStyleSheet(f"background: {self.GRIS_BG};")
        self.setFixedSize(980, 620)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        self.main_layout = main_layout

        self._crear_header()

        self.kpi_frame = QFrame()
        self.kpi_frame.setStyleSheet("background: transparent; border: none;")
        self.kpi_layout = QGridLayout(self.kpi_frame)
        self.kpi_layout.setContentsMargins(24, 12, 24, 4)
        main_layout.addWidget(self.kpi_frame)

        self._crear_busqueda()
        self._crear_tabla()
        self._cargar()
        self.exec()

    def _crear_header(self):
        header = QFrame()
        header.setFixedHeight(50)
        header.setStyleSheet(f"background: {self.AZUL_HEADER};")
        hdr_layout = QHBoxLayout(header)
        hdr_layout.setContentsMargins(20, 0, 20, 0)

        title = QLabel("🔄  Rotación de Inventario")
        title.setFont(QFont('Segoe UI', 14, QFont.Bold))
        title.setStyleSheet("color: white; background: transparent;")
        hdr_layout.addWidget(title)
        hdr_layout.addStretch()

        for txt, cmd in [("🖨️ Imprimir", self._imprimir), ("📤 Exportar", self._exportar)]:
            hdr_layout.addWidget(_make_header_btn(txt, callback=cmd))

        self.main_layout.addWidget(header)

    def _dibujar_kpis(self, datos):
        while self.kpi_layout.count():
            item = self.kpi_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        estrella = '-'
        if datos:
            mejor = max(datos, key=lambda d: float(d.get('indice_rotacion', 0) or 0))
            estrella = str(mejor.get('nombre', '-'))
            if len(estrella) > 18:
                estrella = estrella[:16] + '..'

        indices = [float(d.get('indice_rotacion', 0) or 0) for d in datos]
        promedio = sum(indices) / len(indices) if indices else 0
        critico = sum(1 for d in datos if int(d.get('stock_actual', 0) or 0) < 5)

        kpis = [
            ("⭐", "Producto Estrella", estrella, self.AZUL_COBALT),
            ("📊", "Promedio Rotación", f"{promedio:.2f}", self.VERDE),
            ("⚠️", "Stock Crítico (<5)", str(critico), self.ROJO),
        ]

        for i, (icono, label, valor, color) in enumerate(kpis):
            self.kpi_layout.setColumnStretch(i, 1)
            _make_kpi_card(self.kpi_layout, icono, label, valor, color, col=i)

    def _crear_busqueda(self):
        bar = QFrame()
        bar.setStyleSheet(f"background: {self.GRIS_BG}; border: none;")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(24, 6, 24, 4)

        lbl_icon = QLabel("🔍")
        lbl_icon.setFont(QFont('Segoe UI', 11))
        bar_layout.addWidget(lbl_icon)

        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText("Buscar por categoría o marca")
        self.search_entry.setFont(QFont('Segoe UI', 10))
        self.search_entry.setFixedWidth(280)
        self.search_entry.setStyleSheet(
            "QLineEdit { background: white; border: 1px solid #d1d5db; border-radius: 4px; padding: 4px 8px; }"
        )
        self.search_entry.textChanged.connect(self._filtrar)
        bar_layout.addWidget(self.search_entry)
        bar_layout.addStretch()

        self.main_layout.addWidget(bar)

    def _crear_tabla(self):
        self.table = QTableWidget()
        columns = [
            ('Producto', 170, 'left'),
            ('Categoría', 110, 'left'),
            ('Stock', 60, 'center'),
            ('Vendidas', 70, 'center'),
            ('Índice Rot.', 80, 'center'),
            ('Estatus', 90, 'center'),
        ]
        _setup_table(self.table, columns, row_height=30)

        # Header click for rotation sort
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_click)

        container = QFrame()
        container.setStyleSheet("border: none;")
        c_layout = QVBoxLayout(container)
        c_layout.setContentsMargins(24, 2, 24, 16)
        c_layout.addWidget(self.table)
        self.main_layout.addWidget(container, 1)

    def _on_header_click(self, col):
        if col == 4:  # Índice Rot. column
            self._sort_rotacion()

    def _cargar(self):
        try:
            self.datos_raw = self.reportes_service.rotacion_inventario()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al cargar datos: {e}")
            self.datos_raw = []
        self._dibujar_kpis(self.datos_raw)
        self._renderizar(self.datos_raw)

    def _filtrar(self):
        q = self.search_entry.text().lower().strip()
        if not q:
            filtrados = self.datos_raw
        else:
            filtrados = [r for r in self.datos_raw
                         if q in str(r.get('categoria', '')).lower()
                         or q in str(r.get('marca', '')).lower()
                         or q in str(r.get('nombre', '')).lower()]
        self._dibujar_kpis(filtrados)
        self._renderizar(filtrados)

    def _sort_rotacion(self):
        self.sort_asc = not self.sort_asc
        datos = sorted(self.datos_raw,
                        key=lambda d: float(d.get('indice_rotacion', 0) or 0),
                        reverse=not self.sort_asc)
        self.datos_raw = datos
        self._filtrar()

    def _renderizar(self, datos):
        self.table.setRowCount(len(datos))

        for i, r in enumerate(datos):
            nombre = str(r.get('nombre', '-'))
            marca = str(r.get('marca', ''))
            prod_txt = nombre
            if marca:
                prod_txt += f"  ({marca})"
            if len(prod_txt) > 24:
                prod_txt = prod_txt[:22] + '..'

            cat = str(r.get('categoria', '-'))
            stock = int(r.get('stock_actual', 0) or 0)
            vend = int(r.get('unidades_vendidas', 0) or 0)
            rot = float(r.get('indice_rotacion', 0) or 0)

            if rot >= 3:
                status_txt, s_fg = 'Alta', self.VERDE
            elif rot >= 1:
                status_txt, s_fg = 'Media', self.AMARILLO
            else:
                status_txt, s_fg = 'Baja', self.ROJO

            stock_fg = self.ROJO if stock < 5 else self.TEXTO

            values = [
                (prod_txt, Qt.AlignLeft | Qt.AlignVCenter, self.TEXTO, False),
                (cat, Qt.AlignLeft | Qt.AlignVCenter, self.TEXTO_SEC, False),
                (str(stock), Qt.AlignCenter, stock_fg, True),
                (str(vend), Qt.AlignCenter, self.TEXTO, False),
                (f"{rot:.2f}", Qt.AlignCenter, s_fg, True),
                (status_txt, Qt.AlignCenter, s_fg, True),
            ]

            for col, (text, align, fg, bold) in enumerate(values):
                item = QTableWidgetItem(text)
                item.setTextAlignment(align)
                item.setForeground(QColor(fg))
                if bold:
                    item.setFont(QFont('Segoe UI', 9, QFont.Bold))
                self.table.setItem(i, col, item)

    def _exportar(self):
        from PySide6.QtWidgets import QTableWidget, QFileDialog
        import exportar as _exp
        tabla = self.findChild(QTableWidget)
        if tabla is None or tabla.rowCount() == 0:
            QMessageBox.information(self, "Exportar", "No hay datos para exportar.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar a Excel", _exp.nombre_sugerido("reporte"), "Excel (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            _exp.exportar_tabla_qt(tabla, path)
            QMessageBox.information(self, "Exportación exitosa", f"Exportado a:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Error al exportar", str(exc))

    def _imprimir(self):
        QMessageBox.information(self, "Imprimir", "Funcionalidad de impresión en desarrollo.")


# ═══════════════════════════════════════════════════════════════════════════════
#  VENTANA FLUJO DE CAJA – DASHBOARD ANALÍTICO
# ═══════════════════════════════════════════════════════════════════════════════

class VentanaFlujoCajaDashboard(QDialog):
    """Dashboard de Flujo de Caja con KPIs, desglose, gráfica de tendencia."""

    AZUL_HEADER = '#0f1b30'
    AZUL_COBALT = '#2f6fb0'
    VERDE = '#1d9e75'
    VERDE_CLARO = '#d1fae5'
    NARANJA = '#d97706'
    NARANJA_CLARO = '#fef3c7'
    ROJO = '#ef4444'
    ROJO_CLARO = '#fee2e2'
    GRIS_BG = '#f1f5f9'
    BLANCO = '#ffffff'
    TEXTO = '#0f172a'
    TEXTO_SEC = '#64748b'
    TEXTO_LIGHT = '#94a3b8'
    SOMBRA = '#e2e8f0'
    FILA_ALT = '#f8fafc'

    def __init__(self, parent, reportes_service):
        super().__init__(parent)
        self.reportes_service = reportes_service
        self.datos = None

        self.setWindowTitle("💵 Flujo de Caja")
        self.resize(1020, 640)
        self.setStyleSheet(f"background: {self.GRIS_BG};")
        self.setFixedSize(1020, 640)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        self.main_layout = main_layout

        self._crear_header()
        self._crear_filtros()

        self.main_area = QWidget()
        self.main_area_layout = QVBoxLayout(self.main_area)
        self.main_area_layout.setContentsMargins(24, 0, 24, 16)
        main_layout.addWidget(self.main_area, 1)

        self._generar()
        self.exec()

    def _crear_header(self):
        h = QFrame()
        h.setFixedHeight(50)
        h.setStyleSheet(f"background: {self.AZUL_HEADER};")
        h_layout = QHBoxLayout(h)
        h_layout.setContentsMargins(20, 0, 20, 0)

        title = QLabel("💵  Flujo de Caja")
        title.setFont(QFont('Segoe UI', 14, QFont.Bold))
        title.setStyleSheet("color: white; background: transparent;")
        h_layout.addWidget(title)
        h_layout.addStretch()

        for txt, cmd in [("🖨️ Imprimir", self._imprimir), ("📤 Exportar", self._exportar)]:
            h_layout.addWidget(_make_header_btn(txt, callback=cmd))

        self.main_layout.addWidget(h)

    def _crear_filtros(self):
        bar = QFrame()
        bar.setStyleSheet(f"background: {self.GRIS_BG}; border: none;")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(24, 10, 24, 4)

        hoy = datetime.now()
        hace30 = hoy - timedelta(days=30)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setFont(QFont('Segoe UI', 10, QFont.Bold))
        bar_layout.addWidget(lbl_desde)
        self.fecha_desde = _create_date_edit(hace30)
        bar_layout.addWidget(self.fecha_desde)

        bar_layout.addSpacing(12)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setFont(QFont('Segoe UI', 10, QFont.Bold))
        bar_layout.addWidget(lbl_hasta)
        self.fecha_hasta = _create_date_edit(hoy)
        bar_layout.addWidget(self.fecha_hasta)

        bar_layout.addSpacing(12)

        btn = QPushButton("🔍 Generar Reporte")
        btn.setFont(QFont('Segoe UI', 10, QFont.Bold))
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{ background: {self.AZUL_COBALT}; color: white; border: none; "
            f"border-radius: 6px; padding: 6px 16px; }}"
            f"QPushButton:hover {{ background: #1d4ed8; }}"
        )
        btn.clicked.connect(self._generar)
        bar_layout.addWidget(btn)
        bar_layout.addStretch()

        self.main_layout.addWidget(bar)

    def _generar(self):
        while self.main_area_layout.count():
            item = self.main_area_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

        desde = self.fecha_desde.date().toString('yyyy-MM-dd')
        hasta = self.fecha_hasta.date().toString('yyyy-MM-dd')

        try:
            self.datos = self.reportes_service.flujo_caja(desde, hasta)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al generar reporte: {e}")
            return

        d = self.datos
        ing = d['ingresos']
        egr = d['egresos']
        neto = d['flujo_neto']

        # KPIs
        self._dibujar_kpis(ing['total'], egr['total'], neto)

        # Body: two columns
        body = QHBoxLayout()
        body.setSpacing(12)

        # Left: Desglose
        self._crear_desglose(body, ing, egr, neto)

        # Right: Chart + daily sales
        self._crear_grafica_y_tabla(body, d.get('ventas_diarias', []))

        body_widget = QWidget()
        body_widget.setLayout(body)
        self.main_area_layout.addWidget(body_widget, 1)

    def _dibujar_kpis(self, ingresos, egresos, neto):
        kpi_widget = QWidget()
        kpi_grid = QGridLayout(kpi_widget)
        kpi_grid.setContentsMargins(0, 4, 0, 0)
        kpi_grid.setSpacing(10)

        neto_color = self.VERDE if neto >= 0 else self.ROJO
        kpis = [
            ("📈", "Total Ingresos", f"${ingresos:,.0f}", self.VERDE),
            ("📉", "Total Egresos", f"${egresos:,.0f}", self.ROJO),
            ("💰", "Flujo Neto", f"${neto:,.0f}", neto_color),
        ]

        for i, (icono, label, valor, color) in enumerate(kpis):
            kpi_grid.setColumnStretch(i, 1)
            _make_kpi_card(kpi_grid, icono, label, valor, color, col=i)

        self.main_area_layout.addWidget(kpi_widget)

    def _crear_desglose(self, parent_layout, ing, egr, neto):
        panel = QFrame()
        panel.setStyleSheet(
            f"QFrame {{ background: {self.BLANCO}; border: 1px solid {self.SOMBRA}; border-radius: 4px; }}"
        )
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(16, 12, 16, 12)
        panel_layout.setSpacing(4)

        title = QLabel("Desglose de Movimientos")
        title.setFont(QFont('Segoe UI', 11, QFont.Bold))
        title.setStyleSheet("border: none;")
        panel_layout.addWidget(title)

        # Ingresos
        lbl_ing = QLabel("📈 Ingresos")
        lbl_ing.setFont(QFont('Segoe UI', 10, QFont.Bold))
        lbl_ing.setStyleSheet(f"color: {self.VERDE}; border: none;")
        panel_layout.addWidget(lbl_ing)

        self._fila_desglose(panel_layout, "Ventas", ing['ventas'], self.TEXTO)
        self._fila_desglose(panel_layout, "Abonos Cobrados", ing['abonos_cobrados'], self.TEXTO)

        sep1 = QFrame()
        sep1.setFixedHeight(1)
        sep1.setStyleSheet(f"background: {self.SOMBRA}; border: none;")
        panel_layout.addWidget(sep1)
        self._fila_desglose(panel_layout, "Total Ingresos", ing['total'], self.VERDE, bold=True)

        # Separator
        sep2 = QFrame()
        sep2.setFixedHeight(2)
        sep2.setStyleSheet(f"background: {self.GRIS_BG}; border: none;")
        panel_layout.addWidget(sep2)

        # Egresos
        lbl_egr = QLabel("📉 Egresos")
        lbl_egr.setFont(QFont('Segoe UI', 10, QFont.Bold))
        lbl_egr.setStyleSheet(f"color: {self.ROJO}; border: none;")
        panel_layout.addWidget(lbl_egr)

        self._fila_desglose(panel_layout, "Compras", egr['compras'], self.TEXTO)
        for cat in egr.get('gastos_por_categoria', []):
            nombre = cat.get('categoria', 'Otros')
            monto = cat.get('total', 0)
            self._fila_desglose(panel_layout, f"  {nombre}", monto, self.TEXTO)
        if not egr.get('gastos_por_categoria'):
            self._fila_desglose(panel_layout, "Gastos Operativos", egr['gastos'], self.TEXTO)

        sep3 = QFrame()
        sep3.setFixedHeight(1)
        sep3.setStyleSheet(f"background: {self.SOMBRA}; border: none;")
        panel_layout.addWidget(sep3)
        self._fila_desglose(panel_layout, "Total Egresos", egr['total'], self.ROJO, bold=True)

        # Flujo Neto
        sep4 = QFrame()
        sep4.setFixedHeight(2)
        sep4.setStyleSheet(f"background: {self.AZUL_COBALT}; border: none;")
        panel_layout.addWidget(sep4)

        neto_color = self.VERDE if neto >= 0 else self.ROJO
        neto_row = QHBoxLayout()
        lbl_neto = QLabel("💰 Flujo Neto")
        lbl_neto.setFont(QFont('Segoe UI', 12, QFont.Bold))
        lbl_neto.setStyleSheet("border: none;")
        neto_row.addWidget(lbl_neto)
        neto_row.addStretch()
        lbl_neto_val = QLabel(f"${neto:,.0f}")
        lbl_neto_val.setFont(QFont('Segoe UI', 14, QFont.Bold))
        lbl_neto_val.setStyleSheet(f"color: {neto_color}; border: none;")
        neto_row.addWidget(lbl_neto_val)
        panel_layout.addLayout(neto_row)

        panel_layout.addStretch()
        parent_layout.addWidget(panel)

    def _fila_desglose(self, parent_layout, concepto, monto, fg, bold=False):
        row = QHBoxLayout()
        peso = QFont.Bold if bold else QFont.Normal
        lbl_c = QLabel(concepto)
        lbl_c.setFont(QFont('Segoe UI', 9, peso))
        lbl_c.setStyleSheet(f"color: {self.TEXTO_SEC if not bold else fg}; border: none;")
        row.addWidget(lbl_c)
        row.addStretch()
        lbl_m = QLabel(f"${monto:,.0f}")
        lbl_m.setFont(QFont('Segoe UI', 9, peso))
        lbl_m.setStyleSheet(f"color: {fg}; border: none;")
        row.addWidget(lbl_m)
        parent_layout.addLayout(row)

    def _crear_grafica_y_tabla(self, parent_layout, ventas_diarias):
        panel = QFrame()
        panel.setStyleSheet(
            f"QFrame {{ background: {self.BLANCO}; border: 1px solid {self.SOMBRA}; border-radius: 4px; }}"
        )
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(16, 12, 16, 12)

        title = QLabel("Ventas Diarias")
        title.setFont(QFont('Segoe UI', 11, QFont.Bold))
        title.setStyleSheet("border: none;")
        panel_layout.addWidget(title)

        # Chart
        if ventas_diarias:
            chart = DailyBarChartWidget()
            chart.set_data(ventas_diarias)
            panel_layout.addWidget(chart)

        # Separator
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {self.SOMBRA}; border: none;")
        panel_layout.addWidget(sep)

        # Table
        table = QTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(['Fecha', 'Monto'])
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(26)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setStretchLastSection(True)
        table.setColumnWidth(0, 120)
        table.setStyleSheet(
            "QTableWidget { background: white; alternate-background-color: #f8fafc; border: none; gridline-color: #eef2f7; }"
            "QHeaderView::section { background: #e2e8f0; color: #0f172a; font-weight: 500; "
            "padding: 4px; border: none; font-size: 9pt; }"
        )

        if not ventas_diarias:
            table.setRowCount(1)
            item = QTableWidgetItem("Sin ventas en el periodo")
            item.setTextAlignment(Qt.AlignCenter)
            table.setItem(0, 0, item)
            table.setSpan(0, 0, 1, 2)
        else:
            table.setRowCount(len(ventas_diarias))
            for i, vd in enumerate(ventas_diarias):
                item_fecha = QTableWidgetItem(vd.get('dia', ''))
                table.setItem(i, 0, item_fecha)

                item_monto = QTableWidgetItem(f"${vd.get('monto', 0):,.0f}")
                item_monto.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                item_monto.setForeground(QColor(self.AZUL_COBALT))
                item_monto.setFont(QFont('Segoe UI', 9, QFont.Bold))
                table.setItem(i, 1, item_monto)

        panel_layout.addWidget(table, 1)
        parent_layout.addWidget(panel)

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _exportar(self):
        from PySide6.QtWidgets import QTableWidget, QFileDialog
        import exportar as _exp
        tabla = self.findChild(QTableWidget)
        if tabla is None or tabla.rowCount() == 0:
            QMessageBox.information(self, "Exportar", "No hay datos para exportar.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar a Excel", _exp.nombre_sugerido("reporte"), "Excel (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            _exp.exportar_tabla_qt(tabla, path)
            QMessageBox.information(self, "Exportación exitosa", f"Exportado a:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Error al exportar", str(exc))

    def _imprimir(self):
        QMessageBox.information(self, "Imprimir", "Funcionalidad de impresión en desarrollo.")


# ═══════════════════════════════════════════════════════════════════════════════
#  VENTANA REPORTE CON FECHAS
# ═══════════════════════════════════════════════════════════════════════════════

class VentanaReporteConFechas(QDialog):
    """Ventana de reporte que solicita rango de fechas antes de generar"""

    def __init__(self, parent, titulo, funcion_reporte, columnas_tabla=None):
        super().__init__(parent)
        self.funcion_reporte = funcion_reporte
        self.columnas_tabla = columnas_tabla

        self.setWindowTitle(titulo)
        self.resize(950, 650)

        self.crear_interfaz(titulo)
        self.cargar_reporte()
        self.exec()

    def crear_interfaz(self, titulo):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(60)
        header.setStyleSheet(f"background: {COLORS['primary']};")
        hdr_layout = QHBoxLayout(header)
        hdr_layout.setContentsMargins(20, 0, 20, 0)

        title_lbl = QLabel(titulo)
        title_lbl.setFont(make_font(FONTS['large']))
        title_lbl.setStyleSheet("color: white; background: transparent;")
        hdr_layout.addWidget(title_lbl)
        hdr_layout.addStretch()

        hdr_layout.addWidget(_make_header_btn(f"{ICONS['exportar']} Exportar", callback=self.exportar))
        hdr_layout.addWidget(_make_header_btn(f"{ICONS['imprimir']} Imprimir", callback=self.imprimir))

        layout.addWidget(header)

        # Date filters
        fecha_frame = QFrame()
        fecha_frame.setStyleSheet(f"background: {COLORS['bg_secondary']}; border: none;")
        fecha_layout = QHBoxLayout(fecha_frame)
        fecha_layout.setContentsMargins(20, 10, 20, 10)

        hoy = datetime.now()
        inicio_default = hoy - timedelta(days=30)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setFont(make_font(FONTS['body_bold']))
        fecha_layout.addWidget(lbl_desde)
        self.fecha_inicio = _create_date_edit(inicio_default)
        fecha_layout.addWidget(self.fecha_inicio)

        fecha_layout.addSpacing(15)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setFont(make_font(FONTS['body_bold']))
        fecha_layout.addWidget(lbl_hasta)
        self.fecha_fin = _create_date_edit(hoy)
        fecha_layout.addWidget(self.fecha_fin)

        btn_gen = QPushButton("🔍 Generar Reporte")
        btn_gen.setFont(make_font(FONTS['body_bold']))
        btn_gen.setCursor(Qt.PointingHandCursor)
        btn_gen.setStyleSheet(
            f"QPushButton {{ background: {COLORS['success']}; color: white; border: none; "
            f"border-radius: 6px; padding: 6px 20px; }}"
            f"QPushButton:hover {{ background: {COLORS['success_dark']}; }}"
        )
        btn_gen.clicked.connect(self.cargar_reporte)
        fecha_layout.addWidget(btn_gen)
        fecha_layout.addStretch()

        layout.addWidget(fecha_frame)

        # Content
        content = QFrame()
        content.setStyleSheet("background: white; border: none;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 10, 20, 10)

        self.text = QTextEdit()
        self.text.setFont(QFont('Courier New', 10))
        self.text.setReadOnly(True)
        self.text.setStyleSheet("background: white; border: none;")
        content_layout.addWidget(self.text)

        layout.addWidget(content, 1)

    def cargar_reporte(self):
        try:
            inicio = self.fecha_inicio.date().toString('yyyy-MM-dd')
            fin = self.fecha_fin.date().toString('yyyy-MM-dd')

            datos = self.funcion_reporte(inicio, fin)

            self.text.clear()

            if isinstance(datos, dict):
                texto = self.formatear_dict(datos)
            elif isinstance(datos, list):
                texto = self.formatear_lista(datos)
            else:
                texto = str(datos)

            self.text.setPlainText(texto)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al generar reporte: {str(e)}")

    def formatear_dict(self, datos, nivel=0):
        texto = ""
        indent = "  " * nivel
        for key, value in datos.items():
            label = str(key).replace('_', ' ').title()
            if isinstance(value, dict):
                texto += f"{indent}{'─' * 40}\n" if nivel == 0 else ""
                texto += f"{indent}{label}:\n"
                texto += self.formatear_dict(value, nivel + 1)
            elif isinstance(value, list):
                texto += f"{indent}{'─' * 40}\n" if nivel == 0 else ""
                texto += f"{indent}{label}: ({len(value)} registros)\n"
                texto += self.formatear_lista(value, nivel + 1)
            else:
                if isinstance(value, float):
                    value = f"{value:,.2f}"
                texto += f"{indent}{label}: {value}\n"
        return texto

    def formatear_lista(self, datos, nivel=0):
        texto = ""
        indent = "  " * nivel
        for i, item in enumerate(datos, 1):
            if isinstance(item, dict):
                texto += f"{indent}{'─' * 30}\n"
                texto += f"{indent}#{i}\n"
                for key, value in item.items():
                    label = str(key).replace('_', ' ').title()
                    if isinstance(value, float):
                        value = f"{value:,.2f}"
                    texto += f"{indent}  {label}: {value}\n"
            else:
                texto += f"{indent}{i}. {item}\n"
        return texto

    def imprimir(self):
        QMessageBox.information(self, "Imprimir", "Funcionalidad de impresión en desarrollo")

    def exportar(self):
        QMessageBox.information(self, "Exportar", "Funcionalidad de exportación en desarrollo")


# ═══════════════════════════════════════════════════════════════════════════════
#  VENTANA COMPARATIVA
# ═══════════════════════════════════════════════════════════════════════════════

class VentanaComparativa(QDialog):
    """Ventana especializada para comparar dos períodos"""

    def __init__(self, parent, reportes_service):
        super().__init__(parent)
        self.reportes_service = reportes_service

        self.setWindowTitle("📊 Comparativa de Períodos")
        self.resize(1000, 650)

        self.crear_interfaz()
        self.exec()

    def crear_interfaz(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(60)
        header.setStyleSheet(f"background: {COLORS['warning']};")
        hdr_layout = QHBoxLayout(header)
        hdr_layout.setContentsMargins(20, 0, 20, 0)

        title = QLabel("📊 Comparativa de Períodos")
        title.setFont(make_font(FONTS['large']))
        title.setStyleSheet("color: white; background: transparent;")
        hdr_layout.addWidget(title)
        hdr_layout.addStretch()
        layout.addWidget(header)

        # Selection panel
        sel_frame = QFrame()
        sel_frame.setStyleSheet(f"background: {COLORS['bg_secondary']}; border: none;")
        sel_grid = QGridLayout(sel_frame)
        sel_grid.setContentsMargins(20, 10, 20, 10)
        sel_grid.setSpacing(8)

        hoy = datetime.now()
        hace_30 = hoy - timedelta(days=30)
        hace_60 = hoy - timedelta(days=60)
        hace_31 = hoy - timedelta(days=31)

        # Period 1
        lbl_p1 = QLabel("Período 1 →")
        lbl_p1.setFont(make_font(FONTS['body_bold']))
        lbl_p1.setStyleSheet(f"color: {COLORS['primary']};")
        sel_grid.addWidget(lbl_p1, 0, 0)

        sel_grid.addWidget(QLabel("Desde:"), 0, 1)
        self.p1_inicio = _create_date_edit(hace_30)
        sel_grid.addWidget(self.p1_inicio, 0, 2)

        sel_grid.addWidget(QLabel("Hasta:"), 0, 3)
        self.p1_fin = _create_date_edit(hoy)
        sel_grid.addWidget(self.p1_fin, 0, 4)

        # Period 2
        lbl_p2 = QLabel("Período 2 →")
        lbl_p2.setFont(make_font(FONTS['body_bold']))
        lbl_p2.setStyleSheet(f"color: {COLORS['danger']};")
        sel_grid.addWidget(lbl_p2, 1, 0)

        sel_grid.addWidget(QLabel("Desde:"), 1, 1)
        self.p2_inicio = _create_date_edit(hace_60)
        sel_grid.addWidget(self.p2_inicio, 1, 2)

        sel_grid.addWidget(QLabel("Hasta:"), 1, 3)
        self.p2_fin = _create_date_edit(hace_31)
        sel_grid.addWidget(self.p2_fin, 1, 4)

        btn_comparar = QPushButton("🔍 Comparar")
        btn_comparar.setFont(make_font(FONTS['body_bold']))
        btn_comparar.setCursor(Qt.PointingHandCursor)
        btn_comparar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['warning']}; color: white; border: none; "
            f"border-radius: 6px; padding: 10px 20px; }}"
            f"QPushButton:hover {{ background: {COLORS['warning_dark']}; }}"
        )
        btn_comparar.clicked.connect(self.comparar)
        sel_grid.addWidget(btn_comparar, 0, 5, 2, 1)

        layout.addWidget(sel_frame)

        # Results area
        self.result_frame = QFrame()
        self.result_frame.setStyleSheet("background: white; border: none;")
        self.result_layout = QVBoxLayout(self.result_frame)
        self.result_layout.setContentsMargins(20, 10, 20, 10)
        layout.addWidget(self.result_frame, 1)

        self.comparar()

    def comparar(self):
        try:
            datos = self.reportes_service.comparativa_periodos(
                self.p1_inicio.date().toString('yyyy-MM-dd'),
                self.p1_fin.date().toString('yyyy-MM-dd'),
                self.p2_inicio.date().toString('yyyy-MM-dd'),
                self.p2_fin.date().toString('yyyy-MM-dd')
            )

            # Clear previous
            while self.result_layout.count():
                item = self.result_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
                elif item.layout():
                    self._clear_layout(item.layout())

            p1 = datos['periodo_1']
            p2 = datos['periodo_2']
            var = datos['variacion_porcentual']

            title = QLabel("Resultados de la Comparativa")
            title.setFont(make_font(FONTS['heading']))
            title.setAlignment(Qt.AlignCenter)
            self.result_layout.addWidget(title)

            # Comparison cards
            cards_grid = QGridLayout()
            cards_grid.setSpacing(16)

            metricas = [
                ('Total Ventas', 'total_ventas', '', COLORS['primary']),
                ('Monto Total', 'monto_total', '$', COLORS['success']),
                ('Promedio Venta', 'promedio_venta', '$', COLORS['info']),
                ('Utilidad', 'utilidad', '$', COLORS['warning']),
            ]

            for i, (label, key, prefix, color) in enumerate(metricas):
                cards_grid.setColumnStretch(i, 1)

                card = QFrame()
                card.setStyleSheet(
                    f"QFrame {{ background: {COLORS['bg_secondary']}; border: 1px solid #d1d5db; border-radius: 6px; }}"
                )
                card_l = QVBoxLayout(card)
                card_l.setContentsMargins(15, 10, 15, 10)
                card_l.setAlignment(Qt.AlignCenter)

                lbl_label = QLabel(label)
                lbl_label.setFont(make_font(FONTS['body_bold']))
                lbl_label.setAlignment(Qt.AlignCenter)
                lbl_label.setStyleSheet(f"color: {COLORS['text_secondary']}; border: none;")
                card_l.addWidget(lbl_label)

                val1 = p1.get(key, 0)
                val2 = p2.get(key, 0)
                fmt1 = f"{prefix}{val1:,.2f}" if isinstance(val1, float) else f"{prefix}{val1}"
                fmt2 = f"{prefix}{val2:,.2f}" if isinstance(val2, float) else f"{prefix}{val2}"

                lbl_p1 = QLabel(f"P1: {fmt1}")
                lbl_p1.setFont(make_font(FONTS['body']))
                lbl_p1.setAlignment(Qt.AlignCenter)
                lbl_p1.setStyleSheet(f"color: {color}; border: none;")
                card_l.addWidget(lbl_p1)

                lbl_p2 = QLabel(f"P2: {fmt2}")
                lbl_p2.setFont(make_font(FONTS['body']))
                lbl_p2.setAlignment(Qt.AlignCenter)
                lbl_p2.setStyleSheet(f"color: {COLORS['danger']}; border: none;")
                card_l.addWidget(lbl_p2)

                v = var.get(key, 0)
                v_color = COLORS['success'] if v >= 0 else COLORS['danger']
                v_sign = "▲" if v >= 0 else "▼"
                lbl_var = QLabel(f"{v_sign} {v:+.1f}%")
                lbl_var.setFont(make_font(FONTS['body_bold']))
                lbl_var.setAlignment(Qt.AlignCenter)
                lbl_var.setStyleSheet(f"color: {v_color}; border: none;")
                card_l.addWidget(lbl_var)

                cards_grid.addWidget(card, 0, i)

            cards_widget = QWidget()
            cards_widget.setLayout(cards_grid)
            self.result_layout.addWidget(cards_widget)

            # Range info
            info_lbl = QLabel(f"Período 1: {p1.get('rango', '')}  |  Período 2: {p2.get('rango', '')}")
            info_lbl.setFont(make_font(FONTS['body']))
            info_lbl.setAlignment(Qt.AlignCenter)
            info_lbl.setStyleSheet(f"color: {COLORS['text_secondary']};")
            self.result_layout.addWidget(info_lbl)

            self.result_layout.addStretch()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al comparar períodos: {str(e)}")

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())


# ═══════════════════════════════════════════════════════════════════════════════
#  VENTANA VENTAS POR PERÍODO
# ═══════════════════════════════════════════════════════════════════════════════

class VentanaVentasPeriodo(QDialog):
    """Ventana profesional de Reporte de Ventas por Período con KPIs y DataGrid"""

    AZUL = '#0f1b30'
    AZUL_CLARO = '#2f6fb0'
    AZUL_HEADER = '#0f1b30'
    VERDE = '#1d9e75'
    VERDE_CLARO = '#10b981'
    GRIS_BG = '#f1f5f9'
    GRIS_FILA = '#f8fafc'
    BLANCO = '#ffffff'
    TEXTO = '#0f172a'
    TEXTO_SEC = '#64748b'

    def __init__(self, parent, reportes_service):
        super().__init__(parent)
        self.reportes_service = reportes_service
        self.datos = None
        self.ventas_list = []

        self.setWindowTitle("📊 Reporte de Ventas por Período")
        self.resize(1100, 720)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(f"background: {self.GRIS_BG};")

        self._crear_interfaz()
        self._cargar_datos()
        self.exec()

    def _crear_interfaz(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # HEADER
        top_bar = QFrame()
        top_bar.setStyleSheet(f"background: {self.AZUL};")
        top_layout = QVBoxLayout(top_bar)
        top_layout.setContentsMargins(25, 12, 25, 12)

        # Title row
        title_row = QHBoxLayout()
        title_lbl = QLabel("📊 Reporte de Ventas por Período")
        title_lbl.setFont(QFont('Segoe UI', 17, QFont.Bold))
        title_lbl.setStyleSheet("color: white; background: transparent;")
        title_row.addWidget(title_lbl)
        title_row.addStretch()

        for txt, cmd in [("📤 Exportar", self._exportar), ("🖨️ Imprimir", self._imprimir)]:
            title_row.addWidget(_make_header_btn(txt, callback=cmd))

        top_layout.addLayout(title_row)

        # Filter row
        filtro_row = QHBoxLayout()
        filtro_row.setSpacing(8)

        hoy = datetime.now()
        inicio_def = hoy - timedelta(days=30)

        lbl_desde = QLabel("Desde:")
        lbl_desde.setFont(QFont('Segoe UI', 10, QFont.Bold))
        lbl_desde.setStyleSheet("color: #93c5fd; background: transparent;")
        filtro_row.addWidget(lbl_desde)
        self.fecha_inicio = _create_date_edit(inicio_def)
        filtro_row.addWidget(self.fecha_inicio)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setFont(QFont('Segoe UI', 10, QFont.Bold))
        lbl_hasta.setStyleSheet("color: #93c5fd; background: transparent;")
        filtro_row.addWidget(lbl_hasta)
        self.fecha_fin = _create_date_edit(hoy)
        filtro_row.addWidget(self.fecha_fin)

        self._generando = False
        self.btn_generar = QPushButton("🔍  Generar Reporte")
        self.btn_generar.setFont(QFont('Segoe UI', 11, QFont.Bold))
        self.btn_generar.setCursor(Qt.PointingHandCursor)
        self.btn_generar.setStyleSheet(
            f"QPushButton {{ background: {self.VERDE}; color: white; border: none; "
            f"border-radius: 6px; padding: 6px 22px; }}"
            f"QPushButton:hover {{ background: {self.VERDE_CLARO}; }}"
        )
        self.btn_generar.clicked.connect(self._on_generar_click)
        filtro_row.addWidget(self.btn_generar)
        filtro_row.addStretch()

        top_layout.addLayout(filtro_row)
        layout.addWidget(top_bar)

        # KPI FRAME
        self.kpi_frame = QFrame()
        self.kpi_frame.setStyleSheet("background: transparent;")
        self.kpi_layout = QHBoxLayout(self.kpi_frame)
        self.kpi_layout.setContentsMargins(20, 15, 20, 5)
        layout.addWidget(self.kpi_frame)

        # TABLE
        tabla_container = QFrame()
        tabla_container.setStyleSheet("background: white; border: 1px solid #d1d5db; border-radius: 4px;")
        tabla_layout = QVBoxLayout(tabla_container)
        tabla_layout.setContentsMargins(10, 8, 10, 10)

        self.lbl_conteo = QLabel("")
        self.lbl_conteo.setFont(QFont('Segoe UI', 9))
        self.lbl_conteo.setStyleSheet(f"color: {self.TEXTO_SEC}; border: none;")
        tabla_layout.addWidget(self.lbl_conteo)

        self.table = QTableWidget()
        columns = [
            ('ID', 60, 'center'),
            ('N° Factura', 140, 'center'),
            ('Fecha', 130, 'center'),
            ('Cliente', 180, 'left'),
            ('Total', 110, 'right'),
            ('Método de Pago', 120, 'center'),
            ('Estado', 100, 'center'),
        ]
        _setup_table(self.table, columns)
        self.table.doubleClicked.connect(self._ver_detalle)
        tabla_layout.addWidget(self.table)
        layout.addWidget(tabla_container, 1)

        # BOTTOM BAR
        bottom_bar = QHBoxLayout()
        bottom_bar.setContentsMargins(20, 0, 20, 10)

        btn_detalle = QPushButton("👁️  Ver Detalle")
        btn_detalle.setFont(QFont('Segoe UI', 10, QFont.Bold))
        btn_detalle.setCursor(Qt.PointingHandCursor)
        btn_detalle.setStyleSheet(
            f"QPushButton {{ background: {self.AZUL_CLARO}; color: white; border: none; "
            f"border-radius: 6px; padding: 6px 16px; }}"
            f"QPushButton:hover {{ background: #1d4ed8; }}"
        )
        btn_detalle.clicked.connect(self._ver_detalle)
        bottom_bar.addWidget(btn_detalle)

        btn_imprimir_factura = QPushButton("🖨️  Imprimir Factura")
        btn_imprimir_factura.setFont(QFont('Segoe UI', 10, QFont.Bold))
        btn_imprimir_factura.setCursor(Qt.PointingHandCursor)
        btn_imprimir_factura.setStyleSheet(
            f"QPushButton {{ background: {self.TEXTO_SEC}; color: white; border: none; "
            f"border-radius: 6px; padding: 6px 16px; }}"
            f"QPushButton:hover {{ background: #374151; }}"
        )
        btn_imprimir_factura.clicked.connect(self._imprimir_factura)
        bottom_bar.addWidget(btn_imprimir_factura)

        bottom_bar.addStretch()

        self.lbl_seleccion = QLabel("Seleccione una venta de la tabla")
        self.lbl_seleccion.setFont(QFont('Segoe UI', 9))
        self.lbl_seleccion.setStyleSheet(f"color: {self.TEXTO_SEC}; font-style: italic;")
        bottom_bar.addWidget(self.lbl_seleccion)

        layout.addLayout(bottom_bar)

    def _dibujar_kpis(self, resumen):
        while self.kpi_layout.count():
            item = self.kpi_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        kpis = [
            ("💰", "Total Vendido", f"$ {resumen.get('monto_total', 0):,.2f}", self.AZUL_CLARO),
            ("🧾", "Total Impuestos", f"$ {resumen.get('iva_total', 0):,.2f}", "#8b5cf6"),
            ("📋", "N° de Facturas", f"{resumen.get('total_ventas', 0)}", self.VERDE),
            ("📊", "Venta Promedio", f"$ {resumen.get('promedio_venta', 0):,.2f}", "#f59e0b"),
        ]

        for icon, titulo, valor, color in kpis:
            card = QFrame()
            card.setStyleSheet("QFrame { background: white; border: 1px solid #d1d5db; border-radius: 6px; }")
            card_l = QVBoxLayout(card)
            card_l.setContentsMargins(18, 12, 18, 12)

            bar = QFrame()
            bar.setFixedHeight(4)
            bar.setStyleSheet(f"background: {color}; border: none;")
            card_l.addWidget(bar)

            header_kpi = QHBoxLayout()
            lbl_icon = QLabel(icon)
            lbl_icon.setFont(QFont('Segoe UI', 14))
            lbl_icon.setStyleSheet("border: none;")
            header_kpi.addWidget(lbl_icon)
            lbl_title = QLabel(titulo)
            lbl_title.setFont(QFont('Segoe UI', 9))
            lbl_title.setStyleSheet(f"color: {self.TEXTO_SEC}; border: none;")
            header_kpi.addWidget(lbl_title)
            header_kpi.addStretch()
            card_l.addLayout(header_kpi)

            lbl_val = QLabel(valor)
            lbl_val.setFont(QFont('Segoe UI', 18, QFont.Bold))
            lbl_val.setStyleSheet(f"color: {color}; border: none;")
            card_l.addWidget(lbl_val)

            self.kpi_layout.addWidget(card)

    def _on_generar_click(self):
        if self._generando:
            return
        self._generando = True
        self.btn_generar.setText("⏳ Cargando...")
        self.btn_generar.setEnabled(False)
        QTimer.singleShot(50, self._ejecutar_reporte)

    def _ejecutar_reporte(self):
        try:
            self._cargar_datos()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error inesperado:\n{str(e)}")
        finally:
            self._generando = False
            self.btn_generar.setText("🔍  Generar Reporte")
            self.btn_generar.setEnabled(True)

    def _cargar_datos(self):
        inicio = self.fecha_inicio.date().toString('yyyy-MM-dd')
        fin = self.fecha_fin.date().toString('yyyy-MM-dd')

        try:
            datetime.strptime(inicio, '%Y-%m-%d')
            datetime.strptime(fin, '%Y-%m-%d')
        except ValueError:
            QMessageBox.warning(self, "Fecha inválida",
                                f"Formato de fecha incorrecto.\nUse el formato: YYYY-MM-DD\n"
                                f"Ejemplo: {datetime.now().strftime('%Y-%m-%d')}")
            return

        if inicio > fin:
            QMessageBox.warning(self, "Rango inválido",
                                "La fecha 'Desde' no puede ser mayor que 'Hasta'.")
            return

        try:
            self.datos = self.reportes_service.reporte_ventas_periodo(inicio, fin)
            self.ventas_list = self.datos.get('ventas', [])
            resumen = self.datos.get('resumen', {})

            self._dibujar_kpis(resumen)

            total = len(self.ventas_list)
            self.lbl_conteo.setText(
                f"Mostrando {total} venta{'s' if total != 1 else ''}  •  "
                f"Período: {inicio}  →  {fin}")

            self.table.setRowCount(total)
            for idx, v in enumerate(self.ventas_list):
                fecha_raw = v.get('fecha', '')
                if isinstance(fecha_raw, str) and len(fecha_raw) > 16:
                    fecha_fmt = fecha_raw[:16]
                else:
                    fecha_fmt = str(fecha_raw)

                total_fmt = f"$ {v.get('total', 0):,.2f}"
                cliente = v.get('cliente_nombre') or 'Público General'
                estado = v.get('estado', '')

                estado_color = self.VERDE if estado == 'COMPLETADA' else (
                    '#f59e0b' if estado == 'PENDIENTE' else (
                        '#ef4444' if estado == 'ANULADA' else self.TEXTO))

                values = [
                    (str(v.get('id', '')), Qt.AlignCenter, self.TEXTO),
                    (str(v.get('numero_factura', '')), Qt.AlignCenter, self.TEXTO),
                    (fecha_fmt, Qt.AlignCenter, self.TEXTO),
                    (cliente, Qt.AlignLeft | Qt.AlignVCenter, self.TEXTO),
                    (total_fmt, Qt.AlignRight | Qt.AlignVCenter, self.TEXTO),
                    (str(v.get('metodo_pago', '')), Qt.AlignCenter, self.TEXTO),
                    (estado, Qt.AlignCenter, estado_color),
                ]

                for col, (text, align, fg) in enumerate(values):
                    if col == 6:
                        # Estado como pill (semáforo), igual que el mockup.
                        fila_bg = '#ffffff' if idx % 2 == 0 else '#fafbfc'
                        self.table.setItem(idx, col, QTableWidgetItem(''))
                        self.table.setCellWidget(idx, col,
                                                 self._pill_estado(estado, fila_bg))
                        continue
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(align)
                    item.setForeground(QColor(fg))
                    # Store venta id for retrieval
                    if col == 0:
                        item.setData(Qt.UserRole, v.get('id'))
                    self.table.setItem(idx, col, item)

            self.lbl_seleccion.setText("✅ Reporte generado exitosamente")
            self.lbl_seleccion.setStyleSheet(f"color: {self.VERDE};")
            QTimer.singleShot(3000, lambda: (
                self.lbl_seleccion.setText("Seleccione una venta de la tabla"),
                self.lbl_seleccion.setStyleSheet(f"color: {self.TEXTO_SEC}; font-style: italic;")
            ) if self.isVisible() else None)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al generar reporte:\n{str(e)}")

    def _pill_estado(self, estado, fila_bg='#ffffff'):
        """Devuelve un widget 'pill' (badge redondeado) para la columna Estado,
        con los colores del semáforo del sistema (igual al mockup). El fondo del
        contenedor iguala el color de la fila (zebra) para que no aparezca un
        recuadro blanco detrás del pill."""
        e = (estado or '').upper()
        if e == 'COMPLETADA':
            bg, fg = '#eaf3de', '#3b6d11'
        elif e == 'PENDIENTE':
            bg, fg = '#faeeda', '#854f0b'
        elif e in ('ANULADA', 'CANCELADA'):
            bg, fg = '#fcebeb', '#a32d2d'
        else:
            bg, fg = '#eef1f6', '#64748b'
        cont = QWidget()
        cont.setObjectName("estadoPillCont")
        cont.setStyleSheet(
            f"QWidget#estadoPillCont {{ background: {fila_bg}; border: none; }}")
        lay = QHBoxLayout(cont)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignCenter)
        lbl = QLabel(estado or '')
        lbl.setObjectName("estadoPillLbl")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(
            f"QLabel#estadoPillLbl {{ background: {bg}; color: {fg};"
            f" border: none; border-radius: 9px; padding: 2px 11px;"
            f" font-size: 8pt; font-weight: 500; }}")
        lay.addWidget(lbl)
        return cont

    def _get_venta_seleccionada(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Atención", "Seleccione una venta de la tabla primero.")
            return None
        item = self.table.item(row, 0)
        if not item:
            return None
        venta_id = item.data(Qt.UserRole)
        for v in self.ventas_list:
            if v.get('id') == venta_id:
                return v
        return None

    def _ver_detalle(self):
        venta = self._get_venta_seleccionada()
        if not venta:
            return
        VentanaDetalleVenta(self, venta, self.reportes_service)

    def _imprimir_factura(self):
        venta = self._get_venta_seleccionada()
        if not venta:
            return
        QMessageBox.information(self, "Imprimir",
                                f"Imprimiendo factura {venta.get('numero_factura', '')}...\n"
                                "Funcionalidad de impresión en desarrollo.")

    def _exportar(self):
        from PySide6.QtWidgets import QTableWidget, QFileDialog
        import exportar as _exp
        tabla = self.findChild(QTableWidget)
        if tabla is None or tabla.rowCount() == 0:
            QMessageBox.information(self, "Exportar", "No hay datos para exportar.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar a Excel", _exp.nombre_sugerido("reporte"), "Excel (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            _exp.exportar_tabla_qt(tabla, path)
            QMessageBox.information(self, "Exportación exitosa", f"Exportado a:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Error al exportar", str(exc))

    def _imprimir(self):
        QMessageBox.information(self, "Imprimir", "Funcionalidad de impresión general en desarrollo.")


# ═══════════════════════════════════════════════════════════════════════════════
#  VENTANA DETALLE VENTA
# ═══════════════════════════════════════════════════════════════════════════════

class VentanaDetalleVenta(QDialog):
    """Popup con el detalle completo de una venta incluyendo productos"""

    AZUL = '#0f1b30'
    VERDE = '#1d9e75'
    GRIS_BG = '#f1f5f9'
    GRIS_FILA = '#f8fafc'
    TEXTO = '#0f172a'
    TEXTO_SEC = '#64748b'

    def __init__(self, parent, venta, reportes_service):
        super().__init__(parent)
        self.venta = venta
        self.reportes_service = reportes_service

        self.setWindowTitle(f"Detalle — {venta.get('numero_factura', '')}")
        self.resize(750, 620)
        self.setMinimumSize(650, 500)
        self.setStyleSheet("background: white;")

        self._crear_ui()
        self.exec()

    def _crear_ui(self):
        v = self.venta
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        hdr = QFrame()
        hdr.setStyleSheet(f"background: {self.AZUL};")
        hdr_layout = QHBoxLayout(hdr)
        hdr_layout.setContentsMargins(20, 12, 20, 12)

        title = QLabel(f"📄 Factura {v.get('numero_factura', '')}")
        title.setFont(QFont('Segoe UI', 14, QFont.Bold))
        title.setStyleSheet("color: white; background: transparent;")
        hdr_layout.addWidget(title)
        hdr_layout.addStretch()

        fecha_lbl = QLabel(str(v.get('fecha', '')))
        fecha_lbl.setFont(QFont('Segoe UI', 10))
        fecha_lbl.setStyleSheet("color: #93c5fd; background: transparent;")
        hdr_layout.addWidget(fecha_lbl)

        layout.addWidget(hdr)

        # Info general
        info_frame = QFrame()
        info_frame.setStyleSheet(f"background: {self.GRIS_BG}; border: none;")
        info_layout = QHBoxLayout(info_frame)
        info_layout.setContentsMargins(20, 10, 20, 10)

        campos_izq = [
            ("Cliente", v.get('cliente_nombre') or 'Público General'),
            ("Vendedor", v.get('vendedor', '') or '-'),
            ("Método de Pago", v.get('metodo_pago', '')),
        ]
        campos_der = [
            ("Estado", v.get('estado', '')),
            ("Estado de Pago", v.get('estado_pago', '') or '-'),
            ("ID Venta", v.get('id', '')),
        ]

        for campos in [campos_izq, campos_der]:
            col_frame = QVBoxLayout()
            for label, val in campos:
                row_l = QHBoxLayout()
                lbl_label = QLabel(f"{label}:")
                lbl_label.setFont(QFont('Segoe UI', 9, QFont.Bold))
                lbl_label.setStyleSheet(f"color: {self.TEXTO_SEC};")
                lbl_label.setFixedWidth(120)
                row_l.addWidget(lbl_label)
                lbl_val = QLabel(str(val))
                lbl_val.setFont(QFont('Segoe UI', 9))
                row_l.addWidget(lbl_val)
                row_l.addStretch()
                col_frame.addLayout(row_l)
            info_layout.addLayout(col_frame)

        layout.addWidget(info_frame)

        # Products table
        prod_header = QHBoxLayout()
        prod_header.setContentsMargins(20, 12, 20, 4)
        lbl_prod = QLabel("📦 Productos vendidos")
        lbl_prod.setFont(QFont('Segoe UI', 11, QFont.Bold))
        lbl_prod.setStyleSheet(f"color: {self.AZUL};")
        prod_header.addWidget(lbl_prod)
        prod_header.addStretch()
        layout.addLayout(prod_header)

        self.table = QTableWidget()
        columns = [
            ('Producto', 250, 'left'),
            ('Cantidad', 80, 'center'),
            ('Precio Unit.', 110, 'right'),
            ('Descuento', 90, 'right'),
            ('Subtotal', 110, 'right'),
        ]
        _setup_table(self.table, columns, row_height=28)
        self.table.setStyleSheet(
            f"QTableWidget {{ background: white; alternate-background-color: {COLORS['table_row_alt']}; gridline-color: transparent; border: 1px solid {COLORS['border']}; border-radius: 12px; }}"
            "QTableWidget::item { padding: 7px 6px; }"
            f"QTableWidget::item:selected {{ background: {COLORS['table_selection']}; color: {COLORS['text_primary']}; }}"
            f"QHeaderView::section {{ background: {COLORS['table_header']}; color: {COLORS['table_header_fg']}; font-weight: 500; "
            "padding: 9px 8px; border: none; font-size: 9pt; }"
        )

        tabla_wrapper = QVBoxLayout()
        tabla_wrapper.setContentsMargins(20, 0, 20, 10)
        tabla_wrapper.addWidget(self.table)
        layout.addLayout(tabla_wrapper, 1)

        self._cargar_productos()

        # Summary
        resumen_frame = QFrame()
        resumen_frame.setStyleSheet("background: white; border: none;")
        resumen_layout = QVBoxLayout(resumen_frame)
        resumen_layout.setContentsMargins(0, 0, 20, 0)

        montos_frame = QVBoxLayout()
        montos_frame.setAlignment(Qt.AlignRight)

        montos = [
            ("Subtotal", f"$ {v.get('subtotal', 0):,.2f}", self.TEXTO),
            ("Descuento", f"- $ {v.get('descuento', 0):,.2f}", '#ef4444'),
            ("IVA", f"$ {v.get('iva', 0):,.2f}", self.TEXTO),
        ]
        for label, val, color in montos:
            row_l = QHBoxLayout()
            row_l.addStretch()
            lbl_label = QLabel(f"{label}:")
            lbl_label.setFont(QFont('Segoe UI', 10))
            lbl_label.setStyleSheet(f"color: {self.TEXTO_SEC};")
            lbl_label.setFixedWidth(100)
            lbl_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row_l.addWidget(lbl_label)
            lbl_val = QLabel(val)
            lbl_val.setFont(QFont('Segoe UI', 10))
            lbl_val.setStyleSheet(f"color: {color};")
            lbl_val.setFixedWidth(120)
            lbl_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row_l.addWidget(lbl_val)
            montos_frame.addLayout(row_l)

        # Separator
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #cbd5e1; border: none;")
        montos_frame.addWidget(sep)

        # Total
        total_row = QHBoxLayout()
        total_row.addStretch()
        lbl_total = QLabel("TOTAL:")
        lbl_total.setFont(QFont('Segoe UI', 13, QFont.Bold))
        lbl_total.setStyleSheet(f"color: {self.AZUL};")
        lbl_total.setFixedWidth(100)
        lbl_total.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        total_row.addWidget(lbl_total)
        lbl_total_val = QLabel(f"$ {v.get('total', 0):,.2f}")
        lbl_total_val.setFont(QFont('Segoe UI', 13, QFont.Bold))
        lbl_total_val.setStyleSheet(f"color: {self.VERDE};")
        lbl_total_val.setFixedWidth(120)
        lbl_total_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        total_row.addWidget(lbl_total_val)
        montos_frame.addLayout(total_row)

        resumen_layout.addLayout(montos_frame)

        resumen_wrapper = QHBoxLayout()
        resumen_wrapper.setContentsMargins(20, 0, 20, 5)
        resumen_wrapper.addWidget(resumen_frame)
        layout.addLayout(resumen_wrapper)

        # Close button
        btn_close = QPushButton("Cerrar")
        btn_close.setFont(QFont('Segoe UI', 10))
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet(
            "QPushButton { background: #e2e8f0; color: #334155; border: none; "
            "border-radius: 6px; padding: 6px 20px; }"
            "QPushButton:hover { background: #cbd5e1; }"
        )
        btn_close.clicked.connect(self.close)
        close_layout = QHBoxLayout()
        close_layout.setContentsMargins(0, 5, 0, 12)
        close_layout.addStretch()
        close_layout.addWidget(btn_close)
        close_layout.addStretch()
        layout.addLayout(close_layout)

    def _cargar_productos(self):
        try:
            venta_id = self.venta.get('id')
            if not venta_id:
                return
            conn = self.reportes_service.db.conectar()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT p.nombre, dv.cantidad, dv.precio_unitario,
                       dv.descuento, dv.subtotal
                FROM detalle_ventas dv
                JOIN productos p ON dv.producto_id = p.id
                WHERE dv.venta_id = ?
                ORDER BY dv.id
            """, (venta_id,))
            rows = cursor.fetchall()
            conn.close()

            self.table.setRowCount(len(rows))
            for idx, row in enumerate(rows):
                values = [
                    (row['nombre'], Qt.AlignLeft | Qt.AlignVCenter),
                    (formatear_stock(row['cantidad']), Qt.AlignCenter),
                    (f"$ {row['precio_unitario']:,.2f}", Qt.AlignRight | Qt.AlignVCenter),
                    (f"$ {row['descuento']:,.2f}", Qt.AlignRight | Qt.AlignVCenter),
                    (f"$ {row['subtotal']:,.2f}", Qt.AlignRight | Qt.AlignVCenter),
                ]
                for col, (text, align) in enumerate(values):
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(align)
                    self.table.setItem(idx, col, item)

        except Exception as e:
            self.table.setRowCount(1)
            item = QTableWidgetItem(f"Error al cargar productos: {e}")
            item.setForeground(QColor('#ef4444'))
            self.table.setItem(0, 0, item)
            self.table.setSpan(0, 0, 1, 5)


# ═══════════════════════════════════════════════════════════════════════════════
#  VENTANA REPORTE DEL DÍA
# ═══════════════════════════════════════════════════════════════════════════════

class VentanaReporteDia(QDialog):
    """Reporte completo de un día seleccionado: ventas, métodos de pago y egresos."""

    AZUL      = '#1e3a5f'
    VERDE     = '#059669'
    ROJO      = '#ef4444'
    NARANJA   = '#f59e0b'
    GRIS_BG   = '#f1f5f9'
    TEXTO     = '#0f172a'
    TEXTO_SEC = '#64748b'

    def __init__(self, parent, reportes_service):
        super().__init__(parent)
        self.reportes_service = reportes_service
        self.setWindowTitle("📅 Reporte del Día")
        self.resize(980, 680)
        self.setMinimumSize(860, 560)
        self.setStyleSheet(f"background: {self.GRIS_BG};")
        self._crear_interfaz()
        self._cargar()
        self.exec()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _crear_interfaz(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ─ Header ─────────────────────────────────────────────────────────────
        header = QFrame()
        header.setStyleSheet(f"background: {self.AZUL};")
        h_lay = QVBoxLayout(header)
        h_lay.setContentsMargins(25, 14, 25, 14)

        title_row = QHBoxLayout()
        lbl_title = QLabel("📅 Reporte del Día")
        lbl_title.setFont(QFont('Segoe UI', 17, QFont.Bold))
        lbl_title.setStyleSheet("color: white; background: transparent;")
        title_row.addWidget(lbl_title)
        title_row.addStretch()
        h_lay.addLayout(title_row)

        filtro_row = QHBoxLayout()
        filtro_row.setSpacing(10)

        lbl_fecha = QLabel("Fecha:")
        lbl_fecha.setFont(QFont('Segoe UI', 10, QFont.Bold))
        lbl_fecha.setStyleSheet("color: #93c5fd; background: transparent;")
        filtro_row.addWidget(lbl_fecha)

        hoy = datetime.now()
        self.fecha_edit = _create_date_edit(hoy)
        filtro_row.addWidget(self.fecha_edit)

        btn_gen = QPushButton("🔍  Generar")
        btn_gen.setFont(QFont('Segoe UI', 10, QFont.Bold))
        btn_gen.setCursor(Qt.PointingHandCursor)
        btn_gen.setStyleSheet(
            f"QPushButton {{ background: {self.VERDE}; color: white; border: none; "
            f"border-radius: 6px; padding: 5px 18px; }}"
            f"QPushButton:hover {{ background: #10b981; }}"
        )
        btn_gen.clicked.connect(self._cargar)
        filtro_row.addWidget(btn_gen)
        filtro_row.addStretch()
        h_lay.addLayout(filtro_row)
        root.addWidget(header)

        # ─ Scroll area ────────────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        container = QWidget()
        container.setStyleSheet(f"background: {self.GRIS_BG};")
        self.content = QVBoxLayout(container)
        self.content.setContentsMargins(20, 16, 20, 20)
        self.content.setSpacing(12)
        scroll.setWidget(container)
        root.addWidget(scroll, 1)

        # ─ Close button ───────────────────────────────────────────────────────
        btn_bar = QFrame()
        btn_bar.setStyleSheet("background: white;")
        btn_bar_lay = QHBoxLayout(btn_bar)
        btn_bar_lay.setAlignment(Qt.AlignCenter)
        btn_bar_lay.setContentsMargins(10, 8, 10, 8)
        btn_close = QPushButton("Cerrar")
        btn_close.setFont(QFont('Segoe UI', 10))
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet(
            "QPushButton { background: #64748b; color: white; border: none; "
            "border-radius: 6px; padding: 8px 30px; }"
            "QPushButton:hover { background: #475569; }"
        )
        btn_close.clicked.connect(self.reject)
        btn_bar_lay.addWidget(btn_close)
        root.addWidget(btn_bar)

    # ── Data helpers ──────────────────────────────────────────────────────────

    def _limpiar_contenido(self):
        while self.content.count():
            item = self.content.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _section_title(self, text):
        lbl = QLabel(text)
        lbl.setFont(QFont('Segoe UI', 12, QFont.Bold))
        lbl.setStyleSheet(f"color: {self.AZUL}; background: transparent;")
        return lbl

    def _card(self, title, value, color, subtitle=""):
        f = QFrame()
        f.setStyleSheet(
            "QFrame { background: white; border: 1px solid #e2e8f0; border-radius: 8px; }"
        )
        lay = QVBoxLayout(f)
        lay.setContentsMargins(16, 10, 16, 10)
        bar = QFrame(); bar.setFixedHeight(4)
        bar.setStyleSheet(f"background: {color}; border: none; border-radius: 2px;")
        lay.addWidget(bar)
        l_t = QLabel(title)
        l_t.setFont(QFont('Segoe UI', 9))
        l_t.setStyleSheet(f"color: {self.TEXTO_SEC}; border: none;")
        lay.addWidget(l_t)
        l_v = QLabel(str(value))
        l_v.setFont(QFont('Segoe UI', 16, QFont.Bold))
        l_v.setStyleSheet(f"color: {color}; border: none;")
        lay.addWidget(l_v)
        if subtitle:
            l_s = QLabel(subtitle)
            l_s.setFont(QFont('Segoe UI', 8))
            l_s.setStyleSheet(f"color: {self.TEXTO_SEC}; border: none;")
            lay.addWidget(l_s)
        return f

    # ── Load ──────────────────────────────────────────────────────────────────

    def _cargar(self):
        self._limpiar_contenido()
        fecha = self.fecha_edit.date().toString("yyyy-MM-dd")
        try:
            conn = self.reportes_service.db.conectar()
            cursor = conn.cursor()

            # ── Ventas por método de pago (excluyendo crédito para "dinero real") ──
            cursor.execute("""
                SELECT
                    COUNT(*)                                                           AS num_ventas,
                    COALESCE(SUM(CASE WHEN metodo_pago='EFECTIVO' THEN total ELSE 0 END), 0) AS efectivo,
                    COALESCE(SUM(CASE WHEN metodo_pago IN ('TARJETA_DEBITO','TARJETA_CREDITO')
                                      THEN total ELSE 0 END), 0)                    AS tarjeta,
                    COALESCE(SUM(CASE WHEN metodo_pago='TRANSFERENCIA' THEN total ELSE 0 END), 0) AS transferencia,
                    COALESCE(SUM(CASE WHEN metodo_pago NOT IN (
                        'EFECTIVO','TARJETA_DEBITO','TARJETA_CREDITO','TRANSFERENCIA','CREDITO')
                                      THEN total ELSE 0 END), 0)                    AS otros,
                    COALESCE(SUM(CASE WHEN metodo_pago='CREDITO' THEN total ELSE 0 END), 0) AS credito_nuevo
                FROM ventas
                WHERE DATE(datetime(fecha, 'localtime')) = ? AND estado = 'COMPLETADA'
            """, (fecha,))
            ventas = dict(cursor.fetchone())

            # Abonos cobrados ese día (pagos de créditos de cualquier fecha)
            cursor.execute("""
                SELECT COALESCE(SUM(monto_abono), 0) AS total
                FROM abonos_ventas
                WHERE DATE(fecha_abono) = ?
            """, (fecha,))
            abonos_total = cursor.fetchone()[0]

            # ── Egresos ───────────────────────────────────────────────────
            cursor.execute("""
                SELECT COALESCE(SUM(monto), 0) AS total_egresos
                FROM egresos_caja
                WHERE DATE(fecha_egreso) = ?
            """, (fecha,))
            total_egresos = cursor.fetchone()[0]

            # Egresos por categoría con descripción
            cursor.execute("""
                SELECT categoria, descripcion, metodo_pago, monto
                FROM egresos_caja
                WHERE DATE(fecha_egreso) = ?
                ORDER BY categoria, monto DESC
            """, (fecha,))
            egresos_rows = [dict(r) for r in cursor.fetchall()]

            # Egresos agrupados por categoría (totales)
            cursor.execute("""
                SELECT categoria, COALESCE(SUM(monto), 0) AS total
                FROM egresos_caja
                WHERE DATE(fecha_egreso) = ?
                GROUP BY categoria ORDER BY total DESC
            """, (fecha,))
            egresos_cat = [dict(r) for r in cursor.fetchall()]

            conn.close()
        except Exception as e:
            self._limpiar_contenido()
            lbl = QLabel(f"Error cargando datos: {e}")
            lbl.setStyleSheet("color: #ef4444;")
            self.content.addWidget(lbl)
            return

        # Dinero real = ventas contado + cobros de créditos
        dinero_real = (ventas['efectivo'] + ventas['tarjeta'] +
                       ventas['transferencia'] + ventas['otros'] + abonos_total)
        neto = dinero_real - total_egresos

        # ── Sección: KPIs principales ──────────────────────────────────────
        self.content.addWidget(self._section_title(f"📆 Resumen del {fecha}"))

        kpi_grid = QGridLayout()
        kpi_grid.setSpacing(10)
        kpi_data = [
            ("💵 Dinero Real Recibido", f"${dinero_real:,.0f}", '#059669',
             f"{ventas['num_ventas']} ventas + abonos"),
            ("🤝 Crédito Extendido", f"${ventas['credito_nuevo']:,.0f}", '#7c3aed',
             "No entró a caja"),
            ("📤 Total Egresos", f"${total_egresos:,.0f}",
             self.ROJO if total_egresos > 0 else '#94a3b8', "Gastos del día"),
            ("📊 Neto Real", f"${neto:,.0f}",
             self.VERDE if neto >= 0 else self.ROJO, "Dinero real - Egresos"),
        ]
        for col, (title, val, color, sub) in enumerate(kpi_data):
            kpi_grid.addWidget(self._card(title, val, color, sub), 0, col)

        kpi_widget = QWidget()
        kpi_widget.setStyleSheet("background: transparent;")
        kpi_widget.setLayout(kpi_grid)
        self.content.addWidget(kpi_widget)

        # ── Sección: Dinero Real Recibido ─────────────────────────────────
        self.content.addWidget(self._section_title("💵 Dinero Real Recibido Hoy"))

        real_frame = QFrame()
        real_frame.setStyleSheet(
            "background: white; border: 2px solid #059669; border-radius: 8px;")
        real_lay = QVBoxLayout(real_frame)
        real_lay.setContentsMargins(16, 12, 16, 12)
        real_lay.setSpacing(6)

        metodos_reales = [
            ("💵 Efectivo (ventas contado)",     ventas['efectivo'],       '#059669'),
            ("💳 Tarjeta (ventas contado)",       ventas['tarjeta'],        '#2563eb'),
            ("🔄 Transferencia (ventas contado)", ventas['transferencia'],  '#0891b2'),
            ("📌 Otros métodos (ventas contado)", ventas['otros'],          '#94a3b8'),
            ("📥 Cobros de créditos (abonos)",    abonos_total,             '#0f766e'),
        ]

        hay_real = False
        for nombre, monto, color in metodos_reales:
            if monto <= 0:
                continue
            hay_real = True
            row = QHBoxLayout()
            l_n = QLabel(nombre)
            l_n.setFont(QFont('Segoe UI', 10))
            l_n.setStyleSheet(f"color: {self.TEXTO}; border: none;")
            row.addWidget(l_n, 1)
            l_m = QLabel(f"${monto:,.0f}")
            l_m.setFont(QFont('Segoe UI', 10, QFont.Bold))
            l_m.setStyleSheet(f"color: {color}; border: none;")
            l_m.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(l_m)
            real_lay.addLayout(row)

        if not hay_real:
            l_nd = QLabel("Sin ingresos registrados en esta fecha")
            l_nd.setStyleSheet(f"color: {self.TEXTO_SEC}; border: none;")
            real_lay.addWidget(l_nd)
        else:
            # Separador + total
            sep = QFrame(); sep.setFixedHeight(1)
            sep.setStyleSheet("background: #d1fae5; border: none;")
            real_lay.addWidget(sep)
            total_row = QHBoxLayout()
            l_total_n = QLabel("TOTAL REAL")
            l_total_n.setFont(QFont('Segoe UI', 11, QFont.Bold))
            l_total_n.setStyleSheet(f"color: {self.AZUL}; border: none;")
            total_row.addWidget(l_total_n, 1)
            l_total_v = QLabel(f"${dinero_real:,.0f}")
            l_total_v.setFont(QFont('Segoe UI', 13, QFont.Bold))
            l_total_v.setStyleSheet(f"color: #059669; border: none;")
            l_total_v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            total_row.addWidget(l_total_v)
            real_lay.addLayout(total_row)

        self.content.addWidget(real_frame)

        # ── Sección: Crédito Extendido ────────────────────────────────────
        if ventas['credito_nuevo'] > 0:
            self.content.addWidget(self._section_title("🤝 Crédito Extendido Hoy (No entró a caja)"))

            credito_frame = QFrame()
            credito_frame.setStyleSheet(
                "background: white; border: 2px solid #7c3aed; border-radius: 8px;")
            credito_lay = QVBoxLayout(credito_frame)
            credito_lay.setContentsMargins(16, 12, 16, 12)
            credito_lay.setSpacing(6)

            row_c = QHBoxLayout()
            l_c_n = QLabel("🤝 Ventas a crédito nuevas hoy")
            l_c_n.setFont(QFont('Segoe UI', 10))
            l_c_n.setStyleSheet(f"color: {self.TEXTO}; border: none;")
            row_c.addWidget(l_c_n, 1)
            l_c_v = QLabel(f"${ventas['credito_nuevo']:,.0f}")
            l_c_v.setFont(QFont('Segoe UI', 10, QFont.Bold))
            l_c_v.setStyleSheet("color: #7c3aed; border: none;")
            l_c_v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row_c.addWidget(l_c_v)
            credito_lay.addLayout(row_c)

            nota = QLabel("ℹ️  Los pagos recibidos de este crédito aparecen en 'Cobros de créditos' (arriba)")
            nota.setFont(QFont('Segoe UI', 8))
            nota.setStyleSheet(f"color: {self.TEXTO_SEC}; border: none;")
            nota.setWordWrap(True)
            credito_lay.addWidget(nota)

            self.content.addWidget(credito_frame)

        # ── Sección: Egresos ───────────────────────────────────────────────
        self.content.addWidget(self._section_title("📤 Egresos del Día"))

        if not egresos_rows:
            l_ne = QLabel("No hubo egresos en esta fecha")
            l_ne.setStyleSheet(f"color: {self.TEXTO_SEC}; background: transparent;")
            self.content.addWidget(l_ne)
        else:
            # Totales por categoría
            cat_frame = QFrame()
            cat_frame.setStyleSheet("background: white; border: 1px solid #e2e8f0; border-radius: 8px;")
            cat_lay = QVBoxLayout(cat_frame)
            cat_lay.setContentsMargins(16, 12, 16, 12)

            lbl_cat = QLabel("Por Categoría:")
            lbl_cat.setFont(QFont('Segoe UI', 10, QFont.Bold))
            lbl_cat.setStyleSheet(f"color: {self.AZUL}; border: none;")
            cat_lay.addWidget(lbl_cat)

            for ec in egresos_cat:
                row = QHBoxLayout()
                l_c = QLabel(f"• {ec['categoria']}")
                l_c.setFont(QFont('Segoe UI', 10))
                l_c.setStyleSheet(f"color: {self.TEXTO}; border: none;")
                row.addWidget(l_c, 1)
                l_t = QLabel(f"${ec['total']:,.0f}")
                l_t.setFont(QFont('Segoe UI', 10, QFont.Bold))
                l_t.setStyleSheet(f"color: {self.ROJO}; border: none;")
                l_t.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                row.addWidget(l_t)
                cat_lay.addLayout(row)

            self.content.addWidget(cat_frame)

            # Tabla detalle
            lbl_det = QLabel("Detalle de Egresos:")
            lbl_det.setFont(QFont('Segoe UI', 10, QFont.Bold))
            lbl_det.setStyleSheet(f"color: {self.AZUL}; background: transparent;")
            self.content.addWidget(lbl_det)

            tbl = QTableWidget()
            cols = [("Categoría", 160), ("Descripción", 300), ("Método Pago", 130), ("Monto", 110)]
            tbl.setColumnCount(len(cols))
            tbl.setHorizontalHeaderLabels([c[0] for c in cols])
            for i, (_, w) in enumerate(cols):
                tbl.setColumnWidth(i, w)
            tbl.verticalHeader().setVisible(False)
            tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
            tbl.setSelectionMode(QAbstractItemView.NoSelection)
            tbl.setAlternatingRowColors(True)
            tbl.horizontalHeader().setStretchLastSection(True)
            tbl.setStyleSheet(
                f"QTableWidget {{ background: white; alternate-background-color: {COLORS['table_row_alt']}; gridline-color: transparent; border: 1px solid {COLORS['border']}; border-radius: 12px; }}"
                "QTableWidget::item { padding: 7px 6px; }"
                f"QHeaderView::section {{ background: {COLORS['table_header']}; color: {COLORS['table_header_fg']}; font-weight: 500; padding: 9px 8px; border: none; }}"
            )

            for r in egresos_rows:
                row_idx = tbl.rowCount()
                tbl.insertRow(row_idx)
                tbl.setItem(row_idx, 0, QTableWidgetItem(r.get('categoria', '')))
                tbl.setItem(row_idx, 1, QTableWidgetItem(r.get('descripcion', '')))
                tbl.setItem(row_idx, 2, QTableWidgetItem(r.get('metodo_pago', '')))
                monto_item = QTableWidgetItem(f"${r['monto']:,.0f}")
                monto_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                monto_item.setForeground(QColor(self.ROJO))
                tbl.setItem(row_idx, 3, monto_item)

            tbl_h = min(40 + len(egresos_rows) * 32, 260)
            tbl.setMinimumHeight(tbl_h)
            tbl.setMaximumHeight(tbl_h)
            self.content.addWidget(tbl)

        self.content.addStretch()
