# -*- coding: utf-8 -*-
"""Fence operacional 4D para finalizar abonos cliente y pagos proveedor.

Solo la estación designada (`financial_writer_station_id`) puede persistir
pagos. Las demás pueden leer CxC/CxP. Esto NO es serialización distribuida
ni un coordinador financiero: W01 y W02 no comparten un lock remoto.
"""
from __future__ import annotations

import os
from typing import Iterable, Optional, Sequence

from services.operational_balance import FINANCIAL_WRITER_FENCE, PaymentError

CONFIG_KEY = "financial_writer_station_id"
EXPECTED_STATIONS_KEY = "expected_station_ids"
PROFILE_KEY = "deployment_profile"
ENV_WRITER = "FINANCIAL_WRITER_STATION_ID"
ENV_CURRENT = "FERREPRO_STATION_ID"
ENV_EXPECTED = "FERREPRO_EXPECTED_STATION_IDS"
ENV_PROFILE = "FERREPRO_DEPLOYMENT_PROFILE"

_FENCE_MESSAGE = (
    "FINANCIAL_WRITER_FENCE: esta estación no puede finalizar abonos de "
    "cliente ni pagos a proveedor. Solo la estación designada ({writer}) "
    "puede hacerlo. Fence operacional, no serialización distribuida."
)
_MISSING_WRITER_MESSAGE = (
    "FINANCIAL_WRITER_FENCE: no hay estación financiera designada "
    "(FINANCIAL_WRITER_STATION_ID). Fence operacional, no serialización "
    "distribuida."
)


def _clean(value) -> str:
    return str(value or "").strip()


def _load_config(config=None) -> dict:
    if config is not None:
        return dict(config)
    from local_first_config import load_config

    return load_config()


def configured_financial_writer(config=None) -> str:
    env = _clean(os.environ.get(ENV_WRITER, ""))
    if env:
        return env
    cfg = _load_config(config)
    return _clean(cfg.get(CONFIG_KEY))


def expected_station_ids(config=None) -> tuple:
    env = _clean(os.environ.get(ENV_EXPECTED, ""))
    if env:
        return tuple(item for item in (p.strip() for p in env.split(",")) if item)
    cfg = _load_config(config)
    raw = cfg.get(EXPECTED_STATIONS_KEY) or []
    if isinstance(raw, str):
        return tuple(item for item in (p.strip() for p in raw.split(",")) if item)
    if isinstance(raw, Iterable):
        return tuple(_clean(item) for item in raw if _clean(item))
    return ()


def is_production_profile(config=None) -> bool:
    env = _clean(os.environ.get(ENV_PROFILE, "")).lower()
    if env:
        return env in ("production", "prod")
    cfg = _load_config(config)
    return _clean(cfg.get(PROFILE_KEY)).lower() in ("production", "prod")


def current_station_id(explicit=None) -> str:
    if _clean(explicit):
        return _clean(explicit)
    env = _clean(os.environ.get(ENV_CURRENT, ""))
    if env:
        return env
    from services.caja_service import resolve_station_id

    return _clean(resolve_station_id())


def station_id_is_valid(station: str, *, production: bool = False) -> bool:
    value = _clean(station)
    if not value:
        return False
    if production and value.upper() == "LOCAL":
        return False
    return True


def is_financial_writer(explicit=None, config=None) -> bool:
    writer = configured_financial_writer(config)
    if not writer:
        return not _must_fail_closed(config)
    return current_station_id(explicit) == writer


def _must_fail_closed(config=None) -> bool:
    if is_production_profile(config):
        return True
    return len(expected_station_ids(config)) > 1


def assert_can_finalize_payment(explicit_station=None, config=None) -> str:
    """Gate productivo. Llamar ANTES de persistir un abono/pago.

    Returns the current station id when allowed.
    """
    writer = configured_financial_writer(config)
    current = current_station_id(explicit_station)
    if not writer:
        if _must_fail_closed(config):
            raise PaymentError(FINANCIAL_WRITER_FENCE, _MISSING_WRITER_MESSAGE)
        return current
    if current != writer:
        raise PaymentError(
            FINANCIAL_WRITER_FENCE,
            _FENCE_MESSAGE.format(writer=writer),
        )
    return current


class FinancialWriterFence:
    """Pequeña fachada para UI y preflight."""

    def __init__(self, config=None, current_station=None):
        self.config = config
        self.current_station = current_station

    @property
    def writer(self) -> str:
        return configured_financial_writer(self.config)

    @property
    def current(self) -> str:
        return current_station_id(self.current_station)

    def can_finalize_payment(self) -> bool:
        try:
            assert_can_finalize_payment(self.current_station, self.config)
            return True
        except PaymentError:
            return False

    def assert_can_finalize_payment(self) -> str:
        return assert_can_finalize_payment(self.current_station, self.config)

    def block_reason(self) -> Optional[str]:
        try:
            assert_can_finalize_payment(self.current_station, self.config)
            return None
        except PaymentError as exc:
            return str(exc)


def payment_rejection_message(exc) -> Optional[str]:
    if isinstance(exc, PaymentError):
        return str(exc) or exc.code
    return None


def writer_matches_expected(writer: str, stations: Sequence[str]) -> bool:
    if not stations:
        return True
    return writer in set(stations)
