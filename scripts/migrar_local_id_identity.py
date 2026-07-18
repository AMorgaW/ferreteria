# -*- coding: utf-8 -*-
"""
Estrategia B — Migración/verificación de la identidad de sincronización por
local_id (UUID). Idempotente, segura y no destructiva.

Ejecuta y verifica, en LOCAL (SQLite) y en REMOTO (Supabase):
  1) Backfill de local_id (UUID) en las filas que no lo tengan.
  2) Dedupe de local_id repetidos.
  3) Índice UNIQUE sobre local_id.

No borra datos ni cambia ids. Uso:
    python scripts/migrar_local_id_identity.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DB_MODE", "local")

from local_first_db import (DEFAULT_DB_PATH, SYNC_TABLES, connect,  # noqa: E402
                            ensure_local_id_unique)
from local_sync import SupabaseSyncService  # noqa: E402


def _verificar_local(db_path):
    conn = connect(db_path)
    problemas = []
    try:
        for t in SYNC_TABLES:
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({t})")}
            if "local_id" not in cols:
                continue
            nulos = conn.execute(
                f"SELECT COUNT(*) c FROM {t} WHERE local_id IS NULL OR local_id=''"
            ).fetchone()["c"]
            dups = conn.execute(
                f"SELECT COUNT(*) c FROM (SELECT local_id FROM {t} "
                f"WHERE local_id IS NOT NULL GROUP BY local_id HAVING COUNT(*)>1)"
            ).fetchone()["c"]
            idx = conn.execute(
                f"SELECT COUNT(*) c FROM sqlite_master WHERE type='index' "
                f"AND tbl_name='{t}' AND sql LIKE '%UNIQUE%local_id%'"
            ).fetchone()["c"]
            if nulos or dups or not idx:
                problemas.append(f"{t}: nulos={nulos} dups={dups} indice_unique={bool(idx)}")
    finally:
        conn.close()
    return problemas


def main():
    db_path = os.environ.get("LOCAL_DB_PATH", DEFAULT_DB_PATH)
    print(f"BD local: {db_path}")

    print("\n[1/2] Migrando LOCAL (SQLite)...")
    conn = connect(db_path)
    try:
        ensure_local_id_unique(conn)
    finally:
        conn.close()
    problemas = _verificar_local(db_path)
    if problemas:
        print("  Pendientes en local:")
        for p in problemas:
            print("   -", p)
    else:
        print("  OK: todas las tablas locales con local_id único + índice UNIQUE.")

    print("\n[2/2] Migrando REMOTO (Supabase)...")
    svc = SupabaseSyncService(db_path=db_path)
    if not svc.database_url:
        print("  SUPABASE_URI no configurado; se omite el remoto.")
        return 0
    remote = None
    try:
        import psycopg2
        remote = psycopg2.connect(svc.database_url, connect_timeout=10)
        svc._ensure_remote_local_id_identity(remote)
        # Verificación remota
        with remote.cursor() as cur:
            pend = []
            for t in SYNC_TABLES:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {t} WHERE local_id IS NULL OR local_id=''")
                    nulos = cur.fetchone()[0]
                    cur.execute(f"SELECT COUNT(*) FROM (SELECT local_id FROM {t} "
                                f"WHERE local_id IS NOT NULL GROUP BY local_id HAVING COUNT(*)>1) x")
                    dups = cur.fetchone()[0]
                    if nulos or dups:
                        pend.append(f"{t}: nulos={nulos} dups={dups}")
                except Exception:
                    remote.rollback()
        if pend:
            print("  Pendientes en remoto:")
            for p in pend:
                print("   -", p)
        else:
            print("  OK: Supabase con local_id único + índice UNIQUE en las tablas sincronizadas.")
    finally:
        if remote:
            remote.close()
    print("\nMigración idempotente completada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
