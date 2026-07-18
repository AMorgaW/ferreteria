# -*- coding: utf-8 -*-
"""
Resincroniza las secuencias (auto-increment) de PostgreSQL/Supabase.

Necesario tras haber cargado datos con IDs explícitos (p. ej. la sincronización
local-first SQLite -> Supabase): en ese caso la secuencia de cada tabla quedó
por debajo del MAX(id) real y un INSERT nuevo intenta reutilizar un id existente
(error "duplicate key value violates unique constraint ..._pkey").

Este script recorre todas las tablas del esquema public que tengan una columna
`id` con secuencia asociada y hace `setval(seq, MAX(id))`. Es una operación
SEGURA y NO destructiva: solo adelanta el contador de la secuencia.

Uso:  DB_MODE=remote python scripts/fix_supabase_sequences.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Forzar modo remoto: este script solo tiene sentido contra Postgres/Supabase.
os.environ["DB_MODE"] = "remote"
import pg_compat  # noqa: E402


def main() -> int:
    conn = pg_compat.connect()
    cur = conn.cursor()

    # Tablas del esquema public con columna 'id'.
    cur.execute("""
        SELECT table_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND column_name = 'id'
        ORDER BY table_name
    """)
    tablas = [r[0] for r in cur.fetchall()]

    arregladas, creadas = 0, 0
    for t in tablas:
        # ¿La columna id ya tiene secuencia asociada? (serial/identity)
        cur.execute("SELECT pg_get_serial_sequence(%s, 'id')", (t,))
        row = cur.fetchone()
        seq = row[0] if row else None

        if not seq:
            # La columna id NO tiene auto-increment: crear secuencia, fijarla
            # como DEFAULT de la columna y dejarla en MAX(id). Necesario para
            # que los INSERT de la app (sin id explícito) funcionen.
            seq = f"{t}_id_seq"
            cur.execute(f"CREATE SEQUENCE IF NOT EXISTS {seq} OWNED BY {t}.id")
            cur.execute(
                f"ALTER TABLE {t} ALTER COLUMN id SET DEFAULT nextval('{seq}')")
            cur.execute(
                f"SELECT setval('{seq}', COALESCE((SELECT MAX(id) FROM {t}), 1), true)")
            nuevo = cur.fetchone()[0]
            print(f"  {t:32s} -> secuencia CREADA = {nuevo}")
            creadas += 1
            continue

        # Poner la secuencia existente en MAX(id) (o 1 si la tabla está vacía).
        cur.execute(
            f"SELECT setval('{seq}', COALESCE((SELECT MAX(id) FROM {t}), 1), true)")
        nuevo = cur.fetchone()[0]
        print(f"  {t:32s} -> secuencia = {nuevo}")
        arregladas += 1

    conn.commit()
    conn.close()
    print(f"\nListo. Secuencias resincronizadas: {arregladas}. Creadas: {creadas}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
