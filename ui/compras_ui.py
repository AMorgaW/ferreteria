# -*- coding: utf-8 -*-
"""
Interfaz para Registro de Compras a Proveedores (PySide6)
Sistema de compras completo con múltiples productos por compra
"""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                                QLabel, QPushButton, QFrame, QScrollArea,
                                QTableWidget, QTableWidgetItem, QHeaderView,
                                QDialog, QMessageBox, QLineEdit, QComboBox,
                                QCheckBox, QRadioButton, QSpinBox, QDoubleSpinBox,
                                QListWidget, QListWidgetItem, QCompleter,
                                QSizePolicy, QAbstractItemView, QButtonGroup,
                                QGroupBox)
from PySide6.QtCore import Qt, QSize, QStringListModel, Signal, QTimer, QThreadPool
from PySide6.QtGui import QFont, QColor
from ui_config import COLORS, FONTS, make_font
from ui.widgets import ShadowCard, KpiCard, ActionButton
from models import Abono
from datetime import datetime
from packaging_conversion import (
    PACKAGING_BLOCKED,
    PackagingConversionBlocked,
    PackagingError,
    as_decimal,
    get_base_units_per_package,
)
from repositories.product_barcodes_repo import PACKAGE_ROLE_BASE_UNIT, PACKAGE_ROLE_FULL_PACKAGE
from services.compras_service import ComprasService
from services.purchase_cart import PurchaseCart, receipt_finalize_allowed
from ui.async_worker import FunctionWorker


class AutocompleteEntry(QWidget):
    """Widget personalizado de Entry con autocompletado usando QLineEdit + QListWidget popup"""

    selectionMade = Signal()

    def __init__(self, parent=None, values=None, **kwargs):
        super().__init__(parent)
        self.values = values or []
        self.filtered_values = []
        self.callback = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Entry principal
        self.entry = QLineEdit()
        self.entry.setStyleSheet(f"""
            QLineEdit {{
                border: 1px solid {COLORS['border_input']}; border-radius: 6px;
                padding: 6px 10px; background: {COLORS['bg_primary']}; color: {COLORS['text_primary']};
                font-size: 10pt;
            }}
            QLineEdit:focus {{ border-color: {COLORS['primary']}; }}
        """)
        layout.addWidget(self.entry, 1)

        # Botón de flecha para desplegar
        self.arrow_btn = QPushButton("\u25bc")
        self.arrow_btn.setFixedWidth(30)
        self.arrow_btn.setCursor(Qt.PointingHandCursor)
        self.arrow_btn.setStyleSheet(f"""
            QPushButton {{
                border: 1px solid {COLORS['border_input']}; border-radius: 4px;
                background: {COLORS['bg_secondary']}; font-size: 8pt; padding: 4px;
            }}
            QPushButton:hover {{ background: {COLORS['bg_hover']}; }}
        """)
        self.arrow_btn.clicked.connect(self.toggle_listbox)
        layout.addWidget(self.arrow_btn)

        # Popup listbox para sugerencias
        self.listbox = QListWidget()
        self.listbox.setWindowFlags(Qt.Popup)
        self.listbox.setStyleSheet(f"""
            QListWidget {{
                border: 1px solid {COLORS['border_input']}; background: {COLORS['bg_primary']};
                font-size: 10pt; color: {COLORS['text_primary']};
            }}
            QListWidget::item {{ padding: 6px 10px; }}
            QListWidget::item:hover {{ background: {COLORS['primary_light']}; }}
            QListWidget::item:selected {{ background: {COLORS['primary_hover_light']}; color: {COLORS['text_primary']}; }}
        """)
        self.listbox.setMaximumHeight(200)
        self.listbox.hide()

        self.listbox_visible = False

        # Bindings
        self.entry.textChanged.connect(self.on_keyrelease)
        self.listbox.itemClicked.connect(self.on_select_item)
        self.entry.returnPressed.connect(self.on_enter)

    def toggle_listbox(self):
        if self.listbox_visible:
            self.hide_listbox()
        else:
            self.show_all_items()

    def show_all_items(self):
        self.listbox.clear()
        for value in self.values:
            self.listbox.addItem(value)
        self.show_listbox()
        self.entry.setFocus()

    def on_keyrelease(self, text=None):
        texto = self.entry.text().strip()
        if not texto:
            self.hide_listbox()
            return

        texto_lower = texto.lower()
        self.filtered_values = [v for v in self.values if texto_lower in v.lower()]

        if self.filtered_values:
            self.listbox.clear()
            for value in self.filtered_values:
                self.listbox.addItem(value)
            self.show_listbox()
        else:
            self.hide_listbox()

    def on_select_item(self, item):
        value = item.text()
        self.entry.setText(value)
        self.hide_listbox()
        if self.callback:
            self.callback()

    def on_enter(self):
        if self.listbox_visible and self.listbox.count() > 0:
            if not self.listbox.currentItem():
                self.listbox.setCurrentRow(0)
            item = self.listbox.currentItem()
            if item:
                self.on_select_item(item)

    def show_listbox(self):
        pos = self.entry.mapToGlobal(self.entry.rect().bottomLeft())
        self.listbox.setGeometry(pos.x(), pos.y(), self.width(), 200)
        self.listbox.show()
        self.listbox.raise_()
        self.listbox_visible = True
        self.arrow_btn.setText("\u25b2")

    def hide_listbox(self):
        self.listbox.hide()
        self.listbox_visible = False
        self.arrow_btn.setText("\u25bc")

    def set_values(self, values):
        self.values = values

    def get(self):
        return self.entry.text()

    def set(self, value):
        self.entry.setText(value)

    def bind_select(self, callback):
        self.callback = callback


