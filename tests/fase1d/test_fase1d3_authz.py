# -*- coding: utf-8 -*-
"""FASE 1D.3: autorización empresarial con roles PostgreSQL no-owner."""
from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

from psycopg2 import errors as pg_errors

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase1d.helpers import DEVICE, _op_scaled
from tests.fase1d.pg_harness import (
    POSTGRES_SKIP_REASON,
    apply_coordinator_schema,
    connect,
    connect_as,
    current_session_user,
    insert_producto,
    postgres_available,
    provision_inventory_test_roles,
)


def _skip_unless_pg():
    return unittest.skipUnless(postgres_available(), POSTGRES_SKIP_REASON)


@_skip_unless_pg()
class Fase1D3AuthorizationTest(unittest.TestCase):
    allowed_role = "ferrepro_inventory_allowed_test"
    denied_role = "ferrepro_inventory_denied_test"

    @classmethod
    def setUpClass(cls):
        cls.allowed_password = "t-" + uuid.uuid4().hex
        cls.denied_password = "t-" + uuid.uuid4().hex
        admin = connect()
        try:
            apply_coordinator_schema(admin)
            provision_inventory_test_roles(
                admin,
                allowed_password=cls.allowed_password,
                denied_password=cls.denied_password,
            )
            with admin.cursor() as cur:
                cur.execute(
                    """
                    SELECT rolname, rolsuper, rolbypassrls
                    FROM pg_roles
                    WHERE rolname IN (%s, %s, %s)
                    ORDER BY rolname
                    """,
                    (
                        "ferrepro_inventory_app",
                        cls.allowed_role,
                        cls.denied_role,
                    ),
                )
                rows = cur.fetchall()
            admin.rollback()
            cls._role_flags = {row[0]: (bool(row[1]), bool(row[2])) for row in rows}
        finally:
            admin.close()

    def setUp(self):
        self.admin = connect()

    def tearDown(self):
        try:
            self.admin.close()
        except Exception:
            pass

    def _seed_product(self, qty):
        from inventory_coordinator import InventoryCoordinatorClient

        lid = insert_producto(self.admin, stock=0)
        InventoryCoordinatorClient(self.admin).seed_balance(lid, qty)
        return lid

    def _apply_kwargs(self, lid, delta_scaled, *, tipo="VENTA", usuario_id=None):
        return {
            "command_id": str(uuid.uuid4()),
            "tipo": tipo,
            "device_id": DEVICE,
            "usuario_id": usuario_id,
            "operations": [_op_scaled(lid, delta_scaled)],
        }

    def test_roles_no_son_superuser_ni_bypassrls(self):
        self.assertIn(self.allowed_role, self._role_flags)
        self.assertIn(self.denied_role, self._role_flags)
        for name, (superuser, bypass) in self._role_flags.items():
            self.assertFalse(superuser, name)
            self.assertFalse(bypass, name)

    def test_allowed_no_es_owner_de_tablas(self):
        with self.admin.cursor() as cur:
            cur.execute(
                """
                SELECT c.relname
                FROM pg_class c
                JOIN pg_roles r ON r.oid = c.relowner
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND r.rolname IN (%s, %s)
                """,
                (self.allowed_role, self.denied_role),
            )
            owned = [row[0] for row in cur.fetchall()]
        self.admin.rollback()
        self.assertEqual(owned, [])

    def test_allowed_ejecuta_solo_lo_permitido(self):
        from inventory_coordinator import InventoryCoordinatorClient, STATE_APPLIED

        lid = self._seed_product(50000)
        conn = connect_as(self.allowed_role, self.allowed_password)
        self.addCleanup(conn.close)
        self.assertEqual(current_session_user(conn), self.allowed_role)
        rec = InventoryCoordinatorClient(conn).apply_command(
            **self._apply_kwargs(lid, -1000)
        )
        self.assertEqual(rec.estado, STATE_APPLIED)
        self.assertFalse(rec.replayed)
        with self.admin.cursor() as cur:
            cur.execute(
                "SELECT quantity_scaled FROM inventory_balances WHERE producto_local_id=%s",
                (lid,),
            )
            qty = int(cur.fetchone()[0])
        self.admin.rollback()
        self.assertEqual(qty, 49000)

    def test_denied_no_ejecuta_rpc(self):
        from inventory_coordinator import InventoryCoordinatorClient

        lid = self._seed_product(50000)
        conn = connect_as(self.denied_role, self.denied_password)
        self.addCleanup(conn.close)
        self.assertEqual(current_session_user(conn), self.denied_role)
        with self.assertRaises(Exception) as ctx:
            InventoryCoordinatorClient(conn).apply_command(
                **self._apply_kwargs(lid, -1000)
            )
        message = str(ctx.exception).lower()
        self.assertTrue(
            "permission denied" in message or "inventory_forbidden" in message,
            msg=str(ctx.exception),
        )
        with self.admin.cursor() as cur:
            cur.execute(
                "SELECT quantity_scaled FROM inventory_balances WHERE producto_local_id=%s",
                (lid,),
            )
            qty = int(cur.fetchone()[0])
        self.admin.rollback()
        self.assertEqual(qty, 50000)

    def test_public_no_tiene_execute(self):
        with self.admin.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.role_routine_grants
                WHERE routine_schema='public'
                  AND routine_name='apply_inventory_command'
                  AND grantee='PUBLIC'
                  AND privilege_type='EXECUTE'
                """
            )
            self.assertEqual(int(cur.fetchone()[0]), 0)

    def test_allowed_no_puede_seed_ni_dml_directo(self):
        from inventory_coordinator import seed_inventory_balance

        lid = insert_producto(self.admin, stock=0)
        conn = connect_as(self.allowed_role, self.allowed_password)
        self.addCleanup(conn.close)
        with self.assertRaises(Exception) as seed_ctx:
            seed_inventory_balance(conn, lid, 1000)
        seed_msg = str(seed_ctx.exception).lower()
        self.assertTrue(
            "permission denied" in seed_msg or "inventory_forbidden" in seed_msg,
            msg=str(seed_ctx.exception),
        )
        try:
            conn.rollback()
        except Exception:
            pass
        with self.assertRaises(pg_errors.InsufficientPrivilege):
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE inventory_balances SET quantity_scaled = 1 "
                    "WHERE producto_local_id = %s",
                    (lid,),
                )
        conn.rollback()
        with self.assertRaises(pg_errors.InsufficientPrivilege):
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM inventory_balances")
        conn.rollback()

    def test_usuario_id_manipulado_no_escala_privilegio(self):
        from inventory_coordinator import InventoryCoordinatorClient

        lid = self._seed_product(50000)
        denied = connect_as(self.denied_role, self.denied_password)
        self.addCleanup(denied.close)
        with self.assertRaises(Exception):
            InventoryCoordinatorClient(denied).apply_command(
                **self._apply_kwargs(lid, -1000, usuario_id=1)
            )
        allowed = connect_as(self.allowed_role, self.allowed_password)
        self.addCleanup(allowed.close)
        rec = InventoryCoordinatorClient(allowed).apply_command(
            **self._apply_kwargs(lid, -1000, usuario_id=999999)
        )
        self.assertEqual(rec.estado, "APPLIED")
        self.assertEqual(rec.usuario_id, 999999)

    def test_rpc_rechaza_venta_positiva_sin_pasar_por_adapter(self):
        import json

        from inventory_ledger import command_request_hash

        lid = self._seed_product(50000)
        cid = str(uuid.uuid4())
        oid = str(uuid.uuid4())
        ops = [
            {
                "operation_id": oid,
                "producto_local_id": lid,
                "delta_scaled": 1000,
                "line_no": 1,
            }
        ]
        request_hash = command_request_hash(
            command_id=cid,
            tipo="VENTA",
            documento_tipo=None,
            documento_local_id=None,
            operations=ops,
        )
        conn = connect_as(self.allowed_role, self.allowed_password)
        self.addCleanup(conn.close)
        with self.assertRaises(Exception) as ctx:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT public.apply_inventory_command(
                        %s, %s, %s, %s, %s, %s, %s, %s::jsonb
                    )
                    """,
                    (
                        cid,
                        "VENTA",
                        None,
                        None,
                        DEVICE,
                        None,
                        request_hash,
                        json.dumps(ops, ensure_ascii=False, separators=(",", ":")),
                    ),
                )
        conn.rollback()
        self.assertIn("INVALID_DELTA_SIGN", str(ctx.exception))
        with self.admin.cursor() as cur:
            cur.execute(
                "SELECT quantity_scaled FROM inventory_balances WHERE producto_local_id=%s",
                (lid,),
            )
            qty = int(cur.fetchone()[0])
        self.admin.rollback()
        self.assertEqual(qty, 50000)
        from inventory_coordinator import InvalidDeltaSignError, apply_inventory_command

        lid = self._seed_product(50000)
        conn = connect_as(self.allowed_role, self.allowed_password)
        self.addCleanup(conn.close)
        with self.assertRaises(InvalidDeltaSignError):
            apply_inventory_command(
                conn, **self._apply_kwargs(lid, 1000, tipo="VENTA")
            )
        with self.admin.cursor() as cur:
            cur.execute(
                "SELECT quantity_scaled FROM inventory_balances WHERE producto_local_id=%s",
                (lid,),
            )
            qty = int(cur.fetchone()[0])
        self.admin.rollback()
        self.assertEqual(qty, 50000)

    def test_security_definer_search_path_y_session_user(self):
        with self.admin.cursor() as cur:
            cur.execute(
                """
                SELECT pg_get_userbyid(p.proowner), p.prosecdef, p.proconfig
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname='public' AND p.proname='apply_inventory_command'
                """
            )
            owner, security_definer, config = cur.fetchone()
            self.assertTrue(security_definer)
            self.assertIsNotNone(config)
            joined = " ".join(config)
            self.assertIn("pg_catalog", joined)
            self.assertIn("public", joined)
            cur.execute(
                """
                SELECT pg_get_functiondef(p.oid)
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname='public'
                  AND p.proname='ferrepro_inventory_caller_is_allowed'
                """
            )
            helper = cur.fetchone()[0]
            cur.execute(
                """
                SELECT pg_get_functiondef(p.oid)
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname='public' AND p.proname='apply_inventory_command'
                """
            )
            defn = cur.fetchone()[0]
        self.admin.rollback()
        self.assertIn("ferrepro_inventory_caller_is_allowed", defn)
        self.assertIn("session_user", helper)
        self.assertNotIn("EXECUTE format", defn)
        self.assertIsNotNone(owner)

    def test_allowed_no_puede_set_role_owner(self):
        with self.admin.cursor() as cur:
            cur.execute("SELECT current_user")
            owner = cur.fetchone()[0]
        self.admin.rollback()
        conn = connect_as(self.allowed_role, self.allowed_password)
        self.addCleanup(conn.close)
        with self.assertRaises(Exception):
            with conn.cursor() as cur:
                cur.execute(f"SET ROLE {owner}")
        conn.rollback()

    def test_constraints_nombradas_tras_migracion(self):
        expected = {
            "inventory_commands": "pk_inventory_commands",
            "inventory_operations": "pk_inventory_operations",
            "inventory_balances": "pk_inventory_balances",
            "inventory_balance_init": "pk_inventory_balance_init",
            "inventory_balance_init_state": "pk_inventory_balance_init_state",
        }
        with self.admin.cursor() as cur:
            cur.execute(
                """
                SELECT t.relname, c.conname
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE n.nspname='public'
                  AND t.relname = ANY(%s)
                  AND c.contype = 'p'
                """,
                (list(expected.keys()),),
            )
            found = {row[0]: row[1] for row in cur.fetchall()}
            cur.execute(
                """
                SELECT c.conname
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE n.nspname='public'
                  AND t.relname='inventory_operations'
                  AND c.contype='u'
                """
            )
            unique_names = {row[0] for row in cur.fetchall()}
        self.admin.rollback()
        self.assertEqual(found, expected)
        self.assertIn("uq_inventory_operations_command_line", unique_names)
        self.assertNotIn("inventory_operations_command_id_line_no_key", unique_names)
