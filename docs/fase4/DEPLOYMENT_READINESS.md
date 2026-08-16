# Deployment readiness — Fase 4D

Release software. No es cutover comercial.

## Financial writer fence (operacional)

No es serialización distribuida. No hay coordinador financiero entre estaciones.

Una estación explícita puede finalizar:

- abonos de cliente
- pagos a proveedor

Las otras pueden consultar CxC/CxP y saldos. No pueden persistir el pago.

| Clave | Fuente |
| --- | --- |
| Writer | `financial_writer_station_id` en `local_first_config.json` o `FINANCIAL_WRITER_STATION_ID` |
| Estación actual | `FERREPRO_STATION_ID` o `device_id` (`resolve_station_id`) |
| Estaciones previstas | `expected_station_ids` / `FERREPRO_EXPECTED_STATION_IDS` |
| Perfil | `deployment_profile` / `FERREPRO_DEPLOYMENT_PROFILE` |

`current == writer` → ALLOW. Distinto → `FINANCIAL_WRITER_FENCE`.

El gate está en el repositorio/servicio, no solo en la UI.

## Preflight

```
python services/deployment_readiness.py --production
```

Salida: `READY` o `NOT_READY` + blockers.

READY cuando, en producción:

- SQLite abre y es escribible
- migraciones aplicadas (sin PENDING / CHECKSUM_MISMATCH)
- `station_id` válido (no `LOCAL`)
- writer financiero designado
- writer ∈ expected_station_ids si esa lista no está vacía
- `supabase_inventory_coordinator.sql` resoluble
- directorio `backups/` usable
- `db_mode` local-first
- config disponible

NOT_READY (ejemplos exactos):

- `FINANCIAL_WRITER_FENCE_REQUIRED` — producción o flota >1 sin writer
- `STATION_ID_INVALID`
- `SQLITE_NOT_WRITABLE`
- `SQLITE_NOT_FOUND`
- `SCHEMA_MIGRATIONS_PENDING`
- `COORDINATOR_SQL_MISSING`
- `BACKUP_DIR_UNUSABLE`
- `REMOTE_DB_MODE_NOT_LOCAL_FIRST`

Fail-closed: más de una estación prevista y writer vacío → no READY.

El preflight **no** marca `REAL_INVENTORY_APPLIED`.

INVENTARIO COMERCIAL REAL: PENDING FINAL DEPLOYMENT.

CAJA COMERCIAL REAL: NOT EXECUTED.

Supabase no es requisito de startup.

## Backup

API `sqlite3.backup`. Manifest sidecar (`backup_YYYY_MM_DD_HH_MM.manifest.json`):

- `created_at`
- `station_id` / `device_id`
- `schema_version`
- `sha256`
- `sqlite_backup_api: true`

Offline. Sin cloud.

## Restore

Nunca automático al arrancar.

Antes de reemplazar la DB destino:

1. validar header SQLite + `integrity_check`
2. validar manifest obligatorio + SHA-256
3. safety backup del destino (si esto falla, aborta)
4. restaurar con backup API

Si el restore falla después de comenzar, se recupera automáticamente desde el
safety backup. Si esa recuperación también falla, el resultado declara estado
`INCIERTO` y conserva la ruta exacta del safety backup; nunca reporta éxito.

Tests solo en `tmp_path`. No restaurar `ferreteria.db` comercial.

Un restore válido conserva ventas, compras, reversos, cash sessions/movements, abonos, proyección/balances locales y outbox.

## Frozen resources

PyInstaller onedir. Recurso coordinador obligatorio. Path ausente → `CoordinatorError`. No usar `C:\Users\alex\...` en runtime frozen.

## Inventario real (diferido)

XLSX → VALIDATE → STAGING → MATCHING → REVIEW → DRY-RUN → APPROVE → PRE-FLIGHT → APPLY → VERIFY → COMPLETED.

4D no ejecuta ese flujo.
