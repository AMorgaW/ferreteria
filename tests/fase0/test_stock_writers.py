# -*- coding: utf-8 -*-
"""Análisis estático: todo UPDATE/INSERT de stock debe estar en el inventario."""
import ast
import re
import unittest
from pathlib import Path

try:
    from harness import REPO_ROOT
    from stock_writers import (
        CLASSIFICATION_COUNTS,
        DIRECT_STOCK_WRITER_FILES,
        INSERT_STOCK_FILES,
        PRE_CUTOVER_SQL_ALLOWED,
        PROJECTION_STOCK_FILES,
        STOCK_WRITERS,
        UNTRACKED_DIRECT_WRITER,
        UPDATE_STOCK_FILES,
    )
except ImportError:
    from tests.fase0.harness import REPO_ROOT
    from tests.fase0.stock_writers import (
        CLASSIFICATION_COUNTS,
        DIRECT_STOCK_WRITER_FILES,
        INSERT_STOCK_FILES,
        PRE_CUTOVER_SQL_ALLOWED,
        PROJECTION_STOCK_FILES,
        STOCK_WRITERS,
        UNTRACKED_DIRECT_WRITER,
        UPDATE_STOCK_FILES,
    )

UPDATE_STOCK_RE = re.compile(
    r"UPDATE\s+productos\s+SET[\s\S]{0,800}?stock",
    re.IGNORECASE,
)

INSERT_STOCK_RE = re.compile(
    r"INSERT\s+INTO\s+productos\s*\([^;]{0,1200}?\bstock\b",
    re.IGNORECASE | re.DOTALL,
)

SET_STOCK_RE = re.compile(
    r"SET\s+stock\s*=|"
    r"stock\s*=\s*stock\s*[+-]\s*\?|"
    r"stock\s*=\s*\?",
    re.IGNORECASE,
)

SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "tests", "docs",
    ".cursor", ".agents", "dist", "build",
}


def _iter_production_py():
    for path in REPO_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        yield path, rel.as_posix()


def _scan_direct_stock_files():
    update_files = set()
    insert_files = set()
    set_stock_files = set()
    for path, rel in _iter_production_py():
        text = path.read_text(encoding="utf-8", errors="replace")
        if UPDATE_STOCK_RE.search(text):
            update_files.add(rel)
        if INSERT_STOCK_RE.search(text):
            insert_files.add(rel)
        if SET_STOCK_RE.search(text) and (
            "productos" in text.lower()
        ) and UPDATE_STOCK_RE.search(text):
            set_stock_files.add(rel)
    return update_files, insert_files, set_stock_files


def _function_parent_map(tree):
    parent = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    return parent


def _qualified_name(node, parent):
    parts = [node.name]
    current = parent.get(node)
    while current is not None:
        if isinstance(current, ast.ClassDef):
            parts.append(current.name)
        elif isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            parts.append(current.name)
        current = parent.get(current)
    return ".".join(reversed(parts))


