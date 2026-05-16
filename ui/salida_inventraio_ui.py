# -*- coding: utf-8 -*-
"""
Interfaz para registro de salidas de inventario (PySide6)
Con stock visible y precio automático
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QFrame, QMessageBox, QCheckBox, QGridLayout, QSizePolicy
)
from PySide6.QtCore import Qt
from datetime import datetime
from models import MovimientoInventario
from ui_config import COLORS, FONTS, make_font


class SalidaInventarioUI(QDialog):
    """Interfaz para nueva salida de inventario"""

    def __init__(self, parent, inventario_repo, productos_repo, auth, alertas_service=None):
        super().__init__(parent)
        self.parent_widget = parent
        self.inventario_repo = inventario_repo
        self.productos_repo = productos_repo
        self.auth = auth
        self.alertas_service = alertas_service

        self.producto_seleccionado = None

        self.crear_ventana()

    def crear_ventana(self):
        """Crea la ventana de salida"""
        self.setWindowTitle("Salida de Inventario")
        self.setFixedSize(600, 580)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setStyleSheet("background: white;")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(80)
        header.setStyleSheet(f"background: {COLORS['danger']};")
        header_layout = QVBoxLayout(header)
        header_layout.setAlignment(Qt.AlignCenter)
        lbl_title = QLabel("📤 Nueva Salida")
        lbl_title.setFont(make_font(FONTS['xlarge']))
        lbl_title.setStyleSheet("color: white; background: transparent;")
        lbl_title.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(lbl_title)
        main_layout.addWidget(header)

        # Contenido
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
        self.tipo_combo.addItems(['SALIDA_VENTA', 'SALIDA_AJUSTE', 'SALIDA_MERMA'])
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
            f"QPushButton {{ background: {COLORS['info']}; color: white; border: none; "
            f"border-radius: 4px; padding: 6px 12px; }}"
            f"QPushButton:hover {{ background: #0891b2; }}"
        )
        btn_buscar_prod.clicked.connect(self.buscar_producto)
        producto_row.addWidget(btn_buscar_prod)
        content_layout.addLayout(producto_row)
        content_layout.addSpacing(10)

        # Stock disponible (hidden initially)
        self.stock_frame = QFrame()
        self.stock_frame.setStyleSheet(
            "QFrame { background: #fef3c7; border: 1px solid #fcd34d; border-radius: 4px; }"
        )
        stock_frame_layout = QVBoxLayout(self.stock_frame)
        stock_frame_layout.setContentsMargins(10, 8, 10, 8)
        self.stock_label = QLabel("📦 Stock disponible: --")
        self.stock_label.setFont(make_font(FONTS['body_bold']))
        self.stock_label.setStyleSheet("color: #92400e; background: transparent; border: none;")
        self.stock_label.setAlignment(Qt.AlignCenter)
        stock_frame_layout.addWidget(self.stock_label)
        self.stock_frame.setVisible(False)
        content_layout.addWidget(self.stock_frame)
        content_layout.addSpacing(10)

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
        self.cantidad_entry.textChanged.connect(self.validar_cantidad)
        content_layout.addWidget(self.cantidad_entry)
        content_layout.addSpacing(10)

        # Checkbox: Entrada en cajas
        self.entrada_cajas_check = QCheckBox("Entrada en cajas")
        self.entrada_cajas_check.setFont(make_font(FONTS['body']))
        self.entrada_cajas_check.setStyleSheet("background: transparent;")
        self.entrada_cajas_check.stateChanged.connect(self.toggle_entrada_cajas)
        content_layout.addWidget(self.entrada_cajas_check)
        content_layout.addSpacing(10)

        # Frame para entrada en cajas (hidden initially)
        self.cajas_frame = QFrame()
        self.cajas_frame.setStyleSheet(
            "QFrame { background: #e0f2fe; border: 1px solid #7dd3fc; border-radius: 4px; }"
        )
        cajas_outer = QVBoxLayout(self.cajas_frame)
        cajas_outer.setContentsMargins(15, 10, 15, 10)

        cajas_grid = QGridLayout()
        cajas_grid.setSpacing(5)

        lbl_num_cajas = QLabel("Número de cajas *")
        lbl_num_cajas.setFont(make_font(FONTS['body']))
        lbl_num_cajas.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent; border: none;")
        cajas_grid.addWidget(lbl_num_cajas, 0, 0)

        lbl_unid_caja = QLabel("Unidades por caja *")
        lbl_unid_caja.setFont(make_font(FONTS['body']))
        lbl_unid_caja.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent; border: none;")
        cajas_grid.addWidget(lbl_unid_caja, 0, 1)

        self.num_cajas_entry = QLineEdit("1")
        self.num_cajas_entry.setFont(make_font(FONTS['body']))
        self.num_cajas_entry.setStyleSheet(
            "QLineEdit { border: 1px solid #d1d5db; border-radius: 4px; padding: 6px; background: white; }"
        )
        self.num_cajas_entry.textChanged.connect(self.calcular_total_unidades)
        cajas_grid.addWidget(self.num_cajas_entry, 1, 0)

        self.unidades_caja_entry = QLineEdit("1")
        self.unidades_caja_entry.setFont(make_font(FONTS['body']))
        self.unidades_caja_entry.setStyleSheet(
            "QLineEdit { border: 1px solid #d1d5db; border-radius: 4px; padding: 6px; background: white; }"
        )
        self.unidades_caja_entry.textChanged.connect(self.calcular_total_unidades)
        cajas_grid.addWidget(self.unidades_caja_entry, 1, 1)

        cajas_outer.addLayout(cajas_grid)

        self.info_cajas_label = QLabel("📋 Total de unidades: 1")
        self.info_cajas_label.setFont(make_font(FONTS['body_bold']))
        self.info_cajas_label.setStyleSheet(f"color: {COLORS['info']}; background: transparent; border: none;")
        self.info_cajas_label.setAlignment(Qt.AlignCenter)
        cajas_outer.addWidget(self.info_cajas_label)

        self.cajas_frame.setVisible(False)
        content_layout.addWidget(self.cajas_frame)
        content_layout.addSpacing(10)

        # Precio unitario (automático / readonly)
        lbl_precio = QLabel("Precio unitario *")
        lbl_precio.setFont(make_font(FONTS['body']))
        lbl_precio.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        content_layout.addWidget(lbl_precio)
        content_layout.addSpacing(5)

        self.precio_entry = QLineEdit("0")
        self.precio_entry.setFont(make_font(FONTS['body']))
        self.precio_entry.setReadOnly(True)
        self.precio_entry.setStyleSheet(
            "QLineEdit { border: 1px solid #d1d5db; border-radius: 4px; padding: 6px; background: #f9fafb; }"
        )
        content_layout.addWidget(self.precio_entry)
        content_layout.addSpacing(15)

        # Número de factura
        lbl_factura = QLabel("Número de factura/venta (opcional)")
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
        main_layout.addWidget(content, 1)

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
            f"QPushButton {{ background: {COLORS['danger']}; color: white; border: none; "
            f"border-radius: 6px; padding: 12px 38px; }}"
            f"QPushButton:hover {{ background: {COLORS['danger_dark']}; }}"
        )
        btn_guardar.clicked.connect(self.guardar_salida)

        btn_cancelar = QPushButton("❌ Cancelar")
        btn_cancelar.setFont(make_font(FONTS['body']))
        btn_cancelar.setCursor(Qt.PointingHandCursor)
        btn_cancelar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['secondary']}; color: white; border: none; "
            f"border-radius: 6px; padding: 12px 38px; }}"
            f"QPushButton:hover {{ background: #475569; }}"
        )
        btn_cancelar.clicked.connect(self.reject)

        footer_layout.addWidget(btn_guardar)
        footer_layout.addWidget(btn_cancelar)
        main_layout.addWidget(footer)

    def toggle_entrada_cajas(self):
        """Muestra/oculta el frame de entrada en cajas"""
        if self.entrada_cajas_check.isChecked():
            self.cajas_frame.setVisible(True)
            self.calcular_total_unidades()
        else:
            self.cajas_frame.setVisible(False)
            self.cantidad_entry.setText("1")

    def calcular_total_unidades(self, *args):
        """Calcula el total de unidades basado en cajas"""
        try:
            num_cajas = int(self.num_cajas_entry.text() or 0)
            unidades_caja = int(self.unidades_caja_entry.text() or 0)
            total = num_cajas * unidades_caja

            self.cantidad_entry.setText(str(total))
            self.info_cajas_label.setText(f"📋 Total de unidades: {total}")
        except Exception:
            self.cantidad_entry.setText("0")
            self.info_cajas_label.setText("📋 Total de unidades: 0")

    def buscar_producto(self):
        """Abre ventana de búsqueda de productos"""
        from ui.buscar_producto_dialog import BuscarProductoDialog
        dialog = BuscarProductoDialog(self, self.productos_repo)
        dialog.exec()

        if dialog.producto_seleccionado:
            self.producto_seleccionado = dialog.producto_seleccionado
            texto = f"{self.producto_seleccionado['nombre']} (ID: {self.producto_seleccionado['id']})"
            self.producto_entry.setText(texto)

            # Mostrar stock disponible
            stock = self.producto_seleccionado['stock']
            self.stock_frame.setVisible(True)
            self.stock_label.setText(f"📦 Stock disponible: {stock} unidades")
            self.stock_label.setStyleSheet("color: #92400e; background: transparent; border: none;")

            # Cargar precio automáticamente
            precio_venta = self.producto_seleccionado['precio_venta']
            self.precio_entry.setText(str(precio_venta))

    def validar_cantidad(self, *args):
        """Valida que no se venda más de lo disponible"""
        if not self.producto_seleccionado:
            return

        try:
            cantidad = int(self.cantidad_entry.text() or 0)
            stock = self.producto_seleccionado['stock']

            if cantidad > stock:
                self.stock_label.setText(f"⚠️ Stock insuficiente! Disponible: {stock} unidades")
                self.stock_label.setStyleSheet("color: #dc2626; background: transparent; border: none;")
            else:
                self.stock_label.setText(f"📦 Stock disponible: {stock} unidades")
                self.stock_label.setStyleSheet("color: #92400e; background: transparent; border: none;")
        except Exception:
            pass

    def guardar_salida(self):
        """Guarda la salida de inventario"""
        try:
            # Validaciones
            if not self.producto_seleccionado:
                QMessageBox.warning(self, "Advertencia", "Debe seleccionar un producto")
                return

            cantidad = int(self.cantidad_entry.text())
            if cantidad <= 0:
                QMessageBox.warning(self, "Advertencia", "La cantidad debe ser mayor a 0")
                return

            # Validar stock disponible
            if cantidad > self.producto_seleccionado['stock']:
                QMessageBox.critical(
                    self, "Stock Insuficiente",
                    f"No puede vender {cantidad} unidades.\n"
                    f"Stock disponible: {self.producto_seleccionado['stock']} unidades"
                )
                return

            precio = float(self.precio_entry.text())
            if precio < 0:
                QMessageBox.warning(self, "Advertencia", "El precio no puede ser negativo")
                return

            # Validar número de factura (no repetido)
            num_factura = self.factura_entry.text().strip() or None
            if num_factura:
                existe = self.inventario_repo.verificar_factura_venta_existente(num_factura)
                if existe:
                    respuesta = QMessageBox.question(
                        self, "Factura Duplicada",
                        f"Ya existe una venta con factura '{num_factura}'.\n\n"
                        "¿Desea continuar de todas formas?",
                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                    )
                    if respuesta != QMessageBox.Yes:
                        return

            # Crear movimiento
            movimiento = MovimientoInventario(
                tipo_movimiento=self.tipo_combo.currentText(),
                producto_id=self.producto_seleccionado['id'],
                cantidad=cantidad,
                precio_unitario=precio,
                numero_factura=num_factura,
                usuario_id=self.auth.usuario_actual['id'],
                fecha=datetime.now()
            )

            # Guardar
            exito, mensaje = self.inventario_repo.registrar_movimiento(movimiento)

            if exito:
                QMessageBox.information(self, "Éxito", mensaje)

                # Verificar stock mínimo después de la salida
                self.verificar_y_mostrar_alertas_stock()

                self.accept()
            else:
                QMessageBox.critical(self, "Error", mensaje)

        except ValueError:
            QMessageBox.critical(self, "Error", "Los valores numéricos no son válidos")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error guardando salida:\n{str(e)}")

    def verificar_y_mostrar_alertas_stock(self):
        """Verifica y muestra alertas de stock crítico después de la salida"""
        if not self.alertas_service:
            return

        try:
            # Obtener productos con stock crítico
            productos_criticos = self.alertas_service.obtener_productos_stock_critico()

            if productos_criticos:
                # Crear alerta en el sistema
                self.alertas_service.verificar_stock_bajo()

                # Mostrar aviso visual si el producto vendido está en stock crítico
                for prod in productos_criticos:
                    if prod['id'] == self.producto_seleccionado['id']:
                        if prod['stock_actual'] <= 0:
                            QMessageBox.warning(
                                self, "⚠️ Alerta: Stock Crítico",
                                f"El producto '{prod['nombre']}' ha alcanzado STOCK CERO.\n"
                                f"Stock actual: {prod['stock_actual']}\n"
                                f"Stock mínimo requerido: {prod['stock_minimo']}\n\n"
                                "¡REORDEN INMEDIATO RECOMENDADO!"
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