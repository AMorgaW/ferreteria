# -*- coding: utf-8 -*-
"""UI recepción: doble confirmación, latencia remota y local-first. Offscreen Qt."""
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

from tests.fase3b.helpers import phase3b_env, seed_purchase_product


class ReceivingUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _drain(self):
        from PySide6.QtCore import QThreadPool

        QThreadPool.globalInstance().waitForDone(5000)
        self.app.processEvents()

    def _make_form(self, service):
        from ui.compras_ui import FormularioCompra

        productos = mock.MagicMock()
        productos.cache_disponible.return_value = True
        productos.buscar_productos_cache.return_value = []
        productos.listar_productos.return_value = []
        proveedores = mock.MagicMock()
        prov = mock.MagicMock()
        prov.nombre = "Prov Test"
        prov.id = 1
        proveedores.listar_proveedores.return_value = [prov]
        auth = mock.MagicMock()
        auth.usuario_actual = mock.MagicMock(id=1)
        compras_repo = mock.MagicMock()
        compras_repo.db = mock.MagicMock()
        form = FormularioCompra(
            None,
            compras_repo,
            proveedores,
            productos,
            auth,
            auto_exec=False,
            compras_service=service,
            db_manager=mock.MagicMock(),
        )
        form.proveedores_dict = {"Prov Test": 1}
        form.factura_entry.setText("F-UI")
        return form

    def test_13_duplicate_confirm_starts_one_receipt(self):
        calls = []
        entered = threading.Event()
        release = threading.Event()

        class SlowPurchases:
            def guardar_borrador(self, **kwargs):
                return True, "ok", 1

            def confirmar_recepcion(self, **kwargs):
                calls.append(kwargs)
                entered.set()
                release.wait(2)
                return True, "ok", 1

        form = self._make_form(SlowPurchases())
        form.purchase_cart.add_line(
            {"id": 1, "nombre": "X", "precio_compra": 100, "permite_decimales": 0},
            1,
            costo_unitario=100,
        )
        form._sync_carrito_from_cart()
        with mock.patch("ui.compras_ui.QMessageBox.warning"), \
             mock.patch("ui.compras_ui.QMessageBox.critical"), \
             mock.patch("ui.compras_ui.QMessageBox.information"), \
             mock.patch("ui.compras_ui.QMessageBox.question", return_value=form.Yes if False else __import__("PySide6.QtWidgets", fromlist=["QMessageBox"]).QMessageBox.Yes), \
             mock.patch("ui.compras_ui.receipt_finalize_allowed", return_value=(True, None)):
            form.guardar_compra()
            form.guardar_compra()
            self.assertTrue(entered.wait(1))
            self.assertEqual(len(calls), 1)
            self.assertFalse(form.btn_confirmar.isEnabled())
            self.assertFalse(form.btn_cancelar.isEnabled())
            form.reject()
            self.assertTrue(form.purchase_cart.confirm_in_flight)
            self.assertTrue(form.isVisible() or form.isModal())
            release.set()
            self._drain()
        form.deleteLater()

    def test_20_remote_latency_does_not_block_gui_thread(self):
        gui_thread = threading.get_ident()
        called_from = []
        entered = threading.Event()
        release = threading.Event()

        class SlowPurchases:
            def guardar_borrador(self, **kwargs):
                return True, "ok", 1

            def confirmar_recepcion(self, **kwargs):
                called_from.append(threading.get_ident())
                entered.set()
                release.wait(2)
                return False, "INVENTORY_UNKNOWN x", None

        form = self._make_form(SlowPurchases())
        form.purchase_cart.add_line(
            {"id": 1, "nombre": "X", "precio_compra": 100, "permite_decimales": 0},
            1,
            costo_unitario=100,
        )
        form._sync_carrito_from_cart()
        with mock.patch("ui.compras_ui.QMessageBox.warning"), \
             mock.patch("ui.compras_ui.QMessageBox.critical"), \
             mock.patch("ui.compras_ui.QMessageBox.information"), \
             mock.patch("ui.compras_ui.QMessageBox.question", return_value=__import__("PySide6.QtWidgets", fromlist=["QMessageBox"]).QMessageBox.Yes), \
             mock.patch("ui.compras_ui.receipt_finalize_allowed", return_value=(True, None)):
            started = time.perf_counter()
            form.guardar_compra()
            elapsed = time.perf_counter() - started
            self.assertLess(elapsed, 0.15)
            self.assertTrue(entered.wait(1))
            self.assertTrue(called_from)
            self.assertNotEqual(called_from[0], gui_thread)
            self.app.processEvents()
            release.set()
            self._drain()
        form.deleteLater()

    def test_19_local_first_open_without_network(self):
        from repositories.productos_repo import ProductosRepository
        from repositories.proveedores_repo import ProveedoresRepository
        from repositories.compras_repo import ComprasRepository
        from ui.compras_ui import FormularioCompra, ComprasUI

        with phase3b_env() as env:
            seed_purchase_product(env, barcode="HID-R")
            conn = env.connect()
            try:
                env.insert_proveedor(conn, nombre="Prov Local")
                conn.commit()
            finally:
                conn.close()
            parent = QWidget()
            with mock.patch("psycopg2.connect", side_effect=AssertionError("network")) as network, \
                 mock.patch("ui.compras_ui.QMessageBox.information"), \
                 mock.patch("ui.compras_ui.QMessageBox.critical"):
                widget = ComprasUI(
                    parent,
                    env.db,
                    ComprasRepository(env.db),
                    ProveedoresRepository(env.db),
                    ProductosRepository(env.db),
                    mock.MagicMock(),
                )
                form = FormularioCompra(
                    widget,
                    ComprasRepository(env.db),
                    ProveedoresRepository(env.db),
                    ProductosRepository(env.db),
                    mock.MagicMock(),
                    auto_exec=False,
                    db_manager=env.db,
                )
                form.scan_entry.setText("HID-R")
                form.agregar_por_codigo()
            self.assertGreaterEqual(len(form.purchase_cart.lines), 1)
            network.assert_not_called()
            widget.deleteLater()
            form.deleteLater()


if __name__ == "__main__":
    unittest.main(verbosity=2)
