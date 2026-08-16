from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from inventory_apply_schema import ensure_inventory_apply_schema
from migration_runner import Migration, MigrationError, MigrationRunner
from services.inventory_apply_service import (
    ApprovalBlockedError,
    ApprovedPlanChangedError,
)
from tests.fase2d.helpers import valid_row
from tests.fase2e.helpers import approve_clean, phase2e_env


class ApprovalWorkflowTest(unittest.TestCase):
    def test_01_invalid_batch_cannot_approve(self):
        with phase2e_env(rows=[valid_row(precio_venta=-1)], create_existing=False) as ctx:
            with self.assertRaises(ApprovalBlockedError):
                ctx.apply.approve_batch(ctx.batch_id, actor="ana")

    def test_02_ambiguous_row_blocks_approval(self):
        with phase2e_env() as ctx:
            row = ctx.imported.rows[0]
            conn = ctx.env.connect()
            try:
                conn.execute("UPDATE inventory_import_rows SET match_status='AMBIGUOUS' WHERE row_id=?", (row["row_id"],))
                conn.commit()
            finally:
                conn.close()
            with self.assertRaises(ApprovalBlockedError):
                ctx.apply.approve_batch(ctx.batch_id)

    def test_03_candidate_match_requires_confirmation(self):
        with phase2e_env(rows=[valid_row(nombre="Martillo profesionall")]) as ctx:
            self.assertEqual(ctx.imported.rows[0]["match_status"], "MATCH_CANDIDATE")
            with self.assertRaises(ApprovalBlockedError):
                ctx.apply.approve_batch(ctx.batch_id)

    def test_04_confirmed_match_survives_restart(self):
        with phase2e_env(rows=[valid_row(nombre="Martillo profesionall")]) as ctx:
            row_id = ctx.imported.rows[0]["row_id"]
            ctx.repository.ensure_apply_controls(ctx.batch_id)
            ctx.repository.confirm_match(row_id, ctx.local_id, actor="ana")
            reopened = type(ctx.repository)(ctx.env.db)
            row = reopened.list_apply_rows(ctx.batch_id)[0]
            self.assertEqual(row["identity_resolution"], "CONFIRMED")
            self.assertEqual(row["resolved_producto_local_id"], ctx.local_id)

    def test_05_warning_requires_explicit_approval(self):
        with phase2e_env(rows=[valid_row(categoria="Otra")], create_existing=False) as ctx:
            conn = ctx.env.connect()
            try:
                conn.execute(
                    "UPDATE inventory_import_rows SET validation_status='WARNING', validation_warnings='[{\"code\":\"W\",\"message\":\"revise\"}]'"
                )
                conn.execute("UPDATE inventory_import_batches SET warning_count=1 WHERE batch_id=?", (ctx.batch_id,))
                conn.commit()
            finally:
                conn.close()
            with self.assertRaises(ApprovalBlockedError):
                ctx.apply.approve_batch(ctx.batch_id)
            ctx.repository.acknowledge_batch_warnings(ctx.batch_id, actor="ana")
            self.assertEqual(ctx.apply.approve_batch(ctx.batch_id)["workflow_state"], "APPROVED")

    def test_06_ready_batch_can_approve(self):
        with phase2e_env() as ctx:
            approved = approve_clean(ctx)
            self.assertEqual(approved["workflow_state"], "APPROVED")
            self.assertTrue(approved["approval_plan_hash"])

    def test_07_approved_plan_immutable(self):
        with phase2e_env() as ctx:
            approve_clean(ctx)
            conn = ctx.env.connect()
            try:
                conn.execute(
                    "UPDATE inventory_import_apply_batches SET approved_plan_json='{}' WHERE batch_id=?",
                    (ctx.batch_id,),
                )
                conn.commit()
            finally:
                conn.close()
            with self.assertRaises(ApprovedPlanChangedError):
                ctx.apply.final_preflight(ctx.batch_id)

    def test_08_staging_change_invalidates_approval(self):
        with phase2e_env() as ctx:
            approve_clean(ctx)
            row_id = ctx.imported.rows[0]["row_id"]
            conn = ctx.env.connect()
            try:
                conn.execute("UPDATE inventory_import_rows SET cantidad_contada_scaled=76000 WHERE row_id=?", (row_id,))
                conn.commit()
            finally:
                conn.close()
            batch = ctx.repository.get_apply_batch(ctx.batch_id)
            self.assertEqual(batch["workflow_state"], "REVIEW_REQUIRED")
            self.assertIsNone(batch["approval_id"])

    def test_09_metadata_change_requires_decision(self):
        with phase2e_env(rows=[valid_row(precio_venta=16000)]) as ctx:
            with self.assertRaises(ApprovalBlockedError) as caught:
                ctx.apply.approve_batch(ctx.batch_id)
            self.assertIn("METADATA_APPROVAL_REQUIRED", str(caught.exception))

    def test_10_metadata_keep_current_is_explicit_resolution(self):
        with phase2e_env(rows=[valid_row(precio_venta=16000)]) as ctx:
            blocker = ctx.apply.build_review_plan(ctx.batch_id)["blockers"][0]
            ctx.repository.decide_metadata(blocker["row_id"], "KEEP_CURRENT", actor="ana")
            approved = ctx.apply.approve_batch(ctx.batch_id, actor="ana")
            row = approved["approved_plan"]["rows"][0]
            self.assertEqual(row["metadata_decision"], "KEEP_CURRENT")

    def test_11_metadata_apply_fields_are_snapshotted(self):
        with phase2e_env(rows=[valid_row(precio_venta=16000)]) as ctx:
            blocker = ctx.apply.build_review_plan(ctx.batch_id)["blockers"][0]
            ctx.repository.decide_metadata(
                blocker["row_id"], "APPLY", fields=["precio_venta"], actor="ana"
            )
            row = ctx.apply.approve_batch(ctx.batch_id)["approved_plan"]["rows"][0]
            self.assertEqual(row["metadata_after"]["precio_venta"], 16000)

    def test_12_duplicate_candidate_unresolved_blocks(self):
        with phase2e_env() as ctx:
            row_id = ctx.imported.rows[0]["row_id"]
            conn = ctx.env.connect()
            try:
                conn.execute("UPDATE inventory_import_rows SET duplicate_candidate=1 WHERE row_id=?", (row_id,))
                conn.commit()
            finally:
                conn.close()
            ctx.repository.ensure_apply_controls(ctx.batch_id)
            with self.assertRaises(ApprovalBlockedError):
                ctx.apply.approve_batch(ctx.batch_id)

    def test_13_duplicate_resolution_is_durable(self):
        with phase2e_env() as ctx:
            row_id = ctx.imported.rows[0]["row_id"]
            conn = ctx.env.connect()
            try:
                conn.execute("UPDATE inventory_import_rows SET duplicate_candidate=1 WHERE row_id=?", (row_id,))
                conn.commit()
            finally:
                conn.close()
            ctx.repository.ensure_apply_controls(ctx.batch_id)
            ctx.repository.resolve_duplicate(row_id, "NOT_DUPLICATE", actor="ana")
            self.assertEqual(ctx.repository.list_apply_rows(ctx.batch_id)[0]["duplicate_resolution"], "NOT_DUPLICATE")

    def test_14_approval_alone_zero_inventory_mutation(self):
        with phase2e_env() as ctx:
            before = dict(ctx.gateway.balances)
            approve_clean(ctx)
            self.assertEqual(ctx.gateway.balances, before)
            self.assertEqual(ctx.gateway.calls, [])

    def test_15_cancel_before_apply(self):
        with phase2e_env() as ctx:
            approve_clean(ctx)
            ctx.apply.cancel_batch(ctx.batch_id, actor="ana")
            self.assertEqual(ctx.repository.get_apply_batch(ctx.batch_id)["workflow_state"], "CANCELLED")

    def test_16_unauthorized_transition_rejected(self):
        with phase2e_env() as ctx:
            ctx.repository.ensure_apply_controls(ctx.batch_id)
            with self.assertRaises(Exception):
                ctx.repository.finish_apply(ctx.batch_id, "wrong", "COMPLETED")

    def test_17_apply_migration_rerun(self):
        with phase2e_env() as ctx:
            conn = ctx.env.connect()
            try:
                runner = MigrationRunner((Migration("2e", "apply", "v1", ensure_inventory_apply_schema),))
                self.assertEqual(runner.run(conn, dry_run=False)[0].status, "APPLIED")
                self.assertEqual(runner.run(conn, dry_run=False)[0].status, "SKIPPED_APPLIED")
            finally:
                conn.close()

    def test_18_apply_migration_rollback(self):
        with phase2e_env() as ctx:
            conn = ctx.env.connect()
            try:
                def fail(connection):
                    connection.execute("CREATE TABLE fase2e_partial(id INTEGER)")
                    raise RuntimeError("boom")
                with self.assertRaises(MigrationError):
                    MigrationRunner((Migration("bad2e", "bad", "x", fail),)).run(conn, dry_run=False)
                self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='fase2e_partial'").fetchone())
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()

