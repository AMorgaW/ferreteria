# -*- coding: utf-8 -*-
"""Centinela: xfail de arquitectura de Fase 0 no deben XPASS por 1B."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fase0 import test_contrato_xfail


STILL_XFAIL = (
    "test_contrato_unicidad_global_ultimo_stock",
    "test_contrato_payload_productos_sin_stock_autoritativo",
    "test_contrato_entrada_compra_unica",
    "test_contrato_coordinador_inventario_existe",
    "test_contrato_tablas_recepcion_existen",
    "test_contrato_cantidad_aceptada",
    "test_contrato_frp_y_producto_codigos",
    "test_contrato_offline_authority",
    "test_contrato_outbox_propaga",
    "test_contrato_factura_unica_por_proveedor",
    "test_contrato_fixed_point",
    "test_contrato_upsert_no_pisa_stock_en_fuente",
    "test_contrato_pull_no_pisa_stock_en_fuente",
)

NOW_PASS = (
    "test_contrato_integer_primary_key",
    "test_contrato_device_identity",
    "test_contrato_ledger_operation_id",
    "test_contrato_retry_recupera_resultado",
)


class XfailHeredadosTest(unittest.TestCase):
    def test_xfails_arquitectura_siguen_marcados(self):
        cls = test_contrato_xfail.ContratoExpectedFailureTest
        for name in STILL_XFAIL:
            method = getattr(cls, name)
            self.assertTrue(
                getattr(method, "__unittest_expecting_failure__", False),
                msg=f"{name} debe seguir siendo expectedFailure",
            )
        for name in NOW_PASS:
            method = getattr(cls, name)
            self.assertFalse(
                getattr(method, "__unittest_expecting_failure__", False),
                msg=f"{name} ya no debe ser expectedFailure",
            )

    def test_1b_no_adelanta_1c(self):
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
