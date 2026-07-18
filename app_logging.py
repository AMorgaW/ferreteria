# -*- coding: utf-8 -*-
"""
Sistema de logs y diagnóstico para producción.

- Escribe en logs/ferreteria.log junto a la base de datos (o al .exe si está
  congelado).
- Rotación automática por tamaño (2 MB) conservando 5 históricos.
- Captura excepciones no controladas (sys.excepthook).
- Seguro de llamar varias veces (no duplica handlers).
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

_CONFIGURADO = False
MAX_BYTES = 2 * 1024 * 1024  # 2 MB por archivo
BACKUPS = 5


def _base_dir():
    # Los logs viven junto a la base de datos persistente. Cuando el launcher
    # define LOCAL_DB_PATH (%PROGRAMDATA%\FERREPRO en modo congelado) se usa esa
    # carpeta — escribible aunque el .exe esté en Program Files (solo lectura).
    db = os.environ.get("LOCAL_DB_PATH")
    if db:
        return os.path.dirname(os.path.abspath(db))
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    try:
        from local_first_db import DEFAULT_DB_PATH
        return os.path.dirname(os.path.abspath(DEFAULT_DB_PATH))
    except Exception:
        return os.path.dirname(os.path.abspath(__file__))


def logs_dir():
    d = os.path.join(_base_dir(), "logs")
    os.makedirs(d, exist_ok=True)
    return d


def setup_logging(nivel=logging.INFO, componente="app"):
    """Configura el logging global. Devuelve la ruta del archivo de log."""
    global _CONFIGURADO
    ruta = os.path.join(logs_dir(), "ferreteria.log")
    if _CONFIGURADO:
        return ruta

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh = RotatingFileHandler(ruta, maxBytes=MAX_BYTES, backupCount=BACKUPS,
                             encoding="utf-8")
    fh.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(nivel)
    # Evitar handlers duplicados si se reconfigura
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        root.addHandler(fh)

    # Consola (errores) — útil en modo desarrollo / run_*.bat
    if not any(isinstance(h, logging.StreamHandler) and
               not isinstance(h, RotatingFileHandler) for h in root.handlers):
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        ch.setLevel(logging.WARNING)
        root.addHandler(ch)

    # Capturar excepciones no controladas
    def _excepthook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logging.getLogger("uncaught").critical(
            "Excepción no controlada", exc_info=(exc_type, exc_value, exc_tb))
    sys.excepthook = _excepthook

    _CONFIGURADO = True
    logging.getLogger(componente).info("=== Logging iniciado (%s) ===", componente)
    return ruta
