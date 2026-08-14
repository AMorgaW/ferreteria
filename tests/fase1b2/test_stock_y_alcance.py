# -*- coding: utf-8 -*-
"""FASE 1B.2 no activa exclusion de stock ni adelanta Fase 1C."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase0 import test_contrato_xfail
from tests.fase1b.test_xfail_heredados import STILL_XFAIL


class StockYAlcanceTest(unittest.TestCase):
    def test_authoritative_exclude_sigue_inactiva(self):
        from sync_registry import (
            APPLY_AUTHORITATIVE_EXCLUDE,
            declared_authoritative_exclude,
            fields_excluded_from_authoritative_write,
        )

        self.assertFalse(APPLY_AUTHORITATIVE_EXCLUDE)
        self.assertEqual(declared_authoritative_exclude("productos"), ("stock",))
        self.assertEqual(fields_excluded_from_authoritative_write("productos"), ())

    def test_xfails_arquitectura_siguen_marcados(self):
        cls = test_contrato_xfail.ContratoExpectedFailureTest
        for name in STILL_XFAIL:
            method = getattr(cls, name)
            self.assertTrue(
                getattr(method, "__unittest_expecting_failure__", False),
                msg=f"{name} debe seguir siendo expectedFailure",
            )

    def test_1b2_no_adelanta_1c(self):
        forbidden = (
            "def apply_inventory_operation",
            "OFFLINE_INVENTORY_AUTHORITY",
            "recepcion_documentos",
            "producto_codigos",
        )
        hits = []
        for path in REPO_ROOT.rglob("*.py"):
            rel = path.relative_to(REPO_ROOT)
            if any(
                part in {".git", "tests", "docs", ".cursor", "__pycache__"}
                for part in rel.parts
            ):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for token in forbidden:
                if token in text:
                    hits.append(f"{rel.as_posix()}: {token}")
        self.assertEqual(hits, [])
        src = (REPO_ROOT / "sync_registry.py").read_text(encoding="utf-8")
        self.assertIn("APPLY_AUTHORITATIVE_EXCLUDE = False", src)
