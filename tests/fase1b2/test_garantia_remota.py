# -*- coding: utf-8 -*-
"""FASE 1B.2: _remote_identity_ensured solo True tras precondiciones reales."""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _classify_sql(sql: str) -> str:
    compact = " ".join((sql or "").lower().split())
    nospace = compact.replace(" ", "")
    if "foreach t in array" in compact:
        return "apply"
    if "from pg_index" in compact:
        return "verify"
    if compact.startswith("select table_name from information_schema.columns") and (
        "column_name='local_id'" in nospace
    ):
        return "cols_local_id"
    if compact.startswith("select table_name from information_schema.columns") and (
        "column_name='id'" in nospace
    ):
        return "cols_id"
    if "row_number()" in compact and "partition by local_id" in compact:
        return "dedupe"
    if compact.startswith("update ") and "set local_id" in compact and "where local_id is null" in compact:
        return "backfill"
    if "pg_get_serial_sequence" in compact:
        return "serial"
    return "other"


class _FakeCursor:
    def __init__(self, owner):
        self.owner = owner

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.owner.last_sql = sql
        self.owner.last_params = params
        self.owner.sqls.append(sql)
        kind = _classify_sql(sql)
        self.owner.kinds.append(kind)
        if kind == "apply":
            self.owner.apply_calls += 1
        if self.owner.fail_on and kind == self.owner.fail_on:
            raise RuntimeError(f"fallo simulado en {kind}")

    def fetchall(self):
        kind = _classify_sql(self.owner.last_sql or "")
        if kind == "cols_local_id":
            return [(t,) for t in self.owner.con_local_id]
        if kind == "cols_id":
            return [(t,) for t in self.owner.con_id]
        return []

    def fetchone(self):
        kind = _classify_sql(self.owner.last_sql or "")
        if kind == "serial":
            return (None,)
        if kind == "verify":
            return (bool(self.owner.verify_ok),)
        return None


class _FakeRemote:
    def __init__(
        self,
        con_local_id=("productos",),
        con_id=("productos",),
        fail_on=None,
        verify_ok=True,
    ):
        self.con_local_id = tuple(con_local_id)
        self.con_id = tuple(con_id)
        self.fail_on = fail_on
        self.verify_ok = verify_ok
        self.sqls = []
        self.kinds = []
        self.last_sql = ""
        self.last_params = None
        self.apply_calls = 0
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def _svc():
    from local_sync import SupabaseSyncService

    svc = SupabaseSyncService(
        db_path=":memory:", database_url="postgres://test-1b2"
    )
    svc._schema_ensured = True
    return svc


