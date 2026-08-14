# -*- coding: utf-8 -*-
"""Registry canónico de sincronización FERREPRO (Fase 1B).

Fuente única declarativa. Las listas históricas (SYNC_TABLES, SYNCED_TABLES,
FK_MAP, TOPO_ORDER, PULL_ORDER) se DERIVAN de aquí; no deben volver a
mantenerse a mano.

No aplica exclusión autoritativa de ``productos.stock``: ver
``APPLY_AUTHORITATIVE_EXCLUDE``. El UPSERT LWW de stock sigue vigente (INV-02).
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


class SyncRegistryError(Exception):
    """Registry inválido: ciclo, padre ausente o identificador desconocido."""


# False en 1B–1C: declara el contrato de stock-como-proyección sin cambiar el
# UPSERT productivo. Pasar a True corresponde al coordinador (fase posterior),
# no a persistir el ledger.
APPLY_AUTHORITATIVE_EXCLUDE = False

# Prefijo canónico del UNIQUE(local_id) en PostgreSQL. El runtime histórico
# creaba `ux_*`; ambos nombres son la misma identidad, no índices distintos.
POSTGRES_LOCAL_ID_UNIQUE_INDEX_PREFIX = "uq_"
POSTGRES_LOCAL_ID_UNIQUE_INDEX_LEGACY_PREFIXES: Tuple[str, ...] = ("ux_",)


def _entry(
    entity_type: str,
    *,
    parents: Sequence[Tuple[str, str]] = (),
    pk: str = "id",
    push: bool = True,
    pull: bool = True,
    authoritative_exclude: Sequence[str] = (),
    projection_fields: Sequence[str] = (),
    required_for_startup: bool = False,
    notes: str = "",
) -> dict:
    return {
        "sync": True,
        "push": push,
        "pull": pull,
        "entity_type": entity_type,
        "pk": pk,
        "parents": tuple(parents),
        "authoritative_exclude": tuple(authoritative_exclude),
        "projection_fields": tuple(projection_fields),
        "required_for_startup": bool(required_for_startup),
        "notes": notes,
    }


# Orden de declaración = orden estable de Kahn para nodos con el mismo grado.
SYNC_REGISTRY: Dict[str, dict] = {
    "usuarios": _entry("user", required_for_startup=True),
    "proveedores": _entry("supplier", required_for_startup=True),
    "clientes": _entry(
        "customer",
        projection_fields=("saldo_pendiente",),
        required_for_startup=True,
        notes="saldo_pendiente es proyección local; no se excluye del LWW en 1B.",
    ),
    "configuracion": _entry(
        "config",
        pk="clave",
        notes=(
            "PK de negocio es clave, no id. El sync genérico usa pk_column(); "
            "no asume RETURNING id."
        ),
    ),
    "productos": _entry(
        "product",
        parents=(("proveedor_id", "proveedores"),),
        authoritative_exclude=("stock",),
        projection_fields=("stock",),
        required_for_startup=True,
        notes=(
            "local_id es la identidad global del SKU. stock es proyección; "
            "authoritative_exclude NO se aplica mientras "
            "APPLY_AUTHORITATIVE_EXCLUDE sea False."
        ),
    ),
    "ventas": _entry(
        "sale",
        parents=(("cliente_id", "clientes"), ("usuario_id", "usuarios")),
        required_for_startup=True,
    ),
    "compras": _entry(
        "purchase",
        parents=(("proveedor_id", "proveedores"), ("usuario_id", "usuarios")),
        required_for_startup=True,
    ),
    "cierres_caja": _entry(
        "cash_session",
        parents=(("usuario_id", "usuarios"),),
    ),
    "auditoria": _entry(
        "audit_log",
        parents=(("usuario_id", "usuarios"),),
    ),
    "detalle_ventas": _entry(
        "sale_detail",
        parents=(("producto_id", "productos"), ("venta_id", "ventas")),
        required_for_startup=True,
    ),
    "detalle_compras": _entry(
        "purchase_detail",
        parents=(("producto_id", "productos"), ("compra_id", "compras")),
    ),
    "abonos_ventas": _entry(
        "sale_payment",
        parents=(("id_venta", "ventas"),),
    ),
    "abonos_compras": _entry(
        "purchase_payment",
        parents=(("id_compra", "compras"),),
    ),
    "movimientos": _entry(
        "inventory_movement",
        parents=(
            ("producto_id", "productos"),
            ("proveedor_id", "proveedores"),
            ("usuario_id", "usuarios"),
        ),
        required_for_startup=True,
    ),
    "movimientos_inventario": _entry(
        "inventory_movement2",
        parents=(
            ("producto_id", "productos"),
            ("proveedor_id", "proveedores"),
            ("usuario_id", "usuarios"),
            ("cliente_id", "clientes"),
        ),
    ),
    "egresos_caja": _entry(
        "cash_expense",
        parents=(("id_caja", "cierres_caja"),),
    ),
    "historial_precios": _entry(
        "price_history",
        parents=(("producto_id", "productos"), ("usuario_id", "usuarios")),
    ),
    "cuentas_por_cobrar": _entry(
        "receivable",
        parents=(("cliente_id", "clientes"), ("venta_id", "ventas")),
        required_for_startup=True,
    ),
    "pagos_cuentas": _entry(
        "payment",
        parents=(("cuenta_id", "cuentas_por_cobrar"),),
        notes=(
            "Sin escritores productivos. El cobro real de CxC es abonos_ventas. "
            "Se mantiene en sync para no reabrir el agujero INV-18."
        ),
    ),
}


# Tablas de negocio que existen en SQLite y NO entran al sync. No omitir:
# documentar evita que una fase posterior las meta "por completitud".
NON_SYNC_TABLES: Dict[str, str] = {
    "devoluciones": "documento local; el stock viaja por movimientos+productos",
    "devolucion_detalle": "idem",
    "formulas_mezcla": "receta local; el stock viaja por movimientos+productos",
    "formula_detalle": "idem",
    "alertas": "efímero de UI",
    "categorias_config": "catálogo local de unidades",
    "resumen_deudas": "desnormalizado local",
    "consecutivos": "contador atómico de dispositivo",
    "login_intentos": "seguridad local",
    "local_sessions": "sesiones del servidor LAN",
    "sync_queue": "outbox local",
    "sync_conflicts": "cola local",
    "sync_state": "watermark local",
    "inventory_commands": (
        "ledger append-only/idempotente; no LWW. Transporte especial futuro. "
        "1C no activa push/pull."
    ),
    "inventory_operations": (
        "líneas del ledger; FK al comando. No LWW. Transporte especial futuro."
    ),
}

# PK real del DDL oficial para tablas que PgCursor puede insertar y NO están
# en SYNC_REGISTRY. No se inventa `id`: solo lo que el CREATE TABLE declara.
# Callers remotos (DB_MODE=remote → DatabaseManager.conectar):
# formulas_mezcla / devoluciones usan lastrowid; consecutivos / login_intentos
# tienen PK TEXT y no deben recibir RETURNING id.
NON_SYNC_INSERT_PK: Dict[str, str] = {
    "devoluciones": "id",
    "devolucion_detalle": "id",
    "formulas_mezcla": "id",
    "formula_detalle": "id",
    "alertas": "id",
    "categorias_config": "id",
    "resumen_deudas": "id",
    "consecutivos": "clave",
    "login_intentos": "username",
    "local_sessions": "token",
    "sync_queue": "id",
    "sync_conflicts": "id",
    "sync_state": "clave",
    "inventory_commands": "command_id",
    "inventory_operations": "operation_id",
}

REMOTE_IDENTITY_MIGRATION_FILENAME = "supabase_sync_identity.sql"


def _registry(registry: Optional[Mapping[str, dict]] = None) -> Mapping[str, dict]:
    return SYNC_REGISTRY if registry is None else registry


def sync_tables(registry: Optional[Mapping[str, dict]] = None) -> Tuple[str, ...]:
    """Antes SYNC_TABLES: tablas con columnas local_id y participación en pull."""
    return tuple(
        name for name, spec in _registry(registry).items() if spec.get("sync")
    )


def synced_tables(
    registry: Optional[Mapping[str, dict]] = None,
) -> List[Tuple[str, str]]:
    """Antes SYNCED_TABLES: (tabla, entity_type) con push=True, en orden topo."""
    reg = _registry(registry)
    out: List[Tuple[str, str]] = []
    for table in topo_order(reg):
        spec = reg[table]
        if spec.get("sync") and spec.get("push"):
            out.append((table, spec["entity_type"]))
    return out


def fk_map(
    registry: Optional[Mapping[str, dict]] = None,
) -> Dict[str, List[Tuple[str, str]]]:
    """Antes FK_MAP: solo tablas con padres."""
    result: Dict[str, List[Tuple[str, str]]] = {}
    for table, spec in _registry(registry).items():
        if not spec.get("sync"):
            continue
        parents = list(spec.get("parents") or ())
        if parents:
            result[table] = parents
    return result


def topo_order(registry: Optional[Mapping[str, dict]] = None) -> List[str]:
    """Kahn: padres antes que hijos. Ciclos → SyncRegistryError visible."""
    reg = _registry(registry)
    tables = [name for name, spec in reg.items() if spec.get("sync")]
    table_set = set(tables)
    indeg = {name: 0 for name in tables}
    children: Dict[str, List[str]] = {name: [] for name in tables}
    for table in tables:
        for _fk, parent in reg[table].get("parents") or ():
            if parent not in table_set:
                raise SyncRegistryError(
                    f"{table} referencia padre no sincronizado {parent!r}"
                )
            children[parent].append(table)
            indeg[table] += 1
    queue = [name for name in tables if indeg[name] == 0]
    order: List[str] = []
    while queue:
        node = queue.pop(0)
        order.append(node)
        for child in children[node]:
            indeg[child] -= 1
            if indeg[child] == 0:
                queue.append(child)
    if len(order) != len(tables):
        leftover = [name for name in tables if name not in order]
        raise SyncRegistryError(
            f"Ciclo de dependencia en sync registry: {leftover}"
        )
    return order


def entity_type_for(table: str) -> str:
    try:
        return SYNC_REGISTRY[table]["entity_type"]
    except KeyError as exc:
        raise SyncRegistryError(f"Tabla no está en SYNC_REGISTRY: {table}") from exc


def table_for_entity(entity_type: str) -> str:
    for table, spec in SYNC_REGISTRY.items():
        if spec.get("entity_type") == entity_type:
            return table
    return entity_type


def pk_column(table: str) -> str:
    spec = SYNC_REGISTRY.get(table)
    if spec is None:
        return "id"
    return spec.get("pk") or "id"


def declared_insert_pk(table: str) -> Optional[str]:
    """PK de INSERT para PgCursor. None = no hay metadata; no inventar ``id``.

    Sync: ``pk`` del registry. No-sync: ``NON_SYNC_INSERT_PK`` (DDL oficial).
    """
    spec = SYNC_REGISTRY.get(table)
    if spec is not None and spec.get("sync"):
        return spec.get("pk") or "id"
    return NON_SYNC_INSERT_PK.get(table)


def has_surrogate_integer_pk(table: str) -> bool:
    """True si la PK de negocio de la tabla sync es el entero `id`."""
    return pk_column(table) == "id"


def tables_with_non_surrogate_pk(
    registry: Optional[Mapping[str, dict]] = None,
) -> Tuple[str, ...]:
    """Entidades sync cuya PK de negocio no es `id` (hoy: configuracion)."""
    return tuple(
        name
        for name, spec in _registry(registry).items()
        if spec.get("sync") and (spec.get("pk") or "id") != "id"
    )


def remote_upsert_returning_column(table: str) -> str:
    """Columna RETURNING del UPSERT remoto.

    Con PK entera `id` se usa para `remote_id` y mapas de FK.
    Si la PK de negocio no es `id`, se devuelve esa PK (p.ej. `clave`).
    """
    return pk_column(table)


def remote_tables_required_for_startup(
    registry: Optional[Mapping[str, dict]] = None,
) -> Tuple[str, ...]:
    """Política de arranque, no el conjunto de sync.

    Subconjunto deliberado de tablas ``sync=True`` cuya *ausencia* en
    PostgreSQL hace fallar ``validar_arranque``. No enumera catálogos
    auxiliares sincronizables (configuracion, historial_precios, …).
    """
    return tuple(
        name
        for name, spec in _registry(registry).items()
        if spec.get("sync") and spec.get("required_for_startup")
    )


# Nombre estable para validar_arranque. Derivado del registry; no es una lista
# paralela. CRITICAL_REMOTE_TABLES queda como alias de compatibilidad.
REMOTE_TABLES_REQUIRED_FOR_STARTUP = remote_tables_required_for_startup()
CRITICAL_REMOTE_TABLES = REMOTE_TABLES_REQUIRED_FOR_STARTUP


def parents_of(table: str) -> Tuple[Tuple[str, str], ...]:
    spec = SYNC_REGISTRY.get(table)
    if spec is None:
        return ()
    return tuple(spec.get("parents") or ())


def declared_projection_fields(table: str) -> Tuple[str, ...]:
    spec = SYNC_REGISTRY.get(table) or {}
    return tuple(spec.get("projection_fields") or ())


def declared_authoritative_exclude(table: str) -> Tuple[str, ...]:
    """Contrato declarado. Independiente de si el UPSERT lo aplica."""
    spec = SYNC_REGISTRY.get(table) or {}
    return tuple(spec.get("authoritative_exclude") or ())


def fields_excluded_from_authoritative_write(table: str) -> Tuple[str, ...]:
    """Campos que el UPSERT LWW no debe tratar como autoridad.

    En 1B devuelve vacío porque APPLY_AUTHORITATIVE_EXCLUDE es False.
    """
    if not APPLY_AUTHORITATIVE_EXCLUDE:
        return ()
    return declared_authoritative_exclude(table)


def is_sync_table(table: str) -> bool:
    spec = SYNC_REGISTRY.get(table)
    return bool(spec and spec.get("sync"))


def product_field_class(column: str) -> str:
    """Clasificación de columnas de productos para el contrato de sync.

    Valores: identity_local | identity_global | remote_pointer | business_key |
    metadata | projection | sync_plumbing | unknown
    """
    mapping = {
        "id": "identity_local",
        "local_id": "identity_global",
        "remote_id": "remote_pointer",
        "codigo_barras": "business_key",
        "stock": "projection",
        "updated_at": "sync_plumbing",
        "deleted_at": "sync_plumbing",
        "is_deleted": "sync_plumbing",
        "sync_status": "sync_plumbing",
        "last_synced_at": "sync_plumbing",
        "version": "sync_plumbing",
        "device_id": "sync_plumbing",
        "created_by": "sync_plumbing",
        "updated_by": "sync_plumbing",
    }
    if column in mapping:
        return mapping[column]
    return "metadata"


def postgres_local_id_unique_index_name(table: str) -> str:
    """Nombre canónico del UNIQUE(local_id) en PostgreSQL."""
    return f"{POSTGRES_LOCAL_ID_UNIQUE_INDEX_PREFIX}{table}_local_id"


def postgres_local_id_unique_index_aliases(table: str) -> Tuple[str, ...]:
    """Nombres que representan la misma identidad UNIQUE(local_id)."""
    names = [postgres_local_id_unique_index_name(table)]
    for prefix in POSTGRES_LOCAL_ID_UNIQUE_INDEX_LEGACY_PREFIXES:
        names.append(f"{prefix}{table}_local_id")
    return tuple(names)


def tables_requiring_postgres_local_id_unique(
    registry: Optional[Mapping[str, dict]] = None,
) -> Tuple[str, ...]:
    """Definición canónica: tablas sync que requieren UNIQUE(local_id) en PG."""
    return sync_tables(registry)


# Comprobación plpgsql: cualquier UNIQUE de una columna sobre local_id cuenta,
# sea cual sea el nombre (uq_* canónico o ux_* legado).
# Fuente única del predicado: copiar este fragmento en
# supabase_local_first_migration.sql (paridad 1B.2). No generar ese archivo.
_POSTGRES_LOCAL_ID_UNIQUE_EXISTS_PLPGSQL = """\
EXISTS (
                    SELECT 1
                    FROM pg_index i
                    JOIN pg_class trel ON trel.oid = i.indrelid
                    JOIN pg_namespace nsp ON nsp.oid = trel.relnamespace
                    JOIN pg_attribute a ON a.attrelid = trel.oid
                         AND a.attnum = i.indkey[0]
                         AND NOT a.attisdropped
                    WHERE nsp.nspname = 'public'
                      AND trel.relname = t
                      AND i.indisunique
                      AND i.indpred IS NULL
                      AND i.indnkeyatts = 1
                      AND a.attname = 'local_id'
                )"""


def postgres_local_id_unique_exists_plpgsql() -> str:
    """Predicado plpgsql canónico: UNIQUE de una columna sobre local_id."""
    return _POSTGRES_LOCAL_ID_UNIQUE_EXISTS_PLPGSQL.strip()


def equivalent_local_id_unique_exists(indexes: Iterable[Mapping]) -> bool:
    """True si algún índice es UNIQUE de UNA columna ``local_id`` sin predicado.

    Codifica el mismo criterio que ``_POSTGRES_LOCAL_ID_UNIQUE_EXISTS_PLPGSQL``:
    unique + 1 columna clave + ``local_id`` + sin predicado parcial.
    El nombre (``uq_*`` canónico o ``ux_*`` legado) no importa.
    UNIQUE compuesto o índice no-UNIQUE no cuentan como identidad.
    """
    for idx in indexes:
        unique = bool(idx.get("unique", idx.get("indisunique", False)))
        if not unique:
            continue
        columns = idx.get("columns") or idx.get("key_columns") or ()
        if isinstance(columns, str):
            columns = (columns,)
        columns = tuple(columns)
        nkey = idx.get("indnkeyatts", idx.get("nkeyatts", len(columns)))
        predicate = idx.get("predicate", idx.get("indpred", None))
        if (
            nkey == 1
            and len(columns) == 1
            and columns[0] == "local_id"
            and not predicate
        ):
            return True
    return False


def postgres_local_id_unique_exists_query() -> str:
    """SELECT EXISTS(...) para una tabla (``%s`` = relname). Misma semántica."""
    pred = _POSTGRES_LOCAL_ID_UNIQUE_EXISTS_PLPGSQL.replace(
        "trel.relname = t", "trel.relname = %s", 1
    )
    return f"SELECT {pred}"


def postgres_identity_sql(tables: Optional[Iterable[str]] = None) -> str:
    """SQL PostgreSQL explícito: backfill de local_id + UNIQUE. Nunca SQLite.

    Crea el índice canónico ``uq_<tabla>_local_id`` solo si no existe ya un
    UNIQUE equivalente sobre ``local_id`` (p.ej. el ``ux_*`` histórico).
    """
    names = tuple(
        tables if tables is not None else tables_requiring_postgres_local_id_unique()
    )
    quoted = ",\n        ".join(f"'{name}'" for name in names)
    return f"""-- FERREPRO Fase 1B — identidad local_id en PostgreSQL.