def scan_stock_writes_by_function():
    """Asocia cada UPDATE/INSERT de productos.stock a archivo+función+SQL.

    Distingue LEGACY_ALLOWED_PRE_CUTOVER (writer inventariado) de
    UNTRACKED_DIRECT_WRITER (SQL directo fuera del inventario).
    """
    declared = []
    for writer in STOCK_WRITERS:
        if writer["kind"] == "derived" and not writer.get("scan_sql"):
            continue
        declared.append(
            (
                writer["id"],
                writer["file"],
                writer["function"].split("(")[0].strip(),
            )
        )

    hits = []
    for path, rel in _iter_production_py():
        source = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        lines = source.splitlines()
        parent = _function_parent_map(tree)
        functions = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end = getattr(node, "end_lineno", node.lineno)
                functions.append(
                    (node.lineno, end, _qualified_name(node, parent), node.name)
                )
        functions.sort()
        nested_by_parent = {i: [] for i in range(len(functions))}
        for i, (lineno, end, qual, name) in enumerate(functions):
            for j, (olineno, oend, _oqual, _oname) in enumerate(functions):
                if i == j:
                    continue
                if olineno > lineno and oend <= end:
                    nested_by_parent[i].append((olineno, oend))
        for i, (lineno, end, qual, name) in enumerate(functions):
            own = []
            nested = nested_by_parent[i]
            for idx in range(lineno, end + 1):
                if any(nstart <= idx <= nend for nstart, nend in nested):
                    continue
                own.append(lines[idx - 1])
            body = "\n".join(own)
            update_match = UPDATE_STOCK_RE.search(body)
            insert_match = INSERT_STOCK_RE.search(body)
            if not update_match and not insert_match:
                continue
            sql = (update_match.group(0) if update_match else insert_match.group(0))
            sql = " ".join(sql.split())
            writer_id = None
            for wid, wfile, wfunc in declared:
                if wfile != rel:
                    continue
                token = wfunc.split(".")[-1]
                auth_name = f"_{token}_authoritative"
                if (
                    token == name
                    or name == auth_name
                    or wfunc == qual
                    or qual.endswith("." + wfunc)
                ):
                    writer_id = wid
                    break
            status = (
                PRE_CUTOVER_SQL_ALLOWED
                if writer_id
                else UNTRACKED_DIRECT_WRITER
            )
            hits.append(
                {
                    "file": rel,
                    "function": qual,
                    "name": name,
                    "sql": sql[:240],
                    "writer_id": writer_id,
                    "status": status,
                    "kind": "update" if update_match else "insert",
                }
            )
    return hits


