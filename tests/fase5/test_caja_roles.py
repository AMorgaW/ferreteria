# -*- coding: utf-8 -*-
"""Contrato ADMIN/EMPLEADO de Caja. SQLite temporal. Sin UI automation excesiva."""
from __future__ import annotations

import os
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cash_schema import EFFECT_DRAWER_IN, EFFECT_INFORMATIONAL
from models import Usuario
from services.caja_service import CASH_ADMIN_DENIED, can_view_caja, is_cash_admin
from tests.fase1e.helpers import AuthPermitido, insert_usuario
from tests.fase5.helpers import (
    caja_service,
    complete_sale_as,
    count_movements,
    open_caja,
    phase5_env,
    seed_pos_product,
)


def _app():
    return QApplication.instance() or QApplication([])


class CajaRolesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _seed(self, env):
        conn = env.connect()
        try:
            insert_usuario(conn)
            conn.commit()
        finally:
            conn.close()
        seed_pos_product(env, stock=20, precio_venta=1000)

    def _ui(self, env, rol):
        from ui.caja_ui import CajaUI

        svc = caja_service(env, rol=rol)
        parent = QWidget()
        widget = CajaUI(parent, svc, svc.auth)
        parent.show()
        widget.show()
        self.app.processEvents()
        return widget, svc

    def test_auth_empleado_can_open_caja_section(self):
        from auth import AuthManager

        auth = AuthManager.__new__(AuthManager)
        auth.usuario_actual = Usuario(id=2, username="empleado", rol="EMPLEADO")
        self.assertTrue(auth.tiene_permiso("realizar_ventas"))
        self.assertTrue(can_view_caja(auth.usuario_actual))
        self.assertFalse(is_cash_admin(auth.usuario_actual))
        auth.usuario_actual = Usuario(id=1, username="admin", rol="ADMIN")
        self.assertTrue(is_cash_admin(auth.usuario_actual))

    def test_01_admin_opens_caja_ui(self):
        with phase5_env() as env:
            self._seed(env)
            widget, _svc = self._ui(env, "ADMIN")
            self.assertIn("Cerrada", widget.estado_label.text())
            self.assertTrue(widget.btn_abrir.isVisible())
            widget.deleteLater()

    def test_02_empleado_and_vendedor_open_caja_ui(self):
        with phase5_env() as env:
            self._seed(env)
            for rol in ("EMPLEADO", "VENDEDOR"):
                widget, _svc = self._ui(env, rol)
                self.assertTrue(widget.estado_label.text())
                self.assertIn("Cerrada", widget.estado_label.text())
                self.assertFalse(widget.btn_abrir.isVisible())
                widget.deleteLater()

    def test_03_empleado_sees_open_status(self):
        with phase5_env() as env:
            self._seed(env)
            open_caja(env, Decimal("50000"), "W01")
            widget, svc = self._ui(env, "VENDEDOR")
            text = widget.info_label.text()
            self.assertIn("ABIERTA", text)
            self.assertIn(svc.estacion_actual(), text)
            self.assertNotIn("esperado", text.lower())
            self.assertNotIn("Monto inicial", text)
            self.assertFalse(widget.resumen_frame.isVisible())
            self.assertFalse(widget.btn_cerrar.isVisible())
            self.assertFalse(widget.btn_egreso.isVisible())
            self.assertFalse(widget.btn_ingreso.isVisible())
            widget.deleteLater()

    def test_04_empleado_sees_closed_status(self):
        with phase5_env() as env:
            self._seed(env)
            widget, svc = self._ui(env, "EMPLEADO")
            text = widget.info_label.text()
            self.assertIn("CERRADA", text)
            self.assertIn(svc.estacion_actual(), text)
            self.assertIn("administrador", text.lower())
            self.assertFalse(widget.btn_abrir.isVisible())
            self.assertFalse(widget.resumen_frame.isVisible())
            widget.deleteLater()

    def test_05_to_09_empleado_denied_admin_commands(self):
        with phase5_env() as env:
            self._seed(env)
            open_caja(env, Decimal("10000"))
            for rol in ("EMPLEADO", "VENDEDOR"):
                svc = caja_service(env, rol=rol)
                ok, msg = svc.abrir_caja(Decimal("1"))
                self.assertFalse(ok)
                self.assertEqual(msg, CASH_ADMIN_DENIED)
                ok, msg = svc.cerrar_caja(Decimal("10000"))
                self.assertFalse(ok)
                self.assertEqual(msg, CASH_ADMIN_DENIED)
                ok, msg, _mid = svc.registrar_ingreso_manual(Decimal("10"), "refuerzo")
                self.assertFalse(ok)
                self.assertEqual(msg, CASH_ADMIN_DENIED)
                ok, msg, _mid = svc.registrar_egreso(
                    Decimal("10"), "Otros Gastos", "taxi", "EFECTIVO"
                )
                self.assertFalse(ok)
                self.assertEqual(msg, CASH_ADMIN_DENIED)

    def test_10_11_12_admin_keeps_open_move_close(self):
        with phase5_env() as env:
            self._seed(env)
            svc = caja_service(env, rol="ADMIN")
            ok, msg = svc.abrir_caja(Decimal("20000"))
            self.assertTrue(ok, msg)
            self.assertIsNotNone(svc.obtener_caja_abierta())
            ok, msg, _mid = svc.registrar_ingreso_manual(Decimal("5000"), "cambio")
            self.assertTrue(ok, msg)
            ok, msg, _mid = svc.registrar_egreso(
                Decimal("1000"), "Papelería", "bolsas", "EFECTIVO"
            )
            self.assertTrue(ok, msg)
            ok, msg = svc.cerrar_caja(Decimal("24000"))
            self.assertTrue(ok, msg)
            self.assertIsNone(svc.obtener_caja_abierta())

    def test_13_empleado_cash_sale_one_drawer_in(self):
        with phase5_env() as env:
            self._seed(env)
            open_caja(env, Decimal("0"))
            complete_sale_as(env, rol="VENDEDOR")
            self.assertEqual(count_movements(env, source_kind="venta"), 1)
            conn = env.connect()
            try:
                row = conn.execute(
                    "SELECT cash_effect_kind FROM cash_movements WHERE source_kind='venta'"
                ).fetchone()
            finally:
                conn.close()
            self.assertEqual(row[0], EFFECT_DRAWER_IN)

    def test_14_empleado_noncash_sale_no_drawer(self):
        with phase5_env() as env:
            self._seed(env)
            open_caja(env, Decimal("0"))
            complete_sale_as(env, rol="EMPLEADO", metodo_pago="TARJETA")
            self.assertEqual(count_movements(env, source_kind="venta"), 1)
            conn = env.connect()
            try:
                row = conn.execute(
                    "SELECT cash_effect_kind FROM cash_movements WHERE source_kind='venta'"
                ).fetchone()
            finally:
                conn.close()
            self.assertEqual(row[0], EFFECT_INFORMATIONAL)
            self.assertEqual(caja_service(env).expected_cash(), Decimal("0.00"))

    def test_15_empleado_ui_hides_expected_cash(self):
        with phase5_env() as env:
            self._seed(env)
            open_caja(env, Decimal("999999"))
            widget, _svc = self._ui(env, "VENDEDOR")
            blob = (
                widget.info_label.text()
                + widget.estado_label.text()
                + widget.lbl_total.text()
            ).lower()
            self.assertNotIn("esperado", blob)
            self.assertNotIn("999999", blob)
            self.assertFalse(widget.resumen_frame.isVisible())
            widget.deleteLater()

    def test_16_17_caja_offline_without_supabase(self):
        with phase5_env() as env:
            self._seed(env)
            svc = caja_service(env, rol="ADMIN")
            with mock.patch(
                "psycopg2.connect", side_effect=AssertionError("network")
            ) as network:
                ok, msg = svc.abrir_caja(Decimal("10"))
                self.assertTrue(ok, msg)
                widget, _svc = self._ui(env, "EMPLEADO")
                self.assertIn("ABIERTA", widget.info_label.text())
                widget.deleteLater()
            network.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
