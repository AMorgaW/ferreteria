# -*- coding: utf-8 -*-
"""Fase 5 no muta ferreteria.db comercial."""
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
from tests.fase5.helpers import (
    assert_not_commercial_db,
    commercial_sha256,
    open_caja,
    phase5_env,
)


class CajaSafetyTest(unittest.TestCase):
    def test_18_commercial_db_untouched(self):
        before = commercial_sha256()
        mtime = REPO_FERRETERIA_DB.stat().st_mtime if REPO_FERRETERIA_DB.exists() else None
        with phase5_env() as env:
            assert_not_commercial_db(env)
            conn = env.connect()
            try:
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            open_caja(env, Decimal("1"))
            self.assertNotEqual(Path(env.db_path).resolve(), REPO_FERRETERIA_DB.resolve())
        self.assertEqual(commercial_sha256(), before)
        if REPO_FERRETERIA_DB.exists():
            self.assertEqual(REPO_FERRETERIA_DB.stat().st_mtime, mtime)


if __name__ == "__main__":
    unittest.main(verbosity=2)
