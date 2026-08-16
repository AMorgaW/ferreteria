from __future__ import annotations

import unittest

from barcode_scanner import (
    BarcodeDoubleScanVerifier,
    DoubleScanState,
    HidBarcodeScanner,
    normalize_barcode,
)
from repositories.product_barcodes_repo import BarcodeRecord
from services.barcode_service import BarcodeAssignmentSession, BarcodeSaveState


class _FakeRepository:
    def __init__(self, *, readback=True, mismatched=False):
        self.calls = []
        self.readback = readback
        self.mismatched = mismatched

    def assign_barcode(self, **kwargs):
        self.calls.append(kwargs)
        return BarcodeRecord(
            "barcode-lid",
            kwargs["producto_local_id"],
            kwargs["barcode"],
            kwargs["barcode_type"],
            kwargs["source"],
            True,
            True,
        )

    def get_by_local_id(self, _local_id):
        if not self.readback:
            return None
        value = "OTRO" if self.mismatched else self.calls[-1]["barcode"]
        return BarcodeRecord(
            "barcode-lid", "product-lid", value, "MANUFACTURER", "TEST", True, True
        )


class DoubleScanTest(unittest.TestCase):
    def test_01_first_scan_enters_confirmation_state(self):
        verifier = BarcodeDoubleScanVerifier()
        result = verifier.submit_scan("7701234567890")
        self.assertEqual(result.state, DoubleScanState.WAITING_CONFIRMATION)
        self.assertEqual(verifier.state, DoubleScanState.WAITING_CONFIRMATION)

    def test_02_identical_second_scan_verifies(self):
        verifier = BarcodeDoubleScanVerifier()
        verifier.submit_scan("7701234567890")
        result = verifier.submit_scan("7701234567890")
        self.assertEqual(result.state, DoubleScanState.VERIFIED)

    def test_03_different_second_scan_rejects(self):
        verifier = BarcodeDoubleScanVerifier()
        verifier.submit_scan("7701234567890")
        result = verifier.submit_scan("7701234567891")
        self.assertEqual(result.state, DoubleScanState.MISMATCH)
        self.assertEqual(verifier.state, DoubleScanState.WAITING_FIRST_SCAN)

    def test_04_mismatch_does_not_persist(self):
        repo = _FakeRepository()
        session = BarcodeAssignmentSession(repo, "product-lid")
        session.submit_scan("A")
        result = session.submit_scan("B")
        self.assertEqual(result.state, BarcodeSaveState.MISMATCH)
        self.assertEqual(repo.calls, [])

    def test_05_third_scan_after_mismatch_is_new_first(self):
        verifier = BarcodeDoubleScanVerifier()
        verifier.submit_scan("A")
        verifier.submit_scan("B")
        result = verifier.submit_scan("C")
        self.assertEqual(result.state, DoubleScanState.WAITING_CONFIRMATION)
        self.assertEqual(verifier.first_scan, "C")

    def test_06_leading_zeros_preserved(self):
        self.assertEqual(normalize_barcode("0012345678905\r"), "0012345678905")

    def test_07_cr_removed(self):
        events = HidBarcodeScanner().feed_text("ABC\r")
        self.assertEqual(events[-1].barcode, "ABC")

    def test_08_lf_removed(self):
        events = HidBarcodeScanner().feed_text("ABC\n")
        self.assertEqual(events[-1].barcode, "ABC")

    def test_09_empty_scan_rejected(self):
        events = HidBarcodeScanner().feed_text("\r")
        self.assertEqual(events[-1].error, "Escaneo vacío")

    def test_10_manufacturer_case_preserved(self):
        self.assertEqual(normalize_barcode("AbC-19\r"), "AbC-19")

    def test_11_save_only_after_second_matching_scan(self):
        repo = _FakeRepository()
        session = BarcodeAssignmentSession(repo, "product-lid")
        first = session.submit_scan("00123")
        self.assertEqual(first.state, BarcodeSaveState.SCANNED)
        self.assertEqual(repo.calls, [])
        second = session.submit_scan("00123")
        self.assertTrue(second.success)
        self.assertEqual(len(repo.calls), 1)

    def test_12_db_readback_required_for_success(self):
        repo = _FakeRepository(readback=False)
        session = BarcodeAssignmentSession(repo, "product-lid")
        session.submit_scan("ABC")
        result = session.submit_scan("ABC")
        self.assertEqual(result.state, BarcodeSaveState.ERROR)

    def test_13_readback_mismatch_is_error(self):
        repo = _FakeRepository(mismatched=True)
        session = BarcodeAssignmentSession(repo, "product-lid")
        session.submit_scan("ABC")
        result = session.submit_scan("ABC")
        self.assertEqual(result.state, BarcodeSaveState.ERROR)
        self.assertIn("no coincide", result.message)


if __name__ == "__main__":
    unittest.main()

