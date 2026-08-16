# -*- coding: utf-8 -*-
"""Sesión de caja 3D: open, station, restart, close, inmutabilidad."""
from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cash_schema import ALREADY_CLOSED, EXISTING_OPEN_SESSION, NO_OPEN_SESSION
from services.caja_service import money
from tests.fase1e.helpers import insert_usuario
from tests.fase3d.helpers import (
    assert_not_commercial_db,
    caja_service,
    count_movements,
    open_caja,
    phase3d_env,
)


class CashSessionTest(unittest.TestCase):
    def test_01_open_session(self):
        with phase3d_env() as env:
            conn = env.connect()
            try:
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = open_caja(env, Decimal("200000"))
            caja = svc.obtener_caja_abierta()
            self.assertIsNotNone(caja)
            self.assertEqual(caja["estado"], "OPEN")
            self.assertEqual(caja["station_id"], "W01")
            self.assertIsNone(caja["fecha_cierre"])
            self.assertEqual(svc.expected_cash(), Decimal("200000.00"))

    def test_02_second_open_same_station_rejected(self):
        with phase3d_env() as env:
            conn = env.connect()
            try:
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            open_caja(env)
            ok, msg = caja_service(env).abrir_caja(Decimal("1"))
            self.assertFalse(ok)
            self.assertIn(EXISTING_OPEN_SESSION, msg)

    def test_03_different_stations_independent(self):
        with phase3d_env() as env:
            conn = env.connect()
            try:
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            w01 = open_caja(env, Decimal("10"), "W01")
            w02 = open_caja(env, Decimal("20"), "W02")
            self.assertEqual(w01.obtener_caja_abierta()["station_id"], "W01")
            self.assertEqual(w02.obtener_caja_abierta()["station_id"], "W02")
            self.assertNotEqual(
                w01.obtener_caja_abierta()["id"], w02.obtener_caja_abierta()["id"]
            )

    def test_21_22_close_immutable_and_double_close(self):
        with phase3d_env() as env:
            conn = env.connect()
            try:
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            svc = open_caja(env, Decimal("50000"))
            session_id = svc.obtener_caja_abierta()["id"]
            ok, msg = svc.cerrar_caja(Decimal("50000"), "cuadra")
            self.assertTrue(ok, msg)
            self.assertIsNone(svc.obtener_caja_abierta())
            ok2, msg2 = svc.cerrar_caja(Decimal("1"))
            self.assertFalse(ok2)
            self.assertTrue(
                ALREADY_CLOSED in msg2 or NO_OPEN_SESSION in msg2,
                msg2,
            )
            conn = env.connect()
            try:
                row = conn.execute(
                    "SELECT monto_real, diferencia, estado FROM cierres_caja WHERE id=?",
                    (session_id,),
                ).fetchone()
                self.assertEqual(row["estado"], "CLOSED")
                self.assertEqual(money(row["monto_real"]), Decimal("50000.00"))
                before = count_movements(env, session_id)
                ok3, msg3, _ = svc.registrar_egreso(
                    Decimal("10"), "Gasolina", "no debe entrar", "EFECTIVO"
                )
                self.assertFalse(ok3)
                self.assertIn(NO_OPEN_SESSION, msg3)
                self.assertEqual(count_movements(env, session_id), before)
            finally:
                conn.close()

    def test_24_restart_recovers_open_session(self):
        with phase3d_env() as env:
            conn = env.connect()
            try:
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            first = open_caja(env, Decimal("777"))
            session_id = first.obtener_caja_abierta()["id"]
            local_id = first.obtener_caja_abierta()["local_id"]
            restarted = caja_service(env, "W01")
            caja = restarted.obtener_caja_abierta()
            self.assertEqual(caja["id"], session_id)
            self.assertEqual(caja["local_id"], local_id)
            self.assertEqual(caja["estado"], "OPEN")

    def test_28_session_scoped_by_station(self):
        with phase3d_env() as env:
            conn = env.connect()
            try:
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            open_caja(env, Decimal("1"), "W01")
            other = caja_service(env, "W02")
            self.assertIsNone(other.obtener_caja_abierta())


if __name__ == "__main__":
    unittest.main(verbosity=2)
