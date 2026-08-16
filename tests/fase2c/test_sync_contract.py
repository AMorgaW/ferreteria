from __future__ import annotations

import unittest

from local_sync import build_remote_upsert_sql
from sync_registry import (
    entity_type_for,
    parents_of,
    pk_column,
    sync_tables,
    topo_order,
)


class BarcodeSyncContractTest(unittest.TestCase):
    def test_product_barcodes_uses_canonical_registry(self):
        self.assertIn("product_barcodes", sync_tables())
        self.assertEqual(entity_type_for("product_barcodes"), "product_barcode")
        self.assertEqual(pk_column("product_barcodes"), "local_id")
        self.assertEqual(parents_of("product_barcodes"), ())
        order = topo_order()
        self.assertLess(order.index("productos"), order.index("product_barcodes"))

    def test_remote_upsert_uses_local_id_not_barcode_as_identity(self):
        sql = build_remote_upsert_sql(
            "product_barcodes",
            ["local_id", "producto_local_id", "barcode", "active"],
        )
        self.assertIn("ON CONFLICT (local_id)", sql)
        self.assertIn("RETURNING local_id", sql)
        self.assertNotIn("ON CONFLICT (barcode)", sql)


if __name__ == "__main__":
    unittest.main()

