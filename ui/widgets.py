# -*- coding: utf-8 -*-
"""
Widgets modernos reutilizables para PySide6.
Todos los colores se leen de COLORS (ui_config) — fuente única de verdad.
"""
from PySide6.QtWidgets import (QFrame, QLabel, QHBoxLayout, QVBoxLayout,
                                QPushButton, QGraphicsDropShadowEffect,
                                QWidget, QSizePolicy)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor

from ui_config import COLORS


class ShadowCard(QFrame):
    """
    Tarjeta con sombra real via QGraphicsDropShadowEffect.
    Esquinas redondeadas via QSS.

    Uso:
        card = ShadowCard(parent)
        layout = QVBoxLayout(card)
        layout.addWidget(QLabel("Hola"))
    """

    def __init__(self, parent=None, bg_card=None,
                 shadow_color=None, shadow_blur=18,
                 border_color=None, border_radius=16,
                 content_margins=(14, 10, 14, 10)):
        super().__init__(parent)
        bg_card = bg_card or COLORS['bg_primary']
        shadow_color = shadow_color or COLORS['shadow_card']
        border_css = f"border: 1px solid {border_color};" if border_color else "border: none;"
        self.setStyleSheet(f"""
            ShadowCard {{
                background: {bg_card};
                border-radius: {border_radius}px;
                {border_css}
            }}
        """)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(shadow_blur)
        shadow.setColor(QColor(shadow_color))
        shadow.setOffset(0, 3)
        self.setGraphicsEffect(shadow)

        self.setContentsMargins(*content_margins)


class HoverButton(QPushButton):
    """
    Botón del sidebar con efecto hover suave y estado activo (pill azul claro).
    """

    def __init__(self, parent=None, text='', icon='',
                 font_family='Segoe UI', font_size=10,
                 bg=None, fg=None,
                 hover_bg=None, hover_fg=None,
                 active_bg=None, active_fg=None,
                 padx=18, pady=10, command=None):
        display = f"{icon}  {text}" if icon else text
        super().__init__(display, parent)
        self.setCursor(Qt.PointingHandCursor)

        self._bg = bg or COLORS['bg_primary']
        self._fg = fg or COLORS['text_secondary']
        self._hover_bg = hover_bg or COLORS['bg_hover']
        self._hover_fg = hover_fg or COLORS['text_primary']
        self._active_bg = active_bg or COLORS['primary_light']
        self._active_fg = active_fg or COLORS['primary']
        self._is_active = False
        self._font_size = font_size
        self._font_family = font_family

        self._apply_style()

        if command:
            self.clicked.connect(command)

    def _apply_style(self):
        bg = self._active_bg if self._is_active else self._bg
        fg = self._active_fg if self._is_active else self._fg
        weight = '600' if self._is_active else 'normal'
        hover_bg = self._active_bg if self._is_active else self._hover_bg
        hover_fg = self._active_fg if self._is_active else self._hover_fg
        self.setStyleSheet(f"""
            QPushButton {{
                background: {bg}; color: {fg};
                border: none; border-radius: 8px;
                text-align: left; padding: 8px 14px;
                font-family: '{self._font_family}';
                font-size: {self._font_size}pt;
                font-weight: {weight};
            }}
            QPushButton:hover {{
                background: {hover_bg}; color: {hover_fg};
            }}
        """)

    def set_active(self, active=True):
        self._is_active = active
        self._apply_style()


class ActionButton(QPushButton):
    """
    Botón de acción estilizado. Sólido o outlined.
    """

    def __init__(self, parent=None, text='',
                 bg=None, fg=None,
                 hover_bg=None, border_color=None,
                 border_radius=6, padx=18, pady=8,
                 font_size=10, bold=False,
                 command=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)

        bg = bg or COLORS['bg_primary']
        fg = fg or COLORS['text_secondary']
        border_color = border_color or COLORS['border_input']
        hbg = hover_bg or self._lighten(bg)
        weight = 'bold' if bold else 'normal'
        self.setStyleSheet(f"""
            QPushButton {{
                background: {bg}; color: {fg};
                border: 1px solid {border_color};
                border-radius: {border_radius}px;
                padding: {pady}px {padx}px;
                font-size: {font_size}pt;
                font-weight: {weight};
            }}
            QPushButton:hover {{
                background: {hbg};
            }}
        """)
        if command:
            self.clicked.connect(command)

    @staticmethod
    def _lighten(hex_color):
        try:
            r = min(255, int(hex_color[1:3], 16) + 15)
            g = min(255, int(hex_color[3:5], 16) + 15)
            b = min(255, int(hex_color[5:7], 16) + 15)
            return f'#{r:02x}{g:02x}{b:02x}'
        except Exception:
            return '#f0f0f0'


class KpiCard(ShadowCard):
    """
    Tarjeta KPI con título, valor, subtítulo y badge opcional.
    """

    def __init__(self, parent=None, title='', value='', subtitle='',
                 badge_text='', badge_color=None,
                 title_color=None, value_color=None):
        super().__init__(parent, border_radius=16, shadow_blur=18,
                         shadow_color=COLORS['shadow_card'],
                         content_margins=(20, 14, 20, 14))

        badge_color = badge_color or COLORS['success']
        title_color = title_color or COLORS['kpi_title']
        value_color = value_color or COLORS['kpi_value']
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(0, 0, 0, 0)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"""
            font-size: 7pt; font-weight: 600; color: {title_color};
            letter-spacing: 0.8px; text-transform: uppercase;
            background: transparent; border: none;
        """)
        layout.addWidget(title_lbl)

        row = QHBoxLayout()
        row.setSpacing(10)
        val_lbl = QLabel(value)
        val_lbl.setStyleSheet(f"""
            font-size: 20pt; font-weight: bold; color: {value_color};
            background: transparent; border: none;
        """)
        row.addWidget(val_lbl)

        if badge_text:
            badge = QLabel(badge_text)
            badge.setStyleSheet(f"""
                background: {badge_color}; color: white;
                border-radius: 9px; padding: 2px 10px;
                font-size: 7pt; font-weight: bold;
            """)
            badge.setFixedHeight(20)
            row.addWidget(badge, 0, Qt.AlignVCenter)

        row.addStretch()
        layout.addLayout(row)

        if subtitle:
            sub_lbl = QLabel(subtitle)
            sub_lbl.setStyleSheet(f"""
                font-size: 8pt; color: {COLORS['kpi_subtitle']};
                background: transparent; border: none;
            """)
            layout.addWidget(sub_lbl)

        self._value_label = val_lbl
        self._title_label = title_lbl
        self._badge = None

    def set_value(self, text):
        self._value_label.setText(text)
