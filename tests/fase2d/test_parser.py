from __future__ import annotations

import shutil
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from inventory_excel_importer import InventoryExcelImporter, InventoryWorkbookError
from product_inventory_contract import OPERATIONAL_INVENTORY_FIELDS
from tests.fase2d.helpers import valid_row, write_workbook


class ParserPhase2DTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.importer = InventoryExcelImporter()

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def codes(row):
        return {issue.code for issue in row.all_issues}

    def parse_one(self, **updates):
        path = write_workbook(self.root / "inventory.xlsx", [valid_row(**updates)])
        parsed = self.importer.parse(path)
        self.assertEqual(len(parsed.rows), 1)
        return parsed.rows[0]

    def test_01_valid_workbook_parsed(self):
        row = self.parse_one()
        self.assertEqual(row.validation_status, "VALID")
        self.assertEqual(row.quantity_counted_scaled, 9000)

    def test_02_required_header_missing_rejected(self):
        fields = list(OPERATIONAL_INVENTORY_FIELDS[:-1])
        path = write_workbook(self.root / "missing.xlsx", [valid_row()], fields=fields)
        with self.assertRaisesRegex(InventoryWorkbookError, "Faltan encabezados"):
            self.importer.parse(path)

    def test_03_reordered_headers_are_supported(self):
        path = write_workbook(self.root / "reordered.xlsx", [valid_row()], fields=reversed(OPERATIONAL_INVENTORY_FIELDS))
        self.assertEqual(self.importer.parse(path).rows[0].quantity_counted_scaled, 9000)

    def test_04_extra_columns_are_reported_and_ignored(self):
        path = write_workbook(self.root / "extra.xlsx", [valid_row()], extras=["NOTAS DEL CONTADOR"])
        parsed = self.importer.parse(path)
        self.assertEqual(parsed.extra_headers, ("NOTAS DEL CONTADOR",))
        self.assertEqual(parsed.workbook_warnings[0].code, "EXTRA_COLUMN")

    def test_05_blank_rows_are_ignored(self):
        path = write_workbook(self.root / "blank.xlsx", [valid_row(), {}, valid_row(nombre="Alicate")])
        self.assertEqual(len(self.importer.parse(path).rows), 2)

    def test_06_integer_40_remains_40_and_scales_once(self):
        row = self.parse_one(
            presentacion_empaque="SIN EMPAQUE", cantidad_base_por_empaque=None,
            empaques_completos_contados=0, unidades_sueltas_contadas=40,
            cantidad_total_excel=40,
        )
        self.assertEqual(row.quantity_counted, Decimal("40"))
        self.assertEqual(row.quantity_counted_scaled, 40000)

    def test_07_decimal_40_5_is_exact(self):
        row = self.parse_one(
            presentacion_empaque="SIN EMPAQUE", cantidad_base_por_empaque=None,
            empaques_completos_contados=0, unidades_sueltas_contadas=40.5,
            cantidad_total_excel=40.5, permite_decimales="SI",
        )
        self.assertEqual(row.quantity_counted, Decimal("40.5"))
        self.assertEqual(row.quantity_counted_scaled, 40500)

    def test_08_more_than_three_decimals_rejected(self):
        row = self.parse_one(
            presentacion_empaque="SIN EMPAQUE", cantidad_base_por_empaque=None,
            empaques_completos_contados=0, unidades_sueltas_contadas=0.1255,
            cantidad_total_excel=0.1255, permite_decimales="SI",
        )
        self.assertIn("INVALID_QUANTITY", self.codes(row))

    def test_09_package_formula_is_recalculated(self):
        row = self.parse_one(cantidad_base_por_empaque=24, empaques_completos_contados=3, unidades_sueltas_contadas=4, cantidad_total_excel=76)
        self.assertEqual(row.quantity_counted, Decimal("76"))

    def test_10_wrong_excel_total_detected(self):
        row = self.parse_one(cantidad_total_excel=10)
        self.assertIn("ERROR_COUNT_MISMATCH", self.codes(row))

    def test_11_no_package_uses_loose_units(self):
        row = self.parse_one(presentacion_empaque="SIN EMPAQUE", cantidad_base_por_empaque=None, empaques_completos_contados=0, unidades_sueltas_contadas=7, cantidad_total_excel=7)
        self.assertEqual(row.quantity_counted_scaled, 7000)

    def test_12_complete_packages_calculation(self):
        row = self.parse_one(empaques_completos_contados=3, unidades_sueltas_contadas=0, cantidad_total_excel=12)
        self.assertEqual(row.quantity_counted, Decimal("12"))

    def test_13_loose_units_calculation(self):
        row = self.parse_one(empaques_completos_contados=0, unidades_sueltas_contadas=6, cantidad_total_excel=6)
        self.assertEqual(row.quantity_counted, Decimal("6"))

    def test_14_combination_calculation(self):
        row = self.parse_one(cantidad_base_por_empaque=5, empaques_completos_contados=2, unidades_sueltas_contadas=3, cantidad_total_excel=13)
        self.assertEqual(row.quantity_counted_scaled, 13000)

    def test_complete_packages_must_be_integer(self):
        row = self.parse_one(empaques_completos_contados=1.5, cantidad_total_excel=7)
        self.assertIn("COMPLETE_PACKAGES_NOT_INTEGER", self.codes(row))

    def test_at_least_one_sale_mode_is_required(self):
        row = self.parse_one(vende_unidad_base="NO", vende_medio_empaque="NO", vende_empaque_completo="NO")
        self.assertIn("NO_SALE_MODE", self.codes(row))

    def test_15_half_package_integer(self):
        row = self.parse_one(vende_medio_empaque="SI", cantidad_base_por_empaque=4)
        self.assertEqual(row.values["cantidad_medio_empaque"], Decimal("2"))
        self.assertNotIn("REVIEW_HALF_PACKAGE_FRACTION", self.codes(row))

    def test_16_half_package_fraction_requires_review(self):
        row = self.parse_one(vende_medio_empaque="SI", cantidad_base_por_empaque=5, empaques_completos_contados=1, unidades_sueltas_contadas=0, cantidad_total_excel=5)
        self.assertIn("REVIEW_HALF_PACKAGE_FRACTION", self.codes(row))
        self.assertEqual(row.values["cantidad_medio_empaque"], Decimal("2.5"))

    def test_17_monetary_values_use_decimal(self):
        row = self.parse_one(precio_compra="$ 10.000 COP", precio_venta="$ 15.000 COP")
        self.assertEqual(row.values["precio_compra"], Decimal("10000"))
        self.assertEqual(row.values["precio_venta"], Decimal("15000"))

    def test_18_invalid_purchase_price(self):
        self.assertIn("INVALID_PURCHASE_PRICE", self.codes(self.parse_one(precio_compra=-1)))

    def test_19_invalid_sale_price(self):
        self.assertIn("INVALID_SALE_PRICE", self.codes(self.parse_one(precio_venta=0)))

    def test_20_invalid_unit_requires_review(self):
        self.assertIn("NEW_UNIT_REVIEW", self.codes(self.parse_one(unidad_base="PARSEC")))

    def test_21_invalid_category_requires_review(self):
        self.assertIn("NEW_CATEGORY_REVIEW", self.codes(self.parse_one(categoria="Categoría improvisada")))

    def test_22_barcode_blank_allowed_in_staging(self):
        row = self.parse_one()
        self.assertEqual(row.barcode_status, "BARCODE_PENDING")
        self.assertFalse(row.errors)

    def test_24_mismatched_double_barcode_is_error(self):
        row = self.parse_one(barcode_primero="0012345", barcode_segundo="0012346")
        self.assertEqual(row.barcode_status, "BARCODE_ERROR")
        self.assertIn("BARCODE_SCAN_MISMATCH", self.codes(row))

    def test_25_duplicate_barcode_candidate_is_not_removed(self):
        data = valid_row(barcode_primero="0012345", barcode_segundo="0012345")
        other = valid_row(nombre="Alicate", barcode_primero="0012345", barcode_segundo="0012345")
        parsed = self.importer.parse(write_workbook(self.root / "dupes.xlsx", [data, other]))
        self.assertEqual(len(parsed.rows), 2)
        self.assertTrue(all("DUPLICATE_CANDIDATE" in self.codes(row) for row in parsed.rows))

    def test_29_duplicate_row_detection_does_not_sum(self):
        parsed = self.importer.parse(write_workbook(self.root / "rows.xlsx", [valid_row(), valid_row()]))
        self.assertEqual([row.quantity_counted_scaled for row in parsed.rows], [9000, 9000])
        self.assertTrue(all(row.duplicate_candidate for row in parsed.rows))

    def test_30_row_hash_is_stable(self):
        first = self.importer.parse(write_workbook(self.root / "one.xlsx", [valid_row()])).rows[0]
        second = self.importer.parse(write_workbook(self.root / "two.xlsx", [valid_row()])).rows[0]
        self.assertEqual(first.row_hash, second.row_hash)

    def test_32_changed_file_has_different_sha(self):
        one = self.importer.parse(write_workbook(self.root / "one.xlsx", [valid_row()]))
        two = self.importer.parse(write_workbook(self.root / "two.xlsx", [valid_row(cantidad_total_excel=10)]))
        self.assertNotEqual(one.source_sha256, two.source_sha256)

    def test_44_malformed_xlsx_rejected(self):
        path = self.root / "bad.xlsx"
        path.write_bytes(b"not a zip")
        with self.assertRaisesRegex(InventoryWorkbookError, "malformado"):
            self.importer.parse(path)

    def test_45_oversized_input_protection(self):
        path = write_workbook(self.root / "size.xlsx", [valid_row()])
        with self.assertRaisesRegex(InventoryWorkbookError, "tamaño máximo"):
            InventoryExcelImporter(max_file_bytes=1).parse(path)

    def test_barcode_candidate_preserves_leading_zero_and_is_not_verified(self):
        row = self.parse_one(barcode_primero="0012345", barcode_segundo="0012345")
        self.assertEqual(row.barcode_candidate, "0012345")
        self.assertEqual(row.barcode_status, "BARCODE_EXCEL_CANDIDATE")

    def test_legacy_template_is_rejected_without_modification(self):
        source = Path(__file__).resolve().parents[2] / "plantillas" / "FERREPRO_Inventario_Maestro.xlsx"
        if not source.exists():
            self.skipTest("plantilla operacional no disponible")
        copy = self.root / source.name
        shutil.copy2(source, copy)
        before = source.read_bytes()
        with self.assertRaisesRegex(InventoryWorkbookError, "Faltan encabezados"):
            self.importer.parse(copy)
        self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
