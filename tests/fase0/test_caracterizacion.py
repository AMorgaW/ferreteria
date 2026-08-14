# -*- coding: utf-8 -*-
"""Tests que PASAN hoy porque demuestran la violación del contrato."""
import json
import sqlite3
import unittest
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

try:
    from harness import REPO_ROOT, official_temp_db
except ImportError:
    from tests.fase0.harness import REPO_ROOT, official_temp_db
from models import MovimientoInventario
from repositories._outbox import encolar
from repositories.compras_repo import ComprasRepository
from repositories.inventario_repository import InventarioRepository
from services.movimientos_service import MovimientosService


class _AuthPermitido:
    usuario_actual = type("U", (), {"id": None})()

    def tiene_permiso(self, _nombre):
        return True

    def registrar_auditoria(self, *args, **kwargs):
        return None


class CaracterizacionTest(unittest.TestCase):
    def test_integer_pk_asigna_id(self):
        """INV-15 resuelto en Fase 1A: INTEGER PRIMARY KEY asigna id usable."""
        with official_temp_db() as env:
            conn = env.connect()
            try:
                conn.execute(
                    "INSERT INTO productos (nombre, precio_venta, stock) VALUES (?, ?, ?)",
                    ("SinId", 1, 0),
                )
                row = conn.execute(
                    "SELECT id, nombre FROM productos WHERE nombre = ?",
                    ("SinId",),
                ).fetchone()
                self.assertIsNotNone(row["id"])
                info = conn.execute("PRAGMA table_info(productos)").fetchall()
                id_type = {r["name"]: r["type"] for r in info}["id"]
                self.assertEqual(id_type.upper(), "INTEGER")
            finally:
                conn.close()

    def test_carrera_dos_sqlite_venden_el_ultimo_stock(self):
        """CAR INV-01: dos archivos SQLite aprueban ambos la última unidad."""
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
                cur_a = conn_a.execute(sql, (50, 1, 50))
                cur_b = conn_b.execute(sql, (50, 1, 50))
                conn_a.commit()
                conn_b.commit()
                self.assertEqual(cur_a.rowcount, 1)
                self.assertEqual(cur_b.rowcount, 1)
                stock_a = conn_a.execute("SELECT stock FROM productos WHERE id=1").fetchone()[0]
                stock_b = conn_b.execute("SELECT stock FROM productos WHERE id=1").fetchone()[0]
                self.assertEqual(stock_a, 0)
                self.assertEqual(stock_b, 0)
                self.assertEqual(stock_a + stock_b, 0)
                self.assertEqual(50 + 50, 100)
            finally:
                conn_a.close()
                conn_b.close()

    def test_snapshot_lww_pisa_stock(self):
        """CAR INV-02: el UPSERT de pull (todas las columnas) pisa stock obsoleto."""
        lid = str(uuid.uuid4())
        with official_temp_db() as env:
            conn = env.connect()
            try:
                env.insert_proveedor(conn)
                env.insert_producto(conn, stock=0, local_id=lid)
                conn.commit()
                local_row = dict(conn.execute(
                    "SELECT * FROM productos WHERE local_id = ?", (lid,)
                ).fetchone())
                incoming = dict(local_row)
                incoming["stock"] = 50
                incoming["codigo_barras"] = "TEST-F0-STALE"
                cols = [c for c in incoming.keys() if incoming[c] is not None]
                ph = ",".join(["?"] * len(cols))
                collist = ",".join(cols)
                upd = ",".join(
                    f"{c}=excluded.{c}" for c in cols if c != "local_id"
                )
                sql = (
                    f"INSERT INTO productos ({collist}) VALUES ({ph}) "
                    f"ON CONFLICT(local_id) DO UPDATE SET {upd}"
                )
                conn.execute(sql, [incoming[c] for c in cols])
                conn.commit()
                stock = conn.execute(
                    "SELECT stock FROM productos WHERE local_id = ?", (lid,)
                ).fetchone()[0]
                self.assertEqual(stock, 50)
            finally:
                conn.close()

    def test_enqueue_entity_incluye_stock_en_payload(self):
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
                raw = conn.execute(
                    "SELECT payload FROM sync_queue WHERE table_name='productos'"
                ).fetchone()["payload"]
                self.assertIn('"stock"', raw)
            finally:
                conn.close()

    def test_crear_compra_en_esquema_oficial(self):
        """INV-20 resuelto en Fase 1A: el esquema oficial incluye estado_pago."""
        with official_temp_db() as env:
            conn = env.connect()
            try:
                cols = {
                    r["name"] for r in conn.execute("PRAGMA table_info(compras)")
                }
                env.insert_proveedor(conn)
                env.insert_producto(conn, stock=0)
                conn.commit()
            finally:
                conn.close()
            self.assertIn("estado_pago", cols)
            compras = ComprasRepository(env.db)
            ok, msg, cid = compras.crear_compra(
                proveedor_id=1,
                productos=[{"producto_id": 1, "cantidad": 10, "precio_unitario": 100}],
                numero_factura="FAC-A",
            )
            self.assertTrue(ok, msg)
            self.assertIsNotNone(cid)

    def test_tres_caminos_entrada_compra(self):
        """CAR INV-03: el SQL de compra + inventario + movimientos incrementan el mismo SKU."""
        with official_temp_db() as env:
            conn = env.connect()
            try:
                env.insert_proveedor(conn)
                env.insert_producto(conn, stock=0)
                conn.execute(
                    "UPDATE productos SET stock = stock + ? WHERE id = ?",
                    (10, 1),
                )
                conn.commit()
            finally:
                conn.close()

            inventario = InventarioRepository(env.db)
            mov = MovimientoInventario(
                tipo_movimiento="ENTRADA_COMPRA",
                producto_id=1,
                cantidad=10,
                precio_unitario=100,
                usuario_id=None,
                fecha=datetime.now(),
                proveedor_id=1,
                numero_factura="FAC-A",
                observaciones="camino inventario",
            )
            ok_i, msg_i = inventario.registrar_movimiento(mov)
            self.assertTrue(ok_i, msg_i)

            class _ProdRepo:
                def obtener_por_id(self, _pid):
                    c = env.db.conectar()
                    try:
                        row = c.execute("SELECT * FROM productos WHERE id=1").fetchone()
                        return dict(row)
                    finally:
                        c.close()

            svc = MovimientosService(env.db, _ProdRepo(), None, _AuthPermitido())
            ok_m, msg_m = svc.registrar_movimiento(
                tipo="ENTRADA_COMPRA",
                producto_id=1,
                cantidad=10,
                precio_unitario=100,
                proveedor_id=1,
                num_factura="FAC-A",
                observaciones="camino movimientos",
            )
            self.assertTrue(ok_m, msg_m)

            conn = env.connect()
            try:
                stock = conn.execute("SELECT stock FROM productos WHERE id=1").fetchone()[0]
                n_mov = conn.execute(
                    "SELECT COUNT(*) FROM movimientos WHERE tipo='ENTRADA_COMPRA'"
                ).fetchone()[0]
                n_inv = conn.execute(
                    "SELECT COUNT(*) FROM movimientos_inventario "
                    "WHERE tipo_movimiento='ENTRADA_COMPRA'"
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(stock, 30)
            self.assertGreaterEqual(n_mov, 1)
            self.assertGreaterEqual(n_inv, 1)

    def test_un_solo_codigo_barras(self):
        """CAR INV-09: una columna UNIQUE, sin tabla de múltiples códigos."""
        with official_temp_db() as env:
            conn = env.connect()
            try:
                tables = {
                    r[0] for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                self.assertNotIn("producto_codigos", tables)
                info = conn.execute("PRAGMA table_info(productos)").fetchall()
                cols = {r["name"] for r in info}
                self.assertIn("codigo_barras", cols)
                indexes = list(conn.execute("PRAGMA index_list(productos)"))
                unique_cols = []
                for idx in indexes:
                    if not idx["unique"]:
                        continue
                    for col in conn.execute(f"PRAGMA index_info({idx['name']})"):
                        unique_cols.append(col["name"])
                self.assertIn("codigo_barras", unique_cols)
            finally:
                conn.close()

    def test_outbox_traga_excepciones(self):
        """CAR INV-13."""
        with official_temp_db() as env:
            conn = env.db.conectar()
            try:
                with patch(
                    "local_first_db.enqueue_entity",
                    side_effect=RuntimeError("cola rota"),
                ):
                    encolar(conn, "product", 1, "update", "productos")
            finally:
                conn.close()

    def test_no_existe_ledger_ni_recepcion(self):
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
            for forbidden in (
                "inventory_operations", "inventario_operaciones",
                "recepcion_documentos", "recepcion_lineas", "producto_codigos",
            ):
                self.assertNotIn(forbidden, tables)

    def test_registries_divergen(self):
        """INV-18 (Fase 1B): una sola fuente; derivadas no divergen."""
        from local_first_db import SYNC_TABLES
        from local_sync import TOPO_ORDER, SupabaseSyncService
        from sync_registry import sync_tables, synced_tables, topo_order

        pull_order = SupabaseSyncService.PULL_ORDER
        synced = {t for t, _et in SupabaseSyncService.SYNCED_TABLES}
        sync_tables_set = set(SYNC_TABLES)
        self.assertEqual(list(SYNC_TABLES), list(sync_tables()))
        self.assertEqual(list(SupabaseSyncService.SYNCED_TABLES), synced_tables())
        self.assertEqual(sync_tables_set, synced)
        self.assertIn("configuracion", synced)
        self.assertIn("pagos_cuentas", synced)
        self.assertEqual(list(pull_order), list(TOPO_ORDER))
        self.assertEqual(list(TOPO_ORDER), list(topo_order()))
        source = (REPO_ROOT / "local_sync.py").read_text(encoding="utf-8")
        self.assertNotIn("self.PULL_ORDER", source)
        self.assertIn("TOPO_ORDER", source)
        self.assertIn("PULL_ORDER = TOPO_ORDER", source)

    def test_compras_numero_factura_no_es_unique(self):
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
                conn.execute(
                    """
                    INSERT INTO compras (id, proveedor_id, numero_factura, total, estado)
                    VALUES (2, 1, 'FAC-DUP', 1, 'COMPLETADA')
                    """
                )
                conn.commit()
                n = conn.execute(
                    "SELECT COUNT(*) FROM compras WHERE numero_factura='FAC-DUP'"
                ).fetchone()[0]
                self.assertEqual(n, 2)
            finally:
                conn.close()
