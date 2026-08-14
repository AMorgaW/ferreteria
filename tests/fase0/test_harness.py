# -*- coding: utf-8 -*-
"""El harness usa el esquema oficial y no toca ferreteria.db."""
import ast
import unittest
from pathlib import Path

try:
    from harness import REPO_FERRETERIA_DB, REPO_ROOT, official_temp_db
except ImportError:
    from tests.fase0.harness import REPO_FERRETERIA_DB, REPO_ROOT, official_temp_db


def _calls_shutil_copy2(source: str) -> bool:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in {"copy2", "copy"}:
            if isinstance(func.value, ast.Name) and func.value.id == "shutil":
                return True
    return False


class HarnessOficialTest(unittest.TestCase):
    def test_no_copia_ferreteria_db_en_codigo_fase0(self):
        fase0 = Path(__file__).resolve().parent
        for path in fase0.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertFalse(
                _calls_shutil_copy2(text),
                msg=f"{path.name} no debe llamar shutil.copy/copy2",
            )

    def test_materializa_tablas_oficiales_en_tempfile(self):
        with official_temp_db() as env:
            self.assertTrue(env.db_path.exists())
            self.assertNotEqual(env.db_path.resolve(), REPO_FERRETERIA_DB.resolve())
            self.assertIn("ferrepro-fase0-", str(env.db_path))
            conn = env.connect()
            try:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
            finally:
                conn.close()
            for required in (
                "productos", "compras", "detalle_compras", "movimientos",
                "movimientos_inventario", "ventas", "proveedores", "sync_queue",
            ):
                self.assertIn(required, tables)

    def test_apunta_a_local_no_al_repo(self):
        with official_temp_db() as env:
            import pg_compat
            self.assertEqual(Path(pg_compat.LOCAL_DB_PATH).resolve(), env.db_path.resolve())
            conn = env.db.conectar()
            try:
                row = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='productos'"
                ).fetchone()
                self.assertIsNotNone(row)
            finally:
                conn.close()

    def test_legacy_integration_sigue_copiando_ferreteria_db(self):
        """CAR INV-14: el test viejo todavía depende de copiar ferreteria.db."""
        legacy = (REPO_ROOT / "tests" / "test_local_first_integration.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("shutil.copy2", legacy)
        self.assertIn("ferreteria.db", legacy)
