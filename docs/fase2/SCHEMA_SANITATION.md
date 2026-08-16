# Matriz de esquema y saneamiento

Fecha de análisis: 2026-08-15. Origen SQLite comercial abierto en solo lectura;
destino PostgreSQL observado exclusivamente en el laboratorio local de Fase 1.

El comando documentado en `README.md` emite la matriz completa de 240 filas con
tabla, columna, tipo SQLite, política PostgreSQL, nullable, default, PK, FK,
unique, estado de sync, riesgo y migración. Esta vista resume las columnas que
requieren una decisión o una garantía específica.

## Volumen observado

| Tabla | Filas | Sync |
|---|---:|---|
| productos | 141 | SYNC; `stock` excluido de autoridad/LWW |
| compras | 21 | SYNC |
| detalle_compras | 29 | SYNC |
| ventas | 73 | SYNC |
| detalle_ventas | 110 | SYNC |
| movimientos | 153 | SYNC |
| movimientos_inventario | 0 | SYNC |
| devoluciones | 0 | NON_SYNC |
| proveedores | 10 | SYNC |
| usuarios | 2 | SYNC |
| configuracion | 0 | SYNC |

## Matriz de drift material

| Tabla | Columna/grupo | SQLite | PostgreSQL lab/política | Null/default/keys | Sync | Riesgo | Migración necesaria |
|---|---|---|---|---|---|---|---|
| productos | `id` | INTEGER PK | integer identity en lab | PK, no-null semántico | SYNC | LOW | conservar ID local; identidad global es `local_id` |
| productos | `local_id` | TEXT UNIQUE | text en lab | nullable histórico | SYNC | HIGH si falta/duplica | validar; no regenerar válidos |
| productos | `stock` | INTEGER default 0 | numeric legacy | nullable, proyección | excluido LWW | MEDIUM | **PROJECTION_ONLY**; autoridad es `inventory_balances` |
| productos | `precio_*` | REAL | NUMERIC futuro | defaults mixtos | SYNC | MEDIUM | CAN_REMAIN_LEGACY; migrar dinero por dominio |
| compras | `id/local_id/remote_id` | INTEGER/TEXT/TEXT | tabla ausente en lab | `local_id` UNIQUE | SYNC | HIGH por drift remoto | catálogo PG 2B; preservar identidad |
| compras | `numero_factura` | TEXT | tabla ausente en lab | nullable, no unique | SYNC | MEDIUM | columnas normalizadas nullable; no backfill automático |
| compras | `subtotal/total/monto_pagado/saldo_pendiente` | REAL | NUMERIC futuro | defaults mixtos | SYNC | MEDIUM | regla monetaria y escala en 2B |
| detalle_compras | `cantidad/precio_*/subtotal` | INTEGER/REAL | tabla ausente en lab | FK compra/producto | SYNC | MEDIUM | cantidades/precios por dominio, no float nuevo |
| ventas | `total/subtotal/descuento/monto_pagado/saldo_pendiente` | REAL | tabla ausente en lab | identidad sync | SYNC | MEDIUM | NUMERIC futuro con redondeo explícito |
| detalle_ventas | `cantidad/precio_unitario/subtotal` | INTEGER/REAL | tabla ausente en lab | FK venta/producto | SYNC | MEDIUM | cantidades/precios por dominio |
| movimientos | `cantidad/stock_anterior/stock_nuevo` | INTEGER | tabla ausente en lab | FK producto y documento | SYNC | HIGH si se usa como autoridad | historial legacy; balances PG mandan ONLINE |
| movimientos | `tipo` | TEXT | tabla ausente en lab | valores ENTRADA_*/SALIDA_* | SYNC | MEDIUM | mapa canónico 2B |
| movimientos_inventario | cantidades/tipo | tipos legacy mixtos | tabla ausente en lab | 0 filas observadas | SYNC | MEDIUM | decidir consolidación; no fusionar aún |
| devoluciones | documento y total | legacy local | tabla ausente en lab | sin `local_id`/sync | NON_SYNC | MEDIUM | definir identidad antes de incorporarla; sin función nueva |
| proveedores | `local_id/remote_id` | TEXT/TEXT | tabla ausente en lab | `local_id` UNIQUE | SYNC | HIGH por drift remoto | preservar UUID local; mapear remote opaco |
| usuarios | `local_id/remote_id` | TEXT/TEXT | tabla ausente en lab | `local_id` UNIQUE | SYNC | HIGH por drift remoto | igual que proveedores |
| configuracion | `clave/local_id` | TEXT PK/TEXT UNIQUE | tabla ausente en lab | 0 filas | SYNC | MEDIUM | respetar PK de negocio `clave` |
| inventory_balances | `quantity_scaled` | no materializado en DB histórica | BIGINT NOT NULL | PK `producto_local_id` | coordinador | LOW | **MUST_MIGRATE/ya fijo x1000** |
| inventory_operations | `delta_scaled` | ledger lazy | BIGINT NOT NULL | IDs texto + line_no | no LWW | LOW | impedir regresión a float |
| inventory_commands | `request_hash/estado` | ledger lazy | text NOT NULL | PK `command_id` | no LWW | LOW | materializar por bootstrap; no sync genérico |
| cutover snapshots | cantidades/checksum/epoch | no aplica | BIGINT/text, líneas aprobadas | claves compuestas | admin | LOW | ya certificado; no migración 2A |

