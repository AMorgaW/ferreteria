# -*- coding: utf-8 -*-
"""
Exportación simple a Excel (.xlsx) compatible con Microsoft Excel.
Sin formatos visuales complejos: encabezados en negrita y ancho automático.
"""
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter


def exportar_a_excel(path: str, headers: list, rows: list, sheet_name: str = "Datos") -> str:
    """Escribe una hoja con encabezados + filas. Devuelve la ruta."""
    wb = Workbook()
    ws = wb.active
    ws.title = (sheet_name or "Datos")[:31]

    ws.append(list(headers))
    for celda in ws[1]:
        celda.font = Font(bold=True)

    for fila in rows:
        ws.append(list(fila))

    # Ancho de columna aproximado según el contenido
    for col_idx, _h in enumerate(headers, start=1):
        max_len = len(str(headers[col_idx - 1]))
        for fila in rows:
            if col_idx - 1 < len(fila):
                max_len = max(max_len, len(str(fila[col_idx - 1])))
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max_len + 2, 50)

    ws.freeze_panes = "A2"
    wb.save(path)
    return path


def _money(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def exportar_inventario(productos_repo, path: str) -> str:
    """Exporta el catálogo completo con stock y valor de inventario."""
    productos = productos_repo.listar_productos(solo_activos=False)
    headers = ["SKU", "Nombre", "Categoría", "Marca", "Presentación",
               "P. Compra", "P. Venta", "Stock", "Stock Mín.", "U. Medida",
               "Valor (compra)", "Activo"]
    from formato import formatear_stock
    rows = []
    for p in productos:
        stock = _money(p.get("stock"))
        compra = _money(p.get("precio_compra"))
        permite = p.get("permite_decimales")
        rows.append([
            p.get("codigo_barras") or "",
            p.get("nombre") or "",
            p.get("categoria") or "",
            p.get("marca") or "",
            p.get("presentacion") or "",
            compra,
            _money(p.get("precio_venta")),
            formatear_stock(stock, permite),
            formatear_stock(p.get("stock_minimo"), permite),
            p.get("unidad_medida") or "",
            round(stock * compra, 2),
            "Sí" if p.get("activo", 1) else "No",
        ])
    return exportar_a_excel(path, headers, rows, "Inventario")


def exportar_ventas(ventas: list, path: str) -> str:
    """Exporta una lista de ventas (dicts de VentasService.listar_ventas)."""
    headers = ["Factura", "Fecha", "Cliente", "Vendedor", "Subtotal",
               "Descuento", "Total", "Método de Pago", "Estado"]
    rows = []
    for v in ventas:
        rows.append([
            v.get("numero_factura") or "",
            str(v.get("fecha") or ""),
            v.get("cliente_nombre") or "Consumidor Final",
            v.get("vendedor") or "",
            _money(v.get("subtotal")),
            _money(v.get("descuento")),
            _money(v.get("total")),
            v.get("metodo_pago") or "",
            v.get("estado") or "",
        ])
    return exportar_a_excel(path, headers, rows, "Ventas")


def exportar_compras(compras: list, path: str) -> str:
    """Exporta una lista de compras (dicts)."""
    headers = ["ID", "Fecha", "Proveedor", "Factura", "Tipo", "Total",
               "Estado Pago", "Saldo"]
    rows = []
    for c in compras:
        rows.append([
            c.get("id") or c.get("numero") or "",
            str(c.get("fecha") or ""),
            c.get("proveedor_nombre") or c.get("proveedor") or "",
            c.get("numero_factura") or c.get("factura") or "",
            c.get("tipo_pago") or c.get("tipo") or "",
            _money(c.get("total")),
            c.get("estado_pago") or "",
            _money(c.get("saldo_pendiente") or c.get("saldo")),
        ])
    return exportar_a_excel(path, headers, rows, "Compras")


def exportar_tabla_qt(table, path: str, sheet_name: str = "Reporte") -> str:
    """Exporta el contenido visible de un QTableWidget a Excel (duck-typed,
    no requiere importar PySide6 aquí). Sirve para cualquier reporte tabular."""
    cols = table.columnCount()
    headers = []
    for c in range(cols):
        item = table.horizontalHeaderItem(c)
        headers.append(item.text() if item is not None else f"Col{c + 1}")
    rows = []
    for r in range(table.rowCount()):
        if table.isRowHidden(r):
            continue
        fila = []
        for c in range(cols):
            item = table.item(r, c)
            fila.append(item.text() if item is not None else "")
        rows.append(fila)
    return exportar_a_excel(path, headers, rows, sheet_name)


def nombre_sugerido(prefijo: str) -> str:
    """Nombre de archivo sugerido con marca temporal."""
    return f"{prefijo}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
