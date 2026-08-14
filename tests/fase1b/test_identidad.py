# -*- coding: utf-8 -*-
"""FASE 1B: identidad UUID global de producto y resolución padre/hijo."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase0.harness import (
    REPO_FERRETERIA_DB,
    _patch_local_paths,
    _restore_local_paths,
    official_temp_db,
)


def _seed_old_db_without_local_id(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE proveedores (
                id INTEGER PRIMARY KEY,
                nombre TEXT NOT NULL,
                activo INTEGER DEFAULT 1
            );
            CREATE TABLE productos (
                id INTEGER PRIMARY KEY,
                codigo_barras TEXT UNIQUE,
                nombre TEXT NOT NULL,
                precio_venta REAL NOT NULL,
                stock INTEGER DEFAULT 0,
                activo INTEGER DEFAULT 1,
                proveedor_id INTEGER,
                FOREIGN KEY (proveedor_id) REFERENCES proveedores(id)
            );
            INSERT INTO proveedores (id, nombre, activo)
                VALUES (1, 'ViejoProv', 1);
            INSERT INTO productos
                (id, codigo_barras, nombre, precio_venta, stock, activo, proveedor_id)
                VALUES (1, 'OLD-001', 'ProductoHistorico', 1000, 7, 1, 1);
            INSERT INTO productos
                (id, codigo_barras, nombre, precio_venta, stock, activo, proveedor_id)
                VALUES (2, 'OLD-002', 'OtroHistorico', 2000, 3, 1, 1);
            """
        )
        conn.commit()
    finally:
        conn.close()


