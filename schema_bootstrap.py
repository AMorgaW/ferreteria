# -*- coding: utf-8 -*-
"""Bootstrap canónico de esquema FERREPRO.

Fuentes de verdad (no mezclar):

* SQLite nuevo
  ``DatabaseManager.crear_estructura_completa()`` emite DDL con
  ``INTEGER PRIMARY KEY`` (alias de ROWID). Una instalación limpia materializa
  todas las tablas/columnas/índices que el código actual ya espera.

* Migraciones SQLite
  Este módulo: helpers idempotentes (existencia de tabla/columna/índice) y
  ``apply_required_columns`` / ``ensure_sqlite_integer_pks``. Nunca usa
  ``ADD COLUMN IF NOT EXISTS`` (sintaxis PostgreSQL) ni traga el error.

* PostgreSQL remoto
  El mismo ``crear_estructura_completa()`` emite ``SERIAL PRIMARY KEY``.
  La identidad local-first remota vive en ``supabase_local_first_migration.sql``
  y **solo** se ejecuta contra Postgres en
  ``SupabaseSyncService._ensure_remote_schema``. No es un script SQLite.

Por qué ``INTEGER PRIMARY KEY`` y no ``AUTOINCREMENT`` en tablas de negocio:
SQLite trata ``INTEGER PRIMARY KEY`` (el tipo debe ser exactamente INTEGER)
como alias de ROWID: asigna id, ``lastrowid`` coincide y el valor no queda
NULL. ``AUTOINCREMENT`` solo evita reutilizar el máximo id borrado, con coste
de ``sqlite_sequence``. Las tablas de negocio se identifican en sync por
``local_id`` UUID; no hace falta bloquear reuso de ROWID. Las tablas de cola
(local-first) ya usan AUTOINCREMENT y se dejan así.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Iterable, Optional, Sequence, Tuple


class SchemaBootstrapError(Exception):
    """Fallo crítico de esquema. No se debe declarar la BD sana."""


_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NONCONST_DEFAULT_RE = re.compile(
    r"\s+DEFAULT\s+CURRENT_(?:TIMESTAMP|TIME|DATE)\b",
    re.IGNORECASE,
)

# Tablas de negocio cuyo `id` debe ser ROWID alias en SQLite.
INTEGER_PK_TABLES = (
    "usuarios",
    "proveedores",
    "productos",
    "clientes",
    "ventas",
    "detalle_ventas",
    "movimientos",
    "movimientos_inventario",
    "compras",
    "detalle_compras",
    "cierres_caja",
    "cuentas_por_cobrar",
    "pagos_cuentas",
    "alertas",
    "abonos_compras",
    "resumen_deudas",
    "abonos_ventas",
    "egresos_caja",
    "formulas_mezcla",
    "formula_detalle",
    "auditoria",
    "categorias_config",
)

# Columnas que el código productivo ya lee/escribe y que bases viejas pueden
# no tener. Idempotente: ADD solo si falta.
REQUIRED_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    ("compras", "estado_pago", "TEXT DEFAULT 'PENDIENTE'"),
    ("compras", "monto_pagado", "REAL DEFAULT 0"),
    ("compras", "saldo_pendiente", "REAL DEFAULT 0"),
    ("compras", "fecha_vencimiento", "DATE"),
    ("detalle_ventas", "tipo_unidad", "TEXT DEFAULT 'Unidad'"),
    ("productos", "proveedor_id", "INTEGER"),
    ("productos", "fecha_actualizacion", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
    ("productos", "presentacion", "TEXT"),
    ("productos", "usar_unidades_categoria", "INTEGER DEFAULT 1"),
    ("productos", "unidades_venta_custom", "TEXT"),
    ("productos", "unidad_base_producto", "TEXT"),
    ("productos", "unidades_por_media_caja", "INTEGER DEFAULT 1"),
    ("productos", "vende_por_empaque", "INTEGER DEFAULT 0"),
    ("movimientos_inventario", "numero_factura", "TEXT"),
)

# Índices btree válidos en SQLite y PostgreSQL.
SHARED_INDEXES: Tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_productos_codigo ON productos(codigo_barras)",
    "CREATE INDEX IF NOT EXISTS idx_productos_nombre ON productos(nombre)",
    "CREATE INDEX IF NOT EXISTS idx_productos_activo_nombre ON productos(activo, nombre)",
    "CREATE INDEX IF NOT EXISTS idx_productos_categoria ON productos(categoria)",
    "CREATE INDEX IF NOT EXISTS idx_productos_marca ON productos(marca)",
    "CREATE INDEX IF NOT EXISTS idx_productos_proveedor ON productos(proveedor_id)",
    "CREATE INDEX IF NOT EXISTS idx_ventas_fecha ON ventas(fecha)",
    "CREATE INDEX IF NOT EXISTS idx_ventas_cliente ON ventas(cliente_id)",
    "CREATE INDEX IF NOT EXISTS idx_ventas_estado_fecha ON ventas(estado, fecha)",
    "CREATE INDEX IF NOT EXISTS idx_detalle_ventas_venta ON detalle_ventas(venta_id)",
    "CREATE INDEX IF NOT EXISTS idx_detalle_ventas_producto ON detalle_ventas(producto_id)",
    "CREATE INDEX IF NOT EXISTS idx_movimientos_fecha ON movimientos(fecha)",
    "CREATE INDEX IF NOT EXISTS idx_movimientos_proveedor ON movimientos(proveedor_id)",
    "CREATE INDEX IF NOT EXISTS idx_clientes_documento ON clientes(numero_documento)",
    "CREATE INDEX IF NOT EXISTS idx_clientes_nombre ON clientes(nombre)",
    "CREATE INDEX IF NOT EXISTS idx_clientes_activo_nombre ON clientes(activo, nombre)",
    "CREATE INDEX IF NOT EXISTS idx_proveedores_nombre ON proveedores(nombre)",
    "CREATE INDEX IF NOT EXISTS idx_proveedores_nit ON proveedores(nit)",
    "CREATE INDEX IF NOT EXISTS idx_proveedores_activo_nombre ON proveedores(activo, nombre)",
    "CREATE INDEX IF NOT EXISTS idx_compras_fecha ON compras(fecha)",
    "CREATE INDEX IF NOT EXISTS idx_compras_proveedor ON compras(proveedor_id)",
    "CREATE INDEX IF NOT EXISTS idx_detalle_compras_compra ON detalle_compras(compra_id)",
    "CREATE INDEX IF NOT EXISTS idx_detalle_compras_producto ON detalle_compras(producto_id)",
    "CREATE INDEX IF NOT EXISTS idx_abonos_compra ON abonos_compras(id_compra)",
    "CREATE INDEX IF NOT EXISTS idx_abonos_fecha ON abonos_compras(fecha_abono)",
    "CREATE INDEX IF NOT EXISTS idx_cuentas_cobrar_cliente_estado ON cuentas_por_cobrar(cliente_id, estado)",
    "CREATE INDEX IF NOT EXISTS idx_cuentas_cobrar_vencimiento ON cuentas_por_cobrar(fecha_vencimiento)",
    "CREATE INDEX IF NOT EXISTS idx_alertas_leida_fecha ON alertas(leida, fecha_creacion)",
    "CREATE INDEX IF NOT EXISTS idx_egresos_fecha ON egresos_caja(fecha_egreso)",
    "CREATE INDEX IF NOT EXISTS idx_formula_detalle_formula ON formula_detalle(formula_id)",
    "CREATE INDEX IF NOT EXISTS idx_formulas_mezcla_nombre ON formulas_mezcla(nombre)",
)

# Solo PostgreSQL. Nunca ejecutar contra SQLite.
POSTGRES_ONLY_STATEMENTS: Tuple[str, ...] = (
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    "CREATE INDEX IF NOT EXISTS idx_productos_nombre_trgm ON productos USING gin (LOWER(nombre) gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS idx_productos_codigo_trgm ON productos USING gin (LOWER(codigo_barras) gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS idx_productos_marca_trgm ON productos USING gin (LOWER(marca) gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS idx_clientes_nombre_trgm ON clientes USING gin (LOWER(nombre) gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS idx_clientes_documento_trgm ON clientes USING gin (LOWER(numero_documento) gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS idx_proveedores_nombre_trgm ON proveedores USING gin (LOWER(nombre) gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS idx_proveedores_nit_trgm ON proveedores USING gin (LOWER(nit) gin_trgm_ops)",
)

REMOTE_MIGRATION_FILENAME = "supabase_local_first_migration.sql"


def _quote_ident(name: str) -> str:
    if not _IDENT_RE.match(name):
        raise SchemaBootstrapError(f"Identificador SQL inválido: {name!r}")
    return name


def is_sqlite_connection(conn) -> bool:
    return isinstance(conn, sqlite3.Connection)


def pk_sql(conn) -> str:
    """DDL de PK autogenerada según el motor de *esta* conexión."""
    if is_sqlite_connection(conn):
        return "INTEGER PRIMARY KEY"
    return "SERIAL PRIMARY KEY"


def _cursor(conn):
    return conn.cursor()


def _execute(conn, sql: str, params: Optional[Sequence] = None):
    cur = _cursor(conn)
    try:
        if params is None:
            cur.execute(sql)
        else:
            cur.execute(sql, params)
        return cur
    except SchemaBootstrapError:
        raise
    except Exception as exc:
        raise SchemaBootstrapError(f"SQL falló: {sql[:180]} — {exc}") from exc


def table_exists(conn, table: str) -> bool:
    table = _quote_ident(table)
    if is_sqlite_connection(conn):
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None
    cur = _cursor(conn)
    cur.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name=?",
        (table,),
    )
    return cur.fetchone() is not None


def column_names(conn, table: str) -> set:
    table = _quote_ident(table)
    if is_sqlite_connection(conn):
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    cur = _cursor(conn)
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=?",
        (table,),
    )
    return {row[0] for row in cur.fetchall()}


def column_exists(conn, table: str, column: str) -> bool:
    return column in column_names(conn, table)


def index_exists(conn, name: str) -> bool:
    name = _quote_ident(name)
    if is_sqlite_connection(conn):
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
            (name,),
        ).fetchone()
        return row is not None
    cur = _cursor(conn)
    cur.execute(
        "SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname=?",
        (name,),
    )
    return cur.fetchone() is not None


def add_column_if_missing(conn, table: str, column: str, definition: str) -> bool:
    """Añade la columna si falta. Idempotente. No usa IF NOT EXISTS de Postgres.

    Returns True si la añadió, False si ya existía.
    """
    table = _quote_ident(table)
    column = _quote_ident(column)
    if not table_exists(conn, table):
        raise SchemaBootstrapError(
            f"No se puede añadir {table}.{column}: la tabla no existe"
        )
    if column_exists(conn, table, column):
        return False
    ddl_def = definition
    if is_sqlite_connection(conn):
        # SQLite rechaza CURRENT_TIMESTAMP como default de ADD COLUMN
        # (no es constante). CREATE TABLE sí lo admite; aquí se omite.
        ddl_def = _NONCONST_DEFAULT_RE.sub("", ddl_def)
    try:
        _cursor(conn).execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {ddl_def}"
        )
    except SchemaBootstrapError:
        raise
    except Exception as exc:
        raise SchemaBootstrapError(
            f"No se pudo añadir {table}.{column}: {exc}"
        ) from exc
    return True


def create_index_if_missing(conn, statement: str) -> None:
    """Crea un índice. ``CREATE INDEX IF NOT EXISTS`` es válido en ambos motores.

    Si la tabla o alguna columna indexada aún no existe, no-op. Cualquier
    otro error es crítico.
    """
    table = _index_table_name(statement)
    if table and not table_exists(conn, table):
        return
    cols = _index_column_names(statement)
    if table and cols:
        existing = column_names(conn, table)
        if any(c not in existing for c in cols):
            return
    try:
        _cursor(conn).execute(statement)
    except SchemaBootstrapError:
        raise
    except Exception as exc:
        raise SchemaBootstrapError(
            f"No se pudo crear índice ({statement[:120]}): {exc}"
        ) from exc


def _index_column_names(statement: str) -> Tuple[str, ...]:
    match = re.search(r"ON\s+[A-Za-z_][A-Za-z0-9_]*\s*\((.*)\)", statement, re.I)
    if not match:
        return ()
    return tuple(
        part.strip().split()[0]
        for part in match.group(1).split(",")
        if part.strip() and _IDENT_RE.match(part.strip().split()[0])
    )


def _index_table_name(statement: str) -> Optional[str]:
    match = re.search(
        r"ON\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        statement,
        flags=re.IGNORECASE,
    )
    return match.group(1) if match else None


def apply_required_columns(conn) -> None:
    """Añade columnas que el código actual espera. Falla ruidoso si no puede."""
    for table, column, definition in REQUIRED_COLUMNS:
        if not table_exists(conn, table):
            continue
        add_column_if_missing(conn, table, column, definition)


def apply_shared_indexes(conn) -> None:
    for statement in SHARED_INDEXES:
        create_index_if_missing(conn, statement)


def apply_postgres_only_statements(conn) -> None:
    """Índices/extensiones PostgreSQL. Nunca llamar con una conexión SQLite."""
    if is_sqlite_connection(conn):
        raise SchemaBootstrapError(
            "POSTGRES_ONLY_STATEMENTS no debe ejecutarse contra SQLite"
        )
    for statement in POSTGRES_ONLY_STATEMENTS:
        try:
            _cursor(conn).execute(statement)
        except Exception as exc:
            # Extensión/GIN son rendimiento, no columnas de negocio. Se registra
            # el fallo; no se finge éxito silencioso ni se aborta el bootstrap
            # si el rol de Supabase no puede CREATE EXTENSION.
            print(f"[SCHEMA][PG] Aviso (no crítico): {statement[:80]} — {exc}")


def sqlite_id_is_rowid_alias(conn, table: str) -> bool:
    """True si `id` es INTEGER PRIMARY KEY (alias de ROWID)."""
    if not is_sqlite_connection(conn) or not table_exists(conn, table):
        return True
    table = _quote_ident(table)
    info = list(conn.execute(f"PRAGMA table_info({table})"))
    id_col = next((row for row in info if row["name"] == "id"), None)
    if id_col is None:
        return True
    return str(id_col["type"]).upper() == "INTEGER" and int(id_col["pk"]) == 1


def ensure_sqlite_integer_pks(conn, tables: Iterable[str] = INTEGER_PK_TABLES) -> None:
    """Reconstruye tablas SQLite cuyo `id` no es alias de ROWID (p.ej. SERIAL)."""
    if not is_sqlite_connection(conn):
        return
    for table in tables:
        if not table_exists(conn, table):
            continue
        if sqlite_id_is_rowid_alias(conn, table):
            continue
        _rebuild_sqlite_integer_pk(conn, table)


def _rebuild_sqlite_integer_pk(conn, table: str) -> None:
    table = _quote_ident(table)
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    old_sql = row[0] if row else None
    if not old_sql:
        raise SchemaBootstrapError(f"No hay DDL para reconstruir {table}")

    tmp = f"{table}__pkfix"
    new_sql = re.sub(
        rf"CREATE\s+TABLE\s+(IF\s+NOT\s+EXISTS\s+)?([\"']?{table}[\"']?)",
        f"CREATE TABLE {tmp}",
        old_sql,
        count=1,
        flags=re.IGNORECASE,
    )
    new_sql = re.sub(
        r"\bid\s+SERIAL\s+PRIMARY\s+KEY\b",
        "id INTEGER PRIMARY KEY",
        new_sql,
        count=1,
        flags=re.IGNORECASE,
    )
    if new_sql == old_sql or f"CREATE TABLE {tmp}" not in new_sql:
        # DDL sin SERIAL literal: reconstruir a partir de PRAGMA.
        new_sql = _create_sql_from_pragma(conn, table, tmp)

    indexes = [
        r[0]
        for r in conn.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
            (table,),
        ).fetchall()
    ]
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    if not cols:
        raise SchemaBootstrapError(f"{table} no tiene columnas para copiar")
    col_list = ", ".join(_quote_ident(c) for c in cols)
    count_before = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute(f"DROP TABLE IF EXISTS {tmp}")
        conn.execute(new_sql)
        conn.execute(
            f"INSERT INTO {tmp} ({col_list}) SELECT {col_list} FROM {table}"
        )
        count_after = conn.execute(f"SELECT COUNT(*) FROM {tmp}").fetchone()[0]
        if count_after != count_before:
            conn.execute(f"DROP TABLE IF EXISTS {tmp}")
            raise SchemaBootstrapError(
                f"Reconstrucción PK de {table}: {count_before} filas origen, "
                f"{count_after} copiadas"
            )
        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"ALTER TABLE {tmp} RENAME TO {table}")
        for idx_sql in indexes:
            conn.execute(idx_sql)
        if not sqlite_id_is_rowid_alias(conn, table):
            raise SchemaBootstrapError(
                f"Tras reconstruir {table}, id sigue sin ser INTEGER PRIMARY KEY"
            )
    except SchemaBootstrapError:
        try:
            conn.execute(f"DROP TABLE IF EXISTS {tmp}")
        except sqlite3.Error:
            pass
        raise
    except Exception as exc:
        try:
            conn.execute(f"DROP TABLE IF EXISTS {tmp}")
        except sqlite3.Error:
            pass
        raise SchemaBootstrapError(
            f"Fallo reconstruyendo PK de {table}: {exc}"
        ) from exc
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


def _create_sql_from_pragma(conn, table: str, tmp: str) -> str:
    info = list(conn.execute(f"PRAGMA table_info({table})"))
    pieces = []
    pk_cols = []
    for col in info:
        name = _quote_ident(col["name"])
        col_type = col["type"] or "TEXT"
        if name == "id":
            pieces.append("id INTEGER PRIMARY KEY")
            continue
        notnull = " NOT NULL" if col["notnull"] else ""
        default = ""
        if col["dflt_value"] is not None:
            default = f" DEFAULT {col['dflt_value']}"
        pieces.append(f"{name} {col_type}{notnull}{default}")
        if col["pk"]:
            pk_cols.append(name)
    fk_rows = list(conn.execute(f"PRAGMA foreign_key_list({table})"))
    fks = []
    grouped = {}
    for fk in fk_rows:
        grouped.setdefault(fk["id"], []).append(fk)
    for _fid, rows in grouped.items():
        cols = ", ".join(_quote_ident(r["from"]) for r in rows)
        ref_table = _quote_ident(rows[0]["table"])
        ref_cols = ", ".join(_quote_ident(r["to"]) for r in rows)
        fks.append(f"FOREIGN KEY ({cols}) REFERENCES {ref_table}({ref_cols})")
    body = ", ".join(pieces + fks)
    return f"CREATE TABLE {tmp} ({body})"


def apply_engine_schema_fixes(conn) -> None:
    """Migraciones idempotentes posteriores al CREATE TABLE IF NOT EXISTS.

    En SQLite se ejecutan bajo SAVEPOINT para que un fallo crítico no deje
    columnas a medias ni marque la BD como sana.
    """
    sqlite = is_sqlite_connection(conn)
    if sqlite:
        conn.execute("SAVEPOINT ferrepro_schema_fixes")
    try:
        apply_required_columns(conn)
        if sqlite:
            ensure_sqlite_integer_pks(conn)
        apply_shared_indexes(conn)
        if not sqlite:
            apply_postgres_only_statements(conn)
        if sqlite:
            conn.execute("RELEASE SAVEPOINT ferrepro_schema_fixes")
    except Exception:
        if sqlite:
            try:
                conn.execute("ROLLBACK TO SAVEPOINT ferrepro_schema_fixes")
                conn.execute("RELEASE SAVEPOINT ferrepro_schema_fixes")
            except sqlite3.Error:
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
        raise
