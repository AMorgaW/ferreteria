# -*- coding: utf-8 -*-
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import psycopg2
import psycopg2.extras
import psycopg2.extensions

from local_first_db import (DEFAULT_DB_PATH, SYNC_TABLES, connect,
                            ensure_local_first_schema, now_iso)

# Fechas/horas de Postgres como TEXTO (igual que SQLite) para poder guardarlas
# directamente en columnas TEXT locales durante el pull.
try:
    psycopg2.extensions.register_type(
        psycopg2.extensions.new_type((1082, 1083, 1114, 1184), "TS_TXT",
                                     lambda v, c: v))
except Exception:
    pass


def load_env():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


load_env()


# ── Estrategia B: identidad de sincronización por local_id (UUID) ──────────
# Grafo de claves foráneas: tabla -> [(columna_fk, tabla_padre), ...].
# Se usa para TRADUCIR las FKs entre el espacio de ids local y el remoto,
# usando local_id (UUID) como pivote estable entre equipos.
FK_MAP = {
    "productos": [("proveedor_id", "proveedores")],
    "ventas": [("cliente_id", "clientes"), ("usuario_id", "usuarios")],
    "compras": [("proveedor_id", "proveedores"), ("usuario_id", "usuarios")],
    "cierres_caja": [("usuario_id", "usuarios")],
    "detalle_ventas": [("producto_id", "productos"), ("venta_id", "ventas")],
    "detalle_compras": [("producto_id", "productos"), ("compra_id", "compras")],
    "abonos_ventas": [("id_venta", "ventas")],
    "abonos_compras": [("id_compra", "compras")],
    "movimientos": [("producto_id", "productos"), ("proveedor_id", "proveedores"),
                    ("usuario_id", "usuarios")],
    "movimientos_inventario": [("producto_id", "productos"), ("proveedor_id", "proveedores"),
                               ("usuario_id", "usuarios"), ("cliente_id", "clientes")],
    "egresos_caja": [("id_caja", "cierres_caja")],
    "cuentas_por_cobrar": [("cliente_id", "clientes"), ("venta_id", "ventas")],
    "pagos_cuentas": [("cuenta_id", "cuentas_por_cobrar")],
    "auditoria": [("usuario_id", "usuarios")],
    "historial_precios": [("producto_id", "productos"), ("usuario_id", "usuarios")],
}

# Orden topológico: PADRES antes que HIJOS (evita registros huérfanos al bajar).
TOPO_ORDER = [
    "usuarios", "proveedores", "clientes", "configuracion",
    "productos", "ventas", "compras", "cierres_caja", "auditoria",
    "detalle_ventas", "detalle_compras", "abonos_ventas", "abonos_compras",
    "movimientos", "movimientos_inventario", "egresos_caja",
    "historial_precios", "cuentas_por_cobrar",
    "pagos_cuentas",
]


class _PadreNoSincronizado(Exception):
    """El registro padre referenciado por una FK aún no existe en el destino;
    la fila se difiere (queda pendiente) y se reintenta en el siguiente ciclo."""