class GarantiaRemotaTest(unittest.TestCase):
    def test_sql_canonica_correcta_ensured_true(self):
        fake = _FakeRemote()
        svc = _svc()
        svc._ensure_remote_local_id_identity(fake)
        self.assertTrue(svc._remote_identity_ensured)
        self.assertIsNone(svc._remote_identity_last_error)
        self.assertGreaterEqual(fake.apply_calls, 1)
        self.assertIn("apply", fake.kinds)
        self.assertIn("verify", fake.kinds)

    def test_fallo_antes_de_unique_flag_false(self):
        fake = _FakeRemote(fail_on="backfill")
        svc = _svc()
        with self.assertRaises(RuntimeError):
            svc._ensure_remote_local_id_identity(fake)
        self.assertFalse(svc._remote_identity_ensured)
        self.assertIsNotNone(svc._remote_identity_last_error)
        self.assertEqual(fake.apply_calls, 0)

    def test_fallo_despues_de_backfill_antes_de_unique_flag_false(self):
        from schema_bootstrap import SchemaBootstrapError

        fake = _FakeRemote(fail_on="apply")
        svc = _svc()
        with self.assertRaises(SchemaBootstrapError):
            svc._ensure_remote_local_id_identity(fake)
        self.assertFalse(svc._remote_identity_ensured)
        self.assertIsInstance(
            svc._remote_identity_last_error, SchemaBootstrapError
        )
        self.assertIn("backfill", fake.kinds)
        self.assertIn("dedupe", fake.kinds)

    def test_retry_posterior_exitoso_true(self):
        fake = _FakeRemote(fail_on="backfill")
        svc = _svc()
        with self.assertRaises(RuntimeError):
            svc._ensure_remote_local_id_identity(fake)
        self.assertFalse(svc._remote_identity_ensured)
        fake.fail_on = None
        svc._ensure_remote_local_id_identity(fake)
        self.assertTrue(svc._remote_identity_ensured)
        self.assertIsNone(svc._remote_identity_last_error)

    def test_dos_llamadas_exitosas_idempotentes(self):
        fake = _FakeRemote()
        svc = _svc()
        svc._ensure_remote_local_id_identity(fake)
        first_apply = fake.apply_calls
        first_len = len(fake.sqls)
        self.assertGreaterEqual(first_apply, 1)
        svc._ensure_remote_local_id_identity(fake)
        self.assertTrue(svc._remote_identity_ensured)
        self.assertEqual(fake.apply_calls, first_apply)
        self.assertEqual(len(fake.sqls), first_len)

    def test_excepcion_visible_conservada(self):
        fake = _FakeRemote(fail_on="dedupe")
        svc = _svc()
        with self.assertRaises(RuntimeError) as ctx:
            svc._ensure_remote_local_id_identity(fake)
        self.assertIs(svc._remote_identity_last_error, ctx.exception)
        self.assertIn("dedupe", str(svc._remote_identity_last_error))
        self.assertFalse(svc._remote_identity_ensured)

    def test_unique_no_verificado_no_certifica(self):
        from local_sync import RemoteLocalIdIdentityError

        fake = _FakeRemote(verify_ok=False)
        svc = _svc()
        with self.assertRaises(RemoteLocalIdIdentityError):
            svc._ensure_remote_local_id_identity(fake)
        self.assertFalse(svc._remote_identity_ensured)
        self.assertIsInstance(
            svc._remote_identity_last_error, RemoteLocalIdIdentityError
        )
        self.assertGreaterEqual(fake.apply_calls, 1)

    def test_remote_connect_no_except_pass_alrededor_de_identidad(self):
        src = (REPO_ROOT / "local_sync.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if node.name != "_remote_connect":
                continue
            for child in ast.walk(node):
                if not isinstance(child, ast.Try):
                    continue
                calls_identity = any(
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "_ensure_remote_local_id_identity"
                    for call in ast.walk(child)
                )
                if not calls_identity:
                    continue
                found = True
                self.assertTrue(child.handlers, msg="try de identidad sin except")
                for handler in child.handlers:
                    body = handler.body
                    self.assertFalse(
                        len(body) == 1 and isinstance(body[0], ast.Pass),
                        msg="_remote_connect no debe usar except pass en identidad",
                    )
                    attrs = [
                        n.attr
                        for n in ast.walk(handler)
                        if isinstance(n, ast.Attribute)
                    ]
                    self.assertIn("_remote_identity_last_error", attrs)
        self.assertTrue(found, msg="no se encontró try de identidad en _remote_connect")

    def test_remote_connect_degrada_sin_fingir_exito(self):
        fake = _FakeRemote(fail_on="backfill")
        svc = _svc()
        with patch("local_sync.psycopg2.connect", return_value=fake):
            remote = svc._remote_connect()
        self.assertIs(remote, fake)
        self.assertFalse(svc._remote_identity_ensured)
        self.assertIsNotNone(svc._remote_identity_last_error)

    def test_ensure_no_except_pass_ni_continue_tras_fallo(self):
        src = (REPO_ROOT / "local_sync.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == (
                "_ensure_remote_local_id_identity"
            ):
                text = ast.get_source_segment(src, node) or ""
                self.assertNotIn("except Exception:\n            pass", text)
                self.assertIn("_remote_identity_last_error", text)
                self.assertIn("raise", text)
