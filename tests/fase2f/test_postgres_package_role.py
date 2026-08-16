from __future__ import annotations

import unittest
import uuid

import psycopg2

from barcode_schema import (
    apply_postgres_barcode_migration,
    apply_postgres_barcode_package_role_migration,
)
from tests.fase1e1.pg_dsn import ensure_pg_test_dsn


class PostgresPackageRoleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = ensure_pg_test_dsn()
        if not cls.dsn:
            raise RuntimeError("Fase 2F requiere ferrepro-pg-test en localhost:55432")

    def test_23_package_role_migration_rerun_checksum_and_default(self):
        conn = psycopg2.connect(self.dsn, connect_timeout=5)
        product_lid = str(uuid.uuid4())
        barcode_lid = str(uuid.uuid4())
        try:
            apply_postgres_barcode_migration(conn)
            first = apply_postgres_barcode_package_role_migration(conn)
            second = apply_postgres_barcode_package_role_migration(conn)
            self.assertIn(first.status, ("APPLIED", "SKIPPED_APPLIED"))
            self.assertEqual(second.status, "SKIPPED_APPLIED")
            self.assertEqual(first.checksum, second.checksum)
            with conn.cursor() as cur:
                cur.execute("INSERT INTO productos(local_id,nombre,stock) VALUES(%s,'PG 2F',0)", (product_lid,))
                cur.execute(
                    "INSERT INTO product_barcodes(local_id,producto_local_id,barcode) VALUES(%s,%s,%s) RETURNING package_role",
                    (barcode_lid, product_lid, "PG2F-" + uuid.uuid4().hex),
                )
                self.assertEqual(cur.fetchone()[0], "BASE_UNIT")
            conn.commit()
        finally:
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute("DELETE FROM product_barcodes WHERE local_id=%s", (barcode_lid,))
                cur.execute("DELETE FROM productos WHERE local_id=%s", (product_lid,))
            conn.commit()
            conn.close()


if __name__ == "__main__":
    unittest.main()