## Identidad

Las tablas sincronizadas inspeccionadas tienen 0 `local_id` nulos/vacíos,
0 UUID inválidos y 0 duplicados. También tienen 0 `remote_id` duplicados por
entidad. Un `remote_id` no se clasifica como UUID inválido: en los datos legacy
es un puntero remoto opaco y puede ser numérico/textual. Reinterpretarlo exige
un mapa humano; nunca se reemplaza silenciosamente un `local_id` válido.

## Numéricos

La inspección por `typeof()` encontró 0 valores TEXT/BLOB en columnas
numéricas. Eso no elimina el drift declarado:

- `inventory_balances.quantity_scaled` y `inventory_operations.delta_scaled`:
  **MUST_MIGRATE / ya fixed-point BIGINT x1000**;
- `productos.stock`: **PROJECTION_ONLY**;
- cantidades y montos INTEGER/REAL legacy: **CAN_REMAIN_LEGACY** en 2A, pero
  toda estructura nueva debe usar fixed-point/NUMERIC y reglas explícitas.

## Compras y factura de proveedor

La clave candidata futura es proveedor + tipo de documento normalizado +
número normalizado. En las 21 compras observadas hay 0 grupos duplicados con
número no vacío y 4 compras sin número normalizable. El schema no tiene un
tipo de documento proveedor independiente. Por eso 2A añade solo columnas
nullable e índice de detección no único. Un backfill y una UNIQUE requieren
clasificación humana previa.

## Movimientos

`movimientos` contiene 153 filas: 12 `ENTRADA_AJUSTE`, 29 `ENTRADA_COMPRA` y
112 `SALIDA_VENTA`. `movimientos_inventario` contiene 0. La coexistencia de
ambos modelos queda como deuda MEDIUM: Fase 2B debe elegir tabla canónica y
mapear tipos, sin reinterpretar estos historiales como autoridad ONLINE.

## Devoluciones

`devoluciones` tiene 0 filas, está declarada `NON_SYNC` y no expone identidad
global. Fase 2A no añade funcionalidad ni la incorpora al sync.

## Hallazgos y acción

| Severidad | Hallazgo | Afectados | Automatizable |
|---|---|---:|---|
| MEDIUM | `inventory_commands/operations` aún no materializado en SQLite histórica | 2 tablas | Sí, bootstrap controlado/fixture |
| MEDIUM | compra sin identidad de factura normalizable | 4 compras | No; clasificar documento |
| MEDIUM | dos modelos de movimientos | 153 filas | No; decisión de modelo y mapa |
| INFO | tablas comerciales ausentes del PostgreSQL de laboratorio | 9 familias | Diseñar catálogo PG 2B; no inferir Supabase real |

No se detectaron violaciones FK, duplicados de identidad, duplicados de factura
normalizada ni anomalías numéricas almacenadas. Estos resultados son una
fotografía reproducible, no autorización para aplicar saneamiento sobre datos
reales.