class SupabaseSyncService:
    def __init__(self, db_path=DEFAULT_DB_PATH, database_url=None, interval=10):
        self.db_path = db_path
        self.database_url = database_url or os.environ.get("SUPABASE_URI", "")
        self.interval = int(os.environ.get("SYNC_INTERVAL_SECONDS", interval))
        self._stop = threading.Event()
        self._thread = None

    def start_background(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="supabase-sync", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _loop(self):
        while not self._stop.is_set():
            self.sync_once(limit=50)
            self._stop.wait(self.interval)

    def _set_state(self, conn, key, value):
        conn.execute(
            """
            INSERT INTO sync_state (clave, valor, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor, updated_at = excluded.updated_at
            """,
            (key, str(value), now_iso()),
        )

    def _remote_connect(self):
        if not self.database_url:
            raise RuntimeError("SUPABASE_URI no esta configurado")
        remote = psycopg2.connect(self.database_url, connect_timeout=8)
        try:
            self._ensure_remote_schema(remote)
            if getattr(self, '_schema_ensured', False):
                remote.commit()
        except Exception:
            # Si no puede ejecutar la migración, no bloqueamos la conexión;
            # el error real se mostrará al intentar sincronizar.
            pass
        try:
            self._ensure_remote_local_id_identity(remote)
        except Exception:
            pass
        return remote

    def _ensure_remote_local_id_identity(self, remote):
        """Estrategia B — Fase 1 (lado REMOTO/Supabase): rellena local_id
        faltantes, deduplica y crea índice UNIQUE sobre local_id (requisito para
        el UPSERT `ON CONFLICT (local_id)`). Idempotente; se ejecuta una vez por
        proceso."""
        if getattr(self, "_remote_identity_ensured", False):
            return
        from local_first_db import SYNC_TABLES as _ST
        with remote.cursor() as cur:
            cur.execute("SELECT table_name FROM information_schema.columns "
                        "WHERE table_schema='public' AND column_name='local_id'")
            con_local_id = {r[0] for r in cur.fetchall()}
            cur.execute("SELECT table_name FROM information_schema.columns "
                        "WHERE table_schema='public' AND column_name='id'")
            con_id = {r[0] for r in cur.fetchall()}
        for table in _ST:
            if table not in con_local_id:
                continue
            try:
                with remote.cursor() as cur:
                    cur.execute(
                        f"UPDATE {table} SET local_id = gen_random_uuid()::text "
                        f"WHERE local_id IS NULL OR local_id = ''")
                    # ctid = identificador físico de fila en Postgres (sirve
                    # incluso para tablas sin columna 'id', p. ej. configuracion).
                    cur.execute(
                        f"WITH d AS (SELECT ctid, row_number() OVER "
                        f"(PARTITION BY local_id ORDER BY ctid) rn FROM {table} "
                        f"WHERE local_id IS NOT NULL AND local_id <> '') "
                        f"UPDATE {table} t SET local_id = gen_random_uuid()::text "
                        f"FROM d WHERE t.ctid = d.ctid AND d.rn > 1")
                    cur.execute(
                        f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{table}_local_id "
                        f"ON {table}(local_id)")
                    # Avanzar la secuencia del id por encima del MAX(id) actual:
                    # como el push ya NO envía el id local (Supabase asigna el
                    # suyo), la secuencia debe estar adelantada para que el id
                    # autogenerado no choque con uno existente. Solo para tablas
                    # con columna 'id' (configuracion es clave-valor, no aplica).
                    if table in con_id:
                        cur.execute(
                            "SELECT pg_get_serial_sequence(%s, 'id')", (table,))
                        seqrow = cur.fetchone()
                        if seqrow and seqrow[0]:
                            cur.execute(
                                f"SELECT setval('{seqrow[0]}', "
                                f"COALESCE((SELECT MAX(id) FROM {table}), 1), true)")
                remote.commit()
            except Exception as e:
                remote.rollback()
                print(f"[MIGRACION local_id remoto] {table}: {e}")
        self._remote_identity_ensured = True

    def _ensure_remote_schema(self, remote):
        if getattr(self, '_schema_ensured', False):
            return
        script_path = Path(__file__).resolve().parent / 'supabase_local_first_migration.sql'
        if not script_path.exists():
            return
        with remote.cursor() as cursor:
            cursor.execute(script_path.read_text(encoding='utf-8'))
        self._schema_ensured = True

    def test_connection(self):
        remote = None
        try:
            remote = self._remote_connect()
            with remote.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            return {"ok": True, "message": "Supabase conectado correctamente"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}
        finally:
            if remote:
                remote.close()

    def validar_arranque(self):
        """Validación obligatoria de Supabase al iniciar el sistema. Comprueba
        conectividad, credenciales, acceso a la BD, lectura, escritura y la
        existencia de las tablas requeridas. Devuelve un dict con el detalle
        de cada chequeo y un 'ok' global."""
        res = {"ok": False, "conectividad": False, "lectura": False,
               "escritura": False, "tablas_ok": False, "faltan_tablas": [],
               "mensaje": ""}
        if not self.database_url:
            res["mensaje"] = "SUPABASE_URI no está configurado (modo solo local)."
            return res
        remote = None
        try:
            import psycopg2 as _pg
            remote = _pg.connect(self.database_url, connect_timeout=8)
            res["conectividad"] = True
            with remote.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
                res["lectura"] = True
                # Tablas requeridas (las críticas del negocio)
                requeridas = ["productos", "clientes", "proveedores", "ventas",
                              "detalle_ventas", "movimientos", "usuarios",
                              "compras", "cuentas_por_cobrar"]
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema='public'")
                existentes = {r[0] for r in cur.fetchall()}
                faltan = [t for t in requeridas if t not in existentes]
                res["faltan_tablas"] = faltan
                res["tablas_ok"] = not faltan
                # Prueba de escritura sobre sync_state (tabla de control propia)
                try:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS sync_state (
                            clave text PRIMARY KEY, valor text,
                            updated_at timestamp)""")
                    cur.execute("""
                        INSERT INTO sync_state (clave, valor, updated_at)
                        VALUES ('arranque_check', %s, now())
                        ON CONFLICT (clave) DO UPDATE SET valor=EXCLUDED.valor,
                            updated_at=EXCLUDED.updated_at""",
                        (str(now_iso()),))
                    remote.commit()
                    res["escritura"] = True
                except Exception:
                    remote.rollback()
            res["ok"] = (res["conectividad"] and res["lectura"]
                         and res["escritura"] and res["tablas_ok"])
            res["mensaje"] = ("Supabase disponible y verificado." if res["ok"]
                              else "Supabase respondió pero faltan permisos o tablas: "
                              + (", ".join(res["faltan_tablas"]) or "escritura"))
        except Exception as exc:
            texto = str(exc)
            low = texto.lower()
            # Firma típica de un proyecto Supabase PAUSADO: el pooler responde
            # pero no encuentra el tenant, o el host directo no resuelve.
            if ("tenant" in low and "not found" in low) or "getaddrinfo failed" in low \
                    or "could not translate host name" in low or "name or service not known" in low:
                res["proyecto_pausado"] = True
                res["mensaje"] = (
                    "El proyecto de Supabase parece estar PAUSADO o inactivo.\n\n"
                    "La cadena de conexión es correcta, pero el servicio no responde. "
                    "Los proyectos gratuitos de Supabase se pausan tras varios días "
                    "sin actividad.\n\n"
                    "SOLUCIÓN: entra a https://supabase.com/dashboard, abre tu "
                    "proyecto y pulsa «Restore»/«Resume» para reactivarlo. En unos "
                    "minutos estará disponible y podrás pulsar «Reintentar conexión»."
                    f"\n\n(Detalle técnico: {texto.splitlines()[0][:120]})")
            else:
                res["mensaje"] = f"No fue posible conectarse a Supabase: {texto}"
        finally:
            if remote:
                remote.close()
        return res

    # Tablas que se replican a Supabase (deben tener columna local_id).
    SYNCED_TABLES = [
        ("productos", "product"), ("clientes", "customer"),
        ("proveedores", "supplier"), ("usuarios", "user"),
        ("ventas", "sale"), ("detalle_ventas", "sale_detail"),
        ("movimientos", "inventory_movement"),
        ("movimientos_inventario", "inventory_movement2"),
        ("cuentas_por_cobrar", "receivable"), ("abonos_ventas", "sale_payment"),
        ("cierres_caja", "cash_session"), ("egresos_caja", "cash_expense"),
        ("compras", "purchase"), ("detalle_compras", "purchase_detail"),
        ("abonos_compras", "purchase_payment"),
        ("auditoria", "audit_log"), ("historial_precios", "price_history"),
    ]

    def backfill_to_remote(self):
        """Repara la consistencia histórica local <-> Supabase:

        1) RECONCILIA local_id: para filas que ya existen en ambos lados (por id)
           pero cuyo local_id en Supabase es NULL o distinto, copia el local_id
           local al remoto. Esto evita que los UPDATE de filas creadas antes del
           local-first fallen con colisión de PK (el upsert usa ON CONFLICT
           (local_id)).
        2) ENCOLA huérfanos: filas locales que aún no existen en Supabase.

        Idempotente. Devuelve {'encolados':{...}, 'reconciliados':{...}}."""
        from local_first_db import enqueue_entity, ensure_local_id, table_columns
        local = connect(self.db_path)
        remote = None
        encolados, reconciliados = {}, {}
        try:
            remote = self._remote_connect()
            for table, entity_type in self.SYNCED_TABLES:
                cols = table_columns(local, table)
                if "local_id" not in cols:
                    continue
                try:
                    with remote.cursor() as rc:
                        rc.execute(f"SELECT id, local_id FROM {table}")
                        remote_map = {row[0]: row[1] for row in rc.fetchall()}
                except Exception:
                    continue
                n_enq, n_rec = 0, 0
                rows = local.execute(f"SELECT id, local_id FROM {table}").fetchall()
                for row in rows:
                    rid = row["id"]
                    lid = row["local_id"] or ensure_local_id(local, table, rid)
                    if rid in remote_map:
                        if remote_map[rid] != lid:
                            try:
                                with remote.cursor() as rc:
                                    rc.execute(
                                        f"UPDATE {table} SET local_id=%s WHERE id=%s",
                                        (lid, rid))
                                n_rec += 1
                            except Exception:
                                remote.rollback()
                    else:
                        enqueue_entity(local, entity_type, rid, "create", table)
                        n_enq += 1
                remote.commit()
                if n_enq:
                    encolados[table] = n_enq
                if n_rec:
                    reconciliados[table] = n_rec
            local.commit()
            return {"encolados": encolados, "reconciliados": reconciliados}
        finally:
            if remote:
                remote.close()
            local.close()

    def retry_failed(self):
        local = connect(self.db_path)
        try:
            cursor = local.execute(
                "UPDATE sync_queue SET status='pending', updated_at=? WHERE status='failed'",
                (now_iso(),),
            )
            local.commit()
            return {"updated": cursor.rowcount}
        finally:
            local.close()

    def cleanup_synced(self, keep_latest=500):
        local = connect(self.db_path)
        try:
            cursor = local.execute(
                """
                DELETE FROM sync_queue
                WHERE status='synced'
                  AND id NOT IN (
                    SELECT id FROM sync_queue
                    WHERE status='synced'
                    ORDER BY synced_at DESC, id DESC
                    LIMIT ?
                  )
                """,
                (keep_latest,),
            )
            local.commit()
            return {"deleted": cursor.rowcount}
        finally:
            local.close()

    def sync_once(self, limit=50):
        ensure_local_first_schema(self.db_path)
        local = connect(self.db_path)
        self._set_state(local, "last_attempt", now_iso())
        local.commit()

        rows = local.execute(
            """
            SELECT * FROM sync_queue
            WHERE status IN ('pending', 'failed')
            ORDER BY created_at
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        if not rows:
            local.close()
            return {"processed": 0, "synced": 0, "failed": 0}

        synced = 0
        failed = 0
        diferidos = 0
        remote = None
        cache = {}  # mapas de traducción de FKs por ciclo
        try:
            remote = self._remote_connect()
            remote.autocommit = False
            for row in rows:
                local.execute(
                    "UPDATE sync_queue SET status='syncing', updated_at=? WHERE id=?",
                    (now_iso(), row["id"]),
                )
                local.commit()
                try:
                    remote_id = self._sync_row(remote, local, row, cache)
                    remote.commit()
                    self._marcar_sincronizada(local, row, remote_id)
                    local.execute(
                        """
                        UPDATE sync_queue
                        SET status='synced', synced_at=?, updated_at=?, last_error=NULL
                        WHERE id=?
                        """,
                        (now_iso(), now_iso(), row["id"]),
                    )
                    synced += 1
                except _PadreNoSincronizado as exc:
                    # El padre aún no está en Supabase: se difiere (queda pendiente)
                    # y se reintenta en el siguiente ciclo, cuando el padre ya esté.
                    remote.rollback()
                    diferidos += 1
                    local.execute(
                        "UPDATE sync_queue SET status='pending', last_error=?, updated_at=? WHERE id=?",
                        (f"diferido: {exc}", now_iso(), row["id"]),
                    )
                except Exception as exc:
                    remote.rollback()
                    failed += 1
                    local.execute(
                        """
                        UPDATE sync_queue
                        SET status='failed', attempts=attempts+1, last_error=?, updated_at=?
                        WHERE id=?
                        """,
                        (str(exc), now_iso(), row["id"]),
                    )
                local.commit()

            if failed == 0:
                self._set_state(local, "last_success", now_iso())
                self._set_state(local, "last_error", "")
            else:
                self._set_state(local, "last_error", f"{failed} registro(s) con error")
            local.commit()
            return {"processed": len(rows), "synced": synced, "failed": failed,
                    "diferidos": diferidos}
        except Exception as exc:
            self._set_state(local, "last_error", str(exc))
            local.execute(
                "UPDATE sync_queue SET status='pending', updated_at=? WHERE status='syncing'",
                (now_iso(),),
            )
            local.commit()
            return {"processed": len(rows), "synced": synced, "failed": len(rows)}
        finally:
            if remote:
                remote.close()
            local.close()

    # Tablas "padre" primero (aunque se desactivan las FK durante la carga).
    PULL_ORDER = [
        "usuarios", "configuracion", "productos", "clientes", "proveedores",
        "compras", "ventas", "cierres_caja", "detalle_compras", "detalle_ventas",
        "movimientos", "movimientos_inventario", "egresos_caja", "abonos_ventas",
        "abonos_compras", "cuentas_por_cobrar", "pagos_cuentas",
        "historial_precios", "auditoria",
    ]

    def _get_state(self, local, key, default=None):
        """Lee un valor de la tabla sync_state (clave-valor)."""
        try:
            row = local.execute(
                "SELECT valor FROM sync_state WHERE clave = ?", (key,)).fetchone()
            return row[0] if row else default
        except Exception:
            return default

    def pull_from_remote(self, progress=None, since=None):
        """Descarga datos de Supabase a la BD LOCAL (upsert por id).

        - since=None  -> descarga COMPLETA (se usa al iniciar sesión).
        - since='...' -> descarga solo filas con updated_at > since (DELTA), para
          el chequeo periódico y la reconexión: baja únicamente lo que cambió.

        No borra filas locales ausentes en la nube (no destructivo). Devuelve
        {'ok', 'rows', 'skipped', 'watermark'} donde watermark es el mayor
        updated_at visto (para avanzar la marca de deltas)."""
        if not self.database_url:
            return {"ok": False, "error": "SUPABASE_URI no configurado", "rows": 0}
        ensure_local_first_schema(self.db_path)
        # Orden topológico (padres antes que hijos) para no dejar huérfanos al
        # traducir las FKs.
        tablas = ([t for t in TOPO_ORDER if t in SYNC_TABLES]
                  + [t for t in SYNC_TABLES if t not in TOPO_ORDER])
        remote = None
        local = connect(self.db_path)
        total = 0
        skipped = 0
        watermark = since or ""
        cache = {}  # mapas de traducción de FKs por ciclo
        try:
            remote = self._remote_connect()
            local.execute("PRAGMA foreign_keys=OFF")
            for i, table in enumerate(tablas):
                if progress:
                    try:
                        progress(i, len(tablas), table)
                    except Exception:
                        pass
                cols_local = {r[1] for r in
                              local.execute(f"PRAGMA table_info({table})").fetchall()}
                # Identidad de sync por local_id: sin esa columna no se procesa.
                if not cols_local or "local_id" not in cols_local:
                    continue
                try:
                    with remote.cursor(
                            cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                        if since and "updated_at" in cols_local:
                            cur.execute(
                                f"SELECT * FROM {table} WHERE updated_at > %s",
                                (since,))
                        else:
                            cur.execute(f"SELECT * FROM {table}")
                        rows = cur.fetchall()
                except Exception:
                    remote.rollback()
                    continue  # tabla inexistente/ilegible en remoto
                if not rows:
                    continue
                fks = FK_MAP.get(table, [])
                for r in rows:
                    r = dict(r)
                    lid = r.get("local_id")
                    if not lid:
                        skipped += 1
                        continue  # fila remota sin local_id (se sembrará luego)
                    # Traducir las FKs remoto -> local (por local_id).
                    fk_ok = True
                    for fk_col, parent in fks:
                        val = r.get(fk_col)
                        if val is None:
                            continue
                        local_fk = self._mapa_pull(local, remote, parent, cache).get(val)
                        if local_fk is None:
                            fk_ok = False  # padre aún no local -> reintento próximo pull
                            break
                        r[fk_col] = local_fk
                    if not fk_ok:
                        skipped += 1
                        continue
                    # Columnas a escribir: intersección, EXCLUYENDO el id local
                    # (nunca se sobreescribe). El id remoto se guarda en remote_id.
                    remote_id_val = r.get("id")
                    campos = {k: v for k, v in r.items()
                              if k in cols_local and k != "id"}
                    if "remote_id" in cols_local and remote_id_val is not None:
                        campos["remote_id"] = str(remote_id_val)
                    if "local_id" not in campos:
                        skipped += 1
                        continue
                    # Compatibilidad con datos locales creados por builds
                    # anteriores: si la fila ya existe por remote_id pero tiene
                    # otro local_id, se alinea a la identidad remota antes del
                    # UPSERT. Sin esto, el pull puede insertar una segunda
                    # factura/egreso con el mismo remote_id.
                    if "remote_id" in cols_local and remote_id_val is not None:
                        try:
                            existing = local.execute(
                                f"SELECT id, local_id FROM {table} "
                                "WHERE remote_id = ? LIMIT 1",
                                (str(remote_id_val),)
                            ).fetchone()
                            if existing and existing["local_id"] != campos["local_id"]:
                                conflict = local.execute(
                                    f"SELECT id FROM {table} WHERE local_id = ? LIMIT 1",
                                    (campos["local_id"],)
                                ).fetchone()
                                if not conflict:
                                    local.execute(
                                        f"UPDATE {table} SET local_id = ? WHERE id = ?",
                                        (campos["local_id"], existing["id"])
                                    )
                        except Exception:
                            pass
                    cols = list(campos.keys())
                    ph = ",".join(["?"] * len(cols))
                    collist = ",".join(cols)
                    upd = ",".join([f"{c}=excluded.{c}" for c in cols if c != "local_id"])
                    sql = (f"INSERT INTO {table} ({collist}) VALUES ({ph}) "
                           f"ON CONFLICT(local_id) DO UPDATE SET {upd}")
                    try:
                        local.execute(sql, [campos[c] for c in cols])
                        total += 1
                        ts = r.get("updated_at")
                        if ts and str(ts) > watermark:
                            watermark = str(ts)
                    except Exception:
                        skipped += 1
                local.commit()
                # Invalidar el mapa de este padre para que los HIJOS siguientes
                # vean las filas recién insertadas.
                cache.pop(("pullmap", table), None)
            local.execute("PRAGMA foreign_keys=ON")
            local.commit()
            return {"ok": True, "rows": total, "skipped": skipped,
                    "watermark": watermark}
        except Exception as exc:
            try:
                local.rollback()
            except Exception:
                pass
            return {"ok": False, "error": str(exc), "rows": total,
                    "skipped": skipped, "watermark": watermark}
        finally:
            if remote:
                remote.close()
            local.close()

    def set_pull_watermark(self, watermark):
        """Guarda la marca (mayor updated_at descargado) para los deltas."""
        if not watermark:
            return
        local = connect(self.db_path)
        try:
            self._set_state(local, "pull_watermark", watermark)
            local.commit()
        finally:
            local.close()

    def pull_delta(self, progress=None):
        """Chequeo periódico / reconexión: descarga SOLO lo cambiado en Supabase
        desde la última marca (updated_at). Barato: si no hubo cambios, baja 0
        filas. Avanza la marca. Devuelve el dict de pull_from_remote (con 'rows'
        = nº de filas cambiadas descargadas)."""
        local = connect(self.db_path)
        try:
            since = self._get_state(local, "pull_watermark")
        finally:
            local.close()
        res = self.pull_from_remote(progress=progress, since=since)
        if res.get("ok"):
            wm = res.get("watermark")
            # Avanzar la marca solo si creció (evita retroceder por filas viejas).
            if wm and (not since or str(wm) > str(since)):
                self.set_pull_watermark(wm)
        return res

    def _mapa_push(self, local, remote, parent, cache):
        """{ id_local_padre : id_remoto_padre }  (pivote local_id). Precarga una
        vez por tabla padre y por ciclo."""
        k = ("pushmap", parent)
        if k in cache:
            return cache[k]
        loc = {r["id"]: r["local_id"] for r in
               local.execute(f"SELECT id, local_id FROM {parent}") if r["local_id"]}
        with remote.cursor() as cur:
            cur.execute(f"SELECT local_id, id FROM {parent} WHERE local_id IS NOT NULL")
            rem = {r[0]: r[1] for r in cur.fetchall()}
        m = {lid: rem.get(luid) for lid, luid in loc.items()}
        cache[k] = m
        return m

    def _mapa_pull(self, local, remote, parent, cache):
        """{ id_remoto_padre : id_local_padre }  (pivote local_id)."""
        k = ("pullmap", parent)
        if k in cache:
            return cache[k]
        with remote.cursor() as cur:
            cur.execute(f"SELECT id, local_id FROM {parent} WHERE local_id IS NOT NULL")
            rem = {r[0]: r[1] for r in cur.fetchall()}
        loc = {r["local_id"]: r["id"] for r in
               local.execute(f"SELECT id, local_id FROM {parent}") if r["local_id"]}
        m = {rid: loc.get(ruid) for rid, ruid in rem.items()}
        cache[k] = m
        return m

    def _sync_row(self, remote, local, queue_row, cache):
        table = queue_row["table_name"]
        operation = queue_row["operation"]
        payload = json.loads(queue_row["payload"])
        local_id = payload.get("local_id")

        if operation == "delete":
            if "is_deleted" in payload or "deleted_at" in payload:
                return self._upsert(remote, local, table, payload, cache)
            # Borrado por local_id (identidad de sync), no por id local.
            if local_id:
                with remote.cursor() as cur:
                    cur.execute(f"DELETE FROM {table} WHERE local_id = %s", (local_id,))
            elif "id" in payload:
                with remote.cursor() as cur:
                    cur.execute(f"DELETE FROM {table} WHERE id = %s", (payload["id"],))
            return None

        return self._upsert(remote, local, table, payload, cache)

    def _upsert(self, remote, local, table, payload, cache):
        """PUSH con identidad local_id: traduce las FKs (id local -> id remoto),
        NO envía el id local (Supabase asigna el suyo) y hace UPSERT por
        local_id. Devuelve el id remoto asignado (para guardar remote_id)."""
        payload = dict(payload)  # copia; no mutar el original
        # Traducir claves foráneas al espacio de ids remoto.
        for fk_col, parent in FK_MAP.get(table, []):
            val = payload.get(fk_col)
            if val is None:
                continue
            rid = self._mapa_push(local, remote, parent, cache).get(val)
            if rid is None:
                raise _PadreNoSincronizado(
                    f"{table}.{fk_col} -> {parent} (id local {val}) aún no está en Supabase")
            payload[fk_col] = rid

        # Excluir el id local: la identidad de sincronización es local_id.
        clean = {k: v for k, v in payload.items() if v is not None and k != "id"}
        if "local_id" not in clean:
            return None  # sin local_id no hay identidad (no debería pasar tras Fase 1)
        columns = list(clean.keys())
        placeholders = ", ".join(["%s"] * len(columns))
        col_sql = ", ".join(columns)
        updates = ", ".join([f"{c}=EXCLUDED.{c}" for c in columns if c != "local_id"])
        if not updates:
            updates = "local_id=EXCLUDED.local_id"
        values = [clean[c] for c in columns]
        sql = f"""
            INSERT INTO {table} ({col_sql})
            VALUES ({placeholders})
            ON CONFLICT (local_id) DO UPDATE SET {updates}
            RETURNING id
        """
        with remote.cursor() as cur:
            cur.execute(sql, values)
            row = cur.fetchone()
            remote_id = row[0] if row else None
        # Actualizar el mapa de push en caliente para que un HIJO en el MISMO
        # ciclo encuentre a este padre recién subido (evita diferir 1 ciclo).
        if remote_id is not None and payload.get("id") is not None:
            cache.setdefault(("pushmap", table), {})[payload["id"]] = remote_id
        return remote_id

    def _marcar_sincronizada(self, local, queue_row, remote_id):
        """Guarda en la fila local (por local_id) el remote_id y la marca como
        sincronizada. No afecta el id local ni la lógica de negocio."""
        try:
            payload = json.loads(queue_row["payload"])
            lid = payload.get("local_id")
            table = queue_row["table_name"]
            if not lid or remote_id is None:
                return
            cols = {r["name"] for r in local.execute(f"PRAGMA table_info({table})")}
            sets, params = [], []
            if "remote_id" in cols:
                sets.append("remote_id=?"); params.append(str(remote_id))
            if "last_synced_at" in cols:
                sets.append("last_synced_at=?"); params.append(now_iso())
            if "sync_status" in cols:
                sets.append("sync_status='synced'")
            if sets:
                params.append(lid)
                local.execute(
                    f"UPDATE {table} SET {', '.join(sets)} WHERE local_id=?", params)
        except Exception:
            pass


_SERVICE = None


def get_service(db_path=DEFAULT_DB_PATH):
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = SupabaseSyncService(db_path=db_path)
    return _SERVICE


if __name__ == "__main__":
    ensure_local_first_schema(DEFAULT_DB_PATH)
    result = get_service(DEFAULT_DB_PATH).sync_once()
    print(result)
