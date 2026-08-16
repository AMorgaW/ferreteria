# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from legacy_sanitation import analyze_sqlite
from migration_runner import default_runner


def main() -> int:
    parser = argparse.ArgumentParser(description="FERREPRO Fase 2A: analyze/dry-run")
    parser.add_argument("--db", required=True, help="SQLite objetivo")
    parser.add_argument("--apply", action="store_true", help="aplicar migraciones seguras")
    parser.add_argument(
        "--allow-real-db",
        action="store_true",
        help="permite --apply sobre ferreteria.db; requiere autorización humana",
    )
    args = parser.parse_args()
    target = Path(args.db).resolve()
    commercial = (REPO_ROOT / "ferreteria.db").resolve()
    if args.apply and target == commercial and not args.allow_real_db:
        parser.error("se rechazó mutar ferreteria.db real sin --allow-real-db")
    if args.apply:
        conn = sqlite3.connect(str(target))
    else:
        conn = sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        report = analyze_sqlite(conn).as_dict()
        migrations = default_runner().run(conn, dry_run=not args.apply)
        print(json.dumps({
            "mode": "APPLY" if args.apply else "DRY_RUN",
            "database": str(target),
            "report": report,
            "migrations": [item.__dict__ for item in migrations],
        }, ensure_ascii=False, indent=2))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
