# -*- coding: utf-8 -*-
"""Helpers de outbox para que los repositorios del admin alimenten la cola
local-first (sync_queue) igual que lo hace el servidor LAN, y los cambios se
suban a Supabase. Seguros: solo actúan en modo local y nunca interrumpen la
operación principal del repositorio si algo falla."""
import os


def _es_modo_local() -> bool:
    return os.environ.get("DB_MODE", "local").strip().lower() in (
        "local", "sqlite", "server")


def encolar(conn, entity_type, entity_id, operation, table_name):
    """Encola un alta/edición. Debe llamarse dentro de la misma transacción y
    ANTES del commit."""
    if not _es_modo_local():
        return
    try:
        from local_first_db import enqueue_entity
        enqueue_entity(conn, entity_type, entity_id, operation, table_name)
    except Exception as exc:
        print(f"[SYNC] No se pudo encolar {entity_type} {entity_id}: {exc}")


def encolar_borrado(conn, entity_type, entity_id, table_name):
    """Encola un borrado remoto. Debe llamarse ANTES de borrar la fila local."""
    if not _es_modo_local():
        return
    try:
        from local_first_db import enqueue_sync
        enqueue_sync(conn, entity_type, entity_id, "delete",
                     {"id": entity_id}, table_name)
    except Exception as exc:
        print(f"[SYNC] No se pudo encolar borrado {entity_type} {entity_id}: {exc}")
