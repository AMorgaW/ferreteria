# -*- coding: utf-8 -*-
"""Contrato Fase 0: estos tests DEBEN fallar contra el código actual.

Un XPASS significa que el contrato se cumplió (o que el test se trivializó).
No implementar producción para ponerlos verdes en esta fase.
"""
import inspect
import sqlite3
import unittest
import uuid
from unittest.mock import patch

try:
    from harness import REPO_ROOT, official_temp_db
except ImportError:
    from tests.fase0.harness import REPO_ROOT, official_temp_db
from repositories._outbox import encolar


class ContratoExpectedFailureTest(unittest.TestCase):
    @unittest.expectedFailure
    def test_contrato_unicidad_global_ultimo_stock(self):
        """INV-01: de dos intentos sobre las últimas 50 unidades, solo uno aplica."""
        with official_temp_db() as env:
            conn = env.connect()
            try:
                env.insert_proveedor(conn)
                env.insert_producto(conn, stock=50)
                conn.commit()
            finally:
                conn.close()
            replica = env.db_path.with_name("pc-b.db")
            replica.write_bytes(env.db_path.read_bytes())
            sql = "UPDATE productos SET stock = stock - ? WHERE id = ? AND stock >= ?"
            conn_a = sqlite3.connect(str(env.db_path))
            conn_b = sqlite3.connect(str(replica))
            try:
                applied = (
                    conn_a.execute(sql, (50, 1, 50)).rowcount
                    + conn_b.execute(sql, (50, 1, 50)).rowcount
                )
                conn_a.commit()
                conn_b.commit()
            finally:
                conn_a.close()
                conn_b.close()
            self.assertEqual(applied, 1)

    @unittest.expectedFailure
    def test_contrato_payload_productos_sin_stock_autoritativo(self):
        """INV-02: el outbox de productos no publica stock como LWW."""
        with official_temp_db() as env:
            conn = env.db.conectar()
            try:
                env.insert_proveedor(conn)
                env.insert_producto(conn, stock=7, local_id=str(uuid.uuid4()))
                from local_first_db import enqueue_entity
                payload = enqueue_entity(conn, "product", 1, "update", "productos")
                conn.commit()
            finally:
                conn.close()
            self.assertIsNotNone(payload)
            self.assertNotIn("stock", payload)

    @unittest.expectedFailure
    def test_contrato_entrada_compra_unica(self):
        """INV-03: la UI productiva ya no ofrece ENTRADA_COMPRA de alta."""
        entrada = (REPO_ROOT / "ui" / "entrada_inventario_ui.py").read_text(
            encoding="utf-8"
        )
        movimientos = (REPO_ROOT / "ui" / "movimientos_ui.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("ENTRADA_COMPRA", entrada)
        self.assertNotIn("tipos = ['ENTRADA_COMPRA'", movimientos)

    @unittest.expectedFailure
    def test_contrato_coordinador_inventario_existe(self):
        """INV-01: existe apply_inventory_operation en producción."""
        hits = []
        for path in REPO_ROOT.rglob("*.py"):
            rel = path.relative_to(REPO_ROOT)
            if any(part in {".git", "tests", "docs", ".cursor"} for part in rel.parts):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if "def apply_inventory_operation" in text:
                hits.append(rel.as_posix())
        self.assertTrue(hits)

    def test_contrato_retry_recupera_resultado(self):
        """INV-07 (Fase 1C): el ledger expone operation_id y resultado recuperable.

        No afirma que el delta se haya aplicado a productos.stock.
        """
        hits = []
        for path in REPO_ROOT.rglob("*.py"):
            rel = path.relative_to(REPO_ROOT)
            if any(part in {".git", "tests", "docs", ".cursor"} for part in rel.parts):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if "operation_id" in text and "resultado" in text:
                hits.append(rel.as_posix())
        self.assertTrue(hits)

    @unittest.expectedFailure
    def test_contrato_tablas_recepcion_existen(self):
        """INV-04."""
        with official_temp_db() as env:
            conn = env.connect()
            try:
                tables = {
                    r[0] for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
            finally:
                conn.close()
            self.assertIn("recepcion_documentos", tables)
            self.assertIn("recepcion_lineas", tables)

    @unittest.expectedFailure
    def test_contrato_cantidad_aceptada(self):
        """INV-05."""
        with official_temp_db() as env:
            conn = env.connect()
            try:
                cols = {
                    r["name"] for r in conn.execute("PRAGMA table_info(recepcion_lineas)")
                }
            finally:
                conn.close()
            self.assertIn("cantidad_aceptada", cols)

    def test_contrato_ledger_operation_id(self):
        """INV-06 (Fase 1C): existe inventory_operations.operation_id."""
        with official_temp_db() as env:
            conn = env.connect()
            try:
                tables = {
                    r[0] for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                self.assertTrue(
                    "inventory_operations" in tables
                    or "inventario_operaciones" in tables
                )
                name = (
                    "inventory_operations"
                    if "inventory_operations" in tables
                    else "inventario_operaciones"
                )
                cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({name})")}
            finally:
                conn.close()
            self.assertIn("operation_id", cols)

    @unittest.expectedFailure
    def test_contrato_frp_y_producto_codigos(self):
        """INV-08 / INV-10."""
        with official_temp_db() as env:
            conn = env.connect()
            try:
                tables = {
                    r[0] for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
            finally:
                conn.close()
            self.assertIn("producto_codigos", tables)
        productos_src = (REPO_ROOT / "repositories" / "productos_repo.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("token_hex(8)", productos_src)

    def test_contrato_device_identity(self):
        """INV-11 (Fase 1B): UUID persistente. Sin fencing ni autoridad offline."""
        import socket

        from local_first_config import get_or_create_device_id

        config_src = (REPO_ROOT / "local_first_config.py").read_text(encoding="utf-8")
        self.assertIn("device_identity", config_src)
        self.assertIn("device_id", config_src)
        self.assertIn("def get_or_create_device_id", config_src)
        self.assertNotIn("OFFLINE_INVENTORY_AUTHORITY", config_src)
        with official_temp_db() as env:
            first = get_or_create_device_id()
            second = get_or_create_device_id()
            self.assertEqual(first, second)
            uuid.UUID(first)
            self.assertNotEqual(first, socket.gethostname())
            ident = env.db_path.parent / "config" / "device_identity.json"
            self.assertTrue(ident.exists())

    @unittest.expectedFailure
    def test_contrato_offline_authority(self):
        """INV-12."""
        hits = []
        for path in REPO_ROOT.rglob("*.py"):
            rel = path.relative_to(REPO_ROOT)
            if any(part in {".git", "tests", "docs", ".cursor"} for part in rel.parts):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if "OFFLINE_INVENTORY_AUTHORITY" in text:
                hits.append(rel.as_posix())
        self.assertTrue(hits)

    @unittest.expectedFailure
    def test_contrato_outbox_propaga(self):
        """INV-13."""
        with official_temp_db() as env:
            conn = env.db.conectar()
            try:
                with patch(
                    "local_first_db.enqueue_entity",
                    side_effect=RuntimeError("cola rota"),
                ):
                    with self.assertRaises(RuntimeError):
                        encolar(conn, "product", 1, "update", "productos")
            finally:
                conn.close()

    def test_contrato_integer_primary_key(self):
        """INV-15 (Fase 1A): INTEGER PRIMARY KEY asigna id en SQLite fresco."""
        with official_temp_db() as env:
            conn = env.connect()
            try:
                conn.execute(
                    "INSERT INTO productos (nombre, precio_venta, stock) VALUES (?, ?, ?)",
                    ("ConId", 1, 0),
                )
                row = conn.execute(
                    "SELECT id FROM productos WHERE nombre=?", ("ConId",)
                ).fetchone()
            finally:
                conn.close()
            self.assertIsNotNone(row["id"])

    @unittest.expectedFailure
    def test_contrato_factura_unica_por_proveedor(self):
        """INV-16."""
        with official_temp_db() as env:
            conn = env.connect()
            try:
                env.insert_proveedor(conn)
                conn.execute(
                    """
                    INSERT INTO compras (id, proveedor_id, numero_factura, total, estado)
                    VALUES (1, 1, 'FAC-DUP', 1, 'COMPLETADA')
                    """
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        """
                        INSERT INTO compras (id, proveedor_id, numero_factura, total, estado)
                        VALUES (2, 1, 'FAC-DUP', 1, 'COMPLETADA')
                        """
                    )
            finally:
                conn.close()

    @unittest.expectedFailure
    def test_contrato_fixed_point(self):
        """INV-17."""
        with official_temp_db() as env:
            conn = env.connect()
            try:
                tipo = {
                    r["name"]: r["type"]
                    for r in conn.execute("PRAGMA table_info(productos)")
                }["stock"]
            finally:
                conn.close()
            self.assertNotEqual(tipo.upper(), "INTEGER")
            self.assertIn(tipo.upper(), {"NUMERIC", "REAL", "DECIMAL"})

    @unittest.expectedFailure
    def test_contrato_upsert_no_pisa_stock_en_fuente(self):
        """INV-02b: _upsert no hace LWW de todas las columnas (incluye stock)."""
        from local_sync import SupabaseSyncService, build_remote_upsert_sql

        src = (
            inspect.getsource(SupabaseSyncService._upsert)
            + inspect.getsource(build_remote_upsert_sql)
        )
        self.assertNotIn("EXCLUDED.{c}", src)

    @unittest.expectedFailure
    def test_contrato_pull_no_pisa_stock_en_fuente(self):
        """INV-02c: pull_from_remote no hace LWW de stock."""
        from local_sync import SupabaseSyncService

        src = inspect.getsource(SupabaseSyncService.pull_from_remote)
        self.assertNotIn("{c}=excluded.{c}", src)
