# -*- coding: utf-8 -*-
"""Limpia registros HUÉRFANOS en Supabase: filas que existen en Supabase pero
NO en la base local (la fuente de verdad). Útil para retirar datos de prueba
o residuos. Por seguridad NO borra nada sin --apply (modo dry-run por defecto).

Uso:
  python scripts/limpiar_huerfanos.py            # solo muestra qué borraría
  python scripts/limpiar_huerfanos.py --apply    # borra de verdad
"""
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from local_sync import load_env

load_env()
import psycopg2

LOCAL = os.environ.get("LOCAL_DB_PATH", os.path.join(ROOT, "ferreteria.db"))

# Orden FK-seguro: dependientes primero, padres al final.
ORDEN = [
    "detalle_ventas", "detalle_compras", "abonos_ventas", "abonos_compras",
    "cuentas_por_cobrar", "movimientos", "movimientos_inventario",
    "egresos_caja", "historial_precios", "auditoria",
    "ventas", "compras", "cierres_caja",
    "productos", "clientes", "proveedores", "usuarios",
]


def main():
    aplicar = "--apply" in sys.argv
    loc = sqlite3.connect(LOCAL)
    remote = psycopg2.connect(os.environ["SUPABASE_URI"], connect_timeout=10)
    cur = remote.cursor()
    print("MODO:", "APLICAR (borrado real)" if aplicar else "DRY-RUN (solo muestra)")
    total = 0
    for t in ORDEN:
        try:
            l_ids = {r[0] for r in loc.execute(f"SELECT id FROM {t}")}
        except sqlite3.Error:
            continue
        try:
            cur.execute(f"SELECT id FROM {t}")
            s_ids = {r[0] for r in cur.fetchall()}
        except Exception:
            remote.rollback()
            continue
        huer = sorted(s_ids - l_ids)
        if not huer:
            continue
        total += len(huer)
        print(f"  {t:22} {len(huer):>4} huérfanos: {huer[:20]}")
        if aplicar:
            for hid in huer:
                cur.execute(f"DELETE FROM {t} WHERE id = %s", (hid,))
            remote.commit()
    print("-" * 50)
    if total == 0:
        print("No hay huérfanos. Supabase está limpio respecto al local.")
    elif aplicar:
        print(f"Eliminados {total} registros huérfanos de Supabase.")
    else:
        print(f"{total} huérfanos detectados. Ejecuta con --apply para borrarlos.")
    loc.close()
    remote.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
