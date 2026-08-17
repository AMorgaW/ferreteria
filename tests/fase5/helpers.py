# -*- coding: utf-8 -*-
"""Helpers Fase 5. SQLite temporal. Nunca ferreteria.db comercial."""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from tests.fase0.harness import REPO_FERRETERIA_DB
from tests.fase1e.helpers import AuthPermitido, ClientesRepoDummy
from tests.fase3d.helpers import (
    assert_not_commercial_db,
    caja_service,
    complete_sale_cash,
    count_movements,
    open_caja,
    phase3d_env,
    pos_service,
    seed_pos_product,
)

phase5_env = phase3d_env

EXPECTED_LATEST_TABLES = (
    "schema_migrations",
    "inventory_import_batches",
    "inventory_import_rows",
    "reversal_documents",
    "reversal_lines",
    "cash_movements",
    "operational_balance_legacy_payments",
    "abonos_ventas",
    "abonos_compras",
)

__all__ = [
    "EXPECTED_LATEST_TABLES",
    "FileDb",
    "assert_not_commercial_db",
    "caja_service",
    "commercial_sha256",
    "complete_sale_as",
    "complete_sale_cash",
    "count_movements",
    "insert_legacy_abono_venta",
    "insert_legacy_sale",
    "make_legacy_station_db",
    "open_caja",
    "phase5_env",
    "pos_service",
    "pos_service_as",
    "seed_pos_product",
    "table_exists",
]


class FileDb:
    """Adapter mínimo para repositorios/servicios sobre un archivo SQLite."""

    def __init__(self, path):
        self.db_name = str(path)

    def conectar(self):
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn


def commercial_sha256() -> str:
    if not REPO_FERRETERIA_DB.exists():
        return ""
    return hashlib.sha256(REPO_FERRETERIA_DB.read_bytes()).hexdigest()


def table_exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def make_legacy_station_db(path) -> Path:
    """SQLite de estación pre-catálogo 2A–4B. Sin schema_migrations."""
    db_path = Path(path)
    if db_path.resolve() == REPO_FERRETERIA_DB.resolve():
        raise RuntimeError("se negó a escribir ferreteria.db comercial")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(
            """
            CREATE TABLE productos (
                id INTEGER PRIMARY KEY,
                local_id TEXT UNIQUE NOT NULL,
                nombre TEXT NOT NULL,
                precio_venta REAL DEFAULT 0,
                stock REAL DEFAULT 0,
                activo INTEGER DEFAULT 1
            );
            CREATE TABLE compras (
                id INTEGER PRIMARY KEY,
                proveedor_id INTEGER,
                numero_factura TEXT,
                total REAL DEFAULT 0,
                monto_pagado REAL DEFAULT 0,
                saldo_pendiente REAL DEFAULT 0,
                estado TEXT DEFAULT 'COMPLETADA',
                estado_pago TEXT DEFAULT 'PENDIENTE'
            );
            CREATE TABLE ventas (
                id INTEGER PRIMARY KEY,
                total REAL NOT NULL,
                monto_pagado REAL DEFAULT 0,
                estado TEXT DEFAULT 'COMPLETADA',
                metodo_pago TEXT DEFAULT 'CREDITO',
                estado_pago TEXT DEFAULT 'PENDIENTE',
                fecha TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE detalle_ventas (
                id INTEGER PRIMARY KEY,
                venta_id INTEGER NOT NULL,
                producto_id INTEGER NOT NULL,
                cantidad INTEGER NOT NULL,
                precio_unitario REAL NOT NULL,
                subtotal REAL NOT NULL
            );
            CREATE TABLE abonos_ventas (
                id INTEGER PRIMARY KEY,
                id_venta INTEGER NOT NULL,
                monto_abono REAL NOT NULL,
                fecha_abono TEXT,
                tipo_pago TEXT
            );
            CREATE TABLE abonos_compras (
                id INTEGER PRIMARY KEY,
                id_compra INTEGER NOT NULL,
                monto_abono REAL NOT NULL
            );
            CREATE TABLE cierres_caja (
                id INTEGER PRIMARY KEY,
                usuario_id INTEGER NOT NULL,
                fecha_apertura TEXT,
                fecha_cierre TEXT,
                monto_inicial REAL DEFAULT 0
            );
            CREATE TABLE usuarios (
                id INTEGER PRIMARY KEY,
                username TEXT,
                password_hash TEXT,
                nombre_completo TEXT,
                rol TEXT
            );
            CREATE TABLE devoluciones (
                id INTEGER PRIMARY KEY,
                venta_id INTEGER NOT NULL,
                fecha TEXT,
                usuario_id INTEGER,
                motivo TEXT,
                tipo TEXT,
                total_devuelto REAL DEFAULT 0
            );
            CREATE TABLE devolucion_detalle (
                id INTEGER PRIMARY KEY,
                devolucion_id INTEGER NOT NULL,
                venta_id INTEGER NOT NULL,
                producto_id INTEGER NOT NULL,
                cantidad REAL NOT NULL,
                precio_unitario REAL,
                subtotal REAL
            );
            INSERT INTO usuarios (id, username, password_hash, nombre_completo, rol)
            VALUES (1, 'tester', 'x', 'Tester', 'ADMIN');
            INSERT INTO productos (id, local_id, nombre, precio_venta, stock)
            VALUES (1, '11111111-1111-4111-8111-111111111111', 'Tornillo legacy', 1000, 20);
            """
        )
        conn.commit()
        assert not table_exists(conn, "schema_migrations")
        assert not table_exists(conn, "inventory_import_batches")
        assert not table_exists(conn, "reversal_documents")
        assert not table_exists(conn, "operational_balance_legacy_payments")
        cols = {row[1] for row in conn.execute("PRAGMA table_info(cierres_caja)")}
        assert "station_id" not in cols
    finally:
        conn.close()
    return db_path


