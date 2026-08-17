# -*- coding: utf-8 -*-
"""
Interfaz de Usuario para Gestión de Caja (PySide6)
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QDialog,
    QMessageBox, QFrame, QTextEdit, QGridLayout, QGroupBox,
    QRadioButton, QButtonGroup, QAbstractItemView, QSizePolicy, QPlainTextEdit
)
from PySide6.QtCore import Qt, Signal, QTimer, QTime
from PySide6.QtGui import QFont, QColor

from datetime import datetime
from decimal import Decimal
from services.caja_service import is_cash_admin, money
from ui_config import COLORS, FONTS, ICONS, make_font


class CajaUI(QWidget):
    """Interfaz para gestión de caja"""

    def __init__(self, parent_frame, caja_service, auth_manager, abonos_repo=None, compras_repo=None):
        super().__init__(parent_frame)
        self.parent_widget = parent_frame
        self.caja_service = caja_service
        self.auth = auth_manager
        self.abonos_repo = abonos_repo
        self.compras_repo = compras_repo

        self.crear_interfaz()
        self.verificar_estado_caja()

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
        title = QLabel(f"{ICONS['caja']} Gestión de Caja")
        title.setFont(make_font(FONTS['large']))
        title.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent;")
        header.addWidget(title)
        header.addStretch()
        frame_layout.addLayout(header)

        # Estado de la caja
        self.estado_frame = QFrame()
        self.estado_frame.setStyleSheet("background: white; border: 1px solid #d1d5db; border-radius: 8px;")
        estado_layout = QVBoxLayout(self.estado_frame)
        estado_layout.setContentsMargins(20, 20, 20, 20)
        estado_layout.setAlignment(Qt.AlignCenter)

        self.estado_label = QLabel("")
        self.estado_label.setFont(make_font(FONTS['heading']))
        self.estado_label.setAlignment(Qt.AlignCenter)
        self.estado_label.setStyleSheet("background: transparent; border: none;")
        estado_layout.addWidget(self.estado_label)

        self.info_label = QLabel("")
        self.info_label.setFont(make_font(FONTS['body']))
        self.info_label.setAlignment(Qt.AlignCenter)
        self.info_label.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent; border: none;")
        estado_layout.addWidget(self.info_label)

        frame_layout.addWidget(self.estado_frame)

        # Botones de acción
        self.botones_frame = QFrame()
        self.botones_frame.setStyleSheet("background: transparent;")
        self.botones_layout = QHBoxLayout(self.botones_frame)
        self.botones_layout.setAlignment(Qt.AlignCenter)
        self.botones_layout.setSpacing(10)

        self.btn_abrir = QPushButton("\U0001f513 Abrir Caja")
        self.btn_abrir.setFont(make_font(FONTS['body_bold']))
        self.btn_abrir.setCursor(Qt.PointingHandCursor)
        self.btn_abrir.setStyleSheet(
            f"QPushButton {{ background: {COLORS['success']}; color: white; border: none; "
            f"border-radius: 6px; padding: 15px 30px; }}"
            f"QPushButton:hover {{ background: {COLORS['success_dark']}; }}"
        )
        self.btn_abrir.clicked.connect(self.abrir_caja)

        self.btn_ingreso = QPushButton("Ingreso / refuerzo")
        self.btn_ingreso.setFont(make_font(FONTS['body_bold']))
        self.btn_ingreso.setCursor(Qt.PointingHandCursor)
        self.btn_ingreso.setStyleSheet(
            f"QPushButton {{ background: {COLORS['primary']}; color: white; border: none; "
            f"border-radius: 9px; padding: 14px 28px; font-weight: 500; }}"
            f"QPushButton:hover {{ background: {COLORS['primary_dark']}; }}"
        )
        self.btn_ingreso.clicked.connect(self.registrar_ingreso)

        self.btn_cerrar = QPushButton("\U0001f512 Cerrar Caja")
        self.btn_cerrar.setFont(make_font(FONTS['body_bold']))
        self.btn_cerrar.setCursor(Qt.PointingHandCursor)
        self.btn_cerrar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['danger']}; color: white; border: none; "
            f"border-radius: 9px; padding: 14px 28px; font-weight: 500; }}"
            f"QPushButton:hover {{ background: {COLORS['danger_dark']}; }}"
        )
        self.btn_cerrar.clicked.connect(self.cerrar_caja)
        self.btn_cerrar.setAutoDefault(False)
        self.btn_cerrar.setDefault(False)

        self.btn_egreso = QPushButton("\U0001f4b8 Registrar Egreso")
        self.btn_egreso.setFont(make_font(FONTS['body_bold']))
        self.btn_egreso.setCursor(Qt.PointingHandCursor)
        self.btn_egreso.setStyleSheet(
            f"QPushButton {{ background: {COLORS['accent']}; color: {COLORS['on_accent']}; border: none; "
            f"border-radius: 9px; padding: 14px 28px; font-weight: 500; }}"
            f"QPushButton:hover {{ background: {COLORS['accent_hover']}; }}"
        )
        self.btn_egreso.clicked.connect(self.registrar_egreso)

        # Add buttons to layout (visibility managed in verificar_estado_caja)
        self.botones_layout.addWidget(self.btn_abrir)
        self.botones_layout.addWidget(self.btn_ingreso)
        self.botones_layout.addWidget(self.btn_egreso)
        self.botones_layout.addWidget(self.btn_cerrar)

        self.btn_reimprimir_cierre = QPushButton("Reimprimir último cierre")
        self.btn_reimprimir_cierre.setFont(make_font(FONTS['body_bold']))
        self.btn_reimprimir_cierre.setCursor(Qt.PointingHandCursor)
        self.btn_reimprimir_cierre.setDefault(False)
        self.btn_reimprimir_cierre.setAutoDefault(False)
        self.btn_reimprimir_cierre.setStyleSheet(
            f"QPushButton {{ background: {COLORS['primary']}; color: white; border: none; "
            f"border-radius: 9px; padding: 12px 22px; font-weight: 500; }}"
            f"QPushButton:hover {{ background: {COLORS['primary_dark']}; }}"
        )
        self.btn_reimprimir_cierre.clicked.connect(self.reimprimir_ultimo_cierre)
        self.botones_layout.addWidget(self.btn_reimprimir_cierre)

        # Botón para historial de pagos a proveedores
        self.btn_historial = None
        if self.abonos_repo:
            self.btn_historial = QPushButton("\U0001f4dc Historial de Pagos a Proveedores")
            self.btn_historial.setFont(make_font(FONTS['body_bold']))
            self.btn_historial.setCursor(Qt.PointingHandCursor)
            self.btn_historial.setStyleSheet(
                f"QPushButton {{ background: {COLORS['primary']}; color: white; border: none; "
                f"border-radius: 9px; padding: 12px 22px; font-weight: 500; }}"
                f"QPushButton:hover {{ background: {COLORS['primary_dark']}; }}"
            )
            self.btn_historial.clicked.connect(self.ver_historial_pagos)
            self.botones_layout.addWidget(self.btn_historial)

        frame_layout.addWidget(self.botones_frame)

        # ── Resumen del día ──────────────────────────────────────────
        self.resumen_frame = QFrame()
        self.resumen_frame.setStyleSheet(
            "background: white; border: 1px solid #d1d5db; border-radius: 12px;"
        )
        resumen_layout = QVBoxLayout(self.resumen_frame)
        resumen_layout.setContentsMargins(24, 20, 24, 20)
        resumen_layout.setSpacing(12)

        # Título + badge de cantidad de ventas
        hdr_row = QHBoxLayout()
        resumen_title = QLabel("📊 Resumen de sesión")
        resumen_title.setFont(make_font(FONTS['heading']))
        resumen_title.setStyleSheet("background: transparent; border: none;")
        hdr_row.addWidget(resumen_title)
        hdr_row.addStretch()
        self.badge_ventas = QLabel("0 ventas")
        self.badge_ventas.setFont(make_font(FONTS['body_bold']))
        self.badge_ventas.setStyleSheet(
            "background: #e0f2fe; color: #0369a1; border: none;"
            " border-radius: 12px; padding: 4px 14px;"
        )
        hdr_row.addWidget(self.badge_ventas)
        resumen_layout.addLayout(hdr_row)

        # Total grande centrado
        self.lbl_total = QLabel("$0")
        self.lbl_total.setFont(QFont('Segoe UI', 36, QFont.Bold))
        self.lbl_total.setAlignment(Qt.AlignCenter)
        self.lbl_total.setStyleSheet(
            f"color: {COLORS['primary']}; background: transparent; border: none;"
        )
        resumen_layout.addWidget(self.lbl_total)

        lbl_total_sub = QLabel("Total neto del día")
        lbl_total_sub.setFont(make_font(FONTS['body']))
        lbl_total_sub.setAlignment(Qt.AlignCenter)
        lbl_total_sub.setStyleSheet(
            f"color: {COLORS['text_secondary']}; background: transparent; border: none;"
        )
        resumen_layout.addWidget(lbl_total_sub)

        sep_h = QFrame()
        sep_h.setFrameShape(QFrame.HLine)
        sep_h.setStyleSheet("border: 1px solid #f1f5f9;")
        resumen_layout.addWidget(sep_h)

        # Cards de métodos de pago (fila horizontal)
        cards_row = QWidget()
        cards_row.setStyleSheet("background: transparent;")
        cards_layout = QHBoxLayout(cards_row)
        cards_layout.setSpacing(12)
        cards_layout.setContentsMargins(0, 0, 0, 0)

        self._card_efectivo      = self._crear_metodo_card("💵", "Efectivo",      "#10b981")
        self._card_tarjeta       = self._crear_metodo_card("💳", "Tarjeta",       "#3b82f6")
        self._card_transferencia = self._crear_metodo_card("🔄", "Transferencia", "#8b5cf6")
        self._card_otros         = self._crear_metodo_card("📌", "Otros",         "#f59e0b")

        cards_layout.addWidget(self._card_efectivo['widget'])
        cards_layout.addWidget(self._card_tarjeta['widget'])
        cards_layout.addWidget(self._card_transferencia['widget'])
        cards_layout.addWidget(self._card_otros['widget'])

        resumen_layout.addWidget(cards_row)
        frame_layout.addWidget(self.resumen_frame, 1)

        main_layout.addWidget(main_frame)

    # ------------------------------------------------------------------
    # Helper: mini-card de método de pago
    # ------------------------------------------------------------------

    def _crear_metodo_card(self, icono, nombre, color):
        """Crea una mini-card estilizada para un método de pago."""
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: #f8fafc; border-radius: 8px;"
            f" border-left: 4px solid {color};"
            f" border-top: 1px solid #e2e8f0;"
            f" border-right: 1px solid #e2e8f0;"
            f" border-bottom: 1px solid #e2e8f0; }}"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(5)

        lbl_hdr = QLabel(f"{icono}  {nombre}")
        lbl_hdr.setFont(make_font(FONTS['body_bold']))
        lbl_hdr.setStyleSheet(f"color: {color}; background: transparent; border: none;")
        lay.addWidget(lbl_hdr)

        lbl_ing = QLabel("Ingresos:  $0")
        lbl_ing.setFont(make_font(FONTS['body']))
        lbl_ing.setStyleSheet("color: #374151; background: transparent; border: none;")
        lay.addWidget(lbl_ing)

        lbl_egr = QLabel("Egresos:  $0")
        lbl_egr.setFont(make_font(FONTS['body']))
        lbl_egr.setStyleSheet("color: #ef4444; background: transparent; border: none;")
        lbl_egr.setVisible(False)
        lay.addWidget(lbl_egr)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("border: 1px solid #e2e8f0;")
        lay.addWidget(sep)

        lbl_neto = QLabel("Neto:  $0")
        lbl_neto.setFont(make_font(FONTS['body_bold']))
        lbl_neto.setStyleSheet(f"color: {color}; background: transparent; border: none;")
        lay.addWidget(lbl_neto)

        return {'widget': card, 'lbl_ing': lbl_ing, 'lbl_egr': lbl_egr, 'lbl_neto': lbl_neto}

    def _actualizar_metodo_card(self, card, ingresos, egresos):
        """Actualiza los valores de una mini-card."""
        neto = ingresos - egresos
        card['lbl_ing'].setText(f"Ingresos:  ${ingresos:,.0f}")
        if egresos > 0:
            card['lbl_egr'].setText(f"Egresos:  -${egresos:,.0f}")
            card['lbl_egr'].setVisible(True)
        else:
            card['lbl_egr'].setVisible(False)
        card['lbl_neto'].setText(f"Neto:  ${neto:,.0f}")

    def _es_admin_caja(self) -> bool:
        return is_cash_admin(getattr(self.auth, "usuario_actual", None))

    def _estacion_texto(self, caja=None) -> str:
        if caja and caja.get("station_id"):
            return str(caja["station_id"])
        return self.caja_service.estacion_actual()

    def _aplicar_visibilidad_admin(self, *, abierta: bool) -> None:
        es_admin = self._es_admin_caja()
        self.botones_frame.setVisible(es_admin)
        self.resumen_frame.setVisible(es_admin)
        self.btn_abrir.setVisible(es_admin and not abierta)
        self.btn_ingreso.setVisible(es_admin and abierta)
        self.btn_egreso.setVisible(es_admin and abierta)
        self.btn_cerrar.setVisible(es_admin and abierta)
        last = self.caja_service.obtener_ultimo_cierre_usuario() if es_admin else None
        self.btn_reimprimir_cierre.setVisible(bool(last) and es_admin)
        if self.btn_historial is not None:
            self.btn_historial.setVisible(es_admin)

    def verificar_estado_caja(self):
        """Verifica si hay una caja abierta"""
        caja_abierta = self.caja_service.obtener_caja_abierta()

        if caja_abierta:
            self.mostrar_caja_abierta(caja_abierta)
        else:
            self.mostrar_caja_cerrada()

        self.actualizar_resumen()

    def mostrar_caja_abierta(self, caja):
        """Muestra estado de caja abierta"""
        es_admin = self._es_admin_caja()
        estacion = self._estacion_texto(caja)

        self.estado_label.setText("Caja Abierta")
        self.estado_label.setStyleSheet(f"color: {COLORS['success_dark']}; background: transparent; border: none;")

        if es_admin:
            fecha_raw = caja.get("fecha_apertura") or ""
            try:
                fecha_apertura = datetime.fromisoformat(str(fecha_raw)).strftime("%d/%m/%Y %H:%M")
            except ValueError:
                fecha_apertura = str(fecha_raw)
            resumen = self.caja_service.obtener_resumen_sesion(caja)
            esperado = resumen.get("esperado", caja.get("monto_inicial") or 0)
            self.info_label.setText(
                f"Estación: {estacion}\n"
                f"Abierta el: {fecha_apertura}\n"
                f"Monto inicial: ${caja['monto_inicial']:,.0f}\n"
                f"Efectivo esperado: ${esperado:,.0f}"
            )
        else:
            self.info_label.setText(
                f"Estado: ABIERTA\n"
                f"Estación: {estacion}\n"
                "Las ventas en efectivo se registran automáticamente en la caja."
            )

        self._aplicar_visibilidad_admin(abierta=True)

    def reimprimir_ultimo_cierre(self):
        if not self._es_admin_caja():
            QMessageBox.warning(self, "Caja", "Solo un administrador puede reimprimir cierres.")
            return
        cierre = self.caja_service.obtener_ultimo_cierre_usuario()
        if not cierre:
            QMessageBox.information(self, "Caja", "No hay un cierre para reimprimir.")
            return
        from ui.imprimir_factura import imprimir_por_identidad
        identity = cierre.get("local_id") or cierre.get("id")
        imprimir_por_identidad(self, self.caja_service.db, "CASH_CLOSE", identity)

    def mostrar_caja_cerrada(self):
        """Muestra estado de caja cerrada"""
        es_admin = self._es_admin_caja()
        estacion = self._estacion_texto()

        self.estado_label.setText("Caja Cerrada")
        self.estado_label.setStyleSheet(f"color: {COLORS['danger']}; background: transparent; border: none;")

        if es_admin:
            self.info_label.setText(
                f"Estación: {estacion}\n"
                "No hay una caja abierta actualmente"
            )
        else:
            self.info_label.setText(
                f"Estado: CERRADA\n"
                f"Estación: {estacion}\n"
                "Solicite a un administrador la apertura de caja."
            )

        self._aplicar_visibilidad_admin(abierta=False)

    def actualizar_resumen(self):
        """Actualiza el resumen del día"""
        if not self._es_admin_caja():
            self.resumen_frame.setVisible(False)
            return

        caja_abierta = self.caja_service.obtener_caja_abierta()

        if not caja_abierta:
            ultimo_cierre = self.caja_service.obtener_ultimo_cierre_usuario()
            if ultimo_cierre:
                def monto(campo):
                    valor = ultimo_cierre.get(campo)
                    return float(valor) if valor is not None else 0.0

                self.badge_ventas.setText("Último cierre")
                self.lbl_total.setText(f"${monto('total_ventas'):,.0f}")
                self._actualizar_metodo_card(self._card_efectivo,      monto('ventas_efectivo'),      0)
                self._actualizar_metodo_card(self._card_tarjeta,       monto('ventas_tarjeta'),       0)
                self._actualizar_metodo_card(self._card_transferencia, monto('ventas_transferencia'), 0)
                self._actualizar_metodo_card(self._card_otros,         monto('ventas_otros'),         0)
            else:
                self.badge_ventas.setText("0 ventas")
                self.lbl_total.setText("$0")
                self._actualizar_metodo_card(self._card_efectivo,      0, 0)
                self._actualizar_metodo_card(self._card_tarjeta,       0, 0)
                self._actualizar_metodo_card(self._card_transferencia, 0, 0)
                self._actualizar_metodo_card(self._card_otros,         0, 0)
            return

        resumen = self.caja_service.obtener_resumen_dia()
        total_neto = resumen['total'] - resumen['egresos_total']

        self.badge_ventas.setText(f"{resumen['cantidad_ventas']} ventas")
        self.lbl_total.setText(f"${total_neto:,.0f}")

        self._actualizar_metodo_card(self._card_efectivo,      resumen['efectivo'],      resumen['egresos_efectivo'])
        self._actualizar_metodo_card(self._card_tarjeta,       resumen['tarjeta'],       resumen['egresos_tarjeta'])
        self._actualizar_metodo_card(self._card_transferencia, resumen['transferencia'], resumen['egresos_transferencia'])
        self._actualizar_metodo_card(self._card_otros,         resumen['otros'],         resumen['egresos_otros'])

    def abrir_caja(self):
        """Abre una nueva caja"""
        if not self._es_admin_caja():
            QMessageBox.warning(self, "Caja", "Solo un administrador puede abrir la caja.")
            return
        FormularioAperturaCaja(self, self.caja_service,
                               callback=self.verificar_estado_caja)

    def cerrar_caja(self):
        """Cierra la caja actual. Requiere acción explícita; no reabre sola."""
        if not self._es_admin_caja():
            QMessageBox.warning(self, "Caja", "Solo un administrador puede cerrar la caja.")
            return
        FormularioCierreCaja(self, self.caja_service,
                             callback=self.verificar_estado_caja)

    def registrar_egreso(self):
        """Abre el formulario para registrar un egreso"""
        if not self._es_admin_caja():
            QMessageBox.warning(self, "Caja", "Solo un administrador puede registrar egresos.")
            return
        caja_abierta = self.caja_service.obtener_caja_abierta()
        if not caja_abierta:
            QMessageBox.warning(self, "Advertencia", "Debe abrir una caja primero")
            return

        FormularioEgreso(self, self.caja_service,
                         callback=self.verificar_estado_caja)

    def registrar_ingreso(self):
        """Abre el formulario para un ingreso/refuerzo administrativo."""
        if not self._es_admin_caja():
            QMessageBox.warning(self, "Caja", "Solo un administrador puede registrar ingresos.")
            return
        caja_abierta = self.caja_service.obtener_caja_abierta()
        if not caja_abierta:
            QMessageBox.warning(self, "Advertencia", "Debe abrir una caja primero")
            return
        FormularioIngresoManual(self, self.caja_service,
                                callback=self.verificar_estado_caja)

    MONTO_INICIAL_DEFAULT = 200_000

    def ver_historial_pagos(self):
        """Muestra el historial de pagos a proveedores"""
        if not self._es_admin_caja():
            QMessageBox.warning(self, "Caja", "Solo un administrador puede consultar este historial.")
            return
        if not self.abonos_repo:
            QMessageBox.warning(self, "Advertencia", "Repositorio de abonos no disponible")
            return

        VentanaHistorialPagos(self, self.abonos_repo, self.compras_repo)


class FormularioAperturaCaja(QDialog):
    """Formulario para apertura de caja"""

    def __init__(self, parent, caja_service, callback=None):
        super().__init__(parent)
        self.caja_service = caja_service
        self.callback = callback
        self._formatting = False

        self.setWindowTitle("Abrir Caja")
        self.setFixedSize(400, 300)
        self.setModal(True)

        self.crear_formulario()
        self.exec()

    def crear_formulario(self):
        """Crea el formulario"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(10)

        title = QLabel("\U0001f513 Apertura de Caja")
        title.setFont(make_font(FONTS['heading']))
        title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title)
        main_layout.addSpacing(20)

        lbl_monto = QLabel("Monto Inicial en Efectivo:")
        lbl_monto.setFont(make_font(FONTS['body']))
        main_layout.addWidget(lbl_monto)

        self.monto_entry = QLineEdit("0")
        self.monto_entry.setFont(make_font(FONTS['large']))
        self.monto_entry.setAlignment(Qt.AlignCenter)
        self.monto_entry.textChanged.connect(self._formatear_monto)
        main_layout.addWidget(self.monto_entry)
        self.monto_entry.setFocus()

        hint = QLabel("(Billetes y monedas en la caja)")
        hint.setFont(make_font(FONTS['small']))
        hint.setStyleSheet(f"color: {COLORS['text_light']};")
        main_layout.addWidget(hint)

        main_layout.addStretch()

        # Botones
        btn_layout = QHBoxLayout()
        btn_layout.setAlignment(Qt.AlignCenter)

        btn_abrir = QPushButton("Abrir Caja")
        btn_abrir.setFont(make_font(FONTS['body_bold']))
        btn_abrir.setCursor(Qt.PointingHandCursor)
        btn_abrir.setStyleSheet(
            f"QPushButton {{ background: {COLORS['success']}; color: white; border: none; "
            f"border-radius: 6px; padding: 10px 20px; }}"
            f"QPushButton:hover {{ background: {COLORS['success_dark']}; }}"
        )
        btn_abrir.clicked.connect(self.abrir)
        btn_abrir.setAutoDefault(False)
        btn_abrir.setDefault(False)
        btn_layout.addWidget(btn_abrir)

        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setFont(make_font(FONTS['body']))
        btn_cancelar.setCursor(Qt.PointingHandCursor)
        btn_cancelar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['secondary']}; color: white; border: none; "
            f"border-radius: 6px; padding: 10px 20px; }}"
            f"QPushButton:hover {{ background: #475569; }}"
        )
        btn_cancelar.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancelar)

        main_layout.addLayout(btn_layout)

    def _formatear_monto(self, text):
        """Formatea el monto con separadores de miles mientras se escribe"""
        if self._formatting:
            return
        self._formatting = True
        raw = text.replace('.', '').replace(',', '')
        raw = ''.join(c for c in raw if c.isdigit())
        if raw:
            try:
                num = int(raw)
                formatted = f"{num:,}".replace(',', '.')
                self.monto_entry.setText(formatted)
            except ValueError:
                pass
        self._formatting = False

    def abrir(self):
        """Abre la caja - método real"""
        try:
            monto = money(self.monto_entry.text().replace('.', '').replace(',', '.'))
        except ValueError:
            QMessageBox.critical(self, "Error", "Ingrese un monto válido")
            return

        exito, mensaje = self.caja_service.abrir_caja(monto)

        if exito:
            QMessageBox.information(self, "Éxito", mensaje)
            if self.callback:
                self.callback()
            self.accept()
        else:
            QMessageBox.critical(self, "Error", mensaje)


