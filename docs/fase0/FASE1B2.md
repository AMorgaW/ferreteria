# Fase 1B.2 — Hardening final de identidad remota

**Estado:** implementada. **Prohibido avanzar a Fase 1C** sin GO humano.
Este documento no autoriza implementar 1C.

## Qué es Fase 1B.2

Cierra residuos de 1B.1 en identidad remota y compatibilidad PostgreSQL.
No introduce ledger, coordinador, barcodes ni recepción.

1. El flag `_remote_identity_ensured` solo pasa a True cuando backfill,
   dedupe, UNIQUE(local_id) y la verificación posterior terminaron bien.
2. `supabase_local_first_migration.sql` usa el mismo predicado `pg_index`
   que `postgres_identity_sql()`: un UNIQUE equivalente (cualquier nombre,
   incluido `ux_*` legado) impide crear un `uq_*` redundante. No hay DROP
   para renombrar.
3. `pg_compat.PgCursor` añade `RETURNING id` solo si la PK declarada en el
   registry es `id`. `configuracion` no recibe `RETURNING id`.

No hecho (Fase 1C+):

- `APPLY_AUTHORITATIVE_EXCLUDE` sigue `False`
- InventoryOperation / coordinador / RPC / `operation_id`
- barcodes, recepción, autoridad offline, fixed-point
- INV-02 (stale stock) sigue xfail

## Política abort / reintento / degradar

Contrato de `_ensure_remote_local_id_identity` y su llamada en `_remote_connect`.
No se usa `except: pass` ni `except Exception: pass` en ese contrato.

| Clase | Qué ocurre | Flag | Excepción |
|---|---|---|---|
| **Abortar** | Fallo de backfill, dedupe, UNIQUE, verificación posterior, SQL canónica o `SchemaBootstrapError`. Conexión rota / `SUPABASE_URI` ausente. | permanece `False` | se conserva en `_remote_identity_last_error` y se relanza |
| **Reintentable** | Cualquier fallo de la fila anterior | `False` | la siguiente llamada a `_ensure_remote_local_id_identity` vuelve a intentar |
| **Degradar sin fingir éxito** | `_remote_connect` puede devolver la conexión para no bloquear sync de negocio | `False` | se conserva; **no** `except pass` |

Tras éxito: cada tabla presente con columna `local_id` tiene UNIQUE de una
sola columna sobre `local_id` (`uq_*` canónico o `ux_*` legado). Entonces
flag=`True` y `_remote_identity_last_error=None`.

Idempotencia: dos llamadas exitosas no recrean índices ni cambian estado.

## Legacy `ux_*` vs canónico `uq_*`

Ambos nombres son la **misma** identidad UNIQUE(local_id) de una columna,
sin predicado. El runtime y la migración manual comprueban `pg_index`
(`indisunique`, `indpred IS NULL`, `indnkeyatts = 1`, `attname = 'local_id'`)
antes de `CREATE UNIQUE INDEX uq_*`. Un índice no-UNIQUE o un UNIQUE
compuesto (`local_id` + otra columna) no cuentan. No se DROP-renombra.

El predicado plpgsql vive en `sync_registry._POSTGRES_LOCAL_ID_UNIQUE_EXISTS_PLPGSQL`.
`supabase_local_first_migration.sql` lo reutiliza; no se genera el archivo
entero desde Python (también crea columnas, `historial_precios` e índices
de rendimiento). Helper testeable: `equivalent_local_id_unique_exists`.

## Auditoría pg_compat (`RETURNING id`)

Callers de `pg_compat.connect()`: `DatabaseManager.conectar()`, repositorios
(`abonos_*`, `egresos_caja`), servicios (deudas, CxC, ventas, mezclas,
alertas). En `DB_MODE=remote` el INSERT plano llega a `PgCursor`.

Tablas que **sí** alcanzan ese camino:

- Sync con PK `id` (`usuarios`, `productos`, `ventas`, …): `RETURNING id`;
  `lastrowid` igual que antes.
- Sync con PK no-id: `configuracion` (`clave`). El INSERT de
  `guardar_configuracion` (con `ON CONFLICT`) **no** recibe `RETURNING id`.
- No-sync con PK `id` del DDL (`formulas_mezcla`, `devoluciones`, `alertas`,
  …): `RETURNING id` para no romper `lastrowid` en remoto. PK declarada en
  `NON_SYNC_INSERT_PK`, no inventada.
- No-sync con PK TEXT: `consecutivos` (`clave`), `login_intentos`
  (`username`), `local_sessions` (`token`), `sync_state` (`clave`): no
  `RETURNING id`.
- Tabla sin metadata o nombre irresoluble: `PgCompatError`. No se asume `id`
  (`pk_column()` histórico defaulta a `id`; `declared_insert_pk()` no).

Fase 1C **no** depende de `RETURNING id` ciego: el UPSERT de sync ya usa
`remote_upsert_returning_column` / PK declarada (`local_sync.build_remote_upsert_sql`
no se tocó en 1B.2).

## Tests

```text
python -m unittest discover -s tests/fase0 -v
python -m unittest discover -s tests/fase1a -v
python -m unittest discover -s tests/fase1b -v
python -m unittest discover -s tests/fase1b1 -v
python -m unittest discover -s tests/fase1b2 -v
```

Los xfail de arquitectura de Fase 0 deben seguir expected-fail.
**STOP — no avanzar a Fase 1C.**
