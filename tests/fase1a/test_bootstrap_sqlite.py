# -*- coding: utf-8 -*-
"""FASE 1A: bootstrap SQLite canónico. BD tempfile; nunca copia ferreteria.db."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase0.harness import (
    REPO_FERRETERIA_DB,
    _patch_local_paths,
    _restore_local_paths,
    official_temp_db,
)

CRITICAL_TABLES = (
    "usuarios",
    "proveedores",
    "productos",
    "clientes",
    "ventas",
    "detalle_ventas",
    "movimientos",
    "movimientos_inventario",
    "compras",
    "detalle_compras",
    "cierres_caja",
    "cuentas_por_cobrar",
    "pagos_cuentas",
    "alertas",
    "abonos_compras",
    "abonos_ventas",
    "egresos_caja",
    "auditoria",
    "configuracion",
    "categorias_config",
    "sync_queue",
    "sync_conflicts",
    "sync_state",
)

COMPRAS_PAGO_COLS = ("estado_pago", "monto_pagado", "saldo_pendiente")
PRODUCTO_EXTRA_COLS = (
    "unidades_por_media_caja",
    "vende_por_empaque",
    "usar_unidades_categoria",
)


def _tables(conn):
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def _columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _seed_prev_version(db_path: Path) -> None:
    """Esquema oficial anterior: INTEGER PK, sin columnas añadidas en 1A."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE proveedores (
                id INTEGER PRIMARY KEY,
                nit TEXT UNIQUE,
                nombre TEXT NOT NULL,
                telefono TEXT,
                activo INTEGER DEFAULT 1
            );
            CREATE TABLE productos (
                id INTEGER PRIMARY KEY,
                codigo_barras TEXT UNIQUE,
                nombre TEXT NOT NULL,
                categoria TEXT,
                marca TEXT,
                presentacion TEXT,
                proveedor_id INTEGER,
                precio_compra REAL DEFAULT 0,
                precio_venta REAL NOT NULL,
                stock INTEGER DEFAULT 0,
                stock_minimo INTEGER DEFAULT 10,
                unidad_medida TEXT DEFAULT 'UNIDAD',
                viene_en_caja INTEGER DEFAULT 0,
                unidades_por_caja INTEGER DEFAULT 1,
                permite_decimales INTEGER DEFAULT 0,
                iva REAL DEFAULT 0,
                activo INTEGER DEFAULT 1,
                FOREIGN KEY (proveedor_id) REFERENCES proveedores(id)
            );
            CREATE TABLE compras (
                id INTEGER PRIMARY KEY,
                proveedor_id INTEGER NOT NULL,
                numero_factura TEXT,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                tipo_compra TEXT DEFAULT 'CONTADO',
                subtotal REAL DEFAULT 0,
                total REAL NOT NULL,
                observaciones TEXT,
                usuario_id INTEGER,
                estado TEXT DEFAULT 'COMPLETADA',
                FOREIGN KEY (proveedor_id) REFERENCES proveedores(id)
            );
            INSERT INTO proveedores (id, nombre, activo) VALUES (1, 'PrevProv', 1);
            INSERT INTO productos (id, codigo_barras, nombre, precio_venta, stock, activo)
                VALUES (1, 'PREV-001', 'PrevProd', 1000, 5, 1);
            INSERT INTO compras (id, proveedor_id, numero_factura, total, estado)
                VALUES (1, 1, 'FAC-PREV', 50, 'COMPLETADA');
            """
        )
        conn.commit()
    finally:
        conn.close()


class BootstrapSqliteTest(unittest.TestCase):
    def test_1_bd_nueva_tiene_tablas_criticas(self):
        with official_temp_db() as env:
            self.assertNotEqual(env.db_path.resolve(), REPO_FERRETERIA_DB.resolve())
            conn = env.connect()
            try:
                tables = _tables(conn)
                missing = [t for t in CRITICAL_TABLES if t not in tables]
                self.assertEqual(missing, [], msg=f"Faltan tablas: {missing}")
                for col in COMPRAS_PAGO_COLS:
                    self.assertIn(col, _columns(conn, "compras"))
                for col in PRODUCTO_EXTRA_COLS:
                    self.assertIn(col, _columns(conn, "productos"))
            finally:
                conn.close()

    def test_2_pk_autogenerada_no_null_distinta_estable(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                conn.execute(
                    "INSERT INTO proveedores (nombre, activo) VALUES (?, 1)",
                    ("Prov A",),
                )
                id_a = conn.execute(
                    "SELECT id FROM proveedores WHERE nombre=?", ("Prov A",)
                ).fetchone()[0]
                conn.execute(
                    "INSERT INTO proveedores (nombre, activo) VALUES (?, 1)",
                    ("Prov B",),
                )
                id_b = conn.execute(
                    "SELECT id FROM proveedores WHERE nombre=?", ("Prov B",)
                ).fetchone()[0]
                conn.execute(
                    "INSERT INTO productos (nombre, precio_venta, stock) VALUES (?, ?, ?)",
                    ("Prod A", 1, 0),
                )
                pid_a = conn.execute(
                    "SELECT id FROM productos WHERE nombre=?", ("Prod A",)
                ).fetchone()[0]
                conn.execute(
                    "INSERT INTO productos (nombre, precio_venta, stock) VALUES (?, ?, ?)",
                    ("Prod B", 1, 0),
                )
                pid_b = conn.execute(
                    "SELECT id FROM productos WHERE nombre=?", ("Prod B",)
                ).fetchone()[0]
                conn.commit()
                self.assertIsNotNone(id_a)
                self.assertIsNotNone(id_b)
                self.assertNotEqual(id_a, id_b)
                self.assertIsNotNone(pid_a)
                self.assertIsNotNone(pid_b)
                self.assertNotEqual(pid_a, pid_b)
                info = {
                    r[1]: r[2] for r in conn.execute("PRAGMA table_info(productos)")
                }
                self.assertEqual(info["id"].upper(), "INTEGER")
                again_a = conn.execute(
                    "SELECT id FROM proveedores WHERE nombre=?", ("Prov A",)
                ).fetchone()[0]
                self.assertEqual(again_a, id_a)
            finally:
                conn.close()

    def test_3_bootstrap_dos_veces_idempotente(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                conn.execute(
                    "INSERT INTO proveedores (nombre, activo) VALUES (?, 1)",
                    ("IdemProv",),
                )
                conn.commit()
                n_before = conn.execute("SELECT COUNT(*) FROM proveedores").fetchone()[0]
                tables_before = _tables(conn)
            finally:
                conn.close()

            import database
            import local_first_db

            database.DatabaseManager._schema_initialized = False
            env.db.crear_estructura_completa()
            local_first_db.ensure_local_first_schema(str(env.db_path))
            database.DatabaseManager._schema_initialized = True

            conn = env.connect()
            try:
                n_after = conn.execute("SELECT COUNT(*) FROM proveedores").fetchone()[0]
                self.assertEqual(n_after, n_before)
                nombre = conn.execute(
                    "SELECT nombre FROM proveedores WHERE nombre=?", ("IdemProv",)
                ).fetchone()
                self.assertIsNotNone(nombre)
                self.assertEqual(_tables(conn), tables_before)
            finally:
                conn.close()

    def test_4_crear_producto_repositorio_id_valido(self):
        with official_temp_db() as env:
            from models import Producto
            from repositories.productos_repo import ProductosRepository

            repo = ProductosRepository(env.db)
            ok, msg, producto_id = repo.crear_producto(
                Producto(nombre="Tornillo 1A", precio_venta=1500, precio_compra=500, stock=0)
            )
            self.assertTrue(ok, msg)
            self.assertIsNotNone(producto_id)
            self.assertGreater(producto_id, 0)

    def test_5_crear_compra_camino_real_sin_columnas_faltantes(self):
        with official_temp_db() as env:
            from models import Producto, Proveedor
            from repositories.compras_repo import ComprasRepository
            from repositories.productos_repo import ProductosRepository
            from repositories.proveedores_repo import ProveedoresRepository

            prov_ok, prov_msg, proveedor_id = ProveedoresRepository(env.db).crear_proveedor(
                Proveedor(nombre="Prov 1A")
            )
            self.assertTrue(prov_ok, prov_msg)
            self.assertIsNotNone(proveedor_id)

            prod_ok, prod_msg, producto_id = ProductosRepository(env.db).crear_producto(
                Producto(
                    nombre="Cemento 1A",
                    precio_venta=2000,
                    precio_compra=1000,
                    stock=0,
                    proveedor_id=proveedor_id,
                )
            )
            self.assertTrue(prod_ok, prod_msg)
            self.assertIsNotNone(producto_id)

            ok, msg, compra_id = ComprasRepository(env.db).crear_compra(
                proveedor_id=proveedor_id,
                productos=[{
                    "producto_id": producto_id,
                    "cantidad": 3,
                    "precio_unitario": 1000,
                }],
                numero_factura="FAC-1A",
            )
            self.assertTrue(ok, msg)
            self.assertIsNotNone(compra_id)
            self.assertNotIn("estado_pago", msg)

    def test_6_migracion_desde_version_previa_conserva_datos(self):
        tmp = tempfile.TemporaryDirectory(prefix="ferrepro-fase1a-prev-")
        db_path = Path(tmp.name) / "prev.db"
        try:
            _seed_prev_version(db_path)
            snapshot = _patch_local_paths(db_path)
            try:
                import database
                import local_first_db

                database.DatabaseManager._schema_initialized = False
                db = database.DatabaseManager(str(db_path))
                local_first_db.ensure_local_first_schema(str(db_path))
            finally:
                _restore_local_paths(snapshot)

            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            try:
                prod = conn.execute(
                    "SELECT id, nombre, stock FROM productos WHERE id=1"
                ).fetchone()
                self.assertEqual(prod["nombre"], "PrevProd")
                self.assertEqual(prod["stock"], 5)
                compra = conn.execute(
                    "SELECT id, numero_factura, total FROM compras WHERE id=1"
                ).fetchone()
                self.assertEqual(compra["numero_factura"], "FAC-PREV")
                self.assertEqual(compra["total"], 50)
                cols = _columns(conn, "compras")
                for col in COMPRAS_PAGO_COLS:
                    self.assertIn(col, cols)
                for col in PRODUCTO_EXTRA_COLS:
                    self.assertIn(col, _columns(conn, "productos"))
            finally:
                conn.close()
        finally:
            tmp.cleanup()

    def test_7_error_critico_visible_y_rollback(self):
        tmp = tempfile.TemporaryDirectory(prefix="ferrepro-fase1a-fail-")
        db_path = Path(tmp.name) / "fail.db"
        try:
            _seed_prev_version(db_path)
            snapshot = _patch_local_paths(db_path)
            original = None
            try:
                import database
                import schema_bootstrap

                original = schema_bootstrap.add_column_if_missing

                def _boom(conn, table, column, definition):
                    if column == "monto_pagado":
                        raise RuntimeError("fallo critico inyectado")
                    return original(conn, table, column, definition)

                database.DatabaseManager._schema_initialized = False
                with patch.object(schema_bootstrap, "add_column_if_missing", side_effect=_boom):
                    with self.assertRaises((RuntimeError, schema_bootstrap.SchemaBootstrapError)):
                        database.DatabaseManager(str(db_path))
                self.assertFalse(database.DatabaseManager._schema_initialized)
            finally:
                _restore_local_paths(snapshot)

            conn = sqlite3.connect(str(db_path))
            try:
                cols = _columns(conn, "compras")
                self.assertNotIn("estado_pago", cols)
                row = conn.execute(
                    "SELECT numero_factura FROM compras WHERE id=1"
                ).fetchone()
                self.assertEqual(row[0], "FAC-PREV")
                version = conn.execute(
                    "SELECT name FROM sqlite_master WHERE name='sync_state'"
                ).fetchone()
                if version:
                    sv = conn.execute(
                        "SELECT valor FROM sync_state WHERE clave='schema_version'"
                    ).fetchone()
                    self.assertIsNone(sv)
            finally:
                conn.close()
        finally:
            tmp.cleanup()

    def test_8_sql_remoto_no_se_ejecuta_como_sqlite(self):
        db_src = (REPO_ROOT / "database.py").read_text(encoding="utf-8")
        lf_src = (REPO_ROOT / "local_first_db.py").read_text(encoding="utf-8")
        sb_src = (REPO_ROOT / "schema_bootstrap.py").read_text(encoding="utf-8")
        ls_src = (REPO_ROOT / "local_sync.py").read_text(encoding="utf-8")
        self.assertNotIn("supabase_local_first_migration.sql", db_src)
        self.assertNotIn("supabase_local_first_migration.sql", lf_src)
        self.assertIn("supabase_local_first_migration.sql", ls_src)
        self.assertIn("def _ensure_remote_schema", ls_src)
        self.assertIn("POSTGRES_ONLY_STATEMENTS", sb_src)

        import schema_bootstrap

        with official_temp_db() as env:
            conn = env.connect()
            try:
                with self.assertRaises(schema_bootstrap.SchemaBootstrapError):
                    schema_bootstrap.apply_postgres_only_statements(conn)
                sql_blob = " ".join(
                    row[0] or ""
                    for row in conn.execute("SELECT sql FROM sqlite_master")
                ).lower()
                self.assertNotIn("gin_trgm_ops", sql_blob)
                self.assertNotIn("pg_trgm", sql_blob)
                self.assertNotIn("create extension", sql_blob)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
