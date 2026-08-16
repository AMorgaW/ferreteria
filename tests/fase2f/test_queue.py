from __future__ import annotations

import json
import unittest

from repositories.barcode_queue_repo import (
    FILTER_LEGACY,
    FILTER_PENDING,
    FILTER_STAGING,
    FILTER_VERIFIED,
    BarcodeQueueRepository,
)
from repositories.product_barcodes_repo import ProductBarcodesRepository
from tests.fase2f.helpers import create_product, phase2c_env


class PendingQueueTest(unittest.TestCase):
    def test_01_pending_queue_has_one_db_derived_row_per_product(self):
        with phase2c_env() as env:
            _pid, lid = create_product(env, "Taladro")
            queue = BarcodeQueueRepository(env.db)
            rows = queue.list_queue(FILTER_PENDING)
            self.assertEqual([row.producto_local_id for row in rows], [lid])
            self.assertEqual(len({row.key for row in rows}), len(rows))

    def test_02_verified_product_leaves_pending_and_is_filterable(self):
        with phase2c_env() as env:
            _pid, lid = create_product(env, "Bombillo")
            ProductBarcodesRepository(env.db).assign_barcode(
                producto_local_id=lid, barcode="001770"
            )
            queue = BarcodeQueueRepository(env.db)
            self.assertNotIn(lid, [row.producto_local_id for row in queue.pending_products()])
            self.assertEqual(queue.list_queue(FILTER_VERIFIED)[0].primary_barcode, "001770")

    def test_03_legacy_filter_uses_persisted_status(self):
        with phase2c_env() as env:
            _pid, lid = create_product(env, "Legacy")
            conn = env.connect()
            try:
                conn.execute(
                    "UPDATE productos SET barcode_status='BARCODE_MISSING_LEGACY' WHERE local_id=?",
                    (lid,),
                )
                conn.commit()
            finally:
                conn.close()
            self.assertEqual(BarcodeQueueRepository(env.db).list_queue(FILTER_LEGACY)[0].key, lid)

    def test_04_staging_without_materialized_product_is_visible_once(self):
        with phase2c_env() as env:
            conn = env.connect()
            try:
                conn.execute(
                    "INSERT INTO inventory_import_batches(batch_id,source_filename,source_sha256,source_size_bytes,sheet_name,header_row,status) VALUES('b','x.xlsx','hash',1,'S',1,'READY')"
                )
                conn.execute(
                    """INSERT INTO inventory_import_rows(
                       row_id,batch_id,excel_row_number,normalized_payload,raw_payload,
                       match_status,barcode_status,barcode_candidate,validation_status,row_hash
                       ) VALUES('r','b',2,?, '{}','NEW_PRODUCT','BARCODE_EXCEL_CANDIDATE','EXCEL-1','VALID','rh')""",
                    (json.dumps({"nombre": "Martillo", "marca": "Acme"}),),
                )
                conn.commit()
            finally:
                conn.close()
            rows = BarcodeQueueRepository(env.db).list_queue(FILTER_STAGING)
            self.assertEqual([(row.key, row.excel_candidate) for row in rows], [("r", "EXCEL-1")])

    def test_05_search_covers_name_brand_category_and_exact_barcode(self):
        with phase2c_env() as env:
            _pid, lid = create_product(env, "Alicate")
            conn = env.connect()
            try:
                conn.execute("UPDATE productos SET marca='Truper', categoria='Manuales' WHERE local_id=?", (lid,))
                conn.commit()
            finally:
                conn.close()
            ProductBarcodesRepository(env.db).assign_barcode(producto_local_id=lid, barcode="AbC-007")
            queue = BarcodeQueueRepository(env.db)
            for search in ("alicate", "truper", "manuales", "AbC-007"):
                self.assertEqual(queue.list_queue(search=search)[0].producto_local_id, lid)

    def test_06_restart_rebuild_does_not_requeue_verified_product(self):
        with phase2c_env() as env:
            _pid, lid = create_product(env, "Restart")
            ProductBarcodesRepository(env.db).assign_barcode(producto_local_id=lid, barcode="RST-1")
            first = BarcodeQueueRepository(env.db)
            second = BarcodeQueueRepository(env.db)
            self.assertFalse(any(row.producto_local_id == lid for row in first.pending_products()))
            self.assertFalse(any(row.producto_local_id == lid for row in second.pending_products()))


if __name__ == "__main__":
    unittest.main()
