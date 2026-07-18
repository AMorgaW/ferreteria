# -*- coding: utf-8 -*-
"""
Interfaz de Usuario para Gestión de Movimientos de Inventario (PySide6)
Permite registrar entradas, salidas y consultar historial
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QDialog,
    QMessageBox, QFrame, QTextEdit, QGridLayout, QGroupBox, QCheckBox,
    QAbstractItemView, QSizePolicy, QTreeWidget, QTreeWidgetItem,
    QScrollArea, QDialogButtonBox, QDateEdit, QProgressBar
)
from PySide6.QtCore import Qt, Signal, QDate
from PySide6.QtGui import QFont, QColor, QBrush

from datetime import datetime
from typing import Optional
from collections import defaultdict
import re
from ui_config import COLORS, FONTS, ICONS, make_font
from formato import formatear_stock


class MovimientosUI(QWidget):
    """Interfaz de usuario para movimientos de inventario"""

    def __init__(self, parent, movimientos_service, productos_repo, proveedores_repo,
                 auth, db_manager, inventario_repo, alertas_service=None,
                 compras_repo=None, clientes_repo=None):
        super().__init__(parent)
        self.parent_widget = parent
        self.movimientos_service = movimientos_service
        self.productos_repo = productos_repo
        self.proveedores_repo = proveedores_repo
        self.auth = auth
        self.db_manager = db_manager
        self.inventario_repo = inventario_repo
        self.alertas_service = alertas_service
        self.compras_repo = compras_repo
        self.clientes_repo = clientes_repo

        self.producto_seleccionado = None
        self.producto_seleccionado_data = None
        self.proveedor_seleccionado = None

        self.crear_ui()
        self.cargar_historial()

    def crear_ui(self):
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
        title = QLabel(f"{ICONS['movimientos']} Movimientos de Inventario")
        title.setFont(make_font(FONTS['large']))
        title.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent;")
        header.addWidget(title)
        header.addStretch()

        btn_entrada = QPushButton("📥 Nueva Entrada")
        btn_entrada.setFont(make_font(FONTS['body_bold']))
        btn_entrada.setCursor(Qt.PointingHandCursor)
        btn_entrada.setStyleSheet(
            f"QPushButton {{ background: {COLORS['success']}; color: white; border: none; "
            f"border-radius: 9px; padding: 9px 16px; font-weight: 500; }}"
            f"QPushButton:hover {{ background: {COLORS['success_dark']}; }}"
        )
        btn_entrada.clicked.connect(self.abrir_nueva_entrada)
        header.addWidget(btn_entrada)

        btn_salida = QPushButton("📤 Nueva Salida")
        btn_salida.setFont(make_font(FONTS['body_bold']))
        btn_salida.setCursor(Qt.PointingHandCursor)
        btn_salida.setStyleSheet(
            f"QPushButton {{ background: {COLORS['danger']}; color: white; border: none; "
            f"border-radius: 9px; padding: 9px 16px; font-weight: 500; }}"
            f"QPushButton:hover {{ background: {COLORS['danger_dark']}; }}"
        )
        btn_salida.clicked.connect(self.abrir_nueva_salida)
        header.addWidget(btn_salida)

        btn_refresh = QPushButton("🔄 Actualizar")
        btn_refresh.setFont(make_font(FONTS['body']))
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.setObjectName("ghostBtn")
        btn_refresh.setMinimumHeight(38)
        btn_refresh.clicked.connect(self.cargar_historial)
        header.addWidget(btn_refresh)

        frame_layout.addLayout(header)

        # Filtros
        filtros_layout = QHBoxLayout()
        lbl_filtro = QLabel("Filtrar por tipo:")
        lbl_filtro.setFont(make_font(FONTS['body']))
        lbl_filtro.setStyleSheet("background: transparent;")
        filtros_layout.addWidget(lbl_filtro)

        self.filtro_tipo = QComboBox()
        self.filtro_tipo.setFont(make_font(FONTS['body']))
        self.filtro_tipo.addItems([
            'TODOS', 'ENTRADA_COMPRA', 'ENTRADA_DEVOLUCION', 'ENTRADA_AJUSTE',
            'SALIDA_VENTA', 'SALIDA_DEVOLUCION', 'SALIDA_MERMA',
            'SALIDA_DAÑADO', 'SALIDA_AJUSTE', 'EGRESO_CAJA',
            'CRÉDITOS VENTA (activos)', 'CRÉDITOS COMPRA (activos)'
        ])
        self.filtro_tipo.setCurrentText('TODOS')
        self.filtro_tipo.setFixedWidth(220)
        self.filtro_tipo.currentIndexChanged.connect(lambda: self.cargar_historial())
        filtros_layout.addWidget(self.filtro_tipo)

        # --- Filtro por rango de fechas ---
        self.chk_fecha = QCheckBox("📅 Por fecha:")
        self.chk_fecha.setFont(make_font(FONTS['body_bold']))
        self.chk_fecha.setStyleSheet(
            f"QCheckBox {{ background: transparent; color: {COLORS['primary']}; spacing: 6px; }}"
        )
        self.chk_fecha.stateChanged.connect(self._on_toggle_fecha)
        filtros_layout.addWidget(self.chk_fecha)

        hoy = QDate.currentDate()
        self.fecha_desde = QDateEdit()
        self.fecha_desde.setCalendarPopup(True)
        self.fecha_desde.setDisplayFormat("dd/MM/yyyy")
        self.fecha_desde.setDate(hoy.addDays(-30))
        self.fecha_desde.setFont(make_font(FONTS['body']))
        self.fecha_desde.setEnabled(False)
        self.fecha_desde.dateChanged.connect(lambda: self.cargar_historial())
        filtros_layout.addWidget(self.fecha_desde)

        lbl_a = QLabel("a")
        lbl_a.setFont(make_font(FONTS['body']))
        lbl_a.setStyleSheet("background: transparent;")
        filtros_layout.addWidget(lbl_a)

        self.fecha_hasta = QDateEdit()
        self.fecha_hasta.setCalendarPopup(True)
        self.fecha_hasta.setDisplayFormat("dd/MM/yyyy")
        self.fecha_hasta.setDate(hoy)
        self.fecha_hasta.setFont(make_font(FONTS['body']))
        self.fecha_hasta.setEnabled(False)
        self.fecha_hasta.dateChanged.connect(lambda: self.cargar_historial())
        filtros_layout.addWidget(self.fecha_hasta)

        self.chk_agrupar = QCheckBox("📋 Agrupar por Factura")
        self.chk_agrupar.setFont(make_font(FONTS['body_bold']))
        self.chk_agrupar.setChecked(True)
        self.chk_agrupar.setStyleSheet(
            f"QCheckBox {{ background: transparent; color: {COLORS['primary']}; spacing: 6px; }}"
        )
        self.chk_agrupar.stateChanged.connect(lambda: self.cargar_historial())
        filtros_layout.addWidget(self.chk_agrupar)
        filtros_layout.addStretch()

        frame_layout.addLayout(filtros_layout)

        # Tree widget (for grouped/hierarchical view and flat view)
        self.tree = QTreeWidget()
        self.tree.setStyleSheet(
            f"QTreeWidget {{ background: white; border: 1px solid {COLORS['border']};"
            f" border-radius: 12px; gridline-color: transparent; }}"
            "QTreeWidget::item { padding: 6px 4px; }"
            f"QTreeWidget::item:selected {{ background: {COLORS['table_selection']};"
            f" color: {COLORS['text_primary']}; }}"
            f"QHeaderView::section {{ background: {COLORS['table_header']};"
            f" color: {COLORS['table_header_fg']}; padding: 10px 8px;"
            " border: none; font-weight: 500; }"
        )
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(False)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.itemDoubleClicked.connect(self._on_tree_double_click)

        columnas = ['Fecha', 'Movimiento', 'Referencia', 'Resumen', 'Total', 'Usuario']
        self.tree.setHeaderLabels(columnas)
        anchos = [140, 150, 210, 360, 140, 140]
        for i, w in enumerate(anchos):
            self.tree.setColumnWidth(i, w)
        self.tree.header().setStretchLastSection(True)

        frame_layout.addWidget(self.tree, 1)

        main_layout.addWidget(main_frame)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _on_toggle_fecha(self):
        """Habilita/deshabilita los selectores de fecha y recarga."""
        activo = self.chk_fecha.isChecked()
        self.fecha_desde.setEnabled(activo)
        self.fecha_hasta.setEnabled(activo)
        self.cargar_historial()

    def _rango_fechas(self):
        """Devuelve (fecha_inicio, fecha_fin) en 'yyyy-MM-dd' si el filtro está activo."""
        if not self.chk_fecha.isChecked():
            return None, None
        fi = self.fecha_desde.date().toString('yyyy-MM-dd')
        ff = self.fecha_hasta.date().toString('yyyy-MM-dd')
        return fi, ff

    def _egreso_a_mov(self, e):
        """Convierte un egreso de caja en un dict con forma de movimiento."""
        cat = (e.get('categoria') or 'Egreso')
        desc = (e.get('descripcion') or '').strip()
        nombre = f"{cat} - {desc}" if desc else cat
        return {
            'id': e.get('id'),
            'fecha': e.get('fecha_egreso'),
            'tipo': 'EGRESO_CAJA',
            'producto_id': None,
            'producto_nombre': nombre,
            'categoria': cat,
            'descripcion': desc,
            'proveedor_id': None,
            'proveedor_nombre': '-',
            'cantidad': 0,
            'precio_unitario': 0,
            'costo_total': e.get('monto', 0) or 0,
            'num_factura': None,
            'usuario_nombre': e.get('usuario', 'Sistema'),
            'es_egreso': True,
        }

    def _fmt_fecha_corta(self, fecha):
        return str(fecha or 'N/A')[:16]

    def _recortar(self, texto, limite=70):
        texto = str(texto or '').strip()
        if not texto:
            return '-'
        return texto if len(texto) <= limite else texto[:limite - 1].rstrip() + '…'

    def _parse_ref_pago_proveedor(self, descripcion):
        descripcion = descripcion or ''
        proveedor = re.search(r'Pago a proveedor\s+(.+?)(?:\s+-\s+|$)', descripcion, re.IGNORECASE)
        compra = re.search(r'Compra\s+#?([A-Za-z0-9\-]+)', descripcion, re.IGNORECASE)
        factura = re.search(r'Factura\s+([A-Za-z0-9\-]+)', descripcion, re.IGNORECASE)
        abono = re.search(r'Abono\s+#?([A-Za-z0-9\-]+)', descripcion, re.IGNORECASE)
        return {
            'proveedor': proveedor.group(1).strip() if proveedor else None,
            'compra': compra.group(1).strip() if compra else None,
            'factura': factura.group(1).strip() if factura else None,
            'abono': abono.group(1).strip() if abono else None,
        }

    def _pago_compra_info(self, num_factura=None, compra_id=None):
        cache_key = (num_factura or '', compra_id or '')
        if not hasattr(self, '_pago_compra_cache'):
            self._pago_compra_cache = {}
        if cache_key in self._pago_compra_cache:
            return self._pago_compra_cache[cache_key]

        conn = self.db_manager.conectar()
        cursor = conn.cursor()
        try:
            if compra_id:
                cursor.execute('''
                    SELECT c.id, c.numero_factura, c.estado_pago, c.total,
                           c.monto_pagado, c.saldo_pendiente, p.nombre AS proveedor
                    FROM compras c
                    LEFT JOIN proveedores p ON p.id = c.proveedor_id
                    WHERE c.id = ?
                    LIMIT 1
                ''', (compra_id,))
            else:
                cursor.execute('''
                    SELECT c.id, c.numero_factura, c.estado_pago, c.total,
                           c.monto_pagado, c.saldo_pendiente, p.nombre AS proveedor
                    FROM compras c
                    LEFT JOIN proveedores p ON p.id = c.proveedor_id
                    WHERE c.numero_factura = ?
                    LIMIT 1
                ''', (num_factura,))
            row = cursor.fetchone()
            info = dict(row) if row else None
        finally:
            conn.close()
        self._pago_compra_cache[cache_key] = info
        return info

    def _pago_venta_info(self, num_factura):
        if not hasattr(self, '_pago_venta_cache'):
            self._pago_venta_cache = {}
        if num_factura in self._pago_venta_cache:
            return self._pago_venta_cache[num_factura]

        conn = self.db_manager.conectar()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT v.id, v.numero_factura, v.estado_pago, v.metodo_pago,
                       v.total, v.monto_pagado, c.nombre AS cliente
                FROM ventas v
                LEFT JOIN clientes c ON c.id = v.cliente_id
                WHERE v.numero_factura = ?
                LIMIT 1
            ''', (num_factura,))
            row = cursor.fetchone()
            info = dict(row) if row else None
            if info:
                total = info.get('total') or 0
                pagado = info.get('monto_pagado') or 0
                info['saldo_pendiente'] = max(total - pagado, 0)
        finally:
            conn.close()
        self._pago_venta_cache[num_factura] = info
        return info

    def _tiene_credito_pendiente(self, info):
        if not info:
            return False
        estado = (info.get('estado_pago') or '').upper()
        saldo = info.get('saldo_pendiente')
        if saldo is None:
            total = info.get('total') or 0
            pagado = info.get('monto_pagado') or 0
            saldo = max(total - pagado, 0)
        return saldo > 0 or estado in ('PENDIENTE', 'PARCIAL')

    def _obtener_abonos_venta_visual(self, fecha_inicio=None, fecha_fin=None,
                                     solo_creditos_activos=False):
        conn = self.db_manager.conectar()
        cursor = conn.cursor()
        query = '''
            SELECT a.id, a.id_venta, a.monto_abono, a.fecha_abono,
                   a.tipo_pago, a.usuario, v.numero_factura, v.estado_pago,
                   v.total, v.monto_pagado, c.nombre AS cliente
            FROM abonos_ventas a
            JOIN ventas v ON v.id = a.id_venta
            LEFT JOIN clientes c ON c.id = v.cliente_id
            WHERE 1=1
        '''
        params = []
        if fecha_inicio:
            query += " AND DATE(a.fecha_abono) >= DATE(?)"
            params.append(fecha_inicio)
        if fecha_fin:
            query += " AND DATE(a.fecha_abono) <= DATE(?)"
            params.append(fecha_fin)
        query += " ORDER BY a.fecha_abono DESC LIMIT 300"

        try:
            cursor.execute(query, params)
            rows = [dict(r) for r in cursor.fetchall()]
        except Exception:
            rows = []
        finally:
            conn.close()

        movimientos = []
        for row in rows:
            total = row.get('total') or 0
            pagado = row.get('monto_pagado') or 0
            saldo = max(total - pagado, 0)
            if solo_creditos_activos and saldo <= 0 and row.get('estado_pago') == 'PAGADO':
                continue
            movimientos.append({
                'id': row.get('id'),
                'fecha': row.get('fecha_abono'),
                'tipo': 'ABONO_VENTA',
                'producto_nombre': row.get('cliente') or 'Cliente General',
                'proveedor_nombre': '-',
                'cantidad': 0,
                'precio_unitario': 0,
                'costo_total': row.get('monto_abono') or 0,
                'num_factura': row.get('numero_factura'),
                'usuario_nombre': row.get('usuario') or 'Sistema',
                'estado_pago': row.get('estado_pago'),
                'saldo_pendiente': saldo,
                'es_abono_venta': True,
            })
        return movimientos

    def _fmt_cantidad_precio(self, mov):
        """(cantidad_str, precio_str) — los egresos no tienen cantidad/precio unit."""
        if mov.get('tipo') == 'EGRESO_CAJA':
            return '—', '—'
        return formatear_stock(mov['cantidad']), f"${mov['precio_unitario']:,.0f}"

    def cargar_historial(self):
        """Carga el historial de movimientos (con filtros de tipo y fecha)."""
        try:
            self.tree.clear()
            self._pago_compra_cache = {}
            self._pago_venta_cache = {}

            filtro = self.filtro_tipo.currentText()
            fi, ff = self._rango_fechas()

            if filtro == 'EGRESO_CAJA':
                egresos = self.movimientos_service.obtener_egresos(fi, ff, 500)
                movimientos = [self._egreso_a_mov(e) for e in egresos]
            elif filtro.startswith('CR') and 'VENTA' in filtro:
                movs = self.movimientos_service.obtener_historial(
                    tipo='SALIDA_VENTA', fecha_inicio=fi, fecha_fin=ff, limite=500)
                movimientos = [m for m in movs
                               if self._venta_es_credito_activo(m.get('num_factura'))]
                movimientos += self._obtener_abonos_venta_visual(
                    fi, ff, solo_creditos_activos=True)
                movimientos.sort(key=lambda m: m.get('fecha') or '', reverse=True)
            elif filtro.startswith('CR') and 'COMPRA' in filtro:
                movs = self.movimientos_service.obtener_historial(
                    tipo='ENTRADA_COMPRA', fecha_inicio=fi, fecha_fin=ff, limite=500)
                movimientos = [m for m in movs
                               if self._obtener_estado_pago_compra(m.get('num_factura'))
                               in ('PENDIENTE', 'PARCIAL')]
            else:
                tipo_filtro = None if filtro == 'TODOS' else filtro
                movimientos = self.movimientos_service.obtener_historial(
                    tipo=tipo_filtro, fecha_inicio=fi, fecha_fin=ff, limite=500)
                # En la vista "TODOS" también incluimos los egresos de caja.
                if filtro == 'TODOS':
                    egresos = self.movimientos_service.obtener_egresos(fi, ff, 500)
                    abonos_venta = self._obtener_abonos_venta_visual(fi, ff)
                    movimientos = (
                        movimientos
                        + [self._egreso_a_mov(e) for e in egresos]
                        + abonos_venta
                    )
                    movimientos.sort(key=lambda m: m.get('fecha') or '', reverse=True)

            if self.chk_agrupar.isChecked():
                self.mostrar_agrupado_por_factura(movimientos)
            else:
                self.mostrar_lista_normal(movimientos)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error cargando historial:\n{str(e)}")
            import traceback
            traceback.print_exc()

    # ------------------------------------------------------------------
    # Helpers for payment state
    # ------------------------------------------------------------------

    def _obtener_estado_pago_compra(self, num_factura):
        """Obtiene el estado de pago de una compra por número de factura"""
        try:
            if not self.compras_repo or not num_factura:
                return None
            compras = self.compras_repo.listar_compras_recientes(dias=365, limite=1000)
            for compra in compras:
                if compra.get('numero_factura') == num_factura:
                    return compra.get('estado_pago')
            return None
        except Exception as e:
            print(f"Error obteniendo estado de pago: {e}")
            return None

    def _obtener_estado_pago_venta(self, num_factura):
        """Obtiene el estado de pago de una venta por número de factura."""
        try:
            if not num_factura:
                return None
            conn = self.db_manager.conectar()
            cursor = conn.cursor()
            cursor.execute(
                '''SELECT estado_pago, metodo_pago, total, monto_pagado
                   FROM ventas WHERE numero_factura = ? LIMIT 1''',
                (num_factura,))
            row = cursor.fetchone()
            conn.close()
            if not row:
                return None
            if hasattr(row, 'keys'):
                estado_pago = row['estado_pago']
                metodo_pago = row['metodo_pago']
                total = row['total'] or 0
                monto_pagado = row['monto_pagado'] or 0
            else:
                estado_pago, metodo_pago, total, monto_pagado = row
                total = total or 0
                monto_pagado = monto_pagado or 0
            if metodo_pago != 'CREDITO':
                return 'PAGADO'
            if monto_pagado >= total and total > 0:
                return 'PAGADO'
            return estado_pago or 'PENDIENTE'
        except Exception as e:
            print(f"Error obteniendo estado de pago de venta: {e}")
            return None

    def _venta_es_credito_activo(self, num_factura):
        try:
            if not num_factura:
                return False
            conn = self.db_manager.conectar()
            cursor = conn.cursor()
            cursor.execute(
                '''SELECT estado_pago, metodo_pago, total, monto_pagado
                   FROM ventas WHERE numero_factura = ? LIMIT 1''',
                (num_factura,))
            row = cursor.fetchone()
            conn.close()
            if not row:
                return False
            if hasattr(row, 'keys'):
                metodo_pago = row['metodo_pago']
                estado_pago = row['estado_pago']
                total = row['total'] or 0
                monto_pagado = row['monto_pagado'] or 0
            else:
                estado_pago, metodo_pago, total, monto_pagado = row
                total = total or 0
                monto_pagado = monto_pagado or 0
            if metodo_pago != 'CREDITO':
                return False
            if total > 0 and monto_pagado >= total:
                return False
            return (estado_pago or 'PENDIENTE') in ('PENDIENTE', 'PARCIAL')
        except Exception as e:
            print(f"Error validando crédito de venta: {e}")
            return False

    def _obtener_tag_por_estado(self, estado_pago):
        """Retorna el tag de color según el estado de pago"""
        if not estado_pago:
            return 'entrada'
        estado_map = {
            'PENDIENTE': 'estado_pendiente',
            'PARCIAL': 'estado_parcial',
            'PAGADO': 'estado_pagado',
        }
        return estado_map.get(estado_pago, 'entrada')

    def _color_for_tag(self, tag):
        """Return (bg QColor, fg QColor) for a given tag name."""
        mapping = {
            'entrada': (QColor('#eafaf2'), QColor('#334155')),
            'salida': (QColor('#fef6f6'), QColor('#334155')),
            'estado_pendiente': (QColor('#fff7cc'), QColor('#5f4300')),
            'estado_parcial': (QColor('#fff7cc'), QColor('#5f4300')),
            'credito_pendiente': (QColor('#fff7cc'), QColor('#5f4300')),
            'estado_pagado': (QColor('#eaf3de'), QColor('#3b6d11')),
            'factura': (QColor('#e6f1fb'), QColor('#185fa5')),
            'detalle': (QColor('#ffffff'), QColor('#334155')),
            'egreso': (QColor('#fdeede'), QColor('#9a5b0a')),
        }
        return mapping.get(tag, (QColor('#ffffff'), QColor('#000000')))

    def _apply_row_colors(self, item: QTreeWidgetItem, tags):
        """Apply background/foreground colors to all columns of a QTreeWidgetItem."""
        bg, fg = QColor('#ffffff'), QColor('#000000')
        for t in tags:
            b, f = self._color_for_tag(t)
            bg, fg = b, f
        col_count = self.tree.columnCount()
        for c in range(col_count):
            item.setBackground(c, QBrush(bg))
            item.setForeground(c, QBrush(fg))

    def _set_item_meta(self, item, **meta):
        item.setData(0, Qt.UserRole, meta)

    def _info_pago_mov(self, mov):
        tipo = mov.get('tipo')
        factura = mov.get('num_factura')
        if tipo in ('SALIDA_VENTA', 'ABONO_VENTA') and factura:
            return self._pago_venta_info(factura)
        if tipo == 'ENTRADA_COMPRA' and factura:
            return self._pago_compra_info(num_factura=factura)
        if tipo == 'EGRESO_CAJA':
            ref = self._parse_ref_pago_proveedor(mov.get('descripcion') or mov.get('producto_nombre'))
            if ref.get('compra') or ref.get('factura'):
                return self._pago_compra_info(ref.get('factura'), ref.get('compra'))
        return None

    def _movimiento_label(self, mov, pago_info=None):
        tipo = mov.get('tipo')
        if tipo == 'SALIDA_VENTA':
            return 'Crédito venta' if self._tiene_credito_pendiente(pago_info) else 'Salida'
        if tipo == 'ENTRADA_COMPRA':
            return 'Crédito compra' if self._tiene_credito_pendiente(pago_info) else 'Entrada'
        if tipo == 'ABONO_VENTA':
            return 'Abono crédito' if self._tiene_credito_pendiente(pago_info) else 'Crédito liquidado'
        if tipo == 'EGRESO_CAJA':
            categoria = (mov.get('categoria') or '').lower()
            descripcion = (mov.get('descripcion') or '').lower()
            return 'Pago proveedor' if 'proveedor' in categoria or 'pago a proveedor' in descripcion else 'Egreso'
        if 'ENTRADA' in str(tipo):
            return 'Entrada'
        if 'SALIDA' in str(tipo):
            return 'Salida'
        return 'Otro'

    def _referencia_mov(self, mov):
        tipo = mov.get('tipo')
        factura = mov.get('num_factura')
        if tipo in ('SALIDA_VENTA', 'ABONO_VENTA') and factura:
            return f"Venta {factura}"
        if tipo == 'ENTRADA_COMPRA' and factura:
            info = self._pago_compra_info(num_factura=factura)
            compra_id = info.get('id') if info else None
            return f"Compra #{compra_id} / Factura {factura}" if compra_id else f"Compra {factura}"
        if tipo == 'EGRESO_CAJA':
            ref = self._parse_ref_pago_proveedor(mov.get('descripcion') or '')
            if ref.get('compra') or ref.get('factura'):
                partes = []
                if ref.get('compra'):
                    partes.append(f"Compra #{ref['compra']}")
                if ref.get('factura'):
                    partes.append(f"Factura {ref['factura']}")
                if ref.get('abono'):
                    partes.append(f"Abono #{ref['abono']}")
                return ' / '.join(partes)
            return f"Egreso #{mov.get('id')}"
        return factura or '-'

    def _resumen_mov(self, mov, cantidad_productos=1, pago_info=None):
        tipo = mov.get('tipo')
        if tipo == 'SALIDA_VENTA':
            if self._tiene_credito_pendiente(pago_info):
                return 'Venta a crédito pendiente'
            cliente = (pago_info or {}).get('cliente')
            return f"Venta a {cliente}" if cliente else f"Venta de {cantidad_productos} producto(s)"
        if tipo == 'ENTRADA_COMPRA':
            proveedor = (pago_info or {}).get('proveedor') or mov.get('proveedor_nombre')
            if self._tiene_credito_pendiente(pago_info):
                return 'Compra a crédito pendiente'
            return f"Compra a proveedor {proveedor}" if proveedor else 'Entrada de inventario'
        if tipo == 'ABONO_VENTA':
            return ('Abono parcial recibido' if self._tiene_credito_pendiente(pago_info)
                    else 'Venta pagada completamente')
        if tipo == 'EGRESO_CAJA':
            desc = mov.get('descripcion') or ''
            ref = self._parse_ref_pago_proveedor(desc)
            if ref.get('proveedor'):
                return self._recortar(f"Abono a proveedor {ref['proveedor']}")
            return self._recortar(mov.get('categoria') or desc or 'Egreso de caja')
        return self._recortar(mov.get('producto_nombre') or str(tipo).replace('_', ' ').title())

    def _tags_mov(self, mov, pago_info=None):
        tipo = mov.get('tipo')
        if self._tiene_credito_pendiente(pago_info):
            return ['credito_pendiente']
        if tipo == 'ABONO_VENTA' and pago_info and (pago_info.get('estado_pago') or '').upper() == 'PAGADO':
            return ['estado_pagado']
        if tipo == 'EGRESO_CAJA':
            return ['egreso']
        return ['entrada' if 'ENTRADA' in str(tipo) else 'salida']

    def _valores_compactos(self, mov, cantidad_productos=1, total=None, fecha=None):
        pago_info = self._info_pago_mov(mov)
        monto = mov.get('costo_total') if total is None else total
        if mov.get('tipo') == 'EGRESO_CAJA':
            monto = -abs(monto or 0)
        return [
            self._fmt_fecha_corta(fecha or mov.get('fecha')),
            self._movimiento_label(mov, pago_info),
            self._referencia_mov(mov),
            self._resumen_mov(mov, cantidad_productos, pago_info),
            self._money_cop(monto or 0),
            mov.get('usuario_nombre') or 'Sistema',
        ], self._tags_mov(mov, pago_info)

    # ------------------------------------------------------------------
    # Flat list view
    # ------------------------------------------------------------------

    def mostrar_lista_normal(self, movimientos):
        """Muestra movimientos en lista normal (flat)"""
        self.tree.setRootIsDecorated(False)

        for mov in movimientos:
            values, tags = self._valores_compactos(mov)
            tw_item = QTreeWidgetItem(values)
            tw_item.setTextAlignment(4, Qt.AlignRight | Qt.AlignVCenter)
            self._set_item_meta(
                tw_item,
                tipo=mov.get('tipo'),
                mov_id=mov.get('id'),
                num_factura=mov.get('num_factura'),
                egreso_id=mov.get('id') if mov.get('tipo') == 'EGRESO_CAJA' else None,
            )
            self._apply_row_colors(tw_item, tags)
            self.tree.addTopLevelItem(tw_item)

    # ------------------------------------------------------------------
    # Grouped (hierarchical) view
    # ------------------------------------------------------------------

    def _agregar_egreso_como_factura(self, e):
        """Renderiza un egreso de caja como una factura de salida de dinero,
        con el mismo formato que una venta/compra (fila padre + detalle)."""
        parent_values, tags = self._valores_compactos(e)
        parent = QTreeWidgetItem(parent_values)
        parent.setFont(1, make_font(FONTS['body_bold']))
        parent.setTextAlignment(4, Qt.AlignRight | Qt.AlignVCenter)
        self._set_item_meta(parent, tipo='EGRESO_CAJA', egreso_id=e.get('id'), mov_id=e.get('id'))
        self._apply_row_colors(parent, tags)
        self.tree.addTopLevelItem(parent)

        child = QTreeWidgetItem(parent_values)
        child.setTextAlignment(4, Qt.AlignRight | Qt.AlignVCenter)
        self._set_item_meta(child, tipo='EGRESO_CAJA', egreso_id=e.get('id'), mov_id=e.get('id'))
        self._apply_row_colors(child, tags)
        parent.addChild(child)

    def mostrar_agrupado_por_factura(self, movimientos):
        """Muestra movimientos agrupados por número de factura usando QTreeWidget"""
        self.tree.setRootIsDecorated(True)

        por_factura = defaultdict(list)
        sin_factura = []
        egresos_list = []

        for mov in movimientos:
            if mov.get('tipo') == 'COBRO_CREDITO':
                continue
            if mov.get('tipo') == 'EGRESO_CAJA':
                egresos_list.append(mov)
                continue
            num_factura = mov.get('num_factura')
            if num_factura:
                por_factura[num_factura].append(mov)
            else:
                sin_factura.append(mov)

        grupos_render = []
        for e in egresos_list:
            grupos_render.append(('egreso', e.get('fecha') or '', e))
        for num_factura, items in por_factura.items():
            fecha_grupo = max((item.get('fecha') or '' for item in items), default='')
            grupos_render.append(('factura', fecha_grupo, (num_factura, items)))

        # Egresos y facturas se ordenan juntos por fecha. Antes los egresos se
        # pintaban primero y empujaban ventas/compras fuera del primer vistazo.
        for tipo_grupo, _fecha_grupo, payload in sorted(
            grupos_render, key=lambda item: item[1], reverse=True
        ):
            if tipo_grupo == 'egreso':
                self._agregar_egreso_como_factura(payload)
                continue

            num_factura, items = payload
            if not items:
                continue

            inventario_items = [item for item in items if item.get('tipo') != 'ABONO_VENTA']
            total_factura = sum(item['costo_total'] for item in inventario_items)
            cantidad_productos = len(inventario_items) or len(items)
            latest_item = max(items, key=lambda item: item.get('fecha') or '')
            fecha_factura = latest_item.get('fecha') or items[0].get('fecha')
            tipo_principal = (inventario_items[0] if inventario_items else items[0])['tipo']
            base_tag = 'entrada' if 'ENTRADA' in tipo_principal else 'salida'
            total_mostrar = None if latest_item.get('tipo') == 'ABONO_VENTA' else total_factura
            parent_values, tags_factura = self._valores_compactos(
                latest_item,
                cantidad_productos=cantidad_productos,
                total=total_mostrar,
                fecha=fecha_factura,
            )
            parent_item = QTreeWidgetItem(parent_values)
            parent_item.setFont(1, make_font(FONTS['body_bold']))
            parent_item.setTextAlignment(4, Qt.AlignRight | Qt.AlignVCenter)
            self._set_item_meta(parent_item, tipo=tipo_principal, num_factura=num_factura)
            self._apply_row_colors(parent_item, tags_factura)
            self.tree.addTopLevelItem(parent_item)
            parent_item.setExpanded(False)

            for mov in items:
                child_values, child_tags = self._valores_compactos(mov)
                child_item = QTreeWidgetItem(child_values)
                child_item.setTextAlignment(4, Qt.AlignRight | Qt.AlignVCenter)
                self._set_item_meta(
                    child_item,
                    tipo=mov.get('tipo'),
                    mov_id=mov.get('id'),
                    num_factura=mov.get('num_factura'),
                )
                self._apply_row_colors(child_item, child_tags)
                parent_item.addChild(child_item)

        # Movimientos sin factura agrupados por tipo y minuto
        if sin_factura:
            grupos_sf = defaultdict(list)
            for mov in sin_factura:
                fecha_min = mov['fecha'][:16] if mov.get('fecha') else 'N/A'
                tipo_lbl = mov['tipo'].replace('_', ' ')
                clave = (tipo_lbl, fecha_min)
                grupos_sf[clave].append(mov)

            for (tipo_lbl, fecha_min), items in sorted(grupos_sf.items(), key=lambda x: x[0][1], reverse=True):
                if not items:
                    continue

                cantidad_productos = len(items)
                tipo_principal = items[0]['tipo']
                total_grupo = sum(item.get('costo_total') or 0 for item in items)
                parent_values, parent_tags = self._valores_compactos(
                    items[0],
                    cantidad_productos=cantidad_productos,
                    total=total_grupo,
                    fecha=fecha_min,
                )
                parent_item = QTreeWidgetItem(parent_values)
                parent_item.setFont(1, make_font(FONTS['body_bold']))
                parent_item.setTextAlignment(4, Qt.AlignRight | Qt.AlignVCenter)
                self._set_item_meta(parent_item, tipo=tipo_principal)
                self._apply_row_colors(parent_item, parent_tags)
                self.tree.addTopLevelItem(parent_item)

                for mov in items:
                    child_values, child_tags = self._valores_compactos(mov)
                    child_item = QTreeWidgetItem(child_values)
                    child_item.setTextAlignment(4, Qt.AlignRight | Qt.AlignVCenter)
                    self._set_item_meta(
                        child_item,
                        tipo=mov.get('tipo'),
                        mov_id=mov.get('id'),
                        num_factura=mov.get('num_factura'),
                        egreso_id=mov.get('id') if mov.get('tipo') == 'EGRESO_CAJA' else None,
                    )
                    self._apply_row_colors(child_item, child_tags)
                    parent_item.addChild(child_item)

    # ------------------------------------------------------------------
    # Navigation: new entrada / salida
    # ------------------------------------------------------------------

    def abrir_nueva_entrada(self):
        """Abre ventana para registrar nueva entrada"""
        from ui.entrada_inventario_ui import EntradaInventarioUI
        dialog = EntradaInventarioUI(
            self.parent_widget,
            self.inventario_repo,
            self.productos_repo,
            self.proveedores_repo,
            self.auth,
            self.db_manager,
            self.alertas_service,
        )
        if hasattr(dialog, 'ventana') and isinstance(dialog.ventana, QDialog):
            dialog.ventana.exec()
        elif hasattr(dialog, 'ventana'):
            dialog.ventana.exec()
        self.cargar_historial()

    def abrir_nueva_salida(self):
        """Abre ventana para registrar nueva salida"""
        self.abrir_formulario_movimiento(es_entrada=False)

    # ------------------------------------------------------------------
    # Formulario movimiento (salidas / entradas manuales)
    # ------------------------------------------------------------------

    def abrir_formulario_movimiento(self, es_entrada=True):
        """Abre formulario para registrar movimiento"""
        dialog = QDialog(self.window())
        dialog.setWindowTitle(f"{'Entrada' if es_entrada else 'Salida'} de Inventario")
        dialog.setFixedSize(600, 700)
        dialog.setStyleSheet("background: white;")

        dlg_layout = QVBoxLayout(dialog)
        dlg_layout.setContentsMargins(0, 0, 0, 0)
        dlg_layout.setSpacing(0)

        # Header
        color_header = COLORS['success'] if es_entrada else COLORS['danger']
        header = QFrame()
        header.setFixedHeight(60)
        header.setStyleSheet(f"background: {color_header};")
        h_layout = QHBoxLayout(header)
        h_label = QLabel(f"{'📥 Nueva Entrada' if es_entrada else '📤 Nueva Salida'}")
        h_label.setFont(make_font(FONTS['large']))
        h_label.setStyleSheet("color: white; background: transparent;")
        h_label.setAlignment(Qt.AlignCenter)
        h_layout.addWidget(h_label)
        dlg_layout.addWidget(header)

        # Scrollable form area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: white; }")
        form_widget = QWidget()
        form_widget.setStyleSheet("background: white;")
        form_layout = QVBoxLayout(form_widget)
        form_layout.setContentsMargins(30, 20, 30, 20)
        form_layout.setSpacing(5)

        # Tipo de movimiento
        form_layout.addWidget(self._lbl("Tipo de movimiento *"))
        if es_entrada:
            tipos = ['ENTRADA_COMPRA', 'ENTRADA_DEVOLUCION', 'ENTRADA_AJUSTE']
        else:
            tipos = ['SALIDA_VENTA', 'SALIDA_DEVOLUCION', 'SALIDA_MERMA',
                     'SALIDA_DAÑADO', 'SALIDA_AJUSTE']
        tipo_combo = QComboBox()
        tipo_combo.setFont(make_font(FONTS['body']))
        tipo_combo.addItems(tipos)
        form_layout.addWidget(tipo_combo)

        # Producto
        form_layout.addWidget(self._lbl("Producto *"))
        prod_row = QHBoxLayout()
        producto_entry = QLineEdit()
        producto_entry.setFont(make_font(FONTS['body']))
        producto_entry.setReadOnly(True)
        producto_entry.setPlaceholderText("Seleccione un producto...")
        prod_row.addWidget(producto_entry, 1)

        stock_label = QLabel("")
        stock_label.setFont(make_font(FONTS['body_bold']))
        stock_label.setStyleSheet(f"color: {COLORS['info']}; background: transparent;")

        precio_var = [0.0]  # mutable container for price

        btn_buscar_prod = QPushButton("Buscar")
        btn_buscar_prod.setFont(make_font(FONTS['body']))
        btn_buscar_prod.setCursor(Qt.PointingHandCursor)
        btn_buscar_prod.setStyleSheet(
            f"QPushButton {{ background: {COLORS['info']}; color: white; border: none; "
            f"border-radius: 4px; padding: 6px 14px; }}"
        )
        btn_buscar_prod.clicked.connect(
            lambda: self.buscar_producto(producto_entry, stock_label, precio_var, precio_entry, es_entrada)
        )
        prod_row.addWidget(btn_buscar_prod)
        form_layout.addLayout(prod_row)

        # Stock label (only for salidas)
        if not es_entrada:
            form_layout.addWidget(stock_label)

        # Proveedor (only for entradas)
        proveedor_entry = QLineEdit()
        proveedor_entry.setFont(make_font(FONTS['body']))
        proveedor_entry.setReadOnly(True)
        proveedor_entry.setPlaceholderText("Seleccione un proveedor...")

        proveedor_container = QWidget()
        proveedor_container.setStyleSheet("background: transparent;")
        prov_v = QVBoxLayout(proveedor_container)
        prov_v.setContentsMargins(0, 0, 0, 0)
        prov_v.addWidget(self._lbl("Proveedor"))
        prov_row = QHBoxLayout()
        prov_row.addWidget(proveedor_entry, 1)
        btn_buscar_prov = QPushButton("Buscar")
        btn_buscar_prov.setFont(make_font(FONTS['body']))
        btn_buscar_prov.setCursor(Qt.PointingHandCursor)
        btn_buscar_prov.setStyleSheet(
            f"QPushButton {{ background: {COLORS['info']}; color: white; border: none; "
            f"border-radius: 4px; padding: 6px 14px; }}"
        )
        btn_buscar_prov.clicked.connect(lambda: self.buscar_proveedor(proveedor_entry))
        prov_row.addWidget(btn_buscar_prov)
        prov_v.addLayout(prov_row)

        if es_entrada:
            form_layout.addWidget(proveedor_container)

            def actualizar_campos_proveedor():
                proveedor_container.setVisible(tipo_combo.currentText() == 'ENTRADA_COMPRA')

            tipo_combo.currentTextChanged.connect(lambda t: actualizar_campos_proveedor())
            actualizar_campos_proveedor()

        # Cantidad
        form_layout.addWidget(self._lbl("Cantidad *"))
        cantidad_entry = QLineEdit("1")
        cantidad_entry.setFont(make_font(FONTS['body']))
        form_layout.addWidget(cantidad_entry)

        # Entrada en cajas (solo para entradas)
        cajas_container = QWidget()
        cajas_container.setStyleSheet("background: transparent;")
        cajas_v = QVBoxLayout(cajas_container)
        cajas_v.setContentsMargins(0, 0, 0, 0)

        unidades_por_caja_entry = QLineEdit("1")
        unidades_por_caja_entry.setFont(make_font(FONTS['body']))
        num_cajas_entry = QLineEdit("1")
        num_cajas_entry.setFont(make_font(FONTS['body']))
        total_cajas_label = QLabel("Total: 1 unidades")
        total_cajas_label.setFont(make_font(FONTS['body_bold']))
        total_cajas_label.setStyleSheet(f"color: {COLORS['primary']}; background: transparent;")

        row_unid = QHBoxLayout()
        lbl_u = QLabel("Unidades por caja:")
        lbl_u.setFont(make_font(FONTS['body']))
        lbl_u.setFixedWidth(140)
        lbl_u.setStyleSheet("background: transparent;")
        row_unid.addWidget(lbl_u)
        row_unid.addWidget(unidades_por_caja_entry)
        cajas_v.addLayout(row_unid)

        row_nc = QHBoxLayout()
        lbl_nc = QLabel("Número de cajas:")
        lbl_nc.setFont(make_font(FONTS['body']))
        lbl_nc.setFixedWidth(140)
        lbl_nc.setStyleSheet("background: transparent;")
        row_nc.addWidget(lbl_nc)
        row_nc.addWidget(num_cajas_entry)
        cajas_v.addLayout(row_nc)

        cajas_v.addWidget(total_cajas_label)
        cajas_container.setVisible(False)

        en_cajas_check = None
        if es_entrada:
            en_cajas_check = QCheckBox("Entrada en cajas")
            en_cajas_check.setFont(make_font(FONTS['body']))
            en_cajas_check.setStyleSheet("background: transparent;")

            def toggle_cajas(state):
                cajas_container.setVisible(bool(state))
                if state:
                    try:
                        u = int(unidades_por_caja_entry.text())
                        c = int(num_cajas_entry.text())
                        cantidad_entry.setText(str(u * c))
                    except ValueError:
                        pass
                else:
                    cantidad_entry.setText("1")

            en_cajas_check.stateChanged.connect(toggle_cajas)
            form_layout.addWidget(en_cajas_check)
            form_layout.addWidget(cajas_container)

            def actualizar_total_cajas():
                try:
                    u = int(unidades_por_caja_entry.text())
                    c = int(num_cajas_entry.text())
                    total = u * c
                    total_cajas_label.setText(f"Total: {total} unidades")
                    cantidad_entry.setText(str(total))
                except ValueError:
                    total_cajas_label.setText("Total: - unidades")

            unidades_por_caja_entry.textChanged.connect(lambda: actualizar_total_cajas())
            num_cajas_entry.textChanged.connect(lambda: actualizar_total_cajas())

        # Precio unitario
        precio_label_text = f"Precio unitario * ({'Compra' if es_entrada else 'Venta'})"
        form_layout.addWidget(self._lbl(precio_label_text))
        precio_entry = QLineEdit("0")
        precio_entry.setFont(make_font(FONTS['body']))
        precio_entry.setReadOnly(True)
        form_layout.addWidget(precio_entry)

        precio_info = QLabel("💡 El precio se completa automáticamente al seleccionar el producto")
        precio_info.setFont(make_font(FONTS['small']))
        precio_info.setStyleSheet(f"color: {COLORS['text_light']}; background: transparent;")
        form_layout.addWidget(precio_info)

        # Número de factura
        form_layout.addWidget(self._lbl("Número de factura (opcional)"))
        factura_entry = QLineEdit()
        factura_entry.setFont(make_font(FONTS['body']))
        form_layout.addWidget(factura_entry)

        # Total calculado
        total_compra_label = QLabel("")
        total_compra_label.setFont(make_font(FONTS['body_bold']))
        total_compra_label.setStyleSheet(f"color: {COLORS['primary']}; background: transparent;")
        form_layout.addWidget(total_compra_label)

        def actualizar_total_compra():
            try:
                cant = int(cantidad_entry.text())
                precio = float(precio_entry.text())
                total = cant * precio
                total_compra_label.setText(f"💰 Total: ${total:,.0f}")
            except (ValueError, TypeError):
                total_compra_label.setText("")

        cantidad_entry.textChanged.connect(lambda: actualizar_total_compra())
        precio_entry.textChanged.connect(lambda: actualizar_total_compra())

        form_layout.addStretch()
        scroll.setWidget(form_widget)
        dlg_layout.addWidget(scroll, 1)

        # Botones al fondo
        btn_frame = QFrame()
        btn_frame.setStyleSheet("background: white;")
        btn_h = QHBoxLayout(btn_frame)
        btn_h.setContentsMargins(30, 10, 30, 15)

        btn_guardar = QPushButton("💾 Guardar")
        btn_guardar.setFont(make_font(FONTS['body_bold']))
        btn_guardar.setCursor(Qt.PointingHandCursor)
        btn_guardar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['success']}; color: white; border: none; "
            f"border-radius: 6px; padding: 12px 20px; }}"
            f"QPushButton:hover {{ background: {COLORS['success_dark']}; }}"
        )
        btn_guardar.clicked.connect(lambda: self.guardar_movimiento_mejorado(
            dialog,
            tipo_combo.currentText(),
            producto_entry,
            proveedor_entry,
            cantidad_entry,
            en_cajas_check,
            unidades_por_caja_entry,
            num_cajas_entry,
            precio_entry,
            factura_entry,
            es_entrada,
            stock_label,
        ))
        btn_h.addWidget(btn_guardar, 1)

        btn_cancelar = QPushButton("❌ Cancelar")
        btn_cancelar.setFont(make_font(FONTS['body']))
        btn_cancelar.setCursor(Qt.PointingHandCursor)
        btn_cancelar.setStyleSheet(
            f"QPushButton {{ background: {COLORS['danger']}; color: white; border: none; "
            f"border-radius: 6px; padding: 12px 20px; }}"
            f"QPushButton:hover {{ background: {COLORS['danger_dark']}; }}"
        )
        btn_cancelar.clicked.connect(dialog.reject)
        btn_h.addWidget(btn_cancelar, 1)

        dlg_layout.addWidget(btn_frame)
        from ui.widgets import hacer_dialogo_responsivo
        hacer_dialogo_responsivo(dialog, 600, 700)
        dialog.exec()

    def _lbl(self, text):
        """Helper: create a styled form label."""
        lbl = QLabel(text)
        lbl.setFont(make_font(FONTS['body']))
        lbl.setStyleSheet("background: transparent; padding-top: 8px;")
        return lbl

    # ------------------------------------------------------------------
    # Toggle cajas
    # ------------------------------------------------------------------

    def toggle_cajas_mejorado(self, en_cajas_var, cajas_frame, unidades_var, num_cajas_var, cantidad_var):
        """Muestra/oculta campos de cajas y calcula total"""
        if en_cajas_var.get():
            cajas_frame.setVisible(True)
            try:
                unidades = int(unidades_var.text())
                cajas = int(num_cajas_var.text())
                cantidad_var.setText(str(unidades * cajas))
            except ValueError:
                pass
        else:
            cajas_frame.setVisible(False)
            cantidad_var.setText("1")

    # ------------------------------------------------------------------
    # Search popups
    # ------------------------------------------------------------------

    def buscar_producto(self, producto_entry, stock_label, precio_var, precio_entry, es_entrada):
        """Abre ventana de búsqueda de producto"""
        dialog = QDialog(self.window())
        dialog.setWindowTitle("Buscar Producto")
        dialog.resize(800, 600)
        dialog.setStyleSheet("background: white;")

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)

        # Search bar
        search_row = QHBoxLayout()
        lbl = QLabel("Buscar:")
        lbl.setFont(make_font(FONTS['body']))
        search_row.addWidget(lbl)
        search_entry = QLineEdit()
        search_entry.setFont(make_font(FONTS['body']))
        search_entry.setPlaceholderText("Escriba para buscar...")
        search_row.addWidget(search_entry, 1)
        layout.addLayout(search_row)

        # Table
        table = QTableWidget()
        table.setColumnCount(6)
        table.setHorizontalHeaderLabels(['ID', 'Código', 'Nombre', 'Stock', 'P. Compra', 'P. Venta'])
        table.horizontalHeader().setStyleSheet(
            f"QHeaderView::section {{ background: {COLORS['table_header']}; color: {COLORS['table_header_fg']}; padding: 9px 8px; border: none; font-weight: 500; }}"
        )
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setStyleSheet("QTableWidget { gridline-color: #e5e7eb; }")
        table.setColumnWidth(0, 50)
        table.setColumnWidth(1, 100)
        table.setColumnWidth(2, 250)
        table.setColumnWidth(3, 70)
        table.setColumnWidth(4, 100)
        table.setColumnWidth(5, 100)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        layout.addWidget(table, 1)

        def buscar():
            termino = search_entry.text().strip()
            try:
                productos = self.productos_repo.buscar_productos(termino)
                table.setRowCount(0)
                for p in productos:
                    row = table.rowCount()
                    table.insertRow(row)
                    table.setItem(row, 0, QTableWidgetItem(str(p['id'])))
                    table.setItem(row, 1, QTableWidgetItem(p['codigo_barras'] or 'N/A'))
                    table.setItem(row, 2, QTableWidgetItem(p['nombre']))
                    table.setItem(row, 3, QTableWidgetItem(formatear_stock(p['stock'], p.get('permite_decimales'))))
                    table.setItem(row, 4, QTableWidgetItem(f"${p.get('precio_compra', 0):,.0f}"))
                    table.setItem(row, 5, QTableWidgetItem(f"${p['precio_venta']:,.0f}"))
            except Exception as e:
                QMessageBox.critical(dialog, "Error", f"Error buscando productos:\n{str(e)}")

        search_entry.textChanged.connect(lambda: buscar())
        buscar()

        def seleccionar():
            row = table.currentRow()
            if row < 0:
                QMessageBox.warning(dialog, "Advertencia", "Seleccione un producto")
                return

            prod_id = int(table.item(row, 0).text())
            prod_nombre = table.item(row, 2).text()
            stock = int(table.item(row, 3).text())
            precio_compra = float(table.item(row, 4).text().replace('$', '').replace(',', ''))
            precio_venta = float(table.item(row, 5).text().replace('$', '').replace(',', ''))

            self.producto_seleccionado = prod_id
            producto_entry.setText(f"{prod_nombre} (ID: {prod_id})")

            self.producto_seleccionado_data = {
                'id': prod_id,
                'nombre': prod_nombre,
                'stock': stock,
                'precio_compra': precio_compra,
                'precio_venta': precio_venta,
            }

            if es_entrada:
                precio_var[0] = precio_compra
                precio_entry.setReadOnly(False)
                precio_entry.setText(str(precio_compra))
                precio_entry.setReadOnly(True)
            else:
                stock_label.setText(f"📦 Stock disponible: {formatear_stock(stock)} unidades")
                if stock <= 0:
                    stock_label.setStyleSheet(f"color: {COLORS['danger']}; background: transparent;")
                else:
                    stock_label.setStyleSheet(f"color: {COLORS['info']}; background: transparent;")
                precio_var[0] = precio_venta
                precio_entry.setReadOnly(False)
                precio_entry.setText(str(precio_venta))
                precio_entry.setReadOnly(True)

            dialog.accept()

        table.cellDoubleClicked.connect(lambda r, c: seleccionar())

        btn_sel = QPushButton("✅ Seleccionar")
        btn_sel.setFont(make_font(FONTS['body']))
        btn_sel.setCursor(Qt.PointingHandCursor)
        btn_sel.setStyleSheet(
            f"QPushButton {{ background: {COLORS['primary']}; color: white; border: none; "
            f"border-radius: 6px; padding: 10px 24px; }}"
            f"QPushButton:hover {{ background: {COLORS['primary_dark']}; }}"
        )
        btn_sel.clicked.connect(seleccionar)
        layout.addWidget(btn_sel, alignment=Qt.AlignCenter)

        dialog.exec()

    def buscar_proveedor(self, proveedor_entry):
        """Abre ventana de búsqueda de proveedores"""
        dialog = QDialog(self.window())
        dialog.setWindowTitle("Buscar Proveedor")
        dialog.resize(700, 500)
        dialog.setStyleSheet("background: white;")

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)

        search_row = QHBoxLayout()
        lbl = QLabel("Buscar:")
        lbl.setFont(make_font(FONTS['body']))
        search_row.addWidget(lbl)
        search_entry = QLineEdit()
        search_entry.setFont(make_font(FONTS['body']))
        search_entry.setPlaceholderText("Escriba para buscar...")
        search_row.addWidget(search_entry, 1)
        layout.addLayout(search_row)

        table = QTableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(['ID', 'NIT', 'Nombre', 'Teléfono'])
        table.horizontalHeader().setStyleSheet(
            f"QHeaderView::section {{ background: {COLORS['table_header']}; color: {COLORS['table_header_fg']}; padding: 9px 8px; border: none; font-weight: 500; }}"
        )
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setColumnWidth(0, 50)
        table.setColumnWidth(1, 100)
        table.setColumnWidth(2, 300)
        table.setColumnWidth(3, 120)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        layout.addWidget(table, 1)

        def buscar():
            termino = search_entry.text().strip().lower()
            try:
                proveedores = self.proveedores_repo.listar_proveedores()
                table.setRowCount(0)
                for p in proveedores:
                    if not termino or termino in p.nombre.lower() or (p.nit and termino in p.nit.lower()):
                        row = table.rowCount()
                        table.insertRow(row)
                        table.setItem(row, 0, QTableWidgetItem(str(p.id)))
                        table.setItem(row, 1, QTableWidgetItem(p.nit or 'N/A'))
                        table.setItem(row, 2, QTableWidgetItem(p.nombre))
                        table.setItem(row, 3, QTableWidgetItem(p.telefono or 'N/A'))
            except Exception as e:
                QMessageBox.critical(dialog, "Error", f"Error cargando proveedores:\n{str(e)}")
                import traceback
                traceback.print_exc()

        search_entry.textChanged.connect(lambda: buscar())
        buscar()

        def seleccionar():
            row = table.currentRow()
            if row < 0:
                QMessageBox.warning(dialog, "Advertencia", "Seleccione un proveedor")
                return
            prov_id = int(table.item(row, 0).text())
            prov_nombre = table.item(row, 2).text()
            self.proveedor_seleccionado = prov_id
            proveedor_entry.setText(f"{prov_nombre} (ID: {prov_id})")
            dialog.accept()

        table.cellDoubleClicked.connect(lambda r, c: seleccionar())

        btn_sel = QPushButton("✅ Seleccionar")
        btn_sel.setFont(make_font(FONTS['body']))
        btn_sel.setCursor(Qt.PointingHandCursor)
        btn_sel.setStyleSheet(
            f"QPushButton {{ background: {COLORS['primary']}; color: white; border: none; "
            f"border-radius: 6px; padding: 10px 24px; }}"
            f"QPushButton:hover {{ background: {COLORS['primary_dark']}; }}"
        )
        btn_sel.clicked.connect(seleccionar)
        layout.addWidget(btn_sel, alignment=Qt.AlignCenter)

        dialog.exec()

    # ------------------------------------------------------------------
    # Save movement
    # ------------------------------------------------------------------

    def guardar_movimiento_mejorado(self, dialog, tipo, producto_entry, proveedor_entry,
                                     cantidad_entry, en_cajas_check, unidades_por_caja_entry,
                                     num_cajas_entry, precio_entry, factura_entry,
                                     es_entrada, stock_label):
        """Guarda movimiento con todas las validaciones"""
        try:
            # Validar producto seleccionado
            if not self.producto_seleccionado:
                QMessageBox.warning(dialog, "Advertencia", "Debe seleccionar un producto")
                return

            # Validar cantidad
            try:
                cantidad = int(cantidad_entry.text())
            except ValueError:
                QMessageBox.critical(dialog, "Error", "La cantidad debe ser un número entero")
                return

            if cantidad <= 0:
                QMessageBox.warning(dialog, "Advertencia", "La cantidad debe ser mayor a 0")
                return

            # Validar stock disponible en salidas
            if not es_entrada:
                if self.producto_seleccionado_data:
                    stock_disponible = self.producto_seleccionado_data.get('stock', 0)
                    if cantidad > stock_disponible:
                        QMessageBox.critical(
                            dialog, "Error de Stock",
                            f"No hay suficiente stock disponible.\n\n"
                            f"Stock actual: {stock_disponible} unidades\n"
                            f"Cantidad solicitada: {cantidad} unidades\n\n"
                            f"Ajuste la cantidad o seleccione otro producto."
                        )
                        return
                else:
                    try:
                        producto = self.productos_repo.obtener_por_id(self.producto_seleccionado)
                        if producto:
                            stock_disponible = producto.get('stock', 0) if isinstance(producto, dict) else producto.stock
                            if cantidad > stock_disponible:
                                QMessageBox.critical(
                                    dialog, "Error de Stock",
                                    f"No hay suficiente stock disponible.\n\n"
                                    f"Stock actual: {stock_disponible} unidades\n"
                                    f"Cantidad solicitada: {cantidad} unidades"
                                )
                                return
                    except Exception as e:
                        QMessageBox.critical(dialog, "Error", f"Error validando stock:\n{str(e)}")
                        return

            # Validar precio
            try:
                precio = float(precio_entry.text())
            except ValueError:
                QMessageBox.critical(dialog, "Error", "El precio debe ser un número válido")
                return

            if precio < 0:
                QMessageBox.warning(dialog, "Advertencia", "El precio no puede ser negativo")
                return

            # Validar proveedor solo para ENTRADA_COMPRA
            proveedor_id = None
            if tipo == 'ENTRADA_COMPRA':
                if not self.proveedor_seleccionado:
                    QMessageBox.warning(dialog, "Advertencia",
                                        "Debe seleccionar un proveedor para compras")
                    return
                proveedor_id = self.proveedor_seleccionado

            # Validar número de factura duplicado
            num_factura = factura_entry.text().strip() or None
            if num_factura:
                from repositories.inventario_repository import InventarioRepository
                inv_repo = InventarioRepository(self.movimientos_service.db)

                if es_entrada and proveedor_id:
                    if inv_repo.verificar_factura_existente(num_factura, proveedor_id):
                        resp = QMessageBox.question(
                            dialog, "Factura Duplicada",
                            f"Ya existe una entrada con la factura '{num_factura}' "
                            f"para este proveedor.\n\n¿Desea continuar de todos modos?",
                            QMessageBox.Yes | QMessageBox.No
                        )
                        if resp != QMessageBox.Yes:
                            return
                elif not es_entrada:
                    if inv_repo.verificar_factura_venta_existente(num_factura):
                        resp = QMessageBox.question(
                            dialog, "Factura Duplicada",
                            f"Ya existe una salida con la factura '{num_factura}'.\n\n"
                            f"¿Desea continuar de todos modos?",
                            QMessageBox.Yes | QMessageBox.No
                        )
                        if resp != QMessageBox.Yes:
                            return

            # Datos de cajas
            en_cajas = False
            unidades_por_caja = 0
            num_cajas = 0
            if es_entrada and en_cajas_check is not None and en_cajas_check.isChecked():
                en_cajas = True
                try:
                    unidades_por_caja = int(unidades_por_caja_entry.text())
                    num_cajas = int(num_cajas_entry.text())

                    if unidades_por_caja <= 0 or num_cajas <= 0:
                        QMessageBox.critical(dialog, "Error",
                                             "Unidades por caja y número de cajas deben ser mayores a 0")
                        return

                    cantidad_calculada = unidades_por_caja * num_cajas
                    if cantidad != cantidad_calculada:
                        QMessageBox.critical(
                            dialog, "Error de Cálculo",
                            f"La cantidad total ({cantidad}) no coincide con el cálculo:\n"
                            f"{num_cajas} cajas × {unidades_por_caja} unidades = {cantidad_calculada}"
                        )
                        return
                except ValueError:
                    QMessageBox.critical(dialog, "Error",
                                         "Unidades por caja y número de cajas deben ser números enteros")
                    return

            # Registrar movimiento
            exito, mensaje = self.movimientos_service.registrar_movimiento(
                tipo=tipo,
                producto_id=self.producto_seleccionado,
                cantidad=cantidad,
                precio_unitario=precio,
                proveedor_id=proveedor_id,
                num_factura=num_factura,
                en_cajas=en_cajas,
                num_cajas=num_cajas,
            )

            if exito:
                QMessageBox.information(dialog, "Éxito", mensaje)
                self.verificar_y_mostrar_alertas_stock()
                dialog.accept()
                self.cargar_historial()
                self.producto_seleccionado = None
                self.producto_seleccionado_data = None
                self.proveedor_seleccionado = None
            else:
                QMessageBox.critical(dialog, "Error", mensaje)

        except Exception as e:
            QMessageBox.critical(dialog, "Error", f"Error guardando movimiento:\n{str(e)}")
            import traceback
            traceback.print_exc()

    # ------------------------------------------------------------------
    # Stock alerts
    # ------------------------------------------------------------------

    def verificar_y_mostrar_alertas_stock(self):
        """Verifica y muestra alertas de stock crítico después del movimiento"""
        if not self.alertas_service:
            return
        try:
            productos_criticos = self.alertas_service.obtener_productos_stock_critico()
            if productos_criticos:
                self.alertas_service.verificar_stock_bajo()
                for prod in productos_criticos:
                    if prod['id'] == self.producto_seleccionado:
                        if prod['stock_actual'] <= 0:
                            QMessageBox.warning(
                                self, "⚠️ Stock Crítico",
                                f"El producto '{prod['nombre']}' ha alcanzado STOCK CERO.\n"
                                f"Stock actual: {prod['stock_actual']}\n"
                                f"Stock mínimo: {prod['stock_minimo']}"
                            )
                        elif prod['stock_actual'] <= prod['stock_minimo']:
                            proveedor_info = f"\nProveedor: {prod['proveedor_nombre']}" if prod['proveedor_nombre'] else ""
                            QMessageBox.warning(
                                self, "⚠️ Stock Bajo",
                                f"El producto '{prod['nombre']}' está por debajo del stock mínimo.\n"
                                f"Stock actual: {prod['stock_actual']}\n"
                                f"Stock mínimo: {prod['stock_minimo']}"
                                f"{proveedor_info}"
                            )
                        break
        except Exception as e:
            print(f"Error verificando alertas: {e}")

    # ------------------------------------------------------------------
    # Detail views
    # ------------------------------------------------------------------

    def _extraer_factura_desde_fila(self, texto):
        valor = (texto or '').strip()
        for prefijo in ('Venta ', 'Compra '):
            idx = valor.find(prefijo)
            if idx >= 0:
                return valor[idx + len(prefijo):].strip()
        return valor.replace('📋', '').strip()

    def _money_cop(self, valor):
        try:
            numero = int(round(float(valor or 0)))
        except (TypeError, ValueError):
            numero = 0
        signo = "-" if numero < 0 else ""
        return f"{signo}${abs(numero):,.0f}".replace(",", ".") + " COP"

    def _marca_producto(self, item):
        marca = (item.get('producto_marca') or item.get('marca') or '').strip()
        return marca or 'Sin marca'

    def _estado_pago_visual(self, estado, saldo=0, pagado=0, total=0):
        estado_norm = (estado or '').upper()
        if estado_norm == 'PAGADO' or (total and pagado >= total) or saldo <= 0:
            return 'PAGADO', COLORS['success'], COLORS['success_dark'], "Operación completamente liquidada."
        if estado_norm == 'PARCIAL' or pagado > 0:
            return 'PARCIAL', COLORS['warning'], COLORS['warning_dark'], "Quedan abonos por aplicar."
        return estado_norm or 'PENDIENTE', COLORS['danger'], COLORS['danger_dark'], "No se registran pagos aplicados."

    def _crear_dialogo_detalle(self, titulo, encabezado, color=None, ancho=1120,
                               alto=700, print_callback=None):
        dialog = QDialog(self.window())
        dialog.setWindowTitle(titulo)
        dialog.resize(ancho, alto)
        dialog.setStyleSheet(
            f"QDialog {{ background: {COLORS['bg_secondary']}; }}"
            f"QScrollArea {{ border: none; background: {COLORS['bg_secondary']}; }}"
            "QScrollBar:vertical { width: 8px; background: transparent; }"
            f"QScrollBar::handle:vertical {{ background: {COLORS['border_input']}; border-radius: 4px; }}"
        )

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setFixedHeight(58)
        header.setStyleSheet(f"background: {COLORS['primary_dark']}; border: none;")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(22, 0, 22, 0)
        title = QLabel(encabezado)
        title.setFont(make_font(FONTS['heading']))
        title.setStyleSheet("color: white; background: transparent; font-weight: 600;")
        hl.addWidget(title)
        hl.addStretch()
        layout.addWidget(header)

        accent = QFrame()
        accent.setFixedHeight(3)
        accent.setStyleSheet(f"background: {COLORS['warning']};")
        layout.addWidget(accent)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setStyleSheet(f"background: {COLORS['bg_secondary']};")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(18, 14, 18, 14)
        body_layout.setSpacing(10)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        footer = QFrame()
        footer.setStyleSheet(f"background: white; border-top: 1px solid {COLORS['border']};")
        footer_l = QHBoxLayout(footer)
        footer_l.setContentsMargins(0, 8, 0, 8)
        footer_l.addStretch()

        if print_callback:
            btn_print = QPushButton("🖨️ Imprimir")
            btn_print.setFont(make_font(FONTS['body_bold']))
            btn_print.setCursor(Qt.PointingHandCursor)
            btn_print.setStyleSheet(
                f"QPushButton {{ background: white; color: {COLORS['primary']}; "
                f"border: 1px solid {COLORS['border_input']}; border-radius: 8px; "
                "padding: 9px 32px; }}"
                f"QPushButton:hover {{ background: {COLORS['bg_secondary']}; }}"
            )
            btn_print.clicked.connect(lambda: print_callback(dialog))
            footer_l.addWidget(btn_print)
            footer_l.addSpacing(10)

        btn_close = QPushButton("Cerrar")
        btn_close.setFont(make_font(FONTS['body_bold']))
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet(
            f"QPushButton {{ background: {COLORS['primary']}; color: white; border: none; "
            f"border-radius: 8px; padding: 9px 44px; }}"
            f"QPushButton:hover {{ background: {COLORS['primary_dark']}; }}"
        )
        btn_close.clicked.connect(dialog.accept)
        footer_l.addWidget(btn_close)
        footer_l.addStretch()
        layout.addWidget(footer)
        return dialog, body_layout

    def _card_frame(self):
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: white; border: 1px solid {COLORS['border']}; "
            "border-radius: 8px; }}"
        )
        return frame

    def _add_info_grid(self, layout, campos, columns=4):
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        for idx, (label, value) in enumerate(campos):
            card = self._card_frame()
            card_l = QVBoxLayout(card)
            card_l.setContentsMargins(12, 9, 12, 9)
            card_l.setSpacing(2)
            title = QLabel(label)
            title.setFont(make_font(FONTS['small']))
            title.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent; border: none;")
            val = QLabel(str(value if value not in (None, '') else 'No registrado'))
            val.setFont(make_font(FONTS['body_bold']))
            val.setWordWrap(True)
            val.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent; border: none;")
            card_l.addWidget(title)
            card_l.addWidget(val)
            grid.addWidget(card, idx // columns, idx % columns)
        layout.addLayout(grid)

    def _add_section_title(self, layout, texto):
        lbl = QLabel(texto)
        lbl.setFont(make_font(FONTS['heading']))
        lbl.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent; margin-top: 2px;")
        layout.addWidget(lbl)

    def _add_payment_summary(self, layout, total_label, total, paid_label, paid,
                             saldo, estado, is_sale=False):
        pct = int(round((float(paid or 0) / float(total or 1)) * 100)) if total else 0
        pct = max(0, min(100, pct))
        estado_txt, color, color_dark, hint = self._estado_pago_visual(estado, saldo, paid, total)
        frame = self._card_frame()
        frame.setStyleSheet(
            f"QFrame {{ background: white; border: 1px solid {color}; border-radius: 10px; }}"
        )
        outer = QHBoxLayout(frame)
        outer.setContentsMargins(18, 12, 18, 12)
        outer.setSpacing(16)

        pct_box = QFrame()
        pct_box.setFixedWidth(100)
        pct_box.setStyleSheet("background: transparent; border: none;")
        pct_l = QVBoxLayout(pct_box)
        pct_l.setAlignment(Qt.AlignCenter)
        pct_big = QLabel(f"{pct}%")
        pct_big.setFont(make_font(FONTS['large']))
        pct_big.setAlignment(Qt.AlignCenter)
        pct_big.setStyleSheet(f"color: {color_dark}; background: transparent; border: none;")
        pct_caption = QLabel("Pagado")
        pct_caption.setFont(make_font(FONTS['body']))
        pct_caption.setAlignment(Qt.AlignCenter)
        pct_caption.setStyleSheet(f"color: {color_dark}; background: transparent; border: none;")
        pct_l.addWidget(pct_big)
        pct_l.addWidget(pct_caption)
        outer.addWidget(pct_box)

        mid = QVBoxLayout()
        metrics = QHBoxLayout()
        for label, value, vcolor in [
            (total_label, total, COLORS['text_primary']),
            (paid_label, paid, COLORS['success']),
            ("Saldo pendiente", saldo, COLORS['danger'] if saldo > 0 else COLORS['success']),
        ]:
            box = QVBoxLayout()
            l = QLabel(label)
            l.setFont(make_font(FONTS['small']))
            l.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent; border: none;")
            v = QLabel(self._money_cop(value))
            v.setFont(make_font(FONTS['body_bold']))
            v.setStyleSheet(f"color: {vcolor}; background: transparent; border: none;")
            box.addWidget(l)
            box.addWidget(v)
            metrics.addLayout(box)
        mid.addLayout(metrics)
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(pct)
        bar.setTextVisible(False)
        bar.setFixedHeight(10)
        bar.setStyleSheet(
            f"QProgressBar {{ background: {COLORS['border_light']}; border: none; border-radius: 7px; }}"
            f"QProgressBar::chunk {{ background: {color}; border-radius: 7px; }}"
        )
        mid.addWidget(bar)
        caption = QLabel(f"{pct}% del total pagado")
        caption.setFont(make_font(FONTS['body']))
        caption.setAlignment(Qt.AlignCenter)
        caption.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent; border: none;")
        mid.addWidget(caption)
        outer.addLayout(mid, 1)

        status = QFrame()
        status.setFixedWidth(180)
        status.setStyleSheet(
            f"background: {COLORS['bg_primary']}; border: 1px solid {COLORS['border']}; border-radius: 10px;"
        )
        st_l = QVBoxLayout(status)
        st_l.setContentsMargins(12, 9, 12, 9)
        st_l.setSpacing(6)
        st_title = QLabel("Estado de pago")
        st_title.setFont(make_font(FONTS['body_bold']))
        st_title.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent; border: none;")
        st_badge = QLabel(estado_txt)
        st_badge.setFont(make_font(FONTS['body_bold']))
        st_badge.setAlignment(Qt.AlignCenter)
        st_badge.setStyleSheet(
            f"background: {color}; color: white; border: none; border-radius: 13px; padding: 5px 14px;"
        )
        st_hint = QLabel(hint)
        st_hint.setFont(make_font(FONTS['small']))
        st_hint.setWordWrap(True)
        st_hint.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent; border: none;")
        st_l.addWidget(st_title)
        st_l.addWidget(st_badge)
        st_l.addWidget(st_hint)
        outer.addWidget(status)
        layout.addWidget(frame)

    def _add_note_card(self, layout, titulo, texto):
        if not texto:
            return
        frame = self._card_frame()
        frame.setStyleSheet(
            f"QFrame {{ background: #fffaf2; border: 1px solid {COLORS['warning_border']}; border-radius: 8px; }}"
        )
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(12, 9, 12, 9)
        fl.setSpacing(4)
        title = QLabel(titulo)
        title.setFont(make_font(FONTS['body_bold']))
        title.setStyleSheet(f"color: {COLORS['warning_dark']}; background: transparent; border: none;")
        body = QLabel(str(texto))
        body.setFont(make_font(FONTS['body']))
        body.setWordWrap(True)
        body.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent; border: none;")
        fl.addWidget(title)
        fl.addWidget(body)
        layout.addWidget(frame)

    def _add_abonos_timeline(self, layout, abonos, total):
        if not abonos:
            lbl = QLabel("Sin abonos registrados")
            lbl.setFont(make_font(FONTS['body']))
            lbl.setStyleSheet(
                f"background: white; border: 1px solid {COLORS['border']}; "
                f"border-radius: 8px; padding: 12px; color: {COLORS['text_secondary']};"
            )
            layout.addWidget(lbl)
            return

        saldo_restante = total
        for abono in abonos:
            valor = abono.get('monto_abono') or 0
            saldo_restante = max(saldo_restante - valor, 0)
            card = self._card_frame()
            cl = QGridLayout(card)
            cl.setContentsMargins(12, 8, 12, 8)
            cl.setHorizontalSpacing(10)
            cl.setVerticalSpacing(3)
            fecha = QLabel(str(abono.get('fecha_abono', ''))[:16] or 'No registrado')
            fecha.setFont(make_font(FONTS['body_bold']))
            fecha.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent; border: none;")
            monto = QLabel(self._money_cop(valor))
            monto.setFont(make_font(FONTS['body_bold']))
            monto.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            monto.setStyleSheet(f"color: {COLORS['success']}; background: transparent; border: none;")
            meta = QLabel(
                f"Método: {abono.get('tipo_pago') or 'No registrado'}    "
                f"Comprobante: {abono.get('numero_comprobante') or '-'}    "
                f"Usuario: {abono.get('usuario') or 'Sistema'}"
            )
            meta.setFont(make_font(FONTS['small']))
            meta.setWordWrap(True)
            meta.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent; border: none;")
            saldo = QLabel(f"Saldo restante: {self._money_cop(saldo_restante)}")
            saldo.setFont(make_font(FONTS['small']))
            saldo.setStyleSheet(f"color: {COLORS['warning_dark']}; background: transparent; border: none;")
            cl.addWidget(fecha, 0, 0)
            cl.addWidget(monto, 0, 1)
            cl.addWidget(meta, 1, 0, 1, 2)
            cl.addWidget(saldo, 2, 0, 1, 2)
            layout.addWidget(card)

    def _add_table(self, layout, headers, rows, min_height=120, max_height=320,
                   right_align_columns=None):
        if right_align_columns is None:
            right_align_columns = set(range(1, len(headers)))
        else:
            right_align_columns = set(right_align_columns)
        table = QTableWidget()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setStyleSheet(
            f"QHeaderView::section {{ background: {COLORS['table_header']}; "
            f"color: {COLORS['table_header_fg']}; padding: 8px 7px; border: none; font-weight: 500; }}"
        )
        table.setStyleSheet(
            f"QTableWidget {{ background: white; border: 1px solid {COLORS['border']}; "
            "border-radius: 10px; gridline-color: #EEF1F6; }}"
            f"QTableWidget::item {{ padding: 5px 7px; color: {COLORS['text_primary']}; }}"
        )
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)

        for row_values in rows:
            row = table.rowCount()
            table.insertRow(row)
            for col, value in enumerate(row_values):
                item = QTableWidgetItem(str(value if value not in (None, '') else '-'))
                if col in right_align_columns:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                else:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                table.setItem(row, col, item)

        for col in range(len(headers)):
            mode = QHeaderView.Stretch if col == 0 else QHeaderView.ResizeToContents
            table.horizontalHeader().setSectionResizeMode(col, mode)
        row_h = table.verticalHeader().defaultSectionSize()
        head_h = table.horizontalHeader().sizeHint().height()
        height = max(min_height, min(head_h + max(1, len(rows)) * row_h + 16, max_height))
        table.setMinimumHeight(height)
        table.setMaximumHeight(height)
        layout.addWidget(table)
        return table

    def _obtener_venta_detalle(self, num_factura):
        conn = self.db_manager.conectar()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT v.*, c.nombre as cliente_nombre, u.nombre_completo as usuario_nombre
                FROM ventas v
                LEFT JOIN clientes c ON v.cliente_id = c.id
                LEFT JOIN usuarios u ON v.usuario_id = u.id
                WHERE v.numero_factura = ?
                LIMIT 1
            ''', (num_factura,))
            row = cursor.fetchone()
            if not row:
                return None
            venta = dict(row)
            cursor.execute('''
                SELECT dv.*, p.nombre as producto_nombre, p.marca as producto_marca
                FROM detalle_ventas dv
                LEFT JOIN productos p ON p.id = dv.producto_id
                WHERE dv.venta_id = ?
                ORDER BY dv.id
            ''', (venta['id'],))
            venta['detalles'] = [dict(r) for r in cursor.fetchall()]
            return venta
        finally:
            conn.close()

    def _obtener_compra_detalle(self, num_factura):
        conn = self.db_manager.conectar()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT c.*, p.nombre as proveedor_nombre, u.nombre_completo as usuario_nombre
                FROM compras c
                LEFT JOIN proveedores p ON c.proveedor_id = p.id
                LEFT JOIN usuarios u ON c.usuario_id = u.id
                WHERE c.numero_factura = ?
                LIMIT 1
            ''', (num_factura,))
            row = cursor.fetchone()
            if not row:
                return None
            compra = dict(row)
            cursor.execute('''
                SELECT dc.*, p.nombre as producto_nombre, p.marca as producto_marca
                FROM detalle_compras dc
                LEFT JOIN productos p ON p.id = dc.producto_id
                WHERE dc.compra_id = ?
                ORDER BY dc.id
            ''', (compra['id'],))
            compra['productos'] = [dict(r) for r in cursor.fetchall()]
            cursor.execute('''
                SELECT id, monto_abono, fecha_abono, tipo_pago,
                       numero_comprobante, usuario, observaciones
                FROM abonos_compras
                WHERE id_compra = ?
                ORDER BY fecha_abono ASC, id ASC
            ''', (compra['id'],))
            compra['abonos'] = [dict(r) for r in cursor.fetchall()]
            return compra
        finally:
            conn.close()

    def _obtener_egreso_detalle(self, egreso_id):
        conn = self.db_manager.conectar()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT * FROM egresos_caja WHERE id = ? LIMIT 1', (egreso_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def _imprimir_factura_desde_detalle(self, ventana_padre, num_factura):
        try:
            movimientos = self.movimientos_service.obtener_historial(limite=1000)
            items_factura = [
                m for m in movimientos
                if m.get('num_factura') == num_factura
                and m.get('tipo') != 'COBRO_CREDITO'
            ]
            if not items_factura:
                QMessageBox.warning(
                    ventana_padre,
                    "Sin datos",
                    f"No se encontraron productos para imprimir la factura {num_factura}"
                )
                return
            total_factura = sum(item.get('costo_total') or 0 for item in items_factura)
            self._imprimir_factura_movimiento(
                ventana_padre, num_factura, items_factura, total_factura
            )
        except Exception as e:
            QMessageBox.critical(
                ventana_padre,
                "Error",
                f"No se pudo imprimir la factura:\n{str(e)}"
            )

    def _parse_egreso_referencia_pago(self, egreso):
        descripcion = egreso.get('descripcion') or ''
        ref = {}
        proveedor = re.search(r'Pago a proveedor\s+(.+?)(?:\s+-\s+|$)', descripcion, re.IGNORECASE)
        compra = re.search(r'Compra\s+#?([A-Za-z0-9\-]+)', descripcion, re.IGNORECASE)
        factura = re.search(r'Factura\s+([A-Za-z0-9\-]+)', descripcion, re.IGNORECASE)
        abono = re.search(r'Abono\s+#?([A-Za-z0-9\-]+)', descripcion, re.IGNORECASE)
        if proveedor:
            ref['Proveedor'] = proveedor.group(1).strip()
        if compra:
            ref['Compra asociada'] = compra.group(1).strip()
        if factura:
            ref['Factura'] = factura.group(1).strip()
        if abono:
            ref['Abono relacionado'] = abono.group(1).strip()
        if ref:
            ref['Valor pagado'] = self._money_cop(egreso.get('monto') or 0)
            ref['Fecha del abono'] = str(egreso.get('fecha_egreso', ''))[:16] or 'No registrado'
            ref['Método de pago'] = egreso.get('metodo_pago') or 'No registrado'
        return ref

    def _add_egreso_main_card(self, layout, egreso):
        frame = self._card_frame()
        fl = QGridLayout(frame)
        fl.setContentsMargins(16, 12, 16, 12)
        fl.setHorizontalSpacing(16)
        fl.setVerticalSpacing(7)

        valor = QLabel(self._money_cop(egreso.get('monto') or 0))
        valor.setFont(make_font(FONTS['large']))
        valor.setStyleSheet(f"color: {COLORS['warning_dark']}; background: transparent; border: none;")
        desc = QLabel(egreso.get('descripcion') or 'No registrado')
        desc.setFont(make_font(FONTS['body']))
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent; border: none;")

        fl.addWidget(QLabel("Valor"), 0, 0)
        fl.addWidget(valor, 0, 1)
        fl.addWidget(QLabel("Descripción"), 1, 0)
        fl.addWidget(desc, 1, 1)
        for row in range(2):
            label = fl.itemAtPosition(row, 0).widget()
            label.setFont(make_font(FONTS['small']))
            label.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent; border: none;")
        layout.addWidget(frame)

    def _add_reference_grid(self, layout, titulo, campos):
        frame = self._card_frame()
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(12, 10, 12, 10)
        fl.setSpacing(8)
        title = QLabel(titulo)
        title.setFont(make_font(FONTS['body_bold']))
        title.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent; border: none;")
        fl.addWidget(title)
        self._add_info_grid(fl, list(campos.items()) if campos else [("Referencia", "No registrado")], columns=3)
        layout.addWidget(frame)

    def ver_detalle_venta_factura(self, num_factura):
        venta = self._obtener_venta_detalle(num_factura)
        if not venta:
            QMessageBox.warning(self, "Sin datos", f"No se encontró la venta {num_factura}")
            return

        total = venta.get('total') or 0
        pagado = venta.get('monto_pagado') or 0
        saldo = max(total - pagado, 0)
        dialog, body = self._crear_dialogo_detalle(
            f"Detalle Venta: {num_factura}",
            f"📦 Salida de inventario #{num_factura}",
            COLORS['danger'],
            print_callback=lambda dlg: self._imprimir_factura_desde_detalle(dlg, num_factura)
        )
        self._add_info_grid(body, [
            ("Factura", num_factura),
            ("Fecha", str(venta.get('fecha', ''))[:16]),
            ("Cliente", venta.get('cliente_nombre') or 'Cliente General'),
            ("Usuario", venta.get('usuario_nombre') or venta.get('vendedor') or 'Sistema'),
        ])
        self._add_payment_summary(
            body,
            "Total venta",
            total,
            "Monto pagado",
            pagado,
            saldo,
            venta.get('estado_pago'),
            is_sale=True
        )

        content = QHBoxLayout()
        content.setSpacing(12)
        left = self._card_frame()
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(10, 10, 10, 10)
        right = self._card_frame()
        right.setFixedWidth(330)
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(12, 10, 12, 10)
        right_l.setSpacing(8)

        self._add_table(left_l, ['Producto', 'Marca', 'Cantidad', 'Precio unit.', 'Subtotal'], [
            [
                det.get('producto_nombre', 'Producto'),
                self._marca_producto(det),
                formatear_stock(det.get('cantidad', 0)),
                self._money_cop(det.get('precio_unitario') or 0),
                self._money_cop(det.get('subtotal') or 0),
            ]
            for det in venta.get('detalles', [])
        ], min_height=220, max_height=360, right_align_columns={2, 3, 4})

        self._add_section_title(right_l, "Resumen de cobro")
        self._add_info_grid(right_l, [
            ("Método de pago", venta.get('metodo_pago') or 'No registrado'),
            ("Estado", venta.get('estado_pago') or 'No registrado'),
            ("Caja", venta.get('caja_nombre') or 'Caja principal'),
            ("Cajero", venta.get('usuario_nombre') or venta.get('vendedor') or 'Sistema'),
            ("Total recibido", self._money_cop(pagado)),
        ], columns=1)
        self._add_note_card(right_l, "Observaciones", venta.get('observaciones'))
        right_l.addStretch()
        content.addWidget(left, 1)
        content.addWidget(right)
        body.addLayout(content)
        dialog.exec()

    def ver_detalle_compra_factura(self, num_factura):
        compra = self._obtener_compra_detalle(num_factura)
        if not compra:
            QMessageBox.warning(self, "Sin datos", f"No se encontró la compra {num_factura}")
            return

        total = compra.get('total') or 0
        abonos = compra.get('abonos', [])
        total_abonos = sum((a.get('monto_abono') or 0) for a in abonos)
        monto_pagado = compra.get('monto_pagado')
        if monto_pagado is None:
            monto_pagado = total_abonos
        saldo = compra.get('saldo_pendiente')
        if saldo is None:
            saldo = max(total - monto_pagado, 0)

        dialog, body = self._crear_dialogo_detalle(
            f"Detalle Compra: {num_factura}",
            f"📦 Entrada de inventario #{num_factura}",
            COLORS['success'],
            print_callback=lambda dlg: self._imprimir_factura_desde_detalle(dlg, num_factura)
        )
        self._add_info_grid(body, [
            ("Factura", num_factura),
            ("Fecha compra", str(compra.get('fecha', ''))[:16]),
            ("Proveedor", compra.get('proveedor_nombre')),
            ("Usuario", compra.get('usuario_nombre') or 'Sistema'),
        ])
        self._add_payment_summary(
            body,
            "Total compra",
            total,
            "Pagado acumulado",
            monto_pagado,
            saldo,
            compra.get('estado_pago')
        )

        content = QHBoxLayout()
        content.setSpacing(12)
        left = self._card_frame()
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(10, 10, 10, 10)
        right = self._card_frame()
        right.setFixedWidth(380)
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(12, 10, 12, 10)
        right_l.setSpacing(8)

        self._add_table(left_l, ['Producto', 'Marca', 'Cantidad', 'Precio unit.', 'Subtotal'], [
            [
                prod.get('producto_nombre', 'Producto'),
                self._marca_producto(prod),
                formatear_stock(prod.get('cantidad', 0)),
                self._money_cop(prod.get('precio_unitario') or 0),
                self._money_cop(prod.get('subtotal') or 0),
            ]
            for prod in compra.get('productos', [])
        ], min_height=220, max_height=360, right_align_columns={2, 3, 4})
        self._add_note_card(left_l, "Observaciones", compra.get('observaciones'))

        self._add_section_title(right_l, "Historial de abonos")
        self._add_abonos_timeline(right_l, abonos, total)
        right_l.addStretch()
        content.addWidget(left, 1)
        content.addWidget(right)
        body.addLayout(content)
        dialog.exec()

    def ver_detalle_egreso(self, egreso_id):
        egreso = self._obtener_egreso_detalle(egreso_id)
        if not egreso:
            QMessageBox.warning(self, "Sin datos", f"No se encontró el egreso #{egreso_id}")
            return

        dialog, body = self._crear_dialogo_detalle(
            f"Detalle Egreso: {egreso_id}",
            f"💸 Egreso de caja #{egreso_id}",
            COLORS['warning'] if 'warning' in COLORS else COLORS['danger'],
            ancho=980,
            alto=600
        )
        self._add_info_grid(body, [
            ("Fecha", str(egreso.get('fecha_egreso', ''))[:16]),
            ("Categoría", egreso.get('categoria')),
            ("Valor", self._money_cop(egreso.get('monto') or 0)),
            ("Método pago", egreso.get('metodo_pago')),
            ("Usuario", egreso.get('usuario')),
            ("Comprobante", egreso.get('numero_comprobante') or egreso.get('comprobante') or '-'),
        ], columns=3)
        self._add_egreso_main_card(body, egreso)
        self._add_reference_grid(body, "Referencia del pago", self._parse_egreso_referencia_pago(egreso))
        dialog.exec()

    def _on_tree_double_click(self, item, column):
        """Handle double-click on tree item, dispatch to proper detail view."""
        meta = item.data(0, Qt.UserRole) or {}
        tipo_meta = (meta.get('tipo') or '').upper()
        if meta.get('egreso_id'):
            self.ver_detalle_egreso(meta['egreso_id'])
            return
        if meta.get('num_factura'):
            self.ver_detalle_factura(meta['num_factura'])
            return
        if meta.get('mov_id') and tipo_meta == 'EGRESO_CAJA':
            self.ver_detalle_egreso(meta['mov_id'])
            return
        if meta.get('mov_id') and tipo_meta != 'ABONO_VENTA':
            self.ver_detalle_movimiento(meta['mov_id'])
            return

        primer_valor = item.text(0).strip()
        tipo_texto = item.text(2).strip().upper()

        if primer_valor.startswith('📋'):
            num_factura = self._extraer_factura_desde_fila(primer_valor)
            self.ver_detalle_factura(num_factura)
            return

        if primer_valor.startswith('💸'):
            try:
                egreso_id = int(primer_valor.replace('💸', '').replace('EGRESO-', '').strip())
                self.ver_detalle_egreso(egreso_id)
            except (ValueError, TypeError):
                pass
            return

        if primer_valor.startswith('📥') or primer_valor.startswith('📤'):
            tipo_label = primer_valor.replace('📥', '').replace('📤', '').strip()
            fecha_mov = item.text(1).strip()
            self.ver_detalle_grupo_sin_factura(tipo_label, fecha_mov)
            return

        try:
            mov_id = int(primer_valor)
        except (ValueError, TypeError):
            return

        if 'EGRESO CAJA' in tipo_texto or 'EGRESO DE CAJA' in tipo_texto:
            self.ver_detalle_egreso(mov_id)
            return

        parent = item.parent()
        if parent and parent.text(0).strip().startswith('📋'):
            num_factura = self._extraer_factura_desde_fila(parent.text(0).strip())
            self.ver_detalle_factura(num_factura)
            return

        self.ver_detalle_movimiento(mov_id)

    def ver_detalle_movimiento(self, mov_id):
        """Muestra el detalle de un movimiento individual"""
        try:
            movimientos = self.movimientos_service.obtener_historial(limite=1000)
            movimiento = next((m for m in movimientos if m['id'] == mov_id), None)
            if not movimiento:
                return

            dialog = QDialog(self.window())
            dialog.setWindowTitle(f"Detalle Movimiento #{mov_id}")
            dialog.setFixedSize(500, 600)
            dialog.setStyleSheet("background: white;")

            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(0, 0, 0, 0)

            tipo = movimiento['tipo']
            es_entrada = 'ENTRADA' in tipo

            # Header
            color_h = COLORS['success'] if es_entrada else COLORS['danger']
            header = QFrame()
            header.setFixedHeight(60)
            header.setStyleSheet(f"background: {color_h};")
            hl = QHBoxLayout(header)
            hl.addWidget(self._styled_label(
                f"{'📥' if es_entrada else '📤'} {tipo.replace('_', ' ')}",
                FONTS['large'], "white", color_h, Qt.AlignCenter
            ))
            layout.addWidget(header)

            # Content
            content = QWidget()
            cl = QVBoxLayout(content)
            cl.setContentsMargins(30, 20, 30, 10)

            def add_field(label, value):
                row = QHBoxLayout()
                l = QLabel(f"{label}:")
                l.setFont(make_font(FONTS['body_bold']))
                l.setFixedWidth(140)
                l.setStyleSheet("background: transparent;")
                row.addWidget(l)
                v = QLabel(str(value))
                v.setFont(make_font(FONTS['body']))
                v.setStyleSheet("background: transparent;")
                v.setWordWrap(True)
                row.addWidget(v, 1)
                cl.addLayout(row)

            add_field("ID", movimiento['id'])
            add_field("Fecha", movimiento['fecha'][:16] if movimiento.get('fecha') else 'N/A')
            add_field("Tipo", tipo.replace('_', ' '))
            add_field("Producto", movimiento.get('producto_nombre', 'N/A'))
            if movimiento.get('proveedor_id'):
                add_field("Proveedor", movimiento.get('proveedor_nombre', 'N/A'))
            add_field("Cantidad", f"{movimiento['cantidad']} unidades")
            if movimiento.get('en_cajas'):
                add_field("Cajas", movimiento.get('num_cajas', 0))
            add_field("Precio Unit.", f"${movimiento['precio_unitario']:,.0f}")
            add_field("Costo Total", f"${movimiento['costo_total']:,.0f}")
            if movimiento.get('num_factura'):
                add_field("Núm. Factura", movimiento['num_factura'])

            if movimiento.get('motivo'):
                lbl_obs = QLabel("Observaciones:")
                lbl_obs.setFont(make_font(FONTS['body_bold']))
                lbl_obs.setStyleSheet("background: transparent;")
                cl.addWidget(lbl_obs)
                txt = QTextEdit()
                txt.setFont(make_font(FONTS['body']))
                txt.setPlainText(movimiento['motivo'])
                txt.setReadOnly(True)
                txt.setMaximumHeight(80)
                cl.addWidget(txt)

            add_field("Usuario", movimiento.get('usuario_nombre', 'Sistema'))
            cl.addStretch()
            layout.addWidget(content, 1)

            btn_cerrar = QPushButton("Cerrar")
            btn_cerrar.setFont(make_font(FONTS['body']))
            btn_cerrar.setCursor(Qt.PointingHandCursor)
            btn_cerrar.setStyleSheet(
                f"QPushButton {{ background: {COLORS['secondary']}; color: white; border: none; "
                f"border-radius: 6px; padding: 10px 30px; }}"
            )
            btn_cerrar.clicked.connect(dialog.accept)
            layout.addWidget(btn_cerrar, alignment=Qt.AlignCenter)
            layout.addSpacing(15)

            from ui.widgets import hacer_dialogo_responsivo
            hacer_dialogo_responsivo(dialog, 500, 600)
            dialog.exec()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error mostrando detalle:\n{str(e)}")
            import traceback
            traceback.print_exc()

    def ver_detalle_factura(self, num_factura):
        """Muestra el detalle completo de una factura con todos sus productos"""
        try:
            movimientos = self.movimientos_service.obtener_historial(limite=1000)
            items_factura = [m for m in movimientos
                            if m.get('num_factura') == num_factura
                            and m.get('tipo') != 'COBRO_CREDITO']

            if not items_factura:
                QMessageBox.warning(self, "Sin datos",
                                    f"No se encontraron productos para la factura {num_factura}")
                return

            tipo_factura = items_factura[0].get('tipo')
            if tipo_factura == 'SALIDA_VENTA':
                self.ver_detalle_venta_factura(num_factura)
                return
            if tipo_factura == 'ENTRADA_COMPRA':
                self.ver_detalle_compra_factura(num_factura)
                return

            dialog = QDialog(self.window())
            dialog.setWindowTitle(f"Detalle Factura: {num_factura}")
            dialog.resize(1000, 750)
            dialog.setStyleSheet("background: white;")

            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            tipo_principal = items_factura[0]['tipo']
            es_entrada = 'ENTRADA' in tipo_principal

            # Header
            color_h = COLORS['success'] if es_entrada else COLORS['danger']
            header = QFrame()
            header.setFixedHeight(60)
            header.setStyleSheet(f"background: {color_h};")
            hl = QHBoxLayout(header)
            hl.addWidget(self._styled_label(
                f"{'📥 ENTRADA' if es_entrada else '📤 SALIDA'} - Factura: {num_factura}",
                FONTS['large'], "white", color_h, Qt.AlignCenter
            ))
            layout.addWidget(header)

            # Info section (scrollable)
            info_scroll = QScrollArea()
            info_scroll.setWidgetResizable(True)
            info_scroll.setStyleSheet("QScrollArea { border: none; }")
            info_scroll.setMaximumHeight(300)
            info_widget = QWidget()
            info_widget.setStyleSheet("background: white;")
            info_layout = QVBoxLayout(info_widget)
            info_layout.setContentsMargins(30, 10, 30, 10)

            fecha = items_factura[0].get('fecha', 'N/A')[:16]
            usuario = items_factura[0].get('usuario_nombre', 'Sistema')
            cantidad_productos = len(items_factura)
            total_factura = sum(item['costo_total'] for item in items_factura)

            for txt in [f"📅 Fecha: {fecha}", f"👤 Usuario: {usuario}",
                        f"📦 Productos: {cantidad_productos}"]:
                l = QLabel(txt)
                l.setFont(make_font(FONTS['body']))
                l.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
                info_layout.addWidget(l)

            # Payment info for purchases
            if items_factura[0]['tipo'] == 'ENTRADA_COMPRA' and self.compras_repo:
                try:
                    compras = self.compras_repo.listar_compras_recientes(dias=365, limite=1000)
                    compra = next((c for c in compras if c.get('numero_factura') == num_factura), None)
                    if compra:
                        monto_pagado = compra.get('monto_pagado', 0)
                        saldo_pendiente = compra.get('saldo_pendiente', 0)
                        estado_pago = compra.get('estado_pago', 'PENDIENTE')

                        sep = QFrame()
                        sep.setFrameShape(QFrame.HLine)
                        sep.setStyleSheet("color: #d1d5db;")
                        info_layout.addWidget(sep)

                        lbl_pago_title = QLabel("Información de Pago:")
                        lbl_pago_title.setFont(make_font(FONTS['body_bold']))
                        lbl_pago_title.setStyleSheet(f"color: {COLORS['primary']}; background: transparent;")
                        info_layout.addWidget(lbl_pago_title)

                        for txt, color in [
                            (f"💰 Total de Compra: ${total_factura:,.0f}", COLORS['text_primary']),
                            (f"✓ Monto Pagado: ${monto_pagado:,.0f}", '#10b981'),
                            (f"⏳ Saldo Pendiente: ${saldo_pendiente:,.0f}",
                             '#ef4444' if estado_pago == 'PENDIENTE' else '#f59e0b'),
                        ]:
                            l = QLabel(txt)
                            l.setFont(make_font(FONTS['body_bold']))
                            l.setStyleSheet(f"color: {color}; background: transparent;")
                            info_layout.addWidget(l)

                        color_estado = '#10b981' if estado_pago == 'PAGADO' else '#f59e0b' if estado_pago == 'PARCIAL' else '#ef4444'
                        l_est = QLabel(f"Estado: {estado_pago}")
                        l_est.setFont(make_font(FONTS['body_bold']))
                        l_est.setStyleSheet(f"color: {color_estado}; background: transparent;")
                        info_layout.addWidget(l_est)

                        # Historial de abonos al proveedor
                        try:
                            from repositories.abonos_compras_repo import AbonosaComprasRepository
                            import os as _os
                            _db_path = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), 'ferreteria.db')
                            _abonos_repo = AbonosaComprasRepository(_db_path)
                            _id_compra = compra.get('id')
                            _abonos = _abonos_repo.obtener_abonos_factura(_id_compra) if _id_compra else []

                            sep3 = QFrame()
                            sep3.setFrameShape(QFrame.HLine)
                            sep3.setStyleSheet("color: #d1d5db;")
                            info_layout.addWidget(sep3)

                            lbl_hist_c = QLabel("📋 Historial de Pagos al Proveedor:")
                            lbl_hist_c.setFont(make_font(FONTS['body_bold']))
                            lbl_hist_c.setStyleSheet("color: #1565c0; background: transparent;")
                            info_layout.addWidget(lbl_hist_c)

                            if _abonos:
                                abonos_tbl = QTableWidget()
                                abonos_tbl.setColumnCount(4)
                                abonos_tbl.setHorizontalHeaderLabels(['Fecha', 'Monto', 'Tipo Pago', 'Usuario'])
                                abonos_tbl.horizontalHeader().setStyleSheet(
                                    "QHeaderView::section { background: #e3f2fd; color: black; padding: 4px; border: none; font-weight: 500; font-size: 8pt; }"
                                )
                                abonos_tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
                                abonos_tbl.setSelectionMode(QAbstractItemView.NoSelection)
                                abonos_tbl.verticalHeader().setVisible(False)
                                abonos_tbl.setAlternatingRowColors(True)
                                abonos_tbl.setShowGrid(False)
                                abonos_tbl.horizontalHeader().setStretchLastSection(False)
                                abonos_tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
                                abonos_tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
                                abonos_tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
                                abonos_tbl.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)

                                for _idx, _ab in enumerate(_abonos):
                                    abonos_tbl.insertRow(_idx)
                                    _fecha_ab = _ab['fecha_abono'][:16] if _ab.get('fecha_abono') else 'N/A'
                                    abonos_tbl.setItem(_idx, 0, QTableWidgetItem(_fecha_ab))
                                    _mi = QTableWidgetItem(f"${_ab['monto_abono']:,.0f}")
                                    _mi.setForeground(QBrush(QColor('#10b981')))
                                    abonos_tbl.setItem(_idx, 1, _mi)
                                    abonos_tbl.setItem(_idx, 2, QTableWidgetItem(_ab.get('tipo_pago', 'N/A')))
                                    abonos_tbl.setItem(_idx, 3, QTableWidgetItem(str(_ab.get('usuario', 'N/A'))[:12]))
                                    if _idx % 2 != 0:
                                        for _c in range(4):
                                            abonos_tbl.item(_idx, _c).setBackground(QBrush(QColor('#f5f5f5')))

                                _hh = abonos_tbl.horizontalHeader().sizeHint().height()
                                _rh = abonos_tbl.verticalHeader().defaultSectionSize()
                                _th = max(80, min(_hh + len(_abonos) * _rh + 12, 190))
                                abonos_tbl.setMinimumHeight(_th)
                                abonos_tbl.setMaximumHeight(_th)
                                info_layout.addWidget(abonos_tbl)

                                _total_ab = sum(a['monto_abono'] for a in _abonos)
                                _l_total = QLabel(f"Total Pagado: ${_total_ab:,.0f}")
                                _l_total.setFont(make_font(FONTS['body_bold']))
                                _l_total.setStyleSheet("color: #10b981; background: #e8f5e9; padding: 4px; border-radius: 4px;")
                                info_layout.addWidget(_l_total)
                            else:
                                _l_no = QLabel("No hay pagos registrados aún")
                                _l_no.setFont(make_font(FONTS['body']))
                                _l_no.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
                                info_layout.addWidget(_l_no)
                        except Exception as _e_ab:
                            print(f"[WARN] Historial abonos compra: {_e_ab}")
                except Exception as e:
                    print(f"Error obteniendo información de pago: {e}")

            # Sale info
            elif items_factura[0]['tipo'] == 'SALIDA_VENTA':
                try:
                    from services.ventas_service import VentasService
                    ventas_service = VentasService(self.db_manager, self.productos_repo,
                                                  self.clientes_repo, self.auth)
                    venta = ventas_service.obtener_venta_por_factura(num_factura)

                    if venta:
                        sep = QFrame()
                        sep.setFrameShape(QFrame.HLine)
                        sep.setStyleSheet("color: #d1d5db;")
                        info_layout.addWidget(sep)

                        lbl_venta_title = QLabel("Información de la Venta:")
                        lbl_venta_title.setFont(make_font(FONTS['body_bold']))
                        lbl_venta_title.setStyleSheet(f"color: {COLORS['primary']}; background: transparent;")
                        info_layout.addWidget(lbl_venta_title)

                        cliente_nombre = venta.get('cliente_nombre', 'Cliente General')
                        l_cl = QLabel(f"👤 Cliente: {cliente_nombre}")
                        l_cl.setFont(make_font(FONTS['body_bold']))
                        l_cl.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent;")
                        info_layout.addWidget(l_cl)

                        metodo_pago = venta.get('metodo_pago', 'EFECTIVO')
                        icono_pago = '💵' if metodo_pago == 'EFECTIVO' else '💳' if 'TARJETA' in metodo_pago else '📱' if metodo_pago in ['NEQUI', 'DAVIPLATA'] else '🔄'
                        l_mp = QLabel(f"{icono_pago} Método de Pago: {metodo_pago.replace('_', ' ')}")
                        l_mp.setFont(make_font(FONTS['body_bold']))
                        l_mp.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent;")
                        info_layout.addWidget(l_mp)

                        # Credit payment history
                        if metodo_pago == 'CREDITO':
                            try:
                                from repositories.abonos_ventas_repo import AbonosVentasRepository
                                import os
                                db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ferreteria.db')
                                abonos_repo = AbonosVentasRepository(db_path)

                                id_venta = venta.get('id')
                                abonos = abonos_repo.obtener_abonos_factura(id_venta) if id_venta else []

                                sep2 = QFrame()
                                sep2.setFrameShape(QFrame.HLine)
                                sep2.setStyleSheet("color: #d1d5db;")
                                info_layout.addWidget(sep2)

                                lbl_hist = QLabel("📋 Historial de Pagos:")
                                lbl_hist.setFont(make_font(FONTS['body_bold']))
                                lbl_hist.setStyleSheet("color: #1565c0; background: transparent;")
                                info_layout.addWidget(lbl_hist)

                                if abonos:
                                    abonos_table = QTableWidget()
                                    abonos_table.setColumnCount(4)
                                    abonos_table.setHorizontalHeaderLabels(['Fecha', 'Monto', 'Tipo', 'Usuario'])
                                    abonos_table.horizontalHeader().setStyleSheet(
                                        "QHeaderView::section { background: #e3f2fd; color: black; padding: 4px; border: none; font-weight: 500; font-size: 8pt; }"
                                    )
                                    abonos_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
                                    abonos_table.setSelectionMode(QAbstractItemView.NoSelection)
                                    abonos_table.setSelectionBehavior(QAbstractItemView.SelectRows)
                                    abonos_table.verticalHeader().setVisible(False)
                                    abonos_table.setAlternatingRowColors(True)
                                    abonos_table.setShowGrid(False)
                                    abonos_table.setWordWrap(False)
                                    abonos_table.horizontalHeader().setStretchLastSection(False)
                                    abonos_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
                                    abonos_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
                                    abonos_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
                                    abonos_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)

                                    for idx, abono in enumerate(abonos):
                                        abonos_table.insertRow(idx)
                                        fecha_abono = abono['fecha_abono'][:16] if abono.get('fecha_abono') else 'N/A'
                                        abonos_table.setItem(idx, 0, QTableWidgetItem(fecha_abono))
                                        monto_item = QTableWidgetItem(f"${abono['monto_abono']:,.0f}")
                                        monto_item.setForeground(QBrush(QColor('#10b981')))
                                        abonos_table.setItem(idx, 1, monto_item)
                                        abonos_table.setItem(idx, 2, QTableWidgetItem(abono.get('tipo_pago', 'N/A')))
                                        abonos_table.setItem(idx, 3, QTableWidgetItem(str(abono.get('usuario', 'N/A'))[:12]))

                                        if idx % 2 != 0:
                                            for c in range(4):
                                                abonos_table.item(idx, c).setBackground(QBrush(QColor('#f5f5f5')))

                                    header_height = abonos_table.horizontalHeader().sizeHint().height()
                                    row_height = abonos_table.verticalHeader().defaultSectionSize()
                                    table_height = header_height + (len(abonos) * row_height) + 12
                                    table_height = max(80, min(table_height, 190))
                                    abonos_table.setMinimumHeight(table_height)
                                    abonos_table.setMaximumHeight(table_height)

                                    info_layout.addWidget(abonos_table)

                                    total_abonado = sum(a['monto_abono'] for a in abonos)
                                    l_total_ab = QLabel(f"Total Pagado: ${total_abonado:,.0f}")
                                    l_total_ab.setFont(make_font(FONTS['body_bold']))
                                    l_total_ab.setStyleSheet("color: #10b981; background: #e8f5e9; padding: 4px; border-radius: 4px;")
                                    info_layout.addWidget(l_total_ab)

                                    saldo = total_factura - total_abonado
                                    if saldo > 0:
                                        l_saldo = QLabel(f"⏳ Saldo Pendiente: ${saldo:,.0f}")
                                        l_saldo.setFont(make_font(FONTS['body_bold']))
                                        l_saldo.setStyleSheet("color: #ef4444; background: transparent;")
                                        info_layout.addWidget(l_saldo)
                                    else:
                                        l_pagada = QLabel("✅ Factura Pagada Completamente")
                                        l_pagada.setFont(make_font(FONTS['body_bold']))
                                        l_pagada.setStyleSheet("color: #10b981; background: transparent;")
                                        info_layout.addWidget(l_pagada)
                                else:
                                    l_no = QLabel("No hay pagos registrados")
                                    l_no.setFont(make_font(FONTS['body']))
                                    l_no.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
                                    info_layout.addWidget(l_no)

                            except Exception as e:
                                print(f"[ERROR] Error obteniendo historial de abonos: {e}")
                                import traceback
                                traceback.print_exc()
                                l_err = QLabel(f"Error cargando historial: {str(e)[:50]}")
                                l_err.setFont(make_font(FONTS['small']))
                                l_err.setStyleSheet("color: #ef4444; background: transparent;")
                                info_layout.addWidget(l_err)

                        # Discount
                        descuento = venta.get('descuento', 0)
                        if descuento > 0:
                            l_desc = QLabel(f"🏷️ Descuento Aplicado: ${descuento:,.0f}")
                            l_desc.setFont(make_font(FONTS['body_bold']))
                            l_desc.setStyleSheet("color: #f59e0b; background: transparent;")
                            info_layout.addWidget(l_desc)

                        subtotal = venta.get('subtotal', 0)
                        iva = venta.get('iva', 0)
                        if iva > 0:
                            for txt in [f"Subtotal: ${subtotal:,.0f}", f"IVA: ${iva:,.0f}"]:
                                l = QLabel(txt)
                                l.setFont(make_font(FONTS['body']))
                                l.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
                                info_layout.addWidget(l)

                        estado = venta.get('estado', 'COMPLETADA')
                        color_estado = '#10b981' if estado == 'COMPLETADA' else '#f59e0b' if estado == 'PENDIENTE' else '#ef4444'
                        l_est = QLabel(f"Estado: {estado}")
                        l_est.setFont(make_font(FONTS['body_bold']))
                        l_est.setStyleSheet(f"color: {color_estado}; background: transparent;")
                        info_layout.addWidget(l_est)

                        if venta.get('observaciones'):
                            l_obs = QLabel(f"📝 Observaciones: {venta['observaciones']}")
                            l_obs.setFont(make_font(FONTS['body']))
                            l_obs.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
                            l_obs.setWordWrap(True)
                            info_layout.addWidget(l_obs)
                except Exception as e:
                    print(f"Error obteniendo información de venta: {e}")
                    import traceback
                    traceback.print_exc()

            l_total = QLabel(f"💰 Total de Movimientos: ${total_factura:,.0f}")
            l_total.setFont(make_font(FONTS['heading']))
            l_total.setStyleSheet(f"color: {COLORS['primary']}; background: transparent;")
            info_layout.addWidget(l_total)

            info_scroll.setWidget(info_widget)
            layout.addWidget(info_scroll)

            # Separator
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setStyleSheet("color: #d1d5db;")
            layout.addWidget(sep)

            # Products title
            lbl_prods = QLabel("Productos en esta factura:")
            lbl_prods.setFont(make_font(FONTS['heading']))
            lbl_prods.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent; padding-left: 30px;")
            layout.addWidget(lbl_prods)

            # Products table
            table = QTableWidget()
            table.setColumnCount(7)
            table.setHorizontalHeaderLabels(['ID', 'Producto', 'Tipo Movimiento', 'Cantidad', 'Precio Unitario', 'Total', 'Proveedor'])
            table.horizontalHeader().setStyleSheet(
                f"QHeaderView::section {{ background: {COLORS['table_header']}; color: {COLORS['table_header_fg']}; padding: 9px 8px; border: none; font-weight: 500; }}"
            )
            table.setSelectionBehavior(QAbstractItemView.SelectRows)
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            table.setAlternatingRowColors(True)
            table.verticalHeader().setVisible(False)
            table.setColumnWidth(0, 50)
            table.setColumnWidth(1, 250)
            table.setColumnWidth(2, 150)
            table.setColumnWidth(3, 80)
            table.setColumnWidth(4, 100)
            table.setColumnWidth(5, 100)
            table.setColumnWidth(6, 150)
            table.horizontalHeader().setStretchLastSection(True)

            for item in items_factura:
                row = table.rowCount()
                table.insertRow(row)
                tag = 'entrada' if 'ENTRADA' in item['tipo'] else 'salida'
                bg_color = QColor('#d1fae5') if tag == 'entrada' else QColor('#fee2e2')

                vals = [
                    str(item['id']),
                    item.get('producto_nombre', 'N/A'),
                    item['tipo'].replace('_', ' '),
                    f"{item['cantidad']} unid.",
                    f"${item['precio_unitario']:,.0f}",
                    f"${item['costo_total']:,.0f}",
                    item.get('proveedor_nombre', '-') if item.get('proveedor_id') else '-',
                ]
                for c, v in enumerate(vals):
                    tw = QTableWidgetItem(v)
                    tw.setBackground(QBrush(bg_color))
                    if c in (3, 4, 5):
                        tw.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    table.setItem(row, c, tw)

            layout.addWidget(table, 1)

            # Buttons
            btn_row = QHBoxLayout()
            btn_row.setContentsMargins(30, 10, 30, 15)

            if 'SALIDA' in tipo_principal:
                btn_print = QPushButton("🖨️ Imprimir Factura")
                btn_print.setFont(make_font(FONTS['body_bold']))
                btn_print.setCursor(Qt.PointingHandCursor)
                btn_print.setStyleSheet(
                    "QPushButton { background: #2563eb; color: white; border: none; "
                    "border-radius: 6px; padding: 10px 20px; }"
                    "QPushButton:hover { background: #1d4ed8; }"
                )
                btn_print.clicked.connect(
                    lambda: self._imprimir_factura_movimiento(dialog, num_factura, items_factura, total_factura)
                )
                btn_row.addWidget(btn_print)

            btn_close = QPushButton("Cerrar")
            btn_close.setFont(make_font(FONTS['body_bold']))
            btn_close.setCursor(Qt.PointingHandCursor)
            btn_close.setStyleSheet(
                f"QPushButton {{ background: {COLORS['primary']}; color: white; border: none; "
                f"border-radius: 6px; padding: 10px 40px; }}"
                f"QPushButton:hover {{ background: {COLORS['primary_dark']}; }}"
            )
            btn_close.clicked.connect(dialog.accept)
            btn_row.addWidget(btn_close)

            layout.addLayout(btn_row)
            dialog.exec()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error mostrando detalle de factura:\n{str(e)}")
            import traceback
            traceback.print_exc()

    def _imprimir_factura_movimiento(self, ventana_padre, num_factura, items_factura, total_factura):
        """Imprime una factura desde la sección de movimientos"""
        try:
            from ui.imprimir_factura import imprimir_factura
            from services.ventas_service import VentasService

            ventas_service = VentasService(self.db_manager, self.productos_repo,
                                          self.clientes_repo, self.auth)
            venta = ventas_service.obtener_venta_por_factura(num_factura)

            if venta and venta.get('detalles'):
                venta_data = {
                    'numero_factura': num_factura,
                    'fecha': venta.get('fecha', ''),
                    'total': venta.get('total', total_factura),
                    'subtotal': venta.get('subtotal', total_factura),
                    'descuento': venta.get('descuento', 0),
                    'metodo_pago': venta.get('metodo_pago', 'EFECTIVO'),
                    'cliente_nombre': venta.get('cliente_nombre', 'Cliente General'),
                    'vendedor': venta.get('vendedor', 'Sistema'),
                }
                detalles = []
                for det in venta['detalles']:
                    detalles.append({
                        'producto_nombre': det.get('producto_nombre', 'Producto'),
                        'cantidad': det.get('cantidad', 0),
                        'precio_unitario': det.get('precio_unitario', 0),
                        'subtotal': det.get('subtotal', 0),
                    })
            else:
                venta_data = {
                    'numero_factura': num_factura,
                    'fecha': items_factura[0].get('fecha', '')[:16] if items_factura else '',
                    'total': total_factura,
                    'subtotal': total_factura,
                    'descuento': 0,
                    'metodo_pago': 'EFECTIVO',
                    'cliente_nombre': 'Cliente General',
                    'vendedor': items_factura[0].get('usuario_nombre', 'Sistema') if items_factura else 'Sistema',
                }
                detalles = []
                for item in items_factura:
                    detalles.append({
                        'producto_nombre': item.get('producto_nombre', 'Producto'),
                        'cantidad': item.get('cantidad', 0),
                        'precio_unitario': item.get('precio_unitario', 0),
                        'subtotal': item.get('costo_total', 0),
                    })

            imprimir_factura(ventana_padre, venta_data, detalles)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al preparar impresión:\n{str(e)}")

    def ver_detalle_grupo_sin_factura(self, tipo_label, fecha_mov):
        """Muestra el detalle de un grupo de movimientos sin factura"""
        try:
            movimientos = self.movimientos_service.obtener_historial(limite=1000)

            tipo_busqueda = tipo_label.replace(' ', '_').upper()
            items_grupo = [m for m in movimientos
                          if m['tipo'] == tipo_busqueda
                          and not m.get('num_factura')
                          and m.get('fecha', '')[:16] == fecha_mov]

            if not items_grupo:
                QMessageBox.warning(self, "Sin datos",
                                    f"No se encontraron productos para {tipo_label} en {fecha_mov}")
                return

            dialog = QDialog(self.window())
            dialog.setWindowTitle(f"Detalle: {tipo_label}")
            dialog.resize(900, 700)
            dialog.setStyleSheet("background: white;")

            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            tipo_principal = items_grupo[0]['tipo']
            es_entrada = 'ENTRADA' in tipo_principal

            # Header
            color_h = COLORS['success'] if es_entrada else COLORS['danger']
            header = QFrame()
            header.setFixedHeight(60)
            header.setStyleSheet(f"background: {color_h};")
            hl = QHBoxLayout(header)
            hl.addWidget(self._styled_label(
                f"{'📥 ENTRADA' if es_entrada else '📤 SALIDA'} - {tipo_label}",
                FONTS['large'], "white", color_h, Qt.AlignCenter
            ))
            layout.addWidget(header)

            # Info
            info_w = QWidget()
            info_w.setStyleSheet("background: white;")
            info_l = QVBoxLayout(info_w)
            info_l.setContentsMargins(30, 15, 30, 10)

            fecha = items_grupo[0].get('fecha', 'N/A')[:16]
            usuario = items_grupo[0].get('usuario_nombre', 'Sistema')
            cantidad_productos = len(items_grupo)
            total_grupo = sum(item['costo_total'] for item in items_grupo)

            for txt in [f"📅 Fecha: {fecha}", f"👤 Usuario: {usuario}",
                        f"📦 Productos: {cantidad_productos}"]:
                l = QLabel(txt)
                l.setFont(make_font(FONTS['body_bold']))
                l.setStyleSheet("background: transparent;")
                info_l.addWidget(l)

            if items_grupo[0]['tipo'] == 'ENTRADA_COMPRA' and self.compras_repo:
                try:
                    l_total = QLabel(f"💰 Total del Grupo: ${total_grupo:,.0f}")
                    l_total.setFont(make_font(FONTS['body_bold']))
                    l_total.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent;")
                    info_l.addWidget(l_total)
                    l_warn = QLabel("⚠️ Este grupo no tiene número de factura asignado")
                    l_warn.setFont(make_font(FONTS['small']))
                    l_warn.setStyleSheet(f"color: {COLORS['warning']}; background: transparent;")
                    info_l.addWidget(l_warn)
                except Exception as e:
                    print(f"Error obteniendo información: {e}")
            else:
                l_total = QLabel(f"💰 Total del Grupo: ${total_grupo:,.0f}")
                l_total.setFont(make_font(FONTS['heading']))
                l_total.setStyleSheet(f"color: {COLORS['primary']}; background: transparent;")
                info_l.addWidget(l_total)

            layout.addWidget(info_w)

            # Separator
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setStyleSheet("color: #d1d5db;")
            layout.addWidget(sep)

            # Title
            lbl_prods = QLabel("Productos en este grupo:")
            lbl_prods.setFont(make_font(FONTS['heading']))
            lbl_prods.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent; padding-left: 30px;")
            layout.addWidget(lbl_prods)

            # Table
            table = QTableWidget()
            table.setColumnCount(7)
            table.setHorizontalHeaderLabels(['ID', 'Producto', 'Tipo Movimiento', 'Cantidad', 'Precio Unitario', 'Total', 'Proveedor'])
            table.horizontalHeader().setStyleSheet(
                f"QHeaderView::section {{ background: {COLORS['table_header']}; color: {COLORS['table_header_fg']}; padding: 9px 8px; border: none; font-weight: 500; }}"
            )
            table.setSelectionBehavior(QAbstractItemView.SelectRows)
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            table.setAlternatingRowColors(True)
            table.verticalHeader().setVisible(False)
            table.setColumnWidth(0, 50)
            table.setColumnWidth(1, 250)
            table.setColumnWidth(2, 150)
            table.setColumnWidth(3, 80)
            table.setColumnWidth(4, 100)
            table.setColumnWidth(5, 100)
            table.setColumnWidth(6, 150)
            table.horizontalHeader().setStretchLastSection(True)

            for item in items_grupo:
                row = table.rowCount()
                table.insertRow(row)
                tag = 'entrada' if 'ENTRADA' in item['tipo'] else 'salida'
                bg_color = QColor('#d1fae5') if tag == 'entrada' else QColor('#fee2e2')

                vals = [
                    str(item['id']),
                    item.get('producto_nombre', 'N/A'),
                    item['tipo'].replace('_', ' '),
                    f"{item['cantidad']} unid.",
                    f"${item['precio_unitario']:,.0f}",
                    f"${item['costo_total']:,.0f}",
                    item.get('proveedor_nombre', '-') if item.get('proveedor_id') else '-',
                ]
                for c, v in enumerate(vals):
                    tw = QTableWidgetItem(v)
                    tw.setBackground(QBrush(bg_color))
                    if c in (3, 4, 5):
                        tw.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    table.setItem(row, c, tw)

            layout.addWidget(table, 1)

            # Close button
            btn_close = QPushButton("✅ Cerrar")
            btn_close.setFont(make_font(FONTS['body_bold']))
            btn_close.setCursor(Qt.PointingHandCursor)
            btn_close.setStyleSheet(
                f"QPushButton {{ background: {COLORS['primary']}; color: white; border: none; "
                f"border-radius: 6px; padding: 10px 30px; }}"
                f"QPushButton:hover {{ background: {COLORS['primary_dark']}; }}"
            )
            btn_close.clicked.connect(dialog.accept)
            layout.addWidget(btn_close, alignment=Qt.AlignCenter)
            layout.addSpacing(15)

            dialog.exec()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error mostrando detalle del grupo:\n{str(e)}")
            import traceback
            traceback.print_exc()

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _styled_label(self, text, font_tuple, fg_color, bg_color, alignment=None):
        """Create a styled QLabel."""
        lbl = QLabel(text)
        lbl.setFont(make_font(font_tuple))
        lbl.setStyleSheet(f"color: {fg_color}; background: {bg_color};")
        if alignment:
            lbl.setAlignment(alignment)
        return lbl
