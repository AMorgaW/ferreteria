# -*- coding: utf-8 -*-
"""
Widgets modernos reutilizables para PySide6.
Todos los colores se leen de COLORS (ui_config) — fuente única de verdad.
"""
from PySide6.QtWidgets import (QFrame, QLabel, QHBoxLayout, QVBoxLayout,
                                QPushButton, QGraphicsDropShadowEffect,
                                QWidget, QSizePolicy)
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QSize, QRectF
from PySide6.QtGui import (QFont, QColor, QIcon, QPixmap, QPainter, QPen,
                           QBrush, QPainterPath)

from ui_config import COLORS


def make_line_icon(name, color='#FFFFFF', size=24):
    """Crea iconos vectoriales compactos sin depender de fuentes emoji."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(size / 24.0, size / 24.0)
    pen = QPen(QColor(color), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    if name in ('dashboard', 'grid'):
        for x, y in ((3, 3), (13, 3), (3, 13), (13, 13)):
            painter.drawRoundedRect(QRectF(x, y, 8, 8), 1.4, 1.4)
    elif name in ('productos', 'box'):
        painter.drawRect(QRectF(4, 7, 16, 13))
        painter.drawLine(4, 7, 12, 3)
        painter.drawLine(12, 3, 20, 7)
        painter.drawLine(12, 3, 12, 20)
        painter.drawLine(4, 7, 12, 11)
        painter.drawLine(20, 7, 12, 11)
    elif name in ('clientes', 'usuarios'):
        painter.drawEllipse(QRectF(8, 3, 8, 8))
        painter.drawArc(QRectF(4, 11, 16, 10), 0, 180 * 16)
        if name == 'clientes':
            painter.drawEllipse(QRectF(2, 7, 5, 5))
            painter.drawEllipse(QRectF(17, 7, 5, 5))
    elif name in ('proveedores', 'brand'):
        path = QPainterPath()
        path.moveTo(3, 10); path.lineTo(12, 3); path.lineTo(21, 10)
        painter.drawPath(path)
        painter.drawRect(QRectF(5, 10, 14, 11))
        painter.drawRect(QRectF(10, 14, 4, 7))
    elif name in ('compras', 'cart', 'sales_today'):
        painter.drawLine(3, 5, 6, 5)
        painter.drawLine(6, 5, 8, 16)
        painter.drawLine(8, 16, 19, 16)
        painter.drawLine(8, 8, 21, 8)
        painter.drawLine(21, 8, 19, 14)
        painter.drawEllipse(QRectF(8, 18, 2, 2))
        painter.drawEllipse(QRectF(17, 18, 2, 2))
    elif name in ('ventas', 'coin'):
        painter.drawEllipse(QRectF(4, 4, 16, 16))
        painter.drawLine(12, 7, 12, 17)
        painter.drawArc(QRectF(8, 7, 8, 5), 30 * 16, 230 * 16)
        painter.drawArc(QRectF(8, 12, 8, 5), 210 * 16, 230 * 16)
    elif name in ('movimientos', 'clipboard'):
        painter.drawRoundedRect(QRectF(5, 4, 14, 17), 1.5, 1.5)
        painter.drawRoundedRect(QRectF(8, 2, 8, 4), 1, 1)
        painter.drawLine(8, 10, 16, 10)
        painter.drawLine(8, 14, 16, 14)
        painter.drawLine(8, 18, 13, 18)
    elif name in ('caja', 'credit'):
        painter.drawRoundedRect(QRectF(3, 6, 18, 13), 2, 2)
        painter.drawLine(3, 10, 21, 10)
        painter.drawLine(7, 15, 12, 15)
        if name == 'credit':
            painter.drawEllipse(QRectF(15, 13, 7, 7))
    elif name in ('reportes', 'chart', 'sales_month'):
        painter.drawLine(4, 20, 21, 20)
        painter.drawLine(4, 20, 4, 4)
        painter.drawRoundedRect(QRectF(7, 12, 3, 7), 1, 1)
        painter.drawRoundedRect(QRectF(12, 8, 3, 11), 1, 1)
        painter.drawRoundedRect(QRectF(17, 4, 3, 15), 1, 1)
    elif name in ('configuracion', 'settings'):
        painter.drawEllipse(QRectF(8, 8, 8, 8))
        for x1, y1, x2, y2 in ((12, 2, 12, 6), (12, 18, 12, 22),
                               (2, 12, 6, 12), (18, 12, 22, 12),
                               (5, 5, 8, 8), (16, 16, 19, 19),
                               (5, 19, 8, 16), (16, 8, 19, 5)):
            painter.drawLine(x1, y1, x2, y2)
    elif name == 'stock':
        path = QPainterPath()
        path.moveTo(12, 3); path.lineTo(22, 20); path.lineTo(2, 20); path.closeSubpath()
        painter.drawPath(path)
        painter.drawLine(12, 8, 12, 14)
        painter.drawPoint(12, 17)
    elif name == 'calendar':
        painter.drawRoundedRect(QRectF(4, 5, 16, 15), 2, 2)
        painter.drawLine(4, 9, 20, 9)
        painter.drawLine(8, 3, 8, 7)
        painter.drawLine(16, 3, 16, 7)
    elif name == 'refresh':
        painter.drawArc(QRectF(4, 4, 16, 16), 35 * 16, 285 * 16)
        painter.drawLine(18, 4, 20, 8)
        painter.drawLine(18, 4, 14, 5)
    elif name == 'alertas':
        painter.drawArc(QRectF(6, 5, 12, 12), 0, 180 * 16)
        painter.drawLine(6, 11, 6, 17)
        painter.drawLine(18, 11, 18, 17)
        painter.drawLine(5, 17, 19, 17)
        painter.drawArc(QRectF(10, 17, 4, 4), 180 * 16, 180 * 16)
    elif name == 'support':
        painter.drawArc(QRectF(4, 4, 16, 16), 0, 180 * 16)
        painter.drawLine(4, 12, 4, 18)
        painter.drawLine(20, 12, 20, 18)
        painter.drawLine(20, 18, 16, 18)
    elif name == 'salir':
        painter.drawRect(QRectF(4, 3, 11, 18))
        painter.drawLine(10, 12, 22, 12)
        painter.drawLine(18, 8, 22, 12)
        painter.drawLine(18, 16, 22, 12)

    painter.end()
    return QIcon(pixmap)


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
        border_css = f"border: 1px solid {border_color or COLORS['border']};"
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


def button_qss(kind='primary', radius=9):
    """QSS inline reutilizable para botones, con el lenguaje visual FERREPRO.
    kind: primary | success | dark | ghost | ghost_danger | danger | warning."""
    C = COLORS
    base = (f"QPushButton {{ border-radius: {radius}px; padding: 9px 16px; }}")
    specs = {
        'primary': (C['accent'], C['on_accent'], 'none', '500', C['accent_hover']),
        'success': (C['success'], 'white', 'none', '500', C['success_dark']),
        'dark': (C['primary'], 'white', 'none', '500', C['primary_dark']),
        'danger': (C['danger'], 'white', 'none', '500', C['danger_dark']),
        'warning': (C['warning'], 'white', 'none', '500', C['warning_dark']),
    }
    if kind == 'ghost':
        return (
            f"QPushButton {{ background: {C['bg_primary']}; color: {C['text_body']};"
            f" border: 1px solid {C['border_input']}; border-radius: {radius}px;"
            f" padding: 9px 16px; font-weight: 500; }}"
            f"QPushButton:hover {{ background: {C['bg_hover']}; border-color: {C['primary_border']}; }}"
        )
    if kind == 'ghost_danger':
        return (
            f"QPushButton {{ background: {C['bg_primary']}; color: {C['danger']};"
            f" border: 1px solid {C['danger']}; border-radius: {radius}px;"
            f" padding: 9px 16px; font-weight: 500; }}"
            f"QPushButton:hover {{ background: {C['danger']}; color: white; }}"
        )
    bg, fg, border, weight, hover = specs.get(kind, specs['primary'])
    return (
        f"QPushButton {{ background: {bg}; color: {fg}; border: {border};"
        f" border-radius: {radius}px; padding: 9px 16px; font-weight: {weight}; }}"
        f"QPushButton:hover {{ background: {hover}; }}"
    )


class AnimatedCard(ShadowCard):
    """
    ShadowCard que eleva su sombra suavemente al pasar el mouse
    (micro-interacción natural vía QPropertyAnimation sobre el blur).
    """

    def __init__(self, *args, hover_blur=None, **kwargs):
        base_blur = kwargs.get('shadow_blur', 18)
        super().__init__(*args, **kwargs)
        self._base_blur = base_blur
        self._hover_blur = hover_blur if hover_blur is not None else base_blur + 12
        self._shadow_effect = self.graphicsEffect()
        self._hover_anim = QPropertyAnimation(self._shadow_effect, b"blurRadius", self)
        self._hover_anim.setDuration(160)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)

    def _animate_blur(self, value):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._shadow_effect.blurRadius())
        self._hover_anim.setEndValue(value)
        self._hover_anim.start()

    def enterEvent(self, event):
        self._animate_blur(self._hover_blur)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_blur(self._base_blur)
        super().leaveEvent(event)


class Badge(QLabel):
    """Etiqueta tipo pill (estado / conteo)."""

    def __init__(self, text='', parent=None, bg=None, fg='white',
                 font_size=7, bold=True):
        super().__init__(text, parent)
        bg = bg or COLORS['success']
        weight = '500'
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(f"""
            background: {bg}; color: {fg};
            border-radius: 9px; padding: 2px 10px;
            font-size: {font_size}pt; font-weight: {weight};
        """)
        self.setFixedHeight(20)


class HoverButton(QPushButton):
    """
    Botón del sidebar con efecto hover suave y estado activo (pill).
    """

    def __init__(self, parent=None, text='', icon='',
                 font_family='Segoe UI', font_size=10,
                 bg=None, fg=None,
                 hover_bg=None, hover_fg=None,
                 active_bg=None, active_fg=None,
                 padx=18, pady=10, command=None):
        self._icon_key = icon if icon and icon.isascii() else None
        display = text if self._icon_key else (f"{icon}  {text}" if icon else text)
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
        weight = '500' if self._is_active else 'normal'
        hover_bg = self._active_bg if self._is_active else self._hover_bg
        hover_fg = self._active_fg if self._is_active else self._hover_fg
        if self._icon_key:
            self.setIcon(make_line_icon(self._icon_key, fg, 20))
            self.setIconSize(QSize(20, 20))
        self.setStyleSheet(f"""
            QPushButton {{
                background: {bg}; color: {fg};
                border: none; border-radius: 9px;
                text-align: left; padding: 10px 14px;
                font-family: '{self._font_family}';
                font-size: {self._font_size}pt;
                font-weight: {weight};
            }}
            QPushButton:hover {{
                background: {hover_bg}; color: {hover_fg};
            }}
            QPushButton:pressed {{
                background: {COLORS['primary_dark']}; color: white;
            }}
            QPushButton:focus {{
                border: 1px solid {COLORS['accent']};
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
        weight = '500' if bold else 'normal'
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
            QPushButton:pressed {{
                background: {self._lighten(hbg)};
            }}
            QPushButton:focus {{
                border: 2px solid {COLORS['primary_border']};
            }}
            QPushButton:disabled {{
                background: {COLORS['bg_pressed']}; color: {COLORS['text_light']};
                border-color: {COLORS['border']};
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


class KpiCard(AnimatedCard):
    """
    Tarjeta KPI con título, valor, subtítulo y badge opcional.
    Eleva su sombra al pasar el mouse (hereda de AnimatedCard).
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
            font-size: 7pt; font-weight: 500; color: {title_color};
            letter-spacing: 0.8px; text-transform: uppercase;
            background: transparent; border: none;
        """)
        layout.addWidget(title_lbl)

        row = QHBoxLayout()
        row.setSpacing(10)
        val_lbl = QLabel(value)
        val_lbl.setStyleSheet(f"""
            font-size: 20pt; font-weight: 500; color: {value_color};
            background: transparent; border: none;
        """)
        row.addWidget(val_lbl)

        if badge_text:
            badge = QLabel(badge_text)
            badge.setStyleSheet(f"""
                background: {badge_color}; color: white;
                border-radius: 9px; padding: 2px 10px;
                font-size: 7pt; font-weight: 500;
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


def hacer_dialogo_responsivo(dialog, ancho_pref=None, alto_pref=None,
                             alto_max_factor=0.9):
    """Garantiza que un QDialog nunca exceda el tamaño de la pantalla y que,
    si su contenido no cabe en lo alto, pueda desplazarse con scroll — de modo
    que ningún control (incluidos los botones de acción) quede inalcanzable en
    pantallas pequeñas o laptops.

    No modifica widgets, campos ni lógica: reubica el layout ya construido del
    diálogo dentro de un QScrollArea y ajusta tamaño/posición. Llamar DESPUÉS
    de construir todo el contenido y ANTES de exec().
    """
    from PySide6.QtWidgets import QScrollArea, QApplication
    scr = (dialog.screen().availableGeometry() if dialog.screen()
           else QApplication.primaryScreen().availableGeometry())

    w = ancho_pref or dialog.width()
    h = alto_pref or dialog.height()
    w = min(w, int(scr.width() * 0.95))
    h_max = int(scr.height() * alto_max_factor)
    h = min(h, h_max)

    old_layout = dialog.layout()
    if old_layout is not None:
        # Mover el layout (y todos sus hijos) a un contenedor desplazable.
        contenido = QWidget()
        contenido.setLayout(old_layout)
        scroll = QScrollArea(dialog)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll.setWidget(contenido)
        nuevo = QVBoxLayout(dialog)
        nuevo.setContentsMargins(0, 0, 0, 0)
        nuevo.setSpacing(0)
        nuevo.addWidget(scroll)

    # Liberar cualquier tamaño fijo previo y limitar a la pantalla.
    dialog.setMinimumSize(0, 0)
    dialog.setMaximumHeight(h_max)
    dialog.resize(w, h)
    try:
        center = scr.center()
        dialog.move(center.x() - w // 2, center.y() - h // 2)
    except Exception:
        pass
