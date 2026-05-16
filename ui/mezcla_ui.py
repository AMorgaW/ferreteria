# -*- coding: utf-8 -*-
"""
Ventana Modal de Mezcla de Pinturas (PySide6)
Permite crear mezclas personalizadas seleccionando pinturas base y proporciones
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QFrame,
    QMessageBox, QCheckBox, QAbstractItemView, QSplitter, QWidget
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from ui_config import COLORS, FONTS, ICONS, make_font


class VentanaMezclaPintura(QDialog):
    """Modal para crear una mezcla de pintura personalizada"""

    def __init__(self, parent, mezclas_service, productos_repo, db_manager):
        super().__init__(parent)
        self.mezclas_service = mezclas_service
        self.productos_repo = productos_repo
        self.db_manager = db_manager

        # Resultado: se llena al confirmar
        self.resultado = None

        # Componentes de la mezcla actual
        self.componentes = []

        # Configurar ventana
        self.setWindowTitle("Nueva Mezcla de Pintura")
        self.setFixedSize(950, 700)
        self.setModal(True)

        self.pinturas_data = []

        self.crear_ui()
        self.cargar_pinturas()

    def crear_ui(self):
        """Crea la interfaz completa del modal"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # === HEADER ===
        header = QFrame()
        header.setFixedHeight(60)
        header.setStyleSheet(f"background: {COLORS['primary']};")
        header_layout = QHBoxLayout(header)

        title = QLabel("Mezcla de Pintura Personalizada")
        title.setFont(QFont('Segoe UI', 18, QFont.Bold))
        title.setStyleSheet("color: white; background: transparent;")
        header_layout.addWidget(title)

        header_layout.addStretch()

        btn_close = QPushButton("X")
        btn_close.setFont(QFont('Segoe UI', 12, QFont.Bold))
        btn_close.setFixedWidth(40)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet(
            f"QPushButton {{ background: {COLORS['danger']}; color: white; border: none; "
            f"border-radius: 4px; padding: 5px; }}"
            f"QPushButton:hover {{ background: {COLORS['danger_dark']}; }}"
        )
        btn_close.clicked.connect(self.reject)
        header_layout.addWidget(btn_close)

        main_layout.addWidget(header)

        # === CUERPO PRINCIPAL (2 columnas) ===
        body = QHBoxLayout()
        body.setContentsMargins(15, 10, 15, 0)
        body.setSpacing(16)

        # COLUMNA IZQUIERDA - Buscador de pinturas
        left = QFrame()
        left.setFixedWidth(440)
        left.setStyleSheet("background: white; border-radius: 6px;")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self._crear_panel_busqueda(left_layout)
        body.addWidget(left)

        # COLUMNA DERECHA - Mezcla actual
        right = QFrame()
        right.setStyleSheet("background: white; border-radius: 6px;")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self._crear_panel_mezcla(right_layout)
        body.addWidget(right, 1)

        main_layout.addLayout(body, 1)

        # === FOOTER ===
        footer = QFrame()
        footer.setFixedHeight(60)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(15, 0, 15, 10)
        self._crear_footer(footer_layout)
        main_layout.addWidget(footer)

    def _crear_panel_busqueda(self, layout):
        """Panel izquierdo: buscador de pinturas base"""
        title = QLabel("Seleccionar Pinturas Base")
        title.setFont(QFont('Segoe UI', 14, QFont.Bold))
        title.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent; padding: 15px 15px 5px 15px;")
        layout.addWidget(title)

        # Búsqueda
        search_frame = QFrame()
        search_frame.setStyleSheet("background: transparent;")
        search_layout = QVBoxLayout(search_frame)
        search_layout.setContentsMargins(15, 5, 15, 5)

        self.search_entry = QLineEdit()
        self.search_entry.setFont(make_font(FONTS['body']))
        self.search_entry.setPlaceholderText("Buscar por nombre o marca...")
        self.search_entry.setStyleSheet("border: 1px solid #d1d5db; border-radius: 4px; padding: 6px;")
        self.search_entry.textChanged.connect(self._filtrar_pinturas)
        search_layout.addWidget(self.search_entry)

        layout.addWidget(search_frame)

        # Tabla de pinturas disponibles
        self.table_pinturas = QTableWidget()
        self.table_pinturas.setColumnCount(4)
        self.table_pinturas.setHorizontalHeaderLabels(['Nombre', 'Marca', 'Precio', 'Stock'])
        self.table_pinturas.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_pinturas.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_pinturas.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_pinturas.verticalHeader().setVisible(False)
        self.table_pinturas.setStyleSheet("QTableWidget { margin: 0 15px; }")

        hdr = self.table_pinturas.horizontalHeader()
        hdr.resizeSection(0, 160)
        hdr.resizeSection(1, 80)
        hdr.resizeSection(2, 80)
        hdr.resizeSection(3, 60)
        hdr.setStretchLastSection(True)

        layout.addWidget(self.table_pinturas, 1)

        # Cantidad + Unidad + Agregar
        add_frame = QFrame()
        add_frame.setStyleSheet("background: transparent;")
        add_layout = QHBoxLayout(add_frame)
        add_layout.setContentsMargins(15, 5, 15, 5)

        lbl_cant = QLabel("Cantidad:")
        lbl_cant.setFont(make_font(FONTS['body']))
        lbl_cant.setStyleSheet("background: transparent;")
        add_layout.addWidget(lbl_cant)

        self.cantidad_entry = QLineEdit("1.000")
        self.cantidad_entry.setFont(make_font(FONTS['body']))
        self.cantidad_entry.setFixedWidth(80)
        self.cantidad_entry.setAlignment(Qt.AlignCenter)
        self.cantidad_entry.setStyleSheet("border: 1px solid #d1d5db; border-radius: 4px; padding: 4px;")
        add_layout.addWidget(self.cantidad_entry)

        self.unidad_combo = QComboBox()
        self.unidad_combo.setFont(make_font(FONTS['small']))
        self.unidad_combo.addItems(['L', 'ml', 'Galon', '1/2 Galon', '1/4 Galon'])
        self.unidad_combo.setFixedWidth(100)
        add_layout.addWidget(self.unidad_combo)

        add_layout.addStretch()

        btn_agregar = QPushButton("Agregar a Mezcla")
        btn_agregar.setFont(make_font(FONTS['body_bold']))
        btn_agregar.setCursor(Qt.PointingHandCursor)
        btn_agregar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['primary']}; color: white; border: none; "
            f"border-radius: 4px; padding: 6px 15px; }}"
            f"QPushButton:hover {{ background: {COLORS['primary_dark']}; }}"
        )
        btn_agregar.clicked.connect(self._agregar_componente)
        add_layout.addWidget(btn_agregar)

        layout.addWidget(add_frame)

        # Cargar formulas guardadas
        btn_formulas = QPushButton("Cargar Formula Guardada")
        btn_formulas.setFont(make_font(FONTS['small']))
        btn_formulas.setCursor(Qt.PointingHandCursor)
        btn_formulas.setStyleSheet(
            f"QPushButton {{ background: {COLORS['info']}; color: white; border: none; "
            f"border-radius: 4px; padding: 6px; margin: 0 15px 10px 15px; }}"
            f"QPushButton:hover {{ background: #0891b2; }}"
        )
        btn_formulas.clicked.connect(self._abrir_formulas_guardadas)
        layout.addWidget(btn_formulas)

    def _crear_panel_mezcla(self, layout):
        """Panel derecho: composicion de la mezcla"""
        title = QLabel("Composicion de la Mezcla")
        title.setFont(QFont('Segoe UI', 14, QFont.Bold))
        title.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent; padding: 15px 15px 5px 15px;")
        layout.addWidget(title)

        # Nombre de la mezcla
        nombre_frame = QFrame()
        nombre_frame.setStyleSheet("background: transparent;")
        nombre_layout = QVBoxLayout(nombre_frame)
        nombre_layout.setContentsMargins(15, 5, 15, 5)

        lbl_nombre = QLabel("Nombre de la mezcla:")
        lbl_nombre.setFont(make_font(FONTS['body']))
        lbl_nombre.setStyleSheet("background: transparent;")
        nombre_layout.addWidget(lbl_nombre)

        self.nombre_mezcla_entry = QLineEdit()
        self.nombre_mezcla_entry.setFont(make_font(FONTS['body']))
        self.nombre_mezcla_entry.setPlaceholderText('Ej: "Verde Menta - Casa Sra. Maria"')
        self.nombre_mezcla_entry.setStyleSheet("border: 1px solid #d1d5db; border-radius: 4px; padding: 5px;")
        nombre_layout.addWidget(self.nombre_mezcla_entry)

        layout.addWidget(nombre_frame)

        # Tabla de componentes
        self.table_componentes = QTableWidget()
        self.table_componentes.setColumnCount(4)
        self.table_componentes.setHorizontalHeaderLabels(['Pintura', 'Cantidad', 'Unidad', 'Costo'])
        self.table_componentes.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_componentes.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_componentes.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_componentes.verticalHeader().setVisible(False)
        self.table_componentes.setStyleSheet("QTableWidget { margin: 0 15px; }")

        hdr = self.table_componentes.horizontalHeader()
        hdr.resizeSection(0, 170)
        hdr.resizeSection(1, 80)
        hdr.resizeSection(2, 70)
        hdr.resizeSection(3, 90)
        hdr.setStretchLastSection(True)

        layout.addWidget(self.table_componentes, 1)

        # Botón quitar
        btn_quitar_frame = QFrame()
        btn_quitar_frame.setStyleSheet("background: transparent;")
        btn_quitar_layout = QHBoxLayout(btn_quitar_frame)
        btn_quitar_layout.setContentsMargins(15, 5, 15, 5)
        btn_quitar_layout.addStretch()

        btn_quitar = QPushButton("Quitar Seleccionado")
        btn_quitar.setFont(make_font(FONTS['small']))
        btn_quitar.setCursor(Qt.PointingHandCursor)
        btn_quitar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['danger']}; color: white; border: none; "
            f"border-radius: 4px; padding: 4px 10px; }}"
            f"QPushButton:hover {{ background: {COLORS['danger_dark']}; }}"
        )
        btn_quitar.clicked.connect(self._quitar_componente)
        btn_quitar_layout.addWidget(btn_quitar)

        layout.addWidget(btn_quitar_frame)

        # Resumen de costos
        resumen = QFrame()
        resumen.setStyleSheet(f"background: {COLORS['bg_secondary']}; margin: 5px 15px 10px 15px; border-radius: 4px;")
        resumen_layout = QVBoxLayout(resumen)
        resumen_layout.setContentsMargins(10, 8, 10, 8)
        resumen_layout.setSpacing(4)

        # Volumen total
        row_vol = QHBoxLayout()
        lbl_v = QLabel("Volumen Total:")
        lbl_v.setFont(make_font(FONTS['body']))
        lbl_v.setStyleSheet("background: transparent;")
        row_vol.addWidget(lbl_v)
        row_vol.addStretch()
        self.lbl_volumen = QLabel("0.000 L")
        self.lbl_volumen.setFont(make_font(FONTS['body_bold']))
        self.lbl_volumen.setStyleSheet(f"color: {COLORS['info']}; background: transparent;")
        row_vol.addWidget(self.lbl_volumen)
        resumen_layout.addLayout(row_vol)

        # Costo calculado
        row_costo = QHBoxLayout()
        lbl_c = QLabel("Costo Componentes:")
        lbl_c.setFont(make_font(FONTS['body']))
        lbl_c.setStyleSheet("background: transparent;")
        row_costo.addWidget(lbl_c)
        row_costo.addStretch()
        self.lbl_costo = QLabel("$0")
        self.lbl_costo.setFont(make_font(FONTS['body_bold']))
        self.lbl_costo.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent;")
        row_costo.addWidget(self.lbl_costo)
        resumen_layout.addLayout(row_costo)

        # Precio de venta
        row_precio = QHBoxLayout()
        lbl_p = QLabel("Precio de Venta:")
        lbl_p.setFont(make_font(FONTS['body_bold']))
        lbl_p.setStyleSheet(f"color: {COLORS['primary']}; background: transparent;")
        row_precio.addWidget(lbl_p)
        row_precio.addStretch()
        self.precio_venta_entry = QLineEdit("0")
        self.precio_venta_entry.setFont(make_font(FONTS['body_bold']))
        self.precio_venta_entry.setFixedWidth(100)
        self.precio_venta_entry.setAlignment(Qt.AlignRight)
        self.precio_venta_entry.setStyleSheet("border: 1px solid #d1d5db; border-radius: 4px; padding: 3px;")
        row_precio.addWidget(self.precio_venta_entry)
        resumen_layout.addLayout(row_precio)

        layout.addWidget(resumen)

    def _crear_footer(self, layout):
        """Footer con botones de accion"""
        self.guardar_formula_check = QCheckBox("Guardar como formula reutilizable")
        self.guardar_formula_check.setFont(make_font(FONTS['body']))
        layout.addWidget(self.guardar_formula_check)

        layout.addStretch()

        btn_confirmar = QPushButton("Agregar Mezcla al Carrito")
        btn_confirmar.setFont(make_font(FONTS['body_bold']))
        btn_confirmar.setCursor(Qt.PointingHandCursor)
        btn_confirmar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['success']}; color: white; border: none; "
            f"border-radius: 6px; padding: 8px 25px; }}"
            f"QPushButton:hover {{ background: {COLORS['success_dark']}; }}"
        )
        btn_confirmar.clicked.connect(self._confirmar_mezcla)
        layout.addWidget(btn_confirmar)

        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setFont(make_font(FONTS['body_bold']))
        btn_cancelar.setCursor(Qt.PointingHandCursor)
        btn_cancelar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['secondary']}; color: white; border: none; "
            f"border-radius: 6px; padding: 8px 25px; }}"
            f"QPushButton:hover {{ background: #4b5563; }}"
        )
        btn_cancelar.clicked.connect(self.reject)
        layout.addWidget(btn_cancelar)

    # ====================================
    # LOGICA
    # ====================================

    def cargar_pinturas(self):
        """Carga solo los productos de la categoria Pinturas"""
        try:
            todos = self.productos_repo.listar_productos(solo_activos=True)
            self.pinturas_data = [
                p for p in todos
                if (p.get('categoria') or '').lower() == 'pinturas'
            ]
            self._mostrar_pinturas(self.pinturas_data)
        except Exception as e:
            print(f"[ERROR] Error cargando pinturas: {e}")

    def _mostrar_pinturas(self, pinturas):
        """Muestra pinturas en la tabla"""
        self.table_pinturas.setRowCount(0)

        for row, p in enumerate(pinturas):
            self.table_pinturas.insertRow(row)
            stock = p.get('stock', 0)

            item_nombre = QTableWidgetItem(p.get('nombre', '')[:30])
            item_marca = QTableWidgetItem((p.get('marca') or '')[:15])
            item_precio = QTableWidgetItem(f"${p.get('precio_venta', 0):,.0f}")
            item_stock = QTableWidgetItem(f"{stock:.3f}" if isinstance(stock, float) else str(stock))

            # Store product id as user data
            item_nombre.setData(Qt.UserRole, p.get('id'))

            self.table_pinturas.setItem(row, 0, item_nombre)
            self.table_pinturas.setItem(row, 1, item_marca)
            self.table_pinturas.setItem(row, 2, item_precio)
            self.table_pinturas.setItem(row, 3, item_stock)

    def _filtrar_pinturas(self):
        """Filtra pinturas por texto de busqueda"""
        termino = self.search_entry.text().lower()
        if not termino:
            self._mostrar_pinturas(self.pinturas_data)
            return

        filtradas = [p for p in self.pinturas_data
                     if termino in (p.get('nombre', '') or '').lower()
                     or termino in (p.get('marca', '') or '').lower()]
        self._mostrar_pinturas(filtradas)

    def _agregar_componente(self):
        """Agrega la pintura seleccionada como componente de la mezcla"""
        row = self.table_pinturas.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Advertencia", "Seleccione una pintura de la lista")
            return

        producto_id = self.table_pinturas.item(row, 0).data(Qt.UserRole)
        producto = self.productos_repo.obtener_por_id(producto_id)

        if not producto:
            QMessageBox.critical(self, "Error", "Producto no encontrado")
            return

        # Validar cantidad
        try:
            cantidad = float(self.cantidad_entry.text().replace(',', '.'))
            if cantidad <= 0:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "Advertencia",
                                "Ingrese una cantidad valida (mayor a 0)")
            return

        unidad = self.unidad_combo.currentText()
        cantidad_litros = self._convertir_a_litros(cantidad, unidad)
        cantidad_galones = self._convertir_a_galones(cantidad, unidad)

        # Verificar stock
        stock_actual = producto.get('stock', 0)
        ya_agregado = sum(c['cantidad_galones'] for c in self.componentes
                         if c['producto']['id'] == producto_id)

        if stock_actual < (ya_agregado + cantidad_galones):
            QMessageBox.warning(self, "Stock insuficiente",
                                f"Stock disponible: {stock_actual:.3f} gal\n"
                                f"Ya en mezcla: {ya_agregado:.3f} gal\n"
                                f"Intentando agregar: {cantidad_galones:.3f} gal")
            return

        self.componentes.append({
            'producto': producto,
            'cantidad': cantidad,
            'cantidad_litros': cantidad_litros,
            'cantidad_galones': cantidad_galones,
            'unidad': unidad,
            'costo': producto.get('precio_venta', 0) * cantidad_galones
        })

        self._actualizar_tabla_componentes()
        self._actualizar_resumen()

    def _convertir_a_litros(self, cantidad, unidad):
        """Convierte la cantidad a litros segun la unidad"""
        conversiones = {
            'L': 1.0,
            'ml': 0.001,
            'Galon': 3.785,
            '1/2 Galon': 1.8925,
            '1/4 Galon': 0.946
        }
        factor = conversiones.get(unidad, 1.0)
        return cantidad * factor

    def _convertir_a_galones(self, cantidad, unidad):
        """Convierte la cantidad a galones (unidad de stock del producto)"""
        conversiones_a_galon = {
            'Galon': 1.0,
            '1/2 Galon': 0.5,
            '1/4 Galon': 0.25,
            'L': 1.0 / 3.785,
            'ml': 1.0 / 3785.0,
        }
        factor = conversiones_a_galon.get(unidad, 1.0 / 3.785)
        return cantidad * factor

    def _quitar_componente(self):
        """Quita el componente seleccionado"""
        row = self.table_componentes.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Advertencia",
                                "Seleccione un componente para quitar")
            return

        if 0 <= row < len(self.componentes):
            del self.componentes[row]
            self._actualizar_tabla_componentes()
            self._actualizar_resumen()

    def _actualizar_tabla_componentes(self):
        """Actualiza la tabla de componentes de la mezcla"""
        self.table_componentes.setRowCount(0)

        for idx, comp in enumerate(self.componentes):
            self.table_componentes.insertRow(idx)
            nombre = comp['producto'].get('nombre', '')[:25]
            self.table_componentes.setItem(idx, 0, QTableWidgetItem(nombre))
            self.table_componentes.setItem(idx, 1, QTableWidgetItem(f"{comp['cantidad']:.3f}"))
            self.table_componentes.setItem(idx, 2, QTableWidgetItem(comp['unidad']))
            self.table_componentes.setItem(idx, 3, QTableWidgetItem(f"${comp['costo']:,.0f}"))

    def _actualizar_resumen(self):
        """Actualiza el resumen de volumen y costo"""
        volumen_total = sum(c['cantidad_litros'] for c in self.componentes)
        costo_total = sum(c['costo'] for c in self.componentes)

        self.lbl_volumen.setText(f"{volumen_total:.3f} L")
        self.lbl_costo.setText(f"${costo_total:,.0f}")

        if self.precio_venta_entry.text() == "0":
            self.precio_venta_entry.setText(f"{costo_total:.0f}")

    def _confirmar_mezcla(self):
        """Valida y confirma la mezcla para agregarla al carrito"""
        if not self.componentes:
            QMessageBox.warning(self, "Advertencia",
                                "Agregue al menos una pintura a la mezcla")
            return

        try:
            precio_venta = float(self.precio_venta_entry.text().replace(',', '.').replace('$', ''))
            if precio_venta <= 0:
                QMessageBox.warning(self, "Advertencia",
                                    "Ingrese un precio de venta valido")
                return
        except ValueError:
            QMessageBox.warning(self, "Advertencia",
                                "El precio de venta no es valido")
            return

        nombre = self.nombre_mezcla_entry.text().strip()
        if not nombre:
            nombre = "Mezcla Personalizada"

        componentes_para_stock = []
        for comp in self.componentes:
            componentes_para_stock.append({
                'producto_id': comp['producto']['id'],
                'cantidad': comp['cantidad_galones']
            })

        valido, msg = self.mezclas_service.validar_stock_componentes(componentes_para_stock)
        if not valido:
            QMessageBox.critical(self, "Stock insuficiente", msg)
            return

        formula_id = None
        if self.guardar_formula_check.isChecked():
            comps_formula = [{'producto_id': c['producto']['id'],
                              'cantidad': c['cantidad_galones'],
                              'unidad': 'GAL'} for c in self.componentes]
            exito, msg_f, fid = self.mezclas_service.guardar_formula(
                nombre=nombre,
                componentes=comps_formula,
                precio_venta=precio_venta,
                cliente_referencia=nombre
            )
            if exito:
                formula_id = fid

        volumen_total = sum(c['cantidad_litros'] for c in self.componentes)

        self.resultado = {
            'nombre': f"Mezcla: {nombre} ({volumen_total:.2f}L)",
            'precio_venta': precio_venta,
            'volumen_total': volumen_total,
            'formula_id': formula_id,
            'componentes': [
                {
                    'producto_id': c['producto']['id'],
                    'producto_nombre': c['producto'].get('nombre', ''),
                    'cantidad': c['cantidad_galones'],
                    'cantidad_litros': c['cantidad_litros'],
                    'unidad': 'GAL',
                    'costo': c['costo']
                } for c in self.componentes
            ]
        }

        self.accept()

    def _abrir_formulas_guardadas(self):
        """Abre ventana de formulas guardadas"""
        formulas = self.mezclas_service.obtener_formulas()

        if not formulas:
            QMessageBox.information(self, "Sin formulas",
                                    "No hay formulas guardadas aun.\n"
                                    "Crea una mezcla y marca 'Guardar como formula'.")
            return

        ventana = QDialog(self)
        ventana.setWindowTitle("Formulas Guardadas")
        ventana.setFixedSize(600, 400)
        ventana.setModal(True)

        v_layout = QVBoxLayout(ventana)
        v_layout.setContentsMargins(20, 15, 20, 15)

        lbl_title = QLabel("Formulas de Mezcla Guardadas")
        lbl_title.setFont(QFont('Segoe UI', 14, QFont.Bold))
        lbl_title.setStyleSheet(f"color: {COLORS['text_primary']};")
        lbl_title.setAlignment(Qt.AlignCenter)
        v_layout.addWidget(lbl_title)

        # Tabla
        tree = QTableWidget()
        tree.setColumnCount(4)
        tree.setHorizontalHeaderLabels(['Nombre', 'Volumen (L)', 'Precio', 'Fecha'])
        tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        tree.setSelectionMode(QAbstractItemView.SingleSelection)
        tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tree.verticalHeader().setVisible(False)

        hdr = tree.horizontalHeader()
        hdr.resizeSection(0, 200)
        hdr.resizeSection(1, 100)
        hdr.resizeSection(2, 100)
        hdr.setStretchLastSection(True)

        for row, f in enumerate(formulas):
            tree.insertRow(row)
            item_nombre = QTableWidgetItem(f.get('nombre', ''))
            item_nombre.setData(Qt.UserRole, f.get('id'))
            tree.setItem(row, 0, item_nombre)
            tree.setItem(row, 1, QTableWidgetItem(f"{f.get('volumen_total', 0):.3f}"))
            tree.setItem(row, 2, QTableWidgetItem(f"${f.get('precio_venta', 0):,.0f}"))
            tree.setItem(row, 3, QTableWidgetItem(str(f.get('fecha_creacion', ''))[:16]))

        v_layout.addWidget(tree, 1)

        # Botones
        btn_layout = QHBoxLayout()

        def cargar_seleccionada():
            r = tree.currentRow()
            if r < 0:
                QMessageBox.warning(ventana, "Advertencia", "Seleccione una formula")
                return
            formula_id = tree.item(r, 0).data(Qt.UserRole)
            self._cargar_formula(formula_id)
            ventana.accept()

        def eliminar_seleccionada():
            r = tree.currentRow()
            if r < 0:
                return
            formula_id = tree.item(r, 0).data(Qt.UserRole)
            resp = QMessageBox.question(ventana, "Confirmar", "Eliminar esta formula?",
                                        QMessageBox.Yes | QMessageBox.No)
            if resp == QMessageBox.Yes:
                self.mezclas_service.eliminar_formula(formula_id)
                tree.removeRow(r)

        btn_cargar = QPushButton("Cargar Formula")
        btn_cargar.setFont(make_font(FONTS['body_bold']))
        btn_cargar.setCursor(Qt.PointingHandCursor)
        btn_cargar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['success']}; color: white; border: none; "
            f"border-radius: 4px; padding: 6px 18px; }}"
            f"QPushButton:hover {{ background: {COLORS['success_dark']}; }}"
        )
        btn_cargar.clicked.connect(cargar_seleccionada)
        btn_layout.addWidget(btn_cargar)

        btn_eliminar = QPushButton("Eliminar")
        btn_eliminar.setFont(make_font(FONTS['body']))
        btn_eliminar.setCursor(Qt.PointingHandCursor)
        btn_eliminar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['danger']}; color: white; border: none; "
            f"border-radius: 4px; padding: 6px 12px; }}"
            f"QPushButton:hover {{ background: {COLORS['danger_dark']}; }}"
        )
        btn_eliminar.clicked.connect(eliminar_seleccionada)
        btn_layout.addWidget(btn_eliminar)

        btn_layout.addStretch()

        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setFont(make_font(FONTS['body']))
        btn_cerrar.setCursor(Qt.PointingHandCursor)
        btn_cerrar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['secondary']}; color: white; border: none; "
            f"border-radius: 4px; padding: 6px 18px; }}"
            f"QPushButton:hover {{ background: #4b5563; }}"
        )
        btn_cerrar.clicked.connect(ventana.reject)
        btn_layout.addWidget(btn_cerrar)

        v_layout.addLayout(btn_layout)
        ventana.exec()

    def _cargar_formula(self, formula_id):
        """Carga una formula guardada en la mezcla actual"""
        formula = self.mezclas_service.obtener_formula_detalle(formula_id)
        if not formula:
            QMessageBox.critical(self, "Error", "No se pudo cargar la formula")
            return

        self.componentes = []

        self.nombre_mezcla_entry.setText(formula.get('nombre', ''))
        self.precio_venta_entry.setText(str(int(formula.get('precio_venta', 0))))

        for comp in formula.get('componentes', []):
            producto = self.productos_repo.obtener_por_id(comp['producto_id'])
            if producto:
                cantidad_galones = comp.get('cantidad', 0)
                cantidad_litros = cantidad_galones * 3.785
                self.componentes.append({
                    'producto': producto,
                    'cantidad': cantidad_galones,
                    'cantidad_litros': cantidad_litros,
                    'cantidad_galones': cantidad_galones,
                    'unidad': 'Galon',
                    'costo': producto.get('precio_venta', 0) * cantidad_galones
                })

        self._actualizar_tabla_componentes()
        self._actualizar_resumen()
