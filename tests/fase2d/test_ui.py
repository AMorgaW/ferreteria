from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from ui.inventory_import_ui import InventoryImportUI


class _NoDb:
    def conectar(self):
        raise AssertionError("La UI no debe abrir DB al construir el preview")


class InventoryImportUISmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_preview_opens_and_has_no_apply_action(self):
        widget = InventoryImportUI(None, _NoDb())
        try:
            widget.resize(1500, 820)
            widget.show()
            self.app.processEvents()
            self.assertTrue(widget.isVisible())
            self.assertEqual(widget.table.columnCount(), 11)
            self.assertFalse(widget.dry_run_button.isEnabled())
            texts = [button.text().strip().casefold() for button in widget.findChildren(QPushButton)]
            self.assertFalse(any(text in ("aplicar", "aprobar y aplicar") for text in texts))
            self.assertFalse(any("mxn" in text for text in texts))
        finally:
            widget.close()


if __name__ == "__main__":
    unittest.main()
