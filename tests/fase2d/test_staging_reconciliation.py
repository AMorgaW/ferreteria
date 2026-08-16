from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from inventory_excel_importer import InventoryWorkbookError
from inventory_import_schema import ensure_inventory_import_schema
from migration_runner import Migration, MigrationError, MigrationRunner
from repositories.inventory_import_repository import InventoryImportRepository
from repositories.inventory_import_repository import InventoryAuthorityUnavailable
from services.inventory_import_service import InventoryImportService
from tests.fase2d.helpers import insert_product, make_connection, valid_row, write_workbook


class StagingReconciliationPhase2DTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.conn = make_connection()
        self.repo = InventoryImportRepository(self.conn)
        self.service = InventoryImportService(self.repo)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def stage(self, rows, name="inventory.xlsx"):
        return self.service.import_to_staging(write_workbook(self.root / name, rows))

    def test_23_verified_existing_barcode_drives_exact_match(self):
        local_id = insert_product(self.conn)
        self.conn.execute(
            "INSERT INTO product_barcodes(local_id, producto_local_id, barcode, active) VALUES ('b1', ?, '0012345', 1)",
            (local_id,),
        )
        self.conn.commit()
        result = self.stage([valid_row(nombre="Nombre distinto", barcode_primero="0012345", barcode_segundo="0012345")])
        row = result.rows[0]
        self.assertEqual(row["match_status"], "MATCH_EXACT")
        self.assertEqual(row["matched_producto_local_id"], local_id)
        self.assertEqual(row["barcode_status"], "BARCODE_EXCEL_CANDIDATE")

    def test_26_existing_product_strong_identity_exact_match(self):
        local_id = insert_product(self.conn)
        row = self.stage([valid_row()]).rows[0]
        self.assertEqual(row["match_status"], "MATCH_EXACT")
        self.assertEqual(row["matched_producto_local_id"], local_id)

    def test_27_duplicate_strong_identity_is_ambiguous(self):
        insert_product(self.conn)
        insert_product(self.conn, local_id="22222222-2222-4222-8222-222222222222")
        self.assertEqual(self.stage([valid_row()]).rows[0]["match_status"], "AMBIGUOUS")

    def test_28_unmatched_valid_row_is_new_product(self):
        row = self.stage([valid_row(nombre="Producto totalmente nuevo")]).rows[0]
        self.assertEqual(row["match_status"], "NEW_PRODUCT")
        self.assertIsNone(row["matched_producto_local_id"])

    def test_candidate_name_is_never_auto_merged(self):
        insert_product(self.conn, name="Martillo profesional grande")
        row = self.stage([valid_row(nombre="Martillo profesional gran")]).rows[0]
        self.assertEqual(row["match_status"], "MATCH_CANDIDATE")

    def test_barcode_product_conflict_is_blocking(self):
        owner = insert_product(self.conn, name="Alicate", brand="MARCA A")
        target = insert_product(self.conn, local_id="22222222-2222-4222-8222-222222222222")
        self.conn.execute(
            "INSERT INTO product_barcodes(local_id, producto_local_id, barcode, active) VALUES ('b1', ?, '999', 1)",
            (owner,),
        )
        self.conn.commit()
        row = self.stage([valid_row(barcode_primero="999", barcode_segundo="999")]).rows[0]
        self.assertEqual(row["match_status"], "AMBIGUOUS")
        self.assertEqual(row["barcode_status"], "CONFLICT_BARCODE_PRODUCT")
        self.assertEqual(row["validation_status"], "ERROR")
        self.assertEqual(target, "22222222-2222-4222-8222-222222222222")

    def test_31_same_file_sha_reuses_batch(self):
        path = write_workbook(self.root / "same.xlsx", [valid_row(nombre="Nuevo")])
        first = self.service.import_to_staging(path)
        second = self.service.import_to_staging(path)
        self.assertEqual(first.batch.batch_id, second.batch.batch_id)
        self.assertTrue(second.batch.reused)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM inventory_import_batches").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM inventory_import_rows").fetchone()[0], 1)

    def test_changed_file_creates_a_new_batch(self):
        first = self.stage([valid_row(nombre="Nuevo A")], "a.xlsx")
        second = self.stage([valid_row(nombre="Nuevo B")], "b.xlsx")
        self.assertNotEqual(first.batch.batch_id, second.batch.batch_id)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM inventory_import_batches").fetchone()[0], 2)

    def test_33_staging_persists_after_restart(self):
        db = self.root / "stage.db"
        conn = make_connection(db)
        service = InventoryImportService(InventoryImportRepository(conn))
        result = service.import_to_staging(write_workbook(self.root / "persist.xlsx", [valid_row(nombre="Nuevo")]))
        batch_id = result.batch.batch_id
        conn.close()
        reopened = sqlite3.connect(db)
        reopened.row_factory = sqlite3.Row
        try:
            rows = InventoryImportRepository(reopened).list_rows(batch_id)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["normalized_payload"]["nombre"], "Nuevo")
        finally:
            reopened.close()

    def test_34_35_36_preview_mutates_no_catalog_stock_or_barcode(self):
        local_id = insert_product(self.conn, stock=12)
        before = {
            "products": self.conn.execute("SELECT COUNT(*) FROM productos").fetchone()[0],
            "stock": self.conn.execute("SELECT stock FROM productos WHERE local_id=?", (local_id,)).fetchone()[0],
            "barcodes": self.conn.execute("SELECT COUNT(*) FROM product_barcodes").fetchone()[0],
        }
        self.stage([valid_row(barcode_primero="0012345", barcode_segundo="0012345")])
        after = {
            "products": self.conn.execute("SELECT COUNT(*) FROM productos").fetchone()[0],
            "stock": self.conn.execute("SELECT stock FROM productos WHERE local_id=?", (local_id,)).fetchone()[0],
            "barcodes": self.conn.execute("SELECT COUNT(*) FROM product_barcodes").fetchone()[0],
        }
        self.assertEqual(after, before)

    def test_37_38_authoritative_reconciliation_ignores_stale_product_stock(self):
        local_id = insert_product(self.conn, stock=100, presentation="SIN EMPAQUE")
        self.conn.execute("CREATE TABLE inventory_cutover_control(id INTEGER PRIMARY KEY, status TEXT)")
        self.conn.execute("INSERT INTO inventory_cutover_control(id,status) VALUES(1,'AUTHORITATIVE')")
        self.conn.execute("CREATE TABLE inventory_balances(producto_local_id TEXT PRIMARY KEY, quantity_scaled INTEGER NOT NULL)")
        self.conn.execute("INSERT INTO inventory_balances VALUES(?, 80000)", (local_id,))
        self.conn.commit()
        result = self.stage([
            valid_row(presentacion_empaque="SIN EMPAQUE", cantidad_base_por_empaque=None, empaques_completos_contados=0, unidades_sueltas_contadas=75, cantidad_total_excel=75)
        ])
        plan = self.service.dry_run(result.batch.batch_id)
        adjustment = plan.inventory_adjustments[0]
        self.assertEqual(adjustment["current_quantity_scaled"], 80000)
        self.assertEqual(adjustment["delta_scaled"], -5000)
        self.assertEqual(adjustment["authority_source"], "inventory_balances")

    def test_authoritative_without_balance_source_fails_closed(self):
        insert_product(self.conn)
        self.conn.execute("CREATE TABLE inventory_cutover_control(id INTEGER PRIMARY KEY, status TEXT)")
        self.conn.execute("INSERT INTO inventory_cutover_control(id,status) VALUES(1,'AUTHORITATIVE')")
        self.conn.commit()
        result = self.stage([valid_row()])
        with self.assertRaises(InventoryAuthorityUnavailable):
            self.service.dry_run(result.batch.batch_id)

    def test_39_new_product_proposes_initial_balance_without_creation(self):
        result = self.stage([
            valid_row(nombre="Producto nuevo", presentacion_empaque="SIN EMPAQUE", cantidad_base_por_empaque=None, empaques_completos_contados=0, unidades_sueltas_contadas=40, cantidad_total_excel=40)
        ])
        before = self.conn.execute("SELECT COUNT(*) FROM productos").fetchone()[0]
        plan = self.service.dry_run(result.batch.batch_id)
        proposal = plan.new_products[0]
        self.assertEqual(proposal["balance_action"], "PROPOSE_INITIAL_BALANCE")
        self.assertEqual(proposal["initial_balance_scaled"], 40000)
        self.assertIsNone(proposal["producto_local_id"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM productos").fetchone()[0], before)

    def test_40_existing_product_proposes_adjustment_not_purchase(self):
        insert_product(self.conn, stock=50, presentation="SIN EMPAQUE")
        result = self.stage([
            valid_row(presentacion_empaque="SIN EMPAQUE", cantidad_base_por_empaque=None, empaques_completos_contados=0, unidades_sueltas_contadas=47, cantidad_total_excel=47)
        ])
        adjustment = self.service.dry_run(result.batch.batch_id).inventory_adjustments[0]
        self.assertEqual(adjustment["action"], "PROPOSE_INVENTORY_ADJUSTMENT")
        self.assertEqual(adjustment["delta_scaled"], -3000)

    def test_41_dry_run_has_zero_mutations(self):
        insert_product(self.conn, stock=50)
        result = self.stage([valid_row()])
        before_changes = self.conn.total_changes
        before_stock = self.conn.execute("SELECT stock FROM productos").fetchone()[0]
        self.service.dry_run(result.batch.batch_id)
        self.assertEqual(self.conn.total_changes, before_changes)
        self.assertEqual(self.conn.execute("SELECT stock FROM productos").fetchone()[0], before_stock)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM product_barcodes").fetchone()[0], 0)

    def test_barcode_excel_candidate_is_never_persisted(self):
        result = self.stage([valid_row(nombre="Nuevo", barcode_primero="0012345", barcode_segundo="0012345")])
        plan = self.service.dry_run(result.batch.batch_id)
        self.assertEqual(plan.barcode_candidates[0]["candidate"], "0012345")
        self.assertEqual(plan.barcode_candidates[0]["status"], "BARCODE_EXCEL_CANDIDATE")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM product_barcodes").fetchone()[0], 0)

    def test_malformed_workbook_leaves_no_partial_staging(self):
        bad = self.root / "bad.xlsx"
        bad.write_bytes(b"broken")
        with self.assertRaises(InventoryWorkbookError):
            self.service.import_to_staging(bad)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM inventory_import_batches").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM inventory_import_rows").fetchone()[0], 0)

    def test_42_staging_migration_rerun(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE productos(id INTEGER PRIMARY KEY, local_id TEXT UNIQUE)")
        try:
            migration = Migration("2d", "staging", "v1", ensure_inventory_import_schema)
            runner = MigrationRunner((migration,))
            self.assertEqual(runner.run(conn, dry_run=False)[0].status, "APPLIED")
            self.assertEqual(runner.run(conn, dry_run=False)[0].status, "SKIPPED_APPLIED")
        finally:
            conn.close()

    def test_43_partial_migration_rolls_back(self):
        conn = sqlite3.connect(":memory:")
        try:
            def fail(db):
                db.execute("CREATE TABLE partial_2d(id INTEGER)")
                raise RuntimeError("boom")
            with self.assertRaises(MigrationError):
                MigrationRunner((Migration("2d", "bad", "v1", fail),)).run(conn, dry_run=False)
            self.assertIsNone(conn.execute("SELECT 1 FROM sqlite_master WHERE name='partial_2d'").fetchone())
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
