from __future__ import annotations

import inspect
import uuid
import unittest

from inventory_ledger import (
    IdempotencyConflictError,
    command_request_hash,
    create_inventory_command,
)
from tests.fase0.harness import official_temp_db
from tests.fase1e.helpers import seed_producto


class ExpectedBaseIdentityUnitTest(unittest.TestCase):
    def _payload(self, expected_marker):
        command_id = "11111111-1111-4111-8111-111111111111"
        operation = {
            "operation_id": "22222222-2222-4222-8222-222222222222",
            "producto_local_id": "33333333-3333-4333-8333-333333333333",
            "line_no": 1,
            "delta_scaled": -1000,
        }
        if expected_marker != "ABSENT":
            operation["expected_base_scaled"] = expected_marker
        return command_id, [operation]

    def _hash(self, expected_marker):
        command_id, operations = self._payload(expected_marker)
        return command_request_hash(
            command_id=command_id,
            tipo="AJUSTE",
            documento_tipo="ajuste",
            documento_local_id=None,
            operations=operations,
        )

    def test_absent_null_zero_and_other_have_correct_identity(self):
        self.assertEqual(self._hash("ABSENT"), self._hash(None))
        self.assertNotEqual(self._hash(None), self._hash(0))
        self.assertNotEqual(self._hash(0), self._hash(50000))
        self.assertNotEqual(self._hash(50000), self._hash(40000))

    def test_persisted_changed_expected_base_is_conflict(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                lid = seed_producto(conn, env, stock=50)
                command_id = str(uuid.uuid4())
                operation_id = str(uuid.uuid4())
                common = {
                    "command_id": command_id,
                    "tipo": "AJUSTE",
                    "documento_tipo": "ajuste",
                    "intent_class": "AUTHORITATIVE",
                }
                create_inventory_command(
                    conn,
                    operations=[{
                        "operation_id": operation_id,
                        "producto_local_id": lid,
                        "line_no": 1,
                        "delta_scaled": -1000,
                        "expected_base_scaled": 50000,
                    }],
                    **common,
                )
                conn.commit()
                with self.assertRaises(IdempotencyConflictError):
                    create_inventory_command(
                        conn,
                        operations=[{
                            "operation_id": operation_id,
                            "producto_local_id": lid,
                            "line_no": 1,
                            "delta_scaled": -1000,
                            "expected_base_scaled": 40000,
                        }],
                        **common,
                    )
            finally:
                conn.close()

    def test_w08_w13_w17_use_common_absolute_identity_guard(self):
        from repositories.inventario_repository import InventarioRepository
        from repositories.productos_repo import ProductosRepository
        from services.ventas_service import VentasService

        absolute_sources = (
            inspect.getsource(ProductosRepository._actualizar_producto_authoritative),
            inspect.getsource(InventarioRepository._ajustar_stock_directo_authoritative),
        )
        for source in absolute_sources:
            self.assertIn("expected_base", source)
            self.assertIn("command_already_applied", source)
            self.assertIn("operations=operations", source)
        w17 = inspect.getsource(VentasService._editar_linea_factura_authoritative)
        self.assertIn("command_already_applied", w17)
        self.assertIn("operations=operations", w17)


if __name__ == "__main__":
    unittest.main()