class IdentidadProductoTest(unittest.TestCase):
    def test_producto_nuevo_obtiene_uuid_global_estable(self):
        with official_temp_db() as env:
            from models import Producto
            from repositories.productos_repo import ProductosRepository

            repo = ProductosRepository(env.db)
            ok, msg, producto_id = repo.crear_producto(
                Producto(nombre="Tornillo 1B", precio_venta=1500, stock=0)
            )
            self.assertTrue(ok, msg)
            conn = env.connect()
            try:
                row = conn.execute(
                    "SELECT id, local_id, stock FROM productos WHERE id=?",
                    (producto_id,),
                ).fetchone()
                self.assertIsNotNone(row["local_id"])
                uuid.UUID(row["local_id"])
                self.assertNotEqual(str(row["id"]), row["local_id"])
                first = row["local_id"]
            finally:
                conn.close()

            import local_first_db

            conn = env.connect()
            try:
                local_first_db.ensure_local_id_unique(conn)
                again = conn.execute(
                    "SELECT local_id FROM productos WHERE id=?",
                    (producto_id,),
                ).fetchone()[0]
                self.assertEqual(again, first)
            finally:
                conn.close()

    def test_reabrir_migrar_no_cambia_uuid(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                env.insert_proveedor(conn)
                stable = str(uuid.uuid4())
                env.insert_producto(conn, local_id=stable, stock=4)
                conn.commit()
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
                got = conn.execute(
                    "SELECT local_id, nombre, stock FROM productos WHERE id=1"
                ).fetchone()
                self.assertEqual(got["local_id"], stable)
                self.assertEqual(got["nombre"], "Tornillo Fase0")
                self.assertEqual(got["stock"], 4)
            finally:
                conn.close()

    def test_dos_productos_no_comparten_identidad(self):
        with official_temp_db() as env:
            from models import Producto
            from repositories.productos_repo import ProductosRepository

            repo = ProductosRepository(env.db)
            ok_a, msg_a, id_a = repo.crear_producto(
                Producto(nombre="Prod A 1B", precio_venta=1, stock=0)
            )
            ok_b, msg_b, id_b = repo.crear_producto(
                Producto(nombre="Prod B 1B", precio_venta=1, stock=0)
            )
            self.assertTrue(ok_a, msg_a)
            self.assertTrue(ok_b, msg_b)
            conn = env.connect()
            try:
                rows = conn.execute(
                    "SELECT id, local_id FROM productos WHERE id IN (?, ?)",
                    (id_a, id_b),
                ).fetchall()
                lids = [r["local_id"] for r in rows]
                self.assertEqual(len(lids), 2)
                self.assertNotEqual(lids[0], lids[1])
                uuid.UUID(lids[0])
                uuid.UUID(lids[1])
            finally:
                conn.close()

    def test_fk_hija_se_resuelve_por_local_id_del_padre(self):
        from sync_registry import parents_of

        self.assertIn(("proveedor_id", "proveedores"), parents_of("productos"))
        self.assertIn(("producto_id", "productos"), parents_of("detalle_ventas"))
        with official_temp_db() as env:
            conn = env.connect()
            try:
                env.insert_proveedor(conn)
                env.insert_producto(conn, local_id=str(uuid.uuid4()))
                conn.commit()
                from local_first_db import ensure_local_id

                prov_lid = ensure_local_id(conn, "proveedores", 1)
                prod = conn.execute(
                    "SELECT proveedor_id, local_id FROM productos WHERE id=1"
                ).fetchone()
                padre = conn.execute(
                    "SELECT local_id FROM proveedores WHERE id=?",
                    (prod["proveedor_id"],),
                ).fetchone()
                self.assertEqual(padre["local_id"], prov_lid)
                uuid.UUID(prod["local_id"])
                uuid.UUID(prov_lid)
                self.assertNotEqual(prod["local_id"], prov_lid)
                info = {
                    r[1]: r[2]
                    for r in conn.execute("PRAGMA table_info(detalle_ventas)")
                }
                self.assertIn("producto_id", info)
                self.assertEqual(info["producto_id"].upper(), "INTEGER")
            finally:
                conn.close()

    def test_bootstrap_repetido_conserva_identidades(self):
        with official_temp_db() as env:
            from models import Producto
            from repositories.productos_repo import ProductosRepository

            ok, msg, producto_id = ProductosRepository(env.db).crear_producto(
                Producto(nombre="Idem 1B", precio_venta=1, stock=0)
            )
            self.assertTrue(ok, msg)
            conn = env.connect()
            try:
                before = conn.execute(
                    "SELECT local_id FROM productos WHERE id=?",
                    (producto_id,),
                ).fetchone()[0]
            finally:
                conn.close()

            import database
            import local_first_db

            database.DatabaseManager._schema_initialized = False
            env.db.crear_estructura_completa()
            local_first_db.ensure_local_first_schema(str(env.db_path))
            local_first_db.ensure_local_first_schema(str(env.db_path))
            database.DatabaseManager._schema_initialized = True

            conn = env.connect()
            try:
                after = conn.execute(
                    "SELECT local_id FROM productos WHERE id=?",
                    (producto_id,),
                ).fetchone()[0]
                self.assertEqual(after, before)
            finally:
                conn.close()

    def test_bd_vieja_recibe_local_id_sin_perder_datos(self):
        tmp = tempfile.TemporaryDirectory(prefix="ferrepro-fase1b-old-")
        db_path = Path(tmp.name) / "old.db"
        snapshot = _patch_local_paths(db_path)
        try:
            self.assertNotEqual(db_path.resolve(), REPO_FERRETERIA_DB.resolve())
            _seed_old_db_without_local_id(db_path)
            import database
            import local_first_db

            database.DatabaseManager._schema_initialized = False
            db = database.DatabaseManager(str(db_path))
            db.crear_estructura_completa()
            local_first_db.ensure_local_first_schema(str(db_path))
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    "SELECT id, nombre, stock, codigo_barras, local_id "
                    "FROM productos ORDER BY id"
                ).fetchall()
                self.assertEqual(len(rows), 2)
                self.assertEqual(rows[0]["nombre"], "ProductoHistorico")
                self.assertEqual(rows[0]["stock"], 7)
                self.assertEqual(rows[0]["codigo_barras"], "OLD-001")
                self.assertEqual(rows[1]["nombre"], "OtroHistorico")
                uuid.UUID(rows[0]["local_id"])
                uuid.UUID(rows[1]["local_id"])
                self.assertNotEqual(rows[0]["local_id"], rows[1]["local_id"])
            finally:
                conn.close()
        finally:
            _restore_local_paths(snapshot)
            tmp.cleanup()

    def test_ensure_local_id_configuracion_por_clave(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                conn.execute(
                    "INSERT INTO configuracion (clave, valor) VALUES (?, ?)",
                    ("tema", "oscuro"),
                )
                conn.execute(
                    "UPDATE configuracion SET local_id = NULL WHERE clave=?",
                    ("tema",),
                )
                from local_first_db import ensure_local_id

                lid = ensure_local_id(conn, "configuracion", "tema")
                uuid.UUID(lid)
                row = conn.execute(
                    "SELECT local_id FROM configuracion WHERE clave=?",
                    ("tema",),
                ).fetchone()
                self.assertEqual(row["local_id"], lid)
                again = ensure_local_id(conn, "configuracion", "tema")
                self.assertEqual(again, lid)
            finally:
                conn.close()

    def test_enqueue_sigue_incluyendo_stock(self):
        """Centinela INV-02: 1B no quitó stock del payload autoritativo."""
        with official_temp_db() as env:
            conn = env.db.conectar()
            try:
                env.insert_proveedor(conn)
                env.insert_producto(conn, stock=7, local_id=str(uuid.uuid4()))
                from local_first_db import enqueue_entity

                payload = enqueue_entity(conn, "product", 1, "update", "productos")
                conn.commit()
                self.assertIsNotNone(payload)
                self.assertIn("stock", payload)
                self.assertEqual(payload["stock"], 7)
            finally:
                conn.close()
