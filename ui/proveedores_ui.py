# -*- coding: utf-8 -*-
"""
Interfaz de usuario para gestión de proveedores (PySide6)
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QCheckBox,
    QGroupBox, QGridLayout, QDialog, QMessageBox, QFrame, QSlider,
    QAbstractItemView, QSpinBox, QScrollArea
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor, QCursor

from models import Proveedor
from ui_config import COLORS, FONTS, make_font


class ProveedoresUI(QWidget):
    """Interfaz para gestión de proveedores"""

    def __init__(self, parent, proveedores_repo, auth_manager):
        super().__init__(parent)
        self.parent_widget = parent
        self.repo = proveedores_repo
        self.auth = auth_manager
        self.proveedor_seleccionado = None

        self.crear_ui()
        self.cargar_proveedores()

    def crear_ui(self):
        """Crea la interfaz de usuario"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        main_frame = QFrame()
        main_frame.setStyleSheet(f"background: {COLORS['bg_secondary']};")
        frame_layout = QVBoxLayout(main_frame)
        frame_layout.setContentsMargins(20, 20, 20, 10)
        frame_layout.setSpacing(10)

        # Header
        header = QHBoxLayout()

        title = QLabel("🏪 Gestión de Proveedores")
        title.setFont(make_font(FONTS['large']))
        title.setStyleSheet(f"color: {COLORS['text_primary']};")
        header.addWidget(title)

        header.addStretch()

        # Botones de acción
        btn_nuevo = QPushButton("➕ Nuevo Proveedor")
        btn_nuevo.setFont(make_font(FONTS['body_bold']))
        btn_nuevo.setCursor(QCursor(Qt.PointingHandCursor))
        btn_nuevo.setStyleSheet(
            f"QPushButton {{ background: {COLORS['primary']}; color: white; border: none; "
            f"border-radius: 6px; padding: 8px 15px; }}"
            f"QPushButton:hover {{ background: {COLORS['primary_dark']}; }}"
        )
        btn_nuevo.clicked.connect(self.nuevo_proveedor)
        header.addWidget(btn_nuevo)

        btn_editar = QPushButton("✏️ Editar")
        btn_editar.setFont(make_font(FONTS['body_bold']))
        btn_editar.setCursor(QCursor(Qt.PointingHandCursor))
        btn_editar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['info']}; color: white; border: none; "
            f"border-radius: 6px; padding: 8px 15px; }}"
            f"QPushButton:hover {{ background: {COLORS['primary']}; }}"
        )
        btn_editar.clicked.connect(self.editar_proveedor)
        header.addWidget(btn_editar)

        btn_eliminar = QPushButton("🗑️ Eliminar")
        btn_eliminar.setFont(make_font(FONTS['body_bold']))
        btn_eliminar.setCursor(QCursor(Qt.PointingHandCursor))
        btn_eliminar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['danger']}; color: white; border: none; "
            f"border-radius: 6px; padding: 8px 15px; }}"
            f"QPushButton:hover {{ background: {COLORS['danger_dark']}; }}"
        )
        btn_eliminar.clicked.connect(self.eliminar_proveedor)
        header.addWidget(btn_eliminar)

        btn_actualizar = QPushButton("🔄 Actualizar")
        btn_actualizar.setFont(make_font(FONTS['body']))
        btn_actualizar.setCursor(QCursor(Qt.PointingHandCursor))
        btn_actualizar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['secondary']}; color: white; border: none; "
            f"border-radius: 6px; padding: 8px 15px; }}"
            f"QPushButton:hover {{ background: {COLORS['secondary_dark']}; }}"
        )
        btn_actualizar.clicked.connect(self.cargar_proveedores)
        header.addWidget(btn_actualizar)

        frame_layout.addLayout(header)

        # Búsqueda
        search_layout = QHBoxLayout()
        lbl_buscar = QLabel("🔍 Buscar:")
        lbl_buscar.setFont(make_font(FONTS['body']))
        search_layout.addWidget(lbl_buscar)

        self.search_input = QLineEdit()
        self.search_input.setFont(make_font(FONTS['body']))
        self.search_input.setPlaceholderText("Buscar por nombre, NIT, ciudad...")
        self.search_input.setFixedWidth(350)
        self.search_input.textChanged.connect(self.buscar_proveedores)
        search_layout.addWidget(self.search_input)
        search_layout.addStretch()

        frame_layout.addLayout(search_layout)

        # Tabla
        columns = ['ID', 'NIT', 'Nombre', 'Teléfono', 'Ciudad', 'Contacto',
                    'Productos', 'Calificación', 'Días Crédito', 'Estado']
        widths = [50, 100, 200, 100, 100, 150, 150, 80, 80, 80]

        self.table = QTableWidget()
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)

        for i, w in enumerate(widths):
            self.table.setColumnWidth(i, w)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.table.doubleClicked.connect(lambda: self.editar_proveedor())

        frame_layout.addWidget(self.table, 1)

        main_layout.addWidget(main_frame)

    def cargar_proveedores(self):
        """Carga proveedores en la tabla"""
        self.table.setRowCount(0)

        try:
            proveedores = self.repo.listar_proveedores(solo_activos=False)

            for row_idx, proveedor in enumerate(proveedores):
                self.table.insertRow(row_idx)
                estado = "✅ Activo" if proveedor.activo else "❌ Inactivo"
                calificacion = "⭐" * int(proveedor.calificacion)

                valores = [
                    str(proveedor.id),
                    proveedor.nit or 'N/A',
                    proveedor.nombre,
                    proveedor.telefono or 'N/A',
                    proveedor.ciudad or 'N/A',
                    proveedor.contacto_nombre or 'N/A',
                    proveedor.productos_provee or 'N/A',
                    calificacion,
                    str(proveedor.dias_credito),
                    estado,
                ]

                for col, val in enumerate(valores):
                    item = QTableWidgetItem(val)
                    item.setTextAlignment(Qt.AlignCenter)
                    self.table.setItem(row_idx, col, item)

        except Exception as e:
            QMessageBox.critical(self, "Error",
                                 f"Error al cargar proveedores:\n{str(e)}")

    def buscar_proveedores(self):
        """Busca proveedores según criterio"""
        criterio = self.search_input.text().strip()
        self.table.setRowCount(0)

        try:
            if criterio:
                proveedores = self.repo.buscar_proveedores(criterio, solo_activos=False)
            else:
                proveedores = self.repo.listar_proveedores(solo_activos=False)

            for row_idx, proveedor in enumerate(proveedores):
                self.table.insertRow(row_idx)
                estado = "✅ Activo" if proveedor.activo else "❌ Inactivo"
                calificacion = "⭐" * int(proveedor.calificacion)

                valores = [
                    str(proveedor.id),
                    proveedor.nit or 'N/A',
                    proveedor.nombre,
                    proveedor.telefono or 'N/A',
                    proveedor.ciudad or 'N/A',
                    proveedor.contacto_nombre or 'N/A',
                    proveedor.productos_provee or 'N/A',
                    calificacion,
                    str(proveedor.dias_credito),
                    estado,
                ]

                for col, val in enumerate(valores):
                    item = QTableWidgetItem(val)
                    item.setTextAlignment(Qt.AlignCenter)
                    self.table.setItem(row_idx, col, item)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al buscar:\n{str(e)}")

    def nuevo_proveedor(self):
        """Abre ventana para crear nuevo proveedor"""
        FormularioProveedorWindow(self, self.repo, self.auth,
                                  callback=self.cargar_proveedores)

    def editar_proveedor(self):
        """Abre ventana para editar proveedor seleccionado"""
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Advertencia", "Seleccione un proveedor")
            return

        proveedor_id = int(self.table.item(row, 0).text())
        proveedor = self.repo.obtener_por_id(proveedor_id)

        if proveedor:
            FormularioProveedorWindow(self, self.repo, self.auth,
                                      proveedor=proveedor,
                                      callback=self.cargar_proveedores)

    def eliminar_proveedor(self):
        """Elimina (desactiva) el proveedor seleccionado"""
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Advertencia", "Seleccione un proveedor")
            return

        proveedor_id = int(self.table.item(row, 0).text())
        nombre = self.table.item(row, 2).text()

        respuesta = QMessageBox.question(
            self, "Confirmar Eliminación",
            f"¿Está seguro de eliminar al proveedor:\n{nombre}?\n\n"
            "El proveedor se marcará como inactivo.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )

        if respuesta == QMessageBox.Yes:
            exito, mensaje = self.repo.eliminar_proveedor(proveedor_id)
            if exito:
                QMessageBox.information(self, "Éxito", mensaje)
                self.cargar_proveedores()
            else:
                QMessageBox.critical(self, "Error", mensaje)


class FormularioProveedorWindow(QDialog):
    """Ventana de formulario para crear/editar proveedores"""

    def __init__(self, parent, repo, auth, proveedor=None, callback=None):
        super().__init__(parent)
        self.repo = repo
        self.auth = auth
        self.proveedor = proveedor
        self.callback = callback

        self.setWindowTitle("Nuevo Proveedor" if not proveedor else "Editar Proveedor")
        self.resize(600, 750)
        self.setModal(True)
        self.setStyleSheet(f"background: {COLORS['bg_secondary']};")

        self.crear_formulario()

        if proveedor:
            self.cargar_datos()

        self.centrar_ventana()
        self.exec()

    def centrar_ventana(self):
        """Centra la ventana en la pantalla"""
        screen = self.screen().availableGeometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)

    def crear_formulario(self):
        """Crea el formulario"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(60)
        header.setStyleSheet(f"background: {COLORS['primary']};")
        header_lay = QHBoxLayout(header)
        titulo = "✏️ Editar Proveedor" if self.proveedor else "➕ Nuevo Proveedor"
        lbl_titulo = QLabel(titulo)
        lbl_titulo.setFont(make_font(FONTS['large']))
        lbl_titulo.setStyleSheet("color: white;")
        lbl_titulo.setAlignment(Qt.AlignCenter)
        header_lay.addWidget(lbl_titulo)
        main_layout.addWidget(header)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"background: {COLORS['bg_secondary']};")

        form_widget = QWidget()
        form = QGridLayout(form_widget)
        form.setContentsMargins(30, 20, 30, 20)
        form.setSpacing(8)

        # Campos
        campos = [
            ("NIT:", "nit_entry"),
            ("Nombre Comercial: *", "nombre_entry"),
            ("Teléfono:", "telefono_entry"),
            ("Correo Electrónico:", "correo_entry"),
            ("Dirección:", "direccion_entry"),
            ("Ciudad:", "ciudad_entry"),
            ("Nombre Contacto:", "contacto_nombre_entry"),
            ("Teléfono Contacto:", "contacto_telefono_entry"),
            ("Productos que Provee:", "productos_entry"),
        ]

        self.entries = {}

        for i, (label, var_name) in enumerate(campos):
            lbl = QLabel(label)
            lbl.setFont(make_font(FONTS['body']))
            lbl.setStyleSheet(f"color: {COLORS['text_secondary']};")
            form.addWidget(lbl, i, 0, Qt.AlignLeft)

            entry = QLineEdit()
            entry.setFont(make_font(FONTS['body']))
            form.addWidget(entry, i, 1)
            self.entries[var_name] = entry

        form.setColumnStretch(1, 1)

        # Calificación
        row_cal = len(campos)
        lbl_cal = QLabel("Calificación (1-5):")
        lbl_cal.setFont(make_font(FONTS['body']))
        lbl_cal.setStyleSheet(f"color: {COLORS['text_secondary']};")
        form.addWidget(lbl_cal, row_cal, 0, Qt.AlignLeft)

        cal_widget = QWidget()
        cal_lay = QHBoxLayout(cal_widget)
        cal_lay.setContentsMargins(0, 0, 0, 0)

        self.calificacion_slider = QSlider(Qt.Horizontal)
        self.calificacion_slider.setRange(10, 50)  # 1.0 to 5.0 (x10)
        self.calificacion_slider.setValue(30)
        self.calificacion_slider.setFixedWidth(200)
        cal_lay.addWidget(self.calificacion_slider)

        self.calificacion_label = QLabel("3.0")
        self.calificacion_label.setFont(make_font(FONTS['body']))
        cal_lay.addWidget(self.calificacion_label)
        cal_lay.addStretch()

        self.calificacion_slider.valueChanged.connect(self.actualizar_calificacion)

        form.addWidget(cal_widget, row_cal, 1)

        # Días de crédito
        row_dias = row_cal + 1
        lbl_dias = QLabel("Días de Crédito:")
        lbl_dias.setFont(make_font(FONTS['body']))
        lbl_dias.setStyleSheet(f"color: {COLORS['text_secondary']};")
        form.addWidget(lbl_dias, row_dias, 0, Qt.AlignLeft)

        self.dias_credito_spin = QSpinBox()
        self.dias_credito_spin.setFont(make_font(FONTS['body']))
        self.dias_credito_spin.setRange(0, 180)
        self.dias_credito_spin.setValue(0)
        form.addWidget(self.dias_credito_spin, row_dias, 1)

        # Estado
        row_estado = row_dias + 1
        lbl_estado = QLabel("Estado:")
        lbl_estado.setFont(make_font(FONTS['body']))
        lbl_estado.setStyleSheet(f"color: {COLORS['text_secondary']};")
        form.addWidget(lbl_estado, row_estado, 0, Qt.AlignLeft)

        self.activo_check = QCheckBox("Proveedor Activo")
        self.activo_check.setFont(make_font(FONTS['body']))
        self.activo_check.setChecked(True)
        form.addWidget(self.activo_check, row_estado, 1)

        scroll.setWidget(form_widget)
        main_layout.addWidget(scroll, 1)

        # Botones
        btn_frame = QFrame()
        btn_frame.setStyleSheet(f"background: {COLORS['bg_secondary']};")
        btn_lay = QHBoxLayout(btn_frame)
        btn_lay.setContentsMargins(30, 10, 30, 20)

        btn_guardar = QPushButton("💾 Guardar")
        btn_guardar.setFont(make_font(FONTS['body_bold']))
        btn_guardar.setCursor(QCursor(Qt.PointingHandCursor))
        btn_guardar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['success']}; color: white; border: none; "
            f"border-radius: 6px; padding: 10px 20px; }}"
            f"QPushButton:hover {{ background: {COLORS['success_dark']}; }}"
        )
        btn_guardar.clicked.connect(self.guardar)
        btn_lay.addWidget(btn_guardar)

        btn_cancelar = QPushButton("❌ Cancelar")
        btn_cancelar.setFont(make_font(FONTS['body_bold']))
        btn_cancelar.setCursor(QCursor(Qt.PointingHandCursor))
        btn_cancelar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['danger']}; color: white; border: none; "
            f"border-radius: 6px; padding: 10px 20px; }}"
            f"QPushButton:hover {{ background: {COLORS['danger_dark']}; }}"
        )
        btn_cancelar.clicked.connect(self.reject)
        btn_lay.addWidget(btn_cancelar)

        main_layout.addWidget(btn_frame)

    def actualizar_calificacion(self, value):
        """Actualiza el label de calificación"""
        valor = value / 10.0
        self.calificacion_label.setText(f"{valor:.1f}")

    def cargar_datos(self):
        """Carga datos del proveedor en el formulario"""
        if not self.proveedor:
            return

        self.entries['nit_entry'].setText(self.proveedor.nit or '')
        self.entries['nombre_entry'].setText(self.proveedor.nombre)
        self.entries['telefono_entry'].setText(self.proveedor.telefono or '')
        self.entries['correo_entry'].setText(self.proveedor.correo or '')
        self.entries['direccion_entry'].setText(self.proveedor.direccion or '')
        self.entries['ciudad_entry'].setText(self.proveedor.ciudad or '')
        self.entries['contacto_nombre_entry'].setText(self.proveedor.contacto_nombre or '')
        self.entries['contacto_telefono_entry'].setText(self.proveedor.contacto_telefono or '')
        self.entries['productos_entry'].setText(self.proveedor.productos_provee or '')

        self.calificacion_slider.setValue(int(self.proveedor.calificacion * 10))
        self.dias_credito_spin.setValue(self.proveedor.dias_credito)
        self.activo_check.setChecked(self.proveedor.activo)

    def guardar(self):
        """Guarda el proveedor"""
        nombre = self.entries['nombre_entry'].text().strip()

        if not nombre:
            QMessageBox.warning(self, "Advertencia", "El nombre es obligatorio")
            return

        proveedor = Proveedor(
            id=self.proveedor.id if self.proveedor else None,
            nit=self.entries['nit_entry'].text().strip() or None,
            nombre=nombre,
            telefono=self.entries['telefono_entry'].text().strip() or None,
            correo=self.entries['correo_entry'].text().strip() or None,
            direccion=self.entries['direccion_entry'].text().strip() or None,
            ciudad=self.entries['ciudad_entry'].text().strip() or None,
            contacto_nombre=self.entries['contacto_nombre_entry'].text().strip() or None,
            contacto_telefono=self.entries['contacto_telefono_entry'].text().strip() or None,
            productos_provee=self.entries['productos_entry'].text().strip() or None,
            calificacion=self.calificacion_slider.value() / 10.0,
            dias_credito=self.dias_credito_spin.value(),
            activo=self.activo_check.isChecked()
        )

        if self.proveedor:
            exito, mensaje = self.repo.actualizar_proveedor(proveedor)
        else:
            exito, mensaje, _ = self.repo.crear_proveedor(proveedor)

        if exito:
            QMessageBox.information(self, "Éxito", mensaje)
            if self.callback:
                self.callback()
            self.accept()
        else:
            QMessageBox.critical(self, "Error", mensaje)

