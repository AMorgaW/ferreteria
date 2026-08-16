# -*- coding: utf-8 -*-
"""3D no muta ferreteria.db comercial."""
from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase0.harness import REPO_FERRETERIA_DB
from tests.fase1e.helpers import insert_usuario
from tests.fase3d.helpers import assert_not_commercial_db, open_caja, phase3d_env


class CashSafetyTest(unittest.TestCase):
    def test_30_commercial_db_untouched(self):
        before = REPO_FERRETERIA_DB.stat().st_mtime if REPO_FERRETERIA_DB.exists() else None
        with phase3d_env() as env:
            assert_not_commercial_db(env)
            conn = env.connect()
            try:
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            open_caja(env, Decimal("1"))
            self.assertNotEqual(Path(env.db_path).resolve(), REPO_FERRETERIA_DB.resolve())
        if REPO_FERRETERIA_DB.exists():
            self.assertEqual(REPO_FERRETERIA_DB.stat().st_mtime, before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
