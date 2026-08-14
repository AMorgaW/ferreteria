# -*- coding: utf-8 -*-
import json
import os
import sqlite3
import uuid
from datetime import datetime
import schema_bootstrap
from sync_registry import pk_column, sync_tables, table_for_entity


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.environ.get("LOCAL_DB_PATH", os.path.join(BASE_DIR, "ferreteria.db"))

# Derivado del registry canónico. No editar esta lista a mano.
SYNC_TABLES = sync_tables()


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect(db_path=DEFAULT_DB_PATH):
    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def table_columns(conn, table):
    return schema_bootstrap.column_names(conn, table)


def add_column_if_missing(conn, table, column, definition):
    return schema_bootstrap.add_column_if_missing(conn, table, column, definition)


def row_to_dict(row):
    return dict(row) if row is not None else None


def ensure_local_first_schema(db_path=DEFAULT_DB_PATH):
    conn = connect(db_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                table_name TEXT NOT NULL,
                operation TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                synced_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_conflicts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                local_payload TEXT,
                remote_payload TEXT,
                conflict_reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                resolved_at TEXT,
                resolved_by INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_state (
                clave TEXT PRIMARY KEY,
                valor TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS local_sessions (
                token TEXT PRIMARY KEY,
                usuario_id INTEGER NOT NULL,
                rol TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                expires_at TEXT,
                last_activity_at TEXT
            )
        """)
        add_column_if_missing(conn, "local_sessions", "last_activity_at", "TEXT")

        # Historial de precios debe existir ANTES de añadir columnas sync:
        # está en SYNC_REGISTRY y en un SQLite fresco no lo crea database.py.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS historial_precios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                producto_id INTEGER NOT NULL,
                tipo TEXT NOT NULL,
                precio_anterior REAL,
                precio_nuevo REAL,
                usuario_id INTEGER,
                fecha TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        for table in SYNC_TABLES:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if not exists:
                continue
            add_column_if_missing(conn, table, "local_id", "TEXT")
            add_column_if_missing(conn, table, "remote_id", "TEXT")
            add_column_if_missing(conn, table, "updated_at", "TEXT")
            add_column_if_missing(conn, table, "deleted_at", "TEXT")
            add_column_if_missing(conn, table, "is_deleted", "INTEGER NOT NULL DEFAULT 0")
            add_column_if_missing(conn, table, "sync_status", "TEXT NOT NULL DEFAULT 'pending'")
            add_column_if_missing(conn, table, "last_synced_at", "TEXT")
            add_column_if_missing(conn, table, "version", "INTEGER NOT NULL DEFAULT 1")
            add_column_if_missing(conn, table, "device_id", "TEXT")
            add_column_if_missing(conn, table, "created_by", "INTEGER")
            add_column_if_missing(conn, table, "updated_by", "INTEGER")

        # Columna de presentación (tamaño/medida) para diferenciar variantes.
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='productos'"
        ).fetchone():
            add_column_if_missing(conn, "productos", "presentacion", "TEXT")

        # Contadores atómicos (p. ej. consecutivo de factura por día) para evitar
        # colisiones de numero_factura en ventas simultáneas.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS consecutivos (
                clave TEXT PRIMARY KEY,
                valor INTEGER NOT NULL DEFAULT 0
            )
        """)

        # Control de intentos de login (rate-limiting / bloqueo por fuerza bruta).
        conn.execute("""
            CREATE TABLE IF NOT EXISTS login_intentos (
                username TEXT PRIMARY KEY,
                intentos INTEGER NOT NULL DEFAULT 0,
                ultimo_intento TEXT,
                bloqueado_hasta TEXT
            )
        """)

        # Devoluciones (total / parcial).
        conn.execute("""
            CREATE TABLE IF NOT EXISTS devoluciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                venta_id INTEGER NOT NULL,
                fecha TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                usuario_id INTEGER,
                motivo TEXT,
                tipo TEXT,
                total_devuelto REAL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS devolucion_detalle (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                devolucion_id INTEGER NOT NULL,
                venta_id INTEGER NOT NULL,
                producto_id INTEGER NOT NULL,
                cantidad REAL NOT NULL,
                precio_unitario REAL,
                subtotal REAL
            )
        """)

        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_historial_precios_producto ON historial_precios(producto_id, fecha)",
            "CREATE INDEX IF NOT EXISTS idx_devoluciones_venta ON devoluciones(venta_id)",
            "CREATE INDEX IF NOT EXISTS idx_devolucion_detalle_venta_prod ON devolucion_detalle(venta_id, producto_id)",
            "CREATE INDEX IF NOT EXISTS idx_sync_queue_status ON sync_queue(status, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_sync_queue_entity ON sync_queue(entity_type, entity_id)",
            "CREATE INDEX IF NOT EXISTS idx_productos_busqueda_local ON productos(activo, nombre, codigo_barras)",
            "CREATE INDEX IF NOT EXISTS idx_ventas_fecha_local ON ventas(fecha)",
            "CREATE INDEX IF NOT EXISTS idx_detalle_ventas_venta_local ON detalle_ventas(venta_id)",
            "CREATE INDEX IF NOT EXISTS idx_movimientos_producto_fecha_local ON movimientos(producto_id, fecha)",
            "CREATE INDEX IF NOT EXISTS idx_movimientos_num_factura ON movimientos(num_factura)",
            "CREATE INDEX IF NOT EXISTS idx_mov_inventario_producto ON movimientos_inventario(producto_id, fecha)",
            "CREATE INDEX IF NOT EXISTS idx_historial_precios_prod_fecha ON historial_precios(producto_id, fecha)",
        ]
        for statement in indexes:
            schema_bootstrap.create_index_if_missing(conn, statement)

        # Migración: egresos_caja tenía una FK a 'cajas' (tabla inexistente) que
        # impedía registrar egresos cuando foreign_keys=ON. Se reconstruye la
        # tabla sin esa restricción rota, preservando los datos. Idempotente.
        try:
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='egresos_caja'"
            ).fetchone()
            old_sql = row[0] if row else None
            if old_sql and 'REFERENCES cajas' in old_sql:
                import re as _re
                nuevo_sql = _re.sub(
                    r",\s*FOREIGN KEY\s*\(\s*id_caja\s*\)\s*REFERENCES\s+cajas\s*\(\s*id\s*\)",
                    "", old_sql, flags=_re.IGNORECASE)
                nuevo_sql = nuevo_sql.replace(
                    "CREATE TABLE egresos_caja", "CREATE TABLE egresos_caja_fix", 1)
                conn.execute("PRAGMA foreign_keys=OFF")
                conn.execute("DROP TABLE IF EXISTS egresos_caja_fix")
                conn.execute(nuevo_sql)
                cols = [r[1] for r in conn.execute("PRAGMA table_info(egresos_caja)")]
                col_list = ", ".join(cols)
                conn.execute(
                    f"INSERT INTO egresos_caja_fix ({col_list}) "
                    f"SELECT {col_list} FROM egresos_caja")
                conn.execute("DROP TABLE egresos_caja")
                conn.execute("ALTER TABLE egresos_caja_fix RENAME TO egresos_caja")
                conn.execute("PRAGMA foreign_keys=ON")
        except sqlite3.Error as _exc:
            raise schema_bootstrap.SchemaBootstrapError(
                f"No se pudo corregir FK de egresos_caja: {_exc}"
            ) from _exc

        # Migración: limpiar movimientos legacy 'COBRO_CREDITO' con producto_id=-1.
        # Eran un marcador de cobro de crédito (no inventario) que violaba la FK
        # movimientos→productos y rompía el registro de abonos con foreign_keys=ON.
        # El cobro se rastrea en abonos_ventas + ventas.estado_pago; estos
        # movimientos se filtraban en toda la UI y nunca se sincronizaban.
        try:
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='movimientos'"
            ).fetchone():
                conn.execute("PRAGMA foreign_keys=OFF")
                conn.execute(
                    "DELETE FROM movimientos WHERE tipo='COBRO_CREDITO' AND producto_id=-1")
                conn.execute("PRAGMA foreign_keys=ON")
        except sqlite3.Error as _exc:
            raise schema_bootstrap.SchemaBootstrapError(
                f"No se pudo limpiar COBRO_CREDITO legacy: {_exc}"
            ) from _exc

        # Registrar la versión de esquema aplicada (etiqueta; no selecciona
        # migraciones — ver version.py).
        from version import SCHEMA_VERSION
        conn.execute("""
            INSERT INTO sync_state (clave, valor, updated_at)
            VALUES ('schema_version', ?, ?)
            ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor,
                                             updated_at = excluded.updated_at
        """, (str(SCHEMA_VERSION), now_iso()))

        # Estrategia B: local_id (UUID) como identidad de sincronización.
        ensure_local_id_unique(conn)

        conn.commit()

        # Identidad de dispositivo (ADR-0003 capa 1B): UUID persistente.
        # No escribe device_id de fila ni habilita autoridad offline.
        from local_first_config import get_or_create_device_id
        get_or_create_device_id()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def normalize_table_name(entity_type):
    return table_for_entity(entity_type)


