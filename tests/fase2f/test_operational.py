from __future__ import annotations

import unittest

from repositories.barcode_queue_repo import BarcodeQueueItem, BarcodeQueueRepository
from repositories.product_barcodes_repo import BarcodeRecord, ProductBarcodesRepository
from services.barcode_regularization_service import (
    ContinuousRegularizationController,
    ScannerTrialSession,
    ScannerTrialState,
)
from services.barcode_service import BarcodeSaveState
from tests.fase2f.helpers import create_product, phase2c_env


class _Queue:
    def __init__(self, rows):
        self.rows = rows

    def list_queue(self, *_args):
        return list(self.rows)


class _ReadbackFailureRepository:
    def __init__(self):
        self.calls = []

    def assign_barcode(self, **kwargs):
        self.calls.append(kwargs)
        return BarcodeRecord("b", kwargs["producto_local_id"], kwargs["barcode"], "MANUFACTURER", "TEST", True, True)

    def get_by_local_id(self, _local_id):
        return None


class OperationalFlowTest(unittest.TestCase):
    def test_07_first_scan_never_persists(self):
        with phase2c_env() as env:
            _pid, lid = create_product(env, "Primero")
            controller = ContinuousRegularizationController(
                BarcodeQueueRepository(env.db), ProductBarcodesRepository(env.db)
            )
            controller.refresh_queue(); self.assertTrue(controller.select(lid))
            result = controller.submit_scan("000123")
            self.assertEqual(result.save_result.state, BarcodeSaveState.SCANNED)
            self.assertEqual(ProductBarcodesRepository(env.db).list_for_product(lid), [])

    def test_08_matching_second_scan_persists_and_reads_back(self):
        with phase2c_env() as env:
            _pid, lid = create_product(env, "Confirmado")
            repo = ProductBarcodesRepository(env.db)
            controller = ContinuousRegularizationController(BarcodeQueueRepository(env.db), repo)
            controller.refresh_queue(); controller.select(lid)
            controller.submit_scan("00123")
            result = controller.submit_scan("00123")
            self.assertEqual(result.save_result.state, BarcodeSaveState.PERSISTENCE_VERIFIED)
            self.assertEqual(repo.get_by_barcode("00123").barcode, "00123")

    def test_09_mismatch_has_zero_persistence_and_no_advance(self):
        with phase2c_env() as env:
            _pid, lid = create_product(env, "Mismatch")
            repo = ProductBarcodesRepository(env.db)
            controller = ContinuousRegularizationController(BarcodeQueueRepository(env.db), repo)
            controller.refresh_queue(); controller.select(lid)
            controller.submit_scan("A")
            result = controller.submit_scan("B")
            self.assertEqual(result.save_result.state, BarcodeSaveState.MISMATCH)
            self.assertFalse(result.advanced)
            self.assertEqual(controller.current_item.producto_local_id, lid)
            self.assertEqual(repo.list_for_product(lid), [])

    def test_10_readback_failure_is_error_and_no_advance(self):
        item = BarcodeQueueItem(key="p", item_kind="PRODUCT", nombre="P", producto_local_id="p")
        repo = _ReadbackFailureRepository()
        controller = ContinuousRegularizationController(_Queue([item]), repo)
        controller.refresh_queue(); controller.select("p")
        controller.submit_scan("X")
        result = controller.submit_scan("X")
        self.assertEqual(result.save_result.state, BarcodeSaveState.ERROR)
        self.assertFalse(result.advanced)
        self.assertEqual(controller.current_item.key, "p")

    def test_11_continuous_success_advances_only_to_next_pending(self):
        with phase2c_env() as env:
            _a, lid_a = create_product(env, "A Primero")
            _b, lid_b = create_product(env, "B Segundo")
            controller = ContinuousRegularizationController(
                BarcodeQueueRepository(env.db), ProductBarcodesRepository(env.db)
            )
            controller.refresh_queue(); controller.select(lid_a)
            controller.submit_scan("NEXT")
            result = controller.submit_scan("NEXT")
            self.assertTrue(result.advanced)
            self.assertEqual(controller.current_item.producto_local_id, lid_b)

    def test_12_excel_candidate_match_and_mismatch_are_reference_only(self):
        rows = [BarcodeQueueItem(
            key="p", item_kind="PRODUCT", nombre="P", producto_local_id="p",
            excel_candidate="Excel-007",
        )]
        for scan, expected in (("Excel-007", True), ("DIFFERENT", False)):
            repo = _ReadbackFailureRepository()
            controller = ContinuousRegularizationController(_Queue(rows), repo)
            controller.refresh_queue(); controller.select("p")
            result = controller.submit_scan(scan)
            self.assertEqual(result.excel_candidate_match, expected)
            self.assertEqual(repo.calls, [])

    def test_13_scanner_trial_reports_cr_lf_crlf_and_never_writes(self):
        for terminator, expected in (("\r", "CR"), ("\n", "LF"), ("\r\n", "CRLF")):
            trial = ScannerTrialSession()
            first = trial.feed_text("001Ab" + terminator)[-1]
            second = trial.feed_text("001Ab" + terminator)[-1]
            self.assertEqual(first.length, 5)
            self.assertEqual(second.terminator, expected)
            self.assertEqual(second.state, ScannerTrialState.MATCH)

    def test_14_scanner_trial_mismatch_resets_without_repository(self):
        trial = ScannerTrialSession()
        trial.feed_text("A\r")
        result = trial.feed_text("B\r")[-1]
        self.assertEqual(result.state, ScannerTrialState.MISMATCH)
        self.assertEqual(trial.state, ScannerTrialState.WAITING_FIRST_SCAN)


if __name__ == "__main__":
    unittest.main()
