# -*- coding: utf-8 -*-
"""
Interfaz de Gestión de Usuarios (PySide6)
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QDialog,
    QMessageBox, QFrame, QCheckBox, QAbstractItemView
)
from PySide6.QtCore import Qt
from typing import Optional
from models import Usuario, RolUsuario
from ui_config import COLORS, FONTS, make_font
from ui.widgets import button_qss


class UsuariosUI(QWidget):
    """Interfaz para gestionar usuarios"""

    def __init__(self, parent, auth):
        super().__init__(parent)
        self.parent_widget = parent
        self.auth = auth

        self.crear_interfaz()
        self.cargar_usuarios()

    def crear_interfaz(self):
        """Crea la interfaz de usuarios"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        main_frame = QFrame()
        main_frame.setStyleSheet(f"background: {COLORS['bg_secondary']};")
        frame_layout = QVBoxLayout(main_frame)
        frame_layout.setContentsMargins(20, 10, 20, 10)
        frame_layout.setSpacing(10)

        # Header
        header = QHBoxLayout()

        title = QLabel("👤 Gestión de Usuarios")
        title.setFont(make_font(FONTS['large']))
        title.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent;")
        header.addWidget(title)
        header.addStretch()

        # Botones de acción
        btn_nuevo = QPushButton("➕ Nuevo Usuario")
        btn_nuevo.setFont(make_font(FONTS['body']))
        btn_nuevo.setCursor(Qt.PointingHandCursor)
        btn_nuevo.setStyleSheet(button_qss('primary'))
        btn_nuevo.setMinimumHeight(38)
        btn_nuevo.clicked.connect(self.nuevo_usuario)
        header.addWidget(btn_nuevo)

        btn_editar = QPushButton("✏️ Editar")
        btn_editar.setFont(make_font(FONTS['body']))
        btn_editar.setCursor(Qt.PointingHandCursor)
        btn_editar.setStyleSheet(button_qss('ghost'))
        btn_editar.setMinimumHeight(38)
        btn_editar.clicked.connect(self.editar_usuario)
        header.addWidget(btn_editar)

        btn_password = QPushButton("🔑 Cambiar Contraseña")
        btn_password.setFont(make_font(FONTS['body']))
        btn_password.setCursor(Qt.PointingHandCursor)
        btn_password.setStyleSheet(button_qss('dark'))
        btn_password.setMinimumHeight(38)
        btn_password.clicked.connect(self.cambiar_password)
        header.addWidget(btn_password)

        btn_actualizar = QPushButton("🔄 Actualizar")
        btn_actualizar.setFont(make_font(FONTS['body']))
        btn_actualizar.setCursor(Qt.PointingHandCursor)
        btn_actualizar.setStyleSheet(button_qss('ghost'))
        btn_actualizar.setMinimumHeight(38)
        btn_actualizar.clicked.connect(self.cargar_usuarios)
        header.addWidget(btn_actualizar)

        frame_layout.addLayout(header)

        # Tabla de usuarios
        columnas = ['ID', 'Usuario', 'Nombre', 'Rol', 'Email', 'Teléfono', 'Último Acceso', 'Estado']
        self.table = QTableWidget()
        self.table.setColumnCount(len(columnas))
        self.table.setHorizontalHeaderLabels(columnas)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("background: white;")
        self.table.doubleClicked.connect(self.editar_usuario)

        hdr = self.table.horizontalHeader()
        anchos = [50, 120, 200, 120, 200, 120, 150, 80]
        for i, w in enumerate(anchos):
            hdr.resizeSection(i, w)
        hdr.setStretchLastSection(True)

        frame_layout.addWidget(self.table, 1)
        main_layout.addWidget(main_frame)

    def cargar_usuarios(self):
        """Carga los usuarios en la tabla"""
        self.table.setRowCount(0)

        usuarios = self.auth.listar_usuarios()

        for row, usuario in enumerate(usuarios):
            self.table.insertRow(row)
            estado = "Activo" if usuario.activo else "Inactivo"
            ultimo_acceso = usuario.ultimo_acceso if usuario.ultimo_acceso else "Nunca"

            self.table.setItem(row, 0, QTableWidgetItem(str(usuario.id)))
            self.table.setItem(row, 1, QTableWidgetItem(usuario.username))
            self.table.setItem(row, 2, QTableWidgetItem(usuario.nombre_completo))
            self.table.setItem(row, 3, QTableWidgetItem(usuario.rol))
            self.table.setItem(row, 4, QTableWidgetItem(usuario.email or ''))
            self.table.setItem(row, 5, QTableWidgetItem(usuario.telefono or ''))
            self.table.setItem(row, 6, QTableWidgetItem(str(ultimo_acceso)))
            self.table.setItem(row, 7, QTableWidgetItem(estado))

    def nuevo_usuario(self):
        """Abre ventana para crear nuevo usuario"""
        if not self.auth.tiene_permiso('crear_usuario'):
            QMessageBox.critical(self, "Error", "No tiene permisos para crear usuarios")
            return

        dlg = VentanaUsuarioForm(self, self.auth, None, self.cargar_usuarios)
        dlg.exec()

    def editar_usuario(self):
        """Abre ventana para editar usuario seleccionado"""
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Advertencia", "Seleccione un usuario")
            return

        if not self.auth.tiene_permiso('gestionar_usuarios'):
            QMessageBox.critical(self, "Error", "No tiene permisos para editar usuarios")
            return

        usuario = Usuario(
            id=int(self.table.item(row, 0).text()),
            username=self.table.item(row, 1).text(),
            nombre_completo=self.table.item(row, 2).text(),
            rol=self.table.item(row, 3).text(),
            email=self.table.item(row, 4).text() or None,
            telefono=self.table.item(row, 5).text() or None,
            activo=self.table.item(row, 7).text() == "Activo"
        )

        dlg = VentanaUsuarioForm(self, self.auth, usuario, self.cargar_usuarios)
        dlg.exec()

    def cambiar_password(self):
        """Cambia la contraseña de un usuario"""
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Advertencia", "Seleccione un usuario")
            return

        usuario_id = int(self.table.item(row, 0).text())
        usuario_nombre = self.table.item(row, 2).text()

        dlg = VentanaCambiarPassword(self, self.auth, usuario_id, usuario_nombre)
        dlg.exec()


