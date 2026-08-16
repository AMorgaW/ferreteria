# -*- coding: utf-8 -*-
"""
Dashboard principal con diseño moderno e interactivo
"""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                                QLabel, QPushButton, QFrame, QScrollArea,
                                QTableWidget, QTableWidgetItem, QHeaderView,
                                QDialog, QMessageBox, QLineEdit, QComboBox,
                                QSpinBox, QDoubleSpinBox, QSizePolicy,
                                QAbstractItemView, QTextEdit, QGroupBox)
from PySide6.QtCore import Qt, QSize, Signal, QTimer, QThreadPool, QPointF
from PySide6.QtGui import QFont, QPainter, QColor, QBrush, QPen
from ui_config import COLORS, FONTS, make_font
from formato import formatear_stock
from ui.widgets import ShadowCard, KpiCard, ActionButton, make_line_icon
from ui.async_worker import FunctionWorker
from datetime import datetime, timedelta
import traceback
from models import AbonoVenta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clear_layout(layout):
    """Elimina todos los widgets e items de un layout."""
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget:
            widget.deleteLater()
        child = item.layout()
        if child:
            _clear_layout(child)


# ---------------------------------------------------------------------------
# Bar‑chart widget (replaces tk.Canvas)
# ---------------------------------------------------------------------------