class FormularioCierreCaja(QDialog):
    """Formulario para cierre de caja"""

    def __init__(self, parent, caja_service, callback=None):
        super().__init__(parent)
        self.caja_service = caja_service
        self.callback = callback
        self.monto_esperado = 0
        self._formatting = False

        self.setWindowTitle("Cerrar Caja")
        self.setFixedSize(520, 620)
        self.setModal(True)

        self.crear_formulario()
        self.cargar_datos()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.cargar_datos)
        self._refresh_timer.start(5000)

        from ui.widgets import hacer_dialogo_responsivo
        hacer_dialogo_responsivo(self, 520, 620)
        self.exec()

    def _fila_resumen(self, lay, label, valor, negrita=False, color=None):
        """Agrega una fila label/valor al layout dado"""
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setFont(QFont('Segoe UI', 9, QFont.Bold if negrita else QFont.Normal))
        lbl.setStyleSheet("background: transparent; border: none;"
                          + (f" color: {color};" if color else ""))
        val = QLabel(valor)
        val.setFont(QFont('Segoe UI', 9, QFont.Bold if negrita else QFont.Normal))
        val.setAlignment(Qt.AlignRight)
        val.setStyleSheet("background: transparent; border: none;"
                          + (f" color: {color};" if color else ""))
        row.addWidget(lbl)
        row.addWidget(val)
        lay.addLayout(row)
        return val  # retornar para poder actualizar después

    def _sep_line(self):
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("border: none; border-top: 1px solid #e2e8f0;")
        return sep

    def crear_formulario(self):
        """Crea el formulario"""
        self.setStyleSheet(f"background: {COLORS['bg_secondary']};")
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Header ──────────────────────────────────────────
        header = QFrame()
        header.setFixedHeight(58)
        header.setStyleSheet(f"background: {COLORS['danger']}; border: none;")
        hl = QVBoxLayout(header)
        hl.setAlignment(Qt.AlignCenter)
        t = QLabel("🔒  Cierre de Caja")
        t.setFont(QFont('Segoe UI', 13, QFont.Bold))
        t.setStyleSheet("color: white; background: transparent; border: none;")
        t.setAlignment(Qt.AlignCenter)
        hl.addWidget(t)
        main_layout.addWidget(header)

        # ── Body ─────────────────────────────────────────────
        body = QWidget()
        body.setStyleSheet(f"background: {COLORS['bg_secondary']};")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(20, 16, 20, 16)
        bl.setSpacing(10)

        # Panel blanco con desglose
        panel = QFrame()
        panel.setStyleSheet(
            "QFrame { background: white; border: 1px solid #e2e8f0; border-radius: 10px; }"
        )
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(18, 14, 18, 14)
        pl.setSpacing(5)

        # ── Sección EFECTIVO ──
        ef_titulo = QLabel("💵  EFECTIVO")
        ef_titulo.setFont(QFont('Segoe UI', 9, QFont.Bold))
        ef_titulo.setStyleSheet(
            f"background: transparent; border: none; color: {COLORS['text_secondary']};"
            " letter-spacing: 1px;"
        )
        pl.addWidget(ef_titulo)

        self._lbl_ef_inicial  = self._fila_resumen(pl, "  Monto inicial:", "$0")
        self._lbl_ef_ingresos = self._fila_resumen(pl, "  Ingresos:", "$0", color="#10b981")
        self._lbl_ef_egresos  = self._fila_resumen(pl, "  Egresos:", "$0", color="#ef4444")
        pl.addWidget(self._sep_line())
        self._lbl_ef_total    = self._fila_resumen(pl, "  Total Efectivo:", "$0", negrita=True)

        pl.addSpacing(6)
        pl.addWidget(self._sep_line())
        pl.addSpacing(6)

        # ── Sección TRANSFERENCIA ──
        tr_titulo = QLabel("🔄  TRANSFERENCIA")
        tr_titulo.setFont(QFont('Segoe UI', 9, QFont.Bold))
        tr_titulo.setStyleSheet(
            f"background: transparent; border: none; color: {COLORS['text_secondary']};"
            " letter-spacing: 1px;"
        )
        pl.addWidget(tr_titulo)

        self._lbl_tr_ingresos = self._fila_resumen(pl, "  Ingresos:", "$0", color="#10b981")
        self._lbl_tr_egresos  = self._fila_resumen(pl, "  Egresos:", "$0", color="#ef4444")
        pl.addWidget(self._sep_line())
        self._lbl_tr_total    = self._fila_resumen(pl, "  Total Transferencia:", "$0", negrita=True)

        # Tarjeta (oculta por defecto)
        self._frame_tarjeta = QFrame()
        self._frame_tarjeta.setStyleSheet("background: transparent; border: none;")
        tl = QVBoxLayout(self._frame_tarjeta)
        tl.setContentsMargins(0, 6, 0, 0)
        tl.setSpacing(5)
        ta_titulo = QLabel("💳  TARJETA")
        ta_titulo.setFont(QFont('Segoe UI', 9, QFont.Bold))
        ta_titulo.setStyleSheet(
            f"background: transparent; border: none; color: {COLORS['text_secondary']};"
        )
        tl.addWidget(ta_titulo)
        self._lbl_ta_ingresos = self._fila_resumen(tl, "  Ingresos:", "$0", color="#10b981")
        self._lbl_ta_egresos  = self._fila_resumen(tl, "  Egresos:", "$0", color="#ef4444")
        tl.addWidget(self._sep_line())
        self._lbl_ta_total    = self._fila_resumen(tl, "  Total Tarjeta:", "$0", negrita=True)
        self._frame_tarjeta.setVisible(False)
        pl.addWidget(self._frame_tarjeta)

        pl.addSpacing(6)
        pl.addWidget(self._sep_line())
        pl.addSpacing(4)

        # ── Gran Total ──
        row_gt = QHBoxLayout()
        lbl_gt = QLabel("📊  GRAN TOTAL DEL DÍA")
        lbl_gt.setFont(QFont('Segoe UI', 11, QFont.Bold))
        lbl_gt.setStyleSheet("background: transparent; border: none;")
        self._lbl_gran_total = QLabel("$0")
        self._lbl_gran_total.setFont(QFont('Segoe UI', 16, QFont.Bold))
        self._lbl_gran_total.setAlignment(Qt.AlignRight)
        self._lbl_gran_total.setStyleSheet("background: transparent; border: none; color: #3b82f6;")
        row_gt.addWidget(lbl_gt)
        row_gt.addWidget(self._lbl_gran_total)
        pl.addLayout(row_gt)

        bl.addWidget(panel)

        # ── Input monto real ─────────────────────────────────
        lbl_monto = QLabel("Monto Real Contado en Caja (Efectivo):")
        lbl_monto.setFont(make_font(FONTS['body_bold']))
        lbl_monto.setStyleSheet("background: transparent;")
        bl.addWidget(lbl_monto)

        self.monto_real_entry = QLineEdit("0")
        self.monto_real_entry.setFont(QFont('Segoe UI', 16, QFont.Bold))
        self.monto_real_entry.setAlignment(Qt.AlignCenter)
        self.monto_real_entry.setFixedHeight(48)
        self.monto_real_entry.setStyleSheet(
            "QLineEdit { background: white; border: 2px solid #d1d5db;"
            " border-radius: 8px; padding: 4px 12px; }"
            "QLineEdit:focus { border-color: #3b82f6; }"
        )
        self.monto_real_entry.textChanged.connect(self._formatear_monto_cierre)
        self.monto_real_entry.textChanged.connect(lambda: self.calcular_diferencia())
        bl.addWidget(self.monto_real_entry)

        hint = QLabel("Contar billetes y monedas físicas")
        hint.setFont(QFont('Segoe UI', 8))
        hint.setStyleSheet(f"color: {COLORS['text_light']}; background: transparent;")
        bl.addWidget(hint)

        self.diferencia_label = QLabel("")
        self.diferencia_label.setFont(make_font(FONTS['body_bold']))
        self.diferencia_label.setAlignment(Qt.AlignCenter)
        self.diferencia_label.setFixedHeight(28)
        self.diferencia_label.setStyleSheet("background: transparent; border: none;")
        bl.addWidget(self.diferencia_label)

        bl.addStretch()

        # ── Botones ───────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setFont(make_font(FONTS['body']))
        btn_cancelar.setCursor(Qt.PointingHandCursor)
        btn_cancelar.setFixedHeight(42)
        btn_cancelar.setStyleSheet(
            f"QPushButton {{ background: #e2e8f0; color: {COLORS['text_secondary']};"
            f" border: none; border-radius: 8px; font-size: 10pt; }}"
            f"QPushButton:hover {{ background: #cbd5e1; }}"
        )
        btn_cancelar.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancelar)

        btn_cerrar = QPushButton("🔒  Cerrar Caja")
        btn_cerrar.setFont(QFont('Segoe UI', 10, QFont.Bold))
        btn_cerrar.setCursor(Qt.PointingHandCursor)
        btn_cerrar.setFixedHeight(42)
        btn_cerrar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['danger']}; color: white;"
            f" border: none; border-radius: 8px; font-size: 10pt; }}"
            f"QPushButton:hover {{ background: {COLORS['danger_dark']}; }}"
        )
        btn_cerrar.clicked.connect(self.cerrar)
        btn_cerrar.setAutoDefault(False)
        btn_cerrar.setDefault(False)
        self.btn_cerrar_caja = btn_cerrar
        btn_row.addWidget(btn_cerrar, 2)

        bl.addLayout(btn_row)
        main_layout.addWidget(body, 1)

    def cargar_datos(self):
        """Carga los datos del resumen"""
        resumen = self.caja_service.obtener_resumen_cierre()

        total_efectivo = resumen['esperado']
        total_transfer = resumen['transferencia'] - resumen['egresos_transferencia']
        total_tarjeta  = resumen['tarjeta'] - resumen['egresos_tarjeta']
        gran_total     = total_efectivo + total_transfer + total_tarjeta

        def fmt(v):
            prefix = "+" if v > 0 else ""
            return f"${v:,.0f}" if v >= 0 else f"-${abs(v):,.0f}"

        def fmt_signed(v):
            return f"+${v:,.0f}" if v >= 0 else f"-${abs(v):,.0f}"

        def color_total(v):
            return "#10b981" if v >= 0 else "#ef4444"

        # Efectivo
        self._lbl_ef_inicial.setText(f"${resumen['monto_inicial']:,.0f}")
        self._lbl_ef_ingresos.setText(f"+${resumen['efectivo']:,.0f}")
        self._lbl_ef_egresos.setText(f"-${resumen['egresos_efectivo']:,.0f}")
        self._lbl_ef_total.setText(fmt(total_efectivo))
        self._lbl_ef_total.setStyleSheet(
            f"background: transparent; border: none; color: {color_total(total_efectivo)};"
        )

        # Transferencia
        self._lbl_tr_ingresos.setText(f"+${resumen['transferencia']:,.0f}")
        self._lbl_tr_egresos.setText(f"-${resumen['egresos_transferencia']:,.0f}")
        self._lbl_tr_total.setText(fmt(total_transfer))
        self._lbl_tr_total.setStyleSheet(
            f"background: transparent; border: none; color: {color_total(total_transfer)};"
        )

        # Tarjeta (solo si tiene movimiento)
        tiene_tarjeta = resumen['tarjeta'] > 0 or resumen['egresos_tarjeta'] > 0
        self._frame_tarjeta.setVisible(tiene_tarjeta)
        if tiene_tarjeta:
            self._lbl_ta_ingresos.setText(f"+${resumen['tarjeta']:,.0f}")
            self._lbl_ta_egresos.setText(f"-${resumen['egresos_tarjeta']:,.0f}")
            self._lbl_ta_total.setText(fmt(total_tarjeta))
            self._lbl_ta_total.setStyleSheet(
                f"background: transparent; border: none; color: {color_total(total_tarjeta)};"
            )

        # Gran total
        self._lbl_gran_total.setText(fmt(gran_total))
        self._lbl_gran_total.setStyleSheet(
            f"background: transparent; border: none;"
            f" color: {color_total(gran_total)}; font-size: 16pt;"
        )

        self.monto_esperado = resumen['esperado']
        self.calcular_diferencia()

    def _formatear_monto_cierre(self, text):
        """Formatea el monto con separadores de miles"""
        if self._formatting:
            return
        self._formatting = True
        raw = text.replace('.', '').replace(',', '')
        raw = ''.join(c for c in raw if c.isdigit())
        if raw:
            try:
                num = int(raw)
                formatted = f"{num:,}".replace(',', '.')
                self.monto_real_entry.setText(formatted)
            except ValueError:
                pass
        self._formatting = False

    def calcular_diferencia(self):
        """Calcula la diferencia entre esperado y real"""
        try:
            raw = self.monto_real_entry.text().replace('.', '').replace(',', '')
            monto_real = money(raw) if raw.isdigit() else Decimal("0.00")

            # No mostrar aviso si el campo está en 0 (no contado aún)
            if monto_real == Decimal("0.00"):
                self.diferencia_label.setText("")
                return

            diferencia = monto_real - self.monto_esperado

            if abs(diferencia) < Decimal("0.01"):
                texto = "✅  Caja cuadrada"
                color = COLORS['success']
            elif diferencia > 0:
                texto = f"💰  Sobrante: ${diferencia:,.0f}"
                color = COLORS['info']
            else:
                texto = f"⚠️  Faltante: ${abs(diferencia):,.0f}"
                color = COLORS['danger']

            self.diferencia_label.setText(texto)
            self.diferencia_label.setStyleSheet(f"color: {color}; background: transparent; border: none;")
        except (ValueError, AttributeError):
            self.diferencia_label.setText("")

    def cerrar(self):
        """Cierra la caja"""
        try:
            monto_real = money(
                self.monto_real_entry.text().replace('.', '').replace(',', '.')
            )
        except ValueError:
            QMessageBox.critical(self, "Error", "Ingrese un monto válido")
            return

        # Calcular diferencia
        diferencia = monto_real - self.monto_esperado

        # Determinar tipo de diferencia
        if abs(diferencia) < Decimal("0.01"):
            tipo_diff = "\u2705 Caja Cuadrada"
            color_msg = ""
        elif diferencia > 0:
            tipo_diff = f"\U0001f4b0 Sobrante: ${diferencia:,.0f}"
            color_msg = "\n(Hay más dinero del esperado)"
        else:
            tipo_diff = f"\u26a0\ufe0f Faltante: ${abs(diferencia):,.0f}"
            color_msg = "\n(Falta dinero)"

        separador = "━" * 40
        confirmacion = (
            f"¿CONFIRMAR CIERRE DE CAJA?\n"
            f"{'=' * 40}\n\n"
            f"📊 Monto Esperado:     ${self.monto_esperado:,.0f}\n"
            f"💵 Monto Real (contado): ${monto_real:,.0f}\n"
            f"{separador}\n"
            f"{tipo_diff}{color_msg}\n\n"
            f"¿Desea continuar con el cierre?"
        )

        resp = QMessageBox.question(
            self, "Confirmar Cierre de Caja", confirmacion,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if resp != QMessageBox.Yes:
            return

        observaciones = ""
        if abs(diferencia) >= Decimal("0.01"):
            from PySide6.QtWidgets import QInputDialog

            observaciones, ok_obs = QInputDialog.getText(
                self,
                "Observación de diferencia",
                "La diferencia es evidencia. Indique una observación:",
            )
            if not ok_obs or not str(observaciones).strip():
                QMessageBox.warning(
                    self, "Observación requerida",
                    "Si hay faltante o sobrante debe registrar una observación.",
                )
                return
            observaciones = str(observaciones).strip()

        exito, mensaje = self.caja_service.cerrar_caja(monto_real, observaciones)

        if exito:
            QMessageBox.information(self, "Éxito", mensaje)
            ver = QMessageBox.question(
                self,
                "Comprobante",
                "¿Ver comprobante de cierre?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if ver == QMessageBox.Yes:
                from ui.imprimir_factura import imprimir_por_identidad
                last = self.caja_service.obtener_ultimo_cierre_usuario()
                if last:
                    imprimir_por_identidad(
                        self,
                        self.caja_service.db,
                        "CASH_CLOSE",
                        last.get("local_id") or last.get("id"),
                    )
            if self.callback:
                self.callback()
            self.accept()
        else:
            QMessageBox.critical(self, "Error", mensaje)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            return
        super().keyPressEvent(event)


class VentanaHistorialPagos(QDialog):
    """Ventana para mostrar historial de pagos a proveedores"""

    def __init__(self, parent, abonos_repo, compras_repo):
        super().__init__(parent)
        self.abonos_repo = abonos_repo
        self.compras_repo = compras_repo

        self.setWindowTitle("Historial de Pagos a Proveedores")
        self.resize(1200, 600)

        self.crear_interfaz()
        self.cargar_pagos()
        self.exec()

    def crear_interfaz(self):
        """Crea la interfaz de la ventana"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setStyleSheet(f"background: {COLORS['primary']};")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 15, 20, 15)

        header_lbl = QLabel("\U0001f4b0 Historial de Pagos a Proveedores")
        header_lbl.setFont(make_font(FONTS['large']))
        header_lbl.setStyleSheet("color: white; background: transparent;")
        header_lbl.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(header_lbl)

        main_layout.addWidget(header)

        # Frame de filtros
        filtros_frame = QFrame()
        filtros_frame.setStyleSheet(f"background: {COLORS['bg_secondary']};")
        filtros_layout = QHBoxLayout(filtros_frame)
        filtros_layout.setContentsMargins(20, 10, 20, 10)

        lbl_filtrar = QLabel("Filtrar por:")
        lbl_filtrar.setFont(make_font(FONTS['body_bold']))
        lbl_filtrar.setStyleSheet("background: transparent;")
        filtros_layout.addWidget(lbl_filtrar)

        lbl_periodo = QLabel("Per\u00edodo:")
        lbl_periodo.setFont(make_font(FONTS['body']))
        lbl_periodo.setStyleSheet("background: transparent;")
        filtros_layout.addWidget(lbl_periodo)

        self.periodo_combo = QComboBox()
        self.periodo_combo.addItems(["7", "30", "60", "90", "180", "365", "TODO"])
        self.periodo_combo.setCurrentText("90")
        self.periodo_combo.setFixedWidth(100)
        self.periodo_combo.currentIndexChanged.connect(lambda: self.cargar_pagos())
        filtros_layout.addWidget(self.periodo_combo)

        lbl_dias = QLabel("d\u00edas")
        lbl_dias.setFont(make_font(FONTS['body']))
        lbl_dias.setStyleSheet("background: transparent;")
        filtros_layout.addWidget(lbl_dias)

        btn_actualizar = QPushButton("\U0001f504 Actualizar")
        btn_actualizar.setFont(make_font(FONTS['body']))
        btn_actualizar.setCursor(Qt.PointingHandCursor)
        btn_actualizar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['info']}; color: white; border: none; "
            f"border-radius: 6px; padding: 5px 15px; }}"
            f"QPushButton:hover {{ background: #0891b2; }}"
        )
        btn_actualizar.clicked.connect(self.cargar_pagos)
        filtros_layout.addWidget(btn_actualizar)

        filtros_layout.addStretch()
        main_layout.addWidget(filtros_frame)

        # Tabla de pagos
        self.columns = ('ID', 'Fecha Compra', 'Proveedor', '# Factura', 'Total Factura',
                         'Monto Pagado', 'Saldo', 'Estado', '\u00daltimo Abono', 'Tipo Pago', 'Usuario')

        self.tree = QTableWidget()
        self.tree.setColumnCount(len(self.columns))
        self.tree.setHorizontalHeaderLabels(self.columns)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setAlternatingRowColors(True)
        self.tree.verticalHeader().setVisible(False)
        self.tree.setStyleSheet(
            f"QTableWidget {{ background: white; gridline-color: transparent;"
            f" border: 1px solid {COLORS['border']}; border-radius: 12px;"
            f" alternate-background-color: {COLORS['table_row_alt']}; }}"
            "QTableWidget::item { padding: 7px 6px; }"
            f"QTableWidget::item:selected {{ background: {COLORS['table_selection']};"
            f" color: {COLORS['text_primary']}; }}"
            "QHeaderView::section {"
            f"    background: {COLORS['table_header']}; color: {COLORS['table_header_fg']};"
            "    font-weight: 500; padding: 10px 8px; border: none;"
            "}"
        )

        anchos = {
            'ID': 50, 'Fecha Compra': 130, 'Proveedor': 130, '# Factura': 90,
            'Total Factura': 110, 'Monto Pagado': 110, 'Saldo': 100, 'Estado': 80,
            '\u00daltimo Abono': 130, 'Tipo Pago': 110, 'Usuario': 100
        }
        for i, col in enumerate(self.columns):
            self.tree.setColumnWidth(i, anchos.get(col, 100))

        main_layout.addWidget(self.tree, 1)

        # Frame de totales y estadísticas
        totales_frame = QFrame()
        totales_frame.setStyleSheet(
            f"background: {COLORS['bg_secondary']}; border: 1px solid #d1d5db; border-radius: 6px;"
        )
        stats_layout = QHBoxLayout(totales_frame)
        stats_layout.setContentsMargins(20, 15, 20, 15)
        stats_layout.setAlignment(Qt.AlignCenter)

        self.total_label = QLabel("")
        self.total_label.setFont(make_font(FONTS['body_bold']))
        self.total_label.setStyleSheet(f"color: {COLORS['primary']}; background: transparent; border: none;")
        stats_layout.addWidget(self.total_label)

        stats_layout.addSpacing(40)

        self.facturas_pagadas_label = QLabel("")
        self.facturas_pagadas_label.setFont(make_font(FONTS['body_bold']))
        self.facturas_pagadas_label.setStyleSheet(f"color: {COLORS['success']}; background: transparent; border: none;")
        stats_layout.addWidget(self.facturas_pagadas_label)

        stats_layout.addSpacing(40)

        self.facturas_pendientes_label = QLabel("")
        self.facturas_pendientes_label.setFont(make_font(FONTS['body_bold']))
        self.facturas_pendientes_label.setStyleSheet(f"color: {COLORS['danger']}; background: transparent; border: none;")
        stats_layout.addWidget(self.facturas_pendientes_label)

        main_layout.addWidget(totales_frame)

        # Botones
        btn_frame = QFrame()
        btn_frame.setStyleSheet("background: white;")
        btn_layout = QHBoxLayout(btn_frame)
        btn_layout.setAlignment(Qt.AlignCenter)
        btn_layout.setContentsMargins(10, 10, 10, 10)

        btn_pago = QPushButton("\U0001f4b5 Registrar Pago")
        btn_pago.setFont(make_font(FONTS['body_bold']))
        btn_pago.setCursor(Qt.PointingHandCursor)
        btn_pago.setStyleSheet(
            f"QPushButton {{ background: {COLORS['success']}; color: white; border: none; "
            f"border-radius: 6px; padding: 10px 30px; }}"
            f"QPushButton:hover {{ background: {COLORS['success_dark']}; }}"
        )
        btn_pago.clicked.connect(self.registrar_pago_desde_historial)
        btn_layout.addWidget(btn_pago)

        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setFont(make_font(FONTS['body']))
        btn_cerrar.setCursor(Qt.PointingHandCursor)
        btn_cerrar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['secondary']}; color: white; border: none; "
            f"border-radius: 6px; padding: 10px 30px; }}"
            f"QPushButton:hover {{ background: #475569; }}"
        )
        btn_cerrar.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cerrar)

        main_layout.addWidget(btn_frame)

    def cargar_pagos(self):
        """Carga el historial de pagos"""
        self.tree.setRowCount(0)

        try:
            periodo = self.periodo_combo.currentText()

            # Obtener todas las compras del período (con o sin abonos)
            if periodo == "TODO":
                compras = self.abonos_repo.listar_compras_con_pagos_periodo(dias=9999)
            else:
                dias = int(periodo)
                compras = self.abonos_repo.listar_compras_con_pagos_periodo(dias)

            total_pagado = 0
            facturas_unicas = {}  # {id_compra: estado_pago}

            color_map = {
                'pagado': (QColor('#eaf3de'), QColor('#3b6d11')),
                'parcial': (QColor('#faeeda'), QColor('#854f0b')),
                'pendiente': (QColor('#fcebeb'), QColor('#a32d2d')),
            }

            for compra in compras:
                proveedor = compra.get('proveedor', 'N/A') or 'N/A'
                num_factura = compra.get('numero_factura', '-') or '-'

                # Fecha de la compra
                fecha_compra = compra['fecha_compra'][:16] if compra.get('fecha_compra') else 'N/A'

                # Información financiera
                total_factura = compra.get('total_factura', 0)
                monto_pagado = compra.get('monto_pagado', 0)
                saldo_pendiente = compra.get('saldo_pendiente', 0)
                estado_pago = compra.get('estado_pago', 'PENDIENTE')

                # Info del último abono (si existe)
                fecha_ultimo_abono = compra.get('fecha_ultimo_abono')
                if fecha_ultimo_abono:
                    fecha_ultimo_abono = fecha_ultimo_abono[:16]
                else:
                    fecha_ultimo_abono = 'Sin abonos'

                tipo_pago = compra.get('tipo_pago_ultimo', '-')
                usuario = compra.get('usuario_ultimo_abono', 'Sistema')

                # Rastrear facturas por estado
                id_compra = compra['id_compra']
                facturas_unicas[id_compra] = estado_pago

                # Determinar tag para color
                tag = 'pagado' if estado_pago == 'PAGADO' else 'parcial' if estado_pago == 'PARCIAL' else 'pendiente'
                bg_color, fg_color = color_map[tag]

                valores = (
                    str(id_compra),
                    fecha_compra,
                    proveedor,
                    num_factura,
                    f"${total_factura:,.0f}",
                    f"${monto_pagado:,.0f}",
                    f"${saldo_pendiente:,.0f}",
                    estado_pago,
                    fecha_ultimo_abono,
                    tipo_pago,
                    usuario
                )

                row = self.tree.rowCount()
                self.tree.insertRow(row)
                for col_idx, val in enumerate(valores):
                    item = QTableWidgetItem(str(val))
                    item.setTextAlignment(Qt.AlignCenter)
                    item.setBackground(bg_color)
                    item.setForeground(fg_color)
                    self.tree.setItem(row, col_idx, item)

                total_pagado += monto_pagado

            # Contar estados de facturas
            facturas_pagadas = sum(1 for estado in facturas_unicas.values() if estado == 'PAGADO')
            facturas_pendientes = sum(1 for estado in facturas_unicas.values() if estado in ('PENDIENTE', 'PARCIAL'))

            # Actualizar estadísticas
            self.total_label.setText(
                f"\U0001f4b0 Total Pagado: ${total_pagado:,.0f} ({len(compras)} facturas)"
            )

            self.facturas_pagadas_label.setText(
                f"\u2705 Facturas Pagadas: {facturas_pagadas}"
            )

            self.facturas_pendientes_label.setText(
                f"\u23f3 Facturas Pendientes: {facturas_pendientes}"
            )

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al cargar pagos:\n{str(e)}")
            import traceback
            traceback.print_exc()

    def registrar_pago_desde_historial(self):
        """Abre el formulario de registro de abono para la factura seleccionada"""
        selected = self.tree.selectedItems()
        if not selected:
            QMessageBox.warning(self, "Advertencia", "Seleccione una factura para registrar el pago")
            return

        # Obtener datos de la factura seleccionada
        row = selected[0].row()
        id_compra = int(self.tree.item(row, 0).text())
        num_factura = self.tree.item(row, 3).text()
        total_factura = float(self.tree.item(row, 4).text().replace('$', '').replace(',', ''))
        saldo = float(self.tree.item(row, 6).text().replace('$', '').replace(',', ''))
        estado = self.tree.item(row, 7).text()

        # Verificar que no esté completamente pagada
        if estado == 'PAGADO' or saldo <= 0:
            QMessageBox.information(
                self, "Informaci\u00f3n",
                "Esta factura ya est\u00e1 completamente pagada.\n"
                "No se pueden registrar m\u00e1s abonos."
            )
            return

        # Abrir modal de abono
        self._abrir_modal_abono(id_compra, num_factura, total_factura, saldo)

    def _abrir_modal_abono(self, id_compra, numero_factura, total, saldo):
        """Abre modal para registrar abono"""
        try:
            # Crear modal
            ventana_abono = QDialog(self)
            ventana_abono.setWindowTitle("Registrar Pago a Factura")
            ventana_abono.setFixedSize(600, 500)
            ventana_abono.setModal(True)

            layout = QVBoxLayout(ventana_abono)
            layout.setContentsMargins(15, 10, 15, 10)
            layout.setSpacing(10)

            # Info de factura
            info_group = QGroupBox("Informaci\u00f3n de Factura")
            info_group.setFont(make_font(FONTS['body_bold']))
            info_layout = QVBoxLayout(info_group)

            lbl_factura = QLabel(f"Factura: {numero_factura if numero_factura != '-' else 'Sin n\u00famero'}")
            lbl_factura.setFont(make_font(FONTS['body']))
            info_layout.addWidget(lbl_factura)

            lbl_total = QLabel(f"Total: ${total:,.0f}")
            lbl_total.setFont(make_font(FONTS['body']))
            info_layout.addWidget(lbl_total)

            lbl_saldo = QLabel(f"Saldo Pendiente: ${saldo:,.0f}")
            lbl_saldo.setFont(QFont('Segoe UI', 11, QFont.Bold))
            lbl_saldo.setStyleSheet("color: #e74c3c;")
            info_layout.addWidget(lbl_saldo)

            layout.addWidget(info_group)

            # Form de abono
            form_group = QGroupBox("Datos del Pago")
            form_group.setFont(make_font(FONTS['body_bold']))
            form_layout = QGridLayout(form_group)
            form_layout.setSpacing(8)

            # Monto
            form_layout.addWidget(QLabel("Monto a Pagar:"), 0, 0)
            monto_entry = QLineEdit()
            monto_entry.setFont(make_font(FONTS['large']))
            monto_entry.setFixedWidth(180)
            form_layout.addWidget(monto_entry, 0, 1)
            monto_entry.setFocus()

            # Botón para pagar saldo completo
            btn_pagar_todo = QPushButton("Pagar Saldo Completo")
            btn_pagar_todo.setFont(make_font(FONTS['small']))
            btn_pagar_todo.setCursor(Qt.PointingHandCursor)
            btn_pagar_todo.setStyleSheet(
                f"QPushButton {{ background: {COLORS['info']}; color: white; border: none; "
                f"border-radius: 4px; padding: 4px 8px; }}"
                f"QPushButton:hover {{ background: #0891b2; }}"
            )
            btn_pagar_todo.clicked.connect(lambda: monto_entry.setText(str(int(saldo))))
            form_layout.addWidget(btn_pagar_todo, 0, 2)

            # Tipo de pago
            form_layout.addWidget(QLabel("Tipo de Pago:"), 1, 0)
            tipo_combo = QComboBox()
            tipo_combo.addItems(["Efectivo", "Transferencia", "Tarjeta"])
            tipo_combo.setFixedWidth(180)
            form_layout.addWidget(tipo_combo, 1, 1)

            # Número de comprobante
            form_layout.addWidget(QLabel("# Comprobante:"), 2, 0)
            comprobante_entry = QLineEdit()
            comprobante_entry.setFont(make_font(FONTS['body']))
            comprobante_entry.setFixedWidth(200)
            form_layout.addWidget(comprobante_entry, 2, 1)

            # Observaciones
            form_layout.addWidget(QLabel("Observaciones:"), 3, 0, Qt.AlignTop)
            obs_text = QTextEdit()
            obs_text.setFont(make_font(FONTS['body']))
            obs_text.setMaximumHeight(100)
            form_layout.addWidget(obs_text, 3, 1, 1, 2)

            layout.addWidget(form_group, 1)

            # Botones
            btn_layout = QHBoxLayout()
            btn_layout.setAlignment(Qt.AlignCenter)

            def guardar_abono():
                from services.operational_balance import PaymentError
                try:
                    monto = float(monto_entry.text())

                    if monto <= 0:
                        QMessageBox.critical(ventana_abono, "Error", "El monto debe ser mayor a 0")
                        return

                    if monto > saldo:
                        QMessageBox.critical(
                            ventana_abono, "Error",
                            f"El monto no puede ser mayor al saldo pendiente (${saldo:,.0f})"
                        )
                        return

                    # Crear abono
                    from models import Abono
                    from datetime import datetime

                    abono = Abono(
                        id_compra=id_compra,
                        monto_abono=monto,
                        fecha_abono=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        tipo_pago=tipo_combo.currentText(),
                        numero_comprobante=comprobante_entry.text() or None,
                        usuario='admin',  # Obtener usuario actual
                        observaciones=obs_text.toPlainText().strip() or None
                    )

                    # Guardar en BD
                    self.abonos_repo.crear_abono(abono)

                    QMessageBox.information(
                        ventana_abono, "\u00c9xito",
                        f"Pago registrado correctamente\nMonto: ${monto:,.0f}"
                    )
                    ventana_abono.accept()

                    # Recargar tabla
                    self.cargar_pagos()

                except PaymentError as e:
                    QMessageBox.warning(ventana_abono, "Pago no permitido", str(e))
                except ValueError:
                    QMessageBox.critical(ventana_abono, "Error", "Ingrese un monto v\u00e1lido")
                except Exception as e:
                    QMessageBox.critical(ventana_abono, "Error", f"Error al registrar pago:\n{str(e)}")
                    import traceback
                    traceback.print_exc()

            btn_guardar = QPushButton("Guardar Pago")
            btn_guardar.setFont(make_font(FONTS['body_bold']))
            btn_guardar.setCursor(Qt.PointingHandCursor)
            btn_guardar.setStyleSheet(
                f"QPushButton {{ background: {COLORS['success']}; color: white; border: none; "
                f"border-radius: 6px; padding: 10px 30px; }}"
                f"QPushButton:hover {{ background: {COLORS['success_dark']}; }}"
            )
            btn_guardar.clicked.connect(guardar_abono)
            btn_layout.addWidget(btn_guardar)

            btn_cancelar = QPushButton("Cancelar")
            btn_cancelar.setFont(make_font(FONTS['body']))
            btn_cancelar.setCursor(Qt.PointingHandCursor)
            btn_cancelar.setStyleSheet(
                f"QPushButton {{ background: {COLORS['secondary']}; color: white; border: none; "
                f"border-radius: 6px; padding: 10px 30px; }}"
                f"QPushButton:hover {{ background: #475569; }}"
            )
            btn_cancelar.clicked.connect(ventana_abono.reject)
            btn_layout.addWidget(btn_cancelar)

            layout.addLayout(btn_layout)

            ventana_abono.exec()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al abrir formulario:\n{str(e)}")
            import traceback
            traceback.print_exc()


class FormularioIngresoManual(QDialog):
    """Ingreso/refuerzo administrativo. No es el DRAWER_IN de una venta."""

    def __init__(self, parent, caja_service, callback=None):
        super().__init__(parent)
        self.caja_service = caja_service
        self.callback = callback
        self._formatting = False

        self.setWindowTitle("Ingreso de caja")
        self.setFixedSize(400, 300)
        self.setModal(True)

        self.crear_formulario()
        self.exec()

    def crear_formulario(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(10)

        title = QLabel("Ingreso / refuerzo")
        title.setFont(make_font(FONTS['heading']))
        title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title)
        main_layout.addSpacing(12)

        lbl_monto = QLabel("Monto en efectivo:")
        lbl_monto.setFont(make_font(FONTS['body']))
        main_layout.addWidget(lbl_monto)

        self.monto_entry = QLineEdit("0")
        self.monto_entry.setFont(make_font(FONTS['large']))
        self.monto_entry.setAlignment(Qt.AlignCenter)
        self.monto_entry.textChanged.connect(self._formatear_monto)
        main_layout.addWidget(self.monto_entry)

        lbl_motivo = QLabel("Motivo:")
        lbl_motivo.setFont(make_font(FONTS['body']))
        main_layout.addWidget(lbl_motivo)
        self.motivo_entry = QLineEdit()
        self.motivo_entry.setFont(make_font(FONTS['body']))
        self.motivo_entry.setPlaceholderText("Obligatorio")
        main_layout.addWidget(self.motivo_entry)

        main_layout.addStretch()

        btn_layout = QHBoxLayout()
        btn_guardar = QPushButton("Registrar")
        btn_guardar.setFont(make_font(FONTS['body_bold']))
        btn_guardar.setCursor(Qt.PointingHandCursor)
        btn_guardar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['success']}; color: white; border: none; "
            f"border-radius: 6px; padding: 10px 20px; }}"
            f"QPushButton:hover {{ background: {COLORS['success_dark']}; }}"
        )
        btn_guardar.clicked.connect(self.guardar)
        btn_guardar.setAutoDefault(False)
        btn_guardar.setDefault(False)
        btn_layout.addWidget(btn_guardar)

        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setFont(make_font(FONTS['body']))
        btn_cancelar.setCursor(Qt.PointingHandCursor)
        btn_cancelar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['secondary']}; color: white; border: none; "
            f"border-radius: 6px; padding: 10px 20px; }}"
            f"QPushButton:hover {{ background: #475569; }}"
        )
        btn_cancelar.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancelar)
        main_layout.addLayout(btn_layout)

    def _formatear_monto(self, text):
        if self._formatting:
            return
        self._formatting = True
        raw = "".join(c for c in text.replace(".", "").replace(",", "") if c.isdigit())
        if raw:
            try:
                self.monto_entry.setText(f"{int(raw):,}".replace(",", "."))
            except ValueError:
                pass
        self._formatting = False

    def guardar(self):
        try:
            monto = money(self.monto_entry.text().replace(".", "").replace(",", "."))
        except ValueError:
            QMessageBox.critical(self, "Error", "Ingrese un monto válido")
            return
        motivo = self.motivo_entry.text().strip()
        if not motivo:
            QMessageBox.critical(self, "Error", "El motivo es obligatorio")
            return
        usuario = getattr(getattr(self.caja_service, "auth", None), "usuario_actual", None)
        who = getattr(usuario, "username", None)
        ok, mensaje, _mid = self.caja_service.registrar_ingreso_manual(
            monto, motivo, usuario=who
        )
        if ok:
            QMessageBox.information(self, "Éxito", mensaje)
            if self.callback:
                self.callback()
            self.accept()
        else:
            QMessageBox.critical(self, "Error", mensaje)


class FormularioEgreso(QDialog):
    """Formulario para registrar egresos/gastos de caja"""

    def __init__(self, parent, caja_service, callback=None):
        super().__init__(parent)
        self.caja_service = caja_service
        self.auth = caja_service.auth
        self.callback = callback
        self._formatting = False

        self.setWindowTitle("Registrar Egreso")
        self.setFixedSize(500, 460)
        self.setModal(True)

        self.crear_formulario()
        self.exec()

    def crear_formulario(self):
        """Crea el formulario"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(5)

        title = QLabel("\U0001f4b8 Registrar Egreso")
        title.setFont(make_font(FONTS['heading']))
        title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title)
        main_layout.addSpacing(15)

        # Monto
        lbl_monto = QLabel("Monto del Egreso:")
        lbl_monto.setFont(make_font(FONTS['body_bold']))
        main_layout.addWidget(lbl_monto)

        self.monto_entry = QLineEdit("0")
        self.monto_entry.setFont(make_font(FONTS['large']))
        self.monto_entry.setAlignment(Qt.AlignCenter)
        self.monto_entry.textChanged.connect(self._formatear_monto)
        main_layout.addWidget(self.monto_entry)

        # Categoría
        lbl_cat = QLabel("Categor\u00eda:")
        lbl_cat.setFont(make_font(FONTS['body_bold']))
        main_layout.addWidget(lbl_cat)

        self.categoria_combo = QComboBox()
        self.categoria_combo.setFont(make_font(FONTS['body']))
        categorias = [
            'Combustible/Gasolina',
            'Mantenimiento Veh\u00edculo',
            'Servicios (Agua/Luz/Internet)',
            'Pago a Empleados',
            'Compras Menores',
            'Papeler\u00eda',
            'Transporte',
            'Otros Gastos'
        ]
        self.categoria_combo.addItems(categorias)
        self.categoria_combo.setCurrentIndex(0)
        main_layout.addWidget(self.categoria_combo)

        # Método de pago
        lbl_metodo = QLabel("M\u00e9todo de Pago:")
        lbl_metodo.setFont(make_font(FONTS['body_bold']))
        main_layout.addWidget(lbl_metodo)

        metodos_frame = QHBoxLayout()
        self.metodo_group = QButtonGroup(self)

        rb_efectivo = QRadioButton("\U0001f4b5 Efectivo")
        rb_efectivo.setFont(make_font(FONTS['body']))
        rb_efectivo.setChecked(True)
        self.metodo_group.addButton(rb_efectivo)
        metodos_frame.addWidget(rb_efectivo)

        rb_tarjeta = QRadioButton("\U0001f4b3 Tarjeta")
        rb_tarjeta.setFont(make_font(FONTS['body']))
        self.metodo_group.addButton(rb_tarjeta)
        metodos_frame.addWidget(rb_tarjeta)

        rb_transferencia = QRadioButton("\U0001f3e6 Transferencia")
        rb_transferencia.setFont(make_font(FONTS['body']))
        self.metodo_group.addButton(rb_transferencia)
        metodos_frame.addWidget(rb_transferencia)

        # Store mapping for value retrieval
        self._metodo_map = {
            rb_efectivo: 'Efectivo',
            rb_tarjeta: 'Tarjeta',
            rb_transferencia: 'Transferencia',
        }

        main_layout.addLayout(metodos_frame)

        lbl_motivo = QLabel("Motivo / descripción:")
        lbl_motivo.setFont(make_font(FONTS['body_bold']))
        main_layout.addWidget(lbl_motivo)
        self.motivo_entry = QLineEdit()
        self.motivo_entry.setFont(make_font(FONTS['body']))
        self.motivo_entry.setPlaceholderText("Obligatorio")
        main_layout.addWidget(self.motivo_entry)

        main_layout.addStretch()

        # Botones
        btn_layout = QHBoxLayout()
        btn_layout.setAlignment(Qt.AlignCenter)

        btn_guardar = QPushButton("Guardar Egreso")
        btn_guardar.setFont(make_font(FONTS['body_bold']))
        btn_guardar.setCursor(Qt.PointingHandCursor)
        btn_guardar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['danger']}; color: white; border: none; "
            f"border-radius: 6px; padding: 10px 20px; }}"
            f"QPushButton:hover {{ background: {COLORS['danger_dark']}; }}"
        )
        btn_guardar.clicked.connect(self.guardar)
        btn_guardar.setAutoDefault(False)
        btn_guardar.setDefault(False)
        btn_layout.addWidget(btn_guardar)

        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setFont(make_font(FONTS['body']))
        btn_cancelar.setCursor(Qt.PointingHandCursor)
        btn_cancelar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['secondary']}; color: white; border: none; "
            f"border-radius: 6px; padding: 10px 20px; }}"
            f"QPushButton:hover {{ background: #475569; }}"
        )
        btn_cancelar.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancelar)

        main_layout.addLayout(btn_layout)

    def _formatear_monto(self, text):
        """Formatea el monto con separadores de miles"""
        if self._formatting:
            return
        self._formatting = True
        raw = text.replace('.', '').replace(',', '')
        raw = ''.join(c for c in raw if c.isdigit())
        if raw:
            try:
                num = int(raw)
                formatted = f"{num:,}".replace(',', '.')
                self.monto_entry.setText(formatted)
            except ValueError:
                pass
        self._formatting = False

    def guardar(self):
        """Guarda el egreso"""
        try:
            monto = money(self.monto_entry.text().replace('.', '').replace(',', '.'))
        except ValueError:
            QMessageBox.critical(self, "Error", "Ingrese un monto v\u00e1lido")
            return

        if monto <= 0:
            QMessageBox.critical(self, "Error", "El monto debe ser mayor a cero")
            return

        categoria = self.categoria_combo.currentText()
        motivo = self.motivo_entry.text().strip()
        if not motivo:
            QMessageBox.critical(self, "Error", "El motivo del egreso es obligatorio")
            return
        descripcion = f"{categoria}: {motivo}"
        metodo_pago = self._metodo_map.get(self.metodo_group.checkedButton(), 'Efectivo')

        # Confirmar
        resp = QMessageBox.question(
            self, "Confirmar",
            f"\u00bfRegistrar egreso de ${monto:,.0f}?\n\n"
            f"Categor\u00eda: {categoria}\n"
            f"M\u00e9todo: {metodo_pago}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if resp != QMessageBox.Yes:
            return

        try:
            ok, mensaje, _egreso_id = self.caja_service.registrar_egreso(
                monto=monto,
                categoria=categoria,
                descripcion=descripcion,
                metodo_pago=metodo_pago,
                usuario=self.auth.usuario_actual.username,
            )
            if not ok:
                QMessageBox.critical(self, "Error", mensaje)
                return

            QMessageBox.information(self, "\u00c9xito", f"Egreso de ${monto:,.0f} registrado correctamente")

            if self.callback:
                self.callback()

            self.accept()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al registrar egreso:\n{str(e)}")
            import traceback
            traceback.print_exc()