class ComprasUI(QWidget):
    """Interfaz principal para gestión de compras"""

    def __init__(self, parent, db_manager, compras_repo, proveedores_repo, productos_repo, auth_manager,
                 deudas_service=None, abonos_repo=None):
        super().__init__(parent)
        self.parent_widget = parent
        self.db = db_manager
        self.compras_repo = compras_repo
        self.proveedores_repo = proveedores_repo
        self.productos_repo = productos_repo
        self.auth = auth_manager
        self.deudas_service = deudas_service
        self.abonos_repo = abonos_repo

        self.crear_interfaz()

    def crear_interfaz(self):
        """Crea la interfaz principal — diseño compacto sin scroll"""
        BG = COLORS['bg_secondary']

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # Contenedor principal directo (sin scroll para que todo quepa)
        self.scroll_frame = QWidget()
        self.scroll_frame.setStyleSheet(f"background: {BG};")
        self.scroll_layout = QVBoxLayout(self.scroll_frame)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(0)

        outer_layout.addWidget(self.scroll_frame)

        # ===== HEADER =====
        header = QWidget()
        header.setStyleSheet(f"background: {BG};")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(28, 16, 28, 6)

        title_block = QVBoxLayout()
        title_block.setSpacing(2)
        title_lbl = QLabel("Gestión de Compras a Proveedores")
        title_lbl.setFont(make_font(('Segoe UI', 16, 'bold')))
        title_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent; border: none;")
        title_block.addWidget(title_lbl)

        subtitle_lbl = QLabel("Control logístico y financiero de suministros externos")
        subtitle_lbl.setFont(make_font(('Segoe UI', 9)))
        subtitle_lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent; border: none;")
        title_block.addWidget(subtitle_lbl)

        header_layout.addLayout(title_block)
        header_layout.addStretch()

        btn_nueva = QPushButton("  ＋  Nueva Compra")
        btn_nueva.setFont(make_font(('Segoe UI', 10, 'bold')))
        btn_nueva.setCursor(Qt.PointingHandCursor)
        btn_nueva.setFixedHeight(38)
        btn_nueva.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['accent']}; color: {COLORS['on_accent']};
                border: none; border-radius: 10px;
                padding: 0 22px; font-weight: 500;
            }}
            QPushButton:hover {{ background: {COLORS['accent_hover']}; }}
            QPushButton:pressed {{ background: {COLORS['accent_dark']}; }}
        """)
        btn_nueva.clicked.connect(self.abrir_formulario_compra)
        header_layout.addWidget(btn_nueva)

        self.scroll_layout.addWidget(header)

        # ===== KPI CARDS =====
        self.crear_panel_estadisticas()

        # ===== DEBT BANNER =====
        if self.deudas_service:
            self.crear_panel_deudas()

        # ===== TRANSACTION TABLE =====
        self._crear_tabla_transacciones()

        self.cargar_compras_recientes()

    def _crear_tabla_transacciones(self):
        """Crea la tabla de transacciones con diseño SaaS moderno"""
        BG = COLORS['bg_secondary']

        card = ShadowCard(self.scroll_frame, bg_card=COLORS['bg_primary'],
                          shadow_color=COLORS['shadow_card'], shadow_blur=18,
                          border_radius=16)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        # Card header
        hdr = QWidget()
        hdr.setStyleSheet(f"background: {COLORS['bg_primary']}; border: none;")
        hdr_layout = QHBoxLayout(hdr)
        hdr_layout.setContentsMargins(20, 12, 20, 10)

        title_lbl = QLabel("Historial de Transacciones")
        title_lbl.setFont(make_font(('Segoe UI', 12, 'bold')))
        title_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent; border: none;")
        hdr_layout.addWidget(title_lbl)
        hdr_layout.addStretch()

        search_container = QWidget()
        search_container.setStyleSheet(f"QWidget {{ background: {COLORS['bg_hover']}; border: 1px solid {COLORS['border']}; border-radius: 8px; }}")
        search_h = QHBoxLayout(search_container)
        search_h.setContentsMargins(10, 2, 10, 2)
        search_h.setSpacing(4)

        search_icon = QLabel("🔍")
        search_icon.setStyleSheet(f"color: {COLORS['text_light']}; background: transparent; border: none; font-size: 10pt;")
        search_h.addWidget(search_icon)

        self.table_search_entry = QLineEdit()
        self.table_search_entry.setPlaceholderText("Buscar compra...")
        self.table_search_entry.setFixedWidth(170)
        self.table_search_entry.setStyleSheet(f"""
            QLineEdit {{ border: none; background: transparent; color: {COLORS['text_primary']}; font-size: 9pt; padding: 5px 0; }}
        """)
        search_h.addWidget(self.table_search_entry)
        hdr_layout.addWidget(search_container)

        filter_btn = QLabel("☰")
        filter_btn.setStyleSheet(f"""
            QLabel {{ background: {COLORS['bg_hover']}; color: {COLORS['text_secondary']}; border: 1px solid {COLORS['border']};
                     border-radius: 8px; padding: 6px 10px; font-size: 13pt; }}
        """)
        hdr_layout.addWidget(filter_btn)

        card_layout.addWidget(hdr)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {COLORS['border_light']}; border: none;")
        card_layout.addWidget(sep)

        # Table
        columns = ('ID', 'Fecha', 'Proveedor', '# Factura', 'Tipo',
                   'Productos', 'Total', 'Estado Pago', 'Saldo', 'Usuario')

        self.tree = QTableWidget(0, len(columns))
        self.tree.setHorizontalHeaderLabels([c.upper() for c in columns])
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setAlternatingRowColors(True)
        self.tree.verticalHeader().setVisible(False)
        self.tree.setShowGrid(False)

        anchos = {'ID': 80, 'Fecha': 90, 'Proveedor': 140, '# Factura': 82,
                  'Tipo': 90, 'Productos': 150, 'Total': 100, 'Estado Pago': 110,
                  'Saldo': 100, 'Usuario': 115}

        header_view = self.tree.horizontalHeader()
        for i, col in enumerate(columns):
            self.tree.setColumnWidth(i, anchos.get(col, 100))
        header_view.setStretchLastSection(True)

        self.tree.setStyleSheet(f"""
            QTableWidget {{
                background: {COLORS['bg_primary']}; color: {COLORS['text_body']}; border: none; font-size: 9pt;
                gridline-color: transparent;
                alternate-background-color: {COLORS['table_row_alt']};
            }}
            QTableWidget::item {{
                padding: 6px 8px; border-bottom: 1px solid {COLORS['border_light']};
            }}
            QTableWidget::item:selected {{
                background: {COLORS['table_selection']}; color: {COLORS['text_primary']};
            }}
            QHeaderView::section {{
                background: {COLORS['table_header']}; color: {COLORS['table_header_fg']};
                font-size: 8pt; font-weight: 500;
                border: none; padding: 10px 8px;
                border-right: 1px solid {COLORS['table_header_border']};
            }}
            QHeaderView::section:first {{ border-top-left-radius: 12px; }}
            QHeaderView::section:last {{ border-top-right-radius: 12px; border-right: none; }}
        """)

        # Compact row height
        self.tree.verticalHeader().setDefaultSectionSize(38)

        card_layout.addWidget(self.tree, 1)

        sep2 = QFrame()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet(f"background: {COLORS['border_light']}; border: none;")
        card_layout.addWidget(sep2)

        # Action buttons
        btn_bar = QWidget()
        btn_bar.setStyleSheet(f"background: {COLORS['bg_primary']}; border: none;")
        btn_bar_layout = QHBoxLayout(btn_bar)
        btn_bar_layout.setContentsMargins(20, 8, 20, 12)
        btn_bar_layout.setSpacing(10)

        btn_detalles = ActionButton(btn_bar, text="  Ver Detalles  ",
                                    bg=COLORS['primary_light'], fg=COLORS['primary'],
                                    hover_bg=COLORS['primary_hover_light'], border_color=COLORS['primary_border'],
                                    border_radius=12,
                                    padx=14, pady=6, font_size=9,
                                    command=self.ver_detalles_compra)
        btn_bar_layout.addWidget(btn_detalles)

        btn_devolver = ActionButton(btn_bar, text="  Devolver a proveedor  ",
                                    bg=COLORS['accent_light'], fg=COLORS['accent_dark'],
                                    hover_bg=COLORS['accent_light'], border_color=COLORS['accent'],
                                    border_radius=12,
                                    padx=14, pady=6, font_size=9,
                                    command=self.devolver_a_proveedor)
        btn_bar_layout.addWidget(btn_devolver)

        btn_abono = ActionButton(btn_bar, text="  Registrar Abono  ",
                                 bg=COLORS['warning_light'], fg=COLORS['warning_dark'],
                                 hover_bg=COLORS['warning_hover_light'], border_color=COLORS['warning_border'],
                                 border_radius=12,
                                 padx=14, pady=6, font_size=9,
                                 command=self.registrar_abono_desde_tabla)
        btn_bar_layout.addWidget(btn_abono)

        btn_actualizar = ActionButton(btn_bar, text="  Actualizar  ",
                                      bg=COLORS['bg_primary'], fg=COLORS['text_secondary'],
                                      hover_bg=COLORS['bg_hover'], border_color=COLORS['border_input'],
                                      border_radius=12,
                                      padx=14, pady=6, font_size=9,
                                      command=self.cargar_compras_recientes)
        btn_bar_layout.addWidget(btn_actualizar)
        btn_bar_layout.addStretch()

        card_layout.addWidget(btn_bar)

        wrapper = QWidget()
        wrapper.setStyleSheet(f"background: {COLORS['bg_secondary']}; border: none;")
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(28, 0, 28, 10)
        wrapper_layout.addWidget(card, 1)

        self.scroll_layout.addWidget(wrapper, 1)

    def crear_panel_estadisticas(self):
        """Crea panel con 4 KPI cards — diseño SaaS moderno"""
        BG = COLORS['bg_secondary']

        stats_widget = QWidget()
        stats_widget.setStyleSheet(f"background: {BG}; border: none;")
        stats_layout = QHBoxLayout(stats_widget)
        stats_layout.setContentsMargins(28, 4, 28, 8)
        stats_layout.setSpacing(14)

        try:
            # Estadísticas del MES ACTUAL (no todo el histórico), para no
            # sobrecargar el historial de transacciones.
            from datetime import datetime
            hoy = datetime.now()
            inicio_mes = hoy.replace(day=1).strftime('%Y-%m-%d')
            fin_mes = hoy.strftime('%Y-%m-%d')
            stats = self.compras_repo.obtener_estadisticas_compras(
                fecha_inicio=inicio_mes, fecha_fin=fin_mes)

            cards_data = [
                ("TOTAL COMPRAS", f"{stats['total_compras']:,}", "", COLORS['primary'], "Este mes"),
                ("MONTO TOTAL", f"${stats['total_monto']:,.0f}", "", COLORS['success'], "Este mes"),
                ("PROMEDIO", f"${stats['promedio_compra']:,.0f}", "↗", COLORS['primary'], "Este mes"),
                ("PROVEEDORES", f"{stats['total_proveedores']}", "Activos", COLORS['warning'], ""),
            ]

            for titulo, valor, badge, accent, periodo in cards_data:
                subtitle_parts = []
                if badge:
                    subtitle_parts.append(badge)
                if periodo:
                    subtitle_parts.append(periodo)
                subtitle = "  ".join(subtitle_parts)

                card = KpiCard(
                    parent=stats_widget,
                    title=titulo,
                    value=valor,
                    subtitle=subtitle,
                    badge_text=badge if badge and badge not in ('↗',) else '',
                    badge_color=accent,
                )
                card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                stats_layout.addWidget(card)

        except Exception as e:
            print(f"Error cargando estadísticas: {e}")

        self.scroll_layout.addWidget(stats_widget)

    def _crear_kpi_card(self, parent, titulo, valor, subtexto, color_accent, periodo):
        """Legacy"""
        pass

    def crear_stat_card(self, parent, titulo, valor, color):
        """Legacy compatibility"""
        pass

    def cargar_compras_recientes(self):
        """Carga las compras de los últimos 90 días — estilo SaaS con badges"""
        self.tree.setRowCount(0)

        try:
            compras = self.compras_repo.listar_compras_recientes(dias=90)

            for row_idx, compra in enumerate(compras):
                fecha_raw = compra['fecha'][:10] if compra['fecha'] else ''
                try:
                    from datetime import datetime as dt
                    fecha_obj = dt.strptime(fecha_raw, '%Y-%m-%d')
                    meses = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
                             'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
                    fecha = f"{fecha_obj.day} {meses[fecha_obj.month - 1]} {fecha_obj.year}"
                except Exception:
                    fecha = fecha_raw

                estado_pago = compra.get('estado_pago', 'PENDIENTE')
                estado_texto = {
                    'PENDIENTE': 'Pendiente',
                    'PARCIAL': 'Parcial',
                    'PAGADO': 'Completado'
                }.get(estado_pago, estado_pago)

                # Zebra striping: alternate white and very light gray
                row_bg = COLORS['bg_primary'] if row_idx % 2 == 0 else COLORS['table_row_alt']

                saldo = compra.get('saldo_pendiente', compra.get('total', 0))
                saldo_str = f"${saldo:,.2f}" if saldo > 0 else "$0.00"

                id_display = f"PUR-{compra['id']}" if not str(compra['id']).startswith('PUR') else compra['id']

                tipo_raw = compra['tipo_compra'] or 'CONTADO'
                tipo_display = tipo_raw.lower().capitalize()

                # Status with colored dot
                if estado_pago == 'PAGADO':
                    estado_display = f"✓ {estado_texto}"
                elif estado_pago == 'PARCIAL':
                    estado_display = f"● {estado_texto}"
                else:
                    estado_display = f"● {estado_texto}"

                productos_txt = compra.get('productos_nombres', '') or ''
                if not productos_txt:
                    cant = compra.get('cantidad_productos', 0)
                    productos_txt = f"{cant} producto(s)" if cant else '0'
                else:
                    # Truncate long text
                    if len(productos_txt) > 25:
                        productos_txt = productos_txt[:22] + '...'

                valores = (
                    str(id_display),
                    fecha,
                    compra['proveedor_nombre'] or 'Sin proveedor',
                    compra['numero_factura'] or '-',
                    tipo_display,
                    productos_txt,
                    f"${compra['total']:,.2f}" if compra['total'] else '$0.00',
                    estado_display,
                    saldo_str,
                    compra['usuario_nombre'] or '-'
                )

                self.tree.insertRow(row_idx)
                for col_idx, val in enumerate(valores):
                    item = QTableWidgetItem(str(val))
                    item.setTextAlignment(Qt.AlignCenter)
                    item.setBackground(QColor(row_bg))

                    # Left-align text columns
                    if col_idx in (0, 2, 5):
                        item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)

                    # Color the type badge
                    if col_idx == 4:
                        if 'cred' in val.lower():
                            item.setForeground(QColor(COLORS['credito']))
                        else:
                            item.setForeground(QColor(COLORS['primary']))

                    # Color the status text
                    if col_idx == 7:
                        if estado_pago == 'PAGADO':
                            item.setForeground(QColor(COLORS['success']))
                        elif estado_pago == 'PARCIAL':
                            item.setForeground(QColor(COLORS['warning_dark']))
                        else:
                            item.setForeground(QColor(COLORS['danger']))

                    # Color saldo
                    if col_idx == 8:
                        if saldo > 0:
                            item.setForeground(QColor(COLORS['danger']))
                        else:
                            item.setForeground(QColor(COLORS['success']))

                    self.tree.setItem(row_idx, col_idx, item)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al cargar compras:\n{str(e)}")
            import traceback
            traceback.print_exc()

    def ver_detalles_compra(self):
        """Muestra los detalles de una compra seleccionada"""
        row = self.tree.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Advertencia", "Seleccione una compra para ver detalles")
            return

        compra_id_raw = self.tree.item(row, 0).text()
        compra_id = compra_id_raw.replace('PUR-', '') if compra_id_raw.startswith('PUR-') else compra_id_raw

        VentanaDetallesCompra(self, self.compras_repo, compra_id)

    def devolver_a_proveedor(self):
        row = self.tree.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Advertencia", "Seleccione una recepción completada")
            return
        compra_id_raw = self.tree.item(row, 0).text()
        compra_id = compra_id_raw.replace("PUR-", "") if compra_id_raw.startswith("PUR-") else compra_id_raw
        from services.returns_service import ReturnsService
        from ui.returns_ui import open_supplier_return

        svc = ReturnsService(
            self.db or self.compras_repo.db,
            auth=self.auth,
            productos_repo=self.productos_repo,
        )
        open_supplier_return(
            self, int(compra_id), svc, db_manager=self.db or self.compras_repo.db
        )

    def registrar_abono_desde_tabla(self):
        """Abre modal para registrar abono desde la tabla de compras"""
        row = self.tree.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Advertencia", "Seleccione una compra para registrar abono")
            return

        compra_id_raw = self.tree.item(row, 0).text()
        compra_id = compra_id_raw.replace('PUR-', '') if compra_id_raw.startswith('PUR-') else compra_id_raw
        numero_factura = self.tree.item(row, 3).text()

        try:
            compra = self.compras_repo.obtener_compra_por_id(compra_id)

            if not compra:
                QMessageBox.critical(self, "Error", "No se encontr\u00f3 la compra")
                return

            total = compra.get('total', 0)
            saldo_pendiente = compra.get('saldo_pendiente', total)

            if saldo_pendiente is None:
                saldo_pendiente = total

            if saldo_pendiente <= 0:
                QMessageBox.information(self, "Informaci\u00f3n", "Esta factura ya est\u00e1 completamente pagada")
                return

            self._abrir_modal_abono(compra_id, numero_factura, total, saldo_pendiente)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al procesar abono:\n{str(e)}")
            import traceback
            traceback.print_exc()

    def _abrir_modal_abono(self, id_compra, numero_factura, total, saldo):
        """Abre modal para registrar abono"""
        try:
            ventana_abono = QDialog(self)
            ventana_abono.setWindowTitle("Registrar Abono a Factura")
            ventana_abono.setFixedSize(600, 500)
            ventana_abono.setModal(True)

            main_layout = QVBoxLayout(ventana_abono)
            main_layout.setSpacing(10)

            # Info de factura
            info_group = QGroupBox("Informaci\u00f3n de Factura")
            info_group.setFont(make_font(FONTS['body_bold']))
            info_layout = QVBoxLayout(info_group)

            lbl_factura = QLabel(f"Factura: {numero_factura}")
            lbl_factura.setFont(make_font(FONTS['body']))
            info_layout.addWidget(lbl_factura)

            lbl_total = QLabel(f"Total: ${total:,.0f}")
            lbl_total.setFont(make_font(FONTS['body']))
            info_layout.addWidget(lbl_total)

            lbl_saldo = QLabel(f"Saldo Pendiente: ${saldo:,.0f}")
            lbl_saldo.setFont(make_font(('Segoe UI', 11, 'bold')))
            lbl_saldo.setStyleSheet(f"color: {COLORS['danger']}; border: none;")
            info_layout.addWidget(lbl_saldo)

            main_layout.addWidget(info_group)

            # Formulario de abono
            form_group = QGroupBox("Registrar Abono")
            form_group.setFont(make_font(FONTS['body_bold']))
            form_layout = QVBoxLayout(form_group)

            lbl_monto = QLabel("Monto a Abonar:")
            lbl_monto.setFont(make_font(FONTS['body']))
            form_layout.addWidget(lbl_monto)

            monto_row = QHBoxLayout()
            monto_entry = QLineEdit()
            monto_entry.setFont(make_font(FONTS['body']))
            monto_row.addWidget(monto_entry)

            btn_pagar_todo = QPushButton("Pagar Todo")
            btn_pagar_todo.setFont(make_font(FONTS['body_bold']))
            btn_pagar_todo.setStyleSheet(
                f"background-color: {COLORS['success']}; color: white; "
                "border-radius: 4px; padding: 4px 10px;"
            )
            btn_pagar_todo.clicked.connect(lambda: monto_entry.setText(f"{int(saldo):,}"))
            monto_row.addWidget(btn_pagar_todo)
            form_layout.addLayout(monto_row)

            def _formatear_monto_compra():
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

            monto_entry.textChanged.connect(_formatear_monto_compra)

            lbl_tipo = QLabel("Tipo de Pago:")
            lbl_tipo.setFont(make_font(FONTS['body']))
            form_layout.addWidget(lbl_tipo)

            tipo_combo = QComboBox()
            tipo_combo.setFont(make_font(FONTS['body']))
            tipo_combo.addItems(["Efectivo", "Cheque", "Transferencia", "Dep\u00f3sito", "Otro"])
            form_layout.addWidget(tipo_combo)

            lbl_comprobante = QLabel("N\u00famero de Comprobante (Opcional):")
            lbl_comprobante.setFont(make_font(FONTS['body']))
            form_layout.addWidget(lbl_comprobante)

            comprobante_entry = QLineEdit()
            comprobante_entry.setFont(make_font(FONTS['body']))
            form_layout.addWidget(comprobante_entry)

            main_layout.addWidget(form_group, 1)

            saldo_actual = [saldo]

            btn_layout = QHBoxLayout()

            def limpiar_campos():
                monto_entry.clear()
                tipo_combo.setCurrentIndex(0)
                comprobante_entry.clear()

            def guardar_abono():
                try:
                    monto_texto = monto_entry.text().replace(',', '').strip()
                    if not monto_texto:
                        QMessageBox.warning(ventana_abono, "Advertencia", "Ingrese un monto a abonar")
                        return

                    try:
                        monto = float(monto_texto)
                    except ValueError:
                        QMessageBox.critical(ventana_abono, "Error", "El monto debe ser un n\u00famero v\u00e1lido")
                        return

                    if monto <= 0:
                        QMessageBox.warning(ventana_abono, "Advertencia", "El monto debe ser mayor que 0")
                        return

                    if monto > saldo_actual[0]:
                        QMessageBox.warning(ventana_abono, "Advertencia",
                                            f"El monto no puede exceder el saldo pendiente (${saldo_actual[0]:,.0f})")
                        return

                    abono = Abono(
                        id_compra=id_compra,
                        monto_abono=monto,
                        fecha_abono=datetime.now().strftime('%Y-%m-%d'),
                        tipo_pago=tipo_combo.currentText(),
                        numero_comprobante=comprobante_entry.text().strip() or None,
                        usuario=self.auth.usuario_actual.username if self.auth.usuario_actual else "Sistema",
                        observaciones=None
                    )

                    if self.abonos_repo:
                        self.abonos_repo.crear_abono(abono)

                        saldo_actual[0] -= monto

                        QMessageBox.information(ventana_abono, "\u00c9xito",
                                                f"Abono de ${monto:,.0f} registrado correctamente\n"
                                                f"Nuevo saldo pendiente: ${saldo_actual[0]:,.0f}")

                        limpiar_campos()
                        self.cargar_compras_recientes()

                        if saldo_actual[0] <= 0:
                            ventana_abono.accept()
                    else:
                        QMessageBox.critical(ventana_abono, "Error", "Repositorio de abonos no disponible")

                except Exception as e:
                    QMessageBox.critical(ventana_abono, "Error", f"Error al guardar abono:\n{str(e)}")
                    import traceback
                    traceback.print_exc()

            btn_guardar = QPushButton("Guardar")
            btn_guardar.setFont(make_font(FONTS['body_bold']))
            btn_guardar.setCursor(Qt.PointingHandCursor)
            btn_guardar.setStyleSheet(f"""
                QPushButton {{ background: {COLORS['success']}; color: {COLORS['text_on_dark']}; border: none;
                    border-radius: 6px; padding: 12px 40px; font-weight: 500; }}
                QPushButton:hover {{ background: {COLORS['success_dark']}; }}
            """)
            btn_guardar.clicked.connect(guardar_abono)
            btn_layout.addWidget(btn_guardar)

            btn_cancelar = QPushButton("Cancelar")
            btn_cancelar.setFont(make_font(FONTS['body_bold']))
            btn_cancelar.setCursor(Qt.PointingHandCursor)
            btn_cancelar.setStyleSheet(f"""
                QPushButton {{ background: {COLORS['danger']}; color: {COLORS['text_on_dark']}; border: none;
                    border-radius: 6px; padding: 12px 40px; font-weight: 500; }}
                QPushButton:hover {{ background: {COLORS['danger_dark']}; }}
            """)
            btn_cancelar.clicked.connect(limpiar_campos)
            btn_layout.addWidget(btn_cancelar)

            btn_layout.addStretch()
            main_layout.addLayout(btn_layout)

            ventana_abono.exec()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error:\n{str(e)}")
            import traceback
            traceback.print_exc()

    def abrir_formulario_compra(self):
        """Abre el formulario de nueva compra"""
        FormularioCompra(self, self.compras_repo, self.proveedores_repo,
                         self.productos_repo, self.auth, callback=self.cargar_compras_recientes,
                         abonos_repo=self.abonos_repo, db_manager=self.db)

    def crear_panel_deudas(self):
        """Crea panel de resumen de deudas — estilo ámbar/dorado degradado"""
        try:
            if not self.deudas_service:
                return

            try:
                totales = self.deudas_service.obtener_totales_deudas()
            except Exception as e:
                print(f"No se pudieron obtener totales de deudas: {e}")
                return

            if totales.get('total_deuda', 0) == 0:
                return

            BANNER_BG = COLORS['debt_bg']
            METRIC_BG = COLORS['debt_dark']
            ACCENT = COLORS['debt_accent']

            card = ShadowCard(self.scroll_frame, bg_card=BANNER_BG,
                              shadow_color=COLORS['debt_shadow'], shadow_blur=18,
                              border_radius=16)

            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(24, 12, 24, 12)

            # Left side
            left_layout = QVBoxLayout()
            left_layout.setSpacing(4)

            tag_row = QHBoxLayout()
            tag_row.setSpacing(8)
            icon_lbl = QLabel("📦")
            icon_lbl.setStyleSheet("color: white; font-size: 12pt; background: transparent; border: none;")
            tag_row.addWidget(icon_lbl)

            tag_lbl = QLabel("  [DEUDA$] RESUMEN  ")
            tag_lbl.setStyleSheet(f"""
                background: {METRIC_BG}; color: {ACCENT};
                font-size: 7pt; font-weight: 500;
                border-radius: 4px; padding: 2px 6px; border: none;
            """)
            tag_row.addWidget(tag_lbl)
            tag_row.addStretch()
            left_layout.addLayout(tag_row)

            total_lbl = QLabel(f"Total Deuda: ${totales.get('total_deuda', 0):,.0f}")
            total_lbl.setFont(make_font(('Segoe UI', 18, 'bold')))
            total_lbl.setStyleSheet("color: white; background: transparent; border: none;")
            left_layout.addWidget(total_lbl)

            card_layout.addLayout(left_layout, 1)

            # Right side — metric boxes
            right_layout = QHBoxLayout()
            right_layout.setSpacing(10)

            m1 = QFrame()
            m1.setStyleSheet(f"background: {METRIC_BG}; border-radius: 10px; border: none;")
            m1_layout = QVBoxLayout(m1)
            m1_layout.setContentsMargins(16, 8, 16, 8)
            m1_layout.setAlignment(Qt.AlignCenter)
            m1_title = QLabel("FACTURAS PENDIENTES")
            m1_title.setStyleSheet(f"color: {ACCENT}; font-size: 7pt; font-weight: 500; background: transparent; border: none;")
            m1_title.setAlignment(Qt.AlignCenter)
            m1_layout.addWidget(m1_title)
            m1_val = QLabel(f"{totales.get('facturas_pendientes', 0)}")
            m1_val.setFont(make_font(('Segoe UI', 20, 'bold')))
            m1_val.setStyleSheet("color: white; background: transparent; border: none;")
            m1_val.setAlignment(Qt.AlignCenter)
            m1_layout.addWidget(m1_val)
            right_layout.addWidget(m1)

            m2 = QFrame()
            m2.setStyleSheet(f"background: {METRIC_BG}; border-radius: 10px; border: none;")
            m2_layout = QVBoxLayout(m2)
            m2_layout.setContentsMargins(16, 8, 16, 8)
            m2_layout.setAlignment(Qt.AlignCenter)
            m2_title = QLabel("PROVEEDORES")
            m2_title.setStyleSheet(f"color: {ACCENT}; font-size: 7pt; font-weight: 500; background: transparent; border: none;")
            m2_title.setAlignment(Qt.AlignCenter)
            m2_layout.addWidget(m2_title)
            m2_val = QLabel(f"{totales.get('proveedores_con_deuda', 0)}")
            m2_val.setFont(make_font(('Segoe UI', 20, 'bold')))
            m2_val.setStyleSheet("color: white; background: transparent; border: none;")
            m2_val.setAlignment(Qt.AlignCenter)
            m2_layout.addWidget(m2_val)
            right_layout.addWidget(m2)

            card_layout.addLayout(right_layout)

            wrapper = QWidget()
            wrapper.setStyleSheet(f"background: {COLORS['bg_secondary']}; border: none;")
            w_layout = QVBoxLayout(wrapper)
            w_layout.setContentsMargins(28, 0, 28, 8)
            w_layout.addWidget(card)
            self.scroll_layout.addWidget(wrapper)

        except Exception as e:
            print(f"Error al crear panel de deudas: {e}")
            import traceback
            traceback.print_exc()

    def _crear_metrica_deuda(self, parent, titulo, valor, color):
        """Crea una métrica de deuda"""
        pass


class FormularioCompra(QDialog):
    """Formulario para registrar una compra con m\u00faltiples productos"""

    def __init__(self, parent, compras_repo, proveedores_repo, productos_repo, auth_manager, callback=None, abonos_repo=None, db_manager=None, compras_service=None, auto_exec=True):
        super().__init__(parent)
        self.compras_repo = compras_repo
        self.proveedores_repo = proveedores_repo
        self.productos_repo = productos_repo
        self.auth = auth_manager
        self.callback = callback
        self.abonos_repo = abonos_repo
        self.db_manager = db_manager
        self.compras_service = compras_service or ComprasService(
            db_manager or getattr(compras_repo, "db", None),
            compras_repo=compras_repo,
            productos_repo=productos_repo,
            proveedores_repo=proveedores_repo,
            auth=auth_manager,
        )
        self.purchase_cart = PurchaseCart()
        self._thread_pool = QThreadPool.globalInstance()
        self._draft_id = None

        self.carrito = []
        self.ultimo_precio_proveedor = None

        self.setWindowTitle("Registrar Nueva Compra / Recepción")
        self.resize(1000, 700)
        self.setStyleSheet(f"background: {COLORS['bg_primary']};")
        self.setModal(True)

        self.crear_formulario()
        if auto_exec:
            self.exec()

    def crear_formulario(self):
        """Crea el formulario completo"""
        try:
            main_layout = QVBoxLayout(self)
            main_layout.setContentsMargins(0, 0, 0, 0)
            main_layout.setSpacing(0)

            # Header
            header = QFrame()
            header.setFixedHeight(60)
            header.setStyleSheet(f"background: {COLORS['primary']};")
            header_layout = QHBoxLayout(header)
            header_lbl = QLabel("\U0001f6d2 Registrar Nueva Compra")
            header_lbl.setFont(make_font(FONTS['large']))
            header_lbl.setStyleSheet("color: white; background: transparent; border: none;")
            header_lbl.setAlignment(Qt.AlignCenter)
            header_layout.addWidget(header_lbl)
            main_layout.addWidget(header)

            # Scrollable content
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setStyleSheet(f"QScrollArea {{ background: {COLORS['bg_primary']}; border: none; }}")

            main_container = QWidget()
            main_container.setStyleSheet(f"background: {COLORS['bg_primary']};")
            self.form_layout = QVBoxLayout(main_container)
            self.form_layout.setContentsMargins(20, 10, 20, 10)
            self.form_layout.setSpacing(5)

            scroll.setWidget(main_container)
            main_layout.addWidget(scroll, 1)

            self.crear_seccion_encabezado()
            self.crear_seccion_productos()
            self.crear_seccion_carrito()
            self.crear_botones_finales(main_layout)

        except Exception as e:
            print(f"ERROR al crear formulario: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Error al crear formulario:\n{str(e)}")

    def crear_seccion_encabezado(self):
        """Crea la secci\u00f3n de datos generales de la compra"""
        group = QGroupBox("A. Datos Generales de la Compra")
        group.setFont(make_font(FONTS['body_bold']))
        group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: 500; color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border_input']}; border-radius: 6px;
                margin-top: 10px; padding-top: 14px;
                background: {COLORS['bg_primary']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin; subcontrol-position: top left;
                padding: 0 6px;
            }}
        """)
        group_layout = QVBoxLayout(group)

        grid = QGridLayout()

        # Proveedor (obligatorio)
        lbl_prov = QLabel("Proveedor: *")
        lbl_prov.setFont(make_font(FONTS['body']))
        lbl_prov.setStyleSheet(f"color: {COLORS['text_secondary']}; border: none;")
        grid.addWidget(lbl_prov, 0, 0)

        proveedores = self.cargar_proveedores()
        self.proveedores_dict = {p.nombre: p.id for p in proveedores}

        if not proveedores:
            aviso = QLabel("[AVISO] No hay proveedores registrados. Debe registrar proveedores primero.")
            aviso.setFont(make_font(FONTS['body']))
            aviso.setStyleSheet(f"background: {COLORS['warning_light']}; color: {COLORS['warning_dark']}; padding: 5px 10px; border-radius: 4px;")
            grid.addWidget(aviso, 0, 1, 1, 3)
            self.proveedor_combo = None
        else:
            valores_prov = list(self.proveedores_dict.keys())
            self.proveedor_combo = QComboBox()
            self.proveedor_combo.setFont(make_font(FONTS['body']))
            self.proveedor_combo.addItems(valores_prov)
            if valores_prov:
                self.proveedor_combo.setCurrentText(valores_prov[0])
            self.proveedor_combo.currentTextChanged.connect(self.on_proveedor_change)
            grid.addWidget(self.proveedor_combo, 0, 1)

        # N\u00famero de factura
        lbl_fact = QLabel("# Factura:")
        lbl_fact.setFont(make_font(FONTS['body']))
        lbl_fact.setStyleSheet(f"color: {COLORS['text_secondary']}; border: none;")
        grid.addWidget(lbl_fact, 0, 2)

        self.factura_entry = QLineEdit()
        self.factura_entry.setFont(make_font(FONTS['body']))
        grid.addWidget(self.factura_entry, 0, 3)

        # Tipo de compra
        lbl_tipo = QLabel("Tipo de Compra:")
        lbl_tipo.setFont(make_font(FONTS['body']))
        lbl_tipo.setStyleSheet(f"color: {COLORS['text_secondary']}; border: none;")
        grid.addWidget(lbl_tipo, 1, 0)

        tipo_frame = QWidget()
        tipo_frame.setStyleSheet(f"background: {COLORS['bg_primary']}; border: none;")
        tipo_layout = QHBoxLayout(tipo_frame)
        tipo_layout.setContentsMargins(0, 0, 0, 0)

        self.tipo_compra_group = QButtonGroup(self)
        self.radio_contado = QRadioButton("Contado")
        self.radio_contado.setFont(make_font(FONTS['body']))
        self.radio_contado.setChecked(True)
        self.radio_credito = QRadioButton("Cr\u00e9dito")
        self.radio_credito.setFont(make_font(FONTS['body']))
        self.tipo_compra_group.addButton(self.radio_contado)
        self.tipo_compra_group.addButton(self.radio_credito)
        tipo_layout.addWidget(self.radio_contado)
        tipo_layout.addWidget(self.radio_credito)
        tipo_layout.addStretch()
        grid.addWidget(tipo_frame, 1, 1)

        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        group_layout.addLayout(grid)

        self._observaciones_text = ""

        # PAGO INICIAL
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {COLORS['border_input']}; border: none;")
        group_layout.addWidget(sep)

        pago_title = QLabel("Pago Inicial (Opcional)")
        pago_title.setFont(make_font(FONTS['body_bold']))
        pago_title.setStyleSheet(f"color: {COLORS['primary']}; border: none;")
        group_layout.addWidget(pago_title)

        pago_grid = QGridLayout()

        lbl_monto = QLabel("Monto Pagado Inicial: $")
        lbl_monto.setFont(make_font(FONTS['body']))
        lbl_monto.setStyleSheet(f"color: {COLORS['text_secondary']}; border: none;")
        pago_grid.addWidget(lbl_monto, 0, 0)

        self.monto_pagado_inicial_entry = QLineEdit("0")
        self.monto_pagado_inicial_entry.setFont(make_font(FONTS['body']))
        self.monto_pagado_inicial_entry.textChanged.connect(
            self._formatear_monto_pagado_inicial)
        _monto_row = QHBoxLayout()
        _monto_row.addWidget(self.monto_pagado_inicial_entry, 1)
        btn_pagar_todo = QPushButton("Pagar todo")
        btn_pagar_todo.setFont(make_font(FONTS['small']))
        btn_pagar_todo.setToolTip("Rellena el monto con el total de la compra")
        btn_pagar_todo.setStyleSheet(
            f"QPushButton {{ background: {COLORS['success']}; color: white; "
            f"border: none; border-radius: 6px; padding: 4px 12px; }} "
            f"QPushButton:hover {{ background: {COLORS['success_dark']}; }}")
        btn_pagar_todo.clicked.connect(self._pagar_todo_compra)
        _monto_row.addWidget(btn_pagar_todo)
        pago_grid.addLayout(_monto_row, 0, 1)

        lbl_tipo_pago = QLabel("Tipo de Pago:")
        lbl_tipo_pago.setFont(make_font(FONTS['body']))
        lbl_tipo_pago.setStyleSheet(f"color: {COLORS['text_secondary']}; border: none;")
        pago_grid.addWidget(lbl_tipo_pago, 0, 2)

        self.tipo_pago_inicial_combo = QComboBox()
        self.tipo_pago_inicial_combo.setFont(make_font(FONTS['body']))
        self.tipo_pago_inicial_combo.addItems(['Efectivo', 'Cheque', 'Transferencia', 'Deposito', 'Otro'])
        self.tipo_pago_inicial_combo.currentTextChanged.connect(self._on_tipo_pago_inicial_change)
        pago_grid.addWidget(self.tipo_pago_inicial_combo, 0, 3)

        self.comprobante_label = QLabel("# Comprobante:")
        self.comprobante_label.setFont(make_font(FONTS['body']))
        self.comprobante_label.setStyleSheet(f"color: {COLORS['text_secondary']}; border: none;")
        pago_grid.addWidget(self.comprobante_label, 1, 0)

        self.comprobante_entry = QLineEdit()
        self.comprobante_entry.setFont(make_font(FONTS['body']))
        pago_grid.addWidget(self.comprobante_entry, 1, 1)

        info_lbl = QLabel("(Nota: Ingrese pago inicial. El inicial no puede ser mayor al total)")
        info_lbl.setFont(make_font(FONTS['small']))
        info_lbl.setStyleSheet(f"color: {COLORS['info']}; border: none;")
        pago_grid.addWidget(info_lbl, 2, 0, 1, 4)

        pago_grid.setColumnStretch(1, 1)
        pago_grid.setColumnStretch(3, 1)
        group_layout.addLayout(pago_grid)

        self._on_tipo_pago_inicial_change()

        self.form_layout.addWidget(group)

    def _formatear_monto_pagado_inicial(self):
        """Muestra el monto con separador de miles (200000 -> 200,000) para no
        equivocarse con un cero de menos."""
        e = self.monto_pagado_inicial_entry
        texto = e.text().replace(',', '').strip()
        if not texto:
            return
        try:
            valor = int(float(texto))
        except ValueError:
            return
        e.blockSignals(True)
        pos = e.cursorPosition()
        len_antes = len(e.text())
        e.setText(f"{valor:,}")
        e.setCursorPosition(max(0, pos + len(e.text()) - len_antes))
        e.blockSignals(False)

    def _pagar_todo_compra(self):
        """Rellena el monto pagado inicial con el total de la compra."""
        total = int(getattr(self, "_total_compra_actual", 0) or 0)
        self.monto_pagado_inicial_entry.setText(f"{total:,}")

    def _on_tipo_pago_inicial_change(self, text=None):
        """Muestra u oculta el campo de comprobante seg\u00fan el tipo de pago"""
        try:
            tipo = self.tipo_pago_inicial_combo.currentText()
            if tipo and tipo.lower().startswith('efect'):
                self.comprobante_label.hide()
                self.comprobante_entry.hide()
            else:
                self.comprobante_label.show()
                self.comprobante_entry.show()
        except Exception:
            pass

    def crear_seccion_productos(self):
        """Crea la secci\u00f3n para agregar productos al carrito"""
        group = QGroupBox("B. Agregar Productos a la Compra")
        group.setFont(make_font(FONTS['body_bold']))
        group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: 500; color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border_input']}; border-radius: 6px;
                margin-top: 10px; padding-top: 14px;
                background: {COLORS['bg_primary']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin; subcontrol-position: top left;
                padding: 0 6px;
            }}
        """)
        group_layout = QVBoxLayout(group)

        grid = QGridLayout()

        self.productos_proveedor = []
        self.productos_proveedor_nombres = []

        # Producto
        lbl_prod = QLabel("Producto: *")
        lbl_prod.setFont(make_font(FONTS['body']))
        lbl_prod.setStyleSheet(f"color: {COLORS['text_secondary']}; border: none;")
        grid.addWidget(lbl_prod, 0, 0)

        self.producto_combo = AutocompleteEntry(self)
        self.producto_combo.bind_select(self.on_producto_change)
        grid.addWidget(self.producto_combo, 0, 1)

        lbl_scan = QLabel("Escanear / código:")
        lbl_scan.setFont(make_font(FONTS['body']))
        lbl_scan.setStyleSheet(f"color: {COLORS['text_secondary']}; border: none;")
        grid.addWidget(lbl_scan, 4, 0)
        self.scan_entry = QLineEdit()
        self.scan_entry.setPlaceholderText("Barcode físico o alias de proveedor")
        self.scan_entry.setFont(make_font(FONTS['body']))
        self.scan_entry.returnPressed.connect(self.agregar_por_codigo)
        grid.addWidget(self.scan_entry, 4, 1, 1, 2)

        # M\u00e9todo de compra (cajas/unidades)
        metodo_frame = QWidget()
        metodo_frame.setStyleSheet(f"background: {COLORS['bg_primary']}; border: none;")
        metodo_layout = QHBoxLayout(metodo_frame)
        metodo_layout.setContentsMargins(0, 0, 0, 0)

        lbl_metodo = QLabel("Comprar por:")
        lbl_metodo.setFont(make_font(FONTS['small']))
        lbl_metodo.setStyleSheet(f"color: {COLORS['text_secondary']}; border: none;")
        metodo_layout.addWidget(lbl_metodo)

        self.metodo_compra_group = QButtonGroup(self)
        self.radio_unidad = QRadioButton("Unidades")
        self.radio_unidad.setFont(make_font(FONTS['small']))
        self.radio_unidad.setChecked(True)
        self.radio_unidad.toggled.connect(self.on_metodo_compra_change)

        self.radio_caja = QRadioButton("Cajas")
        self.radio_caja.setFont(make_font(FONTS['small']))
        self.radio_caja.setEnabled(True)
        self.radio_caja.toggled.connect(self.on_metodo_compra_change)

        self.metodo_compra_group.addButton(self.radio_unidad)
        self.metodo_compra_group.addButton(self.radio_caja)
        metodo_layout.addWidget(self.radio_unidad)
        metodo_layout.addWidget(self.radio_caja)
        metodo_layout.addStretch()
        grid.addWidget(metodo_frame, 0, 2, 1, 2)

        # Cantidad
        lbl_cant = QLabel("Cantidad: *")
        lbl_cant.setFont(make_font(FONTS['body']))
        lbl_cant.setStyleSheet(f"color: {COLORS['text_secondary']}; border: none;")
        grid.addWidget(lbl_cant, 1, 0)

        self.cantidad_entry = QLineEdit("1")
        self.cantidad_entry.setFont(make_font(FONTS['body']))
        self.cantidad_entry.setFixedWidth(150)
        grid.addWidget(self.cantidad_entry, 1, 1, Qt.AlignLeft)

        # Frame para detalles de compra por cajas
        self.frame_cajas = QGroupBox("\U0001f4e6 Configuraci\u00f3n de Empaque")
        self.frame_cajas.setFont(make_font(FONTS['body_bold']))
        self.frame_cajas.setStyleSheet(f"""
            QGroupBox {{
                font-weight: 500; color: {COLORS['primary']};
                border: 2px ridge {COLORS['primary_border']}; border-radius: 6px;
                margin-top: 10px; padding: 15px 20px;
                background: {COLORS['primary_light']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin; subcontrol-position: top left;
                padding: 0 6px;
            }}
        """)
        cajas_layout = QGridLayout(self.frame_cajas)

        self.lbl_num_cajas = QLabel("Cantidad de Empaques:")
        self.lbl_num_cajas.setFont(make_font(FONTS['body']))
        self.lbl_num_cajas.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent; border: none;")
        cajas_layout.addWidget(self.lbl_num_cajas, 0, 0)

        self.num_cajas_entry = QLineEdit("0")
        self.num_cajas_entry.setFont(make_font(FONTS['body']))
        self.num_cajas_entry.setFixedWidth(200)
        self.num_cajas_entry.setStyleSheet(f"border: 1px solid {COLORS['border_input']}; border-radius: 4px; padding: 4px 8px;")
        cajas_layout.addWidget(self.num_cajas_entry, 0, 1)

        self.lbl_unidades_caja = QLabel("Unidades por Empaque:")
        self.lbl_unidades_caja.setFont(make_font(FONTS['body']))
        self.lbl_unidades_caja.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent; border: none;")
        cajas_layout.addWidget(self.lbl_unidades_caja, 1, 0)

        self.unidades_por_caja_entry = QLineEdit("1")
        self.unidades_por_caja_entry.setFont(make_font(FONTS['body']))
        self.unidades_por_caja_entry.setFixedWidth(200)
        self.unidades_por_caja_entry.setStyleSheet(f"border: 1px solid {COLORS['border_input']}; border-radius: 4px; padding: 4px 8px;")
        cajas_layout.addWidget(self.unidades_por_caja_entry, 1, 1)

        info_empaque = QFrame()
        info_empaque.setStyleSheet(f"background: {COLORS['primary_light']}; border: 1px solid {COLORS['primary_border']}; border-radius: 4px;")
        info_emp_layout = QHBoxLayout(info_empaque)
        info_emp_layout.setContentsMargins(8, 6, 8, 6)
        info_icon = QLabel("\u2139\ufe0f")
        info_icon.setStyleSheet("font-size: 11pt; background: transparent; border: none;")
        info_emp_layout.addWidget(info_icon)
        self.info_msg_cajas = QLabel("El stock se calcular\u00e1 como: Empaques \u00d7 Unidades")
        self.info_msg_cajas.setFont(make_font(FONTS['small']))
        self.info_msg_cajas.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent; border: none;")
        info_emp_layout.addWidget(self.info_msg_cajas)
        info_emp_layout.addStretch()
        cajas_layout.addWidget(info_empaque, 2, 0, 1, 2)

        self.num_cajas_entry.textChanged.connect(self.calcular_total_cajas)
        self.unidades_por_caja_entry.textChanged.connect(self.calcular_total_cajas)

        self.frame_cajas.hide()
        grid.addWidget(self.frame_cajas, 2, 0, 1, 4)

        # Precio unitario de compra
        lbl_precio = QLabel("Precio Compra: *")
        lbl_precio.setFont(make_font(FONTS['body']))
        lbl_precio.setStyleSheet(f"color: {COLORS['text_secondary']}; border: none;")
        grid.addWidget(lbl_precio, 1, 2)

        self.precio_entry = QLineEdit("0")
        self.precio_entry.setFont(make_font(FONTS['body']))
        self.precio_entry.setFixedWidth(150)
        self.precio_entry.textChanged.connect(self.calcular_precio_venta_sugerido)
        grid.addWidget(self.precio_entry, 1, 3, Qt.AlignLeft)

        # Precio de venta sugerido
        lbl_pventa = QLabel("Precio Venta: *")
        lbl_pventa.setFont(make_font(FONTS['body']))
        lbl_pventa.setStyleSheet(f"color: {COLORS['text_secondary']}; border: none;")
        grid.addWidget(lbl_pventa, 3, 2)

        self.precio_venta_entry = QLineEdit("0")
        self.precio_venta_entry.setFont(make_font(FONTS['body']))
        self.precio_venta_entry.setFixedWidth(150)
        grid.addWidget(self.precio_venta_entry, 3, 3, Qt.AlignLeft)

        # Frame de informaci\u00f3n del producto
        info_frame = QFrame()
        info_frame.setStyleSheet(f"background: {COLORS['primary_light']}; border: 1px solid {COLORS['primary_border']}; border-radius: 6px;")
        info_frame_layout = QVBoxLayout(info_frame)
        info_frame_layout.setContentsMargins(10, 5, 10, 5)

        info_title = QLabel("\u2139\ufe0f Informaci\u00f3n del Producto")
        info_title.setFont(make_font(FONTS['body_bold']))
        info_title.setStyleSheet(f"color: {COLORS['primary']}; background: transparent; border: none;")
        info_frame_layout.addWidget(info_title)

        info_grid = QGridLayout()

        lbl_um_title = QLabel("\U0001f4cf Unidad de Medida:")
        lbl_um_title.setFont(make_font(FONTS['small']))
        lbl_um_title.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent; border: none;")
        info_grid.addWidget(lbl_um_title, 0, 0)
        self.unidad_medida_label = QLabel("-")
        self.unidad_medida_label.setFont(make_font(FONTS['body_bold']))
        self.unidad_medida_label.setStyleSheet(f"color: {COLORS['primary']}; background: transparent; border: none;")
        info_grid.addWidget(self.unidad_medida_label, 0, 1)

        lbl_pres_title = QLabel("\U0001f4e6 Presentaci\u00f3n:")
        lbl_pres_title.setFont(make_font(FONTS['small']))
        lbl_pres_title.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent; border: none;")
        info_grid.addWidget(lbl_pres_title, 0, 2)
        self.presentacion_label = QLabel("-")
        self.presentacion_label.setFont(make_font(FONTS['body_bold']))
        self.presentacion_label.setStyleSheet(f"color: {COLORS['primary']}; background: transparent; border: none;")
        info_grid.addWidget(self.presentacion_label, 0, 3)

        lbl_cont_title = QLabel("\U0001f4ca Contenido:")
        lbl_cont_title.setFont(make_font(FONTS['small']))
        lbl_cont_title.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent; border: none;")
        info_grid.addWidget(lbl_cont_title, 1, 0)
        self.contenido_label = QLabel("-")
        self.contenido_label.setFont(make_font(FONTS['body']))
        self.contenido_label.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent; border: none;")
        info_grid.addWidget(self.contenido_label, 1, 1)

        lbl_stock_title = QLabel("\U0001f3ea Stock Actual:")
        lbl_stock_title.setFont(make_font(FONTS['small']))
        lbl_stock_title.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent; border: none;")
        info_grid.addWidget(lbl_stock_title, 1, 2)
        self.stock_label = QLabel("-")
        self.stock_label.setFont(make_font(FONTS['body']))
        self.stock_label.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent; border: none;")
        info_grid.addWidget(self.stock_label, 1, 3)

        info_frame_layout.addLayout(info_grid)

        self.info_producto_label = QLabel("")
        self.info_producto_label.setFont(make_font(FONTS['small']))
        self.info_producto_label.setStyleSheet(f"color: {COLORS['info']}; background: transparent; border: none;")
        info_frame_layout.addWidget(self.info_producto_label)

        grid.addWidget(info_frame, 4, 0, 1, 4)

        # Bot\u00f3n agregar
        btn_agregar = QPushButton("\u2795 Agregar al Carrito")
        btn_agregar.setFont(make_font(FONTS['body_bold']))
        btn_agregar.setCursor(Qt.PointingHandCursor)
        btn_agregar.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['success']}; color: white;
                border: none; border-radius: 6px;
                padding: 10px; font-weight: 500;
            }}
            QPushButton:hover {{ background: {COLORS['success_dark']}; }}
        """)
        btn_agregar.clicked.connect(self.agregar_producto_al_carrito)
        grid.addWidget(btn_agregar, 5, 0, 1, 4)

        grid.setColumnStretch(1, 1)
        group_layout.addLayout(grid)

        self.form_layout.addWidget(group)

        if self.proveedor_combo:
            self.on_proveedor_change()

    def crear_seccion_carrito(self):
        """Crea la secci\u00f3n del carrito de productos"""
        group = QGroupBox("C. Productos en la Compra (Carrito)")
        group.setFont(make_font(FONTS['body_bold']))
        group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: 500; color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border_input']}; border-radius: 6px;
                margin-top: 10px; padding-top: 14px;
                background: {COLORS['bg_primary']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin; subcontrol-position: top left;
                padding: 0 6px;
            }}
        """)
        group_layout = QVBoxLayout(group)

        columns = ('Producto', 'Cantidad', 'Precio Unit.', 'Subtotal')
        self.tree_carrito = QTableWidget(0, len(columns))
        self.tree_carrito.setHorizontalHeaderLabels(columns)
        self.tree_carrito.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree_carrito.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree_carrito.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree_carrito.verticalHeader().setVisible(False)
        self.tree_carrito.setMinimumHeight(200)

        anchos = {'Producto': 400, 'Cantidad': 100, 'Precio Unit.': 120, 'Subtotal': 120}
        for i, col in enumerate(columns):
            self.tree_carrito.setColumnWidth(i, anchos[col])
        self.tree_carrito.horizontalHeader().setStretchLastSection(True)

        group_layout.addWidget(self.tree_carrito, 1)

        btn_frame = QWidget()
        btn_frame.setStyleSheet(f"background: {COLORS['bg_primary']}; border: none;")
        btn_layout = QHBoxLayout(btn_frame)
        btn_layout.setContentsMargins(0, 0, 0, 0)

        btn_eliminar = QPushButton("\U0001f5d1\ufe0f Eliminar Seleccionado")
        btn_eliminar.setFont(make_font(FONTS['body']))
        btn_eliminar.setCursor(Qt.PointingHandCursor)
        btn_eliminar.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['danger']}; color: white;
                border: none; border-radius: 6px; padding: 8px 14px;
            }}
            QPushButton:hover {{ background: {COLORS['danger_dark']}; }}
        """)
        btn_eliminar.clicked.connect(self.eliminar_del_carrito)
        btn_layout.addWidget(btn_eliminar)

        btn_vaciar = QPushButton("\U0001f9f9 Vaciar Carrito")
        btn_vaciar.setFont(make_font(FONTS['body']))
        btn_vaciar.setCursor(Qt.PointingHandCursor)
        btn_vaciar.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['warning']}; color: white;
                border: none; border-radius: 6px; padding: 8px 14px;
            }}
            QPushButton:hover {{ background: {COLORS['warning_dark']}; }}
        """)
        btn_vaciar.clicked.connect(self.vaciar_carrito)
        btn_layout.addWidget(btn_vaciar)

        btn_layout.addStretch()

        self.total_label = QLabel("TOTAL: $0")
        self.total_label.setFont(make_font(('Segoe UI', 16, 'bold')))
        self.total_label.setStyleSheet(f"color: {COLORS['success']}; background: transparent; border: none;")
        btn_layout.addWidget(self.total_label)

        group_layout.addWidget(btn_frame)

        self.form_layout.addWidget(group)

    def crear_botones_finales(self, parent_layout):
        """Crea los botones finales del formulario"""
        btn_frame = QWidget()
        btn_frame.setStyleSheet(f"background: {COLORS['bg_primary']}; border: none;")
        btn_layout = QHBoxLayout(btn_frame)
        btn_layout.setContentsMargins(30, 10, 30, 20)

        self.btn_cancelar = QPushButton("Cancelar")
        self.btn_cancelar.setFont(make_font(FONTS['body']))
        self.btn_cancelar.setCursor(Qt.PointingHandCursor)
        self.btn_cancelar.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['danger']}; color: white;
                border: none; border-radius: 6px; padding: 12px 30px;
            }}
            QPushButton:hover {{ background: {COLORS['danger_dark']}; }}
            QPushButton:disabled {{ background: {COLORS['border_input']}; color: {COLORS['text_secondary']}; }}
        """)
        self.btn_cancelar.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancelar)

        btn_layout.addStretch()

        self.btn_guardar_borrador = QPushButton("Guardar borrador")
        self.btn_guardar_borrador.setFont(make_font(FONTS['body']))
        self.btn_guardar_borrador.setCursor(Qt.PointingHandCursor)
        self.btn_guardar_borrador.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['bg_secondary']}; color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border_input']}; border-radius: 6px; padding: 12px 22px;
            }}
            QPushButton:hover {{ background: {COLORS['bg_hover']}; }}
        """)
        self.btn_guardar_borrador.clicked.connect(self.guardar_borrador)
        btn_layout.addWidget(self.btn_guardar_borrador)

        self.btn_confirmar = QPushButton("CONFIRMAR RECEPCIÓN")
        self.btn_confirmar.setFont(make_font(FONTS['body_bold']))
        self.btn_confirmar.setCursor(Qt.PointingHandCursor)
        self.btn_confirmar.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['primary']}; color: white;
                border: none; border-radius: 6px; padding: 12px 30px;
                font-weight: 500;
            }}
            QPushButton:hover {{ background: {COLORS['primary_dark']}; }}
            QPushButton:disabled {{ background: {COLORS['border_input']}; color: {COLORS['text_secondary']}; }}
        """)
        self.btn_confirmar.clicked.connect(self.guardar_compra)
        btn_layout.addWidget(self.btn_confirmar)

        parent_layout.addWidget(btn_frame)

    def cargar_proveedores(self):
        """Carga proveedores activos"""
        try:
            return self.proveedores_repo.listar_proveedores(solo_activos=True)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al cargar proveedores:\n{str(e)}")
            return []

    def calcular_precio_venta_sugerido(self, text=None):
        """Calcula autom\u00e1ticamente el precio de venta con margen de ganancia del 30%"""
        try:
            precio_compra_str = self.precio_entry.text()
            if not precio_compra_str or precio_compra_str == "0":
                return

            precio_compra = float(precio_compra_str)
            margen = 0.30
            precio_venta_sugerido = precio_compra * (1 + margen)
            precio_venta_sugerido = round(precio_venta_sugerido / 100) * 100
            self.precio_venta_entry.setText(str(int(precio_venta_sugerido)))
        except ValueError:
            pass

    def on_proveedor_change(self, text=None):
        """Carga productos del proveedor seleccionado"""
        if not self.proveedor_combo:
            return

        proveedor_nombre = self.proveedor_combo.currentText()
        if not proveedor_nombre:
            return

        proveedor_id = self.proveedores_dict.get(proveedor_nombre)
        if not proveedor_id:
            return

        try:
            productos = self.productos_repo.listar_productos_por_proveedor(proveedor_id)

            self.productos_proveedor = []
            nombres = []

            for p in productos:
                self.productos_proveedor.append(p)
                nombres.append(p.nombre)

            self.productos_proveedor_nombres = nombres.copy()

            self.producto_combo.set_values(nombres)
            if nombres:
                self.producto_combo.set(nombres[0])
                self.on_producto_change()
            else:
                self.producto_combo.set('')
                self.info_producto_label.setText("[AVISO] Este proveedor no tiene productos asignados")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al cargar productos:\n{str(e)}")

    def on_producto_change(self, event=None):
        """Actualiza informaci\u00f3n del producto seleccionado"""
        producto_nombre = self.producto_combo.get()
        if not producto_nombre:
            self.unidad_medida_label.setText("-")
            self.presentacion_label.setText("-")
            self.contenido_label.setText("-")
            self.stock_label.setText("-")
            self.info_producto_label.setText("")
            return

        producto = next((p for p in self.productos_proveedor if p.nombre == producto_nombre), None)

        if producto:
            self.producto_actual = producto

            unidad = producto.unidad_medida or "UNIDAD"
            self.unidad_medida_label.setText(unidad)

            factor = get_base_units_per_package(self._producto_mapping(producto))
            tiene_empaque = factor is not None
            presentacion_nombre = (
                getattr(producto, "presentacion", None)
                or getattr(producto, "presentacion_empaque", None)
                or "empaque"
            )
            if tiene_empaque:
                presentacion = str(presentacion_nombre)
                contenido_texto = f"Canónico: {factor} {unidad} por {presentacion}"
                self.unidades_por_caja_entry.setText(str(factor))
                self.unidades_por_caja_entry.setReadOnly(True)
            else:
                presentacion = "Sin empaque canónico"
                contenido_texto = f"Se vende por {unidad}"
                self.unidades_por_caja_entry.setText("1")
                self.unidades_por_caja_entry.setReadOnly(True)
            self.radio_caja.setEnabled(bool(tiene_empaque))
            if not tiene_empaque and self.radio_caja.isChecked():
                self.radio_unidad.setChecked(True)
            self._actualizar_labels_modo_compra(unidad)

            self.presentacion_label.setText(presentacion)
            self.contenido_label.setText(contenido_texto)

            from formato import formatear_stock
            _stock_fmt = formatear_stock(producto.stock, getattr(producto, 'permite_decimales', None))
            stock_texto = f"{_stock_fmt} {unidad}"
            if tiene_empaque and factor and producto.stock > 0:
                empaques_equiv = as_decimal(producto.stock) / factor
                stock_texto = f"{_stock_fmt} {unidad} ({empaques_equiv} {presentacion})"

            self.stock_label.setText(stock_texto)

            proveedor_nombre = self.proveedor_combo.currentText() if self.proveedor_combo else None
            proveedor_id = self.proveedores_dict.get(proveedor_nombre) if proveedor_nombre else None

            ultimo_precio = None
            if proveedor_id:
                ultimo_precio = self.compras_repo.obtener_ultimo_precio_compra(
                    producto.id,
                    proveedor_id
                )

            self.ultimo_precio_proveedor = ultimo_precio

            if ultimo_precio and ultimo_precio > 0:
                info = f"\U0001f4b0 \u00daltima compra a este proveedor: ${ultimo_precio:,.0f}"
                self.precio_entry.setText(str(int(ultimo_precio)))
                self.info_producto_label.setText(info)
                self.info_producto_label.setStyleSheet(f"color: {COLORS['primary']}; background: transparent; border: none;")
            elif producto.precio_compra and producto.precio_compra > 0:
                info = f"\U0001f4b0 Precio general: ${producto.precio_compra:,.0f} (no comprado a este proveedor)"
                self.precio_entry.setText(str(int(producto.precio_compra)))
                self.info_producto_label.setText(info)
                self.info_producto_label.setStyleSheet(f"color: {COLORS['warning_dark']}; background: transparent; border: none;")
            else:
                info = "\U0001f4b0 Sin historial de precio para este producto"
                self.precio_entry.setText("")
                self.info_producto_label.setText(info)
                self.info_producto_label.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent; border: none;")

            if producto.precio_venta and producto.precio_venta > 0:
                self.precio_venta_entry.setText(str(int(producto.precio_venta)))

    def _actualizar_labels_modo_compra(self, unidad):
        """Actualiza labels del panel seg\u00fan la unidad de medida del producto"""
        u = (unidad or 'UNIDAD').upper()
        if u in ('METRO', 'CM', 'MM'):
            self.radio_caja.setText("Por longitud")
            self.frame_cajas.setTitle("\U0001f4cf Configuraci\u00f3n por Longitud")
            self.lbl_num_cajas.setText("Cantidad de piezas:")
            self.lbl_unidades_caja.setText("Metros por pieza:")
            self.info_msg_cajas.setText("Stock total = piezas \u00d7 metros por pieza")
        elif u in ('LITRO', 'ML', 'GAL\u00d3N', 'GALON'):
            self.radio_caja.setText("Por volumen")
            self.frame_cajas.setTitle("\U0001f9f4 Configuraci\u00f3n por Volumen")
            self.lbl_num_cajas.setText("Cantidad de envases:")
            self.lbl_unidades_caja.setText(f"{unidad.capitalize()} por envase:")
            self.info_msg_cajas.setText(f"Stock total = envases \u00d7 {unidad.lower()} por envase")
        elif u in ('KILO', 'GRAMO', 'TON'):
            self.radio_caja.setText("Por peso")
            self.frame_cajas.setTitle("\u2696\ufe0f Configuraci\u00f3n por Peso")
            self.lbl_num_cajas.setText("Cantidad de bultos:")
            self.lbl_unidades_caja.setText(f"{unidad.capitalize()} por bulto:")
            self.info_msg_cajas.setText(f"Stock total = bultos \u00d7 {unidad.lower()} por bulto")
        elif u == 'SACO':
            self.radio_caja.setText("Por saco")
            self.frame_cajas.setTitle("\U0001f9f3 Configuraci\u00f3n por Saco")
            self.lbl_num_cajas.setText("Cantidad de sacos:")
            self.lbl_unidades_caja.setText("Kg por saco:")
            self.info_msg_cajas.setText("Stock total = sacos \u00d7 kg por saco")
        else:
            self.radio_caja.setText("Cajas")
            self.frame_cajas.setTitle("\U0001f4e6 Configuraci\u00f3n de Empaque")
            self.lbl_num_cajas.setText("Cantidad de Empaques:")
            self.lbl_unidades_caja.setText("Unidades por Empaque:")
            self.info_msg_cajas.setText("El stock se calcular\u00e1 como: Empaques \u00d7 Unidades")

    def on_metodo_compra_change(self, checked=False):
        """Muestra u oculta el frame de cajas seg\u00fan la selecci\u00f3n"""
        if self.radio_caja.isChecked():
            self.frame_cajas.show()
            self.cantidad_entry.hide()
        else:
            self.frame_cajas.hide()
            self.cantidad_entry.show()

    def calcular_total_cajas(self, *args):
        """Calcula el total de unidades basado en cajas y unidades por caja"""
        pass

    def _producto_mapping(self, producto):
        if isinstance(producto, dict):
            return producto
        return {
            "id": getattr(producto, "id", None),
            "nombre": getattr(producto, "nombre", ""),
            "precio_compra": getattr(producto, "precio_compra", 0),
            "precio_venta": getattr(producto, "precio_venta", 0),
            "permite_decimales": getattr(producto, "permite_decimales", 0),
            "unidad_medida": getattr(producto, "unidad_medida", "UNIDAD"),
            "unidad_base": getattr(producto, "unidad_base", None)
            or getattr(producto, "unidad_base_producto", None)
            or getattr(producto, "unidad_medida", "UNIDAD"),
            "presentacion": getattr(producto, "presentacion", None),
            "presentacion_empaque": getattr(producto, "presentacion_empaque", None)
            or getattr(producto, "presentacion", None),
            "cantidad_base_por_empaque": getattr(
                producto, "cantidad_base_por_empaque", None
            ),
            "unidades_por_caja": getattr(producto, "unidades_por_caja", None),
            "viene_en_caja": getattr(producto, "viene_en_caja", 0),
            "vende_por_empaque": getattr(producto, "vende_por_empaque", 0),
            "vende_empaque_completo": getattr(producto, "vende_empaque_completo", 0),
            "vende_medio_empaque": getattr(producto, "vende_medio_empaque", 0),
            "unidades_por_media_caja": getattr(producto, "unidades_por_media_caja", None),
            "unidades_venta_custom": getattr(producto, "unidades_venta_custom", None),
            "local_id": getattr(producto, "local_id", None),
            "stock": getattr(producto, "stock", 0),
        }

    def _set_confirm_busy(self, busy: bool):
        self.btn_confirmar.setEnabled(not busy)
        self.btn_guardar_borrador.setEnabled(not busy)
        self.btn_cancelar.setEnabled(not busy)
        self.btn_confirmar.setText("PROCESANDO..." if busy else "CONFIRMAR RECEPCIÓN")

    def reject(self):
        if self.purchase_cart.confirm_in_flight:
            return
        super().reject()

    def closeEvent(self, event):
        if self.purchase_cart.confirm_in_flight:
            event.ignore()
            return
        super().closeEvent(event)

    def agregar_por_codigo(self):
        raw = self.scan_entry.text().strip()
        if not raw:
            return
        proveedor_id = self.proveedores_dict.get(self.proveedor_combo.currentText())
        costo = None
        try:
            if self.precio_entry.text().strip():
                costo = self.precio_entry.text().replace(",", "")
        except Exception:
            costo = None
        result = self.purchase_cart.add_scan(
            self.productos_repo,
            raw,
            aliases_repo=getattr(self.compras_service, "aliases_repo", None),
            proveedor_id=proveedor_id,
            costo_unitario=costo,
        )
        self.scan_entry.clear()
        if not result.ok:
            QMessageBox.warning(self, "Código no aplicado", result.error or "No se pudo agregar")
            return
        self._sync_carrito_from_cart()
        self.actualizar_tabla_carrito()

    def _sync_carrito_from_cart(self):
        self.carrito = []
        for line in self.purchase_cart.lines:
            product = line.get("producto") or {}
            self.carrito.append({
                "producto_id": product.get("id"),
                "nombre": product.get("nombre"),
                "cantidad": line.get("cantidad_presentacion"),
                "cantidad_base": line.get("cantidad"),
                "precio": line.get("precio_unitario"),
                "package_role": line.get("package_role"),
                "unidad_medida": product.get("unidad_medida", "UNIDAD"),
                "texto_cantidad": (
                    f"{line.get('cantidad_presentacion')} "
                    f"{line.get('package_role')} → {line.get('cantidad')} base"
                ),
                "supplier_alias": line.get("supplier_alias"),
            })

    def agregar_producto_al_carrito(self):
        """Agrega el producto al carrito de recepción. No mueve stock."""
        try:
            producto_nombre = self.producto_combo.get()
            if not producto_nombre:
                QMessageBox.warning(self, "Advertencia", "Seleccione un producto")
                return

            producto = next((p for p in self.productos_proveedor if p.nombre == producto_nombre), None)
            if not producto:
                QMessageBox.critical(self, "Error", "Producto no encontrado")
                return
            mapping = self._producto_mapping(producto)
            role = PACKAGE_ROLE_BASE_UNIT
            if self.radio_caja.isChecked():
                role = PACKAGE_ROLE_FULL_PACKAGE
                if get_base_units_per_package(mapping) is None:
                    QMessageBox.warning(
                        self,
                        "Empaque",
                        f"{PACKAGING_BLOCKED}: FULL_PACKAGE sin factor canónico",
                    )
                    return
                try:
                    cantidad_real = self.num_cajas_entry.text() or "0"
                except Exception:
                    cantidad_real = "0"
            else:
                cantidad_real = self.cantidad_entry.text() or "0"

            precio_compra = self.precio_entry.text().replace(",", "") or "0"
            try:
                self.purchase_cart.add_line(
                    mapping,
                    cantidad_real,
                    package_role=role,
                    costo_unitario=precio_compra,
                )
            except (PackagingConversionBlocked, PackagingError, ValueError) as exc:
                QMessageBox.warning(self, "Línea inválida", str(exc))
                return

            self._sync_carrito_from_cart()
            self.actualizar_tabla_carrito()
            if self.radio_caja.isChecked():
                self.num_cajas_entry.setText("0")
            else:
                self.cantidad_entry.setText("1")
        except ValueError as e:
            QMessageBox.critical(self, "Error", f"Cantidad y costo deben ser números válidos\n{str(e)}")

    def actualizar_tabla_carrito(self):
        """Actualiza la tabla del carrito y el total"""
        self.tree_carrito.setRowCount(0)
        from decimal import Decimal
        total = Decimal("0")
        if not self.carrito and self.purchase_cart.lines:
            self._sync_carrito_from_cart()
        for row_idx, item in enumerate(self.carrito):
            subtotal = Decimal(str(item['cantidad'])) * Decimal(str(item['precio']))
            total += subtotal
            cantidad_mostrar = item.get('texto_cantidad', f"{item['cantidad']} {item.get('unidad_medida', '')}")
            valores = (
                item['nombre'],
                cantidad_mostrar,
                f"${Decimal(str(item['precio'])):,.0f}",
                f"${subtotal:,.0f}"
            )
            self.tree_carrito.insertRow(row_idx)
            for col_idx, val in enumerate(valores):
                tw_item = QTableWidgetItem(str(val))
                tw_item.setTextAlignment(Qt.AlignCenter)
                self.tree_carrito.setItem(row_idx, col_idx, tw_item)
        self.total_label.setText(f"TOTAL: ${total:,.0f}")
        self._total_compra_actual = total

    def eliminar_del_carrito(self):
        """Elimina el producto seleccionado del carrito"""
        row = self.tree_carrito.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Advertencia", "Seleccione un producto del carrito")
            return
        try:
            self.purchase_cart.remove_line(row)
        except Exception:
            pass
        self._sync_carrito_from_cart()
        self.actualizar_tabla_carrito()

    def vaciar_carrito(self):
        """Vacía todo el carrito"""
        if not self.purchase_cart.lines:
            QMessageBox.information(self, "Info", "El carrito ya está vacío")
            return
        ret = QMessageBox.question(self, "Confirmar", "¿Está seguro de vaciar el carrito?",
                                   QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret == QMessageBox.Yes:
            self.purchase_cart.clear()
            self._sync_carrito_from_cart()
            self.actualizar_tabla_carrito()

    def _header_payload(self):
        proveedor_nombre = self.proveedor_combo.currentText()
        if not proveedor_nombre:
            return None, "Seleccione un proveedor"
        if not self.purchase_cart.lines:
            return None, "Agregue al menos un producto al carrito"
        proveedor_id = self.proveedores_dict[proveedor_nombre]
        numero_factura = self.factura_entry.text().strip() or None
        if not numero_factura:
            return None, "El número de factura es obligatorio. Ingrese el # Factura del proveedor."
        tipo_compra = 'CONTADO' if self.radio_contado.isChecked() else 'CREDITO'
        observaciones = self._observaciones_text or None
        usuario_id = self.auth.usuario_actual.id if self.auth and self.auth.usuario_actual else None
        items = self.purchase_cart.to_purchase_items()
        return {
            "proveedor_id": proveedor_id,
            "proveedor_nombre": proveedor_nombre,
            "productos": items,
            "numero_factura": numero_factura,
            "tipo_compra": tipo_compra,
            "observaciones": observaciones,
            "usuario_id": usuario_id,
        }, None

    def guardar_borrador(self):
        payload, error = self._header_payload()
        if error:
            QMessageBox.critical(self, "Error", error)
            return
        ok, msg, compra_id = self.compras_service.guardar_borrador(
            proveedor_id=payload["proveedor_id"],
            productos=payload["productos"],
            numero_factura=payload["numero_factura"],
            tipo_compra=payload["tipo_compra"],
            observaciones=payload["observaciones"],
            usuario_id=payload["usuario_id"],
            compra_id=self._draft_id,
        )
        if ok:
            self._draft_id = compra_id
            QMessageBox.information(self, "Borrador", f"{msg} (ID {compra_id}). El inventario no cambió.")
            if self.callback:
                self.callback()
        else:
            QMessageBox.critical(self, "Error", msg)

    def guardar_compra(self):
        """CONFIRMAR RECEPCIÓN. Única vía que aplica inventario."""
        try:
            if self.purchase_cart.confirm_in_flight:
                return
            payload, error = self._header_payload()
            if error:
                QMessageBox.critical(self, "Error", error)
                return
            allowed, reason = receipt_finalize_allowed(
                self.db_manager or getattr(self.compras_repo, "db", None)
            )
            if not allowed:
                QMessageBox.warning(
                    self,
                    "CONFIRMAR bloqueado",
                    reason or "No se puede confirmar la recepción sin autoridad central.",
                )
                return
            total_carrito = self.purchase_cart.totals()[1]
            mensaje_confirmacion = (
                f"¿Confirmar recepción?\n\n"
                f"Proveedor: {payload['proveedor_nombre']}\n"
                f"Productos: {len(payload['productos'])}\n"
                f"Total: ${total_carrito:,.0f}\n"
                f"Tipo: {payload['tipo_compra']}\n\n"
                "El inventario se incrementará exactamente una vez."
            )
            ret = QMessageBox.question(self, "Confirmar recepción", mensaje_confirmacion,
                                       QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret != QMessageBox.Yes:
                return
            if not self.purchase_cart.begin_confirm():
                return
            self._set_confirm_busy(True)
            if self._draft_id is None:
                ok, msg, cid = self.compras_service.guardar_borrador(
                    proveedor_id=payload["proveedor_id"],
                    productos=payload["productos"],
                    numero_factura=payload["numero_factura"],
                    tipo_compra=payload["tipo_compra"],
                    observaciones=payload["observaciones"],
                    usuario_id=payload["usuario_id"],
                )
                if not ok:
                    self.purchase_cart.end_confirm()
                    self._set_confirm_busy(False)
                    QMessageBox.critical(self, "Error", msg)
                    return
                self._draft_id = cid
            draft_id = self._draft_id

            def _confirmar():
                return self.compras_service.confirmar_recepcion(
                    compra_id=draft_id,
                )

            worker = FunctionWorker(_confirmar)
            worker.signals.result.connect(self._on_recepcion_resultado)
            worker.signals.error.connect(self._on_recepcion_error)
            self._thread_pool.start(worker)
        except Exception as e:
            self.purchase_cart.end_confirm()
            self._set_confirm_busy(False)
            QMessageBox.critical(self, "Error", f"Error al confirmar recepción:\n{str(e)}")

    def _on_recepcion_error(self, mensaje):
        self.purchase_cart.end_confirm()
        self._set_confirm_busy(False)
        QMessageBox.critical(self, "Error", mensaje or "Error al confirmar recepción")

    def _on_recepcion_resultado(self, outcome):
        try:
            exito, mensaje, compra_id = outcome
        except Exception:
            self._on_recepcion_error("Resultado de recepción ilegible")
            return
        if not exito:
            self.purchase_cart.end_confirm()
            self._set_confirm_busy(False)
            if mensaje and str(mensaje).startswith("INVENTORY_UNKNOWN"):
                QMessageBox.warning(
                    self,
                    "Inventario pendiente",
                    "La recepción no se confirmó en el coordinador. "
                    "Reintente la misma operación; no cree otra recepción.",
                )
                return
            QMessageBox.critical(self, "Error", mensaje)
            return
        self.purchase_cart.end_confirm()
        self._set_confirm_busy(False)
        QMessageBox.information(
            self,
            "Recepción confirmada",
            f"{mensaje}\n\nCompra ID: {compra_id}\n"
            "El precio de venta maestro no se modificó.",
        )
        self.accept()
        if self.callback:
            self.callback()


class VentanaDetallesCompra(QDialog):
    """Ventana para mostrar detalles de una compra"""

    def __init__(self, parent, compras_repo, compra_id):
        super().__init__(parent)
        self.compras_repo = compras_repo
        self.compra_id = compra_id

        self.setWindowTitle(f"Detalles de Compra #{compra_id}")
        self.resize(800, 600)
        self.setStyleSheet(f"background: {COLORS['bg_primary']};")
        self.setModal(True)

        self.cargar_detalles()
        self.exec()

    def cargar_detalles(self):
        """Carga y muestra los detalles de la compra"""
        try:
            compra = self.compras_repo.obtener_compra_por_id(self.compra_id)
            if not compra:
                QMessageBox.critical(self, "Error", "No se encontr\u00f3 la compra")
                self.reject()
                return

            main_layout = QVBoxLayout(self)
            main_layout.setContentsMargins(0, 0, 0, 0)
            main_layout.setSpacing(0)

            # Header
            header = QFrame()
            header.setFixedHeight(60)
            header.setStyleSheet(f"background: {COLORS['primary']};")
            header_layout = QHBoxLayout(header)
            header_lbl = QLabel(f"\U0001f4c4 Compra #{self.compra_id}")
            header_lbl.setFont(make_font(FONTS['large']))
            header_lbl.setStyleSheet("color: white; background: transparent; border: none;")
            header_lbl.setAlignment(Qt.AlignCenter)
            header_layout.addWidget(header_lbl)
            main_layout.addWidget(header)

            # Informaci\u00f3n general
            info_frame = QFrame()
            info_frame.setStyleSheet("background: white; border-radius: 6px; border: none;")
            info_layout = QVBoxLayout(info_frame)
            info_layout.setContentsMargins(20, 15, 20, 15)

            info_text = (
                f"Proveedor: {compra['proveedor_nombre']}\n"
                f"Fecha: {compra['fecha'][:16] if compra['fecha'] else '-'}\n"
                f"Factura: {compra['numero_factura'] or 'Sin n\u00famero'}\n"
                f"Tipo: {compra['tipo_compra']}\n"
                f"Usuario: {compra['usuario_nombre'] or '-'}\n"
                f"Observaciones: {compra['observaciones'] or 'Ninguna'}"
            )

            info_lbl = QLabel(info_text)
            info_lbl.setFont(make_font(FONTS['body']))
            info_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent; border: none;")
            info_layout.addWidget(info_lbl)

            wrapper_info = QWidget()
            wrapper_info.setStyleSheet("background: transparent; border: none;")
            wi_layout = QVBoxLayout(wrapper_info)
            wi_layout.setContentsMargins(20, 10, 20, 5)
            wi_layout.addWidget(info_frame)
            main_layout.addWidget(wrapper_info)

            # Tabla de productos
            tabla_container = QWidget()
            tabla_container.setStyleSheet("background: white; border: none;")
            tabla_layout = QVBoxLayout(tabla_container)
            tabla_layout.setContentsMargins(20, 5, 20, 5)

            title_prods = QLabel("Productos Comprados")
            title_prods.setFont(make_font(FONTS['body_bold']))
            title_prods.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent; border: none;")
            title_prods.setAlignment(Qt.AlignCenter)
            tabla_layout.addWidget(title_prods)

            columns = ('Producto', 'C\u00f3digo', 'Cantidad', 'Precio Unit.', 'Subtotal')
            tree = QTableWidget(0, len(columns))
            tree.setHorizontalHeaderLabels(columns)
            tree.setSelectionBehavior(QAbstractItemView.SelectRows)
            tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
            tree.verticalHeader().setVisible(False)

            for i in range(len(columns)):
                tree.setColumnWidth(i, 150)
            tree.horizontalHeader().setStretchLastSection(True)

            for row_idx, prod in enumerate(compra['productos']):
                valores = (
                    prod['producto_nombre'],
                    prod['codigo_barras'] or '-',
                    f"{prod['cantidad']} {prod['unidad_medida']}",
                    f"${prod['precio_unitario']:,.0f}",
                    f"${prod['subtotal']:,.0f}"
                )
                tree.insertRow(row_idx)
                for col_idx, val in enumerate(valores):
                    item = QTableWidgetItem(str(val))
                    item.setTextAlignment(Qt.AlignCenter)
                    tree.setItem(row_idx, col_idx, item)

            tabla_layout.addWidget(tree, 1)
            main_layout.addWidget(tabla_container, 1)

            # Total
            total_frame = QWidget()
            total_frame.setStyleSheet("background: white; border: none;")
            total_layout = QHBoxLayout(total_frame)
            total_layout.setContentsMargins(20, 5, 20, 10)
            total_layout.addStretch()

            total_lbl = QLabel(f"TOTAL: ${compra['total']:,.0f}")
            total_lbl.setFont(make_font(('Segoe UI', 16, 'bold')))
            total_lbl.setStyleSheet(f"color: {COLORS['success']}; background: transparent; border: none;")
            total_layout.addWidget(total_lbl)

            main_layout.addWidget(total_frame)

            # Bot\u00f3n cerrar
            btn_cerrar = QPushButton("Cerrar")
            btn_cerrar.setFont(make_font(FONTS['body']))
            btn_cerrar.setCursor(Qt.PointingHandCursor)
            btn_cerrar.setStyleSheet(f"""
                QPushButton {{
                    background: {COLORS['primary']}; color: white;
                    border: none; border-radius: 6px; padding: 10px 40px;
                }}
                QPushButton:hover {{ background: {COLORS['primary_dark']}; }}
            """)
            btn_cerrar.clicked.connect(self.accept)

            btn_wrapper = QWidget()
            btn_wrapper.setStyleSheet("background: transparent; border: none;")
            bw_layout = QHBoxLayout(btn_wrapper)
            bw_layout.addStretch()
            estado = str(compra.get("estado") or "").upper()
            if estado in ("COMPLETADA", "COMPLETED"):
                btn_devolver = QPushButton("Devolver a proveedor")
                btn_devolver.setFont(make_font(FONTS['body']))
                btn_devolver.setCursor(Qt.PointingHandCursor)
                btn_devolver.setDefault(False)
                btn_devolver.setAutoDefault(False)
                btn_devolver.setStyleSheet(f"""
                    QPushButton {{
                        background: {COLORS['accent']}; color: white;
                        border: none; border-radius: 6px; padding: 10px 24px;
                    }}
                    QPushButton:hover {{ background: {COLORS['accent_dark']}; }}
                """)
                def _open_return():
                    from services.returns_service import ReturnsService
                    from ui.returns_ui import open_supplier_return
                    db = getattr(self.compras_repo, "db", None)
                    svc = ReturnsService(db, auth=getattr(self.parent(), "auth", None))
                    open_supplier_return(self, int(self.compra_id), svc, db_manager=db)
                btn_devolver.clicked.connect(_open_return)
                bw_layout.addWidget(btn_devolver)
            bw_layout.addWidget(btn_cerrar)
            bw_layout.addStretch()
            main_layout.addWidget(btn_wrapper)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al cargar detalles:\n{str(e)}")
