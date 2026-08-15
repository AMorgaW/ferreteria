"""
PUNTO DE VENTA MODERNO - PySide6
Interfaz rediseñada completamente con estilo e-commerce
"""
from PySide6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QComboBox,
    QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea, QDialog,
    QRadioButton, QButtonGroup, QMessageBox, QSizePolicy,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QGroupBox, QSplitter,
)
from PySide6.QtCore import Qt, QTimer, Signal, QThreadPool
from PySide6.QtGui import QFont, QColor, QCursor
from datetime import datetime
from ui_config import COLORS, FONTS, ICONS, make_font
from unidades_venta_manager import UnidadesVentaManager
from ui.widgets import ShadowCard, ActionButton
from ui.async_worker import FunctionWorker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _color_with_alpha(hex_color, alpha):
    """Return rgba() string from hex + alpha 0-255."""
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return f"rgba({r},{g},{b},{alpha})"


# ---------------------------------------------------------------------------
# ProductCard
# ---------------------------------------------------------------------------

class ProductCard(QFrame):
    """Tarjeta de producto estilo e-commerce"""

    clicked = Signal(dict)

    def __init__(self, parent, producto, on_click=None):
        super().__init__(parent)
        self.producto = producto
        self._on_click = on_click

        self.setFixedSize(178, 182)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self._normal_style = f"""
            ProductCard {{
                background: {COLORS.get('bg_primary', '#ffffff')};
                border: 1px solid {COLORS['border']};
                border-radius: 12px;
            }}
        """
        self._hover_style = f"""
            ProductCard {{
                background: {COLORS['bg_primary']};
                border: 1px solid {COLORS['accent']};
                border-radius: 12px;
            }}
        """
        self.setStyleSheet(self._normal_style)

        if on_click:
            self.clicked.connect(on_click)

        self._crear_ui()

    # -- UI ------------------------------------------------------------------

    @staticmethod
    def _iniciales(nombre):
        tokens = [t for t in (nombre or '').split() if t]
        if not tokens:
            return '–'
        if len(tokens) == 1:
            return tokens[0][:2].upper()
        return (tokens[0][0] + tokens[1][0]).upper()

    def _crear_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(3)

        transparent = "background: transparent; border: none;"

        # Cabecera flat: badge tipográfico (iniciales) + stock
        from formato import formatear_stock
        stock = self.producto.get('stock', 0)
        _stock_fmt = formatear_stock(stock, self.producto.get('permite_decimales'))
        if stock > 10:
            stock_color = COLORS['success']
            stock_text = f"Stock: {_stock_fmt}"
        elif stock > 0:
            stock_color = COLORS['warning']
            stock_text = f"Stock: {_stock_fmt}"
        else:
            stock_color = COLORS['danger']
            stock_text = "Sin stock"

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(0)
        badge = QLabel(self._iniciales(self.producto.get('nombre')))
        badge.setFixedSize(38, 38)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(
            f"background: {COLORS['primary']}; color: white; border-radius: 10px;"
            f" font-size: 11pt; font-weight: 500;"
        )
        top.addWidget(badge)
        top.addStretch()
        stock_label = QLabel(stock_text)
        stock_label.setStyleSheet(f"font-size: 8pt; font-weight: 500; color: {stock_color}; {transparent}")
        top.addWidget(stock_label, 0, Qt.AlignVCenter)
        layout.addLayout(top)

        # Nombre
        nombre = (self.producto.get('nombre') or 'Sin nombre')[:30]
        nombre_label = QLabel(nombre)
        nombre_label.setWordWrap(True)
        nombre_label.setStyleSheet(
            f"font-size: 10pt; font-weight: 500; color: {COLORS['text_primary']}; {transparent}"
        )
        nombre_label.setMaximumHeight(34)
        layout.addWidget(nombre_label)

        # Marca
        marca = (self.producto.get('marca') or '').strip()
        if marca:
            marca_label = QLabel(marca[:25])
            marca_label.setStyleSheet(
                f"font-size: 8pt; color: {COLORS['text_secondary']}; {transparent}"
            )
            layout.addWidget(marca_label)

        layout.addStretch()

        # Precio
        precio = self.producto.get('precio_venta', 0)
        precio_label = QLabel(f"${precio:,.0f}")
        precio_label.setStyleSheet(
            f"font-size: 13pt; font-weight: 500; color: {COLORS['text_primary']}; {transparent}"
        )
        layout.addWidget(precio_label)

        # Botón agregar
        if stock > 0:
            btn = QPushButton("Agregar")
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {COLORS['primary']}; color: white;
                    border: none; border-radius: 8px;
                    padding: 7px 0; font-size: 9pt; font-weight: 500;
                }}
                QPushButton:hover {{ background: {COLORS['accent']}; color: {COLORS['on_accent']}; }}
            """)
            btn.clicked.connect(self._handle_click)
            layout.addWidget(btn)
        else:
            sold = QLabel("Agotado")
            sold.setAlignment(Qt.AlignCenter)
            sold.setStyleSheet(
                f"background: {COLORS['bg_pressed']}; color: {COLORS['text_light']};"
                f" border-radius: 8px; padding: 7px 0; font-size: 9pt; font-weight: 500;"
            )
            layout.addWidget(sold)

    # -- Events --------------------------------------------------------------

    def enterEvent(self, event):
        self.setStyleSheet(self._hover_style)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet(self._normal_style)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self._handle_click()
        super().mousePressEvent(event)

    def _handle_click(self):
        if self.producto.get('stock', 0) > 0:
            self.clicked.emit(self.producto)


# ---------------------------------------------------------------------------
# DialogoCantidadModern
# ---------------------------------------------------------------------------

class DialogoCantidadModern(QDialog):
    """Diálogo moderno para ingresar cantidad con soporte dinámico de unidades"""

    def __init__(self, parent, producto, db_manager):
        super().__init__(parent)
        self.setWindowTitle("Cantidad")
        self.cantidad = None
        self.producto = producto
        self.db_manager = db_manager
        self.unidades_manager = UnidadesVentaManager(db_manager)

        self.producto_nombre = producto.get('nombre', 'Producto')
        self.stock_disponible = producto.get('stock', 0)
        self.categoria = producto.get('categoria', '')

        self.unidades_disponibles = self.unidades_manager.obtener_unidades_venta_producto(self.producto)

        # Fila de botones es horizontal → altura fija independiente del nº de opciones
        width = 580
        height = 480 if len(self.unidades_disponibles) > 1 else 440

        self.setFixedSize(width, height)
        self.setModal(True)

        self._crear_ui()

        self.entry_cantidad.setFocus()
        self.entry_cantidad.selectAll()

    # -- UI ------------------------------------------------------------------

    def _crear_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(75)
        header.setStyleSheet(f"background: {COLORS['primary']};")
        header_layout = QVBoxLayout(header)
        header_layout.setAlignment(Qt.AlignCenter)
        header_layout.setSpacing(2)

        icon_lbl = QLabel("📦")
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet("font-size: 18pt; background: transparent; border: none; color: white;")
        header_layout.addWidget(icon_lbl)

        name_lbl = QLabel(self.producto_nombre)
        name_lbl.setAlignment(Qt.AlignCenter)
        name_lbl.setWordWrap(True)
        name_lbl.setStyleSheet(
            "font-size: 11pt; font-weight: 500; color: white; background: transparent; border: none;"
        )
        header_layout.addWidget(name_lbl)
        outer.addWidget(header)

        # Content
        content = QWidget()
        content.setStyleSheet("background: white;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 14, 24, 14)
        content_layout.setSpacing(8)

        # Stock info
        success_light = COLORS.get('success_dark', '#059669')
        stock_frame = QFrame()
        stock_frame.setStyleSheet(f"""
            QFrame {{
                background: #ecfdf5; border: 2px solid {COLORS['success']};
                border-radius: 8px;
            }}
        """)
        sf_layout = QVBoxLayout(stock_frame)
        sf_layout.setAlignment(Qt.AlignCenter)
        sf_layout.setContentsMargins(16, 10, 16, 10)
        sf_layout.setSpacing(2)

        check_lbl = QLabel("✓ Stock Disponible")
        check_lbl.setAlignment(Qt.AlignCenter)
        check_lbl.setStyleSheet(
            f"font-size: 9pt; font-weight: 500; color: {COLORS['success']}; background: transparent; border: none;"
        )
        sf_layout.addWidget(check_lbl)

        stock_formateado = self.unidades_manager.formatear_stock_display(self.producto)
        stock_val = QLabel(stock_formateado)
        stock_val.setAlignment(Qt.AlignCenter)
        stock_val.setStyleSheet(
            f"font-size: 14pt; font-weight: 500; color: {COLORS['text_primary']}; background: transparent; border: none;"
        )
        sf_layout.addWidget(stock_val)
        content_layout.addWidget(stock_frame)

        # Unit selection
        self.radio_buttons = []
        self.unidad_seleccionada = self.unidades_disponibles[0]['nombre']

        if len(self.unidades_disponibles) > 1:
            unit_title = QLabel("Tipo de Venta")
            unit_title.setStyleSheet(
                f"font-size: 10pt; font-weight: 500; color: {COLORS['text_primary']}; background: transparent; border: none;"
            )
            content_layout.addWidget(unit_title)

            tipo_row = QHBoxLayout()
            tipo_row.setSpacing(8)
            self.btn_group = QButtonGroup(self)
            self.btn_group.setExclusive(True)

            for idx, unidad_info in enumerate(self.unidades_disponibles):
                nombre_unidad = unidad_info['nombre']
                factor = unidad_info['factor']

                col_widget = QWidget()
                col_layout = QVBoxLayout(col_widget)
                col_layout.setContentsMargins(0, 0, 0, 0)
                col_layout.setSpacing(2)

                radio = QRadioButton(nombre_unidad)
                radio.setStyleSheet("""
                    QRadioButton {
                        font-size: 11pt; font-weight: 500;
                        background: #E8E8E8; color: #2C3E50;
                        border: 2px solid #ccc; border-radius: 6px;
                        padding: 8px; min-height: 28px;
                    }
                    QRadioButton::indicator { width: 0; height: 0; }
                    QRadioButton:checked {
                        background: #10B981; color: white;
                        border: 2px solid #059669;
                    }
                """)
                radio.setCursor(QCursor(Qt.PointingHandCursor))
                if idx == 0:
                    radio.setChecked(True)
                radio.toggled.connect(self._actualizar_seleccion_venta)
                self.btn_group.addButton(radio, idx)
                self.radio_buttons.append(radio)
                col_layout.addWidget(radio)

                if factor == 1:
                    desc_text = "Unidad base"
                    desc_color = COLORS['text_secondary']
                else:
                    desc_text = f"= {factor} base"
                    desc_color = COLORS['info']

                desc_lbl = QLabel(desc_text)
                desc_lbl.setAlignment(Qt.AlignCenter)
                desc_lbl.setStyleSheet(
                    f"font-size: 8pt; color: {desc_color}; background: transparent; border: none;"
                )
                col_layout.addWidget(desc_lbl)
                tipo_row.addWidget(col_widget)

            content_layout.addLayout(tipo_row)

        # Quantity container
        self.cantidad_container = QWidget()
        self.cantidad_container_layout = QVBoxLayout(self.cantidad_container)
        self.cantidad_container_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(self.cantidad_container)

        self._mostrar_campo_cantidad()

        # Separator
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {COLORS.get('disabled', '#cbd5e1')};")
        content_layout.addWidget(sep)

        # Action buttons
        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        btn_cancel = QPushButton("✗ Cancelar")
        btn_cancel.setCursor(QCursor(Qt.PointingHandCursor))
        btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['bg_secondary']}; color: {COLORS['text_primary']};
                border: 2px solid #d1d5db; border-radius: 6px;
                padding: 10px; font-size: 10pt;
            }}
            QPushButton:hover {{ background: #e2e8f0; }}
        """)
        btn_cancel.clicked.connect(self._cancelar)
        action_row.addWidget(btn_cancel)

        btn_ok = QPushButton("✓ Confirmar y Agregar")
        btn_ok.setCursor(QCursor(Qt.PointingHandCursor))
        btn_ok.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['success']}; color: white;
                border: none; border-radius: 6px;
                padding: 10px; font-size: 10pt; font-weight: 500;
            }}
            QPushButton:hover {{ background: #0D9F6E; }}
        """)
        btn_ok.clicked.connect(self._aceptar)
        action_row.addWidget(btn_ok)

        content_layout.addLayout(action_row)
        outer.addWidget(content, 1)

    # -- Dynamic fields ------------------------------------------------------

    def _actualizar_seleccion_venta(self):
        checked = self.btn_group.checkedButton()
        if checked:
            self.unidad_seleccionada = checked.text()
            self._mostrar_campo_cantidad()

    def _mostrar_campo_cantidad(self):
        # Clear
        while self.cantidad_container_layout.count():
            item = self.cantidad_container_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        unidad_info = next(
            (u for u in self.unidades_disponibles if u['nombre'] == self.unidad_seleccionada),
            None
        )
        if not unidad_info:
            return

        factor = unidad_info['factor']
        etiqueta = f"Cantidad de {self.unidad_seleccionada}"
        texto_ayuda = None if factor == 1 else f"1 {self.unidad_seleccionada} = {factor} unidades base"

        lbl = QLabel(etiqueta)
        lbl.setStyleSheet(
            f"font-size: 10pt; font-weight: 500; color: {COLORS['text_primary']}; background: transparent; border: none;"
        )
        self.cantidad_container_layout.addWidget(lbl)

        self.entry_cantidad = QLineEdit("1")
        self.entry_cantidad.setAlignment(Qt.AlignCenter)
        self.entry_cantidad.setStyleSheet(f"""
            QLineEdit {{
                font-size: 28pt; font-weight: 500;
                color: {COLORS['primary']}; background: #FAFAFA;
                border: 3px solid {COLORS['primary']};
                border-radius: 8px; padding: 10px;
            }}
        """)
        self.entry_cantidad.setMaximumHeight(80)
        self.entry_cantidad.returnPressed.connect(self._aceptar)
        self.entry_cantidad.setFocus()
        self.entry_cantidad.selectAll()
        self.cantidad_container_layout.addWidget(self.entry_cantidad)

        if texto_ayuda:
            ayuda = QLabel(texto_ayuda)
            ayuda.setStyleSheet(
                f"font-size: 9pt; color: {COLORS['info']}; background: transparent; border: none;"
            )
            self.cantidad_container_layout.addWidget(ayuda)

    # -- Accept / Cancel -----------------------------------------------------

    def _aceptar(self):
        try:
            cantidad_str = self.entry_cantidad.text().strip()
            cantidad_ingresada = float(cantidad_str)

            if cantidad_ingresada <= 0:
                QMessageBox.warning(self, "Cantidad inválida",
                                    "La cantidad debe ser mayor a 0")
                return

            permite_decimales = self.producto.get('permite_decimales', False)
            if not permite_decimales and cantidad_ingresada != int(cantidad_ingresada):
                nombre_producto = self.producto.get('nombre', 'Este producto')
                QMessageBox.warning(
                    self, "Cantidad inválida",
                    f"{nombre_producto} no permite cantidades decimales.\n\n"
                    f"Solo puede ingresar números enteros (1, 2, 3, etc.).\n\n"
                    f"Cantidad ingresada: {cantidad_ingresada}"
                )
                return

            unidad_actual = self.unidad_seleccionada

            cantidad_base, _ = self.unidades_manager.convertir_a_unidad_base(
                self.producto, cantidad_ingresada, unidad_actual
            )

            es_valido, mensaje = self.unidades_manager.validar_stock_disponible(
                self.producto, cantidad_ingresada, unidad_actual
            )
            if not es_valido:
                QMessageBox.warning(self, "Stock insuficiente", mensaje)
                return

            self.cantidad = cantidad_base
            self.accept()
        except ValueError:
            QMessageBox.critical(self, "Error", "Ingrese una cantidad válida")

    def _cancelar(self):
        self.cantidad = None
        self.reject()


# ---------------------------------------------------------------------------
# DialogoSeleccionCliente
# ---------------------------------------------------------------------------

class DialogoSeleccionCliente(QDialog):
    """Diálogo para buscar y seleccionar un cliente existente."""

    def __init__(self, parent, clientes_repo):
        super().__init__(parent)
        self.setWindowTitle("Seleccionar Cliente")
        self.setFixedSize(600, 480)
        self.setModal(True)
        self.clientes_repo = clientes_repo
        self.cliente_seleccionado = None
        self._buscar_clientes_timer = QTimer(self)
        self._buscar_clientes_timer.setSingleShot(True)
        self._buscar_clientes_timer.setInterval(300)
        self._buscar_clientes_timer.timeout.connect(self._filtrar_clientes)
        self._crear_ui()
        self._cargar_clientes()
        self.search_input.setFocus()

    def _crear_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(54)
        header.setStyleSheet(f"background: {COLORS['primary']};")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 0, 20, 0)
        title = QLabel("👥 Seleccionar Cliente")
        title.setStyleSheet("font-size: 14pt; font-weight: 500; color: white; background: transparent; border: none;")
        hl.addWidget(title)
        outer.addWidget(header)

        # Body
        body = QWidget()
        body.setStyleSheet("background: white;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(20, 15, 20, 15)
        bl.setSpacing(10)

        # Search
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Buscar por nombre, documento o teléfono…")
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                font-size: 11pt; padding: 8px 12px;
                border: 2px solid {COLORS['border_input']}; border-radius: 6px;
            }}
            QLineEdit:focus {{ border-color: {COLORS['primary']}; }}
        """)
        self.search_input.textChanged.connect(lambda: self._buscar_clientes_timer.start())
        bl.addWidget(self.search_input)

        # Table
        self.tabla = QTableWidget()
        self.tabla.setColumnCount(5)
        self.tabla.setHorizontalHeaderLabels(["Nombre", "Documento", "Teléfono", "Ciudad", "Crédito disp."])
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.horizontalHeader().setStretchLastSection(True)
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tabla.setStyleSheet(f"""
            QTableWidget {{
                border: 1px solid {COLORS['border']}; border-radius: 4px;
                gridline-color: {COLORS['border']};
            }}
            QTableWidget::item:selected {{
                background: {COLORS['primary_light']}; color: {COLORS['primary']};
            }}
            QHeaderView::section {{
                background: {COLORS['table_header']}; color: white;
                font-weight: 500; font-size: 9pt;
                padding: 6px; border: none;
            }}
        """)
        self.tabla.doubleClicked.connect(self._aceptar)
        bl.addWidget(self.tabla, 1)

        # Info label
        self.info_label = QLabel("")
        self.info_label.setStyleSheet(f"font-size: 8pt; color: {COLORS['text_light']}; background: transparent;")
        bl.addWidget(self.info_label)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        btn_general = QPushButton("Cliente General")
        btn_general.setCursor(QCursor(Qt.PointingHandCursor))
        btn_general.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['bg_secondary']}; color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border_input']}; border-radius: 6px;
                padding: 10px 18px; font-size: 10pt;
            }}
            QPushButton:hover {{ background: {COLORS['bg_hover']}; }}
        """)
        btn_general.clicked.connect(self._seleccionar_general)
        btn_row.addWidget(btn_general)

        btn_row.addStretch()

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setCursor(QCursor(Qt.PointingHandCursor))
        btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['bg_secondary']}; color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border_input']}; border-radius: 6px;
                padding: 10px 18px; font-size: 10pt;
            }}
            QPushButton:hover {{ background: {COLORS['bg_hover']}; }}
        """)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_ok = QPushButton("✓ Seleccionar")
        btn_ok.setCursor(QCursor(Qt.PointingHandCursor))
        btn_ok.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['primary']}; color: white;
                border: none; border-radius: 6px;
                padding: 10px 22px; font-size: 10pt; font-weight: 500;
            }}
            QPushButton:hover {{ background: {COLORS['primary_dark']}; }}
        """)
        btn_ok.clicked.connect(self._aceptar)
        btn_row.addWidget(btn_ok)

        bl.addLayout(btn_row)
        outer.addWidget(body, 1)

    def _cargar_clientes(self, criterio=None):
        try:
            if self.clientes_repo.cache_disponible():
                clientes = self.clientes_repo.buscar_clientes_cache(criterio=criterio, solo_activos=True, limite=120)
            else:
                clientes = self.clientes_repo.buscar_clientes(criterio=criterio, solo_activos=True, limite=120)
        except Exception:
            clientes = self.clientes_repo.listar_clientes(solo_activos=True, limite=120)

        self._clientes_list = clientes
        self.tabla.setRowCount(len(clientes))

        for row, c in enumerate(clientes):
            self.tabla.setItem(row, 0, QTableWidgetItem(c.nombre or ""))
            self.tabla.setItem(row, 1, QTableWidgetItem(c.numero_documento or ""))
            self.tabla.setItem(row, 2, QTableWidgetItem(c.telefono or ""))
            self.tabla.setItem(row, 3, QTableWidgetItem(c.ciudad or ""))
            disponible = c.limite_credito - c.saldo_pendiente
            self.tabla.setItem(row, 4, QTableWidgetItem(f"${disponible:,.0f}"))

        self.info_label.setText(f"{len(clientes)} cliente(s) encontrado(s)")

    def _filtrar_clientes(self):
        texto = self.search_input.text().strip()
        self._cargar_clientes(criterio=texto if texto else None)

    def _aceptar(self):
        row = self.tabla.currentRow()
        if row < 0 or row >= len(self._clientes_list):
            QMessageBox.warning(self, "Selección", "Seleccione un cliente de la lista.")
            return
        self.cliente_seleccionado = self._clientes_list[row]
        self.accept()

    def _seleccionar_general(self):
        self.cliente_seleccionado = None
        self.accept()


# ---------------------------------------------------------------------------
# VentasUIModern
# ---------------------------------------------------------------------------

class VentasUIModern(QWidget):
    """Interfaz de Punto de Venta MODERNA"""
    
    venta_completada = Signal()  # Signal para notificar cuando se completa una venta

    def __init__(self, parent, ventas_service, productos_repo, clientes_repo,
                 auth, db_manager,
                 cuentas_por_cobrar_service=None, abonos_ventas_repo=None,
                 mezclas_service=None, callback_actualizar_caja=None):
        super().__init__(parent)
        self.parent_widget = parent
        self.ventas_service = ventas_service
        self.productos_repo = productos_repo
        self.clientes_repo = clientes_repo
        self.auth = auth
        self.db_manager = db_manager
        self.cuentas_service = cuentas_por_cobrar_service
        self.abonos_repo = abonos_ventas_repo
        self.mezclas_service = mezclas_service
        self.callback_actualizar_caja = callback_actualizar_caja  # Callback para actualizar caja

        self.carrito = []
        self.cliente_seleccionado = None
        self.productos_data = []

        self.metodo_pago = "EFECTIVO"
        self.descuento_valor = 0.0
        self._buscar_productos_timer = QTimer(self)
        self._buscar_productos_timer.setSingleShot(True)
        self._buscar_productos_timer.setInterval(300)
        self._buscar_productos_timer.timeout.connect(self._ejecutar_busqueda_productos)
        self._thread_pool = QThreadPool.globalInstance()
        self._productos_loading = False

        self._crear_ui()
        self.cargar_productos()

    # =====================================================================
    # UI CREATION
    # =====================================================================

    def _crear_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header
        self._crear_header(main_layout)

        # Body – 2-column splitter
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(15, 15, 15, 15)
        body_layout.setSpacing(15)

        # LEFT – Products (stretch 7)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)
        self._crear_seccion_productos(left_layout)
        body_layout.addWidget(left, 7)

        # RIGHT – Cart (stretch 3)
        right = QFrame()
        right.setStyleSheet(f"""
            QFrame {{
                background: {COLORS.get('bg_primary', '#ffffff')};
                border-radius: 10px;
                border: 1px solid #e2e8f0;
            }}
        """)
        right.setFixedWidth(430)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        self._crear_seccion_carrito(right_layout)
        body_layout.addWidget(right, 3)

        main_layout.addWidget(body, 1)

    # -- Header --------------------------------------------------------------

    def _crear_header(self, parent_layout):
        header = QFrame()
        header.setFixedHeight(90)
        header.setStyleSheet(f"background: {COLORS['primary']};")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(30, 0, 30, 0)

        # Left side – title + credit button
        left_col = QVBoxLayout()
        left_col.setSpacing(4)

        title = QLabel(f"{ICONS.get('ventas', '💰')} Punto de Venta")
        title.setStyleSheet(
            "font-size: 18pt; font-weight: 500; color: white; background: transparent; border: none;"
        )
        left_col.addWidget(title)

        if self.cuentas_service:
            btn_creditos = QPushButton("💳 Ventas a Crédito")
            btn_creditos.setCursor(QCursor(Qt.PointingHandCursor))
            btn_creditos.setStyleSheet("""
                QPushButton {
                    background: #F59E0B; color: white; border: none;
                    border-radius: 4px; padding: 5px 15px;
                    font-size: 9pt; font-weight: 500;
                }
                QPushButton:hover { background: #D97706; }
            """)
            btn_creditos.clicked.connect(self.ver_ventas_credito)
            left_col.addWidget(btn_creditos, 0, Qt.AlignLeft)

        h_layout.addLayout(left_col)
        h_layout.addStretch()

        # Right side – user info + clock
        right_col = QVBoxLayout()
        right_col.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        if self.auth.usuario_actual:
            user_lbl = QLabel(
                f"{ICONS.get('usuarios', '👤')} {self.auth.usuario_actual.nombre_completo}"
            )
            user_lbl.setStyleSheet(
                "font-size: 10pt; color: white; background: transparent; border: none;"
            )
            user_lbl.setAlignment(Qt.AlignRight)
            right_col.addWidget(user_lbl)

        self.hora_label = QLabel("")
        self.hora_label.setStyleSheet(
            "font-size: 9pt; color: white; background: transparent; border: none;"
        )
        self.hora_label.setAlignment(Qt.AlignRight)
        right_col.addWidget(self.hora_label)
        self._actualizar_hora()

        h_layout.addLayout(right_col)
        parent_layout.addWidget(header)

    # -- Productos -----------------------------------------------------------

    def _crear_seccion_productos(self, parent_layout):
        # Search card
        search_card = ShadowCard()
        sc_layout = QVBoxLayout(search_card)
        sc_layout.setContentsMargins(20, 15, 20, 15)
        sc_layout.setSpacing(8)

        search_title = QLabel(f"{ICONS.get('buscar', '🔍')} Buscar Producto")
        search_title.setStyleSheet(
            f"font-size: 13pt; font-weight: 500; color: {COLORS['text_primary']}; background: transparent; border: none;"
        )
        sc_layout.addWidget(search_title)

        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText("Buscar por nombre, código o marca…")
        self.search_entry.setStyleSheet(f"""
            QLineEdit {{
                font-size: 14pt; padding: 10px 14px;
                border: 2px solid #d1d5db; border-radius: 8px;
                background: white; color: {COLORS['text_primary']};
            }}
            QLineEdit:focus {{ border-color: {COLORS['primary']}; }}
        """)
        self.search_entry.textChanged.connect(lambda: self.buscar_productos())
        self.search_entry.returnPressed.connect(self.agregar_por_codigo_rapido)
        sc_layout.addWidget(self.search_entry)

        # Filter row
        filter_row = QHBoxLayout()
        filter_row.setSpacing(10)

        cat_label = QLabel("Categoría:")
        cat_label.setStyleSheet(
            f"font-size: 10pt; font-weight: 500; color: {COLORS['text_primary']}; background: transparent; border: none;"
        )
        filter_row.addWidget(cat_label)

        self.combo_categoria = QComboBox()
        self.combo_categoria.addItem("Todas")
        self.combo_categoria.setMinimumWidth(180)
        self.combo_categoria.currentTextChanged.connect(lambda _: self.buscar_productos())
        filter_row.addWidget(self.combo_categoria)

        filter_row.addStretch()

        if self.mezclas_service:
            btn_mezcla = QPushButton("Nueva Mezcla")
            btn_mezcla.setCursor(QCursor(Qt.PointingHandCursor))
            btn_mezcla.setStyleSheet("""
                QPushButton {
                    background: #7C3AED; color: white; border: none;
                    border-radius: 9px; padding: 8px 16px;
                    font-size: 10pt; font-weight: 500;
                }
                QPushButton:hover { background: #6D28D9; }
            """)
            btn_mezcla.clicked.connect(self.abrir_mezcla_pintura)
            filter_row.addWidget(btn_mezcla)

        sc_layout.addLayout(filter_row)
        parent_layout.addWidget(search_card)

        # Products grid card
        prod_card = ShadowCard()
        pc_layout = QVBoxLayout(prod_card)
        pc_layout.setContentsMargins(10, 10, 10, 10)
        pc_layout.setSpacing(6)

        prod_title = QLabel(f"{ICONS.get('productos', '📦')} Productos Disponibles")
        prod_title.setStyleSheet(
            f"font-size: 13pt; font-weight: 500; color: {COLORS['text_primary']}; background: transparent; border: none;"
        )
        pc_layout.addWidget(prod_title)

        # Scroll area for product cards
        self.productos_scroll = QScrollArea()
        self.productos_scroll.setWidgetResizable(True)
        self.productos_scroll.setStyleSheet("""
            QScrollArea { border: none; background: #F8F9FA; }
        """)

        self.productos_container = QWidget()
        self.productos_container.setStyleSheet("background: #F8F9FA;")
        self.productos_grid = QGridLayout(self.productos_container)
        self.productos_grid.setSpacing(8)
        self.productos_grid.setContentsMargins(4, 4, 4, 4)

        self.productos_scroll.setWidget(self.productos_container)
        pc_layout.addWidget(self.productos_scroll, 1)
        parent_layout.addWidget(prod_card, 1)

    # -- Carrito -------------------------------------------------------------

    def _crear_seccion_carrito(self, parent_layout):
        transparent = "background: transparent; border: none;"

        # AUTORIZAR button
        btn_autorizar = QPushButton("AUTORIZAR VENTA")
        btn_autorizar.setCursor(QCursor(Qt.PointingHandCursor))
        btn_autorizar.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['success']}; color: white;
                border: none; padding: 12px;
                font-size: 11pt; font-weight: 500;
                border-top-left-radius: 12px; border-top-right-radius: 12px;
            }}
            QPushButton:hover {{ background: {COLORS['success_dark']}; }}
        """)
        btn_autorizar.clicked.connect(self.procesar_venta)
        parent_layout.addWidget(btn_autorizar)

        # Payment method
        self._crear_metodo_pago_section(parent_layout)

        # Cliente row
        cliente_card = QWidget()
        cc_layout = QHBoxLayout(cliente_card)
        cc_layout.setContentsMargins(10, 5, 10, 5)
        cc_layout.setSpacing(5)

        cc_label = QLabel("Cliente:")
        cc_label.setStyleSheet(f"font-size: 9pt; {transparent}")
        cc_layout.addWidget(cc_label)

        self.cliente_label = QLabel("Cliente General")
        self.cliente_label.setStyleSheet(
            f"font-size: 9pt; color: {COLORS['text_secondary']}; {transparent}"
        )
        cc_layout.addWidget(self.cliente_label, 1)

        btn_cliente = QPushButton("Cambiar")
        btn_cliente.setCursor(QCursor(Qt.PointingHandCursor))
        btn_cliente.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['info']}; color: white;
                border: none; border-radius: 4px;
                padding: 4px 10px; font-size: 9pt;
            }}
            QPushButton:hover {{ background: #0891b2; }}
        """)
        btn_cliente.clicked.connect(self.seleccionar_cliente)
        cc_layout.addWidget(btn_cliente)
        parent_layout.addWidget(cliente_card)

        # Separator
        sep1 = QFrame()
        sep1.setFixedHeight(1)
        sep1.setStyleSheet("background: #e2e8f0;")
        parent_layout.addWidget(sep1)

        # Cart items scroll area
        self.carrito_scroll = QScrollArea()
        self.carrito_scroll.setWidgetResizable(True)
        self.carrito_scroll.setStyleSheet("QScrollArea { border: none; background: white; }")
        self.carrito_scroll.setMinimumHeight(200)

        self.carrito_container = QWidget()
        self.carrito_container.setStyleSheet("background: white;")
        self.carrito_layout = QVBoxLayout(self.carrito_container)
        self.carrito_layout.setContentsMargins(4, 4, 4, 4)
        self.carrito_layout.setSpacing(3)
        self.carrito_layout.addStretch()

        self.carrito_scroll.setWidget(self.carrito_container)
        parent_layout.addWidget(self.carrito_scroll, 1)

        # Totales
        self._crear_seccion_totales(parent_layout)

    # -- Método de pago ------------------------------------------------------

    def _crear_metodo_pago_section(self, parent_layout):
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #e2e8f0;")
        parent_layout.addWidget(sep)

        container = QWidget()
        cl = QVBoxLayout(container)
        cl.setContentsMargins(10, 5, 10, 5)
        cl.setSpacing(4)

        transparent = "background: transparent; border: none;"
        lbl = QLabel("Método de Pago:")
        lbl.setStyleSheet(f"font-size: 9pt; color: {COLORS['text_primary']}; {transparent}")
        cl.addWidget(lbl)

        metodos = [
            ("Efectivo", "EFECTIVO"),
            ("Tarjeta", "TARJETA"),
            ("Transferencia", "TRANSFERENCIA"),
            ("Crédito", "CREDITO"),
        ]

        grid = QGridLayout()
        grid.setSpacing(4)
        self.metodo_botones = {}

        for idx, (texto, valor) in enumerate(metodos):
            row = idx // 2
            col = idx % 2
            btn = QPushButton(texto)
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            btn.clicked.connect(lambda checked, v=valor: self.seleccionar_metodo_pago(v))
            grid.addWidget(btn, row, col)
            self.metodo_botones[valor] = btn

        cl.addLayout(grid)
        self._actualizar_botones_metodo_pago()

        # Secondary buttons
        sec_row = QHBoxLayout()
        sec_row.setSpacing(6)

        btn_limpiar = QPushButton("Limpiar")
        btn_limpiar.setCursor(QCursor(Qt.PointingHandCursor))
        btn_limpiar.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['danger']}; color: white;
                border: none; border-radius: 4px;
                padding: 6px; font-size: 9pt;
            }}
            QPushButton:hover {{ background: {COLORS['danger_dark']}; }}
        """)
        btn_limpiar.clicked.connect(self.limpiar_carrito)
        sec_row.addWidget(btn_limpiar)

        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setCursor(QCursor(Qt.PointingHandCursor))
        btn_cancelar.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['text_secondary']}; color: white;
                border: none; border-radius: 4px;
                padding: 6px; font-size: 9pt;
            }}
            QPushButton:hover {{ background: #374151; }}
        """)
        btn_cancelar.clicked.connect(self.cancelar_venta)
        sec_row.addWidget(btn_cancelar)

        cl.addLayout(sec_row)
        parent_layout.addWidget(container)

    # -- Totales -------------------------------------------------------------

    def _crear_seccion_totales(self, parent_layout):
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #e2e8f0;")
        parent_layout.addWidget(sep)

        transparent = "background: transparent; border: none;"

        totales = QWidget()
        tl = QVBoxLayout(totales)
        tl.setContentsMargins(10, 5, 10, 8)
        tl.setSpacing(3)

        # Subtotal
        r1 = QHBoxLayout()
        lbl_sub = QLabel("Subtotal:")
        lbl_sub.setStyleSheet(f"font-size: 9pt; {transparent}")
        r1.addWidget(lbl_sub)
        r1.addStretch()
        self.subtotal_label = QLabel("$0")
        self.subtotal_label.setStyleSheet(f"font-size: 9pt; color: {COLORS['text_primary']}; {transparent}")
        r1.addWidget(self.subtotal_label)
        tl.addLayout(r1)

        # Descuento
        r2 = QHBoxLayout()
        lbl_desc = QLabel("Descuento $:")
        lbl_desc.setStyleSheet(f"font-size: 9pt; {transparent}")
        r2.addWidget(lbl_desc)
        r2.addStretch()
        self.descuento_entry = QLineEdit("0")
        self.descuento_entry.setFixedWidth(80)
        self.descuento_entry.setAlignment(Qt.AlignRight)
        self.descuento_entry.setStyleSheet("""
            QLineEdit {
                font-size: 9pt; padding: 2px 6px;
                border: 1px solid #d1d5db; border-radius: 4px;
            }
        """)
        self.descuento_entry.textChanged.connect(self._calcular_totales)
        r2.addWidget(self.descuento_entry)
        tl.addLayout(r2)

        # Sep
        sep2 = QFrame()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet("background: #e2e8f0;")
        tl.addWidget(sep2)

        # Total
        r4 = QHBoxLayout()
        r4_frame = QFrame()
        r4_frame.setStyleSheet(f"""
            QFrame {{
                background: #ecfdf5; border-radius: 6px; border: none;
            }}
        """)
        r4f_layout = QHBoxLayout(r4_frame)
        r4f_layout.setContentsMargins(8, 6, 8, 6)

        lbl_total = QLabel("TOTAL:")
        lbl_total.setStyleSheet(
            f"font-size: 11pt; font-weight: 500; color: {COLORS['primary_dark']}; background: transparent; border: none;"
        )
        r4f_layout.addWidget(lbl_total)
        r4f_layout.addStretch()

        self.total_label = QLabel("$0")
        self.total_label.setStyleSheet(
            f"font-size: 11pt; font-weight: 500; color: {COLORS['primary_dark']}; background: transparent; border: none;"
        )
        r4f_layout.addWidget(self.total_label)
        tl.addWidget(r4_frame)

        parent_layout.addWidget(totales)

    # =====================================================================
    # BUSINESS LOGIC
    # =====================================================================

    def _actualizar_hora(self):
        ahora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        self.hora_label.setText(ahora)
        QTimer.singleShot(1000, self._actualizar_hora)

    def cargar_productos(self):
        try:
            if self.productos_repo.cache_disponible():
                productos = self.productos_repo.buscar_productos_cache(limite=120)
            else:
                productos = self.productos_repo.listar_productos(solo_activos=True, limite=120)
            self.productos_data = productos

            print(f"[DEBUG MODERN] Productos cargados: {len(productos)}")

            categorias = ['Todas'] + self.productos_repo.obtener_categorias()
            self.combo_categoria.blockSignals(True)
            self.combo_categoria.clear()
            self.combo_categoria.addItems(categorias)
            self.combo_categoria.blockSignals(False)

            self.mostrar_productos(productos)

            if not productos:
                QMessageBox.information(self, "Sin productos",
                    "No hay productos en el sistema.\n"
                    "Agregue productos primero en la sección 'Productos'.")
        except Exception as e:
            print(f"[ERROR] Error al cargar productos: {str(e)}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Error al cargar productos: {str(e)}")

    def mostrar_productos(self, productos):
        # Clear grid
        while self.productos_grid.count():
            item = self.productos_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        print(f"[DEBUG] Mostrando {len(productos)} productos en tarjetas")

        cols = 4
        for idx, prod in enumerate(productos):
            row = idx // cols
            col = idx % cols
            card = ProductCard(self.productos_container, prod,
                               on_click=self.mostrar_dialogo_cantidad_y_agregar)
            self.productos_grid.addWidget(card, row, col)

        # Fill remaining columns so cards align left
        remainder = len(productos) % cols
        if remainder:
            for c in range(remainder, cols):
                spacer = QWidget()
                spacer.setFixedSize(175, 0)
                self.productos_grid.addWidget(spacer, len(productos) // cols, c)

    def buscar_productos(self):
        self._buscar_productos_timer.start()

    def _ejecutar_busqueda_productos(self):
        busqueda = self.search_entry.text().lower()
        categoria = self.combo_categoria.currentText()

        try:
            if self.productos_repo.cache_disponible():
                self.productos_data = self.productos_repo.buscar_productos_cache(
                    busqueda.strip(),
                    categoria=categoria,
                    limite=120,
                )
            elif busqueda.strip():
                self.productos_data = self.productos_repo.buscar_productos(busqueda.strip(), limite=120)
            elif categoria == "Todas":
                self.productos_data = self.productos_repo.listar_productos(solo_activos=True, limite=120)
            else:
                self.productos_data = self.productos_repo.buscar_productos(categoria, limite=120)
        except Exception as e:
            print(f"[ERROR] Error buscando productos: {e}")
            return

        productos_filtrados = []
        for prod in self.productos_data:
            if not prod.get('activo', True):
                continue
            nombre = prod.get('nombre', '').lower()
            codigo = (prod.get('codigo_barras') or '').lower()
            marca = (prod.get('marca') or '').lower()

            if busqueda and not (busqueda in nombre or busqueda in codigo or busqueda in marca):
                continue
            if categoria != "Todas" and prod.get('categoria') != categoria:
                continue
            productos_filtrados.append(prod)

        self.mostrar_productos(productos_filtrados)

    def agregar_por_codigo_rapido(self):
        codigo = self.search_entry.text().strip()
        if not codigo:
            return

        producto = self.productos_repo.obtener_por_codigo(codigo)
        if not producto:
            try:
                producto = self.productos_repo.obtener_por_id(int(codigo))
            except Exception:
                pass

        if producto:
            self.mostrar_dialogo_cantidad_y_agregar(producto)
            self.search_entry.clear()
        else:
            QMessageBox.warning(self, "No encontrado",
                                f"No se encontró producto: {codigo}")

    def mostrar_dialogo_cantidad_y_agregar(self, producto):
        if producto.get('stock', 0) == 0:
            QMessageBox.warning(self, "Sin stock",
                                f"{producto.get('nombre')} no tiene stock disponible")
            return

        dialogo = DialogoCantidadModern(self, producto, self.db_manager)
        dialogo.exec()

        if dialogo.cantidad:
            self.agregar_al_carrito(producto, dialogo.cantidad)

    def agregar_al_carrito(self, producto, cantidad=1):
        prod_id = producto.get('id')
        if prod_id is not None:
            for item in self.carrito:
                if not item.get('es_mezcla') and item['producto']['id'] == prod_id:
                    item['cantidad'] += cantidad
                    self._actualizar_carrito_ui()
                    return

        self.carrito.append({
            'producto': producto,
            'cantidad': cantidad,
            'precio_unitario': producto.get('precio_venta', 0),
            'descuento': 0,
        })
        self._actualizar_carrito_ui()

    def _actualizar_carrito_ui(self):
        # Clear
        while self.carrito_layout.count():
            item = self.carrito_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        transparent = "background: transparent; border: none;"

        for idx, item in enumerate(self.carrito):
            item_frame = QFrame()
            item_frame.setStyleSheet(f"""
                QFrame {{
                    background: {COLORS['bg_secondary']};
                    border-radius: 6px; border: none;
                }}
            """)
            fl = QVBoxLayout(item_frame)
            fl.setContentsMargins(8, 6, 8, 6)
            fl.setSpacing(2)

            nombre = item['producto'].get('nombre', '')
            marca = (item['producto'].get('marca') or '').strip()
            nombre_mostrar = f"{nombre} - {marca}" if marca else nombre

            name_lbl = QLabel(nombre_mostrar[:30])
            name_lbl.setStyleSheet(
                f"font-size: 9pt; color: {COLORS['text_primary']}; {transparent}"
            )
            fl.addWidget(name_lbl)

            info_row = QHBoxLayout()
            cant_lbl = QLabel(f"Cant: {item['cantidad']}")
            cant_lbl.setStyleSheet(
                f"font-size: 9pt; color: {COLORS['text_secondary']}; {transparent}"
            )
            info_row.addWidget(cant_lbl)
            info_row.addStretch()

            total_item = item['cantidad'] * item['precio_unitario']
            total_lbl = QLabel(f"${total_item:,.0f}")
            total_lbl.setStyleSheet(
                f"font-size: 9pt; font-weight: 500; color: {COLORS['primary']}; {transparent}"
            )
            info_row.addWidget(total_lbl)
            fl.addLayout(info_row)

            btn_row = QHBoxLayout()
            btn_row.setSpacing(4)

            btn_edit = QPushButton("Editar")
            btn_edit.setCursor(QCursor(Qt.PointingHandCursor))
            btn_edit.setStyleSheet(f"""
                QPushButton {{
                    background: {COLORS['info']}; color: white;
                    border: none; border-radius: 3px;
                    padding: 3px 8px; font-size: 8pt;
                }}
                QPushButton:hover {{ background: #0891b2; }}
            """)
            btn_edit.clicked.connect(lambda checked, i=idx: self.editar_cantidad_item(i))
            btn_row.addWidget(btn_edit)

            btn_del = QPushButton("Quitar")
            btn_del.setCursor(QCursor(Qt.PointingHandCursor))
            btn_del.setStyleSheet(f"""
                QPushButton {{
                    background: {COLORS['danger']}; color: white;
                    border: none; border-radius: 3px;
                    padding: 3px 8px; font-size: 8pt;
                }}
                QPushButton:hover {{ background: {COLORS['danger_dark']}; }}
            """)
            btn_del.clicked.connect(lambda checked, i=idx: self.quitar_del_carrito(i))
            btn_row.addWidget(btn_del)

            btn_row.addStretch()
            fl.addLayout(btn_row)

            self.carrito_layout.addWidget(item_frame)

        self.carrito_layout.addStretch()
        self._calcular_totales()

    def _calcular_totales(self):
        subtotal = sum(it['cantidad'] * it['precio_unitario'] for it in self.carrito)
        try:
            descuento_monto = float(self.descuento_entry.text() or 0)
        except Exception:
            descuento_monto = 0

        total = subtotal - descuento_monto
        self.subtotal_label.setText(f"${subtotal:,.0f}")
        self.total_label.setText(f"${total:,.0f}")

    def editar_cantidad_item(self, idx):
        if idx >= len(self.carrito):
            return
        item = self.carrito[idx]
        dialogo = DialogoCantidadModern(self, item['producto'], self.db_manager)
        dialogo.exec()
        if dialogo.cantidad:
            item['cantidad'] = dialogo.cantidad
            self._actualizar_carrito_ui()

    def quitar_del_carrito(self, idx):
        if idx >= len(self.carrito):
            return
        del self.carrito[idx]
        self._actualizar_carrito_ui()

    def limpiar_carrito(self):
        if self.carrito:
            r = QMessageBox.question(self, "Confirmar", "¿Limpiar todo el carrito?")
            if r == QMessageBox.Yes:
                self.carrito = []
                self._actualizar_carrito_ui()

    def seleccionar_metodo_pago(self, metodo):
        self.metodo_pago = metodo
        self._actualizar_botones_metodo_pago()

    def _actualizar_botones_metodo_pago(self):
        for valor, boton in self.metodo_botones.items():
            if valor == self.metodo_pago:
                boton.setStyleSheet(f"""
                    QPushButton {{
                        background: {COLORS['primary']}; color: white;
                        border: none; border-radius: 4px;
                        padding: 6px; font-size: 9pt; font-weight: 500;
                    }}
                """)
            else:
                boton.setStyleSheet(f"""
                    QPushButton {{
                        background: {COLORS['bg_secondary']}; color: {COLORS['text_primary']};
                        border: 1px solid #d1d5db; border-radius: 4px;
                        padding: 6px; font-size: 9pt;
                    }}
                    QPushButton:hover {{ background: #e2e8f0; }}
                """)

    def seleccionar_cliente(self):
        dlg = DialogoSeleccionCliente(self, self.clientes_repo)
        if dlg.exec() == QDialog.Accepted:
            self.cliente_seleccionado = dlg.cliente_seleccionado
            if self.cliente_seleccionado:
                self.cliente_label.setText(self.cliente_seleccionado.nombre)
            else:
                self.cliente_label.setText("Cliente General")

    # =====================================================================
    # PROCESAR VENTA
    # =====================================================================

    def procesar_venta(self):
        if not self.carrito:
            QMessageBox.warning(self, "Carrito vacío", "Agregue productos al carrito")
            return

        try:
            metodo_pago = self.metodo_pago

            if metodo_pago == 'CREDITO' and not self.cliente_seleccionado:
                cliente_id = self._solicitar_datos_cliente_credito()
                if not cliente_id:
                    return
            else:
                cliente_id = self.cliente_seleccionado.id if self.cliente_seleccionado else None

            if metodo_pago == 'CREDITO' and cliente_id and self.cuentas_service:
                facturas_pendientes = self._obtener_facturas_pendientes_cliente(cliente_id)
                if facturas_pendientes:
                    usar_existente = self._preguntar_agregar_a_factura(facturas_pendientes)
                    if usar_existente:
                        self._agregar_a_factura_existente(usar_existente)
                        return

            try:
                descuento = float(self.descuento_entry.text() or 0)
            except Exception:
                descuento = 0

            items = []
            mezclas_info = []
            for item in self.carrito:
                if item.get('es_mezcla'):
                    componentes = item.get('mezcla_componentes', [])
                    precio_mezcla = item['precio_unitario'] * item['cantidad']
                    costo_total_comps = sum(c.get('costo', 0) for c in componentes)

                    for comp in componentes:
                        if costo_total_comps > 0:
                            proporcion = comp.get('costo', 0) / costo_total_comps
                        else:
                            proporcion = 1.0 / len(componentes) if componentes else 1.0

                        precio_proporcional = (
                            precio_mezcla * proporcion / comp['cantidad']
                            if comp['cantidad'] > 0 else 0
                        )

                        items.append({
                            'producto_id': comp['producto_id'],
                            'cantidad': comp['cantidad'],
                            'precio_unitario': precio_proporcional,
                            'descuento': 0,
                        })

                    nombre = item['producto']['nombre']
                    comps_desc = ', '.join(
                        f"{c['producto_nombre']} ({c.get('cantidad_litros', c['cantidad']):.3f}L)"
                        for c in componentes
                    )
                    mezclas_info.append(f"MEZCLA: {nombre} = [{comps_desc}]")
                else:
                    items.append({
                        'producto_id': item['producto']['id'],
                        'cantidad': item['cantidad'],
                        'precio_unitario': item['precio_unitario'],
                        'descuento': item.get('descuento', 0),
                    })

            obs_mezcla = ' | '.join(mezclas_info) if mezclas_info else None

            exito, mensaje, venta = self.ventas_service.registrar_venta(
                items=items,
                cliente_id=cliente_id,
                metodo_pago=metodo_pago,
                descuento_general=descuento,
                observaciones=obs_mezcla,
            )

            if exito:
                self._checkout_act_id = None
                detalles_impresion = []
                for item in self.carrito:
                    det = {
                        'producto_nombre': item['producto'].get('nombre', 'Producto'),
                        'cantidad': item['cantidad'],
                        'precio_unitario': item['precio_unitario'],
                        'subtotal': item['cantidad'] * item['precio_unitario'],
                    }
                    if item.get('es_mezcla'):
                        det['es_mezcla'] = True
                        comps = item.get('mezcla_componentes', [])
                        det['mezcla_componentes'] = [
                            f"{c['producto_nombre']} ({c.get('cantidad_litros', c['cantidad']):.3f}L)"
                            for c in comps
                        ]
                        det['mezcla_volumen'] = sum(
                            c.get('cantidad_litros', c['cantidad']) for c in comps
                        )
                    detalles_impresion.append(det)

                venta_data_impresion = {
                    'numero_factura': venta.numero_factura,
                    'fecha': str(venta.fecha) if venta.fecha else '',
                    'total': venta.total,
                    'subtotal': venta.subtotal,
                    'descuento': venta.descuento,
                    'iva': getattr(venta, 'iva', 0) or 0,
                    'metodo_pago': metodo_pago,
                    'cliente_nombre': (
                        self.cliente_seleccionado.nombre
                        if self.cliente_seleccionado else 'Cliente General'
                    ),
                }

                self._mostrar_dialogo_venta_exitosa(venta_data_impresion, detalles_impresion)
                self.nueva_venta()
                self.cargar_productos()
                # Notificar a caja para actualizar resumen
                if self.callback_actualizar_caja:
                    try:
                        self.callback_actualizar_caja()
                    except Exception as e:
                        print(f"[VENTAS] Error al llamar callback actualizar caja: {e}")
                self.venta_completada.emit()
            else:
                if mensaje and str(mensaje).startswith("INVENTORY_UNKNOWN"):
                    QMessageBox.warning(
                        self,
                        "Inventario pendiente",
                        "La venta no se confirmó en el coordinador. "
                        "Reintente la misma operación; no cree otra venta.",
                    )
                    return
                QMessageBox.critical(self, "Error", mensaje)

        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Error al procesar venta: {str(e)}")

    # -- Diálogo venta exitosa -----------------------------------------------

    def _mostrar_dialogo_venta_exitosa(self, venta_data, detalles):
        dlg = QDialog(self)
        dlg.setWindowTitle("Venta Exitosa")
        dlg.setFixedSize(420, 310)
        dlg.setModal(True)

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        content = QWidget()
        content.setStyleSheet("background: white;")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(30, 20, 30, 20)
        cl.setSpacing(8)

        transparent = "background: transparent; border: none;"

        title = QLabel("✅ VENTA EXITOSA")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"font-size: 16pt; font-weight: 500; color: #10b981; {transparent}")
        cl.addWidget(title)

        numero = venta_data.get('numero_factura', '')
        total = venta_data.get('total', 0)
        metodo = venta_data.get('metodo_pago', 'EFECTIVO').replace('_', ' ')

        for text in [
            f"Factura: {numero}",
            f"Total: ${total:,.0f}",
            f"Método: {metodo}",
        ]:
            lbl = QLabel(text)
            bold = "font-weight: 500;" if "Total" in text else ""
            lbl.setStyleSheet(f"font-size: 11pt; {bold} {transparent}")
            cl.addWidget(lbl)

        note = QLabel("La venta ha sido registrada en Movimientos.")
        note.setStyleSheet(f"font-size: 9pt; color: #64748b; {transparent}")
        cl.addWidget(note)

        cl.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        btn_print = QPushButton("🖨️ Imprimir Factura")
        btn_print.setCursor(QCursor(Qt.PointingHandCursor))
        btn_print.setStyleSheet("""
            QPushButton {
                background: #2563eb; color: white; border: none;
                border-radius: 5px; padding: 8px 16px;
                font-size: 10pt; font-weight: 500;
            }
            QPushButton:hover { background: #1d4ed8; }
        """)
        btn_print.clicked.connect(lambda: self._imprimir_factura_venta(dlg, venta_data, detalles))
        btn_row.addWidget(btn_print)

        btn_row.addStretch()

        btn_ok = QPushButton("Aceptar")
        btn_ok.setCursor(QCursor(Qt.PointingHandCursor))
        btn_ok.setStyleSheet("""
            QPushButton {
                background: #64748b; color: white; border: none;
                border-radius: 5px; padding: 8px 24px; font-size: 10pt;
            }
            QPushButton:hover { background: #475569; }
        """)
        btn_ok.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_ok)

        cl.addLayout(btn_row)
        lay.addWidget(content)
        dlg.exec()

    def _imprimir_factura_venta(self, dialogo, venta_data, detalles):
        from ui.imprimir_factura import imprimir_factura
        imprimir_factura(dialogo, venta_data, detalles)

    # -- Cancelar / Nueva venta ----------------------------------------------

    def cancelar_venta(self):
        if self.carrito:
            r = QMessageBox.question(self, "Confirmar", "¿Cancelar la venta actual?")
            if r == QMessageBox.Yes:
                self.nueva_venta()

    def nueva_venta(self):
        self.carrito = []
        self.cliente_seleccionado = None
        self._checkout_act_id = None
        self.cliente_label.setText("Cliente General")
        self.descuento_entry.setText("0")
        self.metodo_pago = "EFECTIVO"
        self._actualizar_botones_metodo_pago()
        self._actualizar_carrito_ui()
        self.search_entry.clear()

    # -- Mezcla pintura ------------------------------------------------------

    def abrir_mezcla_pintura(self):
        from ui.mezcla_ui import VentanaMezclaPintura

        dialogo = VentanaMezclaPintura(
            self, self.mezclas_service, self.productos_repo, self.db_manager
        )
        dialogo.exec()

        if dialogo.resultado:
            self._agregar_mezcla_al_carrito(dialogo.resultado)

    def _agregar_mezcla_al_carrito(self, mezcla):
        self.carrito.append({
            'producto': {
                'id': None,
                'nombre': mezcla['nombre'],
                'precio_venta': mezcla['precio_venta'],
                'stock': 999,
                'marca': '',
            },
            'cantidad': 1,
            'precio_unitario': mezcla['precio_venta'],
            'descuento': 0,
            'es_mezcla': True,
            'mezcla_componentes': mezcla['componentes'],
            'mezcla_formula_id': mezcla.get('formula_id'),
        })
        self._actualizar_carrito_ui()

    # =====================================================================
    # VENTAS A CRÉDITO
    # =====================================================================

    def ver_ventas_credito(self):
        if not self.cuentas_service:
            QMessageBox.warning(self, "Advertencia",
                                "Servicio de cuentas por cobrar no disponible")
            return

        ventas = self.cuentas_service.obtener_ventas_credito_pendientes()
        if not ventas:
            QMessageBox.information(self, "Información",
                                    "No hay ventas a crédito pendientes")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Ventas a Crédito Pendientes")
        dlg.setFixedSize(1000, 600)
        dlg.setModal(True)

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        transparent = "background: transparent; border: none;"

        # Header
        hdr = QFrame()
        hdr.setFixedHeight(60)
        hdr.setStyleSheet(f"background: {COLORS['primary']};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(20, 0, 20, 0)
        t = QLabel("💳 Ventas a Crédito Pendientes")
        t.setStyleSheet(f"font-size: 16pt; font-weight: 500; color: white; {transparent}")
        hl.addWidget(t)
        lay.addWidget(hdr)

        # Totales
        total_deuda = sum(v['saldo_pendiente'] for v in ventas)
        total_pagado = sum(v['monto_pagado'] for v in ventas)

        tot_bar = QWidget()
        tot_bar.setStyleSheet("background: white;")
        tbl = QHBoxLayout(tot_bar)
        tbl.setContentsMargins(20, 15, 20, 15)

        for txt, color in [
            (f"Total por Cobrar: ${total_deuda:,.0f}", '#DC2626'),
            (f"Total Abonado: ${total_pagado:,.0f}", '#059669'),
            (f"Facturas: {len(ventas)}", COLORS['text_primary']),
        ]:
            l = QLabel(txt)
            weight = "font-weight: 500;" if "Cobrar" in txt else ""
            l.setStyleSheet(f"font-size: 12pt; {weight} color: {color}; {transparent}")
            tbl.addWidget(l)

        tbl.addStretch()
        lay.addWidget(tot_bar)

        # Table
        columnas = ['Factura', 'Fecha', 'Cliente', 'Total', 'Pagado', 'Saldo', 'Estado', 'Días']
        anchos = [100, 100, 150, 90, 90, 90, 110, 60]

        table = QTableWidget(len(ventas), len(columnas))
        table.setHorizontalHeaderLabels(columnas)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)

        header_view = table.horizontalHeader()
        for i, w in enumerate(anchos):
            table.setColumnWidth(i, w)
        header_view.setStretchLastSection(True)

        self._credito_ids = []

        for row_idx, venta in enumerate(ventas):
            self._credito_ids.append(venta['id'])

            estado_emoji = {
                'PENDIENTE': '⏳', 'PARCIAL': '🟡', 'PAGADO': '✅'
            }.get(venta['estado_pago'], '')

            valores = [
                venta['numero_factura'],
                venta['fecha'][:10] if venta['fecha'] else '',
                venta['cliente_nombre'],
                f"${venta['total']:,.0f}",
                f"${venta['monto_pagado']:,.0f}",
                f"${venta['saldo_pendiente']:,.0f}",
                f"{estado_emoji} {venta['estado_pago']}",
                f"{venta['dias_transcurridos']} días",
            ]

            if venta['dias_transcurridos'] > 60:
                bg = '#fee2e2'
                fg = '#991b1b'
            elif venta['dias_transcurridos'] > 30:
                bg = '#fef3c7'
                fg = '#92400e'
            else:
                bg = 'white'
                fg = COLORS['text_primary']

            for col_idx, val in enumerate(valores):
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignCenter)
                item.setBackground(QColor(bg))
                item.setForeground(QColor(fg))
                table.setItem(row_idx, col_idx, item)

        lay.addWidget(table, 1)

        # Buttons
        btn_frame = QWidget()
        btn_frame.setStyleSheet("background: white;")
        bfl = QHBoxLayout(btn_frame)
        bfl.setContentsMargins(20, 15, 20, 15)

        def registrar_cobro():
            rows = table.selectionModel().selectedRows()
            if not rows:
                QMessageBox.warning(dlg, "Advertencia", "Seleccione una factura")
                return
            row_idx = rows[0].row()
            id_venta = self._credito_ids[row_idx]
            numero_factura = table.item(row_idx, 0).text()
            total_txt = table.item(row_idx, 3).text().replace('$', '').replace(',', '')
            saldo_txt = table.item(row_idx, 5).text().replace('$', '').replace(',', '')
            total_val = float(total_txt)
            saldo_val = float(saldo_txt)
            self._abrir_modal_abono_venta(id_venta, numero_factura, total_val, saldo_val, dlg)

        btn_cobro = QPushButton("💰 Registrar Cobro")
        btn_cobro.setCursor(QCursor(Qt.PointingHandCursor))
        btn_cobro.setStyleSheet("""
            QPushButton {
                background: #059669; color: white; border: none;
                border-radius: 5px; padding: 10px 20px;
                font-size: 10pt; font-weight: 500;
            }
            QPushButton:hover { background: #047857; }
        """)
        btn_cobro.clicked.connect(registrar_cobro)
        bfl.addWidget(btn_cobro)

        bfl.addStretch()

        btn_close = QPushButton("Cerrar")
        btn_close.setCursor(QCursor(Qt.PointingHandCursor))
        btn_close.setStyleSheet("""
            QPushButton {
                background: #6B7280; color: white; border: none;
                border-radius: 5px; padding: 10px 20px; font-size: 10pt;
            }
            QPushButton:hover { background: #4B5563; }
        """)
        btn_close.clicked.connect(dlg.accept)
        bfl.addWidget(btn_close)

        lay.addWidget(btn_frame)
        dlg.exec()

    # -- Modal abono ---------------------------------------------------------

    def _abrir_modal_abono_venta(self, id_venta, numero_factura, total, saldo, parent_window):
        from models import AbonoVenta
        from datetime import datetime

        if not self.abonos_repo:
            QMessageBox.warning(self, "Advertencia",
                                "Repositorio de abonos no disponible")
            return

        try:
            dlg = QDialog(parent_window)
            dlg.setWindowTitle("Registrar Cobro a Factura")
            dlg.setFixedSize(550, 450)
            dlg.setModal(True)

            transparent = "background: transparent; border: none;"

            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(15, 10, 15, 10)
            lay.setSpacing(10)

            # Info group
            info_grp = QGroupBox("Información de Factura")
            ig_lay = QVBoxLayout(info_grp)

            for txt in [f"Factura: {numero_factura}", f"Total: ${total:,.0f}"]:
                ig_lay.addWidget(QLabel(txt))

            saldo_actual = [saldo]

            saldo_label = QLabel(f"Saldo Pendiente: ${saldo_actual[0]:,.0f}")
            saldo_label.setStyleSheet(
                f"font-size: 12pt; font-weight: 500; color: #DC2626; {transparent}"
            )
            ig_lay.addWidget(saldo_label)
            lay.addWidget(info_grp)

            # Form group
            form_grp = QGroupBox("Datos del Cobro")
            fg_lay = QGridLayout(form_grp)

            fg_lay.addWidget(QLabel("Monto Cobrado:"), 0, 0)
            monto_entry = QLineEdit()
            monto_entry.setFocus()
            fg_lay.addWidget(monto_entry, 0, 1)

            btn_todo = QPushButton("Pagar Todo")
            btn_todo.setCursor(QCursor(Qt.PointingHandCursor))
            btn_todo.setStyleSheet("""
                QPushButton {
                    background: #10B981; color: white; border: none;
                    border-radius: 4px; padding: 4px 10px; font-size: 9pt;
                }
            """)
            btn_todo.clicked.connect(lambda: monto_entry.setText(str(int(saldo_actual[0]))))
            fg_lay.addWidget(btn_todo, 0, 2)

            fg_lay.addWidget(QLabel("Tipo de Pago:"), 1, 0)
            tipo_combo = QComboBox()
            tipos = ["Efectivo", "Transferencia", "Cheque",
                     "Tarjeta Débito", "Tarjeta Crédito", "Otro"]
            tipo_combo.addItems(tipos)
            fg_lay.addWidget(tipo_combo, 1, 1)

            fg_lay.addWidget(QLabel("Nº Comprobante:"), 2, 0)
            comprobante_entry = QLineEdit()
            fg_lay.addWidget(comprobante_entry, 2, 1)

            lay.addWidget(form_grp, 1)

            def guardar_abono():
                try:
                    monto = float(monto_entry.text().strip())
                    if monto <= 0:
                        QMessageBox.warning(dlg, "Advertencia",
                                            "El monto debe ser mayor a cero")
                        return
                    if monto > saldo_actual[0]:
                        QMessageBox.warning(
                            dlg, "Advertencia",
                            f"El monto no puede exceder el saldo pendiente "
                            f"(${saldo_actual[0]:,.0f})"
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
                    self.abonos_repo.crear_abono(abono)
                    saldo_actual[0] -= monto

                    QMessageBox.information(
                        dlg, "Éxito",
                        f"Cobro de ${monto:,.0f} registrado correctamente\n"
                        f"Nuevo saldo pendiente: ${saldo_actual[0]:,.0f}"
                    )

                    if saldo_actual[0] <= 0:
                        dlg.accept()
                        parent_window.accept()
                    else:
                        saldo_label.setText(
                            f"Saldo Pendiente: ${saldo_actual[0]:,.0f}"
                        )
                        monto_entry.clear()
                        comprobante_entry.clear()
                        monto_entry.setFocus()
                except ValueError:
                    QMessageBox.critical(dlg, "Error", "Ingrese un monto válido")

            # Buttons
            btn_row = QHBoxLayout()
            btn_save = QPushButton("💾 Guardar Cobro")
            btn_save.setCursor(QCursor(Qt.PointingHandCursor))
            btn_save.setStyleSheet("""
                QPushButton {
                    background: #059669; color: white; border: none;
                    border-radius: 5px; padding: 10px 20px;
                    font-size: 10pt; font-weight: 500;
                }
                QPushButton:hover { background: #047857; }
            """)
            btn_save.clicked.connect(guardar_abono)
            btn_row.addWidget(btn_save)

            btn_row.addStretch()

            btn_cancel = QPushButton("Cancelar")
            btn_cancel.setCursor(QCursor(Qt.PointingHandCursor))
            btn_cancel.setStyleSheet("""
                QPushButton {
                    background: #DC2626; color: white; border: none;
                    border-radius: 5px; padding: 10px 20px; font-size: 10pt;
                }
                QPushButton:hover { background: #B91C1C; }
            """)
            btn_cancel.clicked.connect(dlg.reject)
            btn_row.addWidget(btn_cancel)

            lay.addLayout(btn_row)
            dlg.exec()

        except Exception as e:
            QMessageBox.critical(self, "Error",
                                 f"Error al abrir modal de cobro: {e}")

    # =====================================================================
    # CRÉDITO: solicitar datos cliente
    # =====================================================================

    def _solicitar_datos_cliente_credito(self):
        from models import Cliente
        from PySide6.QtWidgets import QRadioButton, QButtonGroup, QListWidget, QListWidgetItem

        dlg = QDialog(self)
        dlg.setWindowTitle("Venta a Crédito - Cliente")
        dlg.setFixedSize(560, 560)
        dlg.setModal(True)

        transparent = "background: transparent; border: none;"
        resultado = {'cliente_id': None}

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ── Header ──
        hdr = QFrame()
        hdr.setFixedHeight(56)
        hdr.setStyleSheet(f"background: {COLORS['warning']};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(20, 0, 20, 0)
        t = QLabel("💳 Venta a Crédito")
        t.setStyleSheet(f"font-size: 15pt; font-weight: 500; color: white; {transparent}")
        hl.addWidget(t)
        lay.addWidget(hdr)

        # ── Tabs de modo ──
        mode_bar = QWidget()
        mode_bar.setStyleSheet("background: #fef3c7; border-bottom: 1px solid #fcd34d;")
        mbl = QHBoxLayout(mode_bar)
        mbl.setContentsMargins(20, 8, 20, 8)
        mbl.setSpacing(16)

        radio_existente = QRadioButton("Seleccionar cliente existente")
        radio_nuevo = QRadioButton("Registrar nuevo cliente")
        radio_existente.setStyleSheet(f"font-size: 10pt; color: {COLORS['text_primary']}; background: transparent;")
        radio_nuevo.setStyleSheet(f"font-size: 10pt; color: {COLORS['text_primary']}; background: transparent;")
        radio_existente.setChecked(True)

        btn_group = QButtonGroup(dlg)
        btn_group.addButton(radio_existente, 0)
        btn_group.addButton(radio_nuevo, 1)

        mbl.addWidget(radio_existente)
        mbl.addWidget(radio_nuevo)
        mbl.addStretch()
        lay.addWidget(mode_bar)

        # ── Stack con los dos paneles ──
        from PySide6.QtWidgets import QStackedWidget as _SW
        stack = _SW()
        stack.setStyleSheet("background: white;")
        lay.addWidget(stack, 1)

        # ──────────────────────────────
        # Panel 0 – Cliente existente
        # ──────────────────────────────
        panel_exist = QWidget()
        panel_exist.setStyleSheet("background: white;")
        pel = QVBoxLayout(panel_exist)
        pel.setContentsMargins(20, 14, 20, 10)
        pel.setSpacing(8)

        lbl_buscar = QLabel("Buscar por nombre o documento:")
        lbl_buscar.setStyleSheet(f"font-size: 9pt; color: {COLORS['text_secondary']}; {transparent}")
        pel.addWidget(lbl_buscar)

        buscar_entry = QLineEdit()
        buscar_entry.setPlaceholderText("Escriba para filtrar clientes...")
        buscar_entry.setStyleSheet(
            "QLineEdit { border: 1px solid #d1d5db; border-radius: 6px; padding: 7px 10px; font-size: 10pt; }"
            "QLineEdit:focus { border-color: #f59e0b; }"
        )
        pel.addWidget(buscar_entry)

        lista_clientes = QListWidget()
        lista_clientes.setStyleSheet(
            "QListWidget { border: 1px solid #e2e8f0; border-radius: 6px; font-size: 10pt; }"
            "QListWidget::item { padding: 8px 10px; }"
            "QListWidget::item:selected { background: #fef3c7; color: #92400e; }"
            "QListWidget::item:hover { background: #fafafa; }"
        )
        lista_clientes.setMinimumHeight(280)
        pel.addWidget(lista_clientes, 1)

        lbl_sel = QLabel("")
        lbl_sel.setStyleSheet(
            f"font-size: 9pt; color: {COLORS['text_light']}; {transparent}"
        )
        pel.addWidget(lbl_sel)

        # Cache de clientes en memoria
        _todos_clientes = []

        def _cargar_clientes(criterio=""):
            nonlocal _todos_clientes
            try:
                if criterio:
                    clientes = self.clientes_repo.buscar_clientes(criterio)
                else:
                    clientes = self.clientes_repo.listar_clientes()
                _todos_clientes = clientes
            except Exception:
                _todos_clientes = []
            lista_clientes.clear()
            for c in _todos_clientes:
                item = QListWidgetItem(f"  {c.nombre}   ·   {c.telefono or '—'}")
                item.setData(Qt.UserRole, c)
                lista_clientes.addItem(item)
            if not _todos_clientes:
                lista_clientes.addItem("  Sin resultados")

        _cargar_clientes()

        _buscar_timer = QTimer(dlg)
        _buscar_timer.setSingleShot(True)
        _buscar_timer.setInterval(280)
        _buscar_timer.timeout.connect(lambda: _cargar_clientes(buscar_entry.text().strip()))
        buscar_entry.textChanged.connect(lambda _: _buscar_timer.start())

        def _on_item_seleccionado():
            item = lista_clientes.currentItem()
            if item:
                c = item.data(Qt.UserRole)
                if c:
                    lbl_sel.setText(f"✓ Seleccionado: {c.nombre}")
                    lbl_sel.setStyleSheet(f"font-size: 9pt; color: {COLORS['success']}; {transparent}")

        lista_clientes.currentItemChanged.connect(lambda *_: _on_item_seleccionado())

        stack.addWidget(panel_exist)

        # ──────────────────────────────
        # Panel 1 – Nuevo cliente
        # ──────────────────────────────
        panel_nuevo = QWidget()
        panel_nuevo.setStyleSheet("background: white;")
        pnl = QVBoxLayout(panel_nuevo)
        pnl.setContentsMargins(20, 14, 20, 10)
        pnl.setSpacing(8)

        form_grp = QGroupBox("Datos del nuevo cliente")
        fgl = QGridLayout(form_grp)
        fgl.setHorizontalSpacing(10)
        fgl.setVerticalSpacing(10)

        fgl.addWidget(QLabel("Nombre Completo *:"), 0, 0)
        nombre_entry = QLineEdit()
        fgl.addWidget(nombre_entry, 0, 1)

        fgl.addWidget(QLabel("Teléfono *:"), 1, 0)
        telefono_entry = QLineEdit()
        fgl.addWidget(telefono_entry, 1, 1)

        fgl.addWidget(QLabel("Documento:"), 2, 0)
        documento_entry = QLineEdit()
        fgl.addWidget(documento_entry, 2, 1)

        pnl.addWidget(form_grp)
        pnl.addStretch()

        stack.addWidget(panel_nuevo)

        # ── Cambio de modo ──
        def _cambiar_modo(id_):
            stack.setCurrentIndex(id_)
            if id_ == 1:
                nombre_entry.setFocus()

        btn_group.idClicked.connect(_cambiar_modo)

        # ── Botones ──
        btn_w = QWidget()
        btn_w.setStyleSheet("background: white; border-top: 1px solid #e2e8f0;")
        bwl = QHBoxLayout(btn_w)
        bwl.setContentsMargins(20, 12, 20, 16)
        bwl.setSpacing(10)

        btn_save = QPushButton("✓ Continuar")
        btn_save.setCursor(QCursor(Qt.PointingHandCursor))
        btn_save.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['success']}; color: white; border: none;
                border-radius: 5px; padding: 11px 28px;
                font-size: 10pt; font-weight: 500;
            }}
            QPushButton:hover {{ background: {COLORS['success_dark']}; }}
        """)

        def guardar_y_continuar():
            # Modo existente
            if radio_existente.isChecked():
                item = lista_clientes.currentItem()
                if not item:
                    QMessageBox.warning(dlg, "Sin selección",
                                        "Seleccione un cliente de la lista o cambie a 'Registrar nuevo cliente'.")
                    return
                c = item.data(Qt.UserRole)
                if not c:
                    QMessageBox.warning(dlg, "Sin selección",
                                        "Seleccione un cliente válido de la lista.")
                    return
                resultado['cliente_id'] = c.id
                dlg.accept()
                return

            # Modo nuevo
            nombre = nombre_entry.text().strip()
            telefono = telefono_entry.text().strip()
            documento = documento_entry.text().strip()
            if not nombre:
                QMessageBox.warning(dlg, "Campo requerido", "Ingrese el nombre del cliente")
                nombre_entry.setFocus()
                return
            if not telefono:
                QMessageBox.warning(dlg, "Campo requerido", "Ingrese el teléfono del cliente")
                telefono_entry.setFocus()
                return
            try:
                nuevo_cliente = Cliente(
                    tipo_documento='CC',
                    numero_documento=documento if documento else f'CLI-{telefono[-4:]}',
                    nombre=nombre,
                    telefono=telefono,
                    email=None,
                    direccion=None,
                    ciudad=None,
                    limite_credito=0,
                    clasificacion='NORMAL',
                    descuento_default=0,
                    activo=True,
                )
                exito, mensaje, cliente_id = self.clientes_repo.crear_cliente(nuevo_cliente)
                if exito:
                    resultado['cliente_id'] = cliente_id
                    dlg.accept()
                else:
                    QMessageBox.critical(dlg, "Error",
                                         f"No se pudo crear el cliente: {mensaje}")
            except Exception as e:
                QMessageBox.critical(dlg, "Error", f"Error al guardar cliente: {e}")

        btn_save.clicked.connect(guardar_y_continuar)
        bwl.addWidget(btn_save)
        bwl.addStretch()

        btn_cancel = QPushButton("✕ Cancelar")
        btn_cancel.setCursor(QCursor(Qt.PointingHandCursor))
        btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['danger']}; color: white; border: none;
                border-radius: 5px; padding: 11px 28px; font-size: 10pt;
            }}
            QPushButton:hover {{ background: {COLORS['danger_dark']}; }}
        """)
        btn_cancel.clicked.connect(dlg.reject)
        bwl.addWidget(btn_cancel)

        lay.addWidget(btn_w)

        from ui.widgets import hacer_dialogo_responsivo
        hacer_dialogo_responsivo(dlg, 560, 560)
        dlg.exec()
        return resultado['cliente_id']

    # =====================================================================
    # CRÉDITO: facturas pendientes
    # =====================================================================

    def _obtener_facturas_pendientes_cliente(self, cliente_id):
        try:
            conn = self.ventas_service.db.conectar()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, numero_factura, fecha, total, monto_pagado,
                       saldo_pendiente, estado_pago
                FROM ventas
                WHERE cliente_id = ?
                AND metodo_pago = 'CREDITO'
                AND estado_pago IN ('PENDIENTE', 'PARCIAL')
                ORDER BY fecha DESC
            ''', (cliente_id,))
            facturas = cursor.fetchall()
            conn.close()
            return [dict(f) for f in facturas]
        except Exception as e:
            print(f"Error al obtener facturas: {e}")
            return []

    def _preguntar_agregar_a_factura(self, facturas_pendientes):
        dlg = QDialog(self)
        dlg.setWindowTitle("Facturas Pendientes")
        dlg.setFixedSize(700, 500)
        dlg.setModal(True)

        transparent = "background: transparent; border: none;"
        resultado = {'factura_id': None}

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Header
        hdr = QFrame()
        hdr.setStyleSheet(f"background: {COLORS['warning']};")
        hl = QVBoxLayout(hdr)
        hl.setContentsMargins(20, 15, 20, 15)
        t = QLabel("⚠️ Cliente con Facturas Pendientes")
        t.setStyleSheet(f"font-size: 14pt; font-weight: 500; color: white; {transparent}")
        hl.addWidget(t)
        st = QLabel("El cliente tiene facturas de crédito sin pagar completamente")
        st.setStyleSheet(f"font-size: 10pt; color: white; {transparent}")
        hl.addWidget(st)
        lay.addWidget(hdr)

        # Content
        content = QWidget()
        content.setStyleSheet("background: white;")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(20, 15, 20, 15)
        cl.setSpacing(10)

        q_lbl = QLabel(
            "¿Desea agregar los productos a una factura existente o crear una nueva?"
        )
        q_lbl.setStyleSheet(f"font-size: 10pt; font-weight: 500; {transparent}")
        q_lbl.setWordWrap(True)
        cl.addWidget(q_lbl)

        columnas = ['Factura', 'Fecha', 'Total', 'Pagado', 'Saldo', 'Estado']
        anchos = [120, 100, 90, 90, 90, 110]

        table = QTableWidget(len(facturas_pendientes), len(columnas))
        table.setHorizontalHeaderLabels(columnas)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        for i, w in enumerate(anchos):
            table.setColumnWidth(i, w)
        table.horizontalHeader().setStretchLastSection(True)

        self._pending_ids = []
        for row_idx, factura in enumerate(facturas_pendientes):
            self._pending_ids.append(factura['id'])
            valores = [
                factura['numero_factura'],
                factura['fecha'][:10],
                f"${factura['total']:,.0f}",
                f"${factura.get('monto_pagado', 0):,.0f}",
                f"${factura.get('saldo_pendiente', factura['total']):,.0f}",
                factura['estado_pago'],
            ]
            bg = '#fee2e2' if factura['estado_pago'] == 'PENDIENTE' else '#fef3c7'
            for col_idx, val in enumerate(valores):
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignCenter)
                item.setBackground(QColor(bg))
                table.setItem(row_idx, col_idx, item)

        cl.addWidget(table, 1)

        tip = QLabel(
            "💡 Seleccione una factura y haga clic en 'Agregar a Factura', "
            "o cree una nueva factura"
        )
        tip.setStyleSheet(f"font-size: 9pt; color: {COLORS['text_secondary']}; {transparent}")
        tip.setWordWrap(True)
        cl.addWidget(tip)

        lay.addWidget(content, 1)

        def agregar_a_seleccionada():
            rows = table.selectionModel().selectedRows()
            if not rows:
                QMessageBox.warning(dlg, "Advertencia", "Seleccione una factura")
                return
            row_idx = rows[0].row()
            resultado['factura_id'] = self._pending_ids[row_idx]
            dlg.accept()

        def crear_nueva():
            resultado['factura_id'] = None
            dlg.accept()

        btn_w = QWidget()
        btn_w.setStyleSheet("background: white;")
        bwl = QHBoxLayout(btn_w)
        bwl.setContentsMargins(20, 15, 20, 15)

        btn_add = QPushButton("➕ Agregar a Factura Seleccionada")
        btn_add.setCursor(QCursor(Qt.PointingHandCursor))
        btn_add.setStyleSheet("""
            QPushButton {
                background: #059669; color: white; border: none;
                border-radius: 5px; padding: 12px 20px;
                font-size: 10pt; font-weight: 500;
            }
            QPushButton:hover { background: #047857; }
        """)
        btn_add.clicked.connect(agregar_a_seleccionada)
        bwl.addWidget(btn_add)

        bwl.addStretch()

        btn_new = QPushButton("📄 Crear Nueva Factura")
        btn_new.setCursor(QCursor(Qt.PointingHandCursor))
        btn_new.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['primary']}; color: white; border: none;
                border-radius: 5px; padding: 12px 20px; font-size: 10pt;
            }}
            QPushButton:hover {{ background: {COLORS['primary_dark']}; }}
        """)
        btn_new.clicked.connect(crear_nueva)
        bwl.addWidget(btn_new)

        lay.addWidget(btn_w)
        from ui.widgets import hacer_dialogo_responsivo
        hacer_dialogo_responsivo(dlg, 700, 500)
        dlg.exec()
        return resultado['factura_id']

    # =====================================================================
    # CRÉDITO: agregar a factura existente
    # =====================================================================

    def _agregar_a_factura_existente(self, id_venta_existente):
        try:
            items = []
            for item in self.carrito:
                items.append({
                    'producto_id': item['producto']['id'],
                    'cantidad': item['cantidad'],
                    'precio_unitario': item['precio_unitario'],
                    'descuento': item.get('descuento', 0),
                })

            exito, mensaje = self.ventas_service.agregar_productos_a_factura(
                id_venta_existente, items
            )

            if exito:
                QMessageBox.information(
                    self, "Éxito",
                    f"Productos agregados exitosamente a la factura\n\n{mensaje}"
                )
                self.nueva_venta()
                self.cargar_productos()
            else:
                QMessageBox.critical(
                    self, "Error",
                    f"No se pudieron agregar los productos:\n{mensaje}"
                )
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self, "Error",
                f"Error al agregar productos a factura: {e}"
            )
