from __future__ import annotations

import concurrent.futures
import unittest

from services.inventory_apply_service import StaleBalanceError
from tests.fase2d.helpers import valid_row
from tests.fase2e.helpers import approve_clean, phase2e_env


def count_row(total, **updates):
    data = valid_row(
        empaques_completos_contados=total // 4,
        unidades_sueltas_contadas=total % 4,
        cantidad_total_excel=total,
    )
    data.update(updates)
    return data


class ExistingProductApplyTest(unittest.TestCase):
    def test_19_authoritative_80_physical_75_delta_minus_5(self):
        with phase2e_env(rows=[count_row(75)]) as ctx:
            approved = approve_clean(ctx)
            row = approved["approved_plan"]["rows"][0]
            self.assertEqual(row["old_balance_scaled"], 80000)
            self.assertEqual(row["delta_scaled"], -5000)

    def test_20_stale_productos_stock_is_ignored(self):
        with phase2e_env(rows=[count_row(75)]) as ctx:
            conn = ctx.env.connect()
            try:
                conn.execute("UPDATE productos SET stock=999 WHERE local_id=?", (ctx.local_id,))
                conn.commit()
            finally:
                conn.close()
            row = approve_clean(ctx)["approved_plan"]["rows"][0]
            self.assertEqual(row["old_balance_scaled"], 80000)

    def test_21_no_difference_no_inventory_command(self):
        with phase2e_env(rows=[count_row(80)]) as ctx:
            approve_clean(ctx)
            progress = ctx.apply.apply_batch(ctx.batch_id)
            self.assertEqual(progress.state, "COMPLETED")
            self.assertEqual(ctx.gateway.calls, [])

    def test_22_positive_difference(self):
        with phase2e_env(rows=[count_row(85)]) as ctx:
            row = approve_clean(ctx)["approved_plan"]["rows"][0]
            self.assertEqual(row["delta_scaled"], 5000)

    def test_23_negative_difference(self):
        with phase2e_env(rows=[count_row(70)]) as ctx:
            row = approve_clean(ctx)["approved_plan"]["rows"][0]
            self.assertEqual(row["delta_scaled"], -10000)

    def test_24_metadata_unchanged_no_update_audit(self):
        with phase2e_env(rows=[count_row(75)]) as ctx:
            approve_clean(ctx)
            ctx.apply.apply_batch(ctx.batch_id)
            events = [item["event_type"] for item in ctx.repository.list_audit(ctx.batch_id)]
            self.assertNotIn("METADATA_APPLIED", events)

    def test_25_metadata_change_applies_only_after_approval(self):
        with phase2e_env(rows=[count_row(75, precio_venta=16000)]) as ctx:
            review = ctx.apply.build_review_plan(ctx.batch_id)
            blocker = next(item for item in review["blockers"] if item["reason"] == "METADATA_APPROVAL_REQUIRED")
            ctx.repository.decide_metadata(blocker["row_id"], "APPLY", fields=["precio_venta"], actor="ana")
            ctx.apply.approve_batch(ctx.batch_id, actor="ana")
            ctx.apply.apply_batch(ctx.batch_id, actor="ana")
            product = ctx.product_repo.obtener_por_id(ctx.repository.list_apply_rows(ctx.batch_id)[0]["producto_id"] or 1)
            self.assertEqual(float(product["precio_venta"]), 16000)

    def test_26_inventory_reason_and_adjustment_type(self):
        with phase2e_env(rows=[count_row(75)]) as ctx:
            approve_clean(ctx)
            ctx.apply.apply_batch(ctx.batch_id)
            self.assertEqual(ctx.gateway.payloads[0]["tipo"], "AJUSTE")
            audit = [item for item in ctx.repository.list_audit(ctx.batch_id) if item["event_type"] == "INVENTORY_COMMAND_RESULT"][0]
            self.assertIn("INVENTARIO_FISICO", audit["result_json"])

    def test_27_apply_reaches_verified_completion(self):
        with phase2e_env(rows=[count_row(75)]) as ctx:
            approve_clean(ctx)
            progress = ctx.apply.apply_batch(ctx.batch_id)
            self.assertEqual((progress.state, progress.verified), ("COMPLETED", 1))

    def test_28_inventory_readback_matches_physical(self):
        with phase2e_env(rows=[count_row(75)]) as ctx:
            approve_clean(ctx)
            ctx.apply.apply_batch(ctx.batch_id)
            self.assertEqual(ctx.gateway.balances[ctx.local_id], 75000)


