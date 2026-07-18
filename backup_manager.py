# -*- coding: utf-8 -*-
"""
Sistema simple de respaldos automáticos de la base de datos local (SQLite).

- Copias consistentes con WAL usando la API de backup de sqlite3.
- Nomenclatura: backups/backup_YYYY_MM_DD_HH_MM.db (no sobrescribe).
- Conserva las últimas N versiones (poda automática).
- Restauración manual (requiere reiniciar la app).
"""
import glob
import os
import shutil
import sqlite3
from datetime import datetime


def _db_path() -> str:
    from local_first_db import DEFAULT_DB_PATH
    return DEFAULT_DB_PATH


def backups_dir() -> str:
    d = os.path.join(os.path.dirname(os.path.abspath(_db_path())), "backups")
    os.makedirs(d, exist_ok=True)
    return d


def crear_backup(motivo: str = "auto") -> str | None:
    """Crea una copia consistente de la BD. Devuelve la ruta o None."""
    src = _db_path()
    if not os.path.exists(src):
        return None
    ts = datetime.now().strftime("%Y_%m_%d_%H_%M")
    dest = os.path.join(backups_dir(), f"backup_{ts}.db")
    if os.path.exists(dest):  # evitar sobrescribir respaldos del mismo minuto
        ts = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
        dest = os.path.join(backups_dir(), f"backup_{ts}.db")
    source = sqlite3.connect(src)
    destino = sqlite3.connect(dest)
    try:
        with destino:
            source.backup(destino)  # snapshot consistente (incluye WAL)
    finally:
        source.close()
        destino.close()
    return dest


def listar_backups() -> list:
    """Lista de rutas de respaldo, del más reciente al más antiguo."""
    return sorted(glob.glob(os.path.join(backups_dir(), "backup_*.db")), reverse=True)


def limpiar_antiguos(keep: int = 10) -> int:
    """Conserva los últimos `keep` respaldos; elimina el resto. Devuelve nº borrados."""
    borrados = 0
    for old in listar_backups()[keep:]:
        try:
            os.remove(old)
            borrados += 1
        except OSError:
            pass
    return borrados


def auto_backup(keep: int = 10, max_por_dia: int = 1) -> str | None:
    """Respaldo de arranque: crea una copia (limitada por día) y poda las viejas."""
    hoy = datetime.now().strftime("%Y_%m_%d")
    del_hoy = [b for b in listar_backups()
               if os.path.basename(b).startswith(f"backup_{hoy}")]
    creado = None
    if len(del_hoy) < max_por_dia:
        creado = crear_backup(motivo="auto-inicio")
    limpiar_antiguos(keep=keep)
    return creado


def restaurar_backup(path: str) -> tuple:
    """Restaura un respaldo sobre la BD viva. Requiere reiniciar la app.
    Antes crea un respaldo de seguridad del estado actual."""
    src = _db_path()
    if not os.path.exists(path):
        return False, "El archivo de respaldo no existe"
    # Respaldo de seguridad del estado actual antes de sobrescribir
    try:
        crear_backup(motivo="pre-restore")
    except Exception:
        pass
    # Eliminar WAL/SHM para evitar mezclar estado nuevo con el viejo
    for ext in ("-wal", "-shm"):
        p = src + ext
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass
    shutil.copy2(path, src)
    return True, "Respaldo restaurado. Reinicie la aplicación para aplicar los cambios."
