# -*- coding: utf-8 -*-
"""W15 MezclasService.descontar_stock_mezcla — DEPRECATED + gateway."""
from __future__ import annotations

import ast
import sys
import unittest
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from repositories.productos_repo import ProductosRepository
from services.mezclas_service import MezclasService, W15_DEAD_REASON, W15_DEPRECATED
from tests.fase0.harness import official_temp_db
from tests.fase0.test_stock_writers import _iter_production_py
from tests.fase1e.helpers import AuthPermitido, insert_usuario, seed_producto, stock_of, count_mov
from tests.fase1e1.helpers import command_count, transport_applied, transport_rejected


class W15DeadAndLegacyTest(unittest.TestCase):
    def test_deprecated_flag_y_sin_callers_productivos(self):
        self.assertTrue(W15_DEPRECATED)
        self.assertIn("W03", W15_DEAD_REASON)
        callers = []
        for path, rel in _iter_production_py():
            if rel == "services/mezclas_service.py":
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if "descontar_stock_mezcla" in text:
                callers.append(rel)
        self.assertEqual(callers, [], msg=f"W15 volvió a usarse: {callers}")

    def test_legacy_sigue_descontando(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = MezclasService(env.db, ProductosRepository(env.db), AuthPermitido())
            ok, msg = svc.descontar_stock_mezcla(
                [{"producto_id": 1, "cantidad": 2}], num_factura="MZ-1E1"
            )
            self.assertTrue(ok, msg)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 8)
                self.assertEqual(count_mov(conn, "SALIDA_VENTA"), 1)
                self.assertEqual(command_count(conn), 0)
            finally:
                conn.close()


class W15AuthoritativeTest(unittest.TestCase):
    def test_tipo_venta_consumo_sin_dual_write(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = MezclasService(env.db, ProductosRepository(env.db), AuthPermitido())
            cid = str(uuid.uuid4())
            transport = transport_applied()
            ok, msg = svc.descontar_stock_mezcla(
                [{"producto_id": 1, "cantidad": 2}],
                num_factura="MZ-AUTH",
                inventory_mode="authoritative",
                inventory_command_id=cid,
                inventory_transport=transport,
            )
            self.assertTrue(ok, msg)
            self.assertEqual(transport.calls[0]["tipo"], "VENTA")
            self.assertEqual(
                transport.calls[0]["operations"][0]["producto_local_id"], lid
            )
            self.assertEqual(
                transport.calls[0]["operations"][0]["delta_scaled"], -2000
            )
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 10)
            finally:
                conn.close()

    def test_rejected_no_descuenta(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10)
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = MezclasService(env.db, ProductosRepository(env.db), AuthPermitido())
            ok, msg = svc.descontar_stock_mezcla(
                [{"producto_id": 1, "cantidad": 2}],
                inventory_mode="authoritative",
                inventory_transport=transport_rejected(),
            )
            self.assertFalse(ok)
            conn = env.connect()
            try:
                self.assertEqual(stock_of(conn), 10)
            finally:
                conn.close()

    def test_authoritative_no_update_stock(self):
        src = (REPO_ROOT / "services" / "mezclas_service.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "_descontar_stock_mezcla_authoritative"
            ):
                body = ast.get_source_segment(src, node) or ""
                self.assertNotIn("stock = stock -", body)
                return
        self.fail("no está _descontar_stock_mezcla_authoritative")
