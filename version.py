# -*- coding: utf-8 -*-
"""Versión del producto y del esquema de datos (para migraciones)."""

APP_NAME = "FERREPRO"
__version__ = "4.0.0"

# SCHEMA_VERSION es una etiqueta escrita en sync_state tras un bootstrap
# exitoso. NO selecciona ni ordena migraciones: el esquema se aplica con
# CREATE TABLE IF NOT EXISTS + helpers idempotentes en schema_bootstrap.py.
# Incrementarlo no cambia el comportamiento hasta que exista un runner
# versionado. No se finge que controla migraciones.
SCHEMA_VERSION = 4
