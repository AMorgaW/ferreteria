# -*- coding: utf-8 -*-
"""
Interfaz de usuario para gestión de productos (PySide6)
Con autocompletado, búsqueda de proveedores y distinción entre unidad base y presentación
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QCheckBox,
    QGroupBox, QGridLayout, QDialog, QMessageBox, QMenu, QFrame,
    QAbstractItemView, QSizePolicy
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor, QCursor

from models import Producto
from ui_config import COLORS, FONTS, make_font


class ProductosUI(QWidget):
    """Interfaz de gestión de productos"""

    def __init__(self, parent, productos_repo, auth, proveedores_repo=None):
        super().__init__(parent)
        self.parent_widget = parent
        self.productos_repo = productos_repo
        self.auth = auth
        self.proveedores_repo = proveedores_repo

        # Listas para autocompletado
        self.categorias_predefinidas = [
            'Elementos de Fijación',
            'Herrajes',
            'Pinturas',
            'Varillas/Tubos/Alambres',
            'Líquidos',
            'Productos en Polvo',
            'Herramientas Manuales',
            'Electrodomésticos y Equipos',
            'Materiales de Construcción',
            'Electricidad',
            'Plomería'
        ]
        self.marcas_existentes = []
        self.proveedores_lista = []

        self.cargar_datos_autocompletado()
        self.crear_ui()
        self.cargar_productos()

    def cargar_datos_autocompletado(self):
        """Carga datos para autocompletado"""
        try:
            productos = self.productos_repo.buscar_productos('')

            self.marcas_existentes = sorted(list(set(
                p['marca'] for p in productos if p.get('marca')
            )))

            if self.proveedores_repo:
                try:
                    proveedores = self.proveedores_repo.listar_proveedores(solo_activos=True)
                    self.proveedores_lista = [
                        {'id': p.id, 'nombre': p.nombre}
                        for p in proveedores
                    ]
                except Exception as e:
                    print(f"[AVISO] Error cargando proveedores: {e}")
                    import traceback
                    traceback.print_exc()
                    self.proveedores_lista = []
            else:
                print("[AVISO] proveedores_repo no disponible")
        except Exception as e:
            print(f"Error cargando datos de autocompletado: {e}")
            import traceback
            traceback.print_exc()

    # ------------------------------------------------------------------
    #  UI principal
    # ------------------------------------------------------------------
    def crear_ui(self):
        """Crea la interfaz principal"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 15)
        layout.setSpacing(10)

        # ---- Header ----
        header = QHBoxLayout()

        title_frame = QVBoxLayout()
        lbl_title = QLabel("Gestión de Productos")
        lbl_title.setFont(make_font(('Segoe UI', 18, 'bold')))
        lbl_title.setStyleSheet(f"color: {COLORS['text_primary']};")
        title_frame.addWidget(lbl_title)

        lbl_sub = QLabel("Controle el inventario global y niveles de stock crítico.")
        lbl_sub.setFont(make_font(FONTS['body']))
        lbl_sub.setStyleSheet(f"color: {COLORS['text_secondary']};")
        title_frame.addWidget(lbl_sub)

        header.addLayout(title_frame)
        header.addStretch()

        btn_nuevo = QPushButton("  +  Nuevo Producto")
        btn_nuevo.setCursor(QCursor(Qt.PointingHandCursor))
        btn_nuevo.setMinimumHeight(42)
        btn_nuevo.setMinimumWidth(180)
        btn_nuevo.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['primary']}; color: #ffffff;
                border: none; border-radius: 8px;
                padding: 10px 20px; font-size: 11pt;
                font-weight: bold; font-family: 'Segoe UI';
            }}
            QPushButton:hover {{ background: {COLORS['primary_dark']}; }}
        """)
        btn_nuevo.clicked.connect(self.crear_producto)
        header.addWidget(btn_nuevo)

        layout.addLayout(header)

        # ---- Barra de búsqueda ----
        search_bar = QHBoxLayout()

        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText("\U0001f50d  Buscar producto...")
        self.search_entry.setFont(make_font(FONTS['body']))
        self.search_entry.setMinimumHeight(38)
        self.search_entry.textChanged.connect(lambda: self.cargar_productos())
        search_bar.addWidget(self.search_entry, 1)

        btn_filtros = QPushButton("\u2630  FILTROS")
        btn_filtros.setFont(make_font(('Segoe UI', 10)))
        btn_filtros.setMinimumHeight(38)
        btn_filtros.clicked.connect(lambda: self.cargar_productos())
        search_bar.addWidget(btn_filtros)

        layout.addLayout(search_bar)

        # ---- Tabla ----
        self.columnas = ('ID', 'Nombre', 'Categoría', 'Marca', 'P. Compra',
                         'P. Venta', 'Ganancia', 'Margen %', 'Stock', 'Stock Mín.',
                         'U. Medida', 'Presentación')

        self.table = QTableWidget()
        self.table.setColumnCount(len(self.columnas))
        self.table.setHorizontalHeaderLabels(self.columnas)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)

        # Anchos
        anchos = [65, 220, 110, 100, 95, 95, 95, 80, 65, 75, 85, 120]
        for i, w in enumerate(anchos):
            self.table.setColumnWidth(i, w)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)

        self.table.setStyleSheet(f"""
            QTableWidget {{
                background: white;
                border: 1px solid #e2e8f0;
                border-radius: 6px;
                gridline-color: transparent;
            }}
            QTableWidget::item {{
                padding: 6px 8px;
            }}
            QTableWidget::item:selected {{
                background: #e0f2fe;
                color: {COLORS['text_primary']};
            }}
            QHeaderView::section {{
                background: {COLORS['table_header']};
                color: white;
                font-weight: bold;
                font-size: 9pt;
                padding: 8px 4px;
                border: none;
            }}
        """)

        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.mostrar_menu_contextual)
        self.table.doubleClicked.connect(lambda: self.editar_producto())

        layout.addWidget(self.table, 1)

    # ------------------------------------------------------------------
    #  Cargar datos
    # ------------------------------------------------------------------
    def cargar_productos(self):
        """Carga los productos en la tabla"""
        self.table.setRowCount(0)

        try:
            termino = self.search_entry.text().strip()
            productos = self.productos_repo.buscar_productos(termino)

            for p in productos:
                ganancia_neta = p['precio_venta'] - p['precio_compra']
                margen = ((ganancia_neta / p['precio_compra']) * 100) if p['precio_compra'] > 0 else 0

                if p.get('viene_en_caja'):
                    unidad_base = 'Unidad'
                    unidades_caja = p.get('unidades_por_caja', 1)
                    presentacion = f"Caja ({unidades_caja} u/caja)" if unidades_caja > 1 else "\u2014"
                else:
                    unidad_base = p.get('unidad_medida', 'Unidad')
                    if unidad_base:
                        unidad_base = unidad_base.capitalize()
                    presentacion = "\u2014"

                if p['stock'] <= 0:
                    bg_color = '#fff1f2'
                elif p['stock'] <= p['stock_minimo']:
                    bg_color = '#fffbeb'
                else:
                    bg_color = '#ffffff'

                id_formateado = f"#{p['id']}" if not str(p['id']).startswith('#') else p['id']
                ganancia_texto = f"\u2191${ganancia_neta:,.2f}" if ganancia_neta >= 0 else f"\u2193${abs(ganancia_neta):,.2f}"

                row = self.table.rowCount()
                self.table.insertRow(row)

                valores = [
                    id_formateado,
                    p['nombre'],
                    p['categoria'] or 'Sin categoría',
                    p['marca'] or 'Sin marca',
                    f"${p['precio_compra']:,.2f}",
                    f"${p['precio_venta']:,.2f}",
                    ganancia_texto,
                    f"{margen:.1f}%",
                    str(p['stock']),
                    str(p['stock_minimo']),
                    unidad_base,
                    presentacion
                ]

                for col, val in enumerate(valores):
                    item = QTableWidgetItem(str(val))
                    item.setBackground(QColor(bg_color))
                    item.setForeground(QColor(COLORS['text_primary']))
                    if col != 1:
                        item.setTextAlignment(Qt.AlignCenter)
                    self.table.setItem(row, col, item)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error cargando productos:\n{str(e)}")

    # ------------------------------------------------------------------
    #  CRUD helpers
    # ------------------------------------------------------------------
    def crear_producto(self):
        """Abre ventana para crear producto"""
        self.abrir_formulario(modo='crear')

    def editar_producto(self):
        """Edita el producto seleccionado"""
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Advertencia", "Seleccione un producto")
            return

        producto_id = self.table.item(row, 0).text()
        producto_dict = self.productos_repo.obtener_por_id(producto_id)
        if producto_dict:
            self.abrir_formulario(modo='editar', producto_dict=producto_dict)

    # ------------------------------------------------------------------
    #  Formulario
    # ------------------------------------------------------------------
    def abrir_formulario(self, modo='crear', producto_dict=None):
        """Abre el formulario mejorado con autocompletado"""
        ventana = QDialog(self)
        ventana.setWindowTitle(f"{'Crear' if modo == 'crear' else 'Editar'} Producto")
        ventana.setFixedSize(950, 800)
        ventana.setModal(True)

        main_layout = QVBoxLayout(ventana)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ========== HEADER ==========
        header = QFrame()
        header.setFixedHeight(50)
        header.setStyleSheet(f"background: {COLORS['primary']};")
        header_lay = QHBoxLayout(header)

        icono = "\u2795" if modo == 'crear' else "\u270f\ufe0f"
        titulo = "Nuevo Producto" if modo == 'crear' else "Editar Producto"
        lbl_header = QLabel(f"{icono} {titulo}")
        lbl_header.setFont(make_font(FONTS['xlarge']))
        lbl_header.setStyleSheet("color: white;")
        lbl_header.setAlignment(Qt.AlignCenter)
        header_lay.addWidget(lbl_header)

        main_layout.addWidget(header)

        # ========== CONTENEDOR PRINCIPAL ==========
        body = QWidget()
        body.setStyleSheet(f"background: {COLORS['bg_primary']};")
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(15, 8, 15, 8)
        body_lay.setSpacing(20)

        # ========== COLUMNA IZQUIERDA ==========
        left_column = QVBoxLayout()
        left_column.setSpacing(6)

        groupbox_qss = (
            "QGroupBox { background: white; border: 1px solid #e2e8f0; "
            "border-radius: 6px; padding-top: 18px; margin-top: 6px; } "
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }"
        )

        # ===== 1. INFORMACIÓN BÁSICA =====
        info_group = QGroupBox("\U0001f4cb Información Básica")
        info_group.setFont(make_font(FONTS['body_bold']))
        info_group.setStyleSheet(groupbox_qss)
        info_grid = QGridLayout(info_group)
        info_grid.setContentsMargins(12, 6, 12, 10)

        info_grid.addWidget(self._label("Nombre del Producto *"), 0, 0, 1, 2, Qt.AlignLeft)
        nombre_edit = QLineEdit(producto_dict['nombre'] if producto_dict else '')
        nombre_edit.setFont(make_font(FONTS['body']))
        info_grid.addWidget(nombre_edit, 1, 0, 1, 2)

        info_grid.addWidget(self._label("Categoría *"), 2, 0, Qt.AlignLeft)
        categoria_combo = QComboBox()
        categoria_combo.setFont(make_font(FONTS['body']))
        categoria_combo.addItems(self.categorias_predefinidas)
        if producto_dict and producto_dict.get('categoria'):
            idx = categoria_combo.findText(producto_dict['categoria'])
            if idx >= 0:
                categoria_combo.setCurrentIndex(idx)
        info_grid.addWidget(categoria_combo, 3, 0)

        info_grid.addWidget(self._label("Marca"), 2, 1, Qt.AlignLeft)
        marca_combo = QComboBox()
        marca_combo.setFont(make_font(FONTS['body']))
        marca_combo.setEditable(True)
        marca_combo.addItems(self.marcas_existentes)
        if producto_dict and producto_dict.get('marca'):
            marca_combo.setCurrentText(producto_dict['marca'])
        info_grid.addWidget(marca_combo, 3, 1)

        info_grid.addWidget(self._label("Proveedor"), 4, 0, 1, 2, Qt.AlignLeft)

        prov_lay = QHBoxLayout()
        proveedor_combo = QComboBox()
        proveedor_combo.setFont(make_font(FONTS['body']))
        proveedores_nombres = [p['nombre'] for p in self.proveedores_lista] if self.proveedores_lista else []
        proveedor_combo.addItem("")
        proveedor_combo.addItems(proveedores_nombres)
        if not proveedores_nombres:
            proveedor_combo.addItem("No hay proveedores registrados")

        self._proveedor_id_actual = 0
        if producto_dict and producto_dict.get('proveedor_id'):
            prov_id = producto_dict['proveedor_id']
            prov_nombre = next((p['nombre'] for p in self.proveedores_lista if p['id'] == prov_id), None)
            if prov_nombre:
                idx = proveedor_combo.findText(prov_nombre)
                if idx >= 0:
                    proveedor_combo.setCurrentIndex(idx)
                self._proveedor_id_actual = prov_id

        def actualizar_proveedor_id(text):
            if text and text != "No hay proveedores registrados":
                prov = next((p for p in self.proveedores_lista if p['nombre'] == text), None)
                self._proveedor_id_actual = prov['id'] if prov else 0
            else:
                self._proveedor_id_actual = 0

        proveedor_combo.currentTextChanged.connect(actualizar_proveedor_id)
        prov_lay.addWidget(proveedor_combo, 1)

        btn_buscar_prov = QPushButton("\U0001f50d")
        btn_buscar_prov.setFont(make_font(FONTS['body']))
        btn_buscar_prov.setFixedWidth(36)
        btn_buscar_prov.setStyleSheet(
            f"background: {COLORS['info']}; color: white; border: none; border-radius: 4px;"
        )
        prov_lay.addWidget(btn_buscar_prov)
        info_grid.addLayout(prov_lay, 5, 0, 1, 2)

        info_grid.setColumnStretch(0, 1)
        info_grid.setColumnStretch(1, 1)

        left_column.addWidget(info_group)

        # ===== 2. PRECIOS =====
        precio_group = QGroupBox("\U0001f4b0 Precios")
        precio_group.setFont(make_font(FONTS['body_bold']))
        precio_group.setStyleSheet(groupbox_qss)
        precio_grid = QGridLayout(precio_group)
        precio_grid.setContentsMargins(12, 5, 12, 10)

        precio_grid.addWidget(self._label("Precio de Compra *"), 0, 0, Qt.AlignLeft)
        precio_compra_edit = QLineEdit(f"{producto_dict['precio_compra']:,.0f}" if producto_dict else '0')
        precio_compra_edit.setFont(make_font(FONTS['body']))
        precio_grid.addWidget(precio_compra_edit, 1, 0)

        precio_grid.addWidget(self._label("Precio de Venta *"), 0, 1, Qt.AlignLeft)
        precio_venta_edit = QLineEdit(f"{producto_dict['precio_venta']:,.0f}" if producto_dict else '0')
        precio_venta_edit.setFont(make_font(FONTS['body']))
        precio_grid.addWidget(precio_venta_edit, 1, 1)

        def _limpiar_precio(texto):
            """Quita separadores de miles para obtener el valor numérico."""
            return texto.replace(',', '')

        def _formatear_precio(line_edit):
            """Formatea el contenido del QLineEdit con separador de miles."""
            texto = _limpiar_precio(line_edit.text())
            # Conservar solo dígitos y punto decimal
            limpio = ''
            tiene_punto = False
            for ch in texto:
                if ch.isdigit():
                    limpio += ch
                elif ch == '.' and not tiene_punto:
                    limpio += ch
                    tiene_punto = True
            if not limpio or limpio == '.':
                return
            try:
                valor = float(limpio)
                if tiene_punto:
                    partes = limpio.split('.')
                    entero = int(partes[0]) if partes[0] else 0
                    formateado = f"{entero:,}.{partes[1]}"
                else:
                    formateado = f"{int(valor):,}"
                # Evitar recursión: solo actualizar si cambió
                if line_edit.text() != formateado:
                    pos = line_edit.cursorPosition()
                    diff = len(formateado) - len(line_edit.text())
                    line_edit.blockSignals(True)
                    line_edit.setText(formateado)
                    line_edit.setCursorPosition(max(0, pos + diff))
                    line_edit.blockSignals(False)
            except ValueError:
                pass

        precio_compra_edit.textChanged.connect(lambda: _formatear_precio(precio_compra_edit))
        precio_venta_edit.textChanged.connect(lambda: _formatear_precio(precio_venta_edit))

        precio_grid.setColumnStretch(0, 1)
        precio_grid.setColumnStretch(1, 1)

        # Ganancia display
        ganancia_frame = QFrame()
        ganancia_frame.setStyleSheet(
            "background: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 6px;"
        )
        ganancia_lay = QHBoxLayout(ganancia_frame)
        ganancia_lay.setContentsMargins(10, 8, 10, 8)

        ganancia_label = QLabel("$0")
        ganancia_label.setFont(make_font(('Segoe UI', 16, 'bold')))
        ganancia_label.setStyleSheet("color: #059669; border: none;")
        ganancia_lay.addWidget(ganancia_label)

        sep_lbl = QLabel("|")
        sep_lbl.setFont(make_font(FONTS['large']))
        sep_lbl.setStyleSheet("color: #d1d5db; border: none;")
        ganancia_lay.addWidget(sep_lbl)

        margen_label = QLabel("Margen: 0%")
        margen_label.setFont(make_font(FONTS['body_bold']))
        margen_label.setStyleSheet("color: #047857; border: none;")
        ganancia_lay.addWidget(margen_label)
        ganancia_lay.addStretch()

        precio_grid.addWidget(ganancia_frame, 2, 0, 1, 2)

        def calcular_ganancia():
            try:
                compra = float(_limpiar_precio(precio_compra_edit.text()) or 0)
                venta = float(_limpiar_precio(precio_venta_edit.text()) or 0)
                ganancia = venta - compra
                margen = ((ganancia / compra) * 100) if compra > 0 else 0
                ganancia_label.setText(f"${ganancia:,.0f}")
                margen_label.setText(f"Margen: {margen:.1f}%")
            except Exception:
                pass

        precio_compra_edit.textChanged.connect(calcular_ganancia)
        precio_venta_edit.textChanged.connect(calcular_ganancia)
        calcular_ganancia()

        left_column.addWidget(precio_group)

        # ===== 3. INVENTARIO =====
        inventario_group = QGroupBox("\U0001f4e6 Inventario")
        inventario_group.setFont(make_font(FONTS['body_bold']))
        inventario_group.setStyleSheet(groupbox_qss)
        inv_grid = QGridLayout(inventario_group)
        inv_grid.setContentsMargins(15, 10, 15, 10)

        inv_grid.addWidget(self._label("Unidad de Medida Base *"), 0, 0, 1, 2, Qt.AlignLeft)
        unidad_base_combo = QComboBox()
        unidad_base_combo.setFont(make_font(FONTS['body']))
        unidades_base = ['UNIDAD', 'METRO', 'KILO', 'LITRO', 'GALÓN', 'SACO']
        unidad_base_combo.addItems(unidades_base)
        if producto_dict and producto_dict.get('unidad_medida'):
            idx = unidad_base_combo.findText(producto_dict['unidad_medida'].upper())
            if idx >= 0:
                unidad_base_combo.setCurrentIndex(idx)
        inv_grid.addWidget(unidad_base_combo, 1, 0, 1, 2)

        # Checkbox: Permite decimales
        permite_decimales_check = QCheckBox("\u2713 Permite decimales (ej: 1.5, 2.3)")
        permite_decimales_check.setFont(make_font(FONTS['small']))
        permite_decimales_check.setStyleSheet(f"color: {COLORS['primary']};")
        if producto_dict:
            permite_decimales_check.setChecked(producto_dict.get('permite_decimales', False))
        inv_grid.addWidget(permite_decimales_check, 2, 0, 1, 2)

        tooltip_lbl = QLabel("\U0001f4a1 Solo para productos por medida (metros, kilos, litros)")
        tooltip_lbl.setFont(make_font(FONTS['small']))
        tooltip_lbl.setStyleSheet(f"color: {COLORS['text_secondary']};")
        inv_grid.addWidget(tooltip_lbl, 3, 0, 1, 2)

        inv_grid.addWidget(self._label("Presentación (opcional)"), 4, 0, 1, 2, Qt.AlignLeft)
        presentacion_combo = QComboBox()
        presentacion_combo.setFont(make_font(FONTS['body']))
        presentaciones = ['Sin empaque', 'Caja', 'Paquete', 'Blister']
        presentacion_combo.addItems(presentaciones)
        if producto_dict and producto_dict.get('viene_en_caja'):
            presentacion_combo.setCurrentText('Caja')
        inv_grid.addWidget(presentacion_combo, 5, 0, 1, 2)

        stock_label_widget = QLabel("Stock Actual")
        stock_label_widget.setFont(make_font(FONTS['body']))
        stock_label_widget.setStyleSheet(f"color: {COLORS['text_secondary']};")
        inv_grid.addWidget(stock_label_widget, 6, 0, Qt.AlignLeft)

        stock_edit = QLineEdit(str(producto_dict['stock']) if producto_dict else '0')
        stock_edit.setFont(make_font(FONTS['body']))
        inv_grid.addWidget(stock_edit, 7, 0)

        inv_grid.addWidget(self._label("Stock Mínimo *"), 6, 1, Qt.AlignLeft)
        stock_min_edit = QLineEdit(str(producto_dict['stock_minimo']) if producto_dict else '10')
        stock_min_edit.setFont(make_font(FONTS['body']))
        inv_grid.addWidget(stock_min_edit, 7, 1)

        inv_grid.setColumnStretch(0, 1)
        inv_grid.setColumnStretch(1, 1)

        left_column.addWidget(inventario_group, 1)

        body_lay.addLayout(left_column, 1)

        # ========== COLUMNA DERECHA ==========
        right_column = QVBoxLayout()
        right_column.setSpacing(10)

        # ===== Configuración de Empaque =====
        cajas_group = QGroupBox("\U0001f4e6 Configuración de Empaque")
        cajas_group.setFont(make_font(FONTS['body_bold']))
        cajas_group.setStyleSheet(
            "QGroupBox { background: #dbeafe; border: 1px solid #93c5fd; "
            "border-radius: 6px; padding-top: 18px; margin-top: 6px; } "
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }"
        )
        cajas_lay = QVBoxLayout(cajas_group)
        cajas_lay.setContentsMargins(12, 10, 12, 10)

        lbl_cajas_cantidad = self._label("Cantidad de Empaques", bg='#dbeafe', color=COLORS['text_primary'])
        cajas_lay.addWidget(lbl_cajas_cantidad)
        num_cajas_edit = QLineEdit('0')
        num_cajas_edit.setFont(make_font(FONTS['body']))
        cajas_lay.addWidget(num_cajas_edit)

        lbl_cajas_medida = self._label("Unidades por Empaque", bg='#dbeafe', color=COLORS['text_primary'])
        cajas_lay.addWidget(lbl_cajas_medida)
        unidades_por_caja_edit = QLineEdit(
            str(producto_dict.get('unidades_por_caja', 1)) if producto_dict else '1'
        )
        unidades_por_caja_edit.setFont(make_font(FONTS['body']))
        cajas_lay.addWidget(unidades_por_caja_edit)

        tip_media = QLabel("\U0001f4a1 Media caja se calcula automáticamente (mitad)")
        tip_media.setFont(make_font(FONTS['small']))
        tip_media.setStyleSheet(f"color: {COLORS['text_secondary']};")
        cajas_lay.addWidget(tip_media)

        # Separator
        sep_line = QFrame()
        sep_line.setFrameShape(QFrame.HLine)
        sep_line.setStyleSheet("background: #93c5fd; border: none; max-height: 2px;")
        cajas_lay.addWidget(sep_line)

        permitir_venta_empaque_check = QCheckBox(
            "\u2699\ufe0f Permitir venta por Caja/Media Caja (además de Unidad)"
        )
        permitir_venta_empaque_check.setFont(make_font(FONTS['body_bold']))
        permitir_venta_empaque_check.setStyleSheet(f"color: {COLORS['primary']};")
        permitir_venta_empaque_check.setCursor(QCursor(Qt.PointingHandCursor))
        if producto_dict:
            permitir_venta_empaque_check.setChecked(producto_dict.get('vende_por_empaque', 0) == 1)
        cajas_lay.addWidget(permitir_venta_empaque_check)

        info_estado_label = QLabel("")
        info_estado_label.setFont(make_font(FONTS['small']))
        info_estado_label.setWordWrap(True)

        def actualizar_mensaje_checkbox(checked):
            if checked:
                info_estado_label.setText(
                    "\u2705 ACTIVO: Cliente puede comprar por:\n"
                    "   \u2022 Unidad\n   \u2022 Media Caja\n   \u2022 Caja Completa"
                )
                info_estado_label.setStyleSheet("color: #059669;")
            else:
                info_estado_label.setText(
                    "\u26a0\ufe0f INACTIVO: Solo venta por Unidad\n"
                    "   (útil para herramientas individuales)"
                )
                info_estado_label.setStyleSheet("color: #dc2626;")

        permitir_venta_empaque_check.toggled.connect(actualizar_mensaje_checkbox)
        actualizar_mensaje_checkbox(permitir_venta_empaque_check.isChecked())
        cajas_lay.addWidget(info_estado_label)

        info_cajas_lbl = QLabel("\u2139\ufe0f El stock se calcula como:\nEmpaques \u00d7 Unidades")
        info_cajas_lbl.setFont(make_font(FONTS['small']))
        info_cajas_lbl.setStyleSheet(f"color: {COLORS['text_secondary']};")
        info_cajas_lbl.setAlignment(Qt.AlignCenter)
        cajas_lay.addWidget(info_cajas_lbl)

        right_column.addWidget(cajas_group)

        # Presentación toggle logic
        def actualizar_campos_presentacion(text):
            es_empaque = text in ('Caja', 'Paquete', 'Blister')
            cajas_group.setVisible(es_empaque)
            if es_empaque:
                stock_label_widget.setText("Stock (calculado)")
                stock_label_widget.setStyleSheet(f"color: {COLORS['info']};")
                stock_edit.setReadOnly(True)

                def calcular_stock():
                    try:
                        cajas = int(num_cajas_edit.text() or 0)
                        unidades = int(unidades_por_caja_edit.text() or 1)
                        stock_edit.setText(str(cajas * unidades))
                    except Exception:
                        stock_edit.setText('0')

                num_cajas_edit.textChanged.connect(calcular_stock)
                unidades_por_caja_edit.textChanged.connect(calcular_stock)

                if producto_dict and producto_dict.get('viene_en_caja'):
                    stock_actual = producto_dict.get('stock', 0)
                    unidades_caja = producto_dict.get('unidades_por_caja', 1)
                    if unidades_caja > 0:
                        num_cajas_edit.setText(str(stock_actual // unidades_caja))
                    calcular_stock()
            else:
                stock_label_widget.setText("Stock Actual")
                stock_label_widget.setStyleSheet(f"color: {COLORS['text_secondary']};")
                stock_edit.setReadOnly(False)

        def actualizar_labels_medida(unidad):
            u = unidad.upper()
            if u in ('METRO', 'CM', 'MM'):
                lbl_cajas_cantidad.setText("Cantidad de piezas:")
                lbl_cajas_medida.setText("Metros por pieza:")
                info_cajas_lbl.setText("\u2139\ufe0f Stock total = piezas \u00d7 metros por pieza")
                cajas_group.setTitle("\U0001f4cf Configuraci\u00f3n por Longitud")
                permite_decimales_check.setChecked(True)
            elif u in ('LITRO', 'ML', 'GAL\u00d3N', 'GALON'):
                lbl_cajas_cantidad.setText("Cantidad de envases:")
                lbl_cajas_medida.setText(f"{unidad.capitalize()} por envase:")
                info_cajas_lbl.setText(f"\u2139\ufe0f Stock total = envases \u00d7 {unidad.lower()} por envase")
                cajas_group.setTitle("\U0001f9f4 Configuraci\u00f3n por Volumen")
                permite_decimales_check.setChecked(True)
            elif u in ('KILO', 'GRAMO', 'TON'):
                lbl_cajas_cantidad.setText("Cantidad de bultos:")
                lbl_cajas_medida.setText(f"{unidad.capitalize()} por bulto:")
                info_cajas_lbl.setText(f"\u2139\ufe0f Stock total = bultos \u00d7 {unidad.lower()} por bulto")
                cajas_group.setTitle("\u2696\ufe0f Configuraci\u00f3n por Peso")
                permite_decimales_check.setChecked(True)
            elif u == 'SACO':
                lbl_cajas_cantidad.setText("Cantidad de sacos:")
                lbl_cajas_medida.setText("Kg por saco:")
                info_cajas_lbl.setText("\u2139\ufe0f Stock total = sacos \u00d7 kg por saco")
                cajas_group.setTitle("\U0001f9f3 Configuraci\u00f3n por Saco")
            else:
                lbl_cajas_cantidad.setText("Cantidad de Empaques:")
                lbl_cajas_medida.setText("Unidades por Empaque:")
                info_cajas_lbl.setText("\u2139\ufe0f El stock se calcula como:\nEmpaques \u00d7 Unidades")
                cajas_group.setTitle("\U0001f4e6 Configuraci\u00f3n de Empaque")

        unidad_base_combo.currentTextChanged.connect(actualizar_labels_medida)
        presentacion_combo.currentTextChanged.connect(actualizar_campos_presentacion)
        actualizar_campos_presentacion(presentacion_combo.currentText())
        actualizar_labels_medida(unidad_base_combo.currentText())

        # ===== Información / Ayuda =====
        ayuda_group = QGroupBox("\u2139\ufe0f Información")
        ayuda_group.setFont(make_font(FONTS['body_bold']))
        ayuda_group.setStyleSheet(
            "QGroupBox { background: #f0f9ff; border: 1px solid #bae6fd; "
            "border-radius: 6px; padding-top: 18px; margin-top: 6px; } "
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }"
        )
        ayuda_lay = QVBoxLayout(ayuda_group)
        ayuda_lay.setContentsMargins(12, 8, 12, 8)

        ayuda_text = (
            "\u2022 Los campos con * son obligatorios\n\n"
            "- La ganancia se calcula automáticamente\n\n"
            "- Si selecciona empaque (Caja/Paquete):\n"
            "  \u00b7 Configure cantidad y unidades\n"
            "  \u00b7 Active el checkbox SOLO si quiere venta flexible\n"
            "  \u00b7 El stock se calcula automáticamente\n\n"
            "- Para productos sin empaque:\n"
            "  \u00b7 Ingrese el stock directamente\n\n"
            "- Use autocompletado en Categoría y Marca"
        )
        ayuda_lbl = QLabel(ayuda_text)
        ayuda_lbl.setFont(make_font(FONTS['small']))
        ayuda_lbl.setStyleSheet(f"color: {COLORS['text_secondary']};")
        ayuda_lbl.setWordWrap(True)
        ayuda_lay.addWidget(ayuda_lbl)

        right_column.addWidget(ayuda_group, 1)

        body_lay.addLayout(right_column, 1)

        main_layout.addWidget(body, 1)

        # ========== FOOTER ==========
        footer = QFrame()
        footer.setFixedHeight(60)
        footer.setStyleSheet("background: #f8f9fa; border-top: 1px solid #dee2e6;")
        footer_lay = QHBoxLayout(footer)
        footer_lay.setAlignment(Qt.AlignCenter)

        btn_guardar = QPushButton("[GUARDAR] Guardar Producto")
        btn_guardar.setFont(make_font(FONTS['body_bold']))
        btn_guardar.setCursor(QCursor(Qt.PointingHandCursor))
        btn_guardar.setStyleSheet(
            f"background: {COLORS['success']}; color: white; border: none; "
            f"border-radius: 6px; padding: 12px 30px;"
        )
        btn_guardar.clicked.connect(lambda: self.guardar_producto(
            ventana, modo, producto_dict,
            nombre_edit, categoria_combo, marca_combo,
            precio_compra_edit, precio_venta_edit,
            stock_edit, stock_min_edit,
            unidad_base_combo, presentacion_combo,
            num_cajas_edit, unidades_por_caja_edit,
            permitir_venta_empaque_check,
            permite_decimales_check
        ))
        footer_lay.addWidget(btn_guardar)

        btn_cancelar = QPushButton("[ERROR] Cancelar")
        btn_cancelar.setFont(make_font(FONTS['body']))
        btn_cancelar.setCursor(QCursor(Qt.PointingHandCursor))
        btn_cancelar.setStyleSheet(
            f"background: {COLORS['secondary']}; color: white; border: none; "
            f"border-radius: 6px; padding: 12px 30px;"
        )
        btn_cancelar.clicked.connect(ventana.close)
        footer_lay.addWidget(btn_cancelar)

        main_layout.addWidget(footer)

        ventana.exec()

    # ------------------------------------------------------------------
    #  Guardar
    # ------------------------------------------------------------------
    def guardar_producto(self, ventana, modo, producto_dict,
                         nombre_edit, categoria_combo, marca_combo,
                         precio_compra_edit, precio_venta_edit,
                         stock_edit, stock_min_edit,
                         unidad_base_combo, presentacion_combo,
                         num_cajas_edit, unidades_por_caja_edit,
                         permitir_venta_empaque_check,
                         permite_decimales_check):
        """Guarda el producto con la nueva lógica de unidad base y presentación"""
        try:
            nombre = nombre_edit.text().strip()
            if not nombre:
                QMessageBox.warning(ventana, "Advertencia", "El nombre es obligatorio")
                return

            precio_venta = float(precio_venta_edit.text().replace(',', ''))
            if precio_venta <= 0:
                QMessageBox.warning(ventana, "Advertencia", "El precio de venta debe ser mayor a 0")
                return

            unidad_base = unidad_base_combo.currentText()
            presentacion = presentacion_combo.currentText()

            tiene_empaque = presentacion in ['Caja', 'Paquete', 'Blister']

            if tiene_empaque:
                num_cajas = int(num_cajas_edit.text() or 0)
                unidades_caja = int(unidades_por_caja_edit.text() or 1)
                unidades_media_caja = unidades_caja // 2 if unidades_caja > 1 else 1
                stock_total = num_cajas * unidades_caja

                unidad_medida_guardar = unidad_base
                viene_en_caja = True
                vende_por_empaque = 1 if permitir_venta_empaque_check.isChecked() else 0
            else:
                stock_total = int(stock_edit.text() or 0)
                num_cajas = 0
                unidades_caja = 1
                unidades_media_caja = 1
                unidad_medida_guardar = unidad_base
                viene_en_caja = False
                vende_por_empaque = 0

            proveedor_id = self._proveedor_id_actual
            if proveedor_id == 0:
                proveedor_id = None

            producto = Producto(
                id=producto_dict['id'] if producto_dict else None,
                codigo_barras=producto_dict.get('codigo_barras') if producto_dict else None,
                nombre=nombre,
                categoria=categoria_combo.currentText().strip() or None,
                marca=marca_combo.currentText().strip() or None,
                proveedor_id=proveedor_id,
                precio_compra=float(precio_compra_edit.text().replace(',', '') or 0),
                precio_venta=precio_venta,
                stock=stock_total,
                stock_minimo=int(stock_min_edit.text() or 10),
                unidad_medida=unidad_medida_guardar,
                viene_en_caja=viene_en_caja,
                unidades_por_caja=unidades_caja,
                unidades_por_media_caja=unidades_media_caja,
                vende_por_empaque=vende_por_empaque,
                permite_decimales=permite_decimales_check.isChecked()
            )

            if modo == 'crear':
                exito, mensaje, _ = self.productos_repo.crear_producto(producto)
            else:
                exito, mensaje = self.productos_repo.actualizar_producto(producto)

            if exito:
                QMessageBox.information(ventana, "Éxito", mensaje)
                ventana.close()
                self.cargar_datos_autocompletado()
                self.cargar_productos()
            else:
                QMessageBox.critical(ventana, "Error", mensaje)

        except ValueError:
            QMessageBox.critical(ventana, "Error", "Los valores numéricos no son válidos")
        except Exception as e:
            QMessageBox.critical(ventana, "Error", f"Error guardando producto:\n{str(e)}")

    # ------------------------------------------------------------------
    #  Context menu
    # ------------------------------------------------------------------
    def mostrar_menu_contextual(self, pos):
        """Muestra menú contextual"""
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        self.table.selectRow(row)

        menu = QMenu(self)
        menu.addAction("\u270f\ufe0f Editar", self.editar_producto)
        menu.addAction("\U0001f5d1\ufe0f Eliminar", self.eliminar_producto)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def eliminar_producto(self):
        """Elimina el producto seleccionado"""
        row = self.table.currentRow()
        if row < 0:
            return

        producto_id = self.table.item(row, 0).text()
        nombre = self.table.item(row, 1).text()

        respuesta = QMessageBox.question(
            self, "Confirmar",
            f"¿Desea desactivar el producto '{nombre}'?",
            QMessageBox.Yes | QMessageBox.No
        )

        if respuesta == QMessageBox.Yes:
            exito, mensaje = self.productos_repo.eliminar_producto(producto_id)
            if exito:
                QMessageBox.information(self, "Éxito", mensaje)
                self.cargar_productos()
            else:
                QMessageBox.critical(self, "Error", mensaje)

    # ------------------------------------------------------------------
    #  Helpers
    # ------------------------------------------------------------------
    def _label(self, text, bg=None, color=None):
        """Crea un QLabel estilizado para formularios"""
        lbl = QLabel(text)
        lbl.setFont(make_font(FONTS['body']))
        c = color or COLORS['text_secondary']
        style = f"color: {c};"
        if bg:
            style += f" background: {bg};"
        lbl.setStyleSheet(style)
        return lbl