-- SOLO PostgreSQL/Supabase. Nunca ejecutar contra SQLite.
-- Idempotente: no reasigna local_id existentes.
-- UNIQUE(local_id): nombre canónico uq_<tabla>_local_id.
-- Un UNIQUE equivalente ya existente (cualquier nombre, p.ej. ux_*) se respeta.
-- La lista de tablas DEBE coincidir con sync_registry.tables_requiring_postgres_local_id_unique().

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        {quoted}
    ]
    LOOP
        IF to_regclass('public.' || t) IS NOT NULL
           AND EXISTS (
               SELECT 1 FROM information_schema.columns c
               WHERE c.table_schema = 'public'
                 AND c.table_name = t
                 AND c.column_name = 'local_id'
           ) THEN
            EXECUTE format(
                'UPDATE %I SET local_id = gen_random_uuid()::text
                 WHERE local_id IS NULL OR local_id = %L',
                t, ''
            );
            IF NOT {_POSTGRES_LOCAL_ID_UNIQUE_EXISTS_PLPGSQL} THEN
                EXECUTE format(
                    'CREATE UNIQUE INDEX IF NOT EXISTS %I ON %I(local_id)',
                    'uq_' || t || '_local_id',
                    t
                );
            END IF;
        END IF;
    END LOOP;
END $$;
"""