class StaleBalanceTest(unittest.TestCase):
    def test_29_approve_uses_base_80(self):
        with phase2e_env(rows=[count_row(75)]) as ctx:
            row = approve_clean(ctx)["approved_plan"]["rows"][0]
            self.assertEqual(row["old_balance_scaled"], 80000)

    def test_30_authority_change_to_70_before_apply_rejected(self):
        with phase2e_env(rows=[count_row(75)]) as ctx:
            approve_clean(ctx)
            ctx.gateway.balances[ctx.local_id] = 70000
            with self.assertRaises(StaleBalanceError):
                ctx.apply.apply_batch(ctx.batch_id)

    def test_31_stale_preflight_has_zero_inventory_mutation(self):
        with phase2e_env(rows=[count_row(75)]) as ctx:
            approve_clean(ctx)
            ctx.gateway.balances[ctx.local_id] = 70000
            with self.assertRaises(StaleBalanceError):
                ctx.apply.apply_batch(ctx.batch_id)
            self.assertEqual(ctx.gateway.calls, [])

    def test_32_stale_returns_batch_to_review(self):
        with phase2e_env(rows=[count_row(75)]) as ctx:
            approve_clean(ctx)
            ctx.gateway.balances[ctx.local_id] = 70000
            with self.assertRaises(StaleBalanceError):
                ctx.apply.apply_batch(ctx.batch_id)
            self.assertEqual(ctx.repository.get_apply_batch(ctx.batch_id)["workflow_state"], "REVIEW_REQUIRED")

    def test_33_new_plan_recalculates_and_requires_reapproval(self):
        with phase2e_env(rows=[count_row(75)]) as ctx:
            approve_clean(ctx)
            ctx.gateway.balances[ctx.local_id] = 70000
            with self.assertRaises(StaleBalanceError):
                ctx.apply.apply_batch(ctx.batch_id)
            review = ctx.apply.build_review_plan(ctx.batch_id)
            self.assertEqual(review["rows"][0]["delta_scaled"], 5000)
            self.assertNotEqual(ctx.repository.get_apply_batch(ctx.batch_id)["workflow_state"], "APPROVED")


