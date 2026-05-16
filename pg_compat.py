# -*- coding: utf-8 -*-
"""
pg_compat.py - Capa de compatibilidad SQLite -> PostgreSQL

Permite que el codigo que usa sqlite3 funcione con PostgreSQL (Supabase)
sin necesidad de cambiar todos los placeholders ? ni las funciones SQLite.

Conversiones automaticas:
  - ? -> %s
  - datetime(x, 'localtime') -> x AT TIME ZONE 'America/Bogota'
  - julianday('now') - julianday(x) -> (CURRENT_DATE - DATE(x))
  - DATE('now') -> CURRENT_DATE
  - INSERT OR IGNORE INTO -> INSERT INTO ... ON CONFLICT DO NOTHING
  - lastrowid -> via RETURNING id
"""
import re
import psycopg2
import psycopg2.extras

# ─────────────────────────────────────────────────────────────
#  URI de Supabase leída desde .env
# ─────────────────────────────────────────────────────────────
import os as _os

def _load_env():
    env_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), ".env")
    if _os.path.exists(env_path):
        with open(env_path) as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    _os.environ.setdefault(_k.strip(), _v.strip())

_load_env()
DATABASE_URL = _os.environ.get("SUPABASE_URI", "")
# ─────────────────────────────────────────────────────────────


def _fix_query(query: str) -> str:
    """Convierte SQL estilo SQLite a PostgreSQL."""
    q = query

    # DATE('now', '-' || ? || ' days') -> (CURRENT_DATE - ?)
    # Debe hacerse ANTES de ? -> %s
    q = re.sub(
        r"DATE\s*\(\s*'now'\s*,\s*'-'\s*\|\|\s*\?\s*\|\|\s*'\s*days\s*'\s*\)",
        r"(CURRENT_DATE - ?)",
        q, flags=re.IGNORECASE,
    )

    # ? -> %s  (solo fuera de strings literales — aproximacion simple)
    q = q.replace("?", "%s")

    # DATE('now') -> CURRENT_DATE
    q = re.sub(r"DATE\s*\(\s*'now'\s*\)", "CURRENT_DATE", q, flags=re.IGNORECASE)

    # datetime(x, 'localtime') -> x AT TIME ZONE 'America/Bogota'
    q = re.sub(
        r"datetime\(([^,)]+),\s*'localtime'\)",
        r"\1 AT TIME ZONE 'America/Bogota'",
        q,
        flags=re.IGNORECASE,
    )

    # julianday('now') - julianday(x) -> (CURRENT_DATE - DATE(x))
    q = re.sub(
        r"julianday\s*\(\s*'now'\s*\)\s*-\s*julianday\s*\(([^)]+)\)",
        r"(CURRENT_DATE - DATE(\1))",
        q,
        flags=re.IGNORECASE,
    )

    return q


def _is_insert_or_ignore(query: str) -> bool:
    return bool(re.search(r"INSERT\s+OR\s+IGNORE\s+INTO", query, re.IGNORECASE))


def _is_plain_insert(query: str) -> bool:
    stripped = query.strip().upper()
    return (
        stripped.startswith("INSERT")
        and "RETURNING" not in stripped
        and not _is_insert_or_ignore(query)
    )


class PgCursor:
    """Cursor wrapper: convierte queries SQLite y expone lastrowid."""

    def __init__(self, real_cursor):
        self._c = real_cursor
        self.lastrowid = None

    @property
    def description(self):
        return self._c.description

    @property
    def rowcount(self):
        return self._c.rowcount

    def execute(self, query: str, params=None):
        q = _fix_query(query)

        # INSERT OR IGNORE -> INSERT ... ON CONFLICT DO NOTHING
        if _is_insert_or_ignore(query):
            q = re.sub(
                r"INSERT\s+OR\s+IGNORE\s+INTO",
                "INSERT INTO",
                q,
                flags=re.IGNORECASE,
            )
            q = q.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
            self.lastrowid = None
            if params:
                self._c.execute(q, params)
            else:
                self._c.execute(q)
            return

        # INSERT normal -> agregar RETURNING id para soportar lastrowid
        if _is_plain_insert(query):
            q = q.rstrip().rstrip(";") + " RETURNING id"
            if params:
                self._c.execute(q, params)
            else:
                self._c.execute(q)
            try:
                row = self._c.fetchone()
                self.lastrowid = row[0] if row else None
            except Exception:
                self.lastrowid = None
            return

        # Cualquier otro statement
        if params:
            self._c.execute(q, params)
        else:
            self._c.execute(q)

    def executemany(self, query: str, seq_of_params):
        q = _fix_query(query)
        self._c.executemany(q, seq_of_params)

    def executescript(self, script: str):
        """Ejecuta multiples statements separados por ';'."""
        for stmt in script.split(";"):
            stmt = stmt.strip()
            if stmt:
                try:
                    self._c.execute(stmt)
                except Exception:
                    pass  # Ignorar errores (e.g. sintaxis SQLite en CREATE TABLE)

    def fetchone(self):
        return self._c.fetchone()

    def fetchall(self):
        return self._c.fetchall()

    def fetchmany(self, size=None):
        if size is not None:
            return self._c.fetchmany(size)
        return self._c.fetchmany()

    def __iter__(self):
        return iter(self._c)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class PgConnection:
    """Connection wrapper compatible con la API de sqlite3."""

    def __init__(self, real_conn):
        self._conn = real_conn
        # row_factory: ignorado; DictCursor ya devuelve dicts
        self.row_factory = None

    def cursor(self):
        return PgCursor(
            self._conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        )

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    # Contexto
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()


# ─────────────────────────────────────────────────────────────
#  API publica
# ─────────────────────────────────────────────────────────────

class IntegrityError(Exception):
    """Equivalente a sqlite3.IntegrityError para codigo de compatibilidad."""
    pass


def connect() -> PgConnection:
    """Abre una conexion a PostgreSQL. Retorna PgConnection."""
    raw = psycopg2.connect(DATABASE_URL, connect_timeout=15)
    raw.autocommit = False
    return PgConnection(raw)
