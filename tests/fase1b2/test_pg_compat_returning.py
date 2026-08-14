# -*- coding: utf-8 -*-
"""FASE 1B.2: PgCursor RETURNING segun PK declarada, sin inventar id."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class _RecCursor:
    def __init__(self):
        self.q = None
        self.params = None
        self.fetched = False

    def execute(self, q, params=None):
        self.q = q
        self.params = params

    def fetchone(self):
        self.fetched = True
        return (42,)


def _guardar_configuracion_insert_sql():
    src = (REPO_ROOT / "database.py").read_text(encoding="utf-8")
    match = re.search(
        r'def guardar_configuracion.*?cursor\.execute\(\s*"""(.*?)"""',
        src,
        flags=re.DOTALL,
    )
    if not match:
        raise AssertionError("no se encontro el INSERT de guardar_configuracion")
    return match.group(1)


def _usuarios_insert_sql():
    src = (REPO_ROOT / "database.py").read_text(encoding="utf-8")
    match = re.search(
        r"INSERT INTO usuarios \(username, password_hash, nombre_completo, rol\)\s*"
        r"VALUES \(\?, \?, \?, \?\)",
        src,
    )
    if not match:
        raise AssertionError("no se encontro el INSERT de usuarios")
    return match.group(0)


class PgCompatReturningTest(unittest.TestCase):
    def test_insert_tabla_con_id_mantiene_returning_id(self):
        from pg_compat import (
            PgCursor,
            insert_table_name,
            plain_insert_returning_clause,
        )

        sql = "INSERT INTO productos (nombre, stock) VALUES (?, ?)"
        self.assertEqual(insert_table_name(sql), "productos")
        self.assertEqual(plain_insert_returning_clause(sql), " RETURNING id")
        rec = _RecCursor()
        cur = PgCursor(rec)
        cur.execute(sql, ("Tornillo", 1))
        self.assertIn("RETURNING id", rec.q)
        self.assertTrue(rec.fetched)
        self.assertEqual(cur.lastrowid, 42)

    def test_configuracion_no_genera_returning_id(self):
        from pg_compat import PgCursor, insert_table_name, plain_insert_returning_clause

        sql = _guardar_configuracion_insert_sql()
        self.assertIn("INSERT INTO configuracion", sql)
        self.assertIn("ON CONFLICT(clave)", sql)
        self.assertEqual(insert_table_name(sql), "configuracion")
        self.assertEqual(plain_insert_returning_clause(sql), "")
        rec = _RecCursor()
        cur = PgCursor(rec)
        cur.execute(sql, ("tema", "oscuro", None))
        self.assertNotIn("RETURNING id", rec.q or "")
        self.assertNotIn("RETURNING clave", rec.q or "")
        self.assertFalse(rec.fetched)
        self.assertIsNone(cur.lastrowid)

    def test_no_inventa_pk_para_tabla_sin_metadata(self):
        from pg_compat import PgCompatError, insert_table_name, plain_insert_returning_clause
        from sync_registry import declared_insert_pk, pk_column

        sql = "INSERT INTO tabla_inventada (foo) VALUES (?)"
        self.assertEqual(insert_table_name(sql), "tabla_inventada")
        # pk_column() histórico defaulta a `id`; PgCursor no debe usar ese default.
        self.assertEqual(pk_column("tabla_inventada"), "id")
        self.assertIsNone(declared_insert_pk("tabla_inventada"))
        with self.assertRaises(PgCompatError) as ctx:
            plain_insert_returning_clause(sql)
        self.assertIn("falta pk declarada", str(ctx.exception).lower())

    def test_callers_no_sync_con_id_mantienen_returning_id(self):
        from pg_compat import PgCursor, plain_insert_returning_clause

        for sql in (
            "INSERT INTO formulas_mezcla (nombre) VALUES (?)",
            "INSERT INTO devoluciones (venta_id, fecha, usuario_id, motivo, tipo, total_devuelto) "
            "VALUES (?, ?, ?, ?, ?, ?)",
        ):
            self.assertEqual(plain_insert_returning_clause(sql), " RETURNING id", msg=sql)
            rec = _RecCursor()
            PgCursor(rec).execute(sql, ("x",))
            self.assertIn("RETURNING id", rec.q)

    def test_callers_pk_text_no_generan_returning_id(self):
        from pg_compat import PgCursor, plain_insert_returning_clause

        for sql in (
            "INSERT INTO consecutivos (clave, valor) VALUES (?, ?)",
            "INSERT INTO login_intentos (username, intentos, ultimo_intento, bloqueado_hasta) "
            "VALUES (?, ?, ?, ?)",
        ):
            self.assertEqual(plain_insert_returning_clause(sql), "", msg=sql)
            rec = _RecCursor()
            cur = PgCursor(rec)
            cur.execute(sql, ("k", 1, None, None))
            self.assertNotIn("RETURNING", rec.q or "")
            self.assertIsNone(cur.lastrowid)

    def test_compatibilidad_insert_usuarios(self):
        from pg_compat import PgCursor, plain_insert_returning_clause

        sql = _usuarios_insert_sql()
        self.assertEqual(plain_insert_returning_clause(sql), " RETURNING id")
        rec = _RecCursor()
        cur = PgCursor(rec)
        cur.execute(sql, ("admin", "hash", "Administrador", "ADMIN"))
        self.assertIn("RETURNING id", rec.q)
        self.assertEqual(cur.lastrowid, 42)

    def test_error_claro_si_no_se_resuelve_tabla(self):
        from pg_compat import PgCompatError, PgCursor, plain_insert_returning_clause

        with self.assertRaises(PgCompatError) as ctx:
            plain_insert_returning_clause("INSERT VALUES (1)")
        self.assertIn("no se pudo resolver", str(ctx.exception).lower())
        rec = _RecCursor()
        with self.assertRaises(PgCompatError):
            PgCursor(rec).execute("INSERT VALUES (1)")
        self.assertIsNone(rec.q)

    def test_non_sync_pk_cubre_tablas_documentadas(self):
        from sync_registry import NON_SYNC_INSERT_PK, NON_SYNC_TABLES, declared_insert_pk

        self.assertEqual(set(NON_SYNC_INSERT_PK), set(NON_SYNC_TABLES))
        self.assertEqual(declared_insert_pk("configuracion"), "clave")
        self.assertEqual(declared_insert_pk("productos"), "id")
        self.assertEqual(declared_insert_pk("formulas_mezcla"), "id")
        self.assertEqual(declared_insert_pk("consecutivos"), "clave")
