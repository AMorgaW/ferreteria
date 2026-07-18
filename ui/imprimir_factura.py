# -*- coding: utf-8 -*-
"""
Módulo para generar e imprimir facturas de venta.
Genera una ventana de vista previa e imprime usando el sistema nativo de Windows.
PySide6 version.
"""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                                QPushButton, QTextEdit, QComboBox, QMessageBox,
                                QApplication, QFileDialog)
from PySide6.QtCore import Qt, QMarginsF, QSizeF
from PySide6.QtGui import QFont, QPainter, QPageSize, QPageLayout, QPen, QColor
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo
from datetime import datetime
import tempfile
import os


# Controla cuantas lineas en blanco se agregan al final del ticket.
# 0 = sin espacio extra; subir a 1-2 si alguna impresora requiere margen.
FEED_FINAL_LINES = 0


def imprimir_factura(parent, venta_data, detalles, nombre_negocio="FERRETERÍA EL ADOBE"):
    """
    Muestra una vista previa de la factura y permite imprimir.
    """
    dlg = QDialog(parent)
    dlg.setWindowTitle(f"Factura {venta_data.get('numero_factura', '')}")
    dlg.setStyleSheet("background: white;")
    dlg.setWindowModality(Qt.WindowModal)

    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(10, 10, 10, 10)

    contenido = _generar_contenido_factura(venta_data, detalles, nombre_negocio)

    # Calcular altura según número de líneas (mínimo 400, máximo 90% de la pantalla)
    num_lineas = contenido.count('\n') + 1
    px_por_linea = 18  # aprox para Consolas 10pt
    altura_texto = num_lineas * px_por_linea + 80  # +80 para botones y márgenes
    pantalla = QApplication.primaryScreen().availableGeometry()
    altura_max = int(pantalla.height() * 0.90)
    altura_ventana = max(400, min(altura_texto, altura_max))
    dlg.resize(520, altura_ventana)

    text_edit = QTextEdit()
    text_edit.setFont(QFont('Consolas', 10))
    text_edit.setPlainText(contenido)
    text_edit.setReadOnly(True)
    text_edit.setStyleSheet("border: 1px solid #d1d5db; border-radius: 4px;")
    layout.addWidget(text_edit)

    btn_row = QHBoxLayout()
    btn_print = QPushButton("🖨️ Imprimir")
    btn_print.setStyleSheet("""
        QPushButton { background: #2563eb; color: white; border: none;
                     border-radius: 6px; padding: 10px 30px; font-size: 11pt; font-weight: bold; }
        QPushButton:hover { background: #1d4ed8; }
    """)
    btn_print.setCursor(Qt.PointingHandCursor)
    btn_print.clicked.connect(lambda: _enviar_a_imprimir(contenido,
                              venta_data.get('numero_factura', 'factura'), dlg))
    btn_row.addWidget(btn_print)

    btn_pdf = QPushButton("📄 Guardar PDF")
    btn_pdf.setStyleSheet("""
        QPushButton { background: #0f766e; color: white; border: none;
                     border-radius: 6px; padding: 10px 24px; font-size: 11pt; font-weight: bold; }
        QPushButton:hover { background: #115e59; }
    """)
    btn_pdf.setCursor(Qt.PointingHandCursor)
    btn_pdf.clicked.connect(lambda: _guardar_pdf_dialogo(dlg, venta_data, detalles, nombre_negocio))
    btn_row.addWidget(btn_pdf)
    btn_row.addStretch()

    btn_close = QPushButton("Cerrar")
    btn_close.setStyleSheet("""
        QPushButton { background: #64748b; color: white; border: none;
                     border-radius: 6px; padding: 10px 30px; font-size: 11pt; }
        QPushButton:hover { background: #475569; }
    """)
    btn_close.setCursor(Qt.PointingHandCursor)
    btn_close.clicked.connect(dlg.close)
    btn_row.addWidget(btn_close)

    layout.addLayout(btn_row)
    dlg.exec()


