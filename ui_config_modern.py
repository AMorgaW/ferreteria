"""
Configuración de UI Moderna y Atractiva
Colores vibrantes, gradientes y diseño interactivo
"""

# Paleta de colores moderna y vibrante
COLORS_MODERN = {
    # Colores principales (vibrantes)
    'primary': '#4F46E5',          # Indigo vibrante
    'primary_dark': '#3730A3',     # Indigo oscuro
    'primary_light': '#818CF8',    # Indigo claro

    'secondary': '#EC4899',        # Rosa vibrante
    'secondary_dark': '#BE185D',   # Rosa oscuro
    'secondary_light': '#F9A8D4',  # Rosa claro

    'accent': '#8B5CF6',           # Púrpura
    'accent_alt': '#F59E0B',       # Ámbar

    # Colores de estado
    'success': '#10B981',          # Verde esmeralda
    'success_light': '#6EE7B7',
    'danger': '#EF4444',           # Rojo
    'danger_light': '#FCA5A5',
    'warning': '#F59E0B',          # Ámbar
    'warning_light': '#FCD34D',
    'info': '#3B82F6',             # Azul
    'info_light': '#93C5FD',

    # Grises modernos
    'bg_main': '#F8FAFC',          # Gris muy claro
    'bg_secondary': '#F1F5F9',     # Gris claro
    'bg_card': '#FFFFFF',          # Blanco
    'bg_hover': '#E2E8F0',         # Gris hover

    'text_primary': '#0F172A',     # Casi negro
    'text_secondary': '#64748B',   # Gris medio
    'text_light': '#94A3B8',       # Gris claro

    'border': '#E2E8F0',           # Borde sutil
    'border_focus': '#4F46E5',     # Borde con focus

    # Degradados (simulados con colores sólidos)
    'gradient_start': '#4F46E5',
    'gradient_end': '#7C3AED',
}

# Fuentes más grandes y legibles
FONTS_MODERN = {
    'title': ('Segoe UI', 32, 'bold'),
    'heading': ('Segoe UI', 20, 'bold'),
    'subheading': ('Segoe UI', 16, 'bold'),
    'body': ('Segoe UI', 12),
    'body_bold': ('Segoe UI', 12, 'bold'),
    'large': ('Segoe UI', 14),
    'large_bold': ('Segoe UI', 14, 'bold'),
    'xlarge': ('Segoe UI', 24, 'bold'),
    'small': ('Segoe UI', 10),
    'number': ('Consolas', 16, 'bold'),  # Para números/precios
    'number_large': ('Consolas', 28, 'bold'),  # Para totales
}

# Dimensiones
DIMENSIONS = {
    'button_height': 45,
    'button_padding': 15,
    'card_padding': 20,
    'border_radius': 12,  # Nota: Tkinter no soporta nativamente, pero lo simulamos
    'shadow_offset': 2,
}

# Íconos con emojis modernos
ICONS = {
    'cart': '🛒',
    'product': '📦',
    'search': '🔍',
    'user': '👤',
    'money': '💰',
    'edit': '✏️',
    'delete': '🗑️',
    'add': '➕',
    'check': '[OK]',
    'close': '✗',
    'alert': '[AVISO]',
    'star': '⭐',
    'clock': '🕐',
    'calendar': '📅',
    'chart': '[REPORTE]',
    'settings': '⚙️',
    'logout': '🚪',
}
