# -*- coding: utf-8 -*-
import ast
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from services.local_api_client import LocalAPIClient, LocalAPIError
from local_sync import SupabaseSyncService


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class LocalFirstIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "ferreteria-test.db"
        shutil.copy2(BASE_DIR / "ferreteria.db", cls.db_path)
        cls.port = free_port()
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.process = subprocess.Popen(
            [
                sys.executable,
                str(BASE_DIR / "local_server.py"),
                "--host",
                "127.0.0.1",
                "--port",
                str(cls.port),
                "--db",
                str(cls.db_path),
                "--no-sync",
            ],
            cwd=str(BASE_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        client = LocalAPIClient(cls.base_url, timeout=1)
        for _ in range(50):
            try:
                client.health()
                break
            except LocalAPIError:
                time.sleep(0.1)
        else:
            raise RuntimeError("El servidor HTTP local no inicio para las pruebas.")

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        try:
            cls.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait(timeout=2)
        cls.temp_dir.cleanup()

    def test_01_health_and_login(self):
        health = LocalAPIClient(self.base_url).health()
        self.assertEqual(health["mode"], "local-first")

        admin = LocalAPIClient(self.base_url)
        login = admin.login("admin", "admin123")
        self.assertEqual(login["user"]["rol"], "ADMIN")

    def test_02_remote_sale_recalculates_price_and_updates_local_queue(self):
        client = LocalAPIClient(self.base_url)
        client.login("empleado", "empleado123")
        product = client.get_products(limit=1)[0]
        original_stock = float(product["stock"])
        expected_price = float(product["precio_venta"])

        sale = client.create_sale(
            {
                "metodo_pago": "EFECTIVO",
                "items": [
                    {
                        "producto_id": product["id"],
                        "cantidad": 1,
                        "precio_unitario": 1,
                    }
                ],
            }
        )
        self.assertEqual(float(sale["venta"]["total"]), expected_price)
        self.assertEqual(sale["sync_status"], "pending")

        updated = client.get_product(product["id"])
        self.assertEqual(float(updated["stock"]), original_stock - 1)

        conn = sqlite3.connect(self.db_path)
        try:
            queued = conn.execute(
                "SELECT COUNT(*) FROM sync_queue WHERE status='pending'"
            ).fetchone()[0]
            movements = conn.execute(
                "SELECT COUNT(*) FROM movimientos WHERE num_factura=?",
                (sale["venta"]["numero_factura"],),
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertGreaterEqual(queued, 4)
        self.assertEqual(movements, 1)

    def test_03_permissions_and_stock_validation(self):
        worker = LocalAPIClient(self.base_url)
        worker.login("empleado", "empleado123")
        with self.assertRaises(LocalAPIError):
            worker.get_sync_queue()

        product = worker.get_products(limit=1)[0]
        with self.assertRaises(LocalAPIError):
            worker.create_sale(
                {
                    "items": [
                        {
                            "producto_id": product["id"],
                            "cantidad": float(product["stock"]) + 1,
                        }
                    ]
                }
            )
        with self.assertRaises(LocalAPIError):
            worker.create_sale(
                {
                    "items": [
                        {"producto_id": product["id"], "cantidad": float(product["stock"])},
                        {"producto_id": product["id"], "cantidad": 1},
                    ]
                }
            )

    def test_04_client_mode_does_not_import_sqlite_modules(self):
        forbidden = {"database", "pg_compat", "local_first_db", "local_sync", "repositories"}
        roots = set()
        for path in [BASE_DIR / "client_app.py", BASE_DIR / "services" / "local_api_client.py"]:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots.update(alias.name.split(".", 1)[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    roots.add(node.module.split(".", 1)[0])
        self.assertFalse(roots & forbidden)

    def test_05_supabase_outage_keeps_changes_queued(self):
        service = SupabaseSyncService(
            db_path=str(self.db_path),
            database_url="this is not a valid postgresql dsn",
        )
        result = service.sync_once(limit=1)
        self.assertEqual(result["failed"], 1)

        conn = sqlite3.connect(self.db_path)
        try:
            pending = conn.execute(
                "SELECT COUNT(*) FROM sync_queue WHERE status='pending'"
            ).fetchone()[0]
            error = conn.execute(
                "SELECT valor FROM sync_state WHERE clave='last_error'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertGreaterEqual(pending, 1)
        self.assertTrue(error)


if __name__ == "__main__":
    unittest.main(verbosity=2)