class StockWritersStaticTest(unittest.TestCase):
    def test_scanner_coincide_con_inventario(self):
        update_found, insert_found, _set_found = _scan_direct_stock_files()
        known_stock_files = DIRECT_STOCK_WRITER_FILES | PROJECTION_STOCK_FILES
        extra_update = update_found - known_stock_files
        missing_update = UPDATE_STOCK_FILES - update_found
        extra_insert = insert_found - INSERT_STOCK_FILES
        missing_insert = INSERT_STOCK_FILES - insert_found
        extra_direct = (update_found | insert_found) - known_stock_files
        self.assertFalse(
            extra_update,
            msg="Writer UPDATE de stock no inventariado en "
                "tests/fase0/stock_writers.py ni docs/fase0/STOCK_WRITERS.md: "
                f"{sorted(extra_update)}",
        )
        self.assertFalse(
            missing_update,
            msg="El inventario cita archivos sin UPDATE productos/stock; "
                f"actualizar STOCK_WRITERS.md: {sorted(missing_update)}",
        )
        self.assertFalse(
            extra_insert,
            msg="INSERT INTO productos con columna stock no inventariado: "
                f"{sorted(extra_insert)}",
        )
        self.assertFalse(
            missing_insert,
            msg="El inventario cita INSERT de stock sin coincidencia: "
                f"{sorted(missing_insert)}",
        )
        self.assertFalse(
            extra_direct,
            msg="Writer directo de stock (UPDATE/INSERT) no inventariado: "
                f"{sorted(extra_direct)}",
        )

    def test_inventario_declarado_tiene_ids_y_clasificacion(self):
        ids = [w["id"] for w in STOCK_WRITERS]
        self.assertEqual(len(ids), len(set(ids)), msg=f"IDs duplicados: {ids}")
        allowed = {"NEGATIVO", "POSITIVO", "MIXTO", "DERIVADO", "UNKNOWN"}
        kinds = {"direct", "insert", "derived"}
        for writer in STOCK_WRITERS:
            self.assertIn(writer["classification"], allowed, msg=writer["id"])
            self.assertIn(writer["kind"], kinds, msg=writer["id"])
            self.assertTrue(writer["file"], msg=writer["id"])
            self.assertTrue(writer["function"], msg=writer["id"])
            path = REPO_ROOT / writer["file"]
            self.assertTrue(path.is_file(), msg=f"{writer['id']} {writer['file']}")
            source = path.read_text(encoding="utf-8", errors="replace")
            token = writer["function"].split("(")[0].split(".")[-1].strip()
            if writer["kind"] != "derived":
                self.assertIn(
                    token.split()[0],
                    source,
                    msg=f"{writer['id']} no encuentra {token} en {writer['file']}",
                )
        self.assertEqual(CLASSIFICATION_COUNTS["UNKNOWN"], 0)
        self.assertEqual(sum(CLASSIFICATION_COUNTS.values()), len(STOCK_WRITERS))

    def test_funciones_directas_existen_en_ast_cuando_son_metodos(self):
        for writer in STOCK_WRITERS:
            if writer["kind"] == "derived":
                continue
            func = writer["function"]
            if "(" in func or "closure" in func.lower():
                continue
            if "." not in func:
                continue
            class_name, method_name = func.split(".", 1)
            path = REPO_ROOT / writer["file"]
            tree = ast.parse(path.read_text(encoding="utf-8"))
            found = False
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef) and item.name == method_name:
                            found = True
            self.assertTrue(
                found,
                msg=f"{writer['id']}: no está {class_name}.{method_name} en {writer['file']}",
            )

    def test_ui_todavia_ofrece_entrada_compra(self):
        """CAR INV-03: los combos productivos siguen listando ENTRADA_COMPRA."""
        entrada = (REPO_ROOT / "ui" / "entrada_inventario_ui.py").read_text(
            encoding="utf-8"
        )
        movimientos = (REPO_ROOT / "ui" / "movimientos_ui.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("ENTRADA_COMPRA", entrada)
        self.assertIn("ENTRADA_COMPRA", movimientos)
        self.assertIn("addItems(['ENTRADA_COMPRA'", entrada)

    def test_docs_stock_writers_menciona_ids_1e0(self):
        docs = (REPO_ROOT / "docs" / "fase0" / "STOCK_WRITERS.md").read_text(
            encoding="utf-8"
        )
        for writer in STOCK_WRITERS:
            self.assertIn(
                writer["id"],
                docs,
                msg=f"{writer['id']} falta en STOCK_WRITERS.md",
            )
        self.assertIn("UNKNOWN", docs)
        self.assertIn("0", docs)

    def test_scanner_asocia_writer_a_funcion_y_sql(self):
        hits = scan_stock_writes_by_function()
        self.assertTrue(hits, msg="el scanner de función no encontró SQL de stock")
        untracked = [h for h in hits if h["status"] == UNTRACKED_DIRECT_WRITER]
        self.assertFalse(
            untracked,
            msg="UNTRACKED_DIRECT_WRITER: " + repr(untracked),
        )
        by_id = {h["writer_id"]: h for h in hits if h["writer_id"]}
        for writer in STOCK_WRITERS:
            if writer["kind"] not in ("direct", "insert"):
                continue
            self.assertIn(
                writer["id"],
                by_id,
                msg=f"{writer['id']} {writer['function']} no tiene SQL de stock "
                    f"a nivel de función",
            )
            hit = by_id[writer["id"]]
            self.assertEqual(hit["status"], PRE_CUTOVER_SQL_ALLOWED)
            self.assertIn("stock", hit["sql"].lower())
            self.assertEqual(hit["file"], writer["file"])

    def test_negativos_preparados_siguen_legacy_sql_pre_cutover(self):
        from tests.fase0.stock_writers import (
            DIRECT_WRITER_IDS,
            GATEWAY_PREPARED_IDS,
            NEGATIVE_WRITER_IDS,
        )

        self.assertEqual(set(DIRECT_WRITER_IDS), GATEWAY_PREPARED_IDS)
        self.assertTrue(set(NEGATIVE_WRITER_IDS).issubset(GATEWAY_PREPARED_IDS))
        hits = scan_stock_writes_by_function()
        prepared_hits = [h for h in hits if h["writer_id"] in GATEWAY_PREPARED_IDS]
        self.assertEqual(
            {h["writer_id"] for h in prepared_hits},
            set(DIRECT_WRITER_IDS),
        )
        for hit in prepared_hits:
            self.assertEqual(hit["status"], PRE_CUTOVER_SQL_ALLOWED)
