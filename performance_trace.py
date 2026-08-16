# -*- coding: utf-8 -*-
"""Instrumentación ligera de responsiveness para startup, navegación y sync."""
from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import contextmanager


PROCESS_STARTED_AT = time.perf_counter()
_LOGGER = logging.getLogger("ferrepro.performance")


def mark(operation: str, started_at: float | None = None, **fields) -> float:
    """Registra una medición estructurada y devuelve su duración en ms."""
    now = time.perf_counter()
    duration_ms = (now - started_at) * 1000.0 if started_at is not None else 0.0
    data = {
        "operation": operation,
        "duration_ms": f"{duration_ms:.1f}",
        "thread": threading.current_thread().name,
        **fields,
    }
    message = "[PERF] " + " ".join(f"{key}={value}" for key, value in data.items())
    _LOGGER.info(message)
    if os.environ.get("FERREPRO_PERF_STDOUT", "").strip() == "1":
        print(message)
    return duration_ms


@contextmanager
def timed(operation: str, **fields):
    started_at = time.perf_counter()
    try:
        yield
    finally:
        mark(operation, started_at, **fields)
