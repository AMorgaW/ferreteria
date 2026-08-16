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
  - lastrowid -> via RETURNING id solo si la PK declarada es `id`
"""
import re
import sqlite3
import psycopg2
import psycopg2.extras
import psycopg2.extensions
import psycopg2.pool
import threading

# ── Compatibilidad de tipos SQLite ↔ PostgreSQL ──────────────────────────
# SQLite devuelve las fechas como TEXTO; Postgres las parsea a datetime. Gran
# parte de la UI/servicios asume texto (p. ej. fecha[:10], fromisoformat(fecha)).
# Registramos un typecaster para que date/time/timestamp/timestamptz vuelvan
# como el STRING crudo de Postgres, igual que SQLite → cero cambios en el resto.
_TS_OIDS = (1082, 1083, 1114, 1184)  # date, time, timestamp, timestamptz
_TS_AS_TEXT = psycopg2.extensions.new_type(_TS_OIDS, "TS_AS_TEXT", lambda v, c: v)
psycopg2.extensions.register_type(_TS_AS_TEXT)

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
DB_MODE = _os.environ.get("DB_MODE", "local").strip().lower()
LOCAL_DB_PATH = _os.environ.get(
    "LOCAL_DB_PATH",
    _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "ferreteria.db"),
)
POOL_MINCONN = int(_os.environ.get("DB_POOL_MINCONN", "1"))
POOL_MAXCONN = int(_os.environ.get("DB_POOL_MAXCONN", "16"))
CONNECT_TIMEOUT = int(_os.environ.get("DB_CONNECT_TIMEOUT", "8"))
STATEMENT_TIMEOUT_MS = int(_os.environ.get("DB_STATEMENT_TIMEOUT_MS", "20000"))

_POOL = None
_POOL_LOCK = threading.Lock()
# ─────────────────────────────────────────────────────────────


_STRFTIME_TOKENS = [
    ("%Y", "YYYY"), ("%m", "MM"), ("%d", "DD"),
    ("%H", "HH24"), ("%M", "MI"), ("%S", "SS"),
]


def _strftime_to_char(match) -> str:
    """strftime('%Y-%m', expr) -> to_char(expr, 'YYYY-MM')."""
    fmt, expr = match.group(1), match.group(2)
    for sqlite_tok, pg_tok in _STRFTIME_TOKENS:
        fmt = fmt.replace(sqlite_tok, pg_tok)
    # 'now' como literal es de tipo desconocido para to_char (ambiguo) ->
    # usar el timestamp actual.
    if expr.strip().lower() == "'now'":
        expr = "CURRENT_TIMESTAMP"
    return f"to_char({expr}, '{fmt}')"


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

    # DATE('now', 'localtime' | 'utc' | ...) -> CURRENT_DATE
    # (SQLite acepta modificadores; Postgres no tiene date(text, text)).
    q = re.sub(r"DATE\s*\(\s*'now'\s*,\s*'[^']*'\s*\)", "CURRENT_DATE",
               q, flags=re.IGNORECASE)

    # DATE('now') -> CURRENT_DATE
    q = re.sub(r"DATE\s*\(\s*'now'\s*\)", "CURRENT_DATE", q, flags=re.IGNORECASE)

    # datetime('now'[, 'localtime']) -> CURRENT_TIMESTAMP (antes que la regla
    # genérica de datetime, que asume el 1er argumento es una columna).
    q = re.sub(r"datetime\s*\(\s*'now'\s*(,\s*'[^']*'\s*)*\)", "CURRENT_TIMESTAMP",
               q, flags=re.IGNORECASE)

    # datetime(x, 'localtime') -> x AT TIME ZONE 'America/Bogota'
    q = re.sub(
        r"datetime\(([^,)]+),\s*'localtime'\)",
        r"\1 AT TIME ZONE 'America/Bogota'",
        q,
        flags=re.IGNORECASE,
    )

    # TIME(expr) -> CAST(expr AS TIME)  (SQLite: función; Postgres: cast).
    # Solo cuando el contenido no tiene paréntesis anidados.
    q = re.sub(r"\bTIME\s*\(([^()]+)\)", r"CAST(\1 AS TIME)",
               q, flags=re.IGNORECASE)

    # strftime('<fmt>', expr[, 'modificador']) -> to_char(expr, '<fmt_pg>')
    # El valor de tiempo no lleva comas (los datetime(x,'localtime') ya se
    # tradujeron antes); los modificadores tipo 'localtime' se descartan.
    q = re.sub(
        r"strftime\s*\(\s*'([^']*)'\s*,\s*([^,()]+?)\s*(?:,\s*'[^']*'\s*)*\)",
        _strftime_to_char, q, flags=re.IGNORECASE,
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


_INSERT_TABLE_RE = re.compile(
    r"^\s*INSERT\s+(?:OR\s+[A-Za-z]+\s+)?INTO\s+"
    r"(?:(?P<schema>\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)\.)?"
    r"(?P<table>\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE | re.DOTALL,
)


class PgCompatError(Exception):
    """No se puede adaptar el INSERT remoto sin inventar una PK."""


def _unquote_ident(name: str) -> str:
    if len(name) >= 2 and name[0] == '"' and name[-1] == '"':
        return name[1:-1]
    return name.lower()


def insert_table_name(query: str):
    """Nombre de tabla de un INSERT, o None si no se puede parsear."""
    match = _INSERT_TABLE_RE.match(query or "")
    if not match:
        return None
    return _unquote_ident(match.group("table"))


def plain_insert_returning_clause(query: str) -> str:
    """Sufijo RETURNING para INSERT plano según PK declarada. No inventa PK.

    - Tabla con PK declarada ``id`` (sync o no-sync de DDL): `` RETURNING id``.
    - Tabla con PK no-id (configuracion, consecutivos, login_intentos, …):
      ``""``; lastrowid=None.
    - Tabla sin metadata de PK: ``PgCompatError`` (no se asume ``id``).
    - Nombre de tabla irresoluble: ``PgCompatError`` visible.
    """
    if not _is_plain_insert(query):
        return ""
    table = insert_table_name(query)
    if not table:
        raise PgCompatError(
            "INSERT remoto: no se pudo resolver el nombre de tabla; "
            "no se inventa RETURNING id"
        )
    from sync_registry import declared_insert_pk

    pk = declared_insert_pk(table)
    if pk is None:
        raise PgCompatError(
            f"INSERT remoto INTO {table}: falta PK declarada; "
            "no se inventa RETURNING id"
        )
    if pk != "id":
        return ""
    return " RETURNING id"


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

    @property
    def connection(self):
        # Compat sqlite3: algunos módulos acceden a cursor.connection.
        return self._c.connection

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

        # INSERT plano: RETURNING solo si la PK declarada es id.
        if _is_plain_insert(query):
            clause = plain_insert_returning_clause(query)
            if clause:
                q = q.rstrip().rstrip(";") + clause
            if params:
                self._c.execute(q, params)
            else:
                self._c.execute(q)
            if clause:
                row = self._c.fetchone()
                self.lastrowid = row[0] if row else None
            else:
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


def _connection_options():
    options = [f"-c statement_timeout={STATEMENT_TIMEOUT_MS}"]
    return " ".join(options)


def _get_pool():
    global _POOL

    if not DATABASE_URL:
        raise RuntimeError("SUPABASE_URI no esta configurado en .env")

    if _POOL is None:
        with _POOL_LOCK:
            if _POOL is None:
                _POOL = psycopg2.pool.ThreadedConnectionPool(
                    POOL_MINCONN,
                    POOL_MAXCONN,
                    DATABASE_URL,
                    connect_timeout=CONNECT_TIMEOUT,
                    keepalives=1,
                    keepalives_idle=30,
                    keepalives_interval=10,
                    keepalives_count=5,
                    application_name="ferreteria_desktop",
                    options=_connection_options(),
                )
    return _POOL


class PgConnection:
    """Connection wrapper compatible con la API de sqlite3."""

    def __init__(self, real_conn, pool=None):
        self._conn = real_conn
        self._pool = pool
        self._closed = False
        # row_factory: ignorado; DictCursor ya devuelve dicts
        self.row_factory = None

    def cursor(self):
        if self._closed:
            raise RuntimeError("La conexion ya fue cerrada")
        return PgCursor(
            self._conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        )

    def commit(self):
        if self._closed:
            return
        self._conn.commit()

    def rollback(self):
        if self._closed:
            return
        self._conn.rollback()

    def close(self):
        if self._closed:
            return

        discard = False
        try:
            if self._conn.closed:
                discard = True
            else:
                self._conn.rollback()
        except Exception:
            discard = True

        if self._pool is not None:
            self._pool.putconn(self._conn, close=discard)
        else:
            self._conn.close()

        self._closed = True

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
    """Obtiene una conexion PostgreSQL reutilizable desde el pool."""
    if DB_MODE in ("local", "sqlite", "server"):
        # Las conexiones se crean por operación/repositorio. Dejar activo el
        # guard nativo evita compartir accidentalmente conexión/cursor entre hilos.
        conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30, check_same_thread=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    pool = _get_pool()
    raw = pool.getconn()

    if raw.closed:
        pool.putconn(raw, close=True)
        raw = pool.getconn()

    # Limpiar cualquier transacción abortada/pendiente que un uso previo haya
    # dejado en esta conexión del pool. Sin esto, si un statement falló antes
    # (p. ej. DDL SQLite contra Postgres), el siguiente que la reciba hereda el
    # estado "InFailedSqlTransaction: current transaction is aborted".
    try:
        raw.rollback()
    except Exception:
        pool.putconn(raw, close=True)
        raw = pool.getconn()

    raw.autocommit = False
    return PgConnection(raw, pool)
