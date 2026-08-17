# -*- coding: utf-8 -*-
"""Lifecycle de schema SQLite: backup seguro y catálogo versionado.

Única ruta productiva para llevar una estación (fresh o legacy) a latest
antes de que los módulos 2–4 dependan de sus tablas. No crea el archivo
de la DB: eso es instalación nueva explícita vía DatabaseManager.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from backup_manager import (
    SQLITE_HEADER,
    BackupError,
    BackupResult,
    crear_backup_result,
)
from migration_runner import (
    DEFAULT_MIGRATIONS,
    MigrationError,
    MigrationRunner,
    MigrationStatus,
    default_runner,
)

PRE_MIGRATION_MOTIVO = "pre-migration"


class SchemaLifecycleError(RuntimeError):
    """Fallo cerrado del lifecycle. No se continúa con schema a medias."""


@dataclass(frozen=True)
class SchemaLifecycleResult:
    db_path: str
    already_latest: bool
    backup: Optional[BackupResult]
    statuses: Tuple[MigrationStatus, ...]
    latest_version: str

    @property
    def pending_before(self) -> Tuple[str, ...]:
        return tuple(
            item.version
            for item in self.statuses
            if item.status == "PENDING"
        )


def catalog_latest_version(runner: Optional[MigrationRunner] = None) -> str:
    migrations = (runner or default_runner()).migrations
    if not migrations:
        raise SchemaLifecycleError("el catálogo de migraciones está vacío")
    return migrations[-1].version


def _looks_like_sqlite(path: str) -> bool:
    try:
        with open(path, "rb") as handle:
            return handle.read(16) == SQLITE_HEADER
    except OSError:
        return False


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _require_existing_sqlite(db_path: str) -> str:
    path = os.path.abspath(db_path)
    if not os.path.exists(path):
        raise SchemaLifecycleError(
            "SQLITE_NOT_FOUND: no existe la base SQLite local esperada: "
            f"{path}. El lifecycle no crea una DB comercial vacía."
        )
    if not os.path.isfile(path):
        raise SchemaLifecycleError(
            f"la ruta de SQLite no es un archivo: {path}"
        )
    if not _looks_like_sqlite(path):
        raise SchemaLifecycleError(
            "SQLITE_NOT_SQLITE: el archivo no es una base SQLite válida: "
            f"{path}"
        )
    return path


def inspect_sqlite_schema(
    db_path: str,
    *,
    runner: Optional[MigrationRunner] = None,
) -> Tuple[MigrationStatus, ...]:
    """Plan de migraciones. No crea backup ni aplica DDL."""
    path = _require_existing_sqlite(db_path)
    runner = runner or default_runner()
    conn = _connect(path)
    try:
        return runner.plan(conn)
    except MigrationError as exc:
        raise SchemaLifecycleError(str(exc)) from exc
    finally:
        conn.close()


def schema_is_latest(
    db_path: str,
    *,
    runner: Optional[MigrationRunner] = None,
) -> bool:
    plan = inspect_sqlite_schema(db_path, runner=runner)
    return bool(plan) and all(item.status == "APPLIED" for item in plan)


def _verify_latest(conn, runner: MigrationRunner) -> Tuple[MigrationStatus, ...]:
    plan = runner.plan(conn)
    pending = [item.version for item in plan if item.status == "PENDING"]
    mismatch = [item.version for item in plan if item.status == "CHECKSUM_MISMATCH"]
    if mismatch:
        raise SchemaLifecycleError(
            "SCHEMA_CHECKSUM_MISMATCH: "
            + ", ".join(mismatch)
        )
    if pending:
        raise SchemaLifecycleError(
            "SCHEMA_NOT_LATEST: migraciones pendientes después de aplicar: "
            + ", ".join(pending)
        )
    return plan


def ensure_sqlite_schema_current(
    db_path: str,
    *,
    runner: Optional[MigrationRunner] = None,
    backup_fn: Optional[Callable[..., Optional[BackupResult]]] = None,
    backup_dir: Optional[str] = None,
) -> SchemaLifecycleResult:
    """Lleva la SQLite de estación a latest. Idempotente y rerunnable.

    Si ya está latest: no backup, no DDL destructivo.
    Si hay pendientes: backup WAL-safe + manifest; solo entonces
    ``MigrationRunner.run(..., dry_run=False)``.
    Nunca crea el archivo si falta.
    """
    path = _require_existing_sqlite(db_path)
    runner = runner or default_runner()
    latest = catalog_latest_version(runner)
    make_backup = backup_fn or crear_backup_result

    conn = _connect(path)
    try:
        before = runner.plan(conn)
    except MigrationError as exc:
        conn.close()
        raise SchemaLifecycleError(str(exc)) from exc

    mismatch = [item.version for item in before if item.status == "CHECKSUM_MISMATCH"]
    if mismatch:
        conn.close()
        raise SchemaLifecycleError(
            "SCHEMA_CHECKSUM_MISMATCH: no se migrará hasta resolver "
            + ", ".join(mismatch)
        )

    pending = [item for item in before if item.status == "PENDING"]
    if not pending:
        conn.close()
        return SchemaLifecycleResult(
            db_path=path,
            already_latest=True,
            backup=None,
            statuses=before,
            latest_version=latest,
        )

    conn.close()

    try:
        backup = make_backup(
            motivo=PRE_MIGRATION_MOTIVO,
            db_path=path,
            dest_dir=backup_dir,
        )
    except BackupError as exc:
        raise SchemaLifecycleError(
            f"BACKUP_FAILED: backup pre-migración falló; "
            f"no se aplicaron migraciones: {exc}"
        ) from exc
    except Exception as exc:
        raise SchemaLifecycleError(
            f"BACKUP_FAILED: backup pre-migración falló; "
            f"no se aplicaron migraciones: {exc}"
        ) from exc
    if backup is None:
        raise SchemaLifecycleError(
            "BACKUP_FAILED: backup pre-migración no produjo snapshot; "
            "no se aplicaron migraciones"
        )

    conn = _connect(path)
    try:
        try:
            statuses = runner.run(conn, dry_run=False)
        except MigrationError as exc:
            raise SchemaLifecycleError(
                f"MIGRATION_FAILED: {exc}"
            ) from exc
        _verify_latest(conn, runner)
    finally:
        conn.close()

    return SchemaLifecycleResult(
        db_path=path,
        already_latest=False,
        backup=backup,
        statuses=statuses,
        latest_version=latest,
    )


assert DEFAULT_MIGRATIONS[-1].version == "20260816_010"
