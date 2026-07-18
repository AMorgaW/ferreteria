# -*- coding: utf-8 -*-
"""
Interfaz de Usuario para Gestión de Clientes (PySide6)
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QCheckBox,
    QGroupBox, QGridLayout, QDialog, QMessageBox, QMenu, QFrame,
    QAbstractItemView, QSizePolicy, QScrollArea
)
from PySide6.QtCore import Qt, Signal, QTimer, QThreadPool
from PySide6.QtGui import QFont, QColor, QCursor

from ui_config import COLORS, FONTS, ICONS, make_font
from ui.widgets import button_qss
from models import Cliente, AbonoVenta
from datetime import datetime
from ui.async_worker import FunctionWorker


class ClientesUI(QWidget):
    """Interfaz para gestión de clientes"""

    def __init__(self, parent_frame, clientes_repo, auth_manager,
                 cuentas_por_cobrar_service=None, abonos_ventas_repo=None):
        super().__init__(parent_frame)
        self.parent_widget = parent_frame
        self.clientes_repo = clientes_repo
        self.auth = auth_manager
        self.cuentas_service = cuentas_por_cobrar_service
        self.abonos_repo = abonos_ventas_repo
        self.cliente_seleccionado = None
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(350)
        self._search_timer.timeout.connect(self.buscar_clientes)
        self._thread_pool = QThreadPool.globalInstance()
        self._load_seq = 0

        self.crear_interfaz()
        self.cargar_clientes()

    def crear_interfaz(self):
        """Crea la interfaz principal"""
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

        title = QLabel(f"{ICONS['clientes']} Gestión de Clientes")
        title.setFont(make_font(FONTS['large']))
        title.setStyleSheet(f"color: {COLORS['text_primary']};")
        header.addWidget(title)

        header.addStretch()

        # Botones de acción
        btn_nuevo = QPushButton(f"{ICONS['agregar']} Nuevo Cliente")
        btn_nuevo.setFont(make_font(FONTS['body']))
        btn_nuevo.setCursor(QCursor(Qt.PointingHandCursor))
        btn_nuevo.setStyleSheet(button_qss('primary'))
        btn_nuevo.setMinimumHeight(38)
        btn_nuevo.clicked.connect(self.nuevo_cliente)
        header.addWidget(btn_nuevo)

        if self.cuentas_service:
            btn_cuentas = QPushButton("💰 Cuentas por Cobrar")
            btn_cuentas.setFont(make_font(FONTS['body']))
            btn_cuentas.setCursor(QCursor(Qt.PointingHandCursor))
            btn_cuentas.setStyleSheet(button_qss('dark'))
            btn_cuentas.setMinimumHeight(38)
            btn_cuentas.clicked.connect(self.ver_cuentas_por_cobrar_cliente)
            header.addWidget(btn_cuentas)

        btn_actualizar = QPushButton(f"{ICONS['actualizar']} Actualizar")
        btn_actualizar.setFont(make_font(FONTS['body']))
        btn_actualizar.setCursor(QCursor(Qt.PointingHandCursor))
        btn_actualizar.setStyleSheet(button_qss('ghost'))
        btn_actualizar.setMinimumHeight(38)
        btn_actualizar.clicked.connect(self.cargar_clientes)
        header.addWidget(btn_actualizar)

        frame_layout.addLayout(header)

        # Barra de búsqueda
        search_layout = QHBoxLayout()
        lbl_buscar = QLabel(f"{ICONS['buscar']} Buscar:")
        lbl_buscar.setFont(make_font(FONTS['body']))
        search_layout.addWidget(lbl_buscar)

        self.search_input = QLineEdit()
        self.search_input.setFont(make_font(FONTS['body']))
        self.search_input.setPlaceholderText("Buscar por nombre, documento, teléfono...")
        self.search_input.setFixedWidth(350)
        self.search_input.textChanged.connect(lambda: self._search_timer.start())
        search_layout.addWidget(self.search_input)
        search_layout.addStretch()

        frame_layout.addLayout(search_layout)

        # Tabla de clientes
        columnas = ['ID', 'Documento', 'Nombre', 'Teléfono', 'Ciudad',
                     'Límite Crédito', 'Saldo', 'Estado']
        anchos = [50, 120, 200, 100, 100, 100, 100, 80]

        self.table = QTableWidget()
        self.table.setColumnCount(len(columnas))
        self.table.setHorizontalHeaderLabels(columnas)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.mostrar_menu_contextual)
        self.table.doubleClicked.connect(lambda: self.editar_cliente())

        hdr = self.table.horizontalHeader()
        for i, w in enumerate(anchos):
            self.table.setColumnWidth(i, w)
        hdr.setStretchLastSection(True)

        frame_layout.addWidget(self.table, 1)

        # Botones inferiores
        bottom = QHBoxLayout()

        btn_editar = QPushButton(f"{ICONS['editar']} Editar")
        btn_editar.setFont(make_font(FONTS['body']))
        btn_editar.setCursor(QCursor(Qt.PointingHandCursor))
        btn_editar.setStyleSheet(button_qss('ghost'))
        btn_editar.setMinimumHeight(38)
        btn_editar.clicked.connect(self.editar_cliente)
        bottom.addWidget(btn_editar)

        btn_eliminar = QPushButton(f"{ICONS['eliminar']} Eliminar")
        btn_eliminar.setFont(make_font(FONTS['body']))
        btn_eliminar.setCursor(QCursor(Qt.PointingHandCursor))
        btn_eliminar.setStyleSheet(button_qss('ghost_danger'))
        btn_eliminar.setMinimumHeight(38)
        btn_eliminar.clicked.connect(self.eliminar_cliente)
        bottom.addWidget(btn_eliminar)

        bottom.addStretch()

        self.stats_label = QLabel("")
        self.stats_label.setFont(make_font(FONTS['small']))
        self.stats_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        bottom.addWidget(self.stats_label)

        frame_layout.addLayout(bottom)

        main_layout.addWidget(main_frame)

    # ------------------------------------------------------------------
    #  Datos
    # ------------------------------------------------------------------

    def cargar_clientes(self):
        """Carga todos los clientes en la tabla"""
        self.table.setRowCount(0)

        if self.clientes_repo.cache_disponible():
            self._renderizar_clientes(
                self.clientes_repo.buscar_clientes_cache(solo_activos=False, limite=500),
                "Total"
            )
            return

        self._load_seq += 1
        seq = self._load_seq
        worker = FunctionWorker(self.clientes_repo.listar_clientes, False, 500)
        worker.signals.result.connect(lambda clientes, s=seq: self._on_clientes_cargados(clientes, s, "Total"))
        worker.signals.error.connect(lambda e: QMessageBox.critical(self, "Error", f"Error cargando clientes:\n{e}"))
        self._thread_pool.start(worker)

    def buscar_clientes(self):
        """Busca clientes según el criterio"""
        criterio = self.search_input.text().strip()

        self.table.setRowCount(0)

        if self.clientes_repo.cache_disponible():
            limite = 250 if criterio else 500
            clientes = self.clientes_repo.buscar_clientes_cache(criterio, solo_activos=False, limite=limite)
            self._renderizar_clientes(clientes, "Encontrados")
            return

        self._load_seq += 1
        seq = self._load_seq
        if criterio:
            worker = FunctionWorker(self.clientes_repo.buscar_clientes, criterio, False, 250)
        else:
            worker = FunctionWorker(self.clientes_repo.listar_clientes, False, 500)
        worker.signals.result.connect(lambda clientes, s=seq: self._on_clientes_cargados(clientes, s, "Encontrados"))
        worker.signals.error.connect(lambda e: QMessageBox.critical(self, "Error", f"Error buscando clientes:\n{e}"))
        self._thread_pool.start(worker)

    def _on_clientes_cargados(self, clientes, seq, etiqueta):
        if seq != self._load_seq:
            return
        self._renderizar_clientes(clientes, etiqueta)

    def _renderizar_clientes(self, clientes, etiqueta):
        self.table.setRowCount(0)
        for row, cliente in enumerate(clientes):
            self.table.insertRow(row)
            estado = "Activo" if cliente.activo else "Inactivo"
            valores = [
                str(cliente.id),
                f"{cliente.tipo_documento} {cliente.numero_documento}",
                cliente.nombre,
                cliente.telefono or '-',
                cliente.ciudad or '-',
                f"${cliente.limite_credito:,.0f}",
                f"${cliente.saldo_pendiente:,.0f}",
                estado,
            ]
            for col, val in enumerate(valores):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignCenter)
                if not cliente.activo:
                    item.setBackground(QColor('#fee2e2'))
                    item.setForeground(QColor('#991b1b'))
                self.table.setItem(row, col, item)

        self.stats_label.setText(f"{etiqueta}: {len(clientes)} clientes")

    # ------------------------------------------------------------------
    #  Acciones
    # ------------------------------------------------------------------

    def nuevo_cliente(self):
        """Abre ventana para crear nuevo cliente"""
        FormularioCliente(self, self.clientes_repo, self.auth,
                          callback=self.cargar_clientes)

    def editar_cliente(self):
        """Edita el cliente seleccionado"""
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Advertencia", "Seleccione un cliente")
            return

        cliente_id = int(self.table.item(row, 0).text())
        cliente = self.clientes_repo.obtener_cliente(cliente_id)
        if cliente:
            FormularioCliente(self, self.clientes_repo, self.auth,
                              cliente=cliente, callback=self.cargar_clientes)

    def eliminar_cliente(self):
        """Elimina el cliente seleccionado"""
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Advertencia", "Seleccione un cliente")
            return

        cliente_id = int(self.table.item(row, 0).text())
        nombre = self.table.item(row, 2).text()

        respuesta = QMessageBox.question(
            self, "Confirmar eliminación",
            f"¿Está seguro de eliminar el cliente '{nombre}'?\n\n"
            "Esta acción no se puede deshacer.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )

        if respuesta == QMessageBox.Yes:
            exito, mensaje = self.clientes_repo.eliminar_cliente(cliente_id)
            if exito:
                QMessageBox.information(self, "Éxito", mensaje)
                self.cargar_clientes()
            else:
                QMessageBox.critical(self, "Error", mensaje)

    def mostrar_menu_contextual(self, pos):
        """Muestra menú contextual"""
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        self.table.selectRow(row)

        menu = QMenu(self)
        menu.addAction("Editar", self.editar_cliente)
        menu.addAction("Ver historial", self.ver_historial)
        menu.addSeparator()
        menu.addAction("Eliminar", self.eliminar_cliente)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def ver_historial(self):
        """Muestra el historial del cliente"""
        row = self.table.currentRow()
        if row < 0:
            return

        cliente_id = self.table.item(row, 0).text()
        QMessageBox.information(
            self, "Información",
            f"Historial del cliente ID {cliente_id}\n(Funcionalidad en desarrollo)"
        )

    # ------------------------------------------------------------------
    #  Cuentas por cobrar
    # ------------------------------------------------------------------

    def ver_cuentas_por_cobrar_cliente(self):
        """Abre modal con cuentas por cobrar del cliente seleccionado"""
        if not self.cuentas_service:
            QMessageBox.warning(self, "Advertencia",
                                "Servicio de cuentas por cobrar no disponible")
            return

        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Advertencia", "Seleccione un cliente")
            return

        cliente_id = int(self.table.item(row, 0).text())
        datos = self.cuentas_service.obtener_cuentas_cliente(cliente_id)

        if not datos:
            QMessageBox.information(self, "Información", "Cliente no encontrado")
            return

        if not datos['facturas']:
            QMessageBox.information(
                self, "Información",
                f"El cliente {datos['cliente']['nombre']} no tiene facturas pendientes"
            )
            return

        self._mostrar_modal_cuentas(datos)

    def _mostrar_modal_cuentas(self, datos):
        """Muestra modal con detalles de cuentas por cobrar"""
        ventana = QDialog(self)
        ventana.setWindowTitle("Cuentas por Cobrar - Cliente")
        ventana.resize(900, 600)
        ventana.setModal(True)
        layout = QVBoxLayout(ventana)

        # Info del cliente
        info_group = QGroupBox("Información del Cliente")
        info_group.setFont(make_font(FONTS['body_bold']))
        info_lay = QVBoxLayout(info_group)
        cliente = datos['cliente']
        for txt in [
            f"Cliente: {cliente['nombre']}",
            f"Documento: {cliente['documento']}",
            f"Límite de Crédito: ${cliente['limite_credito']:,.0f}",
        ]:
            lbl = QLabel(txt)
            lbl.setFont(make_font(FONTS['body']))
            info_lay.addWidget(lbl)
        layout.addWidget(info_group)

        # Totales
        totales_group = QGroupBox("Resumen")
        totales_group.setFont(make_font(FONTS['body_bold']))
        tot_lay = QVBoxLayout(totales_group)

        lbl_deuda = QLabel(f"Total Deuda: ${datos['total_deuda']:,.0f}")
        lbl_deuda.setFont(QFont('Segoe UI', 14, QFont.Bold))
        lbl_deuda.setStyleSheet("color: #DC2626;")
        tot_lay.addWidget(lbl_deuda)

        lbl_pagado = QLabel(f"Total Pagado: ${datos['total_pagado']:,.0f}")
        lbl_pagado.setFont(make_font(FONTS['body']))
        lbl_pagado.setStyleSheet("color: #059669;")
        tot_lay.addWidget(lbl_pagado)

        lbl_cant = QLabel(f"Facturas Pendientes: {datos['cantidad_facturas']}")
        lbl_cant.setFont(make_font(FONTS['body']))
        tot_lay.addWidget(lbl_cant)

        layout.addWidget(totales_group)

        # Tabla de facturas
        fact_group = QGroupBox("Facturas Pendientes")
        fact_group.setFont(make_font(FONTS['body_bold']))
        fact_lay = QVBoxLayout(fact_group)

        columnas = ['Factura', 'Fecha', 'Total', 'Pagado', 'Saldo', 'Estado', 'Días']
        anchos = [100, 100, 100, 100, 100, 80, 60]

        tree = QTableWidget()
        tree.setColumnCount(len(columnas))
        tree.setHorizontalHeaderLabels(columnas)
        tree.setAlternatingRowColors(True)
        tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        tree.setSelectionMode(QAbstractItemView.SingleSelection)
        tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tree.verticalHeader().setVisible(False)
        for i, w in enumerate(anchos):
            tree.setColumnWidth(i, w)
        tree.horizontalHeader().setStretchLastSection(True)

        # Store id_venta per row
        id_ventas = []

        for row_idx, factura in enumerate(datos['facturas']):
            tree.insertRow(row_idx)

            estado_emoji = {
                'PENDIENTE': '⏳',
                'PARCIAL': '🟡',
                'PAGADO': '✅'
            }.get(factura['estado_pago'], '')

            valores = [
                factura['numero_factura'],
                factura['fecha'][:10] if factura['fecha'] else '',
                f"${factura['total']:,.0f}",
                f"${factura['monto_pagado']:,.0f}",
                f"${factura['saldo_pendiente']:,.0f}",
                f"{estado_emoji} {factura['estado_pago']}",
                f"{factura['dias_vencido']} días",
            ]

            if factura['dias_vencido'] > 60:
                bg = QColor('#fee2e2'); fg = QColor('#991b1b')
            elif factura['dias_vencido'] > 30:
                bg = QColor('#fef3c7'); fg = QColor('#92400e')
            else:
                bg = QColor('white'); fg = QColor('black')

            for col, val in enumerate(valores):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignCenter)
                item.setBackground(bg)
                item.setForeground(fg)
                tree.setItem(row_idx, col, item)

            id_ventas.append(factura['id'])

        fact_lay.addWidget(tree)
        layout.addWidget(fact_group, 1)

        # Botones
        btn_layout = QHBoxLayout()

        def registrar_abono():
            sel_row = tree.currentRow()
            if sel_row < 0:
                QMessageBox.warning(ventana, "Advertencia", "Seleccione una factura")
                return
            id_venta = id_ventas[sel_row]
            numero_factura = tree.item(sel_row, 0).text()
            total = float(tree.item(sel_row, 2).text().replace('$', '').replace(',', ''))
            saldo = float(tree.item(sel_row, 4).text().replace('$', '').replace(',', ''))
            self._abrir_modal_abono(id_venta, numero_factura, total, saldo, ventana)

        btn_cobro = QPushButton("💰 Registrar Cobro")
        btn_cobro.setFont(make_font(FONTS['body']))
        btn_cobro.setCursor(QCursor(Qt.PointingHandCursor))
        btn_cobro.setStyleSheet(
            "QPushButton { background: #059669; color: white; border: none; "
            "border-radius: 6px; padding: 8px 15px; }"
            "QPushButton:hover { background: #047857; }"
        )
        btn_cobro.clicked.connect(registrar_abono)
        btn_layout.addWidget(btn_cobro)

        btn_layout.addStretch()

        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setFont(make_font(FONTS['body']))
        btn_cerrar.setCursor(QCursor(Qt.PointingHandCursor))
        btn_cerrar.setStyleSheet(
            "QPushButton { background: #6B7280; color: white; border: none; "
            "border-radius: 6px; padding: 8px 15px; }"
            "QPushButton:hover { background: #4B5563; }"
        )
        btn_cerrar.clicked.connect(ventana.accept)
        btn_layout.addWidget(btn_cerrar)

        layout.addLayout(btn_layout)
        ventana.exec()

    def _abrir_modal_abono(self, id_venta, numero_factura, total, saldo, parent_window):
        """Abre modal para registrar abono/cobro"""
        if not self.abonos_repo:
            QMessageBox.warning(self, "Advertencia",
                                "Repositorio de abonos no disponible")
            return

        try:
            ventana_abono = QDialog(parent_window)
            ventana_abono.setWindowTitle("Registrar Cobro a Factura")
            ventana_abono.resize(600, 500)
            ventana_abono.setModal(True)
            main_lay = QVBoxLayout(ventana_abono)

            # Info de factura
            info_group = QGroupBox("Información de Factura")
            info_group.setFont(make_font(FONTS['body_bold']))
            info_lay = QVBoxLayout(info_group)
            lbl_fact = QLabel(f"Factura: {numero_factura}")
            lbl_fact.setFont(make_font(FONTS['body']))
            info_lay.addWidget(lbl_fact)
            lbl_total = QLabel(f"Total: ${total:,.0f}")
            lbl_total.setFont(make_font(FONTS['body']))
            info_lay.addWidget(lbl_total)

            saldo_actual = [saldo]

            saldo_label = QLabel(f"Saldo Pendiente: ${saldo_actual[0]:,.0f}")
            saldo_label.setFont(QFont('Segoe UI', 12, QFont.Bold))
            saldo_label.setStyleSheet("color: #DC2626;")
            info_lay.addWidget(saldo_label)
            main_lay.addWidget(info_group)

            # Formulario
            form_group = QGroupBox("Datos del Cobro")
            form_group.setFont(make_font(FONTS['body_bold']))
            form_grid = QGridLayout(form_group)

            # Monto
            form_grid.addWidget(QLabel("Monto Cobrado:"), 0, 0)
            monto_input = QLineEdit()
            monto_input.setFont(make_font(FONTS['body']))
            monto_input.setPlaceholderText("0")
            form_grid.addWidget(monto_input, 0, 1)

            btn_pagar_todo = QPushButton("Pagar Todo")
            btn_pagar_todo.setFont(make_font(FONTS['small']))
            btn_pagar_todo.setStyleSheet(
                "QPushButton { background: #10B981; color: white; border: none; "
                "border-radius: 4px; padding: 4px 10px; }"
                "QPushButton:hover { background: #059669; }"
            )
            btn_pagar_todo.clicked.connect(
                lambda: monto_input.setText(str(int(saldo_actual[0]))))
            form_grid.addWidget(btn_pagar_todo, 0, 2)

            # Tipo de pago
            form_grid.addWidget(QLabel("Tipo de Pago:"), 1, 0)
            tipo_combo = QComboBox()
            tipo_combo.setFont(make_font(FONTS['body']))
            tipo_combo.addItems([
                "Efectivo", "Transferencia", "Cheque",
                "Tarjeta Débito", "Tarjeta Crédito", "Otro"
            ])
            form_grid.addWidget(tipo_combo, 1, 1)

            # Comprobante
            form_grid.addWidget(QLabel("Nº Comprobante:"), 2, 0)
            comprobante_input = QLineEdit()
            comprobante_input.setFont(make_font(FONTS['body']))
            form_grid.addWidget(comprobante_input, 2, 1)

            # Historial
            hist_group = QGroupBox("Historial de Cobros")
            hist_group.setFont(make_font(FONTS['small']))
            hist_lay = QVBoxLayout(hist_group)

            abonos_previos = self.abonos_repo.obtener_abonos_factura(id_venta)
            if abonos_previos:
                for abono in abonos_previos[:3]:
                    texto = (f"• ${abono['monto_abono']:,.0f} - "
                             f"{abono['tipo_pago']} ({abono['fecha_abono'][:10]})")
                    lbl = QLabel(texto)
                    lbl.setFont(make_font(FONTS['small']))
                    lbl.setStyleSheet("color: #6B7280;")
                    hist_lay.addWidget(lbl)
            else:
                lbl = QLabel("No hay cobros registrados aún")
                lbl.setFont(make_font(FONTS['small']))
                lbl.setStyleSheet("color: #9CA3AF;")
                hist_lay.addWidget(lbl)

            form_grid.addWidget(hist_group, 3, 0, 1, 3)
            main_lay.addWidget(form_group, 1)

            def limpiar_campos():
                monto_input.clear()
                comprobante_input.clear()
                monto_input.setFocus()

            def guardar_abono():
                try:
                    monto = float(monto_input.text().strip())

                    if monto <= 0:
                        QMessageBox.warning(ventana_abono, "Advertencia",
                                            "El monto debe ser mayor a cero")
                        return

                    if monto > saldo_actual[0]:
                        QMessageBox.warning(
                            ventana_abono, "Advertencia",
                            f"El monto no puede exceder el saldo pendiente "
                            f"(${saldo_actual[0]:,.0f})")
                        return

                    abono = AbonoVenta(
                        id_venta=id_venta,
                        monto_abono=monto,
                        fecha_abono=datetime.now().strftime('%Y-%m-%d'),
                        tipo_pago=tipo_combo.currentText(),
                        numero_comprobante=comprobante_input.text().strip() or None,
                        usuario=(self.auth.usuario_actual.username
                                 if self.auth.usuario_actual else "Sistema"),
                        observaciones=None
                    )

                    if self.abonos_repo:
                        self.abonos_repo.crear_abono(abono)
                        saldo_actual[0] -= monto

                        QMessageBox.information(
                            ventana_abono, "Éxito",
                            f"Cobro de ${monto:,.0f} registrado correctamente\n"
                            f"Nuevo saldo pendiente: ${saldo_actual[0]:,.0f}")

                        limpiar_campos()
                        self.cargar_clientes()

                        if saldo_actual[0] <= 0:
                            ventana_abono.accept()
                            parent_window.accept()
                        else:
                            saldo_label.setText(
                                f"Saldo Pendiente: ${saldo_actual[0]:,.0f}")
                    else:
                        QMessageBox.critical(ventana_abono, "Error",
                                             "Repositorio de abonos no disponible")
                except ValueError:
                    QMessageBox.critical(ventana_abono, "Error",
                                         "Ingrese un monto válido")

            # Botones
            btn_lay = QHBoxLayout()

            btn_guardar = QPushButton("💾 Guardar Cobro")
            btn_guardar.setFont(make_font(FONTS['body']))
            btn_guardar.setCursor(QCursor(Qt.PointingHandCursor))
            btn_guardar.setStyleSheet(
                "QPushButton { background: #059669; color: white; border: none; "
                "border-radius: 6px; padding: 10px 20px; }"
                "QPushButton:hover { background: #047857; }"
            )
            btn_guardar.clicked.connect(guardar_abono)
            btn_lay.addWidget(btn_guardar)

            btn_limpiar = QPushButton("🗑️ Limpiar")
            btn_limpiar.setFont(make_font(FONTS['body']))
            btn_limpiar.setCursor(QCursor(Qt.PointingHandCursor))
            btn_limpiar.setStyleSheet(
                "QPushButton { background: #6B7280; color: white; border: none; "
                "border-radius: 6px; padding: 10px 20px; }"
                "QPushButton:hover { background: #4B5563; }"
            )
            btn_limpiar.clicked.connect(limpiar_campos)
            btn_lay.addWidget(btn_limpiar)

            btn_lay.addStretch()

            btn_cancelar = QPushButton("Cancelar")
            btn_cancelar.setFont(make_font(FONTS['body']))
            btn_cancelar.setCursor(QCursor(Qt.PointingHandCursor))
            btn_cancelar.setStyleSheet(
                "QPushButton { background: #DC2626; color: white; border: none; "
                "border-radius: 6px; padding: 10px 20px; }"
                "QPushButton:hover { background: #B91C1C; }"
            )
            btn_cancelar.clicked.connect(ventana_abono.reject)
            btn_lay.addWidget(btn_cancelar)

            main_lay.addLayout(btn_lay)
            ventana_abono.exec()

        except Exception as e:
            QMessageBox.critical(self, "Error",
                                 f"Error al abrir modal de abono: {e}")


class FormularioCliente(QDialog):
    """Formulario para crear/editar clientes"""

    def __init__(self, parent, clientes_repo, auth_manager,
                 cliente=None, callback=None):
        super().__init__(parent)
        self.clientes_repo = clientes_repo
        self.auth = auth_manager
        self.cliente = cliente
        self.callback = callback

        self.setWindowTitle("Nuevo Cliente" if not cliente else "Editar Cliente")
        self.resize(600, 700)
        self.setModal(True)

        self.crear_formulario()

        if cliente:
            self.cargar_datos()

        from ui.widgets import hacer_dialogo_responsivo
        hacer_dialogo_responsivo(self, 600, 700)
        self.exec()

    def crear_formulario(self):
        """Crea el formulario"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(10)

        # Título
        titulo = "Editar Cliente" if self.cliente else "Nuevo Cliente"
        lbl_titulo = QLabel(titulo)
        lbl_titulo.setFont(make_font(FONTS['heading']))
        lbl_titulo.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(lbl_titulo)

        # Scroll area for form
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        form_widget = QWidget()
        campos_layout = QGridLayout(form_widget)
        campos_layout.setSpacing(8)

        row = 0

        # Tipo de documento
        self.crear_campo(campos_layout, "Tipo de Documento:", row)
        self.tipo_doc_combo = QComboBox()
        self.tipo_doc_combo.setFont(make_font(FONTS['body']))
        self.tipo_doc_combo.addItems(['CC', 'NIT', 'CE', 'PAS'])
        campos_layout.addWidget(self.tipo_doc_combo, row, 1)
        row += 1

        # Número de documento
        self.crear_campo(campos_layout, "Número de Documento:*", row)
        self.documento_input = QLineEdit()
        self.documento_input.setFont(make_font(FONTS['body']))
        campos_layout.addWidget(self.documento_input, row, 1)
        row += 1

        # Nombre
        self.crear_campo(campos_layout, "Nombre Completo:*", row)
        self.nombre_input = QLineEdit()
        self.nombre_input.setFont(make_font(FONTS['body']))
        campos_layout.addWidget(self.nombre_input, row, 1)
        row += 1

        # Teléfono
        self.crear_campo(campos_layout, "Teléfono:", row)
        self.telefono_input = QLineEdit()
        self.telefono_input.setFont(make_font(FONTS['body']))
        campos_layout.addWidget(self.telefono_input, row, 1)
        row += 1

        # Email
        self.crear_campo(campos_layout, "Email:", row)
        self.email_input = QLineEdit()
        self.email_input.setFont(make_font(FONTS['body']))
        campos_layout.addWidget(self.email_input, row, 1)
        row += 1

        # Dirección
        self.crear_campo(campos_layout, "Dirección:", row)
        self.direccion_input = QLineEdit()
        self.direccion_input.setFont(make_font(FONTS['body']))
        campos_layout.addWidget(self.direccion_input, row, 1)
        row += 1

        # Ciudad
        self.crear_campo(campos_layout, "Ciudad:", row)
        self.ciudad_input = QLineEdit()
        self.ciudad_input.setFont(make_font(FONTS['body']))
        campos_layout.addWidget(self.ciudad_input, row, 1)
        row += 1

        # Límite de crédito
        self.crear_campo(campos_layout, "Límite de Crédito:", row)
        self.limite_input = QLineEdit("0")
        self.limite_input.setFont(make_font(FONTS['body']))
        campos_layout.addWidget(self.limite_input, row, 1)
        row += 1

        # Clasificación
        self.crear_campo(campos_layout, "Clasificación:", row)
        self.clasificacion_combo = QComboBox()
        self.clasificacion_combo.setFont(make_font(FONTS['body']))
        self.clasificacion_combo.addItems(['A', 'B', 'C'])
        self.clasificacion_combo.setCurrentText('C')
        campos_layout.addWidget(self.clasificacion_combo, row, 1)
        row += 1

        # Descuento
        self.crear_campo(campos_layout, "Descuento (%):", row)
        self.descuento_input = QLineEdit("0")
        self.descuento_input.setFont(make_font(FONTS['body']))
        campos_layout.addWidget(self.descuento_input, row, 1)
        row += 1

        # Activo
        self.activo_check = QCheckBox("Cliente Activo")
        self.activo_check.setFont(make_font(FONTS['body']))
        self.activo_check.setChecked(True)
        campos_layout.addWidget(self.activo_check, row, 1)

        campos_layout.setColumnStretch(1, 1)

        scroll.setWidget(form_widget)
        main_layout.addWidget(scroll, 1)

        # Botones
        btn_layout = QHBoxLayout()

        btn_guardar = QPushButton(f"{ICONS['guardar']} Guardar")
        btn_guardar.setFont(make_font(FONTS['body_bold']))
        btn_guardar.setCursor(QCursor(Qt.PointingHandCursor))
        btn_guardar.setMinimumHeight(42)
        btn_guardar.setStyleSheet(button_qss('success'))
        btn_guardar.clicked.connect(self.guardar)
        btn_layout.addWidget(btn_guardar)

        btn_cancelar = QPushButton(f"{ICONS['cancelar']} Cancelar")
        btn_cancelar.setFont(make_font(FONTS['body']))
        btn_cancelar.setCursor(QCursor(Qt.PointingHandCursor))
        btn_cancelar.setMinimumHeight(42)
        btn_cancelar.setStyleSheet(button_qss('ghost'))
        btn_cancelar.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancelar)

        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)

    def crear_campo(self, layout, texto, fila):
        """Crea una etiqueta para un campo"""
        lbl = QLabel(texto)
        lbl.setFont(make_font(FONTS['body']))
        lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(lbl, fila, 0)

    def cargar_datos(self):
        """Carga los datos del cliente en el formulario"""
        if self.cliente:
            self.tipo_doc_combo.setCurrentText(self.cliente.tipo_documento)
            self.documento_input.setText(self.cliente.numero_documento)
            self.nombre_input.setText(self.cliente.nombre)
            self.telefono_input.setText(self.cliente.telefono or '')
            self.email_input.setText(self.cliente.email or '')
            self.direccion_input.setText(self.cliente.direccion or '')
            self.ciudad_input.setText(self.cliente.ciudad or '')
            self.limite_input.setText(str(self.cliente.limite_credito))
            self.clasificacion_combo.setCurrentText(self.cliente.clasificacion)
            self.descuento_input.setText(str(self.cliente.descuento_default))
            self.activo_check.setChecked(self.cliente.activo)

    def guardar(self):
        """Guarda el cliente"""
        if not self.documento_input.text().strip():
            QMessageBox.warning(self, "Advertencia",
                                "El número de documento es obligatorio")
            return

        if not self.nombre_input.text().strip():
            QMessageBox.warning(self, "Advertencia",
                                "El nombre es obligatorio")
            return

        try:
            limite = float(self.limite_input.text() or 0)
            descuento = float(self.descuento_input.text() or 0)
        except ValueError:
            QMessageBox.critical(self, "Error",
                                 "Verifique los valores numéricos")
            return

        if self.cliente:
            self.cliente.tipo_documento = self.tipo_doc_combo.currentText()
            self.cliente.numero_documento = self.documento_input.text().strip()
            self.cliente.nombre = self.nombre_input.text().strip()
            self.cliente.telefono = self.telefono_input.text().strip() or None
            self.cliente.email = self.email_input.text().strip() or None
            self.cliente.direccion = self.direccion_input.text().strip() or None
            self.cliente.ciudad = self.ciudad_input.text().strip() or None
            self.cliente.limite_credito = limite
            self.cliente.clasificacion = self.clasificacion_combo.currentText()
            self.cliente.descuento_default = descuento
            self.cliente.activo = self.activo_check.isChecked()

            exito, mensaje = self.clientes_repo.actualizar_cliente(self.cliente)
        else:
            nuevo_cliente = Cliente(
                tipo_documento=self.tipo_doc_combo.currentText(),
                numero_documento=self.documento_input.text().strip(),
                nombre=self.nombre_input.text().strip(),
                telefono=self.telefono_input.text().strip() or None,
                email=self.email_input.text().strip() or None,
                direccion=self.direccion_input.text().strip() or None,
                ciudad=self.ciudad_input.text().strip() or None,
                limite_credito=limite,
                clasificacion=self.clasificacion_combo.currentText(),
                descuento_default=descuento,
                activo=self.activo_check.isChecked()
            )
            exito, mensaje, _ = self.clientes_repo.crear_cliente(nuevo_cliente)

        if exito:
            QMessageBox.information(self, "Éxito", mensaje)
            if self.callback:
                self.callback()
            self.accept()
        else:
            QMessageBox.critical(self, "Error", mensaje)

