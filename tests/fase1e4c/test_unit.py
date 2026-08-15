# -*- coding: utf-8 -*-
"""1E.4C unitario: scanner de fence en W01–W18 y ausencia de bypass UI."""
from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase0.harness import official_temp_db
from inventory_writer_contract import DEPRECATED_WRITER_IDS as CONTRACT_DEPRECATED
from tests.fase0.stock_writers import DEPRECATED_WRITER_IDS, STOCK_WRITERS
from tests.fase0.test_stock_writers import (
    INSERT_STOCK_RE,
    UPDATE_STOCK_RE,
    scan_stock_writes_by_function,
)
from tests.fase1e.helpers import seed_producto, stock_of
from tests.fase1e2.helpers import make_producto

DIRECT_IDS = tuple(
    w["id"] for w in STOCK_WRITERS if w["kind"] in ("direct", "insert")
)
SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "tests", "docs",
    ".cursor", ".agents", "dist", "build",
}
UPDATE_STOCK_FILE_RE = re.compile(
    r"UPDATE\s+productos\s+SET[\s\S]{0,800}?stock",
    re.IGNORECASE,
)
INSERT_STOCK_FILE_RE = re.compile(
    r"INSERT\s+INTO\s+productos\s*\([^;]{0,1200}?\bstock\b",
    re.IGNORECASE | re.DOTALL,
)
STOCK_DELTA_RE = re.compile(
    r"stock\s*=\s*stock\s*[+-]",
    re.IGNORECASE,
)
CONN_COMMIT_RE = re.compile(r"\bconn\.commit\s*\(")


def _function_own_body(source: str, class_name: str, method_name: str) -> str:
    tree = ast.parse(source)
    parent = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    lines = source.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != method_name:
            continue
        owner = parent.get(node)
        if not isinstance(owner, ast.ClassDef) or owner.name != class_name:
            continue
        end = getattr(node, "end_lineno", node.lineno)
        nested = []
        for child in ast.walk(node):
            if child is node:
                continue
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                nested.append((child.lineno, getattr(child, "end_lineno", child.lineno)))
        own = []
        for idx in range(node.lineno, end + 1):
            if any(start <= idx <= stop for start, stop in nested):
                continue
            own.append(lines[idx - 1])
        return "\n".join(own)
    raise AssertionError(f"no está {class_name}.{method_name}")


def _iter_production_py():
    for path in REPO_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        yield path, rel.as_posix()