def insert_legacy_sale(path, *, total, monto_pagado, sale_id=None) -> int:
    conn = sqlite3.connect(str(path))
    try:
        cursor = conn.execute(
            "INSERT INTO ventas (id, total, monto_pagado, estado, metodo_pago) "
            "VALUES (?, ?, ?, 'COMPLETADA', 'CREDITO')",
            (sale_id, total, monto_pagado),
        )
        venta_id = sale_id or cursor.lastrowid
        conn.execute(
            "INSERT INTO detalle_ventas "
            "(venta_id, producto_id, cantidad, precio_unitario, subtotal) "
            "VALUES (?, 1, 1, ?, ?)",
            (venta_id, total, total),
        )
        conn.commit()
        return int(venta_id)
    finally:
        conn.close()


def insert_legacy_abono_venta(path, venta_id, monto) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "INSERT INTO abonos_ventas (id_venta, monto_abono, fecha_abono, tipo_pago) "
            "VALUES (?, ?, date('now'), 'EFECTIVO')",
            (venta_id, monto),
        )
        conn.commit()
    finally:
        conn.close()


def pos_service_as(env, rol="VENDEDOR", station_id="W01"):
    from repositories.productos_repo import ProductosRepository
    from services.ventas_service import VentasService

    svc = VentasService(
        env.db,
        ProductosRepository(env.db),
        ClientesRepoDummy(),
        AuthPermitido(rol=rol),
    )
    svc.cash_station_id = station_id
    return svc


def complete_sale_as(env, rol="VENDEDOR", items=None, station_id="W01", **kwargs):
    import uuid

    from tests.fase1e1.helpers import transport_applied

    svc = pos_service_as(env, rol=rol, station_id=station_id)
    items = items or [{"producto_id": 1, "cantidad": 1, "precio_unitario": 1000}]
    kwargs.setdefault("metodo_pago", "EFECTIVO")
    kwargs.setdefault("inventory_mode", "authoritative")
    kwargs.setdefault("inventory_command_id", str(uuid.uuid4()))
    kwargs.setdefault("inventory_transport", transport_applied())
    ok, msg, venta = svc.registrar_venta(items=items, **kwargs)
    if not ok:
        raise AssertionError(msg)
    return venta
