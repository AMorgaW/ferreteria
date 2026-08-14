# Base de datos y persistencia

## Propósito

La persistencia de FERREPRO se inicializa en [database.py](../database.py). `DatabaseManager.conectar()` delega en [pg_compat.py](../pg_compat.py): en `DB_MODE=local`, `sqlite` o `server` abre SQLite con WAL, `foreign_keys=ON` y `busy_timeout`; en otros modos usa PostgreSQL/Supabase.

## Modelo de datos

| Área | Tablas comprobadas |
|---|---|
| Seguridad | `usuarios`, `auditoria`, `login_intentos`, `local_sessions` |
| Catálogos | `proveedores`, `productos`, `clientes`, `categorias_config`, `historial_precios` |
| Ventas | `ventas`, `detalle_ventas`, `cuentas_por_cobrar`, `pagos_cuentas`, `abonos_ventas`, `devoluciones`, `devolucion_detalle`, `consecutivos` |
| Compras | `compras`, `detalle_compras`, `abonos_compras`, `resumen_deudas` |
| Inventario/caja | `movimientos`, `movimientos_inventario`, `cierres_caja`, `egresos_caja` |
| Mezclas/alertas | `formulas_mezcla`, `formula_detalle`, `alertas` |
| Local-first | `sync_queue`, `sync_conflicts`, `sync_state` |
| Configuración | `configuracion` |

Relaciones explícitas en el DDL: `productos.proveedor_id → proveedores`; `ventas.cliente_id/usuario_id → clientes/usuarios`; `detalle_ventas → ventas/productos`; `compras → proveedores/usuarios`; `detalle_compras → compras/productos`; `cuentas_por_cobrar → ventas/clientes`; `cierres_caja → usuarios`; `formula_detalle → formulas_mezcla/productos`.

`movimientos` referencia producto, proveedor y usuario. `movimientos_inventario` agrega además cliente. Ambos almacenan trazabilidad de stock con semánticas y llamadores distintos.

## Esquema y migraciones

Fuentes canónicas (no intercambiables):

- **SQLite nuevo:** [database.py](../database.py) `crear_estructura_completa()`. En SQLite emite `INTEGER PRIMARY KEY` (alias de ROWID); en PostgreSQL conserva `SERIAL PRIMARY KEY`.
- **Migraciones SQLite:** [schema_bootstrap.py](../schema_bootstrap.py) — helpers idempotentes (`table_exists`, `column_exists`, `add_column_if_missing`, índices) y reconstrucción de PK si una tabla vieja nació con `SERIAL`. No usa `ADD COLUMN IF NOT EXISTS` ni traga errores críticos.
- **PostgreSQL remoto:** el mismo `crear_estructura_completa()` con `SERIAL`, más [supabase_local_first_migration.sql](../supabase_local_first_migration.sql) ejecutado **solo** contra Postgres en `SupabaseSyncService._ensure_remote_schema`. Identidad `local_id` remota: [supabase_sync_identity.sql](../supabase_sync_identity.sql) (PG only; la lista de tablas debe coincidir con `sync_registry.sync_tables()`).

[version.py](../version.py) declara `SCHEMA_VERSION = 4` como etiqueta en `sync_state`. **No** hay un runner que seleccione migraciones por número; el valor es decorativo hasta que exista uno.

## Archivos involucrados

- [database.py](../database.py): DDL, usuarios bootstrap, configuración y mantenimiento de esquema.
- [schema_bootstrap.py](../schema_bootstrap.py): helpers idempotentes SQLite/PostgreSQL, columnas requeridas y PK INTEGER en SQLite.
- [sync_registry.py](../sync_registry.py): fuente única de tablas sincronizadas, FKs y orden topológico (Fase 1B).
- [pg_compat.py](../pg_compat.py): adaptador SQL SQLite/PostgreSQL y selección de conexión.
- [local_first_db.py](../local_first_db.py): conexión SQLite local, tabla/columnas de sincronización, outbox e identidad UUID.
- [models.py](../models.py): dataclasses usadas por UI, servicios y repositorios.
- [backup_manager.py](../backup_manager.py): copias y restauración de SQLite.

## Puntos sensibles

- No suponga que todos los tipos declarados en dataclasses coinciden exactamente con SQLite: varias cantidades son `INTEGER` en el DDL, pero algunas rutas de UI/API manejan `float`.
- `egresos_caja` tiene una migración correctiva en [local_first_db.py](../local_first_db.py) que elimina una FK histórica hacia una tabla `cajas` inexistente.
- El servicio de sincronización replica las tablas del registry canónico
  [`sync_registry.py`](../sync_registry.py). `SYNC_TABLES` / `SYNCED_TABLES` /
  `FK_MAP` / `TOPO_ORDER` se derivan de ahí; no se editan a mano.
- `pagos_cuentas` existe en el esquema, mientras los flujos visibles de abonos usan principalmente `abonos_ventas`.

## Pruebas relacionadas

[tests/test_local_first_integration.py](../tests/test_local_first_integration.py) verifica esquema local-first, venta por API, stock, movimientos, cola y aislamiento del cliente (todavía copia `ferreteria.db`). El bootstrap SQLite desde cero se cubre en [tests/fase1a/test_bootstrap_sqlite.py](../tests/fase1a/test_bootstrap_sqlite.py). Identidad UUID y registry de sync: [tests/fase1b/](../tests/fase1b/).

## Antes de modificar persistencia

1. Revisar [database.py](../database.py), [local_first_db.py](../local_first_db.py) y [pg_compat.py](../pg_compat.py).
2. Revisar la tabla en consultas de repositorios y servicios, no solo su DDL.
3. Si se replica el dato, leer [Sincronización](sincronizacion.md) y [supabase_local_first_migration.sql](../supabase_local_first_migration.sql).
4. Ejecutar la prueba local-first y verificar una base de desarrollo, nunca la base productiva.