def enqueue_sync(conn, entity_type, entity_id, operation, payload, table_name=None):
    table_name = table_name or normalize_table_name(entity_type)
    conn.execute(
        """
        INSERT INTO sync_queue
            (entity_type, entity_id, table_name, operation, payload, status, attempts, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?)
        """,
        (
            entity_type,
            str(entity_id),
            table_name,
            operation,
            json.dumps(payload, ensure_ascii=False, default=str),
            now_iso(),
            now_iso(),
        ),
    )


def ensure_local_id_unique(conn):
    """Estrategia B — Fase 1 (lado LOCAL/SQLite): garantiza que cada fila de las
    tablas sincronizadas tenga un local_id (UUID), deduplica los repetidos y crea
    un índice UNIQUE sobre local_id. Automático, idempotente y NO destructivo
    (no borra ni cambia ids). Necesario para que el pull/push puedan usar
    local_id como identidad (ON CONFLICT(local_id))."""
    for table in SYNC_TABLES:
        cols = table_columns(conn, table)
        if "local_id" not in cols:
            continue
        declared_pk = pk_column(table)
        if declared_pk in cols:
            pk = declared_pk
        elif "id" in cols:
            pk = "id"
        else:
            pk = "rowid"
        try:
            # 1) Backfill: UUID a las filas sin local_id.
            faltantes = conn.execute(
                f"SELECT {pk} AS pk FROM {table} WHERE local_id IS NULL OR local_id = ''"
            ).fetchall()
            for r in faltantes:
                conn.execute(
                    f"UPDATE {table} SET local_id = ? WHERE {pk} = ?",
                    (str(uuid.uuid4()), r["pk"]))
            # 2) Dedupe: si un local_id se repite, reasignar UUID a los extra
            #    (conservando el de menor identificador).
            dups = conn.execute(
                f"SELECT local_id FROM {table} WHERE local_id IS NOT NULL "
                f"AND local_id <> '' GROUP BY local_id HAVING COUNT(*) > 1"
            ).fetchall()
            for d in dups:
                ids = [x["pk"] for x in conn.execute(
                    f"SELECT {pk} AS pk FROM {table} WHERE local_id = ? ORDER BY {pk}",
                    (d["local_id"],)).fetchall()]
                for extra_id in ids[1:]:
                    conn.execute(
                        f"UPDATE {table} SET local_id = ? WHERE {pk} = ?",
                        (str(uuid.uuid4()), extra_id))
            # 3) Índice UNIQUE.
            conn.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_local_id "
                f"ON {table}(local_id)")
        except sqlite3.Error as exc:
            raise schema_bootstrap.SchemaBootstrapError(
                f"Migración local_id en {table}: {exc}"
            ) from exc
    conn.commit()


