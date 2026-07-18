# -*- coding: utf-8 -*-
"""Versión del producto y del esquema de datos (para migraciones)."""

APP_NAME = "FERREPRO"
__version__ = "4.0.0"

# Se incrementa cuando cambia el esquema de la base de datos. Las migraciones
# son idempotentes (ADD COLUMN / CREATE TABLE IF NOT EXISTS), por lo que datos
# de versiones anteriores siguen siendo compatibles hacia adelante.
SCHEMA_VERSION = 4
