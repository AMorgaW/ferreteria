# -*- coding: utf-8 -*-
"""Helpers compartidos de tests Fase 1D."""
from __future__ import annotations

import uuid

DEVICE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def _op(producto_local_id, delta, line_no=1, operation_id=None, **extra):
    payload = {
        "operation_id": operation_id or str(uuid.uuid4()),
        "producto_local_id": producto_local_id,
        "line_no": line_no,
        "delta": delta,
    }
    payload.update(extra)
    return payload


def _op_scaled(producto_local_id, delta_scaled, line_no=1, operation_id=None):
    return {
        "operation_id": operation_id or str(uuid.uuid4()),
        "producto_local_id": producto_local_id,
        "line_no": line_no,
        "delta_scaled": int(delta_scaled),
    }
