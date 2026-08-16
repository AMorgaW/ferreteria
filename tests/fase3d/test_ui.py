# -*- coding: utf-8 -*-
"""UI Caja 3D: scanner no cierra, latencia remota no congela, local-first."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtWidgets import QApplication, QWidget

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase1e.helpers import insert_usuario
from tests.fase3d.helpers import caja_service, phase3d_env


class CajaUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _widget(self, env):
        from ui.caja_ui import CajaUI

        svc = caja_service(env)
        parent = QWidget()
        return CajaUI(parent, svc, svc.auth), svc

    def test_scanner_enter_does_not_confirm_close(self):
        from ui.caja_ui import FormularioCierreCaja

        with phase3d_env() as env:
            conn = env.connect()
            try:
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            widget, _svc = self._widget(env)
            self.assertFalse(widget.btn_cerrar.isDefault())
            self.assertFalse(widget.btn_cerrar.autoDefault())
            self.assertTrue(hasattr(FormularioCierreCaja, "keyPressEvent"))
            source = Path(FormularioCierreCaja.keyPressEvent.__code__.co_filename)
            self.assertTrue(source.name.endswith("caja_ui.py"))
            widget.deleteLater()

    def test_27_remote_latency_does_not_block_gui_thread(self):
        with phase3d_env() as env:
            conn = env.connect()
            try:
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = caja_service(env)
            parent = QWidget()

            def slow_connect(*_a, **_k):
                time.sleep(2)
                raise AssertionError("network")

            from ui.caja_ui import CajaUI

            started = time.perf_counter()
            with mock.patch("psycopg2.connect", side_effect=slow_connect):
                widget = CajaUI(parent, svc, svc.auth)
            elapsed = time.perf_counter() - started
            self.assertLess(elapsed, 0.5)
            widget.deleteLater()
            self.app.processEvents()

    def test_local_first_caja_ui_without_network(self):
        with phase3d_env() as env:
            conn = env.connect()
            try:
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = caja_service(env)
            parent = QWidget()
            from ui.caja_ui import CajaUI

            with mock.patch("psycopg2.connect", side_effect=AssertionError("network")) as network:
                widget = CajaUI(parent, svc, svc.auth)
                self.assertIn("Cerrada", widget.estado_label.text())
            network.assert_not_called()
            widget.deleteLater()


if __name__ == "__main__":
    unittest.main(verbosity=2)
