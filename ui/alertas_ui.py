# -*- coding: utf-8 -*-
"""
Interfaz de Usuario para Gestión de Alertas (PySide6)
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QRadioButton, QButtonGroup, QMessageBox, QDialog,
    QTextEdit
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from datetime import datetime
from ui_config import COLORS, FONTS, ICONS, make_font


class AlertasUI(QWidget):
    """Interfaz para visualización y gestión de alertas"""

    def __init__(self, parent_frame, alertas_service):
        super().__init__(parent_frame)
        self.alertas_service = alertas_service
        self.filtro_actual = 'TODAS'

        self.crear_interfaz()
        self.cargar_alertas()

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

        title = QLabel(f"{ICONS['alertas']} Centro de Alertas")
        title.setFont(make_font(FONTS['large']))
        title.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent;")
        header.addWidget(title)
        header.addStretch()

        # Botones
        btn_marcar = QPushButton("✓  Marcar Todas como Leídas")
        btn_marcar.setFont(make_font(FONTS['body']))
        btn_marcar.setCursor(Qt.PointingHandCursor)
        btn_marcar.setMinimumHeight(38)
        btn_marcar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['success']}; color: white; border: none; "
            f"border-radius: 9px; padding: 9px 16px; font-weight: 500; }}"
            f"QPushButton:hover {{ background: {COLORS['success_dark']}; }}"
        )
        btn_marcar.clicked.connect(self.marcar_todas_leidas)
        header.addWidget(btn_marcar)

        btn_actualizar = QPushButton(f"{ICONS['actualizar']} Actualizar")
        btn_actualizar.setFont(make_font(FONTS['body']))
        btn_actualizar.setCursor(Qt.PointingHandCursor)
        btn_actualizar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['info']}; color: white; border: none; "
            f"border-radius: 6px; padding: 8px 15px; }}"
            f"QPushButton:hover {{ background: #0891b2; }}"
        )
        btn_actualizar.clicked.connect(self.cargar_alertas)
        header.addWidget(btn_actualizar)

        frame_layout.addLayout(header)

        # Filtros
        filtros_layout = QHBoxLayout()
        lbl_mostrar = QLabel("Mostrar:")
        lbl_mostrar.setFont(make_font(FONTS['body']))
        lbl_mostrar.setStyleSheet(f"background: transparent; color: {COLORS['text_primary']};")
        filtros_layout.addWidget(lbl_mostrar)

        self.filtro_group = QButtonGroup(self)
        filtros = ['TODAS', 'NO LEÍDAS', 'CRÍTICAS', 'ALTAS', 'MEDIAS']
        for filtro in filtros:
            rb = QRadioButton(filtro)
            rb.setFont(make_font(FONTS['body']))
            rb.setStyleSheet("background: transparent;")
            if filtro == 'TODAS':
                rb.setChecked(True)
            rb.toggled.connect(lambda checked, f=filtro: self._on_filtro_changed(f, checked))
            self.filtro_group.addButton(rb)
            filtros_layout.addWidget(rb)

        filtros_layout.addStretch()
        frame_layout.addLayout(filtros_layout)

        # Contador
        self.contador_label = QLabel("")
        self.contador_label.setFont(make_font(FONTS['body_bold']))
        self.contador_label.setStyleSheet(f"color: {COLORS['primary']}; background: transparent;")
        frame_layout.addWidget(self.contador_label)

        # Lista de alertas con scroll
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("background: white; border: 1px solid #d1d5db; border-radius: 8px;")

        self.alertas_container = QWidget()
        self.alertas_layout = QVBoxLayout(self.alertas_container)
        self.alertas_layout.setContentsMargins(0, 0, 0, 0)
        self.alertas_layout.setSpacing(0)
        self.alertas_layout.setAlignment(Qt.AlignTop)

        scroll_area.setWidget(self.alertas_container)
        frame_layout.addWidget(scroll_area, 1)

        main_layout.addWidget(main_frame)

    def _on_filtro_changed(self, filtro, checked):
        """Maneja cambio de filtro de radio button"""
        if checked:
            self.filtro_actual = filtro
            self.cargar_alertas()

    def cargar_alertas(self):
        """Carga y muestra las alertas"""
        # Limpiar alertas anteriores
        while self.alertas_layout.count():
            child = self.alertas_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        filtro = self.filtro_actual

        if filtro == 'NO LEÍDAS':
            alertas = self.alertas_service.obtener_alertas(solo_no_leidas=True)
        else:
            alertas = self.alertas_service.obtener_alertas(solo_no_leidas=False)
            if filtro in ['CRÍTICAS', 'ALTAS', 'MEDIAS']:
                prioridad_map = {'CRÍTICAS': 'CRITICA', 'ALTAS': 'ALTA', 'MEDIAS': 'MEDIA'}
                alertas = [a for a in alertas if a.prioridad == prioridad_map[filtro]]

        # Actualizar contador
        total = len(alertas)
        no_leidas = len([a for a in alertas if not a.leida])
        self.contador_label.setText(
            f"Total: {total} alertas    ·    Sin leer: {no_leidas}"
        )

        # Mostrar alertas
        if not alertas:
            lbl = QLabel("✓  No hay alertas")
            lbl.setFont(make_font(FONTS['heading']))
            lbl.setStyleSheet(f"color: {COLORS['text_light']}; background: transparent;")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setContentsMargins(0, 50, 0, 50)
            self.alertas_layout.addWidget(lbl)
        else:
            for alerta in alertas:
                self.crear_tarjeta_alerta(alerta)

    def crear_tarjeta_alerta(self, alerta):
        """Crea una tarjeta visual para una alerta"""
        colores = {
            'CRITICA': COLORS['danger'],
            'ALTA': COLORS['warning'],
            'MEDIA': COLORS['info'],
            'BAJA': COLORS['secondary']
        }
        color = colores.get(alerta.prioridad, COLORS['secondary'])
        bg_color = 'white' if alerta.leida else '#f0f9ff'

        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: {bg_color}; border: 1px solid #e5e7eb; "
            f"border-top: 5px solid {color}; margin: 5px 10px; }}"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(15, 10, 15, 10)
        card_layout.setSpacing(5)

        # Header de la alerta
        header_layout = QHBoxLayout()

        iconos_tipo = {
            'STOCK_BAJO': '📦',
            'STOCK_CRITICO': '[AVISO]',
            'VENCIMIENTO': '📅',
            'COBRO': '💰',
            'SISTEMA': 'ℹ️'
        }
        icono = iconos_tipo.get(alerta.tipo, '[ALERTA]')

        titulo_lbl = QLabel(f"{icono} {alerta.titulo}")
        titulo_lbl.setFont(make_font(FONTS['body_bold']))
        titulo_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent; border: none;")
        header_layout.addWidget(titulo_lbl)

        header_layout.addStretch()

        try:
            fecha = datetime.fromisoformat(alerta.fecha_creacion).strftime('%d/%m/%Y %H:%M')
        except Exception:
            fecha = alerta.fecha_creacion

        fecha_lbl = QLabel(fecha)
        fecha_lbl.setFont(make_font(FONTS['small']))
        fecha_lbl.setStyleSheet(f"color: {COLORS['text_light']}; background: transparent; border: none;")
        header_layout.addWidget(fecha_lbl)

        card_layout.addLayout(header_layout)

        # Mensaje
        msg_lbl = QLabel(alerta.mensaje)
        msg_lbl.setFont(make_font(FONTS['body']))
        msg_lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent; border: none;")
        msg_lbl.setWordWrap(True)
        card_layout.addWidget(msg_lbl)

        # Acciones
        acciones_layout = QHBoxLayout()

        if not alerta.leida:
            btn_leida = QPushButton("✓  Marcar como leída")
            btn_leida.setFont(make_font(FONTS['small']))
            btn_leida.setCursor(Qt.PointingHandCursor)
            btn_leida.setStyleSheet(
                f"QPushButton {{ background: {COLORS['success']}; color: white; border: none; "
                f"border-radius: 7px; padding: 4px 12px; font-weight: 500; }}"
                f"QPushButton:hover {{ background: {COLORS['success_dark']}; }}"
            )
            btn_leida.clicked.connect(lambda checked, aid=alerta.id: self.marcar_leida(aid))
            acciones_layout.addWidget(btn_leida)

        acciones_layout.addStretch()

        badge = QLabel(f"Prioridad: {alerta.prioridad}")
        badge.setFont(make_font(FONTS['small']))
        badge.setStyleSheet(
            f"background: {color}; color: white; border: none; "
            f"border-radius: 3px; padding: 2px 8px;"
        )
        acciones_layout.addWidget(badge)

        card_layout.addLayout(acciones_layout)
        self.alertas_layout.addWidget(card)

    def marcar_leida(self, alerta_id):
        """Marca una alerta como leída"""
        exito = self.alertas_service.marcar_leida(alerta_id)
        if exito:
            self.cargar_alertas()

    def marcar_todas_leidas(self):
        """Marca todas las alertas como leídas"""
        respuesta = QMessageBox.question(
            self, "Confirmar",
            "¿Desea marcar todas las alertas como leídas?",
            QMessageBox.Yes | QMessageBox.No
        )

        if respuesta == QMessageBox.Yes:
            exito = self.alertas_service.marcar_todas_leidas()
            if exito:
                QMessageBox.information(self, "Éxito", "Todas las alertas fueron marcadas como leídas")
                self.cargar_alertas()


class VentanaAlertasPopup(QDialog):
    """Ventana emergente para mostrar alertas importantes"""

    def __init__(self, parent, alertas_service):
        super().__init__(parent)
        self.alertas_service = alertas_service

        # Obtener alertas críticas no leídas
        alertas = alertas_service.obtener_alertas(solo_no_leidas=True)
        alertas_criticas = [a for a in alertas if a.prioridad in ['CRITICA', 'ALTA']]

        if not alertas_criticas:
            # No mostrar ventana si no hay alertas
            self.close()
            return

        self.setWindowTitle("[AVISO] Alertas Importantes")
        self.setFixedSize(500, 400)
        self.setModal(True)

        self.crear_interfaz(alertas_criticas)

    def crear_interfaz(self, alertas):
        """Crea la interfaz del popup"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(60)
        header.setStyleSheet(f"background: {COLORS['danger']};")
        header_layout = QHBoxLayout(header)

        title = QLabel("[AVISO] Alertas Importantes")
        title.setFont(make_font(FONTS['large']))
        title.setStyleSheet("color: white; background: transparent;")
        title.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(title)

        main_layout.addWidget(header)

        # Contenido
        content = QFrame()
        content.setStyleSheet("background: white;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 20, 20, 20)

        info = QLabel(f"Tiene {len(alertas)} alerta(s) que requieren atención:")
        info.setFont(make_font(FONTS['body']))
        info.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent;")
        content_layout.addWidget(info)

        # Lista de alertas
        text_widget = QTextEdit()
        text_widget.setFont(make_font(FONTS['body']))
        text_widget.setReadOnly(True)
        text_widget.setStyleSheet("background: #fff8f8; border: none; padding: 10px;")

        html_parts = []
        for i, alerta in enumerate(alertas, 1):
            html_parts.append(
                f'<p><b style="color:{COLORS["danger"]}">{i}. </b>'
                f'<b style="color:{COLORS["text_primary"]}">{alerta.titulo}</b><br/>'
                f'<span style="color:{COLORS["text_secondary"]}">&nbsp;&nbsp;&nbsp;{alerta.mensaje}</span></p>'
            )
        text_widget.setHtml(''.join(html_parts))
        content_layout.addWidget(text_widget, 1)

        main_layout.addWidget(content, 1)

        # Botones
        btn_frame = QFrame()
        btn_frame.setStyleSheet("background: white;")
        btn_layout = QHBoxLayout(btn_frame)
        btn_layout.setContentsMargins(20, 10, 20, 20)

        btn_layout.addStretch()

        btn_marcar = QPushButton("Marcar como leídas")
        btn_marcar.setFont(make_font(FONTS['body']))
        btn_marcar.setCursor(Qt.PointingHandCursor)
        btn_marcar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['success']}; color: white; border: none; "
            f"border-radius: 6px; padding: 10px 20px; }}"
            f"QPushButton:hover {{ background: {COLORS['success_dark']}; }}"
        )
        btn_marcar.clicked.connect(lambda: self.marcar_y_cerrar(alertas))
        btn_layout.addWidget(btn_marcar)

        btn_ok = QPushButton("Entendido")
        btn_ok.setFont(make_font(FONTS['body_bold']))
        btn_ok.setCursor(Qt.PointingHandCursor)
        btn_ok.setStyleSheet(
            f"QPushButton {{ background: {COLORS['primary']}; color: white; border: none; "
            f"border-radius: 6px; padding: 10px 30px; }}"
            f"QPushButton:hover {{ background: {COLORS['primary_dark']}; }}"
        )
        btn_ok.clicked.connect(self.accept)
        btn_layout.addWidget(btn_ok)

        main_layout.addWidget(btn_frame)

    def marcar_y_cerrar(self, alertas):
        """Marca las alertas como leídas y cierra la ventana"""
        for alerta in alertas:
            self.alertas_service.marcar_como_leida(alerta.id)
        QMessageBox.information(self, "Éxito", "Alertas marcadas como leídas")
        self.accept()