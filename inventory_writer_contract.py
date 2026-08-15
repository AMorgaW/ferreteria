# -*- coding: utf-8 -*-
"""Marcadores productivos de writers de inventario (Fase 1E.4).

El cutover de producción NO importa tests/ ni el scanner.
El scanner sigue siendo certificación estática en tests/fase0 y tests/fase1e*.
Este módulo declara la versión y el conjunto preparado W01–W18.
"""
from __future__ import annotations

from typing import FrozenSet

WRITER_CONTRACT_VERSION = "1E.4"

PREPARED_DIRECT_WRITER_IDS: FrozenSet[str] = frozenset(
    {
        "W01",
        "W02",
        "W03",
        "W04",
        "W05",
        "W06",
        "W07",
        "W08",
        "W09",
        "W10",
        "W11",
        "W12",
        "W13",
        "W14",
        "W15",
        "W16",
        "W17",
        "W18",
    }
)

DEPRECATED_WRITER_IDS: FrozenSet[str] = frozenset({"W15"})
W04_NO_UI_CALLER = True
EXPECTED_PREPARED_COUNT = 18
CUTOVER_READY = (
    len(PREPARED_DIRECT_WRITER_IDS) == EXPECTED_PREPARED_COUNT
    and DEPRECATED_WRITER_IDS <= PREPARED_DIRECT_WRITER_IDS
)
