from __future__ import annotations

import sqlite3
import unittest

from legacy_sanitation import analyze_sqlite, normalize_supplier_document
from tests.fase0.harness import official_temp_db


def memory_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


class SanitationAnalysisTest(unittest.TestCase):
    def test_local_id_anomalies_are_reported_without_mutation(self):
        conn = memory_db()
        try:
            conn.execute("CREATE TABLE productos (id INTEGER PRIMARY KEY, local_id TEXT, stock REAL)")
            conn.executemany(
                "INSERT INTO productos(local_id, stock) VALUES (?, ?)",
                [(None, 1), ("bad", 2), ("11111111-1111-4111-8111-111111111111", 3),
                 ("11111111-1111-4111-8111-111111111111", 4)],
            )
            conn.commit()
            before = list(conn.execute("SELECT id, local_id, stock FROM productos"))
            report = analyze_sqlite(conn, tables=("productos",))
            codes = {item.code: item.affected for item in report.findings}
            self.assertEqual(codes["LOCAL_ID_MISSING"], 1)
            self.assertEqual(codes["LOCAL_ID_INVALID"], 1)
            self.assertEqual(codes["LOCAL_ID_DUPLICATE"], 1)
            self.assertEqual(before, list(conn.execute("SELECT id, local_id, stock FROM productos")))
        finally:
            conn.close()

    def test_duplicate_supplier_invoice_normalization(self):
        conn = memory_db()
        try:
            conn.execute(
                "CREATE TABLE compras (id INTEGER PRIMARY KEY, proveedor_id INTEGER, numero_factura TEXT)"
            )
            conn.executemany(
                "INSERT INTO compras(proveedor_id, numero_factura) VALUES (?, ?)",
                [(1, " ab-123 "), (1, "AB 123"), (2, "AB123")],
            )
            report = analyze_sqlite(conn, tables=("compras",))
            finding = next(item for item in report.findings if item.code == "SUPPLIER_INVOICE_DUPLICATE")
            self.assertEqual(finding.affected, 2)
            self.assertEqual(normalize_supplier_document(" ab-123 "), "AB123")
        finally:
            conn.close()

    def test_blank_supplier_invoice_is_reported_not_grouped_as_duplicate(self):
        conn = memory_db()
        try:
            conn.execute(
                "CREATE TABLE compras (id INTEGER PRIMARY KEY, proveedor_id INTEGER, numero_factura TEXT)"
            )
            conn.executemany(
                "INSERT INTO compras(proveedor_id, numero_factura) VALUES (?, ?)",
                [(1, None), (1, "  ")],
            )
            report = analyze_sqlite(conn, tables=("compras",))
            finding = next(
                item for item in report.findings
                if item.code == "SUPPLIER_INVOICE_IDENTITY_MISSING"
            )
            self.assertEqual(finding.affected, 2)
            self.assertFalse(
                any(item.code == "SUPPLIER_INVOICE_DUPLICATE" for item in report.findings)
            )
        finally:
            conn.close()

    def test_numeric_text_anomaly_and_schema_drift(self):
        conn = memory_db()
        try:
            conn.execute("CREATE TABLE productos (id INTEGER PRIMARY KEY, local_id TEXT, stock REAL)")
            conn.execute("INSERT INTO productos(local_id, stock) VALUES (?, ?)", ("bad", "not-number"))
            report = analyze_sqlite(conn, tables=("productos", "ventas"))
            codes = {item.code for item in report.findings}
            self.assertIn("NUMERIC_STORAGE_ANOMALY", codes)
            self.assertIn("SCHEMA_TABLE_MISSING", codes)
        finally:
            conn.close()

    def test_fresh_schema_reports_dual_movement_models_and_devoluciones_non_sync(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                report = analyze_sqlite(
                    conn,
                    tables=("movimientos", "movimientos_inventario", "devoluciones"),
                )
                self.assertTrue(any(item.code == "DUAL_MOVEMENT_MODELS" for item in report.findings))
                devolucion_cells = [item for item in report.schema if item.table == "devoluciones"]
                self.assertTrue(devolucion_cells)
                self.assertTrue(all(item.sync_status == "NON_SYNC" for item in devolucion_cells))
            finally:
                conn.close()

    def test_remote_id_duplicate_and_foreign_key_violation_are_reported(self):
        conn = memory_db()
        try:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute(
                "CREATE TABLE proveedores ("
                "id INTEGER PRIMARY KEY, local_id TEXT, remote_id TEXT)"
            )
            conn.execute(
                "CREATE TABLE compras ("
                "id INTEGER PRIMARY KEY, proveedor_id INTEGER, "
                "numero_factura TEXT, local_id TEXT, remote_id TEXT, "
                "FOREIGN KEY(proveedor_id) REFERENCES proveedores(id))"
            )
            conn.executemany(
                "INSERT INTO proveedores(local_id, remote_id) VALUES (?, ?)",
                [
                    ("11111111-1111-4111-8111-111111111111", "remote-1"),
                    ("22222222-2222-4222-8222-222222222222", "remote-1"),
                ],
            )
            conn.execute(
                "INSERT INTO compras(proveedor_id, numero_factura, local_id) "
                "VALUES (999, 'F-1', '33333333-3333-4333-8333-333333333333')"
            )
            conn.commit()
            report = analyze_sqlite(conn, tables=("proveedores", "compras"))
            codes = {item.code for item in report.findings}
            self.assertIn("REMOTE_ID_DUPLICATE", codes)
            self.assertIn("FOREIGN_KEY_VIOLATION", codes)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
