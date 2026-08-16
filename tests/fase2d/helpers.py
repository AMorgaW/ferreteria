from __future__ import annotations

import sqlite3
from pathlib import Path

from openpyxl import Workbook

from inventory_import_schema import ensure_inventory_import_schema
from product_inventory_contract import OPERATIONAL_INVENTORY_FIELDS


def valid_row(**updates):
    row = {
        "nombre": "Martillo profesional",
        "categoria": "Herramientas Manuales",
        "marca": "ACME",
        "precio_compra": 10000,
        "precio_venta": 15000,
        "stock_minimo": 2,
        "unidad_base": "UNIDAD",
        "presentacion_empaque": "CAJA",
        "cantidad_base_por_empaque": 4,
        "vende_unidad_base": "SI",
        "vende_medio_empaque": "NO",
        "vende_empaque_completo": "SI",
        "permite_decimales": "NO",
        "empaques_completos_contados": 2,
        "unidades_sueltas_contadas": 1,
        "cantidad_total_excel": 9,
        "barcode_primero": "",
        "barcode_segundo": "",
    }
    row.update(updates)
    return row


def write_workbook(path: Path, rows, *, fields=None, extras=None):
    fields = list(fields or OPERATIONAL_INVENTORY_FIELDS)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "CONTEO"
    headers = [label for _key, label in fields]
    if extras:
        headers.extend(extras)
    sheet.append(headers)
    for data in rows:
        values = [data.get(key) for key, _label in fields]
        if extras:
            values.extend(["IGNORAR"] * len(extras))
        sheet.append(values)
    workbook.save(path)
    workbook.close()
    return path


def make_connection(path=":memory:"):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        """
        CREATE TABLE productos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            local_id TEXT UNIQUE NOT NULL,
            nombre TEXT NOT NULL,
            categoria TEXT,
            marca TEXT,
            presentacion TEXT,
            unidad_medida TEXT,
            precio_compra REAL,
            precio_venta REAL,
            stock_minimo REAL,
            stock REAL DEFAULT 0,
            activo INTEGER DEFAULT 1
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE product_barcodes (
            local_id TEXT PRIMARY KEY,
            producto_local_id TEXT NOT NULL,
            barcode TEXT UNIQUE NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    ensure_inventory_import_schema(conn)
    conn.commit()
    return conn


def insert_product(conn, *, local_id="11111111-1111-4111-8111-111111111111", name="Martillo profesional", category="Herramientas Manuales", brand="ACME", presentation="CAJA", unit="UNIDAD", stock=0):
    conn.execute(
        """
        INSERT INTO productos (
            local_id, nombre, categoria, marca, presentacion, unidad_medida,
            precio_compra, precio_venta, stock_minimo, stock, activo
        ) VALUES (?, ?, ?, ?, ?, ?, 10000, 15000, 2, ?, 1)
        """,
        (local_id, name, category, brand, presentation, unit, stock),
    )
    conn.commit()
    return local_id
