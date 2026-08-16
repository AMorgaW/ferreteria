# -*- coding: utf-8 -*-
"""
Respaldos consistentes de SQLite local (Fase 4D).

- API sqlite3.backup (incluye WAL). No copia cruda de un .db activo.
- Manifest JSON: timestamp, station/device, schema version, SHA-256.
- Restore explícito: valida archivo + checksum, crea safety backup, no corre
  en startup. Offline. No sube a la nube.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

SQLITE_HEADER = b"SQLite format 3\x00"
MANIFEST_SUFFIX = ".manifest.json"


def _connect(db_file: str, readonly: bool = False):
    if readonly:
        path = os.path.abspath(db_file).replace("\\", "/")
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    return sqlite3.connect(db_file)


class BackupError(RuntimeError):
    """Backup o restore rechazado. No se pisa la DB destino."""


@dataclass(frozen=True)
class BackupResult:
    db_path: str
    manifest_path: str
    sha256: str
    created_at: str
    station_id: str
    schema_version: Optional[str]


def _db_path() -> str:
    from local_first_db import DEFAULT_DB_PATH

    return DEFAULT_DB_PATH


def backups_dir(db_path: Optional[str] = None) -> str:
    base = os.path.dirname(os.path.abspath(db_path or _db_path()))
    d = os.path.join(base, "backups")
    os.makedirs(d, exist_ok=True)
    return d


def _manifest_path_for(db_file: str) -> str:
    if db_file.endswith(".db"):
        return db_file[: -len(".db")] + MANIFEST_SUFFIX
    return db_file + MANIFEST_SUFFIX


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _looks_like_sqlite(path: str) -> bool:
    try:
        with open(path, "rb") as handle:
            return handle.read(16) == SQLITE_HEADER
    except OSError:
        return False


def _schema_version(db_file: str) -> Optional[str]:
    conn = _connect(db_file, readonly=True)
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        if not row:
            return None
        latest = conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
        ).fetchone()
        return str(latest[0]) if latest else None
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def _integrity_ok(db_file: str) -> bool:
    conn = _connect(db_file, readonly=True)
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        return bool(row) and str(row[0]).lower() == "ok"
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def _sqlite_backup(src_path: str, dest_path: str) -> None:
    source = sqlite3.connect(src_path)
    destino = sqlite3.connect(dest_path)
    try:
        with destino:
            source.backup(destino)
    finally:
        source.close()
        destino.close()


def _station_meta() -> tuple:
    station_id = ""
    device_id = ""
    try:
        from services.financial_writer_fence import current_station_id

        station_id = current_station_id()
    except Exception:
        station_id = ""
    try:
        from local_first_config import get_or_create_device_id

        device_id = get_or_create_device_id()
    except Exception:
        device_id = ""
    return station_id, device_id


def _write_manifest(result: BackupResult, motivo: str, device_id: str) -> None:
    payload = {
        "created_at": result.created_at,
        "motivo": motivo,
        "filename": os.path.basename(result.db_path),
        "station_id": result.station_id,
        "device_id": device_id,
        "schema_version": result.schema_version,
        "sha256": result.sha256,
        "sqlite_backup_api": True,
    }
    folder = os.path.dirname(os.path.abspath(result.manifest_path))
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=folder,
            prefix=".ferrepro_manifest_",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, result.manifest_path)
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def read_manifest(db_file: str) -> Optional[dict]:
    path = _manifest_path_for(db_file)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            stored = json.load(handle)
    except (OSError, ValueError) as exc:
        raise BackupError(f"manifest ilegible: {exc}") from exc
    if not isinstance(stored, dict):
        raise BackupError("manifest inválido")
    return stored


def _validate_manifest_contract(db_file: str, manifest: dict) -> None:
    required = {
        "created_at",
        "motivo",
        "filename",
        "station_id",
        "device_id",
        "schema_version",
        "sha256",
        "sqlite_backup_api",
    }
    if not required.issubset(manifest):
        missing = ", ".join(sorted(required.difference(manifest)))
        raise BackupError(f"manifest inválido; faltan campos: {missing}")
    if manifest.get("filename") != os.path.basename(db_file):
        raise BackupError("manifest inválido; filename no corresponde al respaldo")
    if manifest.get("sqlite_backup_api") is not True:
        raise BackupError("manifest inválido; origen de backup no certificado")
    checksum = str(manifest.get("sha256") or "")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", checksum):
        raise BackupError("manifest inválido; checksum SHA-256 ausente o mal formado")
    try:
        datetime.fromisoformat(str(manifest.get("created_at") or ""))
    except ValueError as exc:
        raise BackupError("manifest inválido; created_at no es ISO-8601") from exc
    for key in ("motivo", "station_id", "device_id"):
        if not isinstance(manifest.get(key), str):
            raise BackupError(f"manifest inválido; {key} debe ser texto")
    if manifest.get("schema_version") is not None and not isinstance(
        manifest.get("schema_version"), str
    ):
        raise BackupError("manifest inválido; schema_version debe ser texto o null")


def crear_backup(
    motivo: str = "auto",
    db_path: Optional[str] = None,
    dest_dir: Optional[str] = None,
) -> Optional[str]:
    """Crea una copia consistente. Devuelve la ruta del .db o None si no hay origen."""
    result = crear_backup_result(motivo=motivo, db_path=db_path, dest_dir=dest_dir)
    return None if result is None else result.db_path


def crear_backup_result(
    motivo: str = "auto",
    db_path: Optional[str] = None,
    dest_dir: Optional[str] = None,
) -> Optional[BackupResult]:
    src = db_path or _db_path()
    if not os.path.exists(src):
        return None
    folder = dest_dir or backups_dir(src)
    os.makedirs(folder, exist_ok=True)
    now = datetime.now()
    created_at = now.isoformat(timespec="seconds")
    ts = now.strftime("%Y_%m_%d_%H_%M_%S_%f")
    dest = os.path.join(folder, f"backup_{ts}.db")
    _sqlite_backup(src, dest)
    if not _looks_like_sqlite(dest) or not _integrity_ok(dest):
        try:
            os.remove(dest)
        except OSError:
            pass
        raise BackupError("el snapshot SQLite no pasó integrity_check")
    station_id, device_id = _station_meta()
    result = BackupResult(
        db_path=dest,
        manifest_path=_manifest_path_for(dest),
        sha256=_sha256_file(dest),
        created_at=created_at,
        station_id=station_id,
        schema_version=_schema_version(dest),
    )
    _write_manifest(result, motivo=motivo, device_id=device_id)
    return result


def listar_backups(db_path: Optional[str] = None, dest_dir: Optional[str] = None) -> list:
    folder = dest_dir or backups_dir(db_path)
    return sorted(glob.glob(os.path.join(folder, "backup_*.db")), reverse=True)


def limpiar_antiguos(
    keep: int = 10,
    db_path: Optional[str] = None,
    dest_dir: Optional[str] = None,
) -> int:
    borrados = 0
    for old in listar_backups(db_path=db_path, dest_dir=dest_dir)[keep:]:
        try:
            os.remove(old)
            manifest = _manifest_path_for(old)
            if os.path.exists(manifest):
                os.remove(manifest)
            borrados += 1
        except OSError:
            pass
    return borrados


def auto_backup(keep: int = 10, max_por_dia: int = 1) -> Optional[str]:
    hoy = datetime.now().strftime("%Y_%m_%d")
    del_hoy = [
        item
        for item in listar_backups()
        if os.path.basename(item).startswith(f"backup_{hoy}")
    ]
    creado = None
    if len(del_hoy) < max_por_dia:
        creado = crear_backup(motivo="auto-inicio")
    limpiar_antiguos(keep=keep)
    return creado


def validate_backup_file(path: str) -> dict:
    if not os.path.exists(path):
        raise BackupError("El archivo de respaldo no existe")
    if not _looks_like_sqlite(path):
        raise BackupError("el archivo no es un SQLite válido")
    if not _integrity_ok(path):
        raise BackupError("integrity_check falló; respaldo corrupto")
    manifest = read_manifest(path)
    if manifest is None:
        raise BackupError("manifest requerido; no se puede validar el checksum")
    _validate_manifest_contract(path, manifest)
    actual = _sha256_file(path)
    if actual.lower() != str(manifest["sha256"]).lower():
        raise BackupError("checksum SHA-256 no coincide con el manifest")
    return manifest


def restaurar_backup(
    path: str,
    db_path: Optional[str] = None,
    dest_dir: Optional[str] = None,
) -> tuple:
    """Restaura un respaldo sobre la BD destino. Nunca corre en startup.

    Antes de reemplazar: valida archivo/checksum y crea safety backup del destino.
    """
    src = db_path or _db_path()
    try:
        validate_backup_file(path)
    except BackupError as exc:
        return False, str(exc)
    folder = dest_dir or backups_dir(src)
    safety = None
    if os.path.exists(src):
        try:
            safety = crear_backup_result(
                motivo="pre-restore",
                db_path=src,
                dest_dir=folder,
            )
        except Exception as exc:
            return False, f"no se pudo crear safety backup: {exc}"
        if safety is None:
            return False, "no se pudo crear safety backup del destino"
    try:
        _sqlite_backup(path, src)
        if not _looks_like_sqlite(src) or not _integrity_ok(src):
            raise BackupError("la DB restaurada no pasó integrity_check")
    except Exception as exc:
        if safety is not None:
            try:
                _sqlite_backup(safety.db_path, src)
                if not _looks_like_sqlite(src) or not _integrity_ok(src):
                    raise BackupError("la recuperación no pasó integrity_check")
            except Exception as recovery_exc:
                return (
                    False,
                    "restore falló y el estado destino es INCIERTO; "
                    f"safety backup preservado en {safety.db_path}: {recovery_exc}",
                )
            return (
                False,
                "restore falló; destino RECUPERADO desde safety backup "
                f"{safety.db_path}: {exc}",
            )
        return False, f"restore SQLite falló antes de crear destino válido: {exc}"
    return True, "Respaldo restaurado. Reinicie la aplicación para aplicar los cambios."
