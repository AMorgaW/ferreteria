# -*- coding: utf-8 -*-
"""W02 ComprasRepository.eliminar_compra — 1E.1."""
from __future__ import annotations

import ast
import sys
import unittest
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from repositories.compras_repo import ComprasRepository
from tests.fase0.harness import official_temp_db
from tests.fase1e.helpers import seed_producto, stock_of, count_mov
from tests.fase1e1.helpers import command_count, transport_applied, transport_rejected


class W02LegacyTest(unittest.TestCase):
    def test_marca_cancelada_y_salida_ajuste(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=0)
            finally:
                conn.close()
            repo = ComprasRepository(env.db)
            ok, msg, cid = repo.crear_compra(
                proveedor_id=1,
                productos=[{"producto_id": 1, "cantidad": 4, "precio_unitario": 50}],
                numero_factura="FAC-W02-1E1",
            )
            self.assertTrue(ok, msg)
            ok2, msg2 = repo.eliminar_compra(cid)
            self.assertTrue(ok2, msg2)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 0)
                self.assertEqual(count_mov(conn, "SALIDA_AJUSTE"), 1)
                estado = conn.execute(
                    "SELECT estado FROM compras WHERE id = ?", (cid,)
                ).fetchone()["estado"]
                self.assertEqual(estado, "CANCELADA")
                self.assertEqual(command_count(conn), 0)
            finally:
                conn.close()


class W02AuthoritativeTest(unittest.TestCase):
    def test_ajuste_negativo_sin_dual_write(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = seed_producto(conn, env, stock=0)
            finally:
                conn.close()
            repo = ComprasRepository(env.db)
            ok, msg, compra_id = repo.crear_compra(
                proveedor_id=1,
                productos=[{"producto_id": 1, "cantidad": 4, "precio_unitario": 50}],
                numero_factura="FAC-W02-AUTH",
            )
            self.assertTrue(ok, msg)
            command_id = str(uuid.uuid4())
            transport = transport_applied()
            ok2, msg2 = repo.eliminar_compra(
                compra_id,
                inventory_mode="authoritative",
                inventory_command_id=command_id,
                inventory_transport=transport,
            )
            self.assertTrue(ok2, msg2)
            self.assertEqual(transport.calls[0]["tipo"], "AJUSTE")
            self.assertEqual(
                transport.calls[0]["operations"][0]["delta_scaled"], -4000
            )
            self.assertEqual(
                transport.calls[0]["operations"][0]["producto_local_id"], lid
            )
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 4)
                estado = conn.execute(
                    "SELECT estado FROM compras WHERE id = ?", (compra_id,)
                ).fetchone()["estado"]
                self.assertEqual(estado, "CANCELADA")
                self.assertEqual(count_mov(conn, "SALIDA_AJUSTE"), 1)
            finally:
                conn.close()

    def test_rejected_no_cancela(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=0)
            finally:
                conn.close()
            repo = ComprasRepository(env.db)
            ok, msg, compra_id = repo.crear_compra(
                proveedor_id=1,
                productos=[{"producto_id": 1, "cantidad": 4, "precio_unitario": 50}],
                numero_factura="FAC-W02-REJ",
            )
            self.assertTrue(ok, msg)
            ok2, msg2 = repo.eliminar_compra(
                compra_id,
                inventory_mode="authoritative",
                inventory_transport=transport_rejected(),
            )
            self.assertFalse(ok2)
            conn = env.connect()
            try:
                estado = conn.execute(
                    "SELECT estado FROM compras WHERE id = ?", (compra_id,)
                ).fetchone()["estado"]
                self.assertNotEqual(str(estado).upper(), "CANCELADA")
                self.assertEqual(stock_of(conn), 4)
            finally:
                conn.close()

    def test_authoritative_no_update_stock(self):
        src = (REPO_ROOT / "repositories" / "compras_repo.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "_eliminar_compra_authoritative"
            ):
                body = ast.get_source_segment(src, node) or ""
                self.assertNotIn("stock = stock -", body)
                return
        self.fail("no está _eliminar_compra_authoritative")