def new_local_id():
    """UUID global estable. No deriva de hostname, id entero, fecha ni nombre."""
    return str(uuid.uuid4())


def _row_pk(table, columns):
    declared_pk = pk_column(table)
    if declared_pk in columns:
        return declared_pk
    if "id" in columns:
        return "id"
    return "rowid"


def ensure_local_id(conn, table, row_id):
    columns = table_columns(conn, table)
    if "local_id" not in columns:
        return None
    pk = _row_pk(table, columns)
    row = conn.execute(
        f"SELECT local_id FROM {table} WHERE {pk} = ?", (row_id,)
    ).fetchone()
    if not row:
        return None
    local_id = row["local_id"]
    if not local_id:
        local_id = new_local_id()
        if "updated_at" in columns:
            conn.execute(
                f"UPDATE {table} SET local_id = ?, updated_at = ? WHERE {pk} = ?",
                (local_id, now_iso(), row_id),
            )
        else:
            conn.execute(
                f"UPDATE {table} SET local_id = ? WHERE {pk} = ?",
                (local_id, row_id),
            )
    return local_id


def enqueue_entity(conn, entity_type, entity_id, operation, table_name):
    """Alimenta el outbox (sync_queue) para un registro escrito por el admin,
    replicando el mismo patrón que usa el servidor LAN: asegura un local_id,
    marca la fila como pendiente y encola el payload completo para que el
    servicio local-first lo suba a Supabase.

    Debe llamarse dentro de la MISMA transacción del repositorio y ANTES del
    commit, para que el cambio y su encolado sean atómicos. Tolera tablas sin
    columnas de sincronización (no hace nada si la fila no existe).
    """
    columns = table_columns(conn, table_name)
    pk = _row_pk(table_name, columns)
    ensure_local_id(conn, table_name, entity_id)
    sets, params = [], []
    if "sync_status" in columns:
        sets.append("sync_status = 'pending'")
    if "updated_at" in columns:
        sets.append("updated_at = ?")
        params.append(now_iso())
    if sets:
        params.append(entity_id)
        conn.execute(
            f"UPDATE {table_name} SET {', '.join(sets)} WHERE {pk} = ?", params)
    row = conn.execute(
        f"SELECT * FROM {table_name} WHERE {pk} = ?", (entity_id,)).fetchone()
    payload = row_to_dict(row)
    if payload is None:
        return None
    enqueue_sync(conn, entity_type, entity_id, operation, payload, table_name)
    return payload


def get_sync_status(db_path=DEFAULT_DB_PATH):
    conn = connect(db_path)
    try:
        counts = {
            row["status"]: row["total"]
            for row in conn.execute("SELECT status, COUNT(*) AS total FROM sync_queue GROUP BY status")
        }
        state = {
            row["clave"]: row["valor"]
            for row in conn.execute("SELECT clave, valor FROM sync_state")
        }
        entity_counts = {
            row["entity_type"]: row["total"]
            for row in conn.execute(
                """
                SELECT entity_type, COUNT(*) AS total
                FROM sync_queue
                WHERE status IN ('pending', 'failed')
                GROUP BY entity_type
                """
            )
        }
        conflicts = conn.execute(
            "SELECT COUNT(*) AS total FROM sync_conflicts WHERE status = 'pending'"
        ).fetchone()["total"]
        return {
            "pending": counts.get("pending", 0),
            "syncing": counts.get("syncing", 0),
            "synced": counts.get("synced", 0),
            "failed": counts.get("failed", 0),
            "conflicts": conflicts,
            "entities": entity_counts,
            "last_success": state.get("last_success"),
            "last_attempt": state.get("last_attempt"),
            "last_error": state.get("last_error"),
        }
    finally:
        conn.close()