class NewProductApplyTest(unittest.TestCase):
    def test_34_new_product_uses_canonical_service(self):
        with phase2e_env(rows=[count_row(40, nombre="Producto nuevo 2E")], create_existing=False) as ctx:
            approve_clean(ctx)
            ctx.apply.apply_batch(ctx.batch_id)
            self.assertIsNotNone(ctx.repository.list_apply_rows(ctx.batch_id)[0]["producto_id"])

    def test_35_new_product_gets_system_local_id(self):
        with phase2e_env(rows=[count_row(40, nombre="Producto local id")], create_existing=False) as ctx:
            approved = approve_clean(ctx)
            self.assertTrue(approved["approved_plan"]["rows"][0]["producto_local_id"])

    def test_36_excel_id_not_required(self):
        with phase2e_env(rows=[count_row(40, nombre="Sin excel id")], create_existing=False) as ctx:
            self.assertNotIn("producto_local_id", ctx.imported.rows[0]["normalized_payload"])
            self.assertEqual(approve_clean(ctx)["workflow_state"], "APPROVED")

    def test_37_physical_count_is_initial_inventory(self):
        with phase2e_env(rows=[count_row(40, nombre="Inicial 40")], create_existing=False) as ctx:
            row = approve_clean(ctx)["approved_plan"]["rows"][0]
            self.assertEqual((row["old_balance_scaled"], row["delta_scaled"]), (0, 40000))

    def test_38_new_inventory_uses_gateway(self):
        with phase2e_env(rows=[count_row(40, nombre="Gateway nuevo")], create_existing=False) as ctx:
            approve_clean(ctx)
            ctx.apply.apply_batch(ctx.batch_id)
            self.assertEqual(len(ctx.gateway.calls), 1)

    def test_39_no_direct_authoritative_product_stock_write(self):
        with phase2e_env(rows=[count_row(40, nombre="Stock cero local")], create_existing=False) as ctx:
            approve_clean(ctx)
            ctx.apply.apply_batch(ctx.batch_id)
            row = ctx.repository.list_apply_rows(ctx.batch_id)[0]
            product = ctx.product_repo.obtener_por_id(row["producto_id"])
            self.assertEqual(float(product["stock"]), 0)

    def test_40_barcode_pending_allowed(self):
        with phase2e_env(rows=[count_row(40, nombre="Pending")], create_existing=False) as ctx:
            approve_clean(ctx)
            ctx.apply.apply_batch(ctx.batch_id)
            row = ctx.repository.list_apply_rows(ctx.batch_id)[0]
            self.assertEqual(ctx.product_repo.obtener_por_id(row["producto_id"])["barcode_status"], "BARCODE_PENDING")

    def test_41_no_frp_auto_generated(self):
        with phase2e_env(rows=[count_row(40, nombre="Sin FRP")], create_existing=False) as ctx:
            approve_clean(ctx)
            ctx.apply.apply_batch(ctx.batch_id)
            row = ctx.repository.list_apply_rows(ctx.batch_id)[0]
            product = ctx.product_repo.obtener_por_id(row["producto_id"])
            self.assertFalse(str(product.get("codigo_barras") or "").startswith("FRP-"))

    def test_42_excel_barcode_candidate_not_persisted(self):
        barcode = "0012345678905"
        row = count_row(40, nombre="Barcode candidato", barcode_primero=barcode, barcode_segundo=barcode)
        with phase2e_env(rows=[row], create_existing=False) as ctx:
            ctx.repository.acknowledge_batch_warnings(ctx.batch_id, actor="ana")
            approve_clean(ctx)
            ctx.apply.apply_batch(ctx.batch_id)
            applied = ctx.repository.list_apply_rows(ctx.batch_id)[0]
            product = ctx.product_repo.obtener_por_id(applied["producto_id"])
            self.assertNotEqual(product.get("codigo_barras"), barcode)
            conn = ctx.env.connect()
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM product_barcodes WHERE barcode=?", (barcode,)).fetchone()[0], 0)
            finally:
                conn.close()

    def test_43_packaging_and_sales_forms_preserved(self):
        with phase2e_env(rows=[count_row(40, nombre="Empaque durable")], create_existing=False) as ctx:
            approve_clean(ctx)
            ctx.apply.apply_batch(ctx.batch_id)
            applied = ctx.repository.list_apply_rows(ctx.batch_id)[0]
            product = ctx.product_repo.obtener_por_id(applied["producto_id"])
            self.assertEqual(product["unidades_por_caja"], 4)
            self.assertIn("Empaque completo", product["unidades_venta_custom"])


