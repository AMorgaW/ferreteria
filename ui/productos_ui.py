# -*- coding: utf-8 -*-
"""
Interfaz de usuario para gestión de productos (PySide6)
Con autocompletado, búsqueda de proveedores y distinción entre unidad base y presentación
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QCheckBox,
    QGroupBox, QGridLayout, QDialog, QMessageBox, QMenu, QFrame,
    QAbstractItemView, QSizePolicy, QFileDialog, QScrollArea, QApplication
)
from PySide6.QtCore import Qt, Signal, QTimer, QThreadPool
from PySide6.QtGui import QFont, QColor, QCursor

from models import Producto
from ui_config import COLORS, FONTS, make_font
from formato import formatear_stock
from ui.async_worker import FunctionWorker
from ui.barcode_widget import BarcodeCaptureWidget
from repositories.product_barcodes_repo import ProductBarcodesRepository
from repositories.productos_repo import PRODUCT_CREATION_FINAL


class ProductosUI(QWidget):
    """Interfaz de gestión de productos"""

    def __init__(self, parent, productos_repo, auth, proveedores_repo=None):
        super().__init__(parent)
        self.parent_widget = parent
        self.productos_repo = productos_repo
        self.barcode_repo = ProductBarcodesRepository(productos_repo.db)
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
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(350)
        self._search_timer.timeout.connect(self.cargar_productos)
        self._thread_pool = QThreadPool.globalInstance()
        self._load_seq = 0

        self.cargar_datos_autocompletado()
        self.crear_ui()
        self.cargar_productos()

    def cargar_datos_autocompletado(self):
        """Carga datos para autocompletado"""
        try:
            productos = self.productos_repo.buscar_productos('', limite=1000)

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
                background: {COLORS['accent']}; color: {COLORS['on_accent']};
                border: none; border-radius: 9px;
                padding: 10px 20px; font-size: 11pt;
                font-weight: 500; font-family: 'Segoe UI';
            }}
            QPushButton:hover {{ background: {COLORS['accent_hover']}; }}
            QPushButton:pressed {{ background: {COLORS['accent_dark']}; }}
        """)
        btn_nuevo.clicked.connect(self.crear_producto)
        header.addWidget(btn_nuevo)

        btn_exportar = QPushButton("  📤  Exportar")
        btn_exportar.setCursor(QCursor(Qt.PointingHandCursor))
        btn_exportar.setMinimumHeight(42)
        btn_exportar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['bg_primary']}; color: {COLORS['text_body']}; "
            f"border: 1px solid {COLORS['border_input']}; border-radius: 9px; "
            f"padding: 10px 18px; font-weight: 500; }}"
            f"QPushButton:hover {{ background: {COLORS['bg_hover']}; border-color: {COLORS['primary_border']}; }}"
        )
        btn_exportar.clicked.connect(self.exportar_inventario)
        header.addWidget(btn_exportar)

        layout.addLayout(header)

        # ---- Barra de búsqueda ----
        search_bar = QHBoxLayout()

        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText("\U0001f50d  Buscar producto...")
        self.search_entry.setFont(make_font(FONTS['body']))
        self.search_entry.setMinimumHeight(38)
        self.search_entry.textChanged.connect(lambda: self._search_timer.start())
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
                border: 1px solid {COLORS['border']};
                border-radius: 12px;
                gridline-color: transparent;
            }}
            QTableWidget::item {{
                padding: 7px 8px;
            }}
            QTableWidget::item:selected {{
                background: {COLORS['table_selection']};
                color: {COLORS['text_primary']};
            }}
            QHeaderView::section {{
                background: {COLORS['table_header']};
                color: {COLORS['table_header_fg']};
                font-weight: 500;
                font-size: 9pt;
                padding: 10px 8px;
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
            if self.productos_repo.cache_disponible():
                productos = self.productos_repo.buscar_productos_cache(termino, limite=250)
                self._renderizar_productos(productos)
                return

            self._load_seq += 1
            seq = self._load_seq
            worker = FunctionWorker(self.productos_repo.buscar_productos, termino, True, 250)
            worker.signals.result.connect(lambda productos, s=seq: self._on_productos_cargados(productos, s))
            worker.signals.error.connect(lambda e: QMessageBox.critical(self, "Error", f"Error cargando productos:\n{e}"))
            self._thread_pool.start(worker)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error cargando productos:\n{str(e)}")

    def _on_productos_cargados(self, productos, seq):
        if seq != self._load_seq:
            return
        self._renderizar_productos(productos)

    def exportar_inventario(self):
        """Exporta el inventario completo a un archivo Excel (.xlsx)."""
        try:
            import exportar
            sugerido = exportar.nombre_sugerido("inventario")
            path, _ = QFileDialog.getSaveFileName(
                self, "Exportar inventario a Excel", sugerido, "Excel (*.xlsx)")
            if not path:
                return
            if not path.lower().endswith(".xlsx"):
                path += ".xlsx"
            exportar.exportar_inventario(self.productos_repo, path)
            QMessageBox.information(self, "Exportación exitosa",
                                   f"Inventario exportado a:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Error al exportar", str(e))

    def _renderizar_productos(self, productos):
            self.table.setRowCount(0)
            for p in productos:
                ganancia_neta = p['precio_venta'] - p['precio_compra']
                margen = ((ganancia_neta / p['precio_compra']) * 100) if p['precio_compra'] > 0 else 0

                if p.get('viene_en_caja'):
                    unidad_base = 'Unidad'
                else:
                    unidad_base = p.get('unidad_medida', 'Unidad')
                    if unidad_base:
                        unidad_base = unidad_base.capitalize()

                # Mostrar el tama\u00f1o/medida real; si no hay, el empaque; si no, "\u2014"
                tamano = (p.get('presentacion') or '').strip()
                if tamano:
                    presentacion = tamano
                elif p.get('viene_en_caja') and p.get('unidades_por_caja', 1) > 1:
                    presentacion = f"Caja ({p.get('unidades_por_caja', 1)} u/caja)"
                else:
                    presentacion = "\u2014"

                row = self.table.rowCount()
                # Semáforo de stock: crítico (bajo el mínimo) tiñe toda la fila;
                # el resto alterna en zebra.
                critico = p['stock'] < p['stock_minimo']
                if critico:
                    bg_color = '#fef6f6'
                else:
                    bg_color = '#ffffff' if row % 2 == 0 else '#fafbfc'

                id_formateado = f"#{p['id']}" if not str(p['id']).startswith('#') else p['id']
                ganancia_texto = f"\u2191${ganancia_neta:,.2f}" if ganancia_neta >= 0 else f"\u2193${abs(ganancia_neta):,.2f}"

                self.table.insertRow(row)

                stock_txt = formatear_stock(p['stock'], p.get('permite_decimales'))
                valores = [
                    id_formateado,
                    p['nombre'],
                    p['categoria'] or 'Sin categoría',
                    p['marca'] or 'Sin marca',
                    f"${p['precio_compra']:,.2f}",
                    f"${p['precio_venta']:,.2f}",
                    ganancia_texto,
                    f"{margen:.1f}%",
                    stock_txt,
                    formatear_stock(p['stock_minimo'], p.get('permite_decimales')),
                    unidad_base,
                    presentacion
                ]

                # Alineación: montos/cantidades a la derecha; texto a la izquierda.
                right_cols = {4, 5, 6, 7}
                center_cols = {9}
                fg_cols = {
                    0: '#94a3b8',                       # ID atenuado
                    1: COLORS['text_primary'],          # Nombre destacado
                    6: ('#1d9e75' if ganancia_neta >= 0 else '#a32d2d'),  # Ganancia
                    9: COLORS['text_secondary'],        # Stock mínimo
                }
                for col, val in enumerate(valores):
                    if col == 8:
                        # Pill de semáforo en la columna Stock.
                        celda = QTableWidgetItem('')
                        celda.setBackground(QColor(bg_color))
                        self.table.setItem(row, col, celda)
                        self.table.setCellWidget(
                            row, col,
                            self._crear_pill_stock(stock_txt, p['stock'],
                                                   p['stock_minimo'], bg_color))
                        continue
                    item = QTableWidgetItem(str(val))
                    item.setBackground(QColor(bg_color))
                    item.setForeground(QColor(fg_cols.get(col, COLORS['text_body'])))
                    if col in right_cols:
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    elif col in center_cols:
                        item.setTextAlignment(Qt.AlignCenter)
                    else:
                        item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                    self.table.setItem(row, col, item)

    def _crear_pill_stock(self, texto, stock, minimo, bg_fila):
        """Crea un widget 'pill' (semáforo) para la celda de stock, centrado
        sobre el color de la fila: rojo si bajo el mínimo, ámbar si en el
        mínimo, verde si por encima."""
        if stock < minimo:
            bg, fg = '#fcebeb', '#a32d2d'
        elif stock == minimo:
            bg, fg = '#faeeda', '#854f0b'
        else:
            bg, fg = '#eaf3de', '#3b6d11'
        cont = QWidget()
        cont.setStyleSheet(f"background: {bg_fila};")
        lay = QHBoxLayout(cont)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignCenter)
        lbl = QLabel(texto)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setMinimumWidth(34)
        lbl.setStyleSheet(
            f"background: {bg}; color: {fg}; border-radius: 10px;"
            f" padding: 2px 10px; font-weight: 500;")
        lay.addWidget(lbl)
        return cont

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
        ventana.setModal(True)
        # Tamaño responsivo: nunca más grande que la pantalla; alto máx 85vh.
        _scr = (self.screen().availableGeometry() if self.screen()
                else QApplication.primaryScreen().availableGeometry())
        _w = min(950, int(_scr.width() * 0.95))
        _h = min(800, int(_scr.height() * 0.85))
        ventana.resize(_w, _h)
        ventana.setMaximumHeight(int(_scr.height() * 0.9))
        ventana.move(_scr.center().x() - _w // 2, _scr.center().y() - _h // 2)

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
        marca_combo.setInsertPolicy(QComboBox.NoInsert)
        marca_combo.addItems(self.marcas_existentes)
        marca_combo.setCurrentText("")  # arrancar vacío para que se vea el listado
        # Autocompletado tipo búsqueda: al escribir muestra las marcas ya
        # registradas que coinciden (coincidencia parcial, sin distinguir
        # mayúsculas), igual que el bloque de proveedor.
        from PySide6.QtWidgets import QCompleter
        _comp_marca = QCompleter(self.marcas_existentes, marca_combo)
        _comp_marca.setCaseSensitivity(Qt.CaseInsensitive)
        _comp_marca.setFilterMode(Qt.MatchContains)
        _comp_marca.setCompletionMode(QCompleter.PopupCompletion)
        marca_combo.setCompleter(_comp_marca)
        if producto_dict and producto_dict.get('marca'):
            marca_combo.setCurrentText(producto_dict['marca'])
        info_grid.addWidget(marca_combo, 3, 1)

        # Tamaño / Medida (presentación) — distingue variantes del mismo artículo
        info_grid.addWidget(
            self._label("Tamaño / Medida (variante)"), 4, 0, 1, 2, Qt.AlignLeft
        )

        presentacion_size_edit = QLineEdit(
            (producto_dict.get('presentacion') or '') if producto_dict else '')
        presentacion_size_edit.setFont(make_font(FONTS['body']))
        presentacion_size_edit.setPlaceholderText('Ej: 1/2", 3 pulgadas, 50 kg, 1 galón, rojo')
        presentacion_size_edit.setToolTip(
            "Sirve para diferenciar variantes del MISMO artículo.\n"
            "Ej: «Tornillo» en 1/2\", 3/4\" y 1\", o «Pintura» en 1 galón y 1/4.\n"
            "Escribe la medida, tamaño, color o presentación que distingue esta versión.")
        info_grid.addWidget(presentacion_size_edit, 5, 0, 1, 2)

        info_grid.addWidget(self._label("Proveedor"), 6, 0, 1, 2, Qt.AlignLeft)

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
        info_grid.addLayout(prov_lay, 7, 0, 1, 2)

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

        # ¿Viene en caja/empaque? — checkbox PROMINENTE (antes era un combo escondido).
        viene_en_caja_check = QCheckBox("\U0001f4e6 Este producto viene en caja / empaque")
        viene_en_caja_check.setFont(make_font(FONTS['body_bold']))
        viene_en_caja_check.setStyleSheet(f"color: {COLORS['primary']};")
        viene_en_caja_check.setCursor(QCursor(Qt.PointingHandCursor))
        if producto_dict and producto_dict.get('viene_en_caja'):
            viene_en_caja_check.setChecked(True)
        inv_grid.addWidget(viene_en_caja_check, 4, 0, 1, 2)

        hint_empaque = QLabel(
            "Marca la casilla si el producto llega empacado. Debajo indicas cuántas "
            "cajas y cuántas unidades trae cada una, y el stock se calcula solo "
            "(ej: 2 cajas × 12 = 24 unidades).")
        hint_empaque.setFont(make_font(FONTS['small']))
        hint_empaque.setStyleSheet(f"color: {COLORS['text_secondary']};")
        hint_empaque.setWordWrap(True)
        inv_grid.addWidget(hint_empaque, 5, 0, 1, 2)

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

        existing_barcodes = []
        if producto_dict and producto_dict.get('local_id'):
            try:
                existing_barcodes = self.barcode_repo.list_for_product(
                    producto_dict['local_id']
                )
            except Exception:
                # La propia acción mostrará un error de migración si se intenta
                # escanear/guardar sobre una base aún no migrada.
                existing_barcodes = []
        barcode_widget = BarcodeCaptureWidget(
            self.barcode_repo,
            existing_barcodes=existing_barcodes,
        )
        right_column.addWidget(barcode_widget)

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

        total_empaque_lbl = QLabel("Total: 0 unidades")
        total_empaque_lbl.setFont(make_font(FONTS['body_bold']))
        total_empaque_lbl.setStyleSheet("color: #047857;")
        cajas_lay.addWidget(total_empaque_lbl)

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

        # El panel de empaque va DEBAJO del checkbox, en la columna izquierda,
        # para que todo el flujo "viene en caja → cajas × unidades = total" quede
        # junto y visible (antes estaba oculto en la columna derecha).
        left_column.addWidget(cajas_group)

        def _calcular_stock_empaque():
            try:
                cajas = int(num_cajas_edit.text() or 0)
                unidades = int(unidades_por_caja_edit.text() or 1)
                total = cajas * unidades
                stock_edit.setText(str(total))
                total_empaque_lbl.setText(f"Total: {total} unidades  ({cajas} × {unidades})")
            except Exception:
                stock_edit.setText('0')
                total_empaque_lbl.setText("Total: 0 unidades")

        num_cajas_edit.textChanged.connect(_calcular_stock_empaque)
        unidades_por_caja_edit.textChanged.connect(_calcular_stock_empaque)

        # Toggle del empaque, ahora gobernado por el checkbox (bool).
        def actualizar_campos_presentacion(es_empaque):
            cajas_group.setVisible(bool(es_empaque))
            if es_empaque:
                stock_label_widget.setText("Stock (calculado por empaque)")
                stock_label_widget.setStyleSheet(f"color: {COLORS['info']};")
                stock_edit.setReadOnly(True)
                if producto_dict and producto_dict.get('viene_en_caja'):
                    stock_actual = producto_dict.get('stock', 0)
                    unidades_caja = producto_dict.get('unidades_por_caja', 1)
                    if unidades_caja > 0:
                        num_cajas_edit.setText(str(int(stock_actual // unidades_caja)))
                    unidades_por_caja_edit.setText(str(unidades_caja))
                _calcular_stock_empaque()
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
        viene_en_caja_check.toggled.connect(actualizar_campos_presentacion)
        actualizar_campos_presentacion(viene_en_caja_check.isChecked())
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

        # El cuerpo hace scroll interno; header y footer quedan fijos (sticky),
        # de modo que los botones Guardar/Cancelar siempre estén visibles.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"QScrollArea {{ background: {COLORS['bg_primary']}; border: none; }}")
        scroll.setWidget(body)
        main_layout.addWidget(scroll, 1)

        # ========== FOOTER ==========
        footer = QFrame()
        footer.setFixedHeight(60)
        footer.setStyleSheet("background: #f8f9fa; border-top: 1px solid #dee2e6;")
        footer_lay = QHBoxLayout(footer)
        footer_lay.setAlignment(Qt.AlignCenter)

        btn_guardar = QPushButton("💾  Guardar Producto")
        btn_guardar.setFont(make_font(FONTS['body_bold']))
        btn_guardar.setCursor(QCursor(Qt.PointingHandCursor))
        btn_guardar.setMinimumHeight(44)
        btn_guardar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['accent']}; color: {COLORS['on_accent']}; border: none; "
            f"border-radius: 9px; padding: 12px 30px; font-weight: 500; }}"
            f"QPushButton:hover {{ background: {COLORS['accent_hover']}; }}"
        )
        btn_guardar.clicked.connect(lambda: self.guardar_producto(
            ventana, modo, producto_dict,
            nombre_edit, categoria_combo, marca_combo,
            precio_compra_edit, precio_venta_edit,
            stock_edit, stock_min_edit,
            unidad_base_combo, viene_en_caja_check,
            num_cajas_edit, unidades_por_caja_edit,
            permitir_venta_empaque_check,
            permite_decimales_check,
            presentacion_size_edit, barcode_widget
        ))
        footer_lay.addWidget(btn_guardar)

        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setFont(make_font(FONTS['body']))
        btn_cancelar.setCursor(QCursor(Qt.PointingHandCursor))
        btn_cancelar.setMinimumHeight(44)
        btn_cancelar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['bg_primary']}; color: {COLORS['text_body']}; "
            f"border: 1px solid {COLORS['border_input']}; border-radius: 9px; padding: 12px 30px; font-weight: 500; }}"
            f"QPushButton:hover {{ background: {COLORS['bg_hover']}; border-color: {COLORS['primary_border']}; }}"
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
                         unidad_base_combo, viene_en_caja_check,
                         num_cajas_edit, unidades_por_caja_edit,
                         permitir_venta_empaque_check,
                         permite_decimales_check,
                         presentacion_size_edit=None, barcode_widget=None):
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
            permite_dec = permite_decimales_check.isChecked()

            def _parse_stock(texto):
                """Respeta decimales solo si el producto los permite."""
                texto = (texto or '').strip() or '0'
                return float(texto) if permite_dec else int(float(texto))

            tiene_empaque = viene_en_caja_check.isChecked()

            if tiene_empaque:
                num_cajas = int(num_cajas_edit.text() or 0)
                unidades_caja = int(unidades_por_caja_edit.text() or 1)
                unidades_media_caja = unidades_caja // 2 if unidades_caja > 1 else 1
                stock_total = num_cajas * unidades_caja

                unidad_medida_guardar = unidad_base
                viene_en_caja = True
                vende_por_empaque = 1 if permitir_venta_empaque_check.isChecked() else 0
            else:
                stock_total = _parse_stock(stock_edit.text())
                num_cajas = 0
                unidades_caja = 1
                unidades_media_caja = 1
                unidad_medida_guardar = unidad_base
                viene_en_caja = False
                vende_por_empaque = 0

            proveedor_id = self._proveedor_id_actual
            if proveedor_id == 0:
                proveedor_id = None

            # Tamaño/medida y código histórico. Los barcodes físicos viven
            # exclusivamente en product_barcodes.
            presentacion_size = (presentacion_size_edit.text().strip()
                                 if presentacion_size_edit else '') or None
            codigo_barras = (
                producto_dict.get('codigo_barras') if producto_dict else None
            )

            producto = Producto(
                id=producto_dict['id'] if producto_dict else None,
                codigo_barras=codigo_barras,
                nombre=nombre,
                categoria=categoria_combo.currentText().strip() or None,
                marca=marca_combo.currentText().strip() or None,
                presentacion=presentacion_size,
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
                permite_decimales=permite_dec
            )

            if modo == 'crear':
                exito, mensaje, _ = self.productos_repo.crear_producto(
                    producto,
                    creation_policy=PRODUCT_CREATION_FINAL,
                    verified_barcode=(
                        barcode_widget.verified_barcode if barcode_widget else None
                    ),
                    verified_barcode_type=(
                        barcode_widget.barcode_type if barcode_widget else 'MANUFACTURER'
                    ),
                    verified_barcode_source=(
                        barcode_widget.source if barcode_widget else 'HID_DOUBLE_SCAN'
                    ),
                )
            else:
                exito, mensaje = self.productos_repo.actualizar_producto(producto)
                if exito and barcode_widget and barcode_widget.verified_barcode:
                    try:
                        record = self.barcode_repo.assign_barcode(
                            producto_local_id=producto_dict['local_id'],
                            barcode=barcode_widget.verified_barcode,
                            barcode_type=barcode_widget.barcode_type,
                            source=barcode_widget.source,
                        )
                        if record.barcode != barcode_widget.verified_barcode:
                            raise RuntimeError(
                                "la relectura de DB no coincide con el barcode"
                            )
                        mensaje = "Producto actualizado; CÓDIGO GUARDADO Y VERIFICADO"
                    except Exception as exc:
                        exito = False
                        mensaje = str(exc)

            if exito:
                if barcode_widget and barcode_widget.verified_barcode:
                    barcode_widget.mark_persistence_verified()
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
