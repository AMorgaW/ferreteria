# -*- coding: utf-8 -*-
"""
Diálogo para buscar y seleccionar productos (PySide6)
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame, QAbstractItemView
)
from PySide6.QtCore import Qt, QTimer
from ui_config import COLORS, FONTS, make_font


class BuscarProductoDialog(QDialog):
    """Diálogo de búsqueda de productos"""

    def __init__(self, parent, productos_repo):
        super().__init__(parent)
        self.productos_repo = productos_repo
        self.producto_seleccionado = None
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self.cargar_productos)

        self.crear_ventana()
        self.cargar_productos()

    def crear_ventana(self):
        """Crea la ventana de búsqueda"""
        self.setWindowTitle("Buscar Producto")
        self.setFixedSize(800, 500)
        self.setModal(True)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(60)
        header.setStyleSheet(f"background: {COLORS['primary']};")
        header_layout = QHBoxLayout(header)

        title = QLabel("🔍 Buscar Producto")
        title.setFont(make_font(FONTS['large']))
        title.setStyleSheet("color: white; background: transparent;")
        title.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(title)

        main_layout.addWidget(header)

        # Búsqueda
        search_frame = QFrame()
        search_frame.setStyleSheet("background: white;")
        search_layout = QHBoxLayout(search_frame)
        search_layout.setContentsMargins(20, 15, 20, 15)

        lbl = QLabel("Buscar:")
        lbl.setFont(make_font(FONTS['body']))
        lbl.setStyleSheet("background: transparent;")
        search_layout.addWidget(lbl)

        self.search_entry = QLineEdit()
        self.search_entry.setFont(make_font(FONTS['body']))
        self.search_entry.setPlaceholderText("Escriba para buscar...")
        self.search_entry.textChanged.connect(lambda: self._search_timer.start())
        self.search_entry.setFocus()
        search_layout.addWidget(self.search_entry)

        main_layout.addWidget(search_frame)

        # Tabla
        table_frame = QFrame()
        table_frame.setStyleSheet("background: white;")
        table_layout = QVBoxLayout(table_frame)
        table_layout.setContentsMargins(20, 0, 20, 0)

        columnas = ['ID', 'Nombre', 'Categoría', 'Marca', 'Stock', 'Precio Venta']
        self.table = QTableWidget()
        self.table.setColumnCount(len(columnas))
        self.table.setHorizontalHeaderLabels(columnas)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(self.seleccionar_producto)

        hdr = self.table.horizontalHeader()
        anchos = [50, 250, 120, 120, 80, 100]
        for i, w in enumerate(anchos):
            hdr.resizeSection(i, w)
        hdr.setStretchLastSection(True)

        table_layout.addWidget(self.table)
        main_layout.addWidget(table_frame, 1)

        # Botones
        btn_frame = QFrame()
        btn_frame.setStyleSheet("background: white;")
        btn_layout = QHBoxLayout(btn_frame)
        btn_layout.setContentsMargins(20, 15, 20, 15)

        btn_seleccionar = QPushButton("✓  Seleccionar")
        btn_seleccionar.setFont(make_font(FONTS['body_bold']))
        btn_seleccionar.setCursor(Qt.PointingHandCursor)
        btn_seleccionar.setMinimumHeight(40)
        btn_seleccionar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['accent']}; color: {COLORS['on_accent']}; border: none; "
            f"border-radius: 9px; padding: 10px 25px; font-weight: 500; }}"
            f"QPushButton:hover {{ background: {COLORS['accent_hover']}; }}"
        )
        btn_seleccionar.clicked.connect(self.seleccionar_producto)
        btn_layout.addWidget(btn_seleccionar)

        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setFont(make_font(FONTS['body']))
        btn_cancelar.setCursor(Qt.PointingHandCursor)
        btn_cancelar.setMinimumHeight(40)
        btn_cancelar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['bg_primary']}; color: {COLORS['text_body']}; "
            f"border: 1px solid {COLORS['border_input']}; border-radius: 9px; padding: 10px 25px; font-weight: 500; }}"
            f"QPushButton:hover {{ background: {COLORS['bg_hover']}; border-color: {COLORS['primary_border']}; }}"
        )
        btn_cancelar.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancelar)

        btn_layout.addStretch()
        main_layout.addWidget(btn_frame)

    def cargar_productos(self):
        """Carga los productos en la tabla"""
        self.table.setRowCount(0)

        try:
            termino = self.search_entry.text().strip()
            if self.productos_repo.cache_disponible():
                productos = self.productos_repo.buscar_productos_cache(termino, limite=120)
            else:
                productos = self.productos_repo.buscar_productos(termino, limite=120)

            for row, p in enumerate(productos):
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(str(p['id'])))
                self.table.setItem(row, 1, QTableWidgetItem(p['nombre']))
                self.table.setItem(row, 2, QTableWidgetItem(p['categoria'] or 'Sin categoría'))
                self.table.setItem(row, 3, QTableWidgetItem(p['marca'] or 'Sin marca'))
                self.table.setItem(row, 4, QTableWidgetItem(str(p['stock'])))
                self.table.setItem(row, 5, QTableWidgetItem(f"${p['precio_venta']:,.0f}"))
        except Exception as e:
            print(f"Error cargando productos: {e}")

    def seleccionar_producto(self):
        """Selecciona el producto y cierra la ventana"""
        row = self.table.currentRow()
        if row < 0:
            return

        producto_id = int(self.table.item(row, 0).text())

        producto = self.productos_repo.obtener_por_id(producto_id)
        if producto:
            self.producto_seleccionado = producto
            self.accept()