class Fase1E4CScannerTest(unittest.TestCase):
    def test_w01_to_w18_inventariados(self):
        self.assertEqual(DIRECT_IDS, tuple(f"W{i:02d}" for i in range(1, 19)))

    def test_independent_stock_sql_search(self):
        update_files = set()
        insert_files = set()
        delta_files = set()
        for path, rel in _iter_production_py():
            text = path.read_text(encoding="utf-8", errors="replace")
            if UPDATE_STOCK_FILE_RE.search(text):
                update_files.add(rel)
            if INSERT_STOCK_FILE_RE.search(text):
                insert_files.add(rel)
            if STOCK_DELTA_RE.search(text) and "productos" in text.lower():
                delta_files.add(rel)
        declared = {
            w["file"]
            for w in STOCK_WRITERS
            if w["kind"] in ("direct", "insert") or w.get("scan_sql")
        }
        extra_update = update_files - declared
        extra_insert = insert_files - declared
        self.assertFalse(extra_update, extra_update)
        self.assertFalse(extra_insert, extra_insert)
        self.assertTrue(delta_files)

    def test_legacy_stock_commits_are_fenced_or_deprecated(self):
        fenced = []
        deprecated = []
        bypass = []
        for writer in STOCK_WRITERS:
            if writer["kind"] not in ("direct", "insert"):
                continue
            wid = writer["id"]
            func = writer["function"]
            class_name, method_name = func.split(".", 1)
            source = (REPO_ROOT / writer["file"]).read_text(encoding="utf-8")
            body = _function_own_body(source, class_name, method_name)
            has_stock = bool(UPDATE_STOCK_RE.search(body) or INSERT_STOCK_RE.search(body))
            has_fence = "commit_legacy_inventory" in body
            if wid in CONTRACT_DEPRECATED or wid in DEPRECATED_WRITER_IDS:
                deprecated.append(wid)
                if has_stock and not has_fence:
                    bypass.append(wid)
                continue
            if has_stock and not has_fence:
                bypass.append(wid)
            elif has_fence:
                fenced.append(wid)
            else:
                bypass.append(wid)
        self.assertFalse(bypass, f"bypass de freeze: {bypass}")
        self.assertEqual(set(fenced) | set(deprecated), set(DIRECT_IDS))
        self.assertIn("W15", deprecated)
        for required in ("W06", "W08", "W09", "W10", "W12", "W17", "W18"):
            self.assertIn(required, fenced)

    def test_authoritative_paths_have_no_legacy_stock_sql(self):
        targets = (
            ("services/ventas_service.py", "VentasService", "_agregar_productos_a_factura_authoritative"),
            ("repositories/productos_repo.py", "ProductosRepository", "_actualizar_producto_authoritative"),
            ("repositories/productos_repo.py", "ProductosRepository", "_crear_producto_authoritative"),
            ("services/movimientos_service.py", "MovimientosService", "_registrar_movimiento_authoritative"),
            ("repositories/inventario_repository.py", "InventarioRepository", "_registrar_movimiento_authoritative"),
            ("services/ventas_service.py", "VentasService", "_editar_linea_factura_authoritative"),
            ("services/ventas_service.py", "VentasService", "_eliminar_linea_factura_authoritative"),
        )
        for rel, cls, name in targets:
            body = _function_own_body(
                (REPO_ROOT / rel).read_text(encoding="utf-8"), cls, name
            )
            self.assertNotIn("stock = stock", body, msg=name)
            self.assertNotRegex(body, r"SET\s+stock\s*=", msg=name)

    def test_ui_has_no_direct_stock_commit(self):
        for rel in (
            "ui/dashboard_ui.py",
            "ui/ventas_ui_modern.py",
            "ui/productos_ui.py",
            "ui/movimientos_ui.py",
            "ui/entrada_inventario_ui.py",
        ):
            text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
            self.assertIsNone(UPDATE_STOCK_FILE_RE.search(text), rel)
            self.assertIsNone(INSERT_STOCK_FILE_RE.search(text), rel)

    def test_w08_metadata_branch_does_not_require_fence(self):
        body = _function_own_body(
            (REPO_ROOT / "repositories" / "productos_repo.py").read_text(encoding="utf-8"),
            "ProductosRepository",
            "actualizar_producto",
        )
        self.assertIn("stock_changed", body)
        self.assertIn("commit_legacy_inventory", body)
        self.assertIn("conn.commit()", body)
        self.assertNotIn("precio_venta = ?,\n                    stock = ?,\n                    stock_minimo", body)
        compact = " ".join(body.split())
        self.assertIn("UPDATE productos SET stock = ? WHERE id = ?", compact)

    def test_conn_commit_search_on_stock_writers(self):
        unfenced = []
        for writer in STOCK_WRITERS:
            if writer["kind"] not in ("direct", "insert"):
                continue
            class_name, method_name = writer["function"].split(".", 1)
            body = _function_own_body(
                (REPO_ROOT / writer["file"]).read_text(encoding="utf-8"),
                class_name,
                method_name,
            )
            if not CONN_COMMIT_RE.search(body):
                continue
            has_stock = bool(UPDATE_STOCK_RE.search(body) or INSERT_STOCK_RE.search(body))
            if has_stock and "commit_legacy_inventory" not in body:
                unfenced.append(writer["id"])
        self.assertFalse(unfenced, unfenced)

    def test_w09_zero_stock_is_not_inventory_mutation(self):
        body = _function_own_body(
            (REPO_ROOT / "repositories" / "productos_repo.py").read_text(encoding="utf-8"),
            "ProductosRepository",
            "crear_producto",
        )
        self.assertIn("initial_stock", body)
        self.assertIn("commit_legacy_inventory", body)
        compact = " ".join(body.split())
        self.assertIn("UPDATE productos SET stock = ? WHERE id = ?", compact)

    def test_scanner_function_hits_cover_gateway_writers(self):
        hits = scan_stock_writes_by_function()
        found = {h["writer_id"] for h in hits if h["writer_id"] in DIRECT_IDS}
        self.assertEqual(found, set(DIRECT_IDS))

    def test_w08_metadata_only_legacy_succeeds(self):
        from repositories.productos_repo import ProductosRepository

        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=50)
            finally:
                conn.close()
            repo = ProductosRepository(env.db)
            prod = make_producto(id=1, nombre="Solo metadata", stock=50)
            ok, msg = repo.actualizar_producto(prod)
            self.assertTrue(ok, msg)
            conn = env.connect()
            try:
                row = conn.execute(
                    "SELECT nombre, stock FROM productos WHERE id = 1"
                ).fetchone()
                self.assertEqual(row["nombre"], "Solo metadata")
                self.assertEqual(int(stock_of(conn)), 50)
            finally:
                conn.close()

    def test_w09_zero_initial_stock_legacy_succeeds(self):
        from repositories.productos_repo import ProductosRepository

        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=50)
            finally:
                conn.close()
            repo = ProductosRepository(env.db)
            prod = make_producto(nombre="SKU cero", stock=0)
            ok, msg, pid = repo.crear_producto(prod)
            self.assertTrue(ok, msg)
            self.assertIsNotNone(pid)
            conn = env.connect()
            try:
                row = conn.execute(
                    "SELECT stock FROM productos WHERE id = ?", (pid,)
                ).fetchone()
                self.assertEqual(int(row[0]), 0)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