class BarChartWidget(QWidget):
    """Dibuja la serie de ventas como gráfico lineal compacto."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = []
        self.setMinimumHeight(260)
        self.setStyleSheet("background: transparent; border: none;")

    def set_data(self, datos):
        self._data = datos or []
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(COLORS['bg_primary']))

        if not self._data:
            painter.setPen(QColor(COLORS['text_secondary']))
            painter.setFont(make_font(FONTS['body']))
            painter.drawText(self.rect(), Qt.AlignCenter,
                             "No hay ventas registradas en este período")
            painter.end()
            return

        w = self.width()
        h = self.height()
        left, right, top, bottom = 62, 20, 18, 54
        chart_width = max(1, w - left - right)
        chart_height = max(1, h - top - bottom)

        values = [max(0, float(d.get('monto', 0) or 0)) for d in self._data]
        max_valor = max(values) if values else 0
        scale_max = max(1000.0, max_valor)
        if scale_max > 1000:
            magnitude = 10 ** max(0, len(str(int(scale_max))) - 2)
            scale_max = ((int(scale_max) + magnitude - 1) // magnitude) * magnitude

        n = len(self._data)
        point_step = chart_width / max(1, n - 1)

        # Guías discretas: mejoran la lectura sin competir con los datos.
        grid_pen = QPen(QColor(COLORS['border']))
        grid_pen.setStyle(Qt.DashLine)
        painter.setPen(grid_pen)
        for step in range(5):
            y = top + (chart_height * step / 4)
            painter.drawLine(left, int(y), w - right, int(y))

        painter.setPen(QColor(COLORS['text_secondary']))
        painter.setFont(make_font(FONTS['small']))
        for step in range(5):
            value = scale_max * (4 - step) / 4
            y = top + (chart_height * step / 4)
            painter.drawText(0, int(y - 8), left - 10, 16,
                             Qt.AlignRight | Qt.AlignVCenter, f"{value:,.0f}")

        points = []
        for i, dato in enumerate(self._data):
            x = left + (i * point_step if n > 1 else chart_width / 2)
            y = top + chart_height - (values[i] / scale_max) * chart_height
            points.append(QPointF(x, y))

            # Etiqueta de fecha
            fecha = dato['fecha'].split('-')[2] if '-' in str(dato['fecha']) else str(i + 1)
            painter.setPen(QColor(COLORS['text_secondary']))
            painter.setFont(make_font(FONTS['small']))
            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(fecha)
            painter.drawText(int(x - tw / 2), h - 32, fecha)

            if values[i] > 0:
                painter.setPen(QColor(COLORS['text_primary']))
                text = f"${values[i]:,.0f}"
                tw2 = fm.horizontalAdvance(text)
                painter.drawText(int(x - tw2 / 2), int(y - 10), text)

        line_pen = QPen(QColor(COLORS['accent']), 2.3, Qt.SolidLine,
                        Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(line_pen)
        for i in range(1, len(points)):
            painter.drawLine(points[i - 1], points[i])

        painter.setBrush(QBrush(QColor('white')))
        painter.setPen(QPen(QColor(COLORS['accent']), 2))
        for point in points:
            painter.drawEllipse(point, 4, 4)

        # Leyenda centrada, coherente con la moneda del sistema.
        legend_y = h - 8
        legend_text = "Ventas (COP)"
        painter.setFont(make_font(FONTS['small']))
        legend_width = painter.fontMetrics().horizontalAdvance(legend_text)
        legend_x = (w - legend_width) / 2
        painter.setPen(QPen(QColor(COLORS['accent']), 2))
        painter.drawLine(int(legend_x - 28), legend_y - 4,
                         int(legend_x - 8), legend_y - 4)
        painter.setPen(QColor(COLORS['text_secondary']))
        painter.drawText(int(legend_x), legend_y, legend_text)

        painter.end()


# ---------------------------------------------------------------------------
# Dashboard principal
# ---------------------------------------------------------------------------

class DashboardUI(QWidget):
    """Dashboard principal del sistema"""

    def __init__(self, parent, reportes_service, alertas_service, auth_manager,
                 cuentas_por_cobrar_service=None):
        super().__init__(parent)
        self.parent_widget = parent
        self.reportes = reportes_service
        self.alertas = alertas_service
        self.auth = auth_manager
        self.cuentas_service = cuentas_por_cobrar_service
        self._thread_pool = QThreadPool.globalInstance()

        try:
            self.crear_ui()
            QTimer.singleShot(50, self.cargar_datos)
        except Exception as e:
            print(f"ERROR CRITICO en DashboardUI.__init__: {e}")
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Error al cargar dashboard: {e}")

    # ------------------------------------------------------------------
    # UI creation
    # ------------------------------------------------------------------

    def crear_ui(self):
        """Crea la interfaz del dashboard"""
        print("DEBUG: Iniciando crear_ui()...")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Contenedor principal con scroll
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet(
            f"QScrollArea {{ background: {COLORS['bg_secondary']}; border: none; }}"
        )

        self.scrollable_frame = QWidget()
        self.scrollable_frame.setStyleSheet(f"background: {COLORS['bg_secondary']};")
        self.scroll_layout = QVBoxLayout(self.scrollable_frame)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(0)

        scroll_area.setWidget(self.scrollable_frame)
        main_layout.addWidget(scroll_area)
        print("DEBUG: Canvas y scrollbar configurados")

        # Header del Dashboard
        print("DEBUG: Creando header...")
        self.crear_header()

        # Tarjetas de resumen (KPIs)
        print("DEBUG: Creando tarjetas...")
        self.crear_tarjetas_resumen()

        # Sección de gráficos
        print("DEBUG: Creando gráficos...")
        self.crear_seccion_graficos()

        self.scroll_layout.addStretch()
        print("DEBUG: crear_ui() completado")

    def crear_header(self):
        """Crea el header del dashboard"""
        header_frame = QWidget()
        header_frame.setStyleSheet(f"background: {COLORS['bg_secondary']};")
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(30, 22, 30, 12)

        # Título con icono
        left_layout = QHBoxLayout()
        left_layout.setSpacing(14)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(make_line_icon('grid', COLORS['primary'], 34).pixmap(34, 34))
        icon_lbl.setFixedSize(42, 42)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet("background: transparent; border: none;")
        left_layout.addWidget(icon_lbl)

        title_col = QVBoxLayout()

        es_vendedor = (self.auth.usuario_actual and self.auth.usuario_actual.rol == 'VENDEDOR')
        titulo_dashboard = f"Mis Ventas — {self.auth.usuario_actual.nombre_completo}" if es_vendedor else "Dashboard Principal"
        title_lbl = QLabel(titulo_dashboard)
        title_lbl.setFont(make_font(FONTS['xlarge']))
        title_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; background: transparent; border: none;"
            " font-size: 18pt; font-weight: 500;"
        )
        title_col.addWidget(title_lbl)

        ahora = datetime.now()
        meses = ("enero", "febrero", "marzo", "abril", "mayo", "junio",
                 "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")
        hora_actual = f"{ahora.day} de {meses[ahora.month - 1]} de {ahora.year} · {ahora:%H:%M}"
        date_lbl = QLabel(hora_actual)
        date_lbl.setFont(make_font(FONTS['body']))
        date_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; background: transparent; border: none;"
        )
        title_col.addWidget(date_lbl)

        left_layout.addLayout(title_col)
        header_layout.addLayout(left_layout)
        header_layout.addStretch()

        # Botón de actualizar
        btn_refresh = ActionButton(
            text="Actualizar datos",
            bg=COLORS['accent'], fg='white',
            hover_bg=COLORS['accent_hover'],
            border_color=COLORS['accent'], border_radius=9,
            padx=20, pady=10, bold=True, command=self.cargar_datos,
        )
        btn_refresh.setIcon(make_line_icon('refresh', 'white', 19))
        btn_refresh.setIconSize(QSize(19, 19))
        header_layout.addWidget(btn_refresh)

        self.scroll_layout.addWidget(header_frame)

    def crear_tarjetas_resumen(self):
        """Crea las tarjetas de KPI principales"""
        cards_container = QWidget()
        cards_container.setStyleSheet(f"background: {COLORS['bg_secondary']};")
        grid = QGridLayout(cards_container)
        grid.setContentsMargins(30, 10, 30, 16)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(14)
        self.cards_grid = grid
        self._cards_columns = None

        self.card_ventas_hoy = self.crear_tarjeta_kpi(
            "Ventas de Hoy", "$0", "0 ventas",
            COLORS['success'], COLORS['success_dark'],
        )

        self.card_ventas_mes = self.crear_tarjeta_kpi(
            "Ventas del Mes", "$0", "0 ventas",
            COLORS['accent'], COLORS['accent_dark'],
        )

        self.card_stock_critico = self.crear_tarjeta_kpi(
            "Stock Crítico", "0", "productos",
            COLORS['danger'], COLORS['danger_dark'],
        )

        self.card_cuentas = self.crear_tarjeta_kpi(
            "Cuentas por Cobrar", "$0", "0 cuentas",
            COLORS['warning'], COLORS['warning_dark'],
        )
        self._cards_widgets = [
            self.card_ventas_hoy['card'], self.card_ventas_mes['card'],
            self.card_stock_critico['card'], self.card_cuentas['card'],
        ]
        self._ajustar_grid_tarjetas()

        # Click handlers
        self.card_ventas_hoy['card'].mousePressEvent = (
            lambda e: self.ver_detalle_ventas_hoy()
        )
        self.card_ventas_mes['card'].mousePressEvent = (
            lambda e: self.ver_detalle_ventas_mes()
        )
        self.card_stock_critico['card'].mousePressEvent = (
            lambda e: self.ver_stock_critico_detallado()
        )
        if self.cuentas_service:
            self.card_cuentas['card'].mousePressEvent = (
                lambda e: self.ver_cuentas_por_cobrar()
            )

        self.scroll_layout.addWidget(cards_container)

    def _ajustar_grid_tarjetas(self):
        """Refluye las tarjetas según el ancho disponible, sin alterar datos."""
        width = self.width()
        columns = 4 if width >= 1080 else (2 if width >= 620 else 1)
        if columns == self._cards_columns:
            return
        self._cards_columns = columns
        for index, card in enumerate(self._cards_widgets):
            self.cards_grid.addWidget(card, index // columns, index % columns)
        for column in range(4):
            self.cards_grid.setColumnStretch(column, 1 if column < columns else 0)

    def resizeEvent(self, event):
        """Mantiene la composición del dashboard en resoluciones reducidas."""
        if hasattr(self, 'cards_grid'):
            self._ajustar_grid_tarjetas()
        super().resizeEvent(event)

    def crear_tarjeta_kpi(self, titulo, valor, subtitulo, color, color_hover):
        """Crea una tarjeta KPI con animación hover"""
        card = ShadowCard(content_margins=(0, 0, 0, 0),
                          border_radius=12, shadow_blur=14)
        card.setCursor(Qt.PointingHandCursor)
        card.setMinimumHeight(126)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Franja de color superior (4px, color = tipo de dato).
        color_bar = QFrame()
        color_bar.setFixedHeight(4)
        color_bar.setStyleSheet(f"background: {color}; border: none;")
        lay.addWidget(color_bar)

        # Contenido con icono semántico y jerarquía compacta.
        content = QWidget()
        content.setStyleSheet("background: white; border: none;")
        cl = QHBoxLayout(content)
        cl.setContentsMargins(18, 16, 18, 16)
        cl.setSpacing(14)

        if "Hoy" in titulo:
            icon_key, icon_bg = 'sales_today', '#E7F5EE'
        elif "Mes" in titulo:
            icon_key, icon_bg = 'sales_month', COLORS['accent_light']
        elif "Stock" in titulo:
            icon_key, icon_bg = 'stock', COLORS['danger_light']
        else:
            icon_key, icon_bg = 'credit', COLORS['warning_light']

        icon_lbl = QLabel()
        icon_lbl.setFixedSize(52, 52)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setPixmap(make_line_icon(icon_key, color, 27).pixmap(27, 27))
        icon_lbl.setStyleSheet(
            f"background: {icon_bg}; border: none; border-radius: 26px;"
        )
        cl.addWidget(icon_lbl, 0, Qt.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(3)

        lbl_titulo = QLabel(titulo)
        lbl_titulo.setWordWrap(True)
        lbl_titulo.setFont(make_font(FONTS['body']))
        lbl_titulo.setStyleSheet(
            f"color: {COLORS['text_primary']}; background: transparent; border: none;"
        )
        text_col.addWidget(lbl_titulo)

        lbl_valor = QLabel(valor)
        lbl_valor.setFont(QFont('Segoe UI', 20, QFont.Medium))
        lbl_valor.setStyleSheet(
            f"color: {COLORS['text_primary']}; background: transparent; border: none;"
            " font-size: 20pt; font-weight: 500;"
        )
        lbl_valor.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        text_col.addWidget(lbl_valor)

        lbl_subtitulo = QLabel(subtitulo)
        lbl_subtitulo.setWordWrap(True)
        lbl_subtitulo.setFont(make_font(FONTS['small']))
        lbl_subtitulo.setStyleSheet(
            f"color: {color}; background: transparent; border: none;"
        )
        text_col.addWidget(lbl_subtitulo)
        cl.addLayout(text_col, 1)

        lay.addWidget(content, 1)

        # Efectos hover
        _orig_enter = card.enterEvent
        _orig_leave = card.leaveEvent

        def _on_enter(event):
            color_bar.setStyleSheet(f"background: {color_hover}; border: none;")
            _orig_enter(event)

        def _on_leave(event):
            color_bar.setStyleSheet(f"background: {color}; border: none;")
            _orig_leave(event)

        card.enterEvent = _on_enter
        card.leaveEvent = _on_leave

        return {
            'card': card,
            'valor': lbl_valor,
            'subtitulo': lbl_subtitulo,
            'color_bar': color_bar,
            'content': content,
            'titulo': lbl_titulo,
        }

    def crear_seccion_graficos(self):
        """Crea la sección de gráficos"""
        section = QWidget()
        section.setStyleSheet(f"background: {COLORS['bg_secondary']};")
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(30, 8, 30, 22)

        graph_card = ShadowCard(border_radius=14, shadow_blur=14,
                                content_margins=(0, 0, 0, 0))
        graph_layout = QVBoxLayout(graph_card)
        graph_layout.setContentsMargins(20, 16, 20, 16)
        graph_layout.setSpacing(8)

        graph_header = QHBoxLayout()
        graph_header.setSpacing(10)
        graph_icon = QLabel()
        graph_icon.setFixedSize(36, 36)
        graph_icon.setAlignment(Qt.AlignCenter)
        graph_icon.setPixmap(make_line_icon('chart', COLORS['accent'], 20).pixmap(20, 20))
        graph_icon.setStyleSheet(
            f"background: {COLORS['accent_light']}; border-radius: 18px; border: none;"
        )
        graph_header.addWidget(graph_icon)

        lbl = QLabel("Análisis de Ventas · Últimos 7 Días")
        lbl.setFont(make_font(FONTS['heading']))
        lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; background: transparent; border: none;"
        )
        graph_header.addWidget(lbl)
        graph_header.addStretch()

        period_chip = QFrame()
        period_chip.setStyleSheet(
            f"QFrame {{ background: white; border: 1px solid {COLORS['border_input']};"
            " border-radius: 8px; }}"
        )
        period_layout = QHBoxLayout(period_chip)
        period_layout.setContentsMargins(10, 6, 10, 6)
        period_layout.setSpacing(6)
        period_icon = QLabel()
        period_icon.setPixmap(make_line_icon('calendar', COLORS['text_secondary'], 16).pixmap(16, 16))
        period_icon.setStyleSheet("background: transparent; border: none;")
        period_text = QLabel("Últimos 7 días")
        period_text.setStyleSheet(
            f"color: {COLORS['text_secondary']}; background: transparent; border: none;"
        )
        period_layout.addWidget(period_icon)
        period_layout.addWidget(period_text)
        graph_header.addWidget(period_chip)
        graph_layout.addLayout(graph_header)

        self.grafico_widget = BarChartWidget()
        graph_layout.addWidget(self.grafico_widget)

        section_layout.addWidget(graph_card)
        self.scroll_layout.addWidget(section)

    def crear_accesos_rapidos(self):
        """Crea la sección de accesos rápidos"""
        section = QWidget()
        section.setStyleSheet(f"background: {COLORS['bg_secondary']};")
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(30, 20, 30, 20)

        lbl = QLabel("🚀 Accesos Rápidos")
        lbl.setFont(make_font(FONTS['heading']))
        lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; background: transparent;"
        )
        section_layout.addWidget(lbl)

        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setSpacing(16)

        accesos = [
            ("💰", "Nueva Venta", COLORS['success'], None),
            ("📦", "Nuevo Producto", COLORS['primary'], None),
            ("👤", "Nuevo Cliente", COLORS['info'], None),
            ("📋", "Movimiento", COLORS['warning'], None),
            ("📊", "Ver Reportes", COLORS['primary_dark'], None),
            ("💵", "Abrir Caja", COLORS['success_dark'], None),
        ]

        for i, (icono, texto, color, comando) in enumerate(accesos):
            self.crear_boton_acceso_rapido(
                grid, i // 3, i % 3, icono, texto, color, comando,
            )

        section_layout.addWidget(grid_widget)
        self.scroll_layout.addWidget(section)

    def crear_boton_acceso_rapido(self, grid_layout, row, col, icono, texto,
                                  color, comando):
        """Crea un botón de acceso rápido con efecto"""
        card = ShadowCard(content_margins=(0, 0, 0, 0))
        card.setCursor(Qt.PointingHandCursor)
        card.setMinimumHeight(120)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        content = QWidget()
        content.setStyleSheet("background: white; border: none;")
        content_lay = QVBoxLayout(content)
        content_lay.setAlignment(Qt.AlignCenter)

        icon_lbl = QLabel(icono)
        icon_lbl.setFont(QFont('Segoe UI', 32))
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet("background: transparent; border: none;")
        content_lay.addWidget(icon_lbl)

        text_lbl = QLabel(texto)
        text_lbl.setFont(make_font(FONTS['body_bold']))
        text_lbl.setAlignment(Qt.AlignCenter)
        text_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; background: transparent; border: none;"
        )
        content_lay.addWidget(text_lbl)

        lay.addWidget(content, 1)

        # Barra inferior de color
        color_bar = QFrame()
        color_bar.setFixedHeight(4)
        color_bar.setStyleSheet(f"background: {color}; border: none;")
        lay.addWidget(color_bar)

        # Hover effects
        _orig_enter = card.enterEvent
        _orig_leave = card.leaveEvent

        def _on_enter(event):
            color_bar.setFixedHeight(6)
            content.setStyleSheet(
                f"background: {COLORS['bg_secondary']}; border: none;"
            )
            _orig_enter(event)

        def _on_leave(event):
            color_bar.setFixedHeight(4)
            content.setStyleSheet("background: white; border: none;")
            _orig_leave(event)

        card.enterEvent = _on_enter
        card.leaveEvent = _on_leave

        if comando:
            card.mousePressEvent = lambda e: comando()

        grid_layout.addWidget(card, row, col)

    def crear_seccion_alertas(self):
        """Crea la sección de alertas recientes"""
        section = QWidget()
        section.setStyleSheet(f"background: {COLORS['bg_secondary']};")
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(30, 20, 30, 20)

        header_layout = QHBoxLayout()
        lbl = QLabel("🔔 Alertas Recientes")
        lbl.setFont(make_font(FONTS['heading']))
        lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; background: transparent;"
        )
        header_layout.addWidget(lbl)
        header_layout.addStretch()
        section_layout.addLayout(header_layout)

        self.alertas_container = QWidget()
        self.alertas_layout = QVBoxLayout(self.alertas_container)
        self.alertas_layout.setContentsMargins(0, 0, 0, 0)
        self.alertas_layout.setSpacing(4)
        section_layout.addWidget(self.alertas_container)

        self.scroll_layout.addWidget(section)

    def crear_productos_destacados(self):
        """Crea la sección de productos más vendidos"""
        section = QWidget()
        section.setStyleSheet(f"background: {COLORS['bg_secondary']};")
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(30, 20, 30, 20)

        lbl = QLabel("🏆 Top 5 Productos del Mes")
        lbl.setFont(make_font(FONTS['heading']))
        lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; background: transparent;"
        )
        section_layout.addWidget(lbl)

        self.productos_container = QWidget()
        self.productos_layout = QVBoxLayout(self.productos_container)
        self.productos_layout.setContentsMargins(0, 0, 0, 0)
        self.productos_layout.setSpacing(4)
        section_layout.addWidget(self.productos_container)

        self.scroll_layout.addWidget(section)

    # ------------------------------------------------------------------
    # Data loading / update
    # ------------------------------------------------------------------

    def cargar_datos(self):
        """Carga y actualiza todos los datos del dashboard"""
        worker = FunctionWorker(self._obtener_datos_dashboard)
        worker.signals.result.connect(self._aplicar_datos_dashboard)
        worker.signals.error.connect(lambda e: print(f"Error al cargar datos: {e}"))
        self._thread_pool.start(worker)

    def _obtener_datos_dashboard(self):
        es_vendedor = (self.auth.usuario_actual and self.auth.usuario_actual.rol == 'VENDEDOR')
        uid = self.auth.usuario_actual.id if es_vendedor else None
        datos = self.reportes.dashboard_principal(usuario_id=uid)

        if self.cuentas_service:
            try:
                totales = self.cuentas_service.obtener_totales_cuentas_por_cobrar()
                datos['cuentas_cobrar'] = {
                    'monto_pendiente': totales['total_por_cobrar'],
                    'cuentas_pendientes': totales['total_facturas_pendientes'],
                }
            except Exception as e:
                print(f"Error al cargar cuentas por cobrar: {e}")

        return datos

    def _aplicar_datos_dashboard(self, datos):
        try:
            self.actualizar_card_ventas_hoy(datos['ventas_hoy'])
            self.actualizar_card_ventas_mes(datos['ventas_mes'])
            self.actualizar_card_stock_critico(datos['stock_critico'])
            self.actualizar_card_cuentas_cobrar(datos['cuentas_cobrar'])
            self.dibujar_grafico(datos['grafico_7_dias'])

        except Exception as e:
            print(f"Error al cargar datos: {e}")

    def actualizar_card_ventas_hoy(self, datos):
        """Actualiza la tarjeta de ventas de hoy"""
        es_vendedor = (self.auth.usuario_actual and self.auth.usuario_actual.rol == 'VENDEDOR')
        self.card_ventas_hoy['valor'].setText(f"${datos['monto_hoy']:,.0f}")
        label = "mis ventas" if es_vendedor else "ventas realizadas"
        self.card_ventas_hoy['subtitulo'].setText(f"{datos['ventas_hoy']} {label}")
        if es_vendedor:
            self.card_ventas_hoy['titulo'].setText("Mis Ventas de Hoy")

    def actualizar_card_ventas_mes(self, datos):
        """Actualiza la tarjeta de ventas del mes"""
        es_vendedor = (self.auth.usuario_actual and self.auth.usuario_actual.rol == 'VENDEDOR')
        self.card_ventas_mes['valor'].setText(f"${datos['monto_mes']:,.0f}")
        label = "mis ventas" if es_vendedor else "ventas este mes"
        self.card_ventas_mes['subtitulo'].setText(f"{datos['ventas_mes']} {label}")
        if es_vendedor:
            self.card_ventas_mes['titulo'].setText("Mis Ventas del Mes")

    def actualizar_card_stock_critico(self, count):
        """Actualiza la tarjeta de stock crítico"""
        self.card_stock_critico['valor'].setText(str(count))
        texto = "producto" if count == 1 else "productos"
        self.card_stock_critico['subtitulo'].setText(
            f"{texto} requieren atención"
        )

    def actualizar_card_cuentas_cobrar(self, datos):
        """Actualiza la tarjeta de cuentas por cobrar"""
        self.card_cuentas['valor'].setText(f"${datos['monto_pendiente']:,.0f}")
        texto = "cuenta" if datos['cuentas_pendientes'] == 1 else "cuentas"
        self.card_cuentas['subtitulo'].setText(
            f"{datos['cuentas_pendientes']} {texto} pendientes"
        )

    def dibujar_grafico(self, datos):
        """Actualiza la serie visual del gráfico de ventas."""
        self.grafico_widget.set_data(datos)

    # ------------------------------------------------------------------
    # Alertas
    # ------------------------------------------------------------------

    def cargar_alertas(self):
        """Carga y muestra las alertas recientes"""
        _clear_layout(self.alertas_layout)

        alertas = self.alertas.obtener_alertas(solo_no_leidas=True)[:5]

        if not alertas:
            lbl = QLabel("✅ No hay alertas pendientes")
            lbl.setFont(make_font(FONTS['body']))
            lbl.setStyleSheet(
                f"color: {COLORS['success']}; background: white;"
                "border: 1px solid #e0e0e0; padding: 15px 20px;"
            )
            self.alertas_layout.addWidget(lbl)
            return

        for alerta in alertas:
            self.crear_item_alerta(alerta)

    def crear_item_alerta(self, alerta):
        """Crea un item de alerta"""
        colores_prioridad = {
            'CRITICA': COLORS['danger'],
            'ALTA': COLORS['warning'],
            'MEDIA': COLORS['info'],
            'BAJA': COLORS['text_light'],
        }
        color = colores_prioridad.get(alerta['prioridad'], COLORS['info'])

        item = QFrame()
        item.setStyleSheet(
            "QFrame { background: white; border: 1px solid #e0e0e0; }"
        )
        item_layout = QHBoxLayout(item)
        item_layout.setContentsMargins(0, 0, 0, 0)
        item_layout.setSpacing(0)

        # Barra lateral de color
        bar = QFrame()
        bar.setFixedWidth(5)
        bar.setStyleSheet(f"background: {color}; border: none;")
        item_layout.addWidget(bar)

        # Contenido
        content_lay = QVBoxLayout()
        content_lay.setContentsMargins(15, 10, 15, 10)

        title_lbl = QLabel(alerta['titulo'])
        title_lbl.setFont(make_font(FONTS['body_bold']))
        title_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; background: transparent; border: none;"
        )
        content_lay.addWidget(title_lbl)

        msg_lbl = QLabel(alerta['mensaje'])
        msg_lbl.setFont(make_font(FONTS['small']))
        msg_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; background: transparent; border: none;"
        )
        content_lay.addWidget(msg_lbl)

        item_layout.addLayout(content_lay, 1)
        self.alertas_layout.addWidget(item)

    # ------------------------------------------------------------------
    # Productos destacados
    # ------------------------------------------------------------------

    def cargar_productos_destacados(self, productos):
        """Carga y muestra los productos más vendidos"""
        _clear_layout(self.productos_layout)

        if not productos:
            lbl = QLabel("No hay datos disponibles")
            lbl.setFont(make_font(FONTS['body']))
            lbl.setStyleSheet(
                f"color: {COLORS['text_secondary']}; background: white; padding: 15px 20px;"
            )
            self.productos_layout.addWidget(lbl)
            return

        self.productos_top = productos
        for i, producto in enumerate(productos, 1):
            self.crear_item_producto(i, producto)

    def crear_item_producto(self, posicion, producto):
        """Crea un item de producto destacado"""
        item = QFrame()
        item.setStyleSheet(
            "QFrame { background: white; border: 1px solid #e0e0e0; }"
        )
        item_layout = QHBoxLayout(item)
        item_layout.setContentsMargins(0, 0, 0, 0)
        item_layout.setSpacing(0)

        # Medalla según posición
        medallas = {1: "🥇", 2: "🥈", 3: "🥉"}
        medalla = medallas.get(posicion, "🏅")

        medal_lbl = QLabel(medalla)
        medal_lbl.setFont(QFont('Segoe UI', 20))
        medal_lbl.setFixedWidth(60)
        medal_lbl.setAlignment(Qt.AlignCenter)
        medal_lbl.setStyleSheet("background: transparent; border: none;")
        item_layout.addWidget(medal_lbl)

        # Información del producto
        info_lay = QVBoxLayout()
        info_lay.setContentsMargins(0, 10, 15, 10)

        name_lbl = QLabel(producto['nombre'])
        name_lbl.setFont(make_font(FONTS['body_bold']))
        name_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; background: transparent; border: none;"
        )
        info_lay.addWidget(name_lbl)

        qty_lbl = QLabel(f"{producto['cantidad']} unidades vendidas")
        qty_lbl.setFont(make_font(FONTS['small']))
        qty_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; background: transparent; border: none;"
        )
        info_lay.addWidget(qty_lbl)

        # Barra de progreso simple
        max_cantidad = self.productos_top[0]['cantidad'] if self.productos_top else 1
        if max_cantidad == 0:
            max_cantidad = 1
        porcentaje = (producto['cantidad'] / max_cantidad) * 100

        progress_bg = QFrame()
        progress_bg.setFixedHeight(8)
        progress_bg.setStyleSheet(
            f"background: {COLORS['bg_secondary']}; border-radius: 4px; border: none;"
        )
        prog_lay = QHBoxLayout(progress_bg)
        prog_lay.setContentsMargins(0, 0, 0, 0)
        prog_lay.setSpacing(0)

        progress_fill = QFrame()
        progress_fill.setFixedWidth(max(1, int(porcentaje * 2)))
        progress_fill.setStyleSheet(
            f"background: {COLORS['success']}; border-radius: 4px; border: none;"
        )
        prog_lay.addWidget(progress_fill)
        prog_lay.addStretch()

        info_lay.addWidget(progress_bg)
        item_layout.addLayout(info_lay, 1)

        self.productos_layout.addWidget(item)

    # ------------------------------------------------------------------
    # Ventas de Hoy – popup detalle
    # ------------------------------------------------------------------

    def ver_detalle_ventas_hoy(self):
        """Popup con el desglose de ventas del día actual."""
        try:
            es_vendedor = (self.auth.usuario_actual and self.auth.usuario_actual.rol == 'VENDEDOR')
            uid = self.auth.usuario_actual.id if es_vendedor else None
            data = self.reportes.detalle_ventas_hoy(usuario_id=uid)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudieron cargar los datos: {e}")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Ventas de Hoy")
        dlg.setFixedSize(660, 430)
        dlg.setModal(True)

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(8)

        # ── Fila superior: título + totales ──
        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        lbl_tit = QLabel("💰 Ventas de Hoy")
        lbl_tit.setFont(make_font(FONTS['heading']))
        lbl_tit.setStyleSheet(f"color: {COLORS['text_primary']};")
        top_row.addWidget(lbl_tit)
        top_row.addStretch()

        colores_metodo = {
            'EFECTIVO': ('#10b981', '#ecfdf5'),
            'TARJETA_DEBITO': ('#3b82f6', '#eff6ff'),
            'TARJETA_CREDITO': ('#3b82f6', '#eff6ff'),
            'TRANSFERENCIA': ('#8b5cf6', '#f5f3ff'),
            'CREDITO': ('#f59e0b', '#fffbeb'),
        }
        nombres_metodo = {
            'TARJETA_DEBITO': 'Débito', 'TARJETA_CREDITO': 'T.Crédito',
            'EFECTIVO': 'Efectivo', 'TRANSFERENCIA': 'Transfer.',
            'CREDITO': 'A Crédito',
        }

        total_cobrado = sum(m['monto'] for m in data['por_metodo'] if m['metodo_pago'].upper() != 'CREDITO')
        total_credito_raw = sum(
            m['monto'] for m in data['por_metodo'] if m['metodo_pago'].upper() == 'CREDITO'
        )
        # "pendiente" real = suma de saldo de ventas crédito no pagadas (del chip ya viene monto_pagado)
        total_pendiente = sum(
            (v.get('total', 0) - (v.get('monto_pagado', 0) or 0))
            for v in data['ventas']
            if v.get('metodo_pago', '').upper() == 'CREDITO'
            and v.get('estado_pago', '') != 'PAGADO'
        )

        # Mini-resumen a la derecha del título
        lbl_cobrado = QLabel(f"Cobrado: ${total_cobrado:,.0f}")
        lbl_cobrado.setFont(QFont('Segoe UI', 11, QFont.Bold))
        lbl_cobrado.setStyleSheet(f"color: {COLORS['primary']};")
        top_row.addWidget(lbl_cobrado)

        if total_pendiente > 0:
            sep_v = QLabel("·")
            sep_v.setStyleSheet(f"color: {COLORS['text_light']};")
            top_row.addWidget(sep_v)
            lbl_pend = QLabel(f"Pendiente crédito: ${total_pendiente:,.0f}")
            lbl_pend.setFont(QFont('Segoe UI', 10))
            lbl_pend.setStyleSheet("color: #d97706;")
            top_row.addWidget(lbl_pend)

        lay.addLayout(top_row)

        # ── Chips de métodos (compactos) ──
        metodos_row = QHBoxLayout()
        metodos_row.setSpacing(6)
        for m in data['por_metodo']:
            key = m['metodo_pago'].upper()
            fg, bg = colores_metodo.get(key, (COLORS['primary'], '#f0f9ff'))
            nombre = nombres_metodo.get(key, m['metodo_pago'])
            chip = QLabel(f"{nombre}: ${m['monto']:,.0f} ({m['cantidad']})")
            chip.setFont(QFont('Segoe UI', 8, QFont.Bold))
            chip.setStyleSheet(
                f"background: {bg}; color: {fg}; border-radius: 10px;"
                f" padding: 3px 9px; border: 1px solid {fg};"
            )
            metodos_row.addWidget(chip)
        metodos_row.addStretch()
        lay.addLayout(metodos_row)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"border: 1px solid {COLORS['border']};")
        lay.addWidget(sep)

        # ── Tabla ──
        tabla = QTableWidget()
        tabla.setColumnCount(4)
        tabla.setHorizontalHeaderLabels(["Hora", "Cliente", "Método de pago", "Total"])
        hdr = tabla.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Fixed);   tabla.setColumnWidth(0, 76)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.Fixed);   tabla.setColumnWidth(2, 160)
        hdr.setSectionResizeMode(3, QHeaderView.Fixed);   tabla.setColumnWidth(3, 130)
        tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        tabla.setAlternatingRowColors(True)
        tabla.verticalHeader().setVisible(False)
        tabla.setShowGrid(False)
        tabla.setStyleSheet("""
            QTableWidget { border: 1px solid #e2e8f0; border-radius: 6px; font-size: 9pt; }
            QHeaderView::section { background: #f8fafc; padding: 6px; font-weight: 500;
                                   border: none; border-bottom: 1px solid #e2e8f0; }
        """)

        ventas = data['ventas']
        tabla.setRowCount(len(ventas))
        for i, v in enumerate(ventas):
            es_credito = v.get('metodo_pago', '').upper() == 'CREDITO'
            estado_pago = v.get('estado_pago', '')
            monto_pagado = v.get('monto_pagado', 0) or 0
            total = v.get('total', 0)

            etiqueta_estado = {
                'PAGADO': '✓ Pagado', 'PARCIAL': '⬤ Parcial', 'PENDIENTE': '○ Pendiente'
            }.get(estado_pago, estado_pago) if es_credito else ''

            metodo_txt = (f"Crédito — {etiqueta_estado}" if es_credito
                          else nombres_metodo.get(v.get('metodo_pago', '').upper(),
                                                  v.get('metodo_pago', '')))

            if es_credito and estado_pago != 'PAGADO':
                monto_txt = f"${monto_pagado:,.0f} / ${total:,.0f}"
            else:
                monto_txt = f"${total:,.0f}"

            tabla.setItem(i, 0, QTableWidgetItem(str(v.get('hora', ''))))
            tabla.setItem(i, 1, QTableWidgetItem(str(v.get('cliente', ''))))
            tabla.setItem(i, 2, QTableWidgetItem(metodo_txt))
            monto_item = QTableWidgetItem(monto_txt)
            monto_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            tabla.setItem(i, 3, monto_item)

            if es_credito:
                if estado_pago == 'PAGADO':
                    row_bg, row_fg = QColor('#ecfdf5'), QColor('#065f46')
                elif estado_pago == 'PARCIAL':
                    row_bg, row_fg = QColor('#fff7ed'), QColor('#9a3412')
                else:
                    row_bg, row_fg = QColor('#fffbeb'), QColor('#92400e')
                for col in range(4):
                    it = tabla.item(i, col)
                    if it:
                        it.setBackground(row_bg)
                        it.setForeground(row_fg)

        tabla.resizeRowsToContents()
        lay.addWidget(tabla, 1)

        # ── Leyenda crédito + botón ──
        bot_row = QHBoxLayout()
        bot_row.setSpacing(16)
        for color, texto in [('#ecfdf5', '✓ Pagado'), ('#fff7ed', '⬤ Parcial'), ('#fffbeb', '○ Pendiente')]:
            leg = QLabel(texto)
            leg.setFont(QFont('Segoe UI', 8))
            leg.setStyleSheet(f"background: {color}; border-radius: 4px; padding: 2px 8px;"
                              f" color: {COLORS['text_secondary']};")
            bot_row.addWidget(leg)
        bot_row.addStretch()

        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setFixedWidth(90)
        btn_cerrar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['primary']}; color: white; border: none;"
            f" border-radius: 6px; padding: 7px 0; font-weight: 500; }}"
            f"QPushButton:hover {{ background: {COLORS['primary_dark']}; }}"
        )
        btn_cerrar.clicked.connect(dlg.accept)
        bot_row.addWidget(btn_cerrar)
        lay.addLayout(bot_row)

        dlg.exec()

    # ------------------------------------------------------------------
    # Ventas del Mes – popup detalle
    # ------------------------------------------------------------------

    def ver_detalle_ventas_mes(self):
        """Popup con totales diarios del mes y desglose por método de pago."""
        try:
            es_vendedor = (self.auth.usuario_actual and self.auth.usuario_actual.rol == 'VENDEDOR')
            uid = self.auth.usuario_actual.id if es_vendedor else None
            data = self.reportes.detalle_ventas_mes(usuario_id=uid)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudieron cargar los datos: {e}")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Ventas del Mes")
        dlg.setFixedSize(680, 500)
        dlg.setModal(True)

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)

        lbl_tit = QLabel("📅 Ventas del Mes")
        lbl_tit.setFont(make_font(FONTS['heading']))
        lbl_tit.setStyleSheet(f"color: {COLORS['text_primary']};")
        lay.addWidget(lbl_tit)

        # Chips por método
        metodos_row = QHBoxLayout()
        metodos_row.setSpacing(8)
        colores_metodo = {
            'EFECTIVO': ('#10b981', '#ecfdf5'),
            'TARJETA_DEBITO': ('#3b82f6', '#eff6ff'),
            'TARJETA_CREDITO': ('#3b82f6', '#eff6ff'),
            'TRANSFERENCIA': ('#8b5cf6', '#f5f3ff'),
            'CREDITO': ('#f59e0b', '#fffbeb'),
        }
        total_cobrado_mes = sum(m['monto'] for m in data['por_metodo'] if m['metodo_pago'].upper() != 'CREDITO')
        total_credito_mes = sum(m['monto'] for m in data['por_metodo'] if m['metodo_pago'].upper() == 'CREDITO')
        for m in data['por_metodo']:
            key = m['metodo_pago'].upper()
            fg, bg = colores_metodo.get(key, (COLORS['primary'], '#f0f9ff'))
            nombre_corto = {'TARJETA_DEBITO': 'Débito', 'TARJETA_CREDITO': 'Crédito',
                            'EFECTIVO': 'Efectivo', 'TRANSFERENCIA': 'Transferencia',
                            'CREDITO': 'A Crédito'}.get(key, m['metodo_pago'])
            chip = QLabel(f"{nombre_corto}: ${m['monto']:,.0f}")
            chip.setFont(make_font(FONTS['body_bold']))
            chip.setStyleSheet(
                f"background: {bg}; color: {fg}; border-radius: 12px;"
                f" padding: 5px 12px; border: 1px solid {fg};"
            )
            metodos_row.addWidget(chip)
        metodos_row.addStretch()
        lay.addLayout(metodos_row)

        total_lbl = QLabel(f"Total cobrado: ${total_cobrado_mes:,.0f}")
        total_lbl.setFont(QFont('Segoe UI', 18, QFont.Bold))
        total_lbl.setStyleSheet(f"color: {COLORS['primary']};")
        lay.addWidget(total_lbl)
        if total_credito_mes > 0:
            cred_lbl = QLabel(f"  Pendiente a crédito: ${total_credito_mes:,.0f}")
            cred_lbl.setFont(QFont('Segoe UI', 10))
            cred_lbl.setStyleSheet("color: #d97706;")
            lay.addWidget(cred_lbl)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"border: 1px solid {COLORS['border']};")
        lay.addWidget(sep)

        lbl_sub = QLabel("Totales por día:")
        lbl_sub.setFont(make_font(FONTS['body_bold']))
        lay.addWidget(lbl_sub)

        tabla = QTableWidget()
        tabla.setColumnCount(3)
        tabla.setHorizontalHeaderLabels(["Fecha", "# Ventas", "Total"])
        tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        tabla.setAlternatingRowColors(True)
        tabla.verticalHeader().setVisible(False)
        tabla.setStyleSheet("QTableWidget { border: 1px solid #e2e8f0; }")

        dias = data['por_dia']
        tabla.setRowCount(len(dias))
        for i, d in enumerate(dias):
            tabla.setItem(i, 0, QTableWidgetItem(str(d.get('fecha', ''))))
            cant_item = QTableWidgetItem(formatear_stock(d.get('cantidad', 0)))
            cant_item.setTextAlignment(Qt.AlignCenter)
            tabla.setItem(i, 1, cant_item)
            monto_item = QTableWidgetItem(f"${d.get('monto', 0):,.0f}")
            monto_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            tabla.setItem(i, 2, monto_item)

        lay.addWidget(tabla, 1)

        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['primary']}; color: white; border: none;"
            f" border-radius: 6px; padding: 8px 24px; font-weight: 500; }}"
            f"QPushButton:hover {{ background: {COLORS['primary_dark']}; }}"
        )
        btn_cerrar.clicked.connect(dlg.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(btn_cerrar)
        lay.addLayout(btn_row)

        dlg.exec()

    # ------------------------------------------------------------------
    # Stock Crítico – Vista detallada
    # ------------------------------------------------------------------

    def ver_stock_critico_detallado(self):
        """Abre vista ampliada de productos con stock crítico"""
        try:
            productos_criticos = self.alertas.obtener_productos_stock_critico()

            if not productos_criticos:
                QMessageBox.information(
                    self, "Stock Correcto",
                    "No hay productos con stock crítico en este momento.\n\n"
                    "Todos los productos tienen stock por encima del mínimo configurado.",
                )
                return

            dialog = QDialog(self)
            dialog.setWindowTitle("📦 Productos con Stock Crítico - Vista Detallada")
            dialog.resize(1100, 700)
            dialog.setWindowModality(Qt.WindowModal)

            dlg_layout = QVBoxLayout(dialog)
            dlg_layout.setContentsMargins(0, 0, 0, 0)
            dlg_layout.setSpacing(0)

            # Header
            header = QFrame()
            header.setFixedHeight(80)
            header.setStyleSheet(f"background: {COLORS['danger']};")
            h_lay = QVBoxLayout(header)
            h_lay.setContentsMargins(30, 15, 30, 15)

            h_title = QLabel("⚠️ STOCK CRÍTICO - REPOSICIÓN URGENTE")
            h_title.setFont(QFont('Segoe UI', 18, QFont.Bold))
            h_title.setStyleSheet("color: white; background: transparent;")
            h_lay.addWidget(h_title)

            h_sub = QLabel(
                f"{len(productos_criticos)} productos requieren atención inmediata"
            )
            h_sub.setFont(make_font(FONTS['body']))
            h_sub.setStyleSheet("color: white; background: transparent;")
            h_lay.addWidget(h_sub)

            dlg_layout.addWidget(header)

            # Contenido
            content = QWidget()
            content.setStyleSheet("background: white;")
            content_lay = QVBoxLayout(content)
            content_lay.setContentsMargins(20, 20, 20, 20)

            # Info box
            info_frame = QFrame()
            info_frame.setStyleSheet(
                "background: #fff3cd; border: 1px solid #ffc107; border-radius: 6px;"
            )
            info_lay = QVBoxLayout(info_frame)
            info_lay.setContentsMargins(15, 10, 15, 10)

            info_title = QLabel("ℹ️ Información")
            info_title.setFont(make_font(FONTS['body_bold']))
            info_title.setStyleSheet(
                "color: #856404; background: transparent; border: none;"
            )
            info_lay.addWidget(info_title)

            info_text = QLabel(
                "Los productos listados tienen stock igual o menor al mínimo configurado.\n"
                "Se recomienda realizar pedido de reposición lo antes posible."
            )
            info_text.setFont(make_font(FONTS['body']))
            info_text.setStyleSheet(
                "color: #856404; background: transparent; border: none;"
            )
            info_lay.addWidget(info_text)

            content_lay.addWidget(info_frame)

            # Tabla
            columnas = (
                'Estado', 'Producto', 'Categoría', 'Stock Actual',
                'Stock Mínimo', 'Faltante', 'Proveedor',
            )
            anchos = [100, 250, 150, 100, 100, 100, 200]

            tbl = QTableWidget()
            tbl.setColumnCount(len(columnas))
            tbl.setHorizontalHeaderLabels(columnas)
            tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
            tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
            tbl.horizontalHeader().setStretchLastSection(True)
            tbl.verticalHeader().setVisible(False)

            for i, w in enumerate(anchos):
                tbl.setColumnWidth(i, w)

            # Tags para colores
            for producto in productos_criticos:
                if producto['stock_actual'] == 0:
                    estado = "🔴 CRÍTICO"
                    bg_c = QColor('#f8d7da')
                    fg_c = QColor('#721c24')
                elif producto['diferencia'] >= 5:
                    estado = "🟠 URGENTE"
                    bg_c = QColor('#fff3cd')
                    fg_c = QColor('#856404')
                else:
                    estado = "🟡 BAJO"
                    bg_c = QColor('#d1ecf1')
                    fg_c = QColor('#0c5460')

                categoria = producto.get('categoria', '-') or '-'
                valores = (
                    estado,
                    producto['nombre'],
                    categoria,
                    str(producto['stock_actual']),
                    str(producto['stock_minimo']),
                    f"+{producto['diferencia']}" if producto['diferencia'] > 0 else "0",
                    producto['proveedor_nombre'] or 'Sin proveedor',
                )
                row = tbl.rowCount()
                tbl.insertRow(row)
                for ci, val in enumerate(valores):
                    it = QTableWidgetItem(str(val))
                    it.setBackground(bg_c)
                    it.setForeground(fg_c)
                    if ci != 1:
                        it.setTextAlignment(Qt.AlignCenter)
                    tbl.setItem(row, ci, it)

            content_lay.addWidget(tbl, 1)
            dlg_layout.addWidget(content, 1)

            # Botones
            btn_frame = QWidget()
            btn_frame.setStyleSheet("background: white;")
            btn_lay = QHBoxLayout(btn_frame)
            btn_lay.setContentsMargins(20, 20, 20, 20)
            btn_lay.addStretch()

            btn_export = ActionButton(
                text="📄 Exportar Lista",
                bg=COLORS['success'], fg='white',
                border_color=COLORS['success'],
                command=lambda: self.exportar_stock_critico(productos_criticos),
            )
            btn_lay.addWidget(btn_export)

            btn_ok = ActionButton(
                text="✓ Entendido",
                bg=COLORS['primary'], fg='white',
                border_color=COLORS['primary'], bold=True,
                command=dialog.accept,
            )
            btn_lay.addWidget(btn_ok)

            dlg_layout.addWidget(btn_frame)
            dialog.show()

        except Exception as e:
            print(f"Error mostrando stock crítico: {e}")
            traceback.print_exc()
            QMessageBox.critical(
                self, "Error", f"Error al mostrar stock crítico: {e}"
            )

    def exportar_stock_critico(self, productos):
        """Exporta lista de productos críticos a archivo de texto"""
        try:
            from datetime import datetime

            filename = f"stock_critico_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

            with open(filename, 'w', encoding='utf-8') as f:
                f.write("=" * 80 + "\n")
                f.write("REPORTE DE STOCK CRÍTICO - REPOSICIÓN URGENTE\n")
                f.write(f"Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")
                f.write("=" * 80 + "\n\n")

                f.write(f"Total de productos críticos: {len(productos)}\n\n")

                for i, prod in enumerate(productos, 1):
                    estado = (
                        "CRÍTICO" if prod['stock_actual'] == 0
                        else "URGENTE" if prod['diferencia'] >= 5
                        else "BAJO"
                    )
                    f.write(f"{i}. {prod['nombre']}\n")
                    f.write(f"   Estado: {estado}\n")
                    f.write(f"   Stock actual: {prod['stock_actual']}\n")
                    f.write(f"   Stock mínimo: {prod['stock_minimo']}\n")
                    f.write(f"   Faltante: {prod['diferencia']}\n")
                    if prod['proveedor_nombre']:
                        f.write(f"   Proveedor: {prod['proveedor_nombre']}\n")
                    f.write("\n")

                f.write("=" * 80 + "\n")
                f.write("FIN DEL REPORTE\n")

            QMessageBox.information(
                self, "Exportado",
                f"Lista exportada exitosamente a:\n{filename}",
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al exportar: {e}")

    # ------------------------------------------------------------------
    # Cuentas por Cobrar
    # ------------------------------------------------------------------

    def ver_cuentas_por_cobrar(self):
        """Abre panel completo de gestión de cuentas por cobrar"""
        if not self.cuentas_service:
            QMessageBox.warning(
                self, "Advertencia",
                "Servicio de cuentas por cobrar no disponible",
            )
            return

        try:
            ventas = self.cuentas_service.obtener_ventas_credito_pendientes()
        except Exception as e:
            QMessageBox.critical(
                self, "Error",
                f"Error al obtener cuentas por cobrar: {e}",
            )
            return

        if not ventas:
            QMessageBox.information(
                self, "Información",
                "No hay cuentas por cobrar pendientes",
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Gestión de Cuentas por Cobrar")
        dialog.resize(1100, 650)
        dialog.setWindowModality(Qt.WindowModal)

        dlg_layout = QVBoxLayout(dialog)
        dlg_layout.setContentsMargins(0, 0, 0, 0)
        dlg_layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(70)
        header.setStyleSheet(f"background: {COLORS['warning']};")
        header_lay = QHBoxLayout(header)
        header_lay.setContentsMargins(30, 20, 20, 20)

        h_title = QLabel("💳 Gestión de Cuentas por Cobrar")
        h_title.setFont(QFont('Segoe UI', 18, QFont.Bold))
        h_title.setStyleSheet("color: white; background: transparent;")
        header_lay.addWidget(h_title)
        header_lay.addStretch()

        btn_actualizar = ActionButton(
            text="🔄 Actualizar",
            bg='white', fg=COLORS['warning'],
            border_color='white',
        )
        header_lay.addWidget(btn_actualizar)
        dlg_layout.addWidget(header)

        # Totales
        totales_widget = QWidget()
        totales_widget.setStyleSheet("background: white;")
        totales_lay = QHBoxLayout(totales_widget)
        totales_lay.setContentsMargins(30, 20, 30, 20)

        total_deuda = sum(v['saldo_pendiente'] for v in ventas)
        total_pagado = sum(v['monto_pagado'] for v in ventas)

        lbl_total_deuda = QLabel(f"Total por Cobrar: ${total_deuda:,.0f}")
        lbl_total_deuda.setFont(QFont('Segoe UI', 16, QFont.Bold))
        lbl_total_deuda.setStyleSheet("color: #DC2626; background: transparent;")
        totales_lay.addWidget(lbl_total_deuda)

        lbl_total_pagado = QLabel(f"Total Abonado: ${total_pagado:,.0f}")
        lbl_total_pagado.setFont(make_font(FONTS['body']))
        lbl_total_pagado.setStyleSheet("color: #059669; background: transparent;")
        totales_lay.addWidget(lbl_total_pagado)

        lbl_facturas = QLabel(f"Facturas Pendientes: {len(ventas)}")
        lbl_facturas.setFont(make_font(FONTS['body']))
        lbl_facturas.setStyleSheet("background: transparent;")
        totales_lay.addWidget(lbl_facturas)
        totales_lay.addStretch()

        dlg_layout.addWidget(totales_widget)

        # Guardar refs para poder actualizarlas
        totales_widget.lbl_total_deuda = lbl_total_deuda
        totales_widget.lbl_total_pagado = lbl_total_pagado
        totales_widget.lbl_facturas = lbl_facturas

        # Tabla
        columnas = (
            'Factura', 'Fecha', 'Cliente', 'Total',
            'Pagado', 'Saldo', 'Estado', 'Días',
        )
        anchos = [100, 100, 180, 100, 100, 100, 100, 70]

        tbl = QTableWidget()
        tbl.setColumnCount(len(columnas))
        tbl.setHorizontalHeaderLabels(columnas)
        tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tbl.horizontalHeader().setStretchLastSection(True)
        tbl.verticalHeader().setVisible(False)

        for i, w in enumerate(anchos):
            tbl.setColumnWidth(i, w)

        self._llenar_tabla_cuentas(tbl, ventas)

        tbl_wrapper = QWidget()
        tbl_wrapper.setStyleSheet("background: white;")
        tw_lay = QVBoxLayout(tbl_wrapper)
        tw_lay.setContentsMargins(20, 10, 20, 10)
        tw_lay.addWidget(tbl)
        dlg_layout.addWidget(tbl_wrapper, 1)

        # Doble clic para ver detalle
        def ver_detalle_factura(row_idx, _col):
            if row_idx < 0:
                return
            id_venta = tbl.item(row_idx, 0).data(Qt.UserRole)
            numero_factura = tbl.item(row_idx, 0).text()
            total_val = float(
                tbl.item(row_idx, 3).text().replace('$', '').replace(',', '')
            )
            saldo_val = float(
                tbl.item(row_idx, 5).text().replace('$', '').replace(',', '')
            )
            self._abrir_detalle_factura(
                id_venta, numero_factura, total_val, saldo_val,
                dialog, tbl, totales_widget,
            )

        tbl.cellDoubleClicked.connect(ver_detalle_factura)

        # Botón actualizar
        btn_actualizar.clicked.connect(
            lambda: self._actualizar_tabla_cuentas(tbl, totales_widget, ventas)
        )

        # Botones inferiores
        btn_frame = QWidget()
        btn_frame.setStyleSheet("background: white;")
        btn_lay = QHBoxLayout(btn_frame)
        btn_lay.setContentsMargins(20, 20, 20, 20)

        def registrar_cobro():
            row = tbl.currentRow()
            if row < 0:
                QMessageBox.warning(dialog, "Advertencia", "Seleccione una factura")
                return
            id_venta = tbl.item(row, 0).data(Qt.UserRole)
            numero_factura = tbl.item(row, 0).text()
            total_val = float(
                tbl.item(row, 3).text().replace('$', '').replace(',', '')
            )
            saldo_val = float(
                tbl.item(row, 5).text().replace('$', '').replace(',', '')
            )
            self._abrir_detalle_factura(
                id_venta, numero_factura, total_val, saldo_val,
                dialog, tbl, totales_widget,
            )

        btn_cobro = ActionButton(
            text="💰 Registrar Cobro",
            bg='#059669', fg='white',
            border_color='#059669',
            command=registrar_cobro,
        )
        btn_lay.addWidget(btn_cobro)

        btn_clientes = ActionButton(
            text="📊 Ver por Cliente",
            bg=COLORS['primary'], fg='white',
            border_color=COLORS['primary'],
            command=lambda: self._ver_resumen_clientes(),
        )
        btn_lay.addWidget(btn_clientes)

        btn_lay.addStretch()

        btn_cerrar = ActionButton(
            text="Cerrar",
            bg='#6B7280', fg='white',
            border_color='#6B7280',
            command=dialog.accept,
        )
        btn_lay.addWidget(btn_cerrar)

        dlg_layout.addWidget(btn_frame)
        dialog.show()

    # ---- helpers for the accounts table ----

    def _llenar_tabla_cuentas(self, tbl, ventas):
        """Llena la tabla de cuentas por cobrar con datos."""
        tbl.setRowCount(0)
        for venta in ventas:
            estado_emoji = {
                'PENDIENTE': '⏳',
                'PARCIAL': '🟡',
                'PAGADO': '✅',
                'CREDITO_A_FAVOR': '💠',
            }.get(venta['estado_pago'], '')
            estado_txt = f"{estado_emoji} {venta['estado_pago']}"
            credito = venta.get('credito_a_favor') or 0
            try:
                credito_val = float(credito)
            except (TypeError, ValueError):
                credito_val = 0
            if credito_val > 0:
                estado_txt += f" (crédito ${credito_val:,.0f})"

            valores = (
                venta['numero_factura'],
                venta['fecha'][:10] if venta['fecha'] else '',
                venta['cliente_nombre'][:25],
                f"${venta['total']:,.0f}",
                f"${venta['monto_pagado']:,.0f}",
                f"${venta['saldo_pendiente']:,.0f}",
                estado_txt,
                f"{venta['dias_transcurridos']}",
            )

            if venta['dias_transcurridos'] > 60:
                bg_c = QColor('#fee2e2')
                fg_c = QColor('#991b1b')
            elif venta['dias_transcurridos'] > 30:
                bg_c = QColor('#fef3c7')
                fg_c = QColor('#92400e')
            else:
                bg_c = QColor('white')
                fg_c = QColor('black')

            row = tbl.rowCount()
            tbl.insertRow(row)
            for ci, val in enumerate(valores):
                it = QTableWidgetItem(str(val))
                it.setBackground(bg_c)
                it.setForeground(fg_c)
                it.setTextAlignment(Qt.AlignCenter)
                if ci == 0:
                    it.setData(Qt.UserRole, venta['id'])
                tbl.setItem(row, ci, it)

    def _actualizar_tabla_cuentas(self, tbl, totales_widget, ventas_anteriores):
        """Actualiza la tabla de cuentas por cobrar"""
        try:
            ventas = self.cuentas_service.obtener_ventas_credito_pendientes()
            self._llenar_tabla_cuentas(tbl, ventas)

            total_deuda = sum(v['saldo_pendiente'] for v in ventas)
            total_pagado = sum(v['monto_pagado'] for v in ventas)

            totales_widget.lbl_total_deuda.setText(
                f"Total por Cobrar: ${total_deuda:,.0f}"
            )
            totales_widget.lbl_total_pagado.setText(
                f"Total Abonado: ${total_pagado:,.0f}"
            )
            totales_widget.lbl_facturas.setText(
                f"Facturas Pendientes: {len(ventas)}"
            )

            # Actualizar también el dashboard principal
            self.cargar_datos()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al actualizar: {e}")

    # ------------------------------------------------------------------
    # Modal Cobro Dashboard
    # ------------------------------------------------------------------

    def _abrir_modal_cobro_dashboard(self, id_venta, numero_factura, total, saldo,
                                     parent_window, tbl, totales_widget):
        """Abre modal para registrar cobro desde el dashboard"""
        from repositories.abonos_ventas_repo import AbonosVentasRepository
        from database import DatabaseManager

        try:
            db = DatabaseManager()
            abonos_repo = AbonosVentasRepository(db.db_name)

            dialog = QDialog(parent_window)
            dialog.setWindowTitle("Registrar Cobro")
            dialog.resize(550, 400)
            dialog.setWindowModality(Qt.WindowModal)

            dlg_layout = QVBoxLayout(dialog)

            # Info de factura
            info_group = QGroupBox("Información de Factura")
            info_group.setFont(make_font(FONTS['body_bold']))
            ig_lay = QVBoxLayout(info_group)

            ig_lay.addWidget(QLabel(f"Factura: {numero_factura}"))
            ig_lay.addWidget(QLabel(f"Total: ${total:,.0f}"))

            saldo_actual = [saldo]

            saldo_label = QLabel(f"Saldo Pendiente: ${saldo_actual[0]:,.0f}")
            saldo_label.setFont(QFont('Segoe UI', 12, QFont.Bold))
            saldo_label.setStyleSheet("color: #DC2626;")
            ig_lay.addWidget(saldo_label)

            dlg_layout.addWidget(info_group)

            # Formulario
            form_group = QGroupBox("Datos del Cobro")
            form_group.setFont(make_font(FONTS['body_bold']))
            form_lay = QGridLayout(form_group)

            form_lay.addWidget(QLabel("Monto:"), 0, 0)
            monto_entry = QLineEdit()
            monto_entry.setFont(make_font(FONTS['body']))
            form_lay.addWidget(monto_entry, 0, 1)
            monto_entry.setFocus()

            btn_pagar_todo = ActionButton(
                text="Pagar Todo", bg='#10B981', fg='white',
                border_color='#10B981', font_size=9,
            )
            btn_pagar_todo.clicked.connect(
                lambda: monto_entry.setText(str(int(saldo_actual[0])))
            )
            form_lay.addWidget(btn_pagar_todo, 0, 2)

            form_lay.addWidget(QLabel("Tipo de Pago:"), 1, 0)
            tipo_combo = QComboBox()
            tipo_combo.addItems([
                "Efectivo", "Transferencia", "Cheque",
                "Tarjeta Débito", "Tarjeta Crédito", "Otro",
            ])
            form_lay.addWidget(tipo_combo, 1, 1)

            form_lay.addWidget(QLabel("Nº Comprobante:"), 2, 0)
            comprobante_entry = QLineEdit()
            form_lay.addWidget(comprobante_entry, 2, 1)

            dlg_layout.addWidget(form_group, 1)

            def guardar_cobro():
                try:
                    monto = float(monto_entry.text().strip())

                    if monto <= 0:
                        QMessageBox.warning(
                            dialog, "Advertencia",
                            "El monto debe ser mayor a cero",
                        )
                        return

                    if monto > saldo_actual[0]:
                        QMessageBox.warning(
                            dialog, "Advertencia",
                            f"El monto no puede exceder el saldo (${saldo_actual[0]:,.0f})",
                        )
                        return

                    abono = AbonoVenta(
                        id_venta=id_venta,
                        monto_abono=monto,
                        fecha_abono=datetime.now().strftime('%Y-%m-%d'),
                        tipo_pago=tipo_combo.currentText(),
                        numero_comprobante=comprobante_entry.text() or None,
                        usuario=(
                            self.auth.usuario_actual.username
                            if self.auth.usuario_actual else "Sistema"
                        ),
                        observaciones=None,
                    )

                    abonos_repo.crear_abono(abono)
                    saldo_actual[0] -= monto

                    QMessageBox.information(
                        dialog, "Éxito",
                        f"Cobro de ${monto:,.0f} registrado\n"
                        f"Nuevo saldo: ${saldo_actual[0]:,.0f}",
                    )

                    self._actualizar_tabla_cuentas(tbl, totales_widget, [])

                    if saldo_actual[0] <= 0:
                        dialog.accept()
                    else:
                        saldo_label.setText(
                            f"Saldo Pendiente: ${saldo_actual[0]:,.0f}"
                        )
                        monto_entry.clear()
                        comprobante_entry.clear()
                        monto_entry.setFocus()

                except ValueError:
                    QMessageBox.critical(
                        dialog, "Error", "Ingrese un monto válido"
                    )

            btn_row = QHBoxLayout()
            btn_guardar = ActionButton(
                text="💾 Guardar", bg='#059669', fg='white',
                border_color='#059669', command=guardar_cobro,
            )
            btn_row.addWidget(btn_guardar)
            btn_row.addStretch()
            btn_cancelar = ActionButton(
                text="Cancelar", bg='#DC2626', fg='white',
                border_color='#DC2626', command=dialog.reject,
            )
            btn_row.addWidget(btn_cancelar)

            dlg_layout.addLayout(btn_row)
            dialog.show()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al abrir modal: {e}")

    # ------------------------------------------------------------------
    # Detalle Factura
    # ------------------------------------------------------------------

    def _abrir_detalle_factura(self, id_venta, numero_factura, total, saldo,
                               parent_window, tbl, totales_widget):
        """Abre ventana con detalles de la factura y permite registrar cobro"""
        from repositories.abonos_ventas_repo import AbonosVentasRepository
        from database import DatabaseManager

        try:
            db = DatabaseManager()
            abonos_repo = AbonosVentasRepository(db.db_name)

            # Obtener detalles de la venta directamente de la BD
            conn = db.conectar()
            cursor = conn.cursor()

            cursor.execute('''
                SELECT v.*, c.nombre as cliente_nombre
                FROM ventas v
                LEFT JOIN clientes c ON v.cliente_id = c.id
                WHERE v.id = ?
            ''', (id_venta,))

            venta = cursor.fetchone()
            if not venta:
                conn.close()
                QMessageBox.critical(self, "Error", "No se pudo obtener la venta")
                return

            venta_completa = dict(venta)

            cursor.execute('''
                SELECT
                    dv.id as detalle_id,
                    dv.producto_id,
                    dv.cantidad,
                    dv.precio_unitario,
                    dv.descuento,
                    dv.subtotal,
                    dv.iva,
                    dv.tipo_unidad,
                    p.codigo_barras as codigo_producto,
                    p.nombre as nombre_producto
                FROM detalle_ventas dv
                JOIN productos p ON dv.producto_id = p.id
                WHERE dv.venta_id = ?
            ''', (id_venta,))

            detalles = [dict(row) for row in cursor.fetchall()]
            venta_completa['detalles'] = detalles
            conn.close()

            # Crear ventana de detalles
            ventana = QDialog(parent_window)
            ventana.setWindowTitle(f"Detalles de Factura {numero_factura}")
            ventana.resize(850, 700)
            ventana.setWindowModality(Qt.WindowModal)

            dlg_layout = QVBoxLayout(ventana)
            dlg_layout.setContentsMargins(0, 0, 0, 0)
            dlg_layout.setSpacing(0)

            # Header con info general
            header = QFrame()
            header.setStyleSheet(f"background: {COLORS['primary']};")
            h_lay = QVBoxLayout(header)
            h_lay.setContentsMargins(20, 15, 20, 15)

            h_title = QLabel(f"📄 Factura {numero_factura}")
            h_title.setFont(QFont('Segoe UI', 18, QFont.Bold))
            h_title.setStyleSheet("color: white; background: transparent;")
            h_lay.addWidget(h_title)

            h_sub = QLabel(
                f"Cliente: {venta_completa['cliente_nombre']}  •  "
                f"Fecha: {venta_completa['fecha'][:10]}"
            )
            h_sub.setFont(make_font(FONTS['body']))
            h_sub.setStyleSheet("color: white; background: transparent;")
            h_lay.addWidget(h_sub)

            dlg_layout.addWidget(header)

            # Frame de totales
            info_widget = QWidget()
            info_widget.setStyleSheet("background: #F3F4F6;")
            info_row = QHBoxLayout(info_widget)
            info_row.setContentsMargins(20, 15, 20, 15)

            def _add_info_pair(label_text, value_text,
                               label_color='black', value_color='black',
                               value_bold=False):
                l = QLabel(label_text)
                l.setFont(make_font(FONTS['body_bold']))
                l.setStyleSheet(
                    f"color: {label_color}; background: transparent;"
                )
                info_row.addWidget(l)
                v = QLabel(value_text)
                if value_bold:
                    v.setFont(QFont('Segoe UI', 12, QFont.Bold))
                else:
                    v.setFont(make_font(FONTS['body']))
                v.setStyleSheet(
                    f"color: {value_color}; background: transparent;"
                )
                info_row.addWidget(v)
                return v

            _add_info_pair("Total:", f"${total:,.0f}")
            _add_info_pair(
                "Pagado:",
                f"${venta_completa.get('monto_pagado', 0):,.0f}",
                label_color='#059669', value_color='#059669',
            )
            saldo_label = _add_info_pair(
                "Saldo:", f"${saldo:,.0f}",
                label_color='#DC2626', value_color='#DC2626',
                value_bold=True,
            )
            info_row.addStretch()

            dlg_layout.addWidget(info_widget)

            # Productos vendidos
            prod_group = QGroupBox("Productos de la Factura")
            prod_group.setFont(make_font(FONTS['body_bold']))
            pg_lay = QVBoxLayout(prod_group)

            cols_prod = ('Código', 'Producto', 'Cantidad', 'Tipo', 'Precio Unit.', 'Subtotal')
            anchos_prod = [100, 250, 80, 90, 100, 100]

            tree_productos = QTableWidget()
            tree_productos.setColumnCount(len(cols_prod))
            tree_productos.setHorizontalHeaderLabels(cols_prod)
            tree_productos.setSelectionBehavior(QAbstractItemView.SelectRows)
            tree_productos.setEditTriggers(QAbstractItemView.NoEditTriggers)
            tree_productos.horizontalHeader().setStretchLastSection(True)
            tree_productos.verticalHeader().setVisible(False)

            for i, w in enumerate(anchos_prod):
                tree_productos.setColumnWidth(i, w)

            for detalle in venta_completa.get('detalles', []):
                valores = (
                    detalle.get('codigo_producto', '-'),
                    detalle.get('nombre_producto', '-'),
                    f"{detalle.get('cantidad', 0)}",
                    detalle.get('tipo_unidad', 'Unidad') or 'Unidad',
                    f"${detalle.get('precio_unitario', 0):,.0f}",
                    f"${detalle.get('subtotal', 0):,.0f}",
                )
                row = tree_productos.rowCount()
                tree_productos.insertRow(row)
                for ci, val in enumerate(valores):
                    it = QTableWidgetItem(str(val))
                    if ci != 1:
                        it.setTextAlignment(Qt.AlignCenter)
                    tree_productos.setItem(row, ci, it)

            pg_lay.addWidget(tree_productos)
            dlg_layout.addWidget(prod_group)

            # Historial de abonos
            abonos_group = QGroupBox("Historial de Abonos")
            abonos_group.setFont(make_font(FONTS['body_bold']))
            ag_lay = QVBoxLayout(abonos_group)

            cols_abonos = ('Fecha', 'Monto', 'Tipo Pago', 'Comprobante', 'Usuario')
            anchos_abonos = [100, 100, 120, 120, 100]

            tree_abonos = QTableWidget()
            tree_abonos.setColumnCount(len(cols_abonos))
            tree_abonos.setHorizontalHeaderLabels(cols_abonos)
            tree_abonos.setSelectionBehavior(QAbstractItemView.SelectRows)
            tree_abonos.setEditTriggers(QAbstractItemView.NoEditTriggers)
            tree_abonos.horizontalHeader().setStretchLastSection(True)
            tree_abonos.verticalHeader().setVisible(False)

            for i, w in enumerate(anchos_abonos):
                tree_abonos.setColumnWidth(i, w)

            ag_lay.addWidget(tree_abonos)
            dlg_layout.addWidget(abonos_group)

            # Variable para el saldo actual
            saldo_actual = [saldo]

            def cargar_abonos():
                tree_abonos.setRowCount(0)
                abonos = abonos_repo.obtener_abonos_factura(id_venta)

                total_abonado = 0
                for abono in abonos:
                    valores = (
                        abono['fecha_abono'][:10] if abono.get('fecha_abono') else '-',
                        f"${abono['monto_abono']:,.0f}",
                        abono.get('tipo_pago', '-'),
                        abono.get('numero_comprobante', '-'),
                        abono.get('usuario', '-'),
                    )
                    r = tree_abonos.rowCount()
                    tree_abonos.insertRow(r)
                    for ci, val in enumerate(valores):
                        it = QTableWidgetItem(str(val))
                        it.setTextAlignment(Qt.AlignCenter)
                        tree_abonos.setItem(r, ci, it)
                    total_abonado += abono['monto_abono']

                if not abonos:
                    r = tree_abonos.rowCount()
                    tree_abonos.insertRow(r)
                    it = QTableWidgetItem("Sin abonos registrados")
                    it.setTextAlignment(Qt.AlignCenter)
                    tree_abonos.setItem(r, 1, it)

                # Actualizar el total pagado desde la BD
                conn2 = db.conectar()
                cursor2 = conn2.cursor()
                cursor2.execute(
                    'SELECT COALESCE(monto_pagado, 0) as pagado FROM ventas WHERE id = ?',
                    (id_venta,),
                )
                row_data = cursor2.fetchone()
                monto_pagado_actual = row_data['pagado'] if row_data else total_abonado
                conn2.close()

                # Reconstruir fila de info
                _clear_layout(info_row)

                def _re_add(lt, vt, lc='black', vc='black', vb=False):
                    l = QLabel(lt)
                    l.setFont(make_font(FONTS['body_bold']))
                    l.setStyleSheet(
                        f"color: {lc}; background: transparent;"
                    )
                    info_row.addWidget(l)
                    v = QLabel(vt)
                    if vb:
                        v.setFont(QFont('Segoe UI', 12, QFont.Bold))
                    else:
                        v.setFont(make_font(FONTS['body']))
                    v.setStyleSheet(
                        f"color: {vc}; background: transparent;"
                    )
                    info_row.addWidget(v)
                    return v

                _re_add("Total:", f"${total:,.0f}")
                _re_add(
                    "Pagado:", f"${monto_pagado_actual:,.0f}",
                    lc='#059669', vc='#059669',
                )
                nuevo_saldo = total - monto_pagado_actual
                saldo_actual[0] = nuevo_saldo
                new_saldo_lbl = _re_add(
                    "Saldo:", f"${nuevo_saldo:,.0f}",
                    lc='#DC2626', vc='#DC2626', vb=True,
                )
                info_row.addStretch()

                return new_saldo_lbl

            saldo_label_ref = [None]
            initial_saldo_label = cargar_abonos()
            saldo_label_ref[0] = initial_saldo_label

            # Botones de acción
            btn_frame = QWidget()
            btn_lay = QHBoxLayout(btn_frame)
            btn_lay.setContentsMargins(15, 15, 15, 15)

            def abrir_modal_abono():
                modal_abono = QDialog(ventana)
                modal_abono.setWindowTitle("Registrar Abono")
                modal_abono.resize(450, 380)
                modal_abono.setWindowModality(Qt.WindowModal)

                m_lay = QVBoxLayout(modal_abono)

                # Info
                info_grp = QGroupBox("Información")
                info_grp.setFont(make_font(FONTS['body_bold']))
                ig_lay2 = QVBoxLayout(info_grp)

                saldo_info = QLabel(
                    f"Saldo Pendiente: ${saldo_actual[0]:,.0f}"
                )
                saldo_info.setFont(QFont('Segoe UI', 12, QFont.Bold))
                saldo_info.setStyleSheet("color: #DC2626;")
                ig_lay2.addWidget(saldo_info)
                m_lay.addWidget(info_grp)

                # Formulario
                form = QGridLayout()

                form.addWidget(QLabel("Monto:"), 0, 0)
                monto_entry = QLineEdit()
                monto_entry.setFont(make_font(FONTS['body']))
                form.addWidget(monto_entry, 0, 1)
                monto_entry.setFocus()

                def _formatear_monto_abono():
                    texto = monto_entry.text().replace(',', '').strip()
                    if not texto:
                        return
                    try:
                        valor = int(float(texto))
                        monto_entry.blockSignals(True)
                        pos = monto_entry.cursorPosition()
                        len_antes = len(monto_entry.text())
                        monto_entry.setText(f"{valor:,}")
                        len_despues = len(monto_entry.text())
                        monto_entry.setCursorPosition(
                            max(0, pos + len_despues - len_antes)
                        )
                        monto_entry.blockSignals(False)
                    except ValueError:
                        pass

                monto_entry.textChanged.connect(_formatear_monto_abono)

                btn_pt = ActionButton(
                    text="Pagar Todo", bg='#10B981', fg='white',
                    border_color='#10B981', font_size=9,
                )
                btn_pt.clicked.connect(
                    lambda: monto_entry.setText(f"{int(saldo_actual[0]):,}")
                )
                form.addWidget(btn_pt, 0, 2)

                form.addWidget(QLabel("Tipo de Pago:"), 1, 0)
                tipo_combo = QComboBox()
                tipo_combo.addItems([
                    "Efectivo", "Transferencia", "Cheque",
                    "Tarjeta Débito", "Tarjeta Crédito", "Otro",
                ])
                form.addWidget(tipo_combo, 1, 1, 1, 2)

                form.addWidget(QLabel("Nº Comprobante:"), 2, 0)
                comprobante_entry = QLineEdit()
                form.addWidget(comprobante_entry, 2, 1, 1, 2)

                form.addWidget(QLabel("Observaciones:"), 3, 0, Qt.AlignTop)
                obs_text = QTextEdit()
                obs_text.setFixedHeight(60)
                form.addWidget(obs_text, 3, 1, 1, 2)

                m_lay.addLayout(form)

                def guardar_abono():
                    try:
                        monto = float(
                            monto_entry.text().replace(',', '').strip()
                        )

                        if monto <= 0:
                            QMessageBox.warning(
                                modal_abono, "Advertencia",
                                "El monto debe ser mayor a cero",
                            )
                            return

                        if monto > saldo_actual[0]:
                            QMessageBox.warning(
                                modal_abono, "Advertencia",
                                f"El monto no puede exceder el saldo "
                                f"(${saldo_actual[0]:,.0f})",
                            )
                            return

                        abono = AbonoVenta(
                            id_venta=id_venta,
                            monto_abono=monto,
                            fecha_abono=datetime.now().strftime(
                                '%Y-%m-%d %H:%M:%S'
                            ),
                            tipo_pago=tipo_combo.currentText(),
                            numero_comprobante=comprobante_entry.text() or None,
                            usuario=(
                                self.auth.usuario_actual.username
                                if self.auth.usuario_actual else "Sistema"
                            ),
                            observaciones=(
                                obs_text.toPlainText().strip() or None
                            ),
                        )

                        abonos_repo.crear_abono(abono)

                        nuevo_saldo_label = cargar_abonos()
                        saldo_label_ref[0] = nuevo_saldo_label

                        QMessageBox.information(
                            modal_abono, "Éxito",
                            f"Abono de ${monto:,.0f} registrado\n"
                            f"Nuevo saldo: ${saldo_actual[0]:,.0f}",
                        )

                        self._actualizar_tabla_cuentas(tbl, totales_widget, [])

                        if saldo_actual[0] <= 0:
                            modal_abono.accept()
                            ventana.accept()
                        else:
                            modal_abono.accept()

                    except ValueError:
                        QMessageBox.critical(
                            modal_abono, "Error",
                            "Ingrese un monto válido",
                        )

                btn_modal_row = QHBoxLayout()
                btn_save = ActionButton(
                    text="💾 Guardar", bg='#059669', fg='white',
                    border_color='#059669', command=guardar_abono,
                )
                btn_modal_row.addWidget(btn_save)
                btn_modal_row.addStretch()
                btn_cancel = ActionButton(
                    text="Cancelar", bg='#6B7280', fg='white',
                    border_color='#6B7280', command=modal_abono.reject,
                )
                btn_modal_row.addWidget(btn_cancel)

                m_lay.addLayout(btn_modal_row)
                modal_abono.show()

            # Botones principales
            if saldo > 0:
                btn_abono = ActionButton(
                    text="💰 Registrar Abono", bg='#059669', fg='white',
                    border_color='#059669', bold=True,
                    command=abrir_modal_abono,
                )
                btn_lay.addWidget(btn_abono)

                def agregar_productos_modal():
                    self._abrir_modal_agregar_productos(
                        id_venta, numero_factura, ventana,
                        tbl, totales_widget, saldo_actual,
                        saldo_label_ref[0], tree_productos, venta_completa,
                    )

                btn_agregar = ActionButton(
                    text="➕ Agregar Productos", bg='#F59E0B', fg='white',
                    border_color='#F59E0B', command=agregar_productos_modal,
                )
                btn_lay.addWidget(btn_agregar)

                # --- Editar Producto ---
                def editar_producto_factura():
                    row_sel = tree_productos.currentRow()
                    if row_sel < 0:
                        QMessageBox.warning(ventana, "Advertencia",
                                            "Seleccione un producto para editar")
                        return
                    detalles_act = venta_completa.get('detalles', [])
                    if row_sel >= len(detalles_act):
                        return
                    detalle = detalles_act[row_sel]
                    detalle_id = detalle.get('detalle_id')
                    if not detalle_id:
                        QMessageBox.warning(ventana, "Advertencia",
                                            "No se puede editar este producto")
                        return

                    from PySide6.QtWidgets import QDialog as QDlg, QFormLayout, QSpinBox, QDoubleSpinBox, QDialogButtonBox

                    dlg_edit = QDlg(ventana)
                    dlg_edit.setWindowTitle("Editar Producto")
                    dlg_edit.setMinimumWidth(350)
                    form = QFormLayout(dlg_edit)

                    lbl_prod = QLabel(detalle.get('nombre_producto', ''))
                    lbl_prod.setFont(make_font(FONTS['body_bold']))
                    form.addRow("Producto:", lbl_prod)

                    spin_cant = QSpinBox()
                    spin_cant.setRange(1, 99999)
                    spin_cant.setValue(int(detalle.get('cantidad', 1)))
                    form.addRow("Cantidad:", spin_cant)

                    spin_precio = QDoubleSpinBox()
                    spin_precio.setRange(0, 999999999)
                    spin_precio.setDecimals(0)
                    spin_precio.setPrefix("$")
                    spin_precio.setValue(detalle.get('precio_unitario', 0))
                    form.addRow("Precio Unit.:", spin_precio)

                    btns = QDialogButtonBox(
                        QDialogButtonBox.Save | QDialogButtonBox.Cancel
                    )
                    btns.accepted.connect(dlg_edit.accept)
                    btns.rejected.connect(dlg_edit.reject)
                    form.addRow(btns)

                    if dlg_edit.exec() == QDlg.Accepted:
                        nueva_cant = spin_cant.value()
                        nuevo_precio = spin_precio.value()
                        try:
                            from database import DatabaseManager
                            from repositories.productos_repo import ProductosRepository
                            from repositories.clientes_repo import ClientesRepository
                            from services.ventas_service import VentasService

                            db_edit = DatabaseManager()
                            ventas_service = VentasService(
                                db_edit,
                                ProductosRepository(db_edit),
                                ClientesRepository(db_edit),
                                self.auth,
                            )
                            ok, msg = ventas_service.editar_linea_factura(
                                id_venta, detalle_id, nueva_cant, nuevo_precio,
                            )
                            if not ok:
                                QMessageBox.critical(ventana, "Error", msg)
                                return
                            conn_e = db_edit.conectar()
                            cur_e = conn_e.cursor()
                            self._refrescar_productos_factura(
                                cur_e, id_venta, tree_productos, venta_completa,
                                saldo_actual, saldo_label_ref, tbl, totales_widget,
                            )
                            conn_e.close()
                            QMessageBox.information(ventana, "Éxito", "Producto actualizado")
                        except Exception as ex:
                            traceback.print_exc()
                            QMessageBox.critical(ventana, "Error", f"Error al editar: {ex}")

                btn_editar = ActionButton(
                    text="✏️ Editar Producto", bg='#3B82F6', fg='white',
                    border_color='#3B82F6', command=editar_producto_factura,
                )
                btn_lay.addWidget(btn_editar)

                # --- Eliminar Producto ---
                def eliminar_producto_factura():
                    row_sel = tree_productos.currentRow()
                    if row_sel < 0:
                        QMessageBox.warning(ventana, "Advertencia",
                                            "Seleccione un producto para eliminar")
                        return
                    detalles_act = venta_completa.get('detalles', [])
                    if row_sel >= len(detalles_act):
                        return
                    detalle = detalles_act[row_sel]
                    detalle_id = detalle.get('detalle_id')
                    if not detalle_id:
                        QMessageBox.warning(ventana, "Advertencia",
                                            "No se puede eliminar este producto")
                        return

                    resp = QMessageBox.question(
                        ventana, "Confirmar eliminación",
                        f"¿Eliminar \"{detalle.get('nombre_producto', '')}\" de la factura?",
                        QMessageBox.Yes | QMessageBox.No,
                    )
                    if resp != QMessageBox.Yes:
                        return

                    try:
                        from database import DatabaseManager
                        from repositories.productos_repo import ProductosRepository
                        from repositories.clientes_repo import ClientesRepository
                        from services.ventas_service import VentasService

                        db_del = DatabaseManager()
                        ventas_service = VentasService(
                            db_del,
                            ProductosRepository(db_del),
                            ClientesRepository(db_del),
                            self.auth,
                        )
                        ok, msg = ventas_service.eliminar_linea_factura(
                            id_venta, detalle_id,
                        )
                        if not ok:
                            QMessageBox.critical(ventana, "Error", msg)
                            return
                        conn_d = db_del.conectar()
                        cur_d = conn_d.cursor()
                        self._refrescar_productos_factura(
                            cur_d, id_venta, tree_productos, venta_completa,
                            saldo_actual, saldo_label_ref, tbl, totales_widget,
                        )
                        conn_d.close()
                        QMessageBox.information(ventana, "Éxito", "Producto eliminado")
                    except Exception as ex:
                        traceback.print_exc()
                        QMessageBox.critical(ventana, "Error", f"Error al eliminar: {ex}")

                btn_eliminar_prod = ActionButton(
                    text="🗑️ Eliminar Producto", bg='#EF4444', fg='white',
                    border_color='#EF4444', command=eliminar_producto_factura,
                )
                btn_lay.addWidget(btn_eliminar_prod)

            btn_print = ActionButton(
                text="🖨️ Imprimir", bg=COLORS['primary'], fg='white',
                border_color=COLORS['primary'],
                command=lambda: QMessageBox.information(
                    ventana, "Info", "Funcionalidad en desarrollo"
                ),
            )
            btn_lay.addWidget(btn_print)

            btn_lay.addStretch()

            btn_close = ActionButton(
                text="Cerrar", bg='#6B7280', fg='white',
                border_color='#6B7280', command=ventana.accept,
            )
            btn_lay.addWidget(btn_close)

            dlg_layout.addWidget(btn_frame)
            ventana.show()

        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(
                self, "Error", f"Error al abrir detalles: {e}"
            )

    # ------------------------------------------------------------------
    # Refrescar productos de la factura
    # ------------------------------------------------------------------

    def _refrescar_productos_factura(self, cursor, id_venta, tree_productos,
                                     venta_completa, saldo_actual,
                                     saldo_label_ref, tbl, totales_widget):
        """Refresca la tabla de productos y los totales de la factura"""
        try:
            tree_productos.setRowCount(0)
            cursor.execute('''
                SELECT
                    dv.id as detalle_id,
                    dv.producto_id,
                    dv.cantidad,
                    dv.precio_unitario,
                    dv.descuento,
                    dv.subtotal,
                    dv.iva,
                    dv.tipo_unidad,
                    p.codigo_barras as codigo_producto,
                    p.nombre as nombre_producto
                FROM detalle_ventas dv
                JOIN productos p ON dv.producto_id = p.id
                WHERE dv.venta_id = ?
            ''', (id_venta,))

            detalles = [dict(row) for row in cursor.fetchall()]
            venta_completa['detalles'] = detalles

            for detalle in detalles:
                valores = (
                    detalle.get('codigo_producto', '-'),
                    detalle.get('nombre_producto', '-'),
                    f"{detalle.get('cantidad', 0)}",
                    detalle.get('tipo_unidad', 'Unidad') or 'Unidad',
                    f"${detalle.get('precio_unitario', 0):,.0f}",
                    f"${detalle.get('subtotal', 0):,.0f}",
                )
                r = tree_productos.rowCount()
                tree_productos.insertRow(r)
                for ci, val in enumerate(valores):
                    it = QTableWidgetItem(str(val))
                    if ci != 1:
                        it.setTextAlignment(Qt.AlignCenter)
                    tree_productos.setItem(r, ci, it)

            # Actualizar saldo
            cursor.execute(
                'SELECT total, monto_pagado FROM ventas WHERE id = ?',
                (id_venta,),
            )
            row_data = cursor.fetchone()
            if row_data:
                nuevo_total = row_data[0]
                monto_pagado = row_data[1] or 0
                nuevo_saldo = nuevo_total - monto_pagado
                saldo_actual[0] = nuevo_saldo
                try:
                    saldo_label_ref[0].setText(f"${nuevo_saldo:,.0f}")
                except RuntimeError:
                    pass

            try:
                self._actualizar_tabla_cuentas(tbl, totales_widget, [])
            except RuntimeError:
                pass
        except RuntimeError:
            pass

    # ------------------------------------------------------------------
    # Modal Agregar Productos
    # ------------------------------------------------------------------

    def _abrir_modal_agregar_productos(self, id_venta, numero_factura,
                                       ventana_padre, tree_principal,
                                       totales_widget, saldo_actual,
                                       saldo_label, tree_productos,
                                       venta_completa):
        """Abre modal para agregar productos a la factura existente"""
        from repositories.productos_repo import ProductosRepository
        from database import DatabaseManager
        from unidades_venta_manager import UnidadesVentaManager

        db = DatabaseManager()
        productos_repo = ProductosRepository(db)
        unidades_manager = UnidadesVentaManager(db)

        modal = QDialog(ventana_padre)
        modal.setWindowTitle(f"Agregar Productos a {numero_factura}")
        modal.resize(950, 750)
        modal.setWindowModality(Qt.WindowModal)

        m_layout = QVBoxLayout(modal)
        m_layout.setContentsMargins(0, 0, 0, 0)
        m_layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setStyleSheet("background: #F59E0B;")
        h_lay = QVBoxLayout(header)
        h_lay.setContentsMargins(20, 15, 20, 15)

        h_title = QLabel(
            f"➕ Agregar Productos a Factura {numero_factura}"
        )
        h_title.setFont(QFont('Segoe UI', 16, QFont.Bold))
        h_title.setStyleSheet("color: white; background: transparent;")
        h_lay.addWidget(h_title)
        m_layout.addWidget(header)

        # Búsqueda de productos
        search_widget = QWidget()
        search_widget.setStyleSheet("background: white;")
        search_lay = QHBoxLayout(search_widget)
        search_lay.setContentsMargins(20, 15, 20, 15)

        search_lbl = QLabel("Buscar Producto:")
        search_lbl.setFont(make_font(FONTS['body_bold']))
        search_lay.addWidget(search_lbl)

        search_entry = QLineEdit()
        search_entry.setFont(make_font(FONTS['body']))
        search_entry.setMinimumWidth(300)
        search_entry.setFocus()
        search_lay.addWidget(search_entry)
        search_lay.addStretch()

        m_layout.addWidget(search_widget)

        # Lista de productos
        cols = ('Código', 'Nombre', 'Precio', 'Stock')
        anchos = [120, 350, 100, 80]

        prod_table = QTableWidget()
        prod_table.setColumnCount(len(cols))
        prod_table.setHorizontalHeaderLabels(cols)
        prod_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        prod_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        prod_table.horizontalHeader().setStretchLastSection(True)
        prod_table.verticalHeader().setVisible(False)

        for i, w in enumerate(anchos):
            prod_table.setColumnWidth(i, w)

        prod_wrapper = QWidget()
        prod_wrapper.setStyleSheet("background: white;")
        pw_lay = QVBoxLayout(prod_wrapper)
        pw_lay.setContentsMargins(20, 0, 20, 0)
        pw_lay.addWidget(prod_table)
        m_layout.addWidget(prod_wrapper, 1)

        carrito_temporal = []

        def cargar_productos(criterio=None):
            prod_table.setRowCount(0)
            productos = (
                productos_repo.buscar_productos(criterio)
                if criterio else productos_repo.listar_productos()
            )
            for p in productos:
                if p['stock'] > 0:
                    valores = (
                        p.get('codigo_barras', '-'),
                        p['nombre'][:45],
                        f"${p['precio_venta']:,.0f}",
                        formatear_stock(p['stock'], p.get('permite_decimales')),
                    )
                    r = prod_table.rowCount()
                    prod_table.insertRow(r)
                    for ci, val in enumerate(valores):
                        it = QTableWidgetItem(str(val))
                        if ci != 1:
                            it.setTextAlignment(Qt.AlignCenter)
                        if ci == 0:
                            it.setData(Qt.UserRole, p['id'])
                        prod_table.setItem(r, ci, it)

        search_entry.textChanged.connect(
            lambda text: cargar_productos(text.strip() if text.strip() else None)
        )
        cargar_productos()

        # Variables para unidad y cantidad
        producto_seleccionado = {'producto': None, 'unidades': []}

        # Frame para unidad de venta
        unidad_widget = QWidget()
        unidad_widget.setStyleSheet("background: white;")
        unidad_lay = QHBoxLayout(unidad_widget)
        unidad_lay.setContentsMargins(20, 10, 20, 10)

        unidad_lay.addWidget(QLabel("Unidad de Venta:"))
        unidad_combo = QComboBox()
        unidad_combo.setMinimumWidth(200)
        unidad_lay.addWidget(unidad_combo)

        precio_unidad_label = QLabel("")
        precio_unidad_label.setStyleSheet("color: #059669;")
        unidad_lay.addWidget(precio_unidad_label)
        unidad_lay.addStretch()

        m_layout.addWidget(unidad_widget)

        # Cantidad
        cantidad_widget = QWidget()
        cantidad_widget.setStyleSheet("background: white;")
        cantidad_lay = QHBoxLayout(cantidad_widget)
        cantidad_lay.setContentsMargins(20, 10, 20, 10)

        cantidad_lay.addWidget(QLabel("Cantidad:"))
        cantidad_entry = QLineEdit("1")
        cantidad_entry.setFont(make_font(FONTS['body']))
        cantidad_entry.setFixedWidth(80)
        cantidad_lay.addWidget(cantidad_entry)

        total_label = QLabel("")
        total_label.setFont(make_font(FONTS['body_bold']))
        total_label.setStyleSheet("color: #1565C0;")
        cantidad_lay.addWidget(total_label)

        def actualizar_precio():
            """Actualiza el precio según la unidad y cantidad"""
            try:
                if (not producto_seleccionado['producto']
                        or not unidad_combo.currentText()):
                    return
                cantidad = float(cantidad_entry.text() or 0)
                if cantidad <= 0:
                    return
                nombre_unidad = unidad_combo.currentText()
                unidad_info = next(
                    (u for u in producto_seleccionado['unidades']
                     if u['nombre'] == nombre_unidad), None,
                )
                if unidad_info:
                    precio_unidad = unidad_info['precio']
                    t = precio_unidad * cantidad
                    total_label.setText(f"Total: ${t:,.0f}")
            except Exception:
                pass

        cantidad_entry.textChanged.connect(lambda: actualizar_precio())
        unidad_combo.currentTextChanged.connect(lambda: actualizar_precio())

        def on_producto_seleccionado():
            """Cuando se selecciona un producto, cargar sus unidades"""
            row = prod_table.currentRow()
            if row < 0:
                return
            producto_id = prod_table.item(row, 0).data(Qt.UserRole)
            producto = productos_repo.obtener_por_id(producto_id)
            if not producto:
                return

            producto_seleccionado['producto'] = producto

            unidades = unidades_manager.obtener_unidades_venta_producto(producto)
            precio_base = producto['precio_venta']
            for unidad in unidades:
                unidad['precio'] = precio_base * unidad['factor']

            producto_seleccionado['unidades'] = unidades

            unidad_combo.clear()
            nombres_unidades = [u['nombre'] for u in unidades]
            unidad_combo.addItems(nombres_unidades)

            if nombres_unidades:
                unidad_combo.setCurrentIndex(0)
                precio_primera = unidades[0]['precio']
                precio_unidad_label.setText(f"Precio: ${precio_primera:,.0f}")
                actualizar_precio()

        prod_table.itemSelectionChanged.connect(on_producto_seleccionado)

        def agregar_al_carrito():
            try:
                row = prod_table.currentRow()
                if row < 0:
                    QMessageBox.warning(
                        modal, "Advertencia", "Seleccione un producto"
                    )
                    return

                if not unidad_combo.currentText():
                    QMessageBox.warning(
                        modal, "Advertencia",
                        "Seleccione una unidad de venta",
                    )
                    return

                try:
                    cantidad_venta = float(cantidad_entry.text())
                    if cantidad_venta <= 0:
                        QMessageBox.warning(
                            modal, "Advertencia",
                            "La cantidad debe ser mayor a 0",
                        )
                        return
                except Exception:
                    QMessageBox.warning(
                        modal, "Advertencia",
                        "Ingrese una cantidad válida",
                    )
                    return

                producto = producto_seleccionado['producto']
                if not producto:
                    QMessageBox.warning(
                        modal, "Advertencia", "Seleccione un producto"
                    )
                    return

                nombre_unidad = unidad_combo.currentText()
                unidad_info = next(
                    (u for u in producto_seleccionado['unidades']
                     if u['nombre'] == nombre_unidad), None,
                )

                if not unidad_info:
                    QMessageBox.warning(
                        modal, "Advertencia",
                        "Error al obtener información de la unidad",
                    )
                    return

                factor = unidad_info.get('factor', 1.0)
                cantidad_real = cantidad_venta * factor

                if producto['stock'] < cantidad_real:
                    QMessageBox.warning(
                        modal, "Advertencia",
                        f"Stock insuficiente.\n"
                        f"Disponible: {formatear_stock(producto['stock'], producto.get('permite_decimales'))} "
                        f"{producto.get('unidad_base', 'unidades')}",
                    )
                    return

                precio_unitario = unidad_info['precio']
                precio_base = producto['precio_venta']

                if factor == 1.0:
                    descripcion = f"{producto['nombre']}"
                else:
                    descripcion = (
                        f"{producto['nombre']} "
                        f"({cantidad_venta} {nombre_unidad})"
                    )

                carrito_temporal.append({
                    'producto_id': producto['id'],
                    'nombre': descripcion,
                    'cantidad': cantidad_real,
                    'cantidad_venta': cantidad_venta,
                    'precio_unitario': precio_unitario,
                    'precio_base': precio_base,
                    'tipo_unidad': nombre_unidad,
                    'descuento': 0,
                })

                actualizar_carrito_visual()
                cantidad_entry.setText("1")

            except Exception as e:
                QMessageBox.critical(
                    modal, "Error",
                    f"Error al agregar producto:\n{str(e)}",
                )
                traceback.print_exc()

        btn_agregar = ActionButton(
            text="➕ Agregar al Carrito", bg='#10B981', fg='white',
            border_color='#10B981', command=agregar_al_carrito,
        )
        cantidad_lay.addWidget(btn_agregar)

        lbl_carrito = QLabel("Productos en carrito: 0")
        lbl_carrito.setFont(make_font(FONTS['body_bold']))
        lbl_carrito.setStyleSheet("color: #059669;")
        cantidad_lay.addWidget(lbl_carrito)
        cantidad_lay.addStretch()

        m_layout.addWidget(cantidad_widget)

        # Tabla de carrito
        cart_group = QGroupBox("Carrito de Compra")
        cart_group.setFont(make_font(FONTS['body_bold']))
        cart_group.setStyleSheet("QGroupBox { background: white; }")
        cg_lay = QVBoxLayout(cart_group)

        cols_carrito = ('Producto', 'Cant.', 'Precio Unit.', 'Subtotal')
        anchos_carrito = [350, 80, 100, 100]

        tree_carrito = QTableWidget()
        tree_carrito.setColumnCount(len(cols_carrito))
        tree_carrito.setHorizontalHeaderLabels(cols_carrito)
        tree_carrito.setSelectionBehavior(QAbstractItemView.SelectRows)
        tree_carrito.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tree_carrito.horizontalHeader().setStretchLastSection(True)
        tree_carrito.verticalHeader().setVisible(False)
        tree_carrito.setMaximumHeight(150)

        for i, w in enumerate(anchos_carrito):
            tree_carrito.setColumnWidth(i, w)

        cg_lay.addWidget(tree_carrito)

        total_carrito_label = QLabel("Total: $0")
        total_carrito_label.setFont(QFont('Segoe UI', 13, QFont.Bold))
        total_carrito_label.setStyleSheet(
            "color: #1565C0; background: transparent;"
        )
        total_carrito_label.setAlignment(Qt.AlignCenter)
        cg_lay.addWidget(total_carrito_label)

        cart_wrapper = QWidget()
        cart_wrapper.setStyleSheet("background: white;")
        cw_lay = QVBoxLayout(cart_wrapper)
        cw_lay.setContentsMargins(20, 5, 20, 5)
        cw_lay.addWidget(cart_group)
        m_layout.addWidget(cart_wrapper)

        def actualizar_carrito_visual():
            """Actualiza la tabla visual del carrito"""
            tree_carrito.setRowCount(0)
            total_general = 0

            for _idx, item_data in enumerate(carrito_temporal):
                cant_mostrar = item_data.get(
                    'cantidad_venta', item_data['cantidad']
                )
                precio_unit = item_data['precio_unitario']
                subtotal = precio_unit * cant_mostrar

                valores = (
                    item_data['nombre'][:45],
                    (f"{cant_mostrar:.1f}"
                     if cant_mostrar != int(cant_mostrar)
                     else f"{int(cant_mostrar)}"),
                    f"${precio_unit:,.0f}",
                    f"${subtotal:,.0f}",
                )
                r = tree_carrito.rowCount()
                tree_carrito.insertRow(r)
                for ci, val in enumerate(valores):
                    it = QTableWidgetItem(str(val))
                    if ci != 0:
                        it.setTextAlignment(Qt.AlignCenter)
                    tree_carrito.setItem(r, ci, it)
                total_general += subtotal

            total_carrito_label.setText(f"Total: ${total_general:,.0f}")
            lbl_carrito.setText(
                f"Productos en carrito: {len(carrito_temporal)}"
            )

        # Botones del carrito
        cart_btn_widget = QWidget()
        cart_btn_widget.setStyleSheet("background: white;")
        cart_btn_lay = QHBoxLayout(cart_btn_widget)
        cart_btn_lay.setContentsMargins(20, 5, 20, 5)

        def limpiar_carrito():
            """Limpia todos los productos del carrito"""
            carrito_temporal.clear()
            actualizar_carrito_visual()

        def eliminar_seleccionado():
            """Elimina el producto seleccionado del carrito"""
            row = tree_carrito.currentRow()
            if row < 0:
                QMessageBox.warning(
                    modal, "Advertencia",
                    "Seleccione un producto para eliminar",
                )
                return
            if 0 <= row < len(carrito_temporal):
                carrito_temporal.pop(row)
                actualizar_carrito_visual()

        btn_eliminar = ActionButton(
            text="❌ Eliminar Seleccionado", bg='#F59E0B', fg='white',
            border_color='#F59E0B', command=eliminar_seleccionado,
        )
        cart_btn_lay.addWidget(btn_eliminar)

        btn_limpiar = ActionButton(
            text="🗑️ Limpiar Todo", bg='#EF4444', fg='white',
            border_color='#EF4444', command=limpiar_carrito,
        )
        cart_btn_lay.addWidget(btn_limpiar)
        cart_btn_lay.addStretch()

        m_layout.addWidget(cart_btn_widget)

        def guardar_productos():
            if not carrito_temporal:
                QMessageBox.warning(
                    modal, "Advertencia",
                    "Agregue productos al carrito",
                )
                return

            items = []
            for item_data in carrito_temporal:
                items.append({
                    'producto_id': item_data['producto_id'],
                    'cantidad': item_data['cantidad'],
                    'precio_unitario': item_data.get('precio_base', item_data['precio_unitario']),
                    'descuento': item_data.get('descuento', 0),
                    'tipo_unidad': item_data.get('tipo_unidad', 'Unidad'),
                })

            try:
                from services.ventas_service import VentasService
                from repositories.productos_repo import ProductosRepository
                from repositories.clientes_repo import ClientesRepository
                from auth import AuthManager

                ventas_service = VentasService(
                    db, productos_repo, ClientesRepository(db), self.auth,
                )

                exito, mensaje = ventas_service.agregar_productos_a_factura(
                    id_venta, items,
                )

                if exito:
                    modal.accept()

                    try:
                        conn3 = db.conectar()
                        cursor3 = conn3.cursor()

                        self._refrescar_productos_factura(
                            cursor3, id_venta, tree_productos, venta_completa,
                            saldo_actual, [saldo_label], tree_principal,
                            totales_widget,
                        )
                        conn3.close()
                    except RuntimeError:
                        pass

                    QMessageBox.information(self, "Éxito", mensaje)
                else:
                    QMessageBox.critical(modal, "Error", mensaje)

            except Exception as e:
                traceback.print_exc()
                QMessageBox.critical(
                    modal, "Error",
                    f"Error al agregar productos: {e}",
                )

        # Botones principales
        main_btn_widget = QWidget()
        main_btn_widget.setStyleSheet("background: white;")
        main_btn_lay = QHBoxLayout(main_btn_widget)
        main_btn_lay.setContentsMargins(20, 10, 20, 10)

        btn_guardar = QPushButton("💾 GUARDAR CAMBIOS")
        btn_guardar.setFont(QFont('Segoe UI', 12, QFont.Bold))
        btn_guardar.setCursor(Qt.PointingHandCursor)
        btn_guardar.setStyleSheet("""
            QPushButton {
                background: #10B981; color: white; border: none;
                border-radius: 6px; padding: 12px 50px;
            }
            QPushButton:hover { background: #059669; }
        """)
        btn_guardar.clicked.connect(guardar_productos)
        main_btn_lay.addWidget(btn_guardar, 1)

        btn_cancelar = QPushButton("✕ CANCELAR")
        btn_cancelar.setFont(QFont('Segoe UI', 11, QFont.Bold))
        btn_cancelar.setCursor(Qt.PointingHandCursor)
        btn_cancelar.setStyleSheet("""
            QPushButton {
                background: #6B7280; color: white; border: none;
                border-radius: 6px; padding: 12px 50px;
            }
            QPushButton:hover { background: #4B5563; }
        """)
        btn_cancelar.clicked.connect(modal.reject)
        main_btn_lay.addWidget(btn_cancelar, 1)

        m_layout.addWidget(main_btn_widget)
        modal.show()

    # ------------------------------------------------------------------
    # Resumen por Cliente
    # ------------------------------------------------------------------

    def _ver_resumen_clientes(self):
        """Muestra resumen de cuentas por cobrar agrupadas por cliente"""
        if not self.cuentas_service:
            return

        try:
            resumen = self.cuentas_service.obtener_resumen_cuentas_por_cobrar()

            if not resumen:
                QMessageBox.information(
                    self, "Información", "No hay cuentas por cobrar"
                )
                return

            dialog = QDialog(self)
            dialog.setWindowTitle("Resumen por Cliente")
            dialog.resize(800, 500)
            dialog.setWindowModality(Qt.WindowModal)

            dlg_layout = QVBoxLayout(dialog)
            dlg_layout.setContentsMargins(0, 0, 0, 0)
            dlg_layout.setSpacing(0)

            # Header
            header_lbl = QLabel(
                "📊 Cuentas por Cobrar - Resumen por Cliente"
            )
            header_lbl.setFont(make_font(FONTS['large']))
            header_lbl.setStyleSheet(
                f"background: {COLORS['primary']}; color: white; padding: 15px 20px;"
            )
            dlg_layout.addWidget(header_lbl)

            # Tabla
            columnas = (
                'Cliente', 'Facturas', 'Total Deuda',
                '0-30 días', '31-60 días', '+60 días', 'Estado',
            )

            tbl = QTableWidget()
            tbl.setColumnCount(len(columnas))
            tbl.setHorizontalHeaderLabels(columnas)
            tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
            tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
            tbl.horizontalHeader().setStretchLastSection(True)
            tbl.verticalHeader().setVisible(False)

            for i in range(len(columnas)):
                tbl.setColumnWidth(i, 100)

            for cliente in resumen:
                valores = (
                    cliente['nombre_cliente'][:30],
                    str(cliente['facturas_pendientes']),
                    f"${cliente['total_deuda']:,.0f}",
                    f"${cliente['deuda_30']:,.0f}",
                    f"${cliente['deuda_60']:,.0f}",
                    f"${cliente['deuda_90']:,.0f}",
                    cliente['estado_vencimiento'],
                )
                r = tbl.rowCount()
                tbl.insertRow(r)
                for ci, val in enumerate(valores):
                    it = QTableWidgetItem(str(val))
                    it.setTextAlignment(Qt.AlignCenter)
                    tbl.setItem(r, ci, it)

            tbl_wrapper = QWidget()
            tw_lay = QVBoxLayout(tbl_wrapper)
            tw_lay.setContentsMargins(20, 10, 20, 10)
            tw_lay.addWidget(tbl)
            dlg_layout.addWidget(tbl_wrapper, 1)

            btn_cerrar = ActionButton(
                text="Cerrar", bg='#6B7280', fg='white',
                border_color='#6B7280', command=dialog.accept,
            )
            btn_cerrar.setFixedWidth(120)

            btn_widget = QWidget()
            bw_lay = QHBoxLayout(btn_widget)
            bw_lay.setContentsMargins(0, 10, 0, 10)
            bw_lay.addStretch()
            bw_lay.addWidget(btn_cerrar)
            bw_lay.addStretch()
            dlg_layout.addWidget(btn_widget)

            dialog.show()

        except Exception as e:
            QMessageBox.critical(
                self, "Error", f"Error al cargar resumen: {e}"
            )