def _generar_contenido_factura(venta_data, detalles, nombre_negocio):
    """Genera texto para ticket con ancho fijo por columnas."""
    # 58mm con margen de 5mm por lado: usar menos columnas evita saltos visuales
    # al subir un poco el tamano de fuente en impresion.
    W = 28
    SEP = "=" * W
    SEP2 = "-" * W

    numero_factura = venta_data.get('numero_factura', 'N/A').strip()
    fecha = datetime.now().strftime('%Y-%m-%d %H:%M').strip()
    metodo_pago = venta_data.get('metodo_pago', 'EFECTIVO').strip()
    metodo_display = metodo_pago.replace('_', ' ')

    total = venta_data.get('total', 0)
    subtotal = venta_data.get('subtotal', total)
    descuento = venta_data.get('descuento', 0)
    iva = venta_data.get('iva', 0) or 0

    L = []
    L.append(SEP.strip())
    L.append(_centrar32("FERRETERIA EL ADOBE", W).strip())
    L.append(_centrar32("FACTURA DE VENTA", W).strip())
    L.append(SEP.strip())
    L.append(f"Fact: {numero_factura}"[:W].strip())
    L.append(f"Fecha: {fecha}"[:W].strip())
    L.append(f"Pago: {metodo_display}"[:W].strip())
    L.append(SEP2.strip())

    for det in detalles:
        nombre_completo = det.get('producto_nombre', 'Producto').strip()
        cantidad = det.get('cantidad', 0)
        precio_unit = det.get('precio_unitario', 0)
        item_sub = det.get('subtotal', cantidad * precio_unit)

        while len(nombre_completo) > W:
            L.append(nombre_completo[:W])
            nombre_completo = nombre_completo[W:]
        L.append(nombre_completo)

        from formato import formatear_stock
        izq = f"{formatear_stock(cantidad)} x ${precio_unit:,.0f}"
        der = f"${item_sub:,.0f}"
        L.append(_alinear_item_ticket(izq, der, W))

        if det.get('es_mezcla'):
            L.append("*" * W)
            L.append(_centrar32("MEZCLA PERSONALIZADA", W).strip())
            L.append("*" * W)
            vol = det.get('mezcla_volumen', 0)
            L.append(f"  Vol. total: {vol:.3f}L")
            L.append("  Componentes:")
            for comp_txt in det.get('mezcla_componentes', []):
                L.append(f"   - {comp_txt}"[:W])
            L.append("*" * W)

    L.append(SEP2.strip())

    if descuento > 0:
        L.append(_alinear32("Subtotal:", f"${subtotal:,.0f}", W).strip())
        L.append(_alinear32("Descuento:", f"${descuento:,.0f}", W).strip())

    if iva and iva > 0:
        base = total - iva
        L.append(_alinear32("Base gravable:", f"${base:,.0f}", W).strip())
        L.append(_alinear32("IVA incluido:", f"${iva:,.0f}", W).strip())

    L.append(_alinear32("TOTAL:", f"${total:,.0f}", W).strip())
    L.append(SEP.strip())
    L.append(_centrar32("Gracias por su compra!", W).strip())

    for _ in range(FEED_FINAL_LINES):
        L.append("")

    return "\r\n".join(L)


def _centrar32(texto, w):
    t = texto.strip()
    if len(t) >= w:
        return t[:w]
    total_esp = w - len(t)
    izq = total_esp // 2
    der = total_esp - izq
    return (" " * izq) + t + (" " * der)


def _alinear32(label, valor, w):
    l = label.strip()
    v = valor.strip()
    esp = w - len(l) - len(v)
    if esp < 1:
        esp = 1
    return f"{l}{' ' * esp}{v}"


def _alinear_item_ticket(izq, der, w):
    """Mantiene el subtotal al extremo derecho en una sola fila."""
    left = izq.strip()
    right = der.strip()

    # Reserva minimo un espacio entre ambas partes.
    max_left = max(1, w - len(right) - 1)
    if len(left) > max_left:
        left = left[:max_left]

    esp = w - len(left) - len(right)
    if esp < 1:
        esp = 1
    return f"{left}{' ' * esp}{right}"


def _enviar_a_imprimir(contenido, nombre_archivo, parent_dlg=None):
    """Muestra selector de impresora y envia factura con QPrinter (58mm)."""
    try:
        impresoras_info = QPrinterInfo.availablePrinters()
        nombres = [p.printerName() for p in impresoras_info]

        if not nombres:
            QMessageBox.critical(parent_dlg, "Error",
                                 "No se encontraron impresoras instaladas.")
            return

        sel = QDialog(parent_dlg)
        sel.setWindowTitle("Seleccionar Impresora")
        sel.setFixedSize(400, 200)
        sel.setStyleSheet("background: white;")
        sl = QVBoxLayout(sel)
        sl.setContentsMargins(20, 15, 20, 15)

        sl.addWidget(QLabel("Seleccione la impresora:"))

        default_name = QPrinterInfo.defaultPrinter().printerName()
        combo = QComboBox()
        combo.addItems(nombres)
        idx = combo.findText(default_name)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        sl.addWidget(combo)
        sl.addStretch()

        btn_row = QHBoxLayout()
        btn_ok = QPushButton("Imprimir")
        btn_ok.setStyleSheet("""
            QPushButton { background: #2563eb; color: white; border: none;
                         border-radius: 6px; padding: 8px 20px; font-weight: bold; }
            QPushButton:hover { background: #1d4ed8; }
        """)
        btn_ok.setCursor(Qt.PointingHandCursor)

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setStyleSheet("""
            QPushButton { background: #64748b; color: white; border: none;
                         border-radius: 6px; padding: 8px 20px; }
            QPushButton:hover { background: #475569; }
        """)
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.clicked.connect(sel.reject)

        def confirmar():
            sel.accept()
            _imprimir_directo(contenido, combo.currentText(), parent_dlg)

        btn_ok.clicked.connect(confirmar)
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        sl.addLayout(btn_row)

        sel.exec()

    except Exception as e:
        QMessageBox.critical(parent_dlg, "Error",
                             f"No se pudo imprimir:\n{str(e)}")


