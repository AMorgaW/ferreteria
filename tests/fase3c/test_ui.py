# -*- coding: utf-8 -*-
"""UI 3C: confirmación explícita, scanner no confirma, latencia remota."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtWidgets import QApplication

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from returns_schema import KIND_CUSTOMER_RETURN, ORIGINAL_TIPO_VENTA
from tests.fase3c.helpers import phase3c_env


class ReturnsUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _drain(self):
        from PySide6.QtCore import QThreadPool

        QThreadPool.globalInstance().waitForDone(5000)
        self.app.processEvents()

    def _make_dialog(self, service):
        from ui.returns_ui import ReversalDialog

        dlg = ReversalDialog(
            None,
            kind=KIND_CUSTOMER_RETURN,
            original_tipo=ORIGINAL_TIPO_VENTA,
            original_id=1,
            returns_service=service,
            db_manager=mock.MagicMock(),
            auto_exec=False,
        )
        return dlg

    def test_18_scanner_enter_does_not_confirm(self):
        class PreviewSvc:
            def preview(self, **kwargs):
                return {
                    "original": {"id": 1, "estado": "COMPLETADA", "local_id": "x"},
                    "lines": [
                        {
                            "producto_id": 1,
                            "producto_nombre": "X",
                            "original_qty": 1,
                            "returned_qty": 0,
                            "available_qty": 1,
                            "precio_unitario": 10,
                        }
                    ],
                    "derived_status": None,
                }

        dlg = self._make_dialog(PreviewSvc())
        self.assertFalse(dlg.btn_confirm.isDefault())
        self.assertFalse(dlg.btn_confirm.autoDefault())
        dlg.scan_entry.setText("770123")
        dlg.scan_entry.returnPressed.emit()
        self.assertEqual(dlg.scan_entry.text(), "")
        dlg.deleteLater()

    def test_23_remote_latency_does_not_block_gui_thread(self):
        gui_thread = threading.get_ident()
        called_from = []
        entered = threading.Event()
        release = threading.Event()

        class SlowReturns:
            def preview(self, **kwargs):
                return {
                    "original": {"id": 1, "estado": "COMPLETADA"},
                    "lines": [
                        {
                            "producto_id": 1,
                            "producto_nombre": "X",
                            "original_qty": 1,
                            "returned_qty": 0,
                            "available_qty": 1,
                            "precio_unitario": 10,
                        }
                    ],
                    "derived_status": None,
                }

            def guardar_borrador(self, **kwargs):
                return True, "ok", 1

            def confirmar(self, *args, **kwargs):
                called_from.append(threading.get_ident())
                entered.set()
                release.wait(2)
                return True, "ok", 1

        dlg = self._make_dialog(SlowReturns())
        dlg.spinboxes[0].setValue(1)
        with mock.patch("ui.returns_ui.QMessageBox.warning"), \
             mock.patch("ui.returns_ui.QMessageBox.critical"), \
             mock.patch("ui.returns_ui.QMessageBox.information"), \
             mock.patch(
                 "ui.returns_ui.QMessageBox.question",
                 return_value=__import__(
                     "PySide6.QtWidgets", fromlist=["QMessageBox"]
                 ).QMessageBox.Yes,
             ), \
             mock.patch("ui.returns_ui.return_finalize_allowed", return_value=(True, None)):
            started = time.perf_counter()
            dlg._confirm()
            gui_waited = time.perf_counter() - started
            self.assertTrue(entered.wait(1))
            self.assertLess(gui_waited, 0.4)
            self.assertFalse(dlg.btn_confirm.isEnabled())
            self.assertNotIn(gui_thread, called_from)
            release.set()
            self._drain()
        dlg.deleteLater()


if __name__ == "__main__":
    unittest.main(verbosity=2)
