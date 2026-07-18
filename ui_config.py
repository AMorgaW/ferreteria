# -*- coding: utf-8 -*-
"""
Configuración de estilos y colores para la interfaz de usuario (PySide6)
Fuente ÚNICA de verdad para toda la paleta visual del sistema.
"""

# ─── Paleta de colores semántica ─────────────────────────────
# Cambiar un valor aquí se propaga a TODA la aplicación.
COLORS = {
    # ── Marca / superficies oscuras ──
    'primary': '#122033',
    'primary_dark': '#0B1626',
    'primary_light': '#E9EEF5',
    'primary_border': '#BBC7D6',
    'primary_hover_light': '#DDE5EF',
    'secondary': '#64748B',
    'secondary_dark': '#475569',

    # ── Acento de marca (naranja cálido El Adobe) ──
    'accent': '#E4572E',
    'accent_dark': '#C84420',
    'accent_light': '#FBE8E1',
    'accent_hover': '#EE6A40',
    'on_accent': '#FFFFFF',

    # ── Sidebar oscuro (navy) ──
    'sidebar_bg': '#122033',
    'sidebar_bg_alt': '#0B1626',
    'sidebar_fg': '#D2DAE6',
    'sidebar_brand': '#FFFFFF',
    'sidebar_active_bg': '#E4572E',
    'sidebar_active_fg': '#FFFFFF',
    'sidebar_hover_bg': '#1E3048',
    'sidebar_hover_fg': '#FFFFFF',
    'sidebar_border': '#2A3C54',

    # ── Semáforo de estados ──
    'success': '#1D9E75',
    'success_dark': '#0F6E56',
    'danger': '#E24B4A',
    'danger_dark': '#A32D2D',
    'danger_light': '#FCEBEB',
    'warning': '#F59E0B',
    'warning_dark': '#854F0B',
    'warning_light': '#FAEEDA',
    'warning_border': '#F0D49A',
    'warning_hover_light': '#F5E2C0',
    'info': '#378ADD',
    'credito': '#854F0B',

    # ── Fondos ──
    'bg_primary': '#FFFFFF',
    'bg_secondary': '#F6F8FB',
    'bg_hover': '#EEF2F7',
    'bg_pressed': '#E2E8F0',
    'bg_sidebar': '#122033',
    'bg_dark': '#122033',

    # ── Texto ──
    'text_primary': '#172033',
    'text_secondary': '#64748B',
    'text_light': '#94A3B8',
    'text_on_dark': '#ffffff',
    'text_body': '#334155',
    'text_value': '#172033',

    # ── Bordes y líneas ──
    'border': '#E4E9F0',
    'border_input': '#CED6E1',
    'border_light': '#EEF1F6',
    'disabled': '#CBD5E1',

    # ── Tabla ──
    'table_header': '#122033',
    'table_header_fg': '#CDD7E6',
    'table_header_border': '#22324C',
    'table_row_alt': '#FAFBFC',
    'table_row_border': '#EEF1F6',
    'table_selection': '#FBE8E1',

    # ── Sombras (usadas en QGraphicsDropShadowEffect) ──
    'shadow_card': '#C9D1DC',

    # ── Banner de deudas ──
    'debt_bg': '#78350F',
    'debt_dark': '#451A03',
    'debt_accent': '#FBBF24',
    'debt_shadow': '#92400E',

    # ── Tarjeta KPI ──
    'kpi_title': '#94A3B8',
    'kpi_subtitle': '#94A3B8',
    'kpi_value': '#172033',
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
    'sidebar_width': 236,
    'header_height': 50,
    'statusbar_height': 32,
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
    """Convierte tupla de fuente a QFont.

    Por lineamiento de diseño FERREPRO solo se usan pesos 400 (Normal) y
    500 (Medium); nunca 600/700. Las tuplas marcadas como 'bold' se mapean
    a peso Medium para mantener jerarquía sin engrosar el texto.
    """
    from PySide6.QtGui import QFont
    family = font_tuple[0]
    size = font_tuple[1]
    bold = len(font_tuple) > 2 and font_tuple[2] == 'bold'
    f = QFont(family, size)
    if bold:
        f.setWeight(QFont.Medium)
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
QPushButton:hover {{ background: {C['bg_hover']}; border-color: {C['primary_border']}; }}
QPushButton:pressed {{ background: {C['bg_pressed']}; }}
QPushButton:disabled {{ background: {C['bg_pressed']}; color: {C['text_light']}; border-color: {C['border']}; }}
QPushButton:focus {{
    border: 2px solid {C['accent']}; padding: 7px 17px;
}}
QPushButton#primaryBtn {{
    background: {C['accent']}; color: {C['on_accent']}; border: none;
    font-weight: 500; border-radius: 8px;
}}
QPushButton#primaryBtn:hover {{
    background: {C['accent_hover']}; color: {C['on_accent']}; border: none;
}}
QPushButton#primaryBtn:focus {{
    background: {C['accent']}; color: {C['on_accent']};
    border: 2px solid {C['accent_dark']}; padding: 7px 17px;
}}
QPushButton#primaryBtn:pressed {{
    background: {C['accent_dark']}; color: {C['on_accent']}; border: none;
}}
QPushButton#successBtn {{
    background: {C['success']}; color: {C['text_on_dark']}; border: none;
    font-weight: 500; border-radius: 8px;
}}
QPushButton#successBtn:hover {{ background: {C['success_dark']}; }}
QPushButton#darkBtn {{
    background: {C['primary']}; color: {C['text_on_dark']}; border: none;
    font-weight: 500; border-radius: 8px;
}}
QPushButton#darkBtn:hover {{ background: {C['primary_dark']}; }}
QPushButton#dangerBtn {{
    background: {C['danger']}; color: {C['text_on_dark']}; border: none; border-radius: 8px;
}}
QPushButton#dangerBtn:hover {{ background: {C['danger_dark']}; }}
QPushButton#ghostBtn {{
    background: {C['bg_primary']}; color: {C['text_body']};
    border: 1px solid {C['border_input']}; border-radius: 8px; font-weight: 500;
}}
QPushButton#ghostBtn:hover {{ background: {C['bg_hover']}; border-color: {C['primary_border']}; }}
QPushButton#ghostDangerBtn {{
    background: {C['bg_primary']}; color: {C['danger']};
    border: 1px solid {C['danger']}; border-radius: 8px; font-weight: 500;
}}
QPushButton#ghostDangerBtn:hover {{ background: {C['danger']}; color: white; }}
QPushButton#warningBtn {{
    background: {C['warning']}; color: {C['text_on_dark']}; border: none;
    font-weight: 500; border-radius: 8px;
}}
QPushButton#warningBtn:hover {{ background: {C['warning_dark']}; }}

QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    border: 1px solid {C['border_input']}; border-radius: 8px;
    padding: 8px 12px; background: {C['bg_primary']}; color: {C['text_primary']};
    selection-background-color: {C['accent_light']}; selection-color: {C['text_primary']};
}}
QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 2px solid {C['accent']}; padding: 7px 11px;
}}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{
    border-color: {C['primary_border']};
}}
QComboBox::drop-down {{ border: none; padding-right: 8px; }}
QComboBox QAbstractItemView {{
    border: 1px solid {C['border_input']}; border-radius: 8px; background: {C['bg_primary']};
    selection-background-color: {C['accent_light']}; selection-color: {C['text_primary']};
    outline: none; padding: 4px;
}}

QTableWidget, QTableView {{
    border: none; background: {C['bg_primary']};
    alternate-background-color: {C['table_row_alt']}; gridline-color: transparent;
    selection-background-color: {C['table_selection']}; selection-color: {C['text_primary']};
    font-size: 9pt;
}}
QTableWidget::item, QTableView::item {{ padding: 6px 4px; }}
QTableWidget::item:hover, QTableView::item:hover {{ background: {C['bg_hover']}; }}
QTableWidget::item:selected, QTableView::item:selected {{
    background: {C['table_selection']}; color: {C['text_primary']};
}}
QHeaderView::section {{
    background: {C['table_header']}; color: {C['table_header_fg']}; font-weight: 500;
    font-size: 8pt; padding: 11px 8px; border: none;
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
    margin-top: 12px; padding-top: 18px; font-weight: 500; color: {C['text_primary']};
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
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px; border: 1px solid {C['border_input']}; background: {C['bg_primary']};
}}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    border-color: {C['accent']}; background: {C['accent']};
}}

QProgressBar {{
    min-height: 8px; border: none; border-radius: 4px; background: {C['bg_hover']};
    text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {C['success']}; border-radius: 4px; }}

QDateEdit {{
    border: 1px solid {C['border_input']}; border-radius: 9px;
    padding: 8px 12px; background: {C['bg_primary']}; color: {C['text_primary']};
}}
QDateEdit:focus {{ border: 2px solid {C['accent']}; padding: 7px 11px; }}

QTabBar::tab {{
    background: transparent; color: {C['text_secondary']};
    padding: 9px 18px; border: none; font-weight: 500;
    border-top-left-radius: 9px; border-top-right-radius: 9px;
}}
QTabBar::tab:selected {{ background: {C['bg_primary']}; color: {C['text_primary']}; }}
QTabBar::tab:hover:!selected {{ color: {C['text_primary']}; }}
QTabWidget::pane {{ border: 1px solid {C['border']}; border-radius: 12px; top: -1px; }}
"""


GLOBAL_QSS = _build_qss()
