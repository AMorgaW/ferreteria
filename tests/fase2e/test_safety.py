from __future__ import annotations

import inspect
import unittest
from pathlib import Path

from services.inventory_apply_service import InventoryImportApplyService
from tests.fase2d.helpers import valid_row
from tests.fase2e.helpers import approve_clean, phase2e_env


class Phase2ESafetyTest(unittest.TestCase):
    def test_55_dry_run_zero_mutation(self):
        with phase2e_env() as ctx:
            before_products = len(ctx.repository.list_products())
            before_balances = dict(ctx.gateway.balances)
            ctx.apply.build_review_plan(ctx.batch_id)
            self.assertEqual(len(ctx.repository.list_products()), before_products)
            self.assertEqual(ctx.gateway.balances, before_balances)
            self.assertEqual(ctx.gateway.calls, [])

    def test_56_preview_zero_mutation(self):
        with phase2e_env() as ctx:
            before = dict(ctx.gateway.balances)
            rows = ctx.repository.list_rows(ctx.batch_id)
            self.assertTrue(rows)
            self.assertEqual(ctx.gateway.balances, before)

    def test_57_malformed_batch_cannot_apply(self):
        with phase2e_env(rows=[valid_row(precio_compra="mal")], create_existing=False) as ctx:
            with self.assertRaises(Exception):
                ctx.apply.approve_batch(ctx.batch_id)
            with self.assertRaises(Exception):
                ctx.apply.apply_batch(ctx.batch_id)
            self.assertEqual(ctx.gateway.calls, [])

    def test_58_unapproved_batch_cannot_apply(self):
        with phase2e_env() as ctx:
            ctx.repository.ensure_apply_controls(ctx.batch_id)
            with self.assertRaises(Exception):
                ctx.apply.apply_batch(ctx.batch_id)
            self.assertEqual(ctx.gateway.calls, [])

    def test_59_no_supabase_reference_in_apply_engine(self):
        source = inspect.getsource(InventoryImportApplyService).casefold()
        self.assertNotIn("supabase", source)
        self.assertNotIn("service_role", source)

    def test_60_no_direct_product_stock_sql_in_apply_engine(self):
        source = inspect.getsource(InventoryImportApplyService).casefold()
        self.assertNotIn("update productos set stock", source)
        self.assertNotIn("insert into inventory_balances", source)

    def test_61_no_barcode_assignment_in_apply_engine(self):
        source = inspect.getsource(InventoryImportApplyService).casefold()
        self.assertNotIn("assign_in_connection", source)
        self.assertNotIn("generate_frp", source)

    def test_62_fixture_database_only(self):
        with phase2e_env() as ctx:
            real = Path(__file__).resolve().parents[2] / "ferreteria.db"
            self.assertNotEqual(ctx.env.db_path.resolve(), real.resolve())
            self.assertIn("ferrepro-fase0", str(ctx.env.db_path))

    def test_63_readback_verifies_metadata(self):
        with phase2e_env(rows=[valid_row(precio_venta=16000)]) as ctx:
            review = ctx.apply.build_review_plan(ctx.batch_id)
            blocker = next(item for item in review["blockers"] if item["reason"] == "METADATA_APPROVAL_REQUIRED")
            ctx.repository.decide_metadata(blocker["row_id"], "APPLY", fields=["precio_venta"], actor="ana")
            ctx.apply.approve_batch(ctx.batch_id, actor="ana")
            result = ctx.apply.apply_batch(ctx.batch_id, actor="ana")
            self.assertEqual(result.state, "COMPLETED")

    def test_64_audit_has_balance_and_actor(self):
        row = valid_row(
            empaques_completos_contados=18,
            unidades_sueltas_contadas=3,
            cantidad_total_excel=75,
        )
        with phase2e_env(rows=[row]) as ctx:
            approve_clean(ctx)
            ctx.apply.apply_batch(ctx.batch_id, actor="ana")
            audit = ctx.repository.list_audit(ctx.batch_id)
            command = next(item for item in audit if item["event_type"] == "INVENTORY_COMMAND_RESULT")
            self.assertEqual(command["actor"], "ana")
            self.assertIn("old_balance_scaled", command["result_json"])
            self.assertTrue(command["inventory_command_id"])

    def test_65_completed_requires_every_row_verified(self):
        rows = [valid_row(nombre="Nuevo seguro A"), valid_row(nombre="Nuevo seguro B")]
        with phase2e_env(rows=rows, create_existing=False) as ctx:
            approve_clean(ctx)
            ctx.gateway.reject_call = 2
            result = ctx.apply.apply_batch(ctx.batch_id)
            self.assertNotEqual(result.state, "COMPLETED")
            self.assertLess(result.verified, result.total)

    def test_66_expected_base_sent_to_gateway(self):
        row = valid_row(
            empaques_completos_contados=18,
            unidades_sueltas_contadas=3,
            cantidad_total_excel=75,
        )
        with phase2e_env(rows=[row]) as ctx:
            approve_clean(ctx)
            ctx.apply.apply_batch(ctx.batch_id)
            operation = ctx.gateway.calls[0][1]
            self.assertEqual(operation["expected_base_scaled"], 80000)

    def test_69_new_product_waits_for_central_sync_before_rpc(self):
        with phase2e_env(rows=[valid_row(nombre="Espera sync")], create_existing=False) as ctx:
            approve_clean(ctx)
            real_path = InventoryImportApplyService(
                ctx.repository,
                product_repository=ctx.product_repo,
                authority_reader=lambda product_id: 0,
            )
            progress = real_path.apply_batch(ctx.batch_id)
            self.assertEqual(progress.state, "PARTIALLY_FAILED")
            row = ctx.repository.list_apply_rows(ctx.batch_id)[0]
            self.assertEqual(row["apply_state"], "FAILED_RETRYABLE")
            self.assertIn("PRODUCT_SYNC_PENDING", row["last_error"])
            self.assertEqual(ctx.gateway.calls, [])

    def test_70_stop_request_is_durable_without_rollback(self):
        with phase2e_env() as ctx:
            approve_clean(ctx)
            lease = ctx.repository.acquire_apply_lease(ctx.batch_id)
            ctx.repository.request_stop(ctx.batch_id, actor="ana")
            batch = ctx.repository.get_apply_batch(ctx.batch_id)
            self.assertEqual(batch["stop_requested"], 1)
            self.assertEqual(ctx.gateway.calls, [])
            ctx.repository.finish_apply(
                ctx.batch_id, lease["lease_token"], "PARTIALLY_FAILED",
                error="STOP_REQUESTED",
            )

    def test_71_staging_is_locked_during_apply(self):
        with phase2e_env() as ctx:
            approve_clean(ctx)
            ctx.repository.acquire_apply_lease(ctx.batch_id)
            row_id = ctx.imported.rows[0]["row_id"]
            conn = ctx.env.connect()
            try:
                with self.assertRaises(Exception) as caught:
                    conn.execute(
                        "UPDATE inventory_import_rows SET cantidad_contada_scaled=1 WHERE row_id=?",
                        (row_id,),
                    )
                self.assertIn("STAGING_LOCKED_DURING_APPLY", str(caught.exception))
            finally:
                conn.rollback()
                conn.close()


if __name__ == "__main__":
    unittest.main()
