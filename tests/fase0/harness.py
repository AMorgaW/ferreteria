# -*- coding: utf-8 -*-
"""Harness Fase 0: BD temporal desde el esquema oficial. Nunca copia ferreteria.db."""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

REPO_FERRETERIA_DB = REPO_ROOT / "ferreteria.db"


@dataclass
class Fase0Env:
    db_path: Path
    db: object

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def insert_proveedor(self, conn: sqlite3.Connection, proveedor_id: int = 1,
                         nombre: str = "Proveedor Fase0") -> int:
        conn.execute(
            "INSERT INTO proveedores (id, nombre, activo) VALUES (?, ?, 1)",
            (proveedor_id, nombre),
        )
        return proveedor_id

    def insert_producto(
        self,
        conn: sqlite3.Connection,
        producto_id: int = 1,
        nombre: str = "Tornillo Fase0",
        stock: float = 50,
        codigo: str = "TEST-F0-001",
        precio_venta: float = 1000,
        proveedor_id: Optional[int] = 1,
        local_id: Optional[str] = None,
    ) -> int:
        cols = [
            "id", "codigo_barras", "nombre", "precio_venta", "stock",
            "activo", "proveedor_id",
        ]
        vals = [
            producto_id, codigo, nombre, precio_venta, stock, 1, proveedor_id,
        ]
        if local_id:
            cols.append("local_id")
            vals.append(local_id)
        placeholders = ",".join("?" * len(cols))
        conn.execute(
            f"INSERT INTO productos ({', '.join(cols)}) VALUES ({placeholders})",
            vals,
        )
        return producto_id


def _patch_local_paths(db_path: Path) -> dict:
    """Redirige pg_compat / local_first_db / DatabaseManager al tempfile."""
    os.environ["DB_MODE"] = "local"
    os.environ["LOCAL_DB_PATH"] = str(db_path)

    import database
    import local_first_db
    import pg_compat

    snapshot = {
        "pg_mode": pg_compat.DB_MODE,
        "pg_path": pg_compat.LOCAL_DB_PATH,
        "lf_path": local_first_db.DEFAULT_DB_PATH,
        "schema_init": database.DatabaseManager._schema_initialized,
        "env_mode": None,
        "env_path": None,
    }
    pg_compat.DB_MODE = "local"
    pg_compat.LOCAL_DB_PATH = str(db_path)
    local_first_db.DEFAULT_DB_PATH = str(db_path)
    database.DatabaseManager._schema_initialized = False
    return snapshot


def _restore_local_paths(snapshot: dict) -> None:
    import database
    import local_first_db
    import pg_compat

    pg_compat.DB_MODE = snapshot["pg_mode"]
    pg_compat.LOCAL_DB_PATH = snapshot["pg_path"]
    local_first_db.DEFAULT_DB_PATH = snapshot["lf_path"]
    database.DatabaseManager._schema_initialized = snapshot["schema_init"]


@contextmanager
def official_temp_db() -> Iterator[Fase0Env]:
    """Crea SQLite vacío con crear_estructura_completa + ensure_local_first_schema."""
    tmp = tempfile.TemporaryDirectory(prefix="ferrepro-fase0-")
    db_path = Path(tmp.name) / "ferrepro-fase0.db"
    if db_path.resolve() == REPO_FERRETERIA_DB.resolve():
        tmp.cleanup()
        raise RuntimeError("El harness se negó a usar ferreteria.db del repositorio.")
    if REPO_FERRETERIA_DB.exists():
        # Defensa: jamás copiar la BD de trabajo.
        pass

    snapshot = _patch_local_paths(db_path)
    try:
        import database

        db = database.DatabaseManager(str(db_path))
        resolved = Path(db_path).resolve()
        if resolved == REPO_FERRETERIA_DB.resolve():
            raise RuntimeError("DatabaseManager apuntó a ferreteria.db del repo.")
        if not db_path.exists():
            raise RuntimeError("El esquema oficial no materializó la BD temporal.")
        yield Fase0Env(db_path=db_path, db=db)
    finally:
        _restore_local_paths(snapshot)
        tmp.cleanup()
