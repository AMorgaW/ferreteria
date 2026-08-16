from __future__ import annotations

import concurrent.futures
import threading
import unittest
import uuid

import psycopg2
from psycopg2 import sql

from barcode_schema import apply_postgres_barcode_migration
from tests.fase1e1.pg_dsn import ensure_pg_test_dsn


class PostgresBarcodeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = ensure_pg_test_dsn()
        if not cls.dsn:
            raise RuntimeError(
                "Fase 2C requiere ferrepro-pg-test en localhost:55432"
            )
        admin = psycopg2.connect(cls.dsn, connect_timeout=5)
        apply_postgres_barcode_migration(admin)
        cls.created_products = set()
        cls.allowed_role = "ferrepro_barcode_allowed_test"
        cls.denied_role = "ferrepro_barcode_denied_test"
        cls.allowed_password = "F2cAllowed-Only-Lab!"
        cls.denied_password = "F2cDenied-Only-Lab!"
        with admin.cursor() as cur:
            cur.execute("SELECT current_database()")
            dbname = cur.fetchone()[0]
            for role in (cls.allowed_role, cls.denied_role):
                cur.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,))
                if cur.fetchone():
                    cur.execute(sql.SQL("DROP OWNED BY {} CASCADE").format(sql.Identifier(role)))
                    cur.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
            cur.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS "
                    "NOCREATEDB NOCREATEROLE INHERIT PASSWORD %s"
                ).format(sql.Identifier(cls.allowed_role)),
                (cls.allowed_password,),
            )
            cur.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS "
                    "NOCREATEDB NOCREATEROLE INHERIT PASSWORD %s"
                ).format(sql.Identifier(cls.denied_role)),
                (cls.denied_password,),
            )
            cur.execute(
                sql.SQL("GRANT ferrepro_barcode_app TO {}").format(
                    sql.Identifier(cls.allowed_role)
                )
            )
            for role in (cls.allowed_role, cls.denied_role):
                cur.execute(
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                        sql.Identifier(dbname), sql.Identifier(role)
                    )
                )
                cur.execute(
                    sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
                        sql.Identifier(role)
                    )
                )
        admin.commit()
        admin.close()

    @classmethod
    def tearDownClass(cls):
        admin = psycopg2.connect(cls.dsn, connect_timeout=5)
        try:
            with admin.cursor() as cur:
                if cls.created_products:
                    lids = list(cls.created_products)
                    cur.execute(
                        "DELETE FROM product_barcodes WHERE producto_local_id = ANY(%s)",
                        (lids,),
                    )
                    cur.execute(
                        "DELETE FROM productos WHERE local_id = ANY(%s)",
                        (lids,),
                    )
                for role in (cls.allowed_role, cls.denied_role):
                    cur.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,))
                    if cur.fetchone():
                        cur.execute(
                            sql.SQL("DROP OWNED BY {} CASCADE").format(
                                sql.Identifier(role)
                            )
                        )
                        cur.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
            admin.commit()
        finally:
            admin.close()

    def _connect(self):
        conn = psycopg2.connect(self.dsn, connect_timeout=5)
        conn.autocommit = False
        return conn

    def _product(self, conn, name):
        local_id = str(uuid.uuid4())
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO productos(local_id,nombre,stock) VALUES(%s,%s,0)",
                (local_id, name),
            )
        conn.commit()
        self.created_products.add(local_id)
        return local_id

    def _insert_barcode(self, conn, product_lid, barcode):
        local_id = str(uuid.uuid4())
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO product_barcodes"
                "(local_id,producto_local_id,barcode,is_primary) "
                "VALUES(%s,%s,%s,1)",
                (local_id, product_lid, barcode),
            )
        return local_id

    def test_34_central_duplicate_barcode_rejected(self):
        conn = self._connect()
        try:
            a = self._product(conn, "PG Central A")
            b = self._product(conn, "PG Central B")
            barcode = "PG-" + uuid.uuid4().hex
            self._insert_barcode(conn, a, barcode)
            conn.commit()
            with self.assertRaises(psycopg2.errors.UniqueViolation):
                self._insert_barcode(conn, b, barcode)
            conn.rollback()
        finally:
            conn.close()

    def test_35_concurrent_duplicate_assignment_one_success_one_conflict(self):
        setup = self._connect()
        try:
            product_a = self._product(setup, "Station A")
            product_b = self._product(setup, "Station B")
        finally:
            setup.close()
        barcode = "RACE-" + uuid.uuid4().hex
        barrier = threading.Barrier(2)

        def station(product_lid):
            conn = self._connect()
            try:
                barrier.wait(timeout=5)
                self._insert_barcode(conn, product_lid, barcode)
                conn.commit()
                return "SUCCESS"
            except psycopg2.errors.UniqueViolation:
                conn.rollback()
                return "CONFLICT"
            finally:
                conn.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(station, (product_a, product_b)))
        self.assertCountEqual(results, ["SUCCESS", "CONFLICT"])

    def test_36_app_role_permissions(self):
        admin = self._connect()
        try:
            product = self._product(admin, "Role Product")
        finally:
            admin.close()

        allowed = psycopg2.connect(
            self.dsn,
            user=self.allowed_role,
            password=self.allowed_password,
            connect_timeout=5,
        )
        try:
            self._insert_barcode(allowed, product, "ROLE-" + uuid.uuid4().hex)
            allowed.commit()
        finally:
            allowed.close()

        denied = psycopg2.connect(
            self.dsn,
            user=self.denied_role,
            password=self.denied_password,
            connect_timeout=5,
        )
        try:
            with self.assertRaises(psycopg2.errors.InsufficientPrivilege):
                with denied.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM product_barcodes")
            denied.rollback()
        finally:
            denied.close()

    def test_37_migration_rerun(self):
        conn = self._connect()
        try:
            first = apply_postgres_barcode_migration(conn)
            second = apply_postgres_barcode_migration(conn)
            self.assertEqual(first.status, "SKIPPED_APPLIED")
            self.assertEqual(second.status, "SKIPPED_APPLIED")
            self.assertEqual(first.checksum, second.checksum)
        finally:
            conn.close()

    def test_38_restart_lookup_persistence(self):
        conn = self._connect()
        barcode = "RESTART-" + uuid.uuid4().hex
        try:
            product = self._product(conn, "Restart Product")
            local_id = self._insert_barcode(conn, product, barcode)
            conn.commit()
        finally:
            conn.close()

        reopened = self._connect()
        try:
            with reopened.cursor() as cur:
                cur.execute(
                    "SELECT local_id,producto_local_id,barcode "
                    "FROM product_barcodes WHERE barcode=%s",
                    (barcode,),
                )
                row = cur.fetchone()
            self.assertEqual(row, (local_id, product, barcode))
        finally:
            reopened.close()


if __name__ == "__main__":
    unittest.main()
