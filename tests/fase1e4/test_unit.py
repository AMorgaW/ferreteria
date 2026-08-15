# -*- coding: utf-8 -*-
"""1E.4 unitario: snapshot, contrato productivo, sin tests/ en cutover."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase0.harness import official_temp_db
from tests.fase0.stock_writers import GATEWAY_PREPARED_IDS
from tests.fase1e.helpers import seed_producto


class WriterContractUnitTest(unittest.TestCase):
    def test_cutover_no_importa_tests(self):
        src = (REPO_ROOT / "inventory_cutover.py").read_text(encoding="utf-8")
        self.assertNotIn("from tests.", src)
        self.assertNotIn("import tests.", src)
        self.assertNotIn("scan_stock_writes_by_function", src)

    def test_contract_matches_scanner_inventory(self):
        from inventory_writer_contract import (
            CUTOVER_READY,
            EXPECTED_PREPARED_COUNT,
            PREPARED_DIRECT_WRITER_IDS,
        )

        self.assertTrue(CUTOVER_READY)
        self.assertEqual(len(PREPARED_DIRECT_WRITER_IDS), EXPECTED_PREPARED_COUNT)
        self.assertEqual(PREPARED_DIRECT_WRITER_IDS, GATEWAY_PREPARED_IDS)

    def test_verify_preconditions_uses_contract(self):
        from inventory_cutover import verify_preconditions

        with official_temp_db() as env:
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=1)
                failures = verify_preconditions(
                    conn, require_app_dsn=False, app_factory=None
                )
                self.assertFalse(
                    any("contrato writers" in f for f in failures), msg=repr(failures)
                )
            finally:
                conn.close()


class SnapshotUnitTest(unittest.TestCase):
    def test_snapshot_hash_identity(self):
        from inventory_cutover import build_cutover_snapshot, snapshot_checksum

        a = build_cutover_snapshot(
            [("b" * 8 + "-aaaa-4aaa-8aaa-aaaaaaaaaaaa", 1000),
             ("a" * 8 + "-aaaa-4aaa-8aaa-aaaaaaaaaaaa", 2000)],
            epoch=0,
            cutover_id="11111111-1111-4111-8111-111111111111",
        )
        b = build_cutover_snapshot(
            [("a" * 8 + "-aaaa-4aaa-8aaa-aaaaaaaaaaaa", 2000),
             ("b" * 8 + "-aaaa-4aaa-8aaa-aaaaaaaaaaaa", 1000)],
            epoch=0,
            cutover_id="11111111-1111-4111-8111-111111111111",
        )
        self.assertEqual(a.checksum, b.checksum)
        self.assertEqual(a.quantity_identity(), b.quantity_identity())
        identity = {
            "cutover_id": a.cutover_id,
            "epoch": a.epoch,
            "source": a.source,
            "lines": [
                {
                    "producto_local_id": line.producto_local_id,
                    "quantity_scaled": line.quantity_scaled,
                }
                for line in a.lines
            ],
        }
        self.assertEqual(snapshot_checksum(identity), a.checksum)
        mutated = build_cutover_snapshot(
            [("a" * 8 + "-aaaa-4aaa-8aaa-aaaaaaaaaaaa", 1)],
            epoch=0,
            cutover_id=a.cutover_id,
        )
        self.assertNotEqual(mutated.checksum, a.checksum)

    def test_unsafe_rollback_does_not_write_failed(self):
        src = (REPO_ROOT / "inventory_cutover.py").read_text(encoding="utf-8")
        self.assertNotRegex(src, r"status\s*=\s*STATUS_FAILED")

    def test_open_act_survives_new_connection(self):
        from inventory_cutover import (
            ACT_KIND_POS_CHECKOUT,
            begin_or_resume_open_act,
            complete_open_act,
        )

        with official_temp_db() as env:
            conn = env.connect()
            try:
                first = begin_or_resume_open_act(conn, ACT_KIND_POS_CHECKOUT)
            finally:
                conn.close()
            conn2 = env.connect()
            try:
                resumed = begin_or_resume_open_act(conn2, ACT_KIND_POS_CHECKOUT)
                self.assertEqual(resumed, first)
                complete_open_act(conn2, ACT_KIND_POS_CHECKOUT)
                second = begin_or_resume_open_act(conn2, ACT_KIND_POS_CHECKOUT)
                self.assertNotEqual(second, first)
            finally:
                conn2.close()


if __name__ == "__main__":
    unittest.main()