def _imprimir_directo(contenido, nombre_impresora, parent_dlg=None):
    """Imprime en impresora termica 58mm usando QPrinter con tamaño de papel exacto."""
    try:
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setPrinterName(nombre_impresora)
        printer.setFullPage(True)

        # Papel 58mm ancho, alto calculado segun contenido
        lineas = contenido.strip().split('\n')
        fuente = QFont('Courier New', 8)
        fuente.setBold(True)
        fuente.setWeight(QFont.Weight.DemiBold)
        fuente.setStyleHint(QFont.StyleHint.TypeWriter)
        fuente.setStyleStrategy(QFont.StyleStrategy.PreferMatch)
        # Altura aprox por linea para 8pt.
        alto_mm = max(len(lineas) * 3.9 + 10, 50.0)

        printer.setPageSize(
            QPageSize(QSizeF(58.0, alto_mm), QPageSize.Unit.Millimeter)
        )
        printer.setPageMargins(QMarginsF(5, 2, 5, 2), QPageLayout.Unit.Millimeter)
        printer.setPageOrientation(QPageLayout.Orientation.Portrait)
        printer.setColorMode(QPrinter.ColorMode.GrayScale)
        printer.setResolution(300)

        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.critical(parent_dlg, "Error",
                                 "No se pudo iniciar la impresión.")
            return

        painter.setPen(QPen(QColor(0, 0, 0), 0.8))
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, False)
        painter.setFont(fuente)
        fm = painter.fontMetrics()
        line_h = fm.height()
        x = 0
        y = fm.ascent()

        for linea in lineas:
            painter.drawText(x, y, linea)
            y += line_h

        painter.end()
        QMessageBox.information(parent_dlg, "Imprimir",
                                "Factura enviada a la impresora.")

    except Exception as e:
        QMessageBox.critical(parent_dlg, "Error",
                             f"Error al imprimir:\n{str(e)}")


def factura_a_pdf(venta_data, detalles, path, nombre_negocio="FERRETERÍA EL ADOBE"):
    """Genera un PDF imprimible del recibo, con el MISMO layout que la impresión
    térmica (58mm). Devuelve la ruta del PDF generado."""
    contenido = _generar_contenido_factura(venta_data, detalles, nombre_negocio)
    lineas = contenido.strip().split('\n')

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(path)
    printer.setFullPage(True)

    fuente = QFont('Courier New', 8)
    fuente.setBold(True)
    fuente.setStyleHint(QFont.StyleHint.TypeWriter)
    fuente.setStyleStrategy(QFont.StyleStrategy.PreferMatch)
    alto_mm = max(len(lineas) * 3.9 + 12, 50.0)
    printer.setPageSize(QPageSize(QSizeF(58.0, alto_mm), QPageSize.Unit.Millimeter))
    printer.setPageMargins(QMarginsF(5, 2, 5, 2), QPageLayout.Unit.Millimeter)
    printer.setPageOrientation(QPageLayout.Orientation.Portrait)
    printer.setResolution(300)

    painter = QPainter()
    if not painter.begin(printer):
        raise RuntimeError("No se pudo iniciar la generación del PDF")
    try:
        painter.setPen(QPen(QColor(0, 0, 0), 0.8))
        painter.setFont(fuente)
        fm = painter.fontMetrics()
        line_h = fm.height()
        x = 0
        y = fm.ascent()
        for linea in lineas:
            painter.drawText(x, y, linea)
            y += line_h
    finally:
        painter.end()
    return path


def _guardar_pdf_dialogo(parent, venta_data, detalles, nombre_negocio):
    """Pide ruta y guarda el recibo como PDF."""
    numero = str(venta_data.get('numero_factura', 'factura')).replace('/', '-')
    sugerido = f"factura_{numero}.pdf"
    path, _ = QFileDialog.getSaveFileName(parent, "Guardar recibo en PDF",
                                          sugerido, "PDF (*.pdf)")
    if not path:
        return
    if not path.lower().endswith(".pdf"):
        path += ".pdf"
    try:
        factura_a_pdf(venta_data, detalles, path, nombre_negocio)
        QMessageBox.information(parent, "PDF generado", f"Recibo guardado en:\n{path}")
    except Exception as exc:
        QMessageBox.critical(parent, "Error al generar PDF", str(exc))