class VentanaUsuarioForm(QDialog):
    """Ventana de formulario para crear/editar usuario"""

    def __init__(self, parent, auth, usuario: Optional[Usuario], callback):
        super().__init__(parent)
        self.auth = auth
        self.usuario = usuario
        self.callback = callback

        self.setWindowTitle("Editar Usuario" if usuario else "Nuevo Usuario")
        self.setFixedSize(500, 600)
        self.setModal(True)

        self.entries = {}
        self.crear_formulario()

        if usuario:
            self.cargar_datos()

        from ui.widgets import hacer_dialogo_responsivo
        hacer_dialogo_responsivo(self, 500, 600)

    def crear_formulario(self):
        """Crea el formulario"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(60)
        header.setStyleSheet(f"background: {COLORS['primary']};")
        header_layout = QHBoxLayout(header)
        titulo = "Editar Usuario" if self.usuario else "Nuevo Usuario"
        title = QLabel(titulo)
        title.setFont(make_font(FONTS['large']))
        title.setStyleSheet("color: white; background: transparent;")
        title.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(title)
        main_layout.addWidget(header)

        # Formulario
        form_frame = QFrame()
        form_frame.setStyleSheet(f"background: {COLORS['bg_primary']};")
        form_layout = QVBoxLayout(form_frame)
        form_layout.setContentsMargins(30, 20, 30, 20)
        form_layout.setSpacing(5)

        # Usuario
        self.crear_campo(form_layout, 'username', 'Usuario:', True,
                         readonly=bool(self.usuario))

        # Contraseña (solo para nuevo)
        if not self.usuario:
            self.crear_campo(form_layout, 'password', 'Contraseña:', True, password=True)
            self.crear_campo(form_layout, 'password2', 'Confirmar Contraseña:', True, password=True)

        # Nombre completo
        self.crear_campo(form_layout, 'nombre_completo', 'Nombre Completo:', True)

        # Rol
        lbl_rol = QLabel("Rol: *")
        lbl_rol.setFont(make_font(FONTS['body']))
        lbl_rol.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        form_layout.addWidget(lbl_rol)

        self.rol_combo = QComboBox()
        self.rol_combo.setFont(make_font(FONTS['body']))
        roles = [rol.name for rol in RolUsuario]
        self.rol_combo.addItems(roles)
        form_layout.addWidget(self.rol_combo)

        # Email
        self.crear_campo(form_layout, 'email', 'Email:', False)

        # Teléfono
        self.crear_campo(form_layout, 'telefono', 'Teléfono:', False)

        # Estado
        self.activo_check = QCheckBox("Usuario Activo")
        self.activo_check.setFont(make_font(FONTS['body']))
        self.activo_check.setChecked(True)
        self.activo_check.setStyleSheet("background: transparent;")
        form_layout.addWidget(self.activo_check)

        form_layout.addStretch()
        main_layout.addWidget(form_frame, 1)

        # Botones
        btn_frame = QFrame()
        btn_frame.setStyleSheet(f"background: {COLORS['bg_primary']};")
        btn_layout = QHBoxLayout(btn_frame)
        btn_layout.setContentsMargins(30, 0, 30, 20)

        btn_guardar = QPushButton("💾  Guardar")
        btn_guardar.setFont(make_font(FONTS['body_bold']))
        btn_guardar.setCursor(Qt.PointingHandCursor)
        btn_guardar.setStyleSheet(button_qss('success'))
        btn_guardar.setMinimumHeight(42)
        btn_guardar.clicked.connect(self.guardar)
        btn_layout.addWidget(btn_guardar)

        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setFont(make_font(FONTS['body']))
        btn_cancelar.setCursor(Qt.PointingHandCursor)
        btn_cancelar.setStyleSheet(button_qss('ghost'))
        btn_cancelar.setMinimumHeight(42)
        btn_cancelar.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancelar)

        main_layout.addWidget(btn_frame)

    def crear_campo(self, parent_layout, nombre, etiqueta, requerido, readonly=False, password=False):
        """Crea un campo del formulario"""
        label_text = etiqueta + (' *' if requerido else '')
        lbl = QLabel(label_text)
        lbl.setFont(make_font(FONTS['body']))
        lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        parent_layout.addWidget(lbl)

        entry = QLineEdit()
        entry.setFont(make_font(FONTS['body']))
        if password:
            entry.setEchoMode(QLineEdit.Password)
        if readonly:
            entry.setReadOnly(True)
        parent_layout.addWidget(entry)
        self.entries[nombre] = entry

    def cargar_datos(self):
        """Carga los datos del usuario en el formulario"""
        if not self.usuario:
            return

        self.entries['username'].setText(self.usuario.username)
        self.entries['nombre_completo'].setText(self.usuario.nombre_completo)

        idx = self.rol_combo.findText(self.usuario.rol)
        if idx >= 0:
            self.rol_combo.setCurrentIndex(idx)

        if self.usuario.email:
            self.entries['email'].setText(self.usuario.email)

        if self.usuario.telefono:
            self.entries['telefono'].setText(self.usuario.telefono)

        self.activo_check.setChecked(self.usuario.activo)

    def guardar(self):
        """Guarda el usuario"""
        username = self.entries['username'].text().strip()
        nombre_completo = self.entries['nombre_completo'].text().strip()
        rol = self.rol_combo.currentText()

        if not username or not nombre_completo or not rol:
            QMessageBox.critical(self, "Error", "Complete todos los campos obligatorios")
            return

        # Validar contraseñas para nuevo usuario
        if not self.usuario:
            password = self.entries['password'].text()
            password2 = self.entries['password2'].text()

            if not password or not password2:
                QMessageBox.critical(self, "Error", "Complete las contraseñas")
                return

            if password != password2:
                QMessageBox.critical(self, "Error", "Las contraseñas no coinciden")
                return

            if len(password) < 6:
                QMessageBox.critical(self, "Error", "La contraseña debe tener al menos 6 caracteres")
                return

        email = self.entries['email'].text().strip() or None
        telefono = self.entries['telefono'].text().strip() or None

        if self.usuario:
            # Actualizar (no hay método directo, usar SQL)
            conn = self.auth.db.conectar()
            cursor = conn.cursor()

            try:
                cursor.execute('''
                    UPDATE usuarios
                    SET nombre_completo = ?, rol = ?, email = ?, telefono = ?, activo = ?
                    WHERE id = ?
                ''', (nombre_completo, rol, email, telefono,
                      1 if self.activo_check.isChecked() else 0, self.usuario.id))

                conn.commit()
                conn.close()

                QMessageBox.information(self, "Éxito", "Usuario actualizado exitosamente")
                self.callback()
                self.accept()
            except Exception as e:
                conn.close()
                QMessageBox.critical(self, "Error", f"Error al actualizar: {str(e)}")
        else:
            # Crear nuevo
            password = self.entries['password'].text()
            exito, mensaje = self.auth.crear_usuario(
                username, password, nombre_completo, rol, email, telefono
            )

            if exito:
                QMessageBox.information(self, "Éxito", mensaje)
                self.callback()
                self.accept()
            else:
                QMessageBox.critical(self, "Error", mensaje)


class VentanaCambiarPassword(QDialog):
    """Ventana para cambiar contraseña"""

    def __init__(self, parent, auth, usuario_id, usuario_nombre):
        super().__init__(parent)
        self.auth = auth
        self.usuario_id = usuario_id

        self.setWindowTitle("Cambiar Contraseña")
        self.setFixedSize(400, 300)
        self.setModal(True)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(60)
        header.setStyleSheet(f"background: {COLORS['primary']};")
        header_layout = QHBoxLayout(header)
        title = QLabel("🔑 Cambiar Contraseña")
        title.setFont(make_font(FONTS['large']))
        title.setStyleSheet("color: white; background: transparent;")
        title.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(title)
        main_layout.addWidget(header)

        # Form
        form_frame = QFrame()
        form_frame.setStyleSheet(f"background: {COLORS['bg_primary']};")
        form_layout = QVBoxLayout(form_frame)
        form_layout.setContentsMargins(30, 20, 30, 20)

        lbl_user = QLabel(f"Usuario: {usuario_nombre}")
        lbl_user.setFont(make_font(FONTS['body_bold']))
        lbl_user.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent;")
        form_layout.addWidget(lbl_user)

        # Nueva contraseña
        lbl_pw = QLabel("Nueva Contraseña:")
        lbl_pw.setFont(make_font(FONTS['body']))
        lbl_pw.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        form_layout.addWidget(lbl_pw)

        self.password_entry = QLineEdit()
        self.password_entry.setFont(make_font(FONTS['body']))
        self.password_entry.setEchoMode(QLineEdit.Password)
        form_layout.addWidget(self.password_entry)

        # Confirmar contraseña
        lbl_pw2 = QLabel("Confirmar Contraseña:")
        lbl_pw2.setFont(make_font(FONTS['body']))
        lbl_pw2.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        form_layout.addWidget(lbl_pw2)

        self.password2_entry = QLineEdit()
        self.password2_entry.setFont(make_font(FONTS['body']))
        self.password2_entry.setEchoMode(QLineEdit.Password)
        form_layout.addWidget(self.password2_entry)

        form_layout.addStretch()
        main_layout.addWidget(form_frame, 1)

        # Botones
        btn_frame = QFrame()
        btn_frame.setStyleSheet(f"background: {COLORS['bg_primary']};")
        btn_layout = QHBoxLayout(btn_frame)
        btn_layout.setContentsMargins(30, 0, 30, 20)

        btn_cambiar = QPushButton("💾  Cambiar")
        btn_cambiar.setFont(make_font(FONTS['body_bold']))
        btn_cambiar.setCursor(Qt.PointingHandCursor)
        btn_cambiar.setStyleSheet(button_qss('success'))
        btn_cambiar.setMinimumHeight(42)
        btn_cambiar.clicked.connect(self.cambiar)
        btn_layout.addWidget(btn_cambiar)

        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setFont(make_font(FONTS['body']))
        btn_cancelar.setCursor(Qt.PointingHandCursor)
        btn_cancelar.setStyleSheet(button_qss('ghost'))
        btn_cancelar.setMinimumHeight(42)
        btn_cancelar.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancelar)

        main_layout.addWidget(btn_frame)

    def cambiar(self):
        """Cambia la contraseña"""
        password = self.password_entry.text()
        password2 = self.password2_entry.text()

        if not password or not password2:
            QMessageBox.critical(self, "Error", "Complete ambos campos")
            return

        if password != password2:
            QMessageBox.critical(self, "Error", "Las contraseñas no coinciden")
            return

        if len(password) < 6:
            QMessageBox.critical(self, "Error", "La contraseña debe tener al menos 6 caracteres")
            return

        exito, mensaje = self.auth.cambiar_password(self.usuario_id, password)

        if exito:
            QMessageBox.information(self, "Éxito", mensaje)
            self.accept()
        else:
            QMessageBox.critical(self, "Error", mensaje)