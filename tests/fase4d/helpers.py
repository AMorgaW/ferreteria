# -*- coding: utf-8 -*-
"""Helpers Fase 4D. SQLite temporal. Nunca ferreteria.db comercial."""
from __future__ import annotations

import os
from contextlib import contextmanager

from tests.fase4a.helpers import (
    assert_commercial_untouched,
    assert_not_commercial_db,
    commercial_db_mtime,
)
from tests.fase4b.helpers import (
    credit_purchase,
    credit_sale,
    cxc,
    cxp,
    pay_customer,
    pay_supplier,
    phase4b_env,
    seed_cliente,
    seed_ops,
)

phase4d_env = phase4b_env

FENCE_ENV_KEYS = (
    "FINANCIAL_WRITER_STATION_ID",
    "FERREPRO_STATION_ID",
    "FERREPRO_EXPECTED_STATION_IDS",
    "FERREPRO_DEPLOYMENT_PROFILE",
)


@contextmanager
def station_context(current="W01", writer=None, expected=None, profile=None):
    previous = {key: os.environ.get(key) for key in FENCE_ENV_KEYS}
    try:
        os.environ["FERREPRO_STATION_ID"] = current
        if writer:
            os.environ["FINANCIAL_WRITER_STATION_ID"] = writer
        else:
            os.environ.pop("FINANCIAL_WRITER_STATION_ID", None)
        if expected:
            os.environ["FERREPRO_EXPECTED_STATION_IDS"] = ",".join(expected)
        else:
            os.environ.pop("FERREPRO_EXPECTED_STATION_IDS", None)
        if profile:
            os.environ["FERREPRO_DEPLOYMENT_PROFILE"] = profile
        else:
            os.environ.pop("FERREPRO_DEPLOYMENT_PROFILE", None)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