class IdempotencyRecoveryTest(unittest.TestCase):
    def test_44_double_click_one_application(self):
        with phase2e_env(rows=[count_row(75)]) as ctx:
            approve_clean(ctx)
            ctx.apply.apply_batch(ctx.batch_id)
            with self.assertRaises(Exception):
                ctx.apply.apply_batch(ctx.batch_id)
            self.assertEqual(len(ctx.gateway.commands), 1)

    def test_45_same_retry_uses_same_command_id(self):
        with phase2e_env(rows=[count_row(75)]) as ctx:
            approved = approve_clean(ctx)
            command = approved["approved_plan"]["rows"][0]["inventory_command_id"]
            ctx.gateway.unknown_once.add(command)
            ctx.apply.apply_batch(ctx.batch_id)
            ctx.apply.apply_batch(ctx.batch_id)
            self.assertEqual({call[0] for call in ctx.gateway.calls}, {command})

    def test_46_timeout_unknown_restart_exactly_once_balance(self):
        with phase2e_env(rows=[count_row(75)]) as ctx:
            approved = approve_clean(ctx)
            command = approved["approved_plan"]["rows"][0]["inventory_command_id"]
            ctx.gateway.unknown_once.add(command)
            first = ctx.apply.apply_batch(ctx.batch_id)
            self.assertEqual(first.unknown, 1)
            second = ctx.apply.apply_batch(ctx.batch_id)
            self.assertEqual(second.state, "COMPLETED")
            self.assertEqual(ctx.gateway.balances[ctx.local_id], 75000)
            self.assertEqual(len(ctx.gateway.commands), 1)

    def test_47_new_product_not_created_twice_on_unknown(self):
        with phase2e_env(rows=[count_row(40, nombre="Nuevo retry")], create_existing=False) as ctx:
            approved = approve_clean(ctx)
            command = approved["approved_plan"]["rows"][0]["inventory_command_id"]
            ctx.gateway.unknown_once.add(command)
            ctx.apply.apply_batch(ctx.batch_id)
            ctx.apply.apply_batch(ctx.batch_id)
            conn = ctx.env.connect()
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM productos WHERE nombre='Nuevo retry'").fetchone()[0], 1)
            finally:
                conn.close()

    def test_48_completed_rows_not_reapplied_after_partial_failure(self):
        rows = [count_row(10, nombre="Nuevo A"), count_row(20, nombre="Nuevo B")]
        with phase2e_env(rows=rows, create_existing=False) as ctx:
            approve_clean(ctx)
            ctx.gateway.reject_call = 2
            first = ctx.apply.apply_batch(ctx.batch_id)
            self.assertEqual(first.state, "PARTIALLY_FAILED")
            first_command = ctx.gateway.calls[0][0]
            ctx.gateway.reject_call = None
            second = ctx.apply.apply_batch(ctx.batch_id)
            self.assertEqual(second.state, "COMPLETED")
            self.assertEqual(sum(call[0] == first_command for call in ctx.gateway.calls), 1)

    def test_49_partial_batch_not_falsely_completed(self):
        rows = [count_row(10, nombre="Parcial A"), count_row(20, nombre="Parcial B")]
        with phase2e_env(rows=rows, create_existing=False) as ctx:
            approve_clean(ctx)
            ctx.gateway.reject_call = 2
            progress = ctx.apply.apply_batch(ctx.batch_id)
            self.assertEqual(progress.state, "PARTIALLY_FAILED")
            self.assertEqual(progress.verified, 1)

    def test_50_wrong_readback_prevents_verified(self):
        with phase2e_env(rows=[count_row(75)]) as ctx:
            approve_clean(ctx)
            ctx.gateway.wrong_readback = True
            progress = ctx.apply.apply_batch(ctx.batch_id)
            self.assertEqual(progress.state, "PARTIALLY_FAILED")
            self.assertEqual(progress.verified, 0)

    def test_51_audit_record_exists(self):
        with phase2e_env(rows=[count_row(75)]) as ctx:
            approve_clean(ctx)
            ctx.apply.apply_batch(ctx.batch_id, actor="ana")
            events = {item["event_type"] for item in ctx.repository.list_audit(ctx.batch_id)}
            self.assertTrue({"BATCH_APPROVED", "INVENTORY_COMMAND_RESULT", "ROW_VERIFIED"}.issubset(events))

    def test_52_row_command_identity_persisted_before_apply(self):
        with phase2e_env(rows=[count_row(75)]) as ctx:
            approve_clean(ctx)
            row = ctx.repository.list_apply_rows(ctx.batch_id)[0]
            self.assertTrue(row["inventory_command_id"])
            self.assertTrue(row["inventory_operation_id"])
            self.assertEqual(ctx.gateway.calls, [])

    def test_53_batch_apply_identity_persisted_before_apply(self):
        with phase2e_env(rows=[count_row(75)]) as ctx:
            batch = approve_clean(ctx)
            self.assertTrue(batch["apply_id"])
            self.assertEqual(ctx.gateway.calls, [])

    def test_54_concurrent_lease_only_one_winner(self):
        with phase2e_env(rows=[count_row(75)]) as ctx:
            approve_clean(ctx)
            def acquire(_):
                try:
                    return ctx.repository.acquire_apply_lease(ctx.batch_id)["lease_token"]
                except Exception:
                    return "CONFLICT"
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(acquire, (1, 2)))
            self.assertEqual(sum(item != "CONFLICT" for item in results), 1)


if __name__ == "__main__":
    unittest.main()
