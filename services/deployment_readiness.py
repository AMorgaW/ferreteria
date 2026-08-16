# -*- coding: utf-8 -*-
"""Preflight de release 4D. No modifica negocio ni aplica inventario real.

Salida: READY o NOT_READY + blockers exactos.
No marca REAL_INVENTORY_APPLIED. No abre caja comercial. No requiere Supabase.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional

# Permite el entrypoint documentado desde la raíz del repo:
# `python services/deployment_readiness.py --production`.
if __package__ in (None, ""):
    repo_root = str(Path(__file__).resolve().parents[1])
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

from services.financial_writer_fence import (
    configured_financial_writer,
    current_station_id,
    expected_station_ids,
    is_production_profile,
    station_id_is_valid,
    writer_matches_expected,
)

INVENTORY_COMMERCIAL_STATUS = "PENDING FINAL DEPLOYMENT"
CASH_COMMERCIAL_STATUS = "NOT EXECUTED"
SECRET_KEY_FRAGMENTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "service_role",
    "service-role",
    "api_key",
    "apikey",
    "connection_string",
    "database_url",
    "supabase_key",
)


@dataclass
class ReadinessReport:
    ready: bool
    blockers: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    inventory_commercial_status: str = INVENTORY_COMMERCIAL_STATUS
    cash_commercial_status: str = CASH_COMMERCIAL_STATUS

    @property
    def status(self) -> str:
        return "READY" if self.ready else "NOT_READY"

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "blockers": list(self.blockers),
            "notes": list(self.notes),
            "inventory_commercial_status": self.inventory_commercial_status,
            "cash_commercial_status": self.cash_commercial_status,
            "inventory_flow": (
                "XLSX → VALIDATE → STAGING → MATCHING → REVIEW → DRY-RUN → "
                "APPROVE → PRE-FLIGHT → APPLY → VERIFY → COMPLETED"
            ),
        }

    def text(self) -> str:
        lines = [self.status]
        if self.blockers:
            lines.append("blockers:")
            lines.extend(f"  - {item}" for item in self.blockers)
        if self.notes:
            lines.append("notes:")
            lines.extend(f"  - {item}" for item in self.notes)
        lines.append(f"INVENTARIO COMERCIAL REAL: {self.inventory_commercial_status}")
        lines.append(f"CAJA COMERCIAL REAL: {self.cash_commercial_status}")
        return "\n".join(lines)


def _add(blockers: list, code: Optional[str]) -> None:
    if code and code not in blockers:
        blockers.append(code)


def _looks_secret(key: str) -> bool:
    lowered = str(key or "").lower()
    return any(fragment in lowered for fragment in SECRET_KEY_FRAGMENTS)


def _redact_config(config: dict) -> dict:
    safe = {}
    for key, value in (config or {}).items():
        if _looks_secret(key):
            continue
        if isinstance(value, str) and any(
            fragment in value.lower() for fragment in ("eyj", "service_role", "postgres://")
        ):
            continue
        safe[key] = value
    return safe


def _sqlite_writable(db_path: str) -> Optional[str]:
    try:
        path = os.path.abspath(db_path).replace("\\", "/")
        # mode=rw evita que un preflight diagnóstico cree una DB vacía.
        conn = sqlite3.connect(f"file:{path}?mode=rw", uri=True, timeout=5)
        try:
            conn.execute("PRAGMA busy_timeout=1000")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("ROLLBACK")
        finally:
            conn.close()
        return None
    except sqlite3.Error as exc:
        return str(exc)


def _schema_status(db_path: str) -> Optional[str]:
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            from migration_runner import default_runner

            plan = default_runner().plan(conn)
            pending = [item.version for item in plan if item.status == "PENDING"]
            mismatch = [item.version for item in plan if item.status == "CHECKSUM_MISMATCH"]
            if mismatch:
                return "SCHEMA_CHECKSUM_MISMATCH"
            if pending:
                return "SCHEMA_MIGRATIONS_PENDING"
            return None
        finally:
            conn.close()
    except Exception:
        return "SCHEMA_STATUS_UNREADABLE"


def _coordinator_sql_ok() -> Optional[str]:
    try:
        from inventory_coordinator import coordinator_sql_path

        path = coordinator_sql_path()
        if not path.is_file():
            return "COORDINATOR_SQL_MISSING"
        return None
    except Exception:
        return "COORDINATOR_SQL_MISSING"


def _backup_dir_usable(folder: str) -> Optional[str]:
    try:
        os.makedirs(folder, exist_ok=True)
        probe = os.path.join(folder, ".ferrepro_readiness_probe")
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("ok")
        os.remove(probe)
        return None
    except OSError:
        return "BACKUP_DIR_UNUSABLE"


def evaluate_readiness(
    *,
    db_path: Optional[str] = None,
    config: Optional[dict] = None,
    production: Optional[bool] = None,
    backup_dir: Optional[str] = None,
) -> ReadinessReport:
    blockers: List[str] = []
    notes: List[str] = [
        "financial writer fence is operational, not distributed serialization",
        "supabase is not required for local startup",
        "real commercial inventory apply is deferred",
        "real commercial cash open/close is deferred",
    ]
    if config is None:
        try:
            from local_first_config import load_config

            config = load_config()
        except Exception:
            config = {}
            _add(blockers, "CONFIG_UNAVAILABLE")
    else:
        config = dict(config)

    if db_path is None:
        db_path = os.environ.get("LOCAL_DB_PATH") or ""
        if not db_path:
            try:
                from local_first_db import DEFAULT_DB_PATH

                db_path = DEFAULT_DB_PATH
            except Exception:
                db_path = ""
    if not db_path:
        _add(blockers, "SQLITE_PATH_MISSING")
    elif not os.path.isfile(db_path):
        _add(blockers, "SQLITE_NOT_FOUND")
    else:
        writable_error = _sqlite_writable(db_path)
        if writable_error is not None:
            _add(blockers, "SQLITE_NOT_WRITABLE")
        else:
            _add(blockers, _schema_status(db_path))

    production_mode = is_production_profile(config) if production is None else bool(production)
    station = current_station_id()
    if not station_id_is_valid(station, production=production_mode):
        _add(blockers, "STATION_ID_INVALID")

    writer = configured_financial_writer(config)
    expected = expected_station_ids(config)
    if (production_mode or len(expected) > 1) and not writer:
        _add(blockers, "FINANCIAL_WRITER_FENCE_REQUIRED")
    if writer and expected and not writer_matches_expected(writer, expected):
        _add(blockers, "FINANCIAL_WRITER_NOT_IN_EXPECTED_STATIONS")
    if writer and not station_id_is_valid(writer, production=production_mode):
        _add(blockers, "FINANCIAL_WRITER_STATION_ID_INVALID")

    db_mode = str(config.get("db_mode") or "local").strip().lower()
    if db_mode not in ("local", "sqlite", "server"):
        _add(blockers, "REMOTE_DB_MODE_NOT_LOCAL_FIRST")

    _add(blockers, _coordinator_sql_ok())
    folder = backup_dir
    if not folder and db_path:
        folder = os.path.join(os.path.dirname(os.path.abspath(db_path)), "backups")
    if folder:
        _add(blockers, _backup_dir_usable(folder))
    else:
        _add(blockers, "BACKUP_DIR_UNUSABLE")

    report = ReadinessReport(ready=not blockers, blockers=blockers, notes=notes)
    # Guard: never claim real inventory/cash were executed.
    assert "REAL_INVENTORY_APPLIED" not in report.text()
    _redact_config(config)
    return report


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    production = "--production" in argv or "-p" in argv
    report = evaluate_readiness(production=production)
    print(report.text())
    # ASCII escapado mantiene el CLI portable en consolas Windows CP1252.
    print(json.dumps(report.as_dict(), ensure_ascii=True, indent=2))
    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
