# -*- coding: utf-8 -*-
"""
Interfaz para registro de entradas de inventario (PySide6)
Con entrada en múltiples unidades según categoría del producto
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QFrame, QMessageBox, QRadioButton, QButtonGroup, QSizePolicy,
    QScrollArea, QApplication
)
from PySide6.QtCore import Qt
from datetime import datetime
from models import MovimientoInventario
from ui_config import COLORS, FONTS, make_font
from unidades_venta_manager import UnidadesVentaManager


class EntradaInventarioUI(QDialog):
    """Interfaz para nueva entrada de inventario"""

    def __init__(self, parent, inventario_repo, productos_repo, proveedores_repo, auth, db_manager, alertas_service=None):
        super().__init__(parent)
        self.parent_widget = parent
        self.inventario_repo = inventario_repo
        self.productos_repo = productos_repo
        self.proveedores_repo = proveedores_repo
        self.auth = auth
        self.db_manager = db_manager
        self.alertas_service = alertas_service
        self.unidades_manager = UnidadesVentaManager(db_manager)

        self.producto_seleccionado = None
        self.proveedor_seleccionado = None
        self.unidades_disponibles = []
        self._unidad_seleccionada_valor = ""

        self.crear_ventana()

    def crear_ventana(self):
        """Crea la ventana de entrada"""
        self.setWindowTitle("Entrada de Inventario")
        _scr = (self.screen().availableGeometry() if self.screen()
                else QApplication.primaryScreen().availableGeometry())
        _w, _h = 600, min(650, int(_scr.height() * 0.85))
        self.resize(_w, _h)
        self.setMaximumHeight(int(_scr.height() * 0.9))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setStyleSheet("background: white;")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(80)
        header.setStyleSheet(f"background: {COLORS['success']};")
        header_layout = QVBoxLayout(header)
        header_layout.setAlignment(Qt.AlignCenter)
        lbl_title = QLabel("📦 Nueva Entrada")
        lbl_title.setFont(make_font(FONTS['xlarge']))
        lbl_title.setStyleSheet(f"color: white; background: transparent;")
        lbl_title.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(lbl_title)
        main_layout.addWidget(header)

        # Contenido (scrollable area via widget)
        content = QFrame()
        content.setStyleSheet("background: white;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(30, 20, 30, 20)
        content_layout.setSpacing(0)

        # Tipo de movimiento
        lbl_tipo = QLabel("Tipo de movimiento *")
        lbl_tipo.setFont(make_font(FONTS['body']))
        lbl_tipo.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        content_layout.addWidget(lbl_tipo)
        content_layout.addSpacing(5)

        self.tipo_combo = QComboBox()
        self.tipo_combo.setFont(make_font(FONTS['body']))
        self.tipo_combo.addItems(['ENTRADA_COMPRA', 'ENTRADA_AJUSTE', 'ENTRADA_DEVOLUCION'])
        self.tipo_combo.setStyleSheet(
            "QComboBox { border: 1px solid #d1d5db; border-radius: 4px; padding: 6px; background: white; }"
        )
        content_layout.addWidget(self.tipo_combo)
        content_layout.addSpacing(15)

        # Producto
        lbl_prod = QLabel("Producto *")
        lbl_prod.setFont(make_font(FONTS['body']))
        lbl_prod.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        content_layout.addWidget(lbl_prod)
        content_layout.addSpacing(5)

        producto_row = QHBoxLayout()
        producto_row.setSpacing(5)
        self.producto_entry = QLineEdit()
        self.producto_entry.setFont(make_font(FONTS['body']))
        self.producto_entry.setStyleSheet(
            "QLineEdit { border: 1px solid #d1d5db; border-radius: 4px; padding: 6px; background: white; }"
        )
        producto_row.addWidget(self.producto_entry, 1)

        btn_buscar_prod = QPushButton("🔍 Buscar")
        btn_buscar_prod.setFont(make_font(FONTS['body']))
        btn_buscar_prod.setCursor(Qt.PointingHandCursor)
        btn_buscar_prod.setStyleSheet(
            f"QPushButton {{ background: {COLORS['primary']}; color: white; border: none; "
            f"border-radius: 8px; padding: 7px 14px; font-weight: 500; }}"
            f"QPushButton:hover {{ background: {COLORS['primary_dark']}; }}"
        )
        btn_buscar_prod.clicked.connect(self.buscar_producto)
        producto_row.addWidget(btn_buscar_prod)
        content_layout.addLayout(producto_row)
        content_layout.addSpacing(15)

        # Marca (solo lectura)
        lbl_marca = QLabel("Marca")
        lbl_marca.setFont(make_font(FONTS['body']))
        lbl_marca.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        content_layout.addWidget(lbl_marca)
        content_layout.addSpacing(5)

        self.marca_entry = QLineEdit()
        self.marca_entry.setFont(make_font(FONTS['body']))
        self.marca_entry.setReadOnly(True)
        self.marca_entry.setStyleSheet(
            "QLineEdit { border: 1px solid #d1d5db; border-radius: 4px; padding: 6px; background: #f9fafb; }"
        )
        content_layout.addWidget(self.marca_entry)
        content_layout.addSpacing(15)

        # Proveedor
        lbl_prov = QLabel("Proveedor")
        lbl_prov.setFont(make_font(FONTS['body']))
        lbl_prov.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        content_layout.addWidget(lbl_prov)
        content_layout.addSpacing(5)

        proveedor_row = QHBoxLayout()
        proveedor_row.setSpacing(5)
        self.proveedor_entry = QLineEdit()
        self.proveedor_entry.setFont(make_font(FONTS['body']))
        self.proveedor_entry.setStyleSheet(
            "QLineEdit { border: 1px solid #d1d5db; border-radius: 4px; padding: 6px; background: white; }"
        )
        proveedor_row.addWidget(self.proveedor_entry, 1)

        btn_buscar_prov = QPushButton("🔍 Buscar")
        btn_buscar_prov.setFont(make_font(FONTS['body']))
        btn_buscar_prov.setCursor(Qt.PointingHandCursor)
        btn_buscar_prov.setStyleSheet(
            f"QPushButton {{ background: {COLORS['primary']}; color: white; border: none; "
            f"border-radius: 8px; padding: 7px 14px; font-weight: 500; }}"
            f"QPushButton:hover {{ background: {COLORS['primary_dark']}; }}"
        )
        btn_buscar_prov.clicked.connect(self.buscar_proveedor)
        proveedor_row.addWidget(btn_buscar_prov)
        content_layout.addLayout(proveedor_row)
        content_layout.addSpacing(10)

        # Frame para unidades de entrada (dinámico)
        self.unidades_frame = QFrame()
        self.unidades_frame.setStyleSheet("background: transparent;")
        self.unidades_layout = QVBoxLayout(self.unidades_frame)
        self.unidades_layout.setContentsMargins(0, 0, 0, 0)
        self.unidades_layout.setSpacing(2)
        content_layout.addWidget(self.unidades_frame)
        content_layout.addSpacing(5)

        # Cantidad
        lbl_cant = QLabel("Cantidad *")
        lbl_cant.setFont(make_font(FONTS['body']))
        lbl_cant.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        content_layout.addWidget(lbl_cant)
        content_layout.addSpacing(5)

        self.cantidad_entry = QLineEdit("1")
        self.cantidad_entry.setFont(make_font(FONTS['body']))
        self.cantidad_entry.setStyleSheet(
            "QLineEdit { border: 1px solid #d1d5db; border-radius: 4px; padding: 6px; background: white; }"
        )
        content_layout.addWidget(self.cantidad_entry)
        content_layout.addSpacing(15)

        # Precio unitario
        lbl_precio = QLabel("Precio unitario *")
        lbl_precio.setFont(make_font(FONTS['body']))
        lbl_precio.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        content_layout.addWidget(lbl_precio)
        content_layout.addSpacing(5)

        self.precio_entry = QLineEdit("0")
        self.precio_entry.setFont(make_font(FONTS['body']))
        self.precio_entry.setStyleSheet(
            "QLineEdit { border: 1px solid #d1d5db; border-radius: 4px; padding: 6px; background: white; }"
        )
        content_layout.addWidget(self.precio_entry)
        content_layout.addSpacing(15)

        # Número de factura
        lbl_factura = QLabel("Número de factura (opcional)")
        lbl_factura.setFont(make_font(FONTS['body']))
        lbl_factura.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        content_layout.addWidget(lbl_factura)
        content_layout.addSpacing(5)

        self.factura_entry = QLineEdit()
        self.factura_entry.setFont(make_font(FONTS['body']))
        self.factura_entry.setStyleSheet(
            "QLineEdit { border: 1px solid #d1d5db; border-radius: 4px; padding: 6px; background: white; }"
        )
        content_layout.addWidget(self.factura_entry)

        content_layout.addStretch()
        # Cuerpo con scroll interno: header y footer quedan fijos (sticky).
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: white; }")
        scroll.setWidget(content)
        main_layout.addWidget(scroll, 1)

        # Footer
        separator = QFrame()
        separator.setFixedHeight(1)
        separator.setStyleSheet("background: #dee2e6;")
        main_layout.addWidget(separator)

        footer = QFrame()
        footer.setFixedHeight(70)
        footer.setStyleSheet("background: #f8f9fa;")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setAlignment(Qt.AlignCenter)
        footer_layout.setSpacing(16)

        btn_guardar = QPushButton("💾 Guardar")
        btn_guardar.setFont(make_font(FONTS['body_bold']))
        btn_guardar.setCursor(Qt.PointingHandCursor)
        btn_guardar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['success']}; color: white; border: none; "
            f"border-radius: 8px; padding: 12px 38px; font-weight: 500; }}"
            f"QPushButton:hover {{ background: {COLORS['success_dark']}; }}"
        )
        btn_guardar.clicked.connect(self.guardar_entrada)

        btn_cancelar = QPushButton("✕  Cancelar")
        btn_cancelar.setFont(make_font(FONTS['body']))
        btn_cancelar.setCursor(Qt.PointingHandCursor)
        btn_cancelar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['bg_primary']}; color: {COLORS['text_body']}; "
            f"border: 1px solid {COLORS['border_input']}; border-radius: 9px; padding: 12px 38px; font-weight: 500; }}"
            f"QPushButton:hover {{ background: {COLORS['bg_hover']}; border-color: {COLORS['primary_border']}; }}"
        )
        btn_cancelar.clicked.connect(self.reject)

        footer_layout.addWidget(btn_guardar)
        footer_layout.addWidget(btn_cancelar)
        main_layout.addWidget(footer)

    def buscar_producto(self):
        """Abre ventana de búsqueda de productos"""
        from ui.buscar_producto_dialog import BuscarProductoDialog
        dialog = BuscarProductoDialog(self, self.productos_repo)
        dialog.exec()

        if dialog.producto_seleccionado:
            self.producto_seleccionado = dialog.producto_seleccionado
            texto = f"{self.producto_seleccionado['nombre']} (ID: {self.producto_seleccionado['id']})"
            self.producto_entry.setText(texto)

            # Mostrar marca (si existe)
            marca = (self.producto_seleccionado.get('marca') or '').strip()
            self.marca_entry.setText(marca)

            # Obtener y mostrar unidades disponibles para este producto
            self.mostrar_unidades_disponibles()

            # Si tiene precio de compra, autocompletar
            if 'precio_compra' in self.producto_seleccionado and self.producto_seleccionado['precio_compra']:
                self.precio_entry.setText(str(self.producto_seleccionado['precio_compra']))

    def mostrar_unidades_disponibles(self):
        """Muestra las unidades disponibles según la categoría del producto"""
        # Limpiar frame
        while self.unidades_layout.count():
            item = self.unidades_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            elif item.layout():
                while item.layout().count():
                    sub = item.layout().takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()

        # Obtener unidades disponibles
        self.unidades_disponibles = self.unidades_manager.obtener_unidades_venta_producto(
            self.producto_seleccionado
        )

        # Si solo hay una unidad, no mostrar selector
        if len(self.unidades_disponibles) == 1:
            self._unidad_seleccionada_valor = self.unidades_disponibles[0]['nombre']
            return

        # Si hay múltiples unidades, mostrar selector
        lbl_unidad = QLabel("Unidad de entrada")
        lbl_unidad.setFont(make_font(FONTS['body']))
        lbl_unidad.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        self.unidades_layout.addWidget(lbl_unidad)

        self.unidad_button_group = QButtonGroup(self)
        self._unidad_seleccionada_valor = self.unidades_disponibles[0]['nombre']

        for idx, unidad_info in enumerate(self.unidades_disponibles):
            nombre_unidad = unidad_info['nombre']
            factor = unidad_info['factor']

            if factor == 1:
                texto = f"{nombre_unidad} (unidad base)"
            else:
                texto = f"{nombre_unidad} (1 = {factor} unidades base)"

            rb = QRadioButton(texto)
            rb.setFont(make_font(FONTS['body']))
            rb.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent;")
            if idx == 0:
                rb.setChecked(True)
            rb.toggled.connect(lambda checked, n=nombre_unidad: self._on_unidad_changed(checked, n))
            self.unidad_button_group.addButton(rb, idx)
            self.unidades_layout.addWidget(rb)

    def _on_unidad_changed(self, checked, nombre):
        if checked:
            self._unidad_seleccionada_valor = nombre

    def buscar_proveedor(self):
        """Abre ventana de búsqueda de proveedores"""
        from ui.buscar_proveedor_dialog import BuscarProveedorDialog
        dialog = BuscarProveedorDialog(self, self.proveedores_repo)
        dialog.exec()

        if dialog.proveedor_seleccionado:
            self.proveedor_seleccionado = dialog.proveedor_seleccionado
            texto = f"{self.proveedor_seleccionado['nombre']} (ID: {self.proveedor_seleccionado['id']})"
            self.proveedor_entry.setText(texto)

    def guardar_entrada(self):
        """Guarda la entrada de inventario"""
        try:
            # Validaciones
            if not self.producto_seleccionado:
                QMessageBox.warning(self, "Advertencia", "Debe seleccionar un producto")
                return

            cantidad_ingresada = float(self.cantidad_entry.text())
            if cantidad_ingresada <= 0:
                QMessageBox.warning(self, "Advertencia", "La cantidad debe ser mayor a 0")
                return

            precio = float(self.precio_entry.text())
            if precio < 0:
                QMessageBox.warning(self, "Advertencia", "El precio no puede ser negativo")
                return

            # Convertir cantidad a unidad base si es necesario
            unidad_actual = self._unidad_seleccionada_valor
            if unidad_actual and self.unidades_disponibles:
                cantidad_base, _ = self.unidades_manager.convertir_a_unidad_base(
                    self.producto_seleccionado,
                    cantidad_ingresada,
                    unidad_actual
                )
            else:
                # Sin unidades configuradas, usar cantidad directa
                cantidad_base = cantidad_ingresada

            # Validar número de factura (no repetido)
            num_factura = self.factura_entry.text().strip() or None
            if num_factura and self.proveedor_seleccionado:
                existe = self.inventario_repo.verificar_factura_existente(
                    num_factura,
                    self.proveedor_seleccionado['id']
                )
                if existe:
                    respuesta = QMessageBox.question(
                        self, "Factura Duplicada",
                        f"Ya existe una entrada con factura '{num_factura}' "
                        f"del proveedor {self.proveedor_seleccionado['nombre']}.\n\n"
                        "¿Desea continuar de todas formas?",
                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                    )
                    if respuesta != QMessageBox.Yes:
                        return

            # Crear movimiento con cantidad convertida a unidad base
            movimiento = MovimientoInventario(
                tipo_movimiento=self.tipo_combo.currentText(),
                producto_id=self.producto_seleccionado['id'],
                proveedor_id=self.proveedor_seleccionado['id'] if self.proveedor_seleccionado else None,
                cantidad=cantidad_base,  # Usar cantidad convertida
                precio_unitario=precio,
                numero_factura=num_factura,
                usuario_id=self.auth.usuario_actual['id'],
                fecha=datetime.now()
            )

            # Guardar
            exito, mensaje = self.inventario_repo.registrar_movimiento(movimiento)

            if exito:
                QMessageBox.information(self, "Éxito", mensaje)

                # Verificar stock mínimo y mostrar alertas
                self.verificar_y_mostrar_alertas_stock()

                self.accept()
            else:
                QMessageBox.critical(self, "Error", mensaje)

        except ValueError:
            QMessageBox.critical(self, "Error", "Los valores numéricos no son válidos")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error guardando entrada:\n{str(e)}")

    def verificar_y_mostrar_alertas_stock(self):
        """Verifica y muestra alertas de stock crítico después de la entrada"""
        if not self.alertas_service:
            return

        try:
            # Obtener productos con stock crítico
            productos_criticos = self.alertas_service.obtener_productos_stock_critico()

            if productos_criticos:
                # Crear alerta en el sistema
                self.alertas_service.verificar_stock_bajo()

                # Mostrar aviso visual al usuario si hay productos críticos relacionados con esta entrada
                for prod in productos_criticos:
                    if prod['id'] == self.producto_seleccionado['id']:
                        if prod['stock_actual'] <= 0:
                            QMessageBox.warning(
                                self, "⚠️ Alerta: Stock Crítico",
                                f"El producto '{prod['nombre']}' ha alcanzado STOCK CERO.\n"
                                f"Stock actual: {prod['stock_actual']}\n"
                                f"Stock mínimo requerido: {prod['stock_minimo']}"
                            )
                        elif prod['stock_actual'] <= prod['stock_minimo']:
                            proveedor_info = f"\nProveedor: {prod['proveedor_nombre']}" if prod['proveedor_nombre'] else ""
                            QMessageBox.warning(
                                self, "⚠️ Alerta: Stock Bajo",
                                f"El producto '{prod['nombre']}' está por debajo del stock mínimo.\n"
                                f"Stock actual: {prod['stock_actual']}\n"
                                f"Stock mínimo requerido: {prod['stock_minimo']}"
                                f"{proveedor_info}"
                            )
        except Exception as e:
            print(f"Error verificando alertas de stock: {e}")