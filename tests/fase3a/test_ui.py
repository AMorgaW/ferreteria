# -*- coding: utf-8 -*-
"""UI POS: doble confirmación, latencia remota y local-first. Offscreen Qt."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtWidgets import QApplication, QWidget

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase3a.helpers import phase3a_env, seed_pos_product


class PosUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _drain(self):
        from PySide6.QtCore import QThreadPool

        QThreadPool.globalInstance().waitForDone(5000)
        self.app.processEvents()

    def _make_pos(self, ventas_service):
        from ui.ventas_ui_modern import VentasUIModern

        productos = mock.MagicMock()
        productos.cache_disponible.return_value = True
        productos.buscar_productos_cache.return_value = []
        productos.obtener_categorias.return_value = []
        auth = mock.MagicMock()
        auth.tiene_permiso.return_value = True
        parent = QWidget()
        with mock.patch("ui.ventas_ui_modern.QMessageBox.information"):
            widget = VentasUIModern(
                parent,
                ventas_service,
                productos,
                mock.MagicMock(),
                auth,
                mock.MagicMock(),
            )
        return widget

    def test_14_duplicate_confirm_starts_one_sale(self):
        calls = []
        entered = threading.Event()
        release = threading.Event()

        class SlowSales:
            def registrar_venta(self, **kwargs):
                calls.append(kwargs)
                entered.set()
                release.wait(2)
                venta = type(
                    "V",
                    (),
                    {
                        "id": 1,
                        "numero_factura": "T-1",
                        "fecha": "2026-08-16",
                        "total": 1000,
                        "subtotal": 1000,
                        "descuento": 0,
                        "iva": 0,
                    },
                )()
                return True, "ok", venta

        widget = self._make_pos(SlowSales())
        widget.cargar_productos = lambda: None
        widget.pos_cart.add_manual(
            {"id": 1, "nombre": "X", "precio_venta": 1000, "permite_decimales": 0},
            1,
        )
        with mock.patch("ui.ventas_ui_modern.QMessageBox.warning"), \
             mock.patch("ui.ventas_ui_modern.QMessageBox.critical"), \
             mock.patch("ui.ventas_ui_modern.QMessageBox.information"), \
             mock.patch("ui.ventas_ui_modern.pos_finalize_allowed", return_value=(True, None)), \
             mock.patch.object(widget, "_mostrar_dialogo_venta_exitosa"):
            widget.procesar_venta()
            widget.procesar_venta()
            self.assertTrue(entered.wait(1))
            self.assertEqual(len(calls), 1)
            self.assertFalse(widget.btn_autorizar.isEnabled())
            release.set()
            self._drain()
        widget.deleteLater()

    def test_18_remote_latency_does_not_block_gui_thread(self):
        gui_thread = threading.get_ident()
        called_from = []
        entered = threading.Event()
        release = threading.Event()

        class SlowSales:
            def registrar_venta(self, **kwargs):
                called_from.append(threading.get_ident())
                entered.set()
                release.wait(2)
                return False, "INVENTORY_UNKNOWN x", None

        widget = self._make_pos(SlowSales())
        widget.cargar_productos = lambda: None
        widget.pos_cart.add_manual(
            {"id": 1, "nombre": "X", "precio_venta": 1000, "permite_decimales": 0},
            1,
        )
        with mock.patch("ui.ventas_ui_modern.QMessageBox.warning"), \
             mock.patch("ui.ventas_ui_modern.QMessageBox.critical"), \
             mock.patch("ui.ventas_ui_modern.pos_finalize_allowed", return_value=(True, None)):
            started = time.perf_counter()
            widget.procesar_venta()
            elapsed = time.perf_counter() - started
            self.assertLess(elapsed, 0.15)
            self.assertTrue(entered.wait(1))
            self.assertTrue(called_from)
            self.assertNotEqual(called_from[0], gui_thread)
            self.app.processEvents()
            release.set()
            self._drain()
        widget.deleteLater()

    def test_local_first_open_and_scan_without_network(self):
        from repositories.productos_repo import ProductosRepository
        from ui.ventas_ui_modern import VentasUIModern

        with phase3a_env() as env:
            seed_pos_product(env, barcode="HID-1")
            repo = ProductosRepository(env.db)
            parent = QWidget()
            with mock.patch("psycopg2.connect", side_effect=AssertionError("network")) as network, \
                 mock.patch("ui.ventas_ui_modern.QMessageBox.information"):
                widget = VentasUIModern(
                    parent,
                    mock.MagicMock(),
                    repo,
                    mock.MagicMock(),
                    mock.MagicMock(),
                    env.db,
                )
                widget.search_entry.setText("HID-1")
                widget.agregar_por_codigo_rapido()
            self.assertEqual(len(widget.carrito), 1)
            network.assert_not_called()
            widget.ventas_service.registrar_venta.assert_not_called()
            widget.deleteLater()


if __name__ == "__main__":
    unittest.main(verbosity=2)
