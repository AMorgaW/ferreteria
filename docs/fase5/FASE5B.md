# Fase 5B — Migration lifecycle & schema consistency

**Veredicto de implementación:** GO si `tests/fase5` y la regresión 3C–4D / 2D–2E pasan.

5B no resuelve F5-M1 (`local_server` writer legacy), no resuelve F5-L1 (auth rehash logging), no es Fase 6, no toca `ferreteria.db` comercial y no abre inventario/caja/abonos reales.

## Hallazgos cerrados

**F5-H1.** El catálogo versionado (`migration_runner.DEFAULT_MIGRATIONS`, 001→010) existía, pero el lifecycle normal de una estación SQLite no lo ejecutaba. `MigrationRunner.run` conserva `dry_run=True` por defecto. El bootstrap histórico creaba tablas core + `schema_bootstrap` y, desde 5A, materializaba solo el schema operacional de Caja.

Consecuencia: `schema_migrations`, staging 2D/2E, reversos 3C y el baseline 4B `operational_balance_legacy_payments` podían faltar en una SQLite de trabajo. El preflight 4D reportaba `SCHEMA_MIGRATIONS_PENDING`.

**F5-H2.** Sin la migración `20260816_010`, `operational_balance` no congelaba pagos legacy demostrados solo por `monto_pagado`. Mismo origen: el catálogo no corría.

## Lifecycle

Entrypoint: `schema_lifecycle.ensure_sqlite_schema_current`.

```
resolve local SQLite file
        ↓
inspect catalog (PENDING / APPLIED / CHECKSUM_MISMATCH)
        ↓
already latest → no backup, no DDL
        ↓
pending → backup WAL-safe (sqlite3.backup + manifest SHA-256)
        ↓
backup PASS → MigrationRunner.run(conn, dry_run=False)
        ↓
verify latest → fail closed if not
```

- No crea el archivo si falta (`SQLITE_NOT_FOUND`). Eso no es “instalación nueva”.
- Instalación nueva explícita: `DatabaseManager.crear_estructura_completa` + `ensure_local_first_schema`, después el lifecycle.
- Archivo existente que no es SQLite: `SQLITE_NOT_SQLITE`.
- Backup fallido: `BACKUP_FAILED`; **no se migró**.
- Migración fallida: `MIGRATION_FAILED` (causa: `MigrationError`). No hay auto-restore en startup. El backup `pre-migration` queda en `backups/`.
- Rerunnable: segunda pasada es no-op (`already_latest`).
- Offline: trabajo local, sin red ni Supabase.

`dry_run=True` sigue siendo el default de `MigrationRunner.run` para diagnóstico. La ruta productiva lo invoca **explícitamente** con `dry_run=False`.

## Backup-before-migrate

Reutiliza `backup_manager.crear_backup_result` (Fase 4D): API `sqlite3.backup`, WAL-safe, manifest, SHA-256. Motivo: `pre-migration`. No backup cloud. No restore automático.

Atomicidad del runner: savepoint + commit por migración. Un fallo a mitad deja aplicadas las anteriores y rollback de la fallida. Re-ejecutar el lifecycle reintenta solo las `PENDING`. Estado parcialmente migrado es visible, no silencioso.

## Startup

`DatabaseManager.__init__` (solo SQLite):

1. `crear_estructura_completa` (tablas core + `schema_bootstrap`; guarda 5A `ensure_sqlite_cash_operational_schema` como compatibility)
2. usuarios default
3. `ensure_local_first_schema` (`productos.local_id` y sync)
4. `ensure_sqlite_schema_current`

PostgreSQL remoto no usa este catálogo.

Fresh DB: el bootstrap crea el archivo y el lifecycle llega a latest.

Legacy DB: `CREATE IF NOT EXISTS` no destruye datos; el lifecycle detecta pendientes, respalda y aplica 001–010.

Restart: latest → no backup, 0 duplicados.

## Relación con 5A

`services/caja_service._ensure_cash_schema` permanece como **compatibility guard**. No es un segundo catálogo. El DDL canónico de Caja es la migración `20260816_009`. El guard evita que Caja explote en un path que no pasó por `DatabaseManager`.

## Migración 010

Contrato 4B intacto. `CUTOVER_MONTO_PAGADO` solo si `monto_pagado > 0` y no existe fila de abono durable. `INSERT OR IGNORE`. No duplica. No sintetiza la diferencia si hay abonos y la proyección legacy es mayor.

| Caso | Resultado |
| --- | --- |
| total 100 / pagado 30 / sin abonos | baseline 30, saldo 70 |
| total 100 / pagado 100 / sin abonos | baseline 100, saldo 0 |
| total 100 / pagado 30 / abono 30 | sin baseline extra, saldo 70 |
| total 100 / pagado 50 / abono 30 | no sintetiza 20; pagos canónicos = 30 |
| rerun | exactamente una baseline |

Después del cutover la autoridad es `operational_balance`.

## Schema latest (mínimo verificado)

`schema_migrations`, `inventory_import_batches/rows`, `reversal_documents/lines`, `cierres_caja.station_id`, `cash_movements`, `operational_balance_legacy_payments`, `abonos_ventas/compras` (+ `local_id`).

Vienen del catálogo oficial. No se crean a mano para pasar tests.

Tras latest: `InventoryImportRepository._require_schema` PASS; 3C no falla por tabla ausente; Caja ADMIN/EMPLEADO de 5A PASS; `deployment_readiness` ya no reporta `SCHEMA_MIGRATIONS_PENDING` por schema (puede seguir `FINANCIAL_WRITER_FENCE_REQUIRED` si no hay writer).

## Seguridad de esta ejecución

`ferreteria.db` comercial: **no mutada**. Tests en temp dirs / fixtures. No inventario real, no APPLY comercial, no caja comercial, no abonos reales, no Supabase destructivo.

## No hecho en 5B

- F5-M1 local_server legacy writer
- F5-L1 auth rehash logging
- `FASE5_FINAL.md`
- Fase 6 / deployment comercial / autoridad financiera distribuida
