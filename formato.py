# -*- coding: utf-8 -*-
"""
Formato centralizado de cantidades/stock para mostrar al usuario.

La base de datos conserva SIEMPRE la precisión completa (no se redondea al
guardar). Aquí solo se formatea para PANTALLA / reportes:

- Productos sin decimales  -> entero:        40, 15, 350
- Productos con decimales  -> máx. 2 dec.:   16.97, 2.25, 10.50
- Valores enteros          -> sin decimales:  40.00 -> 40
"""


def formatear_stock(valor, permite_decimales=None) -> str:
    """Devuelve el stock/cantidad formateado para mostrar.

    permite_decimales:
        False -> entero (redondeado)
        True/None -> hasta 2 decimales; si es entero exacto, sin decimales.
    """
    try:
        v = float(valor or 0)
    except (TypeError, ValueError):
        return "0"

    if permite_decimales is False:
        return f"{int(round(v))}"

    v2 = round(v, 2)
    if v2 == int(v2):
        return f"{int(v2)}"
    return f"{v2:.2f}"
