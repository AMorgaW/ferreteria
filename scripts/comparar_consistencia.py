# -*- coding: utf-8 -*-
"""Comparador de consistencia SQLite local <-> Supabase (solo lectura).

Para cada tabla replicada compara: cantidad de registros, IDs faltantes
(en local y no en Supabase), IDs huérfanos (en Supabase y no en local),
y alineación de local_id. No modifica ningún dato.

Uso:  python scripts/comparar_consistencia.py
"""
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from local_sync import SupabaseSyncService, load_env

load_env()
import psycopg2

LOCAL = os.environ.get("LOCAL_DB_PATH", os.path.join(ROOT, "ferreteria.db"))


def main():
    loc = sqlite3.connect(LOCAL)
    loc.row_factory = sqlite3.Row
    try:
        remote = psycopg2.connect(os.environ["SUPABASE_URI"], connect_timeout=10)
    except Exception as exc:
        print("No se pudo conectar a Supabase:", exc)
        return 1
    cur = remote.cursor()

    print(f"{'TABLA':22}{'LOCAL':>7}{'SUPABASE':>9}{'  FALTAN':>9}"
          f"{'HUERFANOS':>11}{'  local_id'}")
    print("-" * 72)
    problemas = 0
    for table, _ in SupabaseSyncService.SYNCED_TABLES:
        try:
            l_ids = {r["id"] for r in loc.execute(f"SELECT id FROM {table}")}
        except sqlite3.Error:
            continue
        try:
            cur.execute(f"SELECT id FROM {table}")
            s_ids = {r[0] for r in cur.fetchall()}
            cur.execute(f"SELECT COUNT(*) FROM {table} WHERE local_id IS NULL")
            null_lid = cur.fetchone()[0]
        except Exception:
            remote.rollback()
            print(f"{table:22}{'(no existe en Supabase)':>40}")
            continue
        faltan = l_ids - s_ids       # en local, no en Supabase
        huerfanos = s_ids - l_ids    # en Supabase, no en local
        estado_lid = "todos" if null_lid == 0 else f"{null_lid} sin id"
        if faltan or huerfanos or null_lid:
            problemas += 1
        print(f"{table:22}{len(l_ids):>7}{len(s_ids):>9}{len(faltan):>9}"
              f"{len(huerfanos):>11}{'   ' + estado_lid}")
        if faltan:
            print(f"    -> IDs en LOCAL sin replicar: {sorted(faltan)[:15]}")
        if huerfanos:
            print(f"    -> IDs HUÉRFANOS en Supabase: {sorted(huerfanos)[:15]}")

    print("-" * 72)
    if problemas == 0:
        print("RESULTADO: CONSISTENCIA TOTAL — local y Supabase coinciden.")
    else:
        print(f"RESULTADO: {problemas} tabla(s) con diferencias. "
              f"Ejecuta backfill_to_remote() para reconciliar.")
    loc.close()
    remote.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
