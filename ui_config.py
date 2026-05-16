# -*- coding: utf-8 -*-
"""
Configuración de estilos y colores para la interfaz de usuario (PySide6)
Fuente ÚNICA de verdad para toda la paleta visual del sistema.
"""

# ─── Paleta de colores semántica ─────────────────────────────
# Cambiar un valor aquí se propaga a TODA la aplicación.
COLORS = {
    # ── Marca / Acción principal (navy profundo — ref. ProcureFlow) ──
    'primary': '#0C3547',
    'primary_dark': '#091F32',
    'primary_light': '#E3EFF5',
    'primary_border': '#B0CFE0',
    'primary_hover_light': '#CCDEE8',
    'secondary': '#64748B',
    'secondary_dark': '#475569',

    # ── Semáforo de estados ──
    'success': '#10B981',
    'success_dark': '#059669',
    'danger': '#EF4444',
    'danger_dark': '#DC2626',
    'danger_light': '#FEE2E2',
    'warning': '#F59E0B',
    'warning_dark': '#D97706',
    'warning_light': '#FEF3C7',
    'warning_border': '#FCD34D',
    'warning_hover_light': '#FDE68A',
    'info': '#3B82F6',
    'credito': '#D97706',

    # ── Fondos ──
    'bg_primary': '#ffffff',
    'bg_secondary': '#F7F8FA',
    'bg_hover': '#F1F5F9',
    'bg_pressed': '#E2E8F0',
    'bg_sidebar': '#ffffff',
    'bg_dark': '#0C3547',

    # ── Texto ──
    'text_primary': '#0F172A',
    'text_secondary': '#64748B',
    'text_light': '#94A3B8',
    'text_on_dark': '#ffffff',
    'text_body': '#334155',
    'text_value': '#0F172A',

    # ── Bordes y líneas ──
    'border': '#E2E8F0',
    'border_input': '#CBD5E1',
    'border_light': '#F1F5F9',
    'disabled': '#CBD5E1',

    # ── Tabla ──
    'table_header': '#0C3547',
    'table_header_border': '#164E63',
    'table_row_alt': '#F8FAFC',
    'table_row_border': '#F1F5F9',
    'table_selection': '#E3EFF5',

    # ── Sombras (usadas en QGraphicsDropShadowEffect) ──
    'shadow_card': '#CBD5E1',

    # ── Banner de deudas ──
    'debt_bg': '#78350F',
    'debt_dark': '#451A03',
    'debt_accent': '#FBBF24',
    'debt_shadow': '#92400E',

    # ── Tarjeta KPI ──
    'kpi_title': '#94A3B8',
    'kpi_subtitle': '#94A3B8',
    'kpi_value': '#0F172A',
}

FONTS = {
    'small': ('Segoe UI', 9),
    'body': ('Segoe UI', 10),
    'body_bold': ('Segoe UI', 10, 'bold'),
    'heading': ('Segoe UI', 14, 'bold'),
    'large': ('Segoe UI', 16, 'bold'),
    'xlarge': ('Segoe UI', 20, 'bold'),
}

DIMENSIONS = {
    'sidebar_width': 250,
    'header_height': 70,
    'statusbar_height': 30,
    'button_height': 40,
    'input_height': 35,
}

ICONS = {
    'dashboard': '📊',
    'productos': '📦',
    'clientes': '👥',
    'proveedores': '🏪',
    'ventas': '💰',
    'movimientos': '📋',
    'caja': '💵',
    'reportes': '📈',
    'usuarios': '👤',
    'configuracion': '⚙️',
    'alertas': '🔔',
    'buscar': '🔍',
    'agregar': '➕',
    'editar': '✏️',
    'eliminar': '🗑️',
    'guardar': '💾',
    'cancelar': '❌',
    'aceptar': '✅',
    'imprimir': '🖨️',
    'exportar': '📤',
    'importar': '📥',
    'actualizar': '🔄',
    'salir': '🚪',
    'herramienta': '🔧',
}


def make_font(font_tuple):
    """Convierte tupla de fuente a QFont."""
    from PySide6.QtGui import QFont
    family = font_tuple[0]
    size = font_tuple[1]
    bold = len(font_tuple) > 2 and font_tuple[2] == 'bold'
    f = QFont(family, size)
    if bold:
        f.setBold(True)
    return f


