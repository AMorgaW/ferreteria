# -*- coding: utf-8 -*-
"""Caja abre aunque la BD local aún no tenga station_id (causa raíz)."""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from models import Usuario
from services.caja_service import CajaService
from tests.fase0.harness import REPO_FERRETERIA_DB, official_temp_db


class _LegacyDb:
    def __init__(self, path: str):
        self.db_name = path

    def conectar(self):
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        return conn


class _Auth:
    def __init__(self, rol="ADMIN"):
        self.usuario_actual = Usuario(
            id=1, username="tester", nombre_completo="Tester", rol=rol
        )

    def registrar_auditoria(self, *args, **kwargs):
        return None


class CajaSchemaRepairTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_legacy_cierres_without_station_id_opens_ui(self):
        tmp = tempfile.TemporaryDirectory(prefix="ferrepro-fase5-legacy-")
        db_path = Path(tmp.name) / "legacy-caja.db"
        self.assertNotEqual(db_path.resolve(), REPO_FERRETERIA_DB.resolve())
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                """
                CREATE TABLE usuarios (
                    id INTEGER PRIMARY KEY,
                    username TEXT,
                    password_hash TEXT,
                    nombre_completo TEXT,
                    rol TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE cierres_caja (
                    id INTEGER PRIMARY KEY,
                    usuario_id INTEGER NOT NULL,
                    fecha_apertura TEXT,
                    fecha_cierre TEXT,
                    monto_inicial REAL DEFAULT 0
                )
                """
            )
            conn.execute(
                "INSERT INTO usuarios (id, username, password_hash, nombre_completo, rol) "
                "VALUES (1, 'tester', 'x', 'Tester', 'ADMIN')"
            )
            conn.execute(
                "INSERT INTO cierres_caja (usuario_id, fecha_apertura, monto_inicial) "
                "VALUES (1, '2026-08-16 10:00:00', 1000)"
            )
            conn.commit()
            cols = {row[1] for row in conn.execute("PRAGMA table_info(cierres_caja)")}
            self.assertNotIn("station_id", cols)
        finally:
            conn.close()

        from ui.caja_ui import CajaUI

        svc = CajaService(_LegacyDb(str(db_path)), _Auth("ADMIN"), station_id="W01")
        parent = QWidget()
        widget = CajaUI(parent, svc, svc.auth)
        parent.show()
        widget.show()
        self.app.processEvents()
        self.assertIn("Abierta", widget.estado_label.text())
        self.assertIsNotNone(svc.obtener_caja_abierta())
        widget.deleteLater()
        tmp.cleanup()

    def test_official_bootstrap_materializes_cash_schema(self):
        with official_temp_db() as env:
            conn = env.connect()
            try:
                cols = {
                    row[1] for row in conn.execute("PRAGMA table_info(cierres_caja)")
                }
                cash = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='cash_movements'"
                ).fetchone()
            finally:
                conn.close()
            self.assertIn("station_id", cols)
            self.assertIsNotNone(cash)


if __name__ == "__main__":
    unittest.main(verbosity=2)
