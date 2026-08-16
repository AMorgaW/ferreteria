# Fase 2A — inventario y saneamiento preparatorio

**Resultado:** COMPLETADA.

## Gate de entrada

El gate heredado cerró con **0 BLOCKER** y **0 HIGH**:

- snapshot de flota: estaciones esperadas explícitas, atestaciones completas y
  convergentes, aprobación persistida en PostgreSQL;
- identidad CAS: `expected_base_scaled` pertenece al hash canónico;
- seed: consume por `cutover_id/epoch` las líneas aprobadas en PostgreSQL, no un
  payload mutable del caller.

Certificación: PostgreSQL 16 local `ferrepro-pg-test`, base `ferrepro_test`.
Gate 1E.4B–1E.4D: 53 PASS. Regresión completa de cierre Fase 0–1E.4D:
436 PASS, 13 expectedFailure, 0 FAIL/ERROR/SKIP/XPASS. El cutover productivo no
fue ejecutado.

## Análisis realizado

`ferreteria.db` se abrió con URI SQLite `mode=ro`. Se analizaron 240 celdas de
esquema y los datos de once tablas focales. No se alteró el archivo.

| Área | Resultado | Clasificación 2A |
|---|---|---|
| Identidad `local_id` | 0 NULL/vacíos, 0 UUID inválidos, 0 duplicados | Verde |
| `remote_id` | 0 duplicados; varios valores no UUID son IDs legacy opacos | Decisión semántica 2B |
| Integridad FK | 0 violaciones | Verde |
| Almacenamiento numérico | 0 valores TEXT/BLOB en columnas numéricas inspeccionadas | Verde con deuda de tipos |
| Factura proveedor | 0 grupos duplicados normalizados; 4 compras sin número normalizable | Decisión humana |
| Movimientos | 153 filas en `movimientos`, 0 en `movimientos_inventario` | Modelo canónico pendiente |
| Devoluciones | 0 filas; tabla local `NON_SYNC`, sin identidad global | Mantener sin nueva función |
| Ledger local | `inventory_commands/operations` no materializado en esta base histórica | Bootstrap controlado pendiente |

## Infraestructura de migración

Se introdujo un runner mínimo reutilizando `schema_bootstrap`:

- versión, nombre y SHA-256 de la firma;
- registro `schema_migrations` solo después de aplicar;
- una migración por savepoint; fallo revierte la migración fallida y se propaga;
- reejecución devuelve `SKIPPED_APPLIED`;
- cambio de checksum en una versión aplicada aborta;
- dry-run no crea siquiera la tabla de control;
- alcance 2A explícitamente SQLite; PostgreSQL requiere catálogo separado.
- si falta el bootstrap base (`compras`) aborta y no registra un no-op como
  migración aplicada.

Migraciones seguras preparadas y aplicadas únicamente a fixtures:

1. `20260815_001`: añade a `compras` dos columnas TEXT nullable,
   `documento_tipo_normalizado` y `numero_factura_normalizada`, sin backfill.
2. `20260815_002`: índice **no UNIQUE** para detección por proveedor/tipo/número.

No se ejecutaron sobre `ferreteria.db`.

## Validación

- `tests/fase2`: 13 PASS, 0 FAIL/ERROR/SKIP.
- regresión total Fase 0–2A: 449 PASS, 13 expectedFailure,
  0 FAIL/ERROR/SKIP/XPASS.
- PostgreSQL crítico: 0 SKIP.
- dry-run comercial: tamaño, timestamp y SHA-256 idénticos antes/después.

## Decisiones reservadas para Fase 2B

1. Definir semántica y mapeo de `remote_id`; no convertirlo a UUID por
   suposición ni regenerar `local_id` válidos.
2. Clasificar las cuatro compras sin número y definir catálogo de tipo de
   documento antes de backfill.
3. Resolver cualquier duplicado que aparezca en el universo productivo antes
   de evaluar una restricción UNIQUE.
4. Elegir modelo canónico entre `movimientos` y `movimientos_inventario` y
   documentar el mapa ENTRADA/SALIDA/AJUSTE.
5. Diseñar catálogo PostgreSQL versionado para tablas comerciales; el esquema
   de laboratorio actual certifica inventario, no paridad comercial completa.
6. Migrar dinero/cantidades legacy por dominio y con reglas de redondeo
   explícitas, sin conversión masiva.

Fase 2B no se implementa en esta microfase.