def _build_qss():
    """Genera el QSS global inyectando valores de COLORS."""
    C = COLORS
    return f"""
QWidget {{
    font-family: 'Inter', 'Segoe UI', 'Roboto', sans-serif;
    font-size: 10pt;
}}
QMainWindow {{ background: {C['bg_secondary']}; }}

QPushButton {{
    border: 1px solid {C['border_input']}; border-radius: 8px;
    padding: 8px 18px; background: {C['bg_primary']}; color: {C['text_primary']};
}}
QPushButton:hover {{ background: {C['bg_hover']}; border-color: #c6c6c6; }}
QPushButton:pressed {{ background: {C['bg_pressed']}; }}
QPushButton#primaryBtn {{
    background: {C['primary']}; color: {C['text_on_dark']}; border: none;
    font-weight: 600; border-radius: 8px;
}}
QPushButton#primaryBtn:hover {{ background: {C['primary_dark']}; }}
QPushButton#dangerBtn {{
    background: {C['danger']}; color: {C['text_on_dark']}; border: none; border-radius: 8px;
}}
QPushButton#dangerBtn:hover {{ background: {C['danger_dark']}; }}
QPushButton#warningBtn {{
    background: {C['warning']}; color: {C['text_on_dark']}; border: none;
    font-weight: 600; border-radius: 8px;
}}
QPushButton#warningBtn:hover {{ background: {C['warning_dark']}; }}

QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    border: 1px solid {C['border_input']}; border-radius: 8px;
    padding: 8px 12px; background: {C['bg_primary']}; color: {C['text_primary']};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {C['primary']};
}}
QComboBox::drop-down {{ border: none; padding-right: 8px; }}
QComboBox QAbstractItemView {{
    border: 1px solid {C['border_input']}; background: {C['bg_primary']};
    selection-background-color: {C['primary_light']}; selection-color: {C['text_primary']};
}}

QTableWidget, QTableView {{
    border: none; background: {C['bg_primary']};
    alternate-background-color: {C['table_row_alt']}; gridline-color: transparent;
    selection-background-color: {C['table_selection']}; selection-color: {C['text_primary']};
    font-size: 9pt;
}}
QHeaderView::section {{
    background: {C['table_header']}; color: {C['text_on_dark']}; font-weight: 600;
    font-size: 8pt; padding: 10px 8px; border: none;
    border-right: 1px solid {C['table_header_border']};
}}
QHeaderView::section:first {{ border-top-left-radius: 12px; }}
QHeaderView::section:last {{ border-top-right-radius: 12px; border-right: none; }}
QHeaderView::section:hover {{ background: {C['table_header_border']}; }}

QScrollBar:vertical {{
    background: transparent; width: 6px; border: none; border-radius: 3px;
}}
QScrollBar::handle:vertical {{
    background: {C['border_input']}; border-radius: 3px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {C['text_light']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: transparent; height: 6px; border: none; border-radius: 3px;
}}
QScrollBar::handle:horizontal {{
    background: {C['border_input']}; border-radius: 3px; min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{ background: {C['text_light']}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

QGroupBox {{
    border: 1px solid {C['border']}; border-radius: 12px;
    margin-top: 12px; padding-top: 18px; font-weight: 600; color: {C['text_primary']};
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; }}

QToolTip {{
    background: {C['text_primary']}; color: {C['text_on_dark']}; border: none;
    border-radius: 6px; padding: 6px 10px; font-size: 9pt;
}}

QDialog {{ background: {C['bg_primary']}; }}

QMenu {{
    background: {C['bg_primary']}; border: 1px solid {C['border']};
    border-radius: 8px; padding: 4px;
}}
QMenu::item {{ padding: 8px 24px; border-radius: 4px; }}
QMenu::item:selected {{ background: {C['bg_hover']}; color: {C['text_primary']}; }}

QCheckBox, QRadioButton {{ spacing: 8px; color: {C['text_primary']}; }}

QDateEdit {{
    border: 1px solid {C['border_input']}; border-radius: 6px;
    padding: 8px 12px; background: {C['bg_primary']}; color: {C['text_primary']};
}}
QDateEdit:focus {{ border-color: {C['primary']}; }}
"""


GLOBAL_QSS = _build_qss()