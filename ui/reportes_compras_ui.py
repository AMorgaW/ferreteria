# -*- coding: utf-8 -*-
"""
Interfaz de usuario para reportes de compras a proveedores (PySide6)
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QFrame,
    QMessageBox, QScrollArea, QAbstractItemView, QGroupBox, QFileDialog
)
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QFont, QPainter, QColor
from datetime import datetime, timedelta
from typing import Optional
from ui_config import COLORS, FONTS, make_font
import os


class ReportesComprasUI(QWidget):
    """Interfaz para visualizar reportes de compras a proveedores"""

    def __init__(self, parent, reportes_service, proveedores_repo, productos_repo, auth_manager):
        super().__init__(parent)
        self.parent_widget = parent
        self.service = reportes_service
        self.proveedores_repo = proveedores_repo
        self.productos_repo = productos_repo
        self.auth = auth_manager

        self.compras_actuales = []

        self.crear_interfaz()
        self.cargar_datos_iniciales()

    def crear_interfaz(self):
        """Crea la interfaz principal"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        outer_frame = QFrame()
        outer_frame.setStyleSheet(f"background: {COLORS['bg_secondary']};")
        outer_layout = QVBoxLayout(outer_frame)
        outer_layout.setContentsMargins(20, 10, 20, 10)
        outer_layout.setSpacing(10)

        # Header
        header = QHBoxLayout()
        title = QLabel("[REPORTE] Reporte de Compras a Proveedores")
        title.setFont(make_font(FONTS['large']))
        title.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent;")
        header.addWidget(title)
        header.addStretch()

        btn_exportar = QPushButton("📤 Exportar CSV")
        btn_exportar.setFont(make_font(FONTS['body']))
        btn_exportar.setCursor(Qt.PointingHandCursor)
        btn_exportar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['success']}; color: white; border: none; "
            f"border-radius: 6px; padding: 8px 15px; }}"
            f"QPushButton:hover {{ background: {COLORS['success_dark']}; }}"
        )
        btn_exportar.clicked.connect(self.exportar_csv)
        header.addWidget(btn_exportar)

        btn_actualizar = QPushButton("🔄 Actualizar")
        btn_actualizar.setFont(make_font(FONTS['body']))
        btn_actualizar.setCursor(Qt.PointingHandCursor)
        btn_actualizar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['info']}; color: white; border: none; "
            f"border-radius: 6px; padding: 8px 15px; }}"
            f"QPushButton:hover {{ background: #0891b2; }}"
        )
        btn_actualizar.clicked.connect(self.aplicar_filtros)
        header.addWidget(btn_actualizar)

        outer_layout.addLayout(header)

        # Scroll area for content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")

        self.scrollable_widget = QWidget()
        self.scrollable_layout = QVBoxLayout(self.scrollable_widget)
        self.scrollable_layout.setContentsMargins(0, 0, 0, 0)
        self.scrollable_layout.setSpacing(15)

        scroll.setWidget(self.scrollable_widget)

        # Crear secciones
        self.crear_seccion_filtros()
        self.crear_seccion_estadisticas()
        self.crear_seccion_graficos()
        self.crear_seccion_tabla()

        outer_layout.addWidget(scroll, 1)
        main_layout.addWidget(outer_frame)

    def crear_seccion_filtros(self):
        """Crea la sección de filtros"""
        filtros_group = QGroupBox("🔍 Filtros")
        filtros_group.setFont(make_font(FONTS['body_bold']))
        filtros_group.setStyleSheet(
            "QGroupBox { background: white; border: 1px solid #d1d5db; border-radius: 8px; "
            f"color: {COLORS['text_primary']}; padding: 15px; margin-top: 10px; }}"
            "QGroupBox::title { subcontrol-origin: margin; padding: 0 10px; }"
        )
        filtros_layout = QVBoxLayout(filtros_group)

        # Fila 1: Proveedor y Producto
        fila1 = QHBoxLayout()

        lbl_prov = QLabel("Proveedor:")
        lbl_prov.setFont(make_font(FONTS['body']))
        lbl_prov.setStyleSheet("background: transparent;")
        fila1.addWidget(lbl_prov)

        try:
            proveedores = self.service.obtener_proveedores_activos()
            self.proveedores_dict = {p['nombre']: p['id'] for p in proveedores}
            valores_prov = ["-- Todos --"] + list(self.proveedores_dict.keys())
        except Exception as e:
            print(f"Error cargando proveedores: {e}")
            self.proveedores_dict = {}
            valores_prov = ["-- Todos --"]

        self.proveedor_combo = QComboBox()
        self.proveedor_combo.setFont(make_font(FONTS['body']))
        self.proveedor_combo.addItems(valores_prov)
        self.proveedor_combo.setMinimumWidth(200)
        fila1.addWidget(self.proveedor_combo)

        fila1.addSpacing(20)

        lbl_prod = QLabel("Producto:")
        lbl_prod.setFont(make_font(FONTS['body']))
        lbl_prod.setStyleSheet("background: transparent;")
        fila1.addWidget(lbl_prod)

        productos = self.productos_repo.listar()
        self.productos_dict = {p.nombre: p.id for p in productos if p.activo}
        valores_prod = ["-- Todos --"] + list(self.productos_dict.keys())

        self.producto_combo = QComboBox()
        self.producto_combo.setFont(make_font(FONTS['body']))
        self.producto_combo.addItems(valores_prod)
        self.producto_combo.setMinimumWidth(250)
        fila1.addWidget(self.producto_combo)

        fila1.addStretch()
        filtros_layout.addLayout(fila1)

        # Fila 2: Fechas
        fila2 = QHBoxLayout()

        lbl_desde = QLabel("Desde:")
        lbl_desde.setFont(make_font(FONTS['body']))
        lbl_desde.setStyleSheet("background: transparent;")
        fila2.addWidget(lbl_desde)

        self.fecha_inicio = QLineEdit()
        self.fecha_inicio.setFont(make_font(FONTS['body']))
        self.fecha_inicio.setFixedWidth(120)
        self.fecha_inicio.setText((datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))
        fila2.addWidget(self.fecha_inicio)

        fila2.addSpacing(20)

        lbl_hasta = QLabel("Hasta:")
        lbl_hasta.setFont(make_font(FONTS['body']))
        lbl_hasta.setStyleSheet("background: transparent;")
        fila2.addWidget(lbl_hasta)

        self.fecha_fin = QLineEdit()
        self.fecha_fin.setFont(make_font(FONTS['body']))
        self.fecha_fin.setFixedWidth(120)
        self.fecha_fin.setText(datetime.now().strftime('%Y-%m-%d'))
        fila2.addWidget(self.fecha_fin)

        fila2.addSpacing(20)

        btn_aplicar = QPushButton("🔍 Aplicar Filtros")
        btn_aplicar.setFont(make_font(FONTS['body']))
        btn_aplicar.setCursor(Qt.PointingHandCursor)
        btn_aplicar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['primary']}; color: white; border: none; "
            f"border-radius: 6px; padding: 8px 15px; }}"
            f"QPushButton:hover {{ background: {COLORS['primary_dark']}; }}"
        )
        btn_aplicar.clicked.connect(self.aplicar_filtros)
        fila2.addWidget(btn_aplicar)

        btn_limpiar = QPushButton("🗑️ Limpiar")
        btn_limpiar.setFont(make_font(FONTS['body']))
        btn_limpiar.setCursor(Qt.PointingHandCursor)
        btn_limpiar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['secondary']}; color: white; border: none; "
            f"border-radius: 6px; padding: 8px 15px; }}"
            f"QPushButton:hover {{ background: #4b5563; }}"
        )
        btn_limpiar.clicked.connect(self.limpiar_filtros)
        fila2.addWidget(btn_limpiar)

        fila2.addStretch()
        filtros_layout.addLayout(fila2)

        self.scrollable_layout.addWidget(filtros_group)

    def crear_seccion_estadisticas(self):
        """Crea las tarjetas de estadísticas"""
        self.stats_frame = QFrame()
        self.stats_frame.setStyleSheet("background: transparent;")
        self.stats_layout = QHBoxLayout(self.stats_frame)
        self.stats_layout.setContentsMargins(0, 0, 0, 0)
        self.stats_layout.setSpacing(10)
        self.scrollable_layout.addWidget(self.stats_frame)

    def crear_card_estadistica(self, titulo, valor, subtitulo, color, icono):
        """Crea una tarjeta de estadística"""
        card = QFrame()
        card.setStyleSheet("background: white; border: 1px solid #e5e7eb; border-radius: 8px;")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(15, 10, 15, 10)
        card_layout.setAlignment(Qt.AlignCenter)

        # Barra de color
        barra = QFrame()
        barra.setFixedHeight(5)
        barra.setStyleSheet(f"background: {color}; border: none; border-radius: 2px;")
        card_layout.addWidget(barra)

        lbl_icon = QLabel(icono)
        lbl_icon.setFont(QFont('Segoe UI', 24))
        lbl_icon.setAlignment(Qt.AlignCenter)
        lbl_icon.setStyleSheet("background: transparent; border: none;")
        card_layout.addWidget(lbl_icon)

        lbl_titulo = QLabel(titulo)
        lbl_titulo.setFont(make_font(FONTS['small']))
        lbl_titulo.setAlignment(Qt.AlignCenter)
        lbl_titulo.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent; border: none;")
        card_layout.addWidget(lbl_titulo)

        lbl_valor = QLabel(valor)
        lbl_valor.setFont(make_font(FONTS['heading']))
        lbl_valor.setAlignment(Qt.AlignCenter)
        lbl_valor.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent; border: none;")
        card_layout.addWidget(lbl_valor)

        lbl_sub = QLabel(subtitulo)
        lbl_sub.setFont(make_font(FONTS['small']))
        lbl_sub.setAlignment(Qt.AlignCenter)
        lbl_sub.setStyleSheet(f"color: {COLORS['text_light']}; background: transparent; border: none;")
        card_layout.addWidget(lbl_sub)

        self.stats_layout.addWidget(card)

    def crear_seccion_graficos(self):
        """Crea la sección de gráficos"""
        graficos_frame = QFrame()
        graficos_frame.setStyleSheet("background: transparent;")
        graficos_layout = QHBoxLayout(graficos_frame)
        graficos_layout.setContentsMargins(0, 0, 0, 0)
        graficos_layout.setSpacing(10)

        # Gráfico: Top proveedores
        self.grafico_proveedores_group = QGroupBox("📈 Top 5 Proveedores por Monto Comprado")
        self.grafico_proveedores_group.setFont(make_font(FONTS['body_bold']))
        self.grafico_proveedores_group.setStyleSheet(
            "QGroupBox { background: white; border: 1px solid #d1d5db; border-radius: 8px; "
            f"color: {COLORS['text_primary']}; padding: 15px; margin-top: 10px; }}"
            "QGroupBox::title { subcontrol-origin: margin; padding: 0 10px; }"
        )
        self.grafico_proveedores_layout = QVBoxLayout(self.grafico_proveedores_group)
        graficos_layout.addWidget(self.grafico_proveedores_group)

        # Gráfico: Productos más comprados
        self.grafico_productos_group = QGroupBox("📦 Top 5 Productos Más Comprados")
        self.grafico_productos_group.setFont(make_font(FONTS['body_bold']))
        self.grafico_productos_group.setStyleSheet(
            "QGroupBox { background: white; border: 1px solid #d1d5db; border-radius: 8px; "
            f"color: {COLORS['text_primary']}; padding: 15px; margin-top: 10px; }}"
            "QGroupBox::title { subcontrol-origin: margin; padding: 0 10px; }"
        )
        self.grafico_productos_layout = QVBoxLayout(self.grafico_productos_group)
        graficos_layout.addWidget(self.grafico_productos_group)

        self.scrollable_layout.addWidget(graficos_frame)

    def crear_grafico_barras(self, parent_layout, datos, key_nombre, key_valor, color):
        """Crea un gráfico de barras simple usando QLabels y QFrames"""
        # Limpiar layout
        while parent_layout.count():
            child = parent_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if not datos:
            lbl = QLabel("No hay datos para mostrar")
            lbl.setFont(make_font(FONTS['body']))
            lbl.setStyleSheet(f"color: {COLORS['text_light']}; background: transparent;")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setContentsMargins(0, 20, 0, 20)
            parent_layout.addWidget(lbl)
            return

        max_valor = max([d[key_valor] for d in datos]) if datos else 1

        for item in datos:
            nombre = item[key_nombre]
            valor = item[key_valor]
            porcentaje = (valor / max_valor * 100) if max_valor > 0 else 0

            row_frame = QFrame()
            row_frame.setStyleSheet("background: transparent;")
            row_layout = QHBoxLayout(row_frame)
            row_layout.setContentsMargins(0, 2, 0, 2)
            row_layout.setSpacing(10)

            lbl_nombre = QLabel(nombre[:30])
            lbl_nombre.setFont(make_font(FONTS['small']))
            lbl_nombre.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
            lbl_nombre.setFixedWidth(180)
            row_layout.addWidget(lbl_nombre)

            # Barra visual
            barra_container = QFrame()
            barra_container.setFixedHeight(20)
            barra_container.setFixedWidth(200)
            barra_container.setStyleSheet(f"background: {COLORS['bg_secondary']}; border-radius: 3px;")

            barra = QFrame(barra_container)
            barra_width = max(int(porcentaje * 2), 1)
            barra.setGeometry(0, 0, barra_width, 20)
            barra.setStyleSheet(f"background: {color}; border-radius: 3px;")

            row_layout.addWidget(barra_container)

            lbl_valor = QLabel(f"${valor:,.0f}")
            lbl_valor.setFont(make_font(FONTS['small']))
            lbl_valor.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent;")
            row_layout.addWidget(lbl_valor)

            row_layout.addStretch()
            parent_layout.addWidget(row_frame)

    def crear_seccion_tabla(self):
        """Crea la tabla detallada de compras"""
        tabla_group = QGroupBox("📋 Detalle de Compras")
        tabla_group.setFont(make_font(FONTS['body_bold']))
        tabla_group.setStyleSheet(
            "QGroupBox { background: white; border: 1px solid #d1d5db; border-radius: 8px; "
            f"color: {COLORS['text_primary']}; padding: 10px; margin-top: 10px; }}"
            "QGroupBox::title { subcontrol-origin: margin; padding: 0 10px; }"
        )
        tabla_layout = QVBoxLayout(tabla_group)

        columnas = ['Fecha', 'Proveedor', '# Factura', 'Producto', 'Cantidad',
                     'Precio Unit.', 'Total', 'Usuario']
        self.table = QTableWidget()
        self.table.setColumnCount(len(columnas))
        self.table.setHorizontalHeaderLabels(columnas)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(300)

        hdr = self.table.horizontalHeader()
        anchos = [100, 150, 100, 200, 80, 100, 100, 120]
        for i, w in enumerate(anchos):
            hdr.resizeSection(i, w)
        hdr.setStretchLastSection(True)

        tabla_layout.addWidget(self.table)

        self.label_totales = QLabel("")
        self.label_totales.setFont(make_font(FONTS['body_bold']))
        self.label_totales.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent;")
        self.label_totales.setAlignment(Qt.AlignCenter)
        tabla_layout.addWidget(self.label_totales)

        self.scrollable_layout.addWidget(tabla_group)

    def cargar_datos_iniciales(self):
        """Carga los datos iniciales"""
        self.aplicar_filtros()

    def aplicar_filtros(self):
        """Aplica los filtros y actualiza la visualización"""
        try:
            proveedor_sel = self.proveedor_combo.currentText()
            proveedor_id = self.proveedores_dict.get(proveedor_sel) if proveedor_sel != "-- Todos --" else None

            producto_sel = self.producto_combo.currentText()
            producto_id = self.productos_dict.get(producto_sel) if producto_sel != "-- Todos --" else None

            fecha_inicio = self.fecha_inicio.text()
            fecha_fin = self.fecha_fin.text()

            self.compras_actuales = self.service.obtener_compras_por_proveedor(
                proveedor_id=proveedor_id,
                producto_id=producto_id,
                fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin
            )

            self.actualizar_estadisticas(fecha_inicio, fecha_fin, proveedor_id)
            self.actualizar_graficos(fecha_inicio, fecha_fin)
            self.actualizar_tabla()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al aplicar filtros: {str(e)}")

    def actualizar_estadisticas(self, fecha_inicio, fecha_fin, proveedor_id):
        """Actualiza las tarjetas de estadísticas"""
        # Limpiar cards existentes
        while self.stats_layout.count():
            child = self.stats_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        try:
            stats = self.service.obtener_estadisticas_generales(fecha_inicio, fecha_fin)

            self.crear_card_estadistica(
                "Total Compras",
                f"{stats['total_compras']}",
                "operaciones realizadas",
                COLORS['info'],
                "🛒"
            )

            self.crear_card_estadistica(
                "Monto Total",
                f"${stats['monto_total']:,.0f}",
                "invertido en compras",
                COLORS['success'],
                "💰"
            )

            self.crear_card_estadistica(
                "Proveedores",
                f"{stats['proveedores_activos']}",
                "proveedores diferentes",
                COLORS['primary'],
                "🏪"
            )

            self.crear_card_estadistica(
                "Productos",
                f"{stats['productos_comprados']}",
                "productos distintos",
                COLORS['warning'],
                "📦"
            )

            self.crear_card_estadistica(
                "Unidades",
                f"{stats['unidades_totales']:,.0f}",
                "unidades compradas",
                COLORS['secondary'],
                "[REPORTE]"
            )

        except Exception as e:
            print(f"Error actualizando estadísticas: {e}")

    def actualizar_graficos(self, fecha_inicio, fecha_fin):
        """Actualiza los gráficos"""
        try:
            top_proveedores = self.service.obtener_proveedores_principales(
                limite=5, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin
            )
            self.crear_grafico_barras(
                self.grafico_proveedores_layout,
                top_proveedores,
                'proveedor_nombre',
                'monto_total',
                COLORS['primary']
            )

            top_productos = self.service.obtener_productos_mas_comprados(
                limite=5, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin
            )
            self.crear_grafico_barras(
                self.grafico_productos_layout,
                top_productos,
                'nombre',
                'monto_total',
                COLORS['success']
            )

        except Exception as e:
            print(f"Error actualizando gráficos: {e}")

    def actualizar_tabla(self):
        """Actualiza la tabla con las compras"""
        self.table.setRowCount(0)

        total_general = 0
        total_unidades = 0

        for row, compra in enumerate(self.compras_actuales):
            self.table.insertRow(row)
            fecha = compra['fecha'][:10] if compra['fecha'] else ''
            proveedor = compra['proveedor_nombre']
            factura = compra.get('num_factura', '')
            producto = compra['producto_nombre']
            cantidad = compra['cantidad']
            precio_unit = compra['precio_unitario']
            total = compra['costo_total']
            usuario = compra.get('usuario_nombre', '')

            self.table.setItem(row, 0, QTableWidgetItem(fecha))
            self.table.setItem(row, 1, QTableWidgetItem(proveedor))
            self.table.setItem(row, 2, QTableWidgetItem(str(factura)))
            self.table.setItem(row, 3, QTableWidgetItem(producto))
            self.table.setItem(row, 4, QTableWidgetItem(str(cantidad)))
            self.table.setItem(row, 5, QTableWidgetItem(f"${precio_unit:,.2f}"))
            self.table.setItem(row, 6, QTableWidgetItem(f"${total:,.2f}"))
            self.table.setItem(row, 7, QTableWidgetItem(str(usuario)))

            total_general += total
            total_unidades += cantidad

        texto_totales = f"Total Registros: {len(self.compras_actuales)} | "
        texto_totales += f"Total Unidades: {total_unidades:,.0f} | "
        texto_totales += f"Total Invertido: ${total_general:,.2f}"
        self.label_totales.setText(texto_totales)

    def limpiar_filtros(self):
        """Limpia todos los filtros"""
        self.proveedor_combo.setCurrentIndex(0)
        self.producto_combo.setCurrentIndex(0)
        self.fecha_inicio.setText((datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))
        self.fecha_fin.setText(datetime.now().strftime('%Y-%m-%d'))
        self.aplicar_filtros()

    def exportar_csv(self):
        """Exporta el reporte actual a CSV"""
        if not self.compras_actuales:
            QMessageBox.warning(self, "Advertencia", "No hay datos para exportar")
            return

        try:
            archivo, _ = QFileDialog.getSaveFileName(
                self,
                "Exportar Reporte",
                f"reporte_compras_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                "CSV (*.csv);;Todos (*.*)"
            )

            if archivo:
                self.service.exportar_reporte_csv(self.compras_actuales, archivo)
                QMessageBox.information(self, "Éxito", f"Reporte exportado correctamente:\n{archivo}")

                resp = QMessageBox.question(
                    self, "Abrir archivo", "¿Desea abrir el archivo exportado?",
                    QMessageBox.Yes | QMessageBox.No
                )
                if resp == QMessageBox.Yes:
                    os.startfile(archivo)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al exportar: {str(e)}")