# Contrato de Inventory Apply

## Plan aprobado

`InventoryImportApplyService.approve_batch` solo acepta un batch sin errores,
matches pendientes, duplicados sin resolver, warnings sin confirmar ni cambios
de metadata pendientes. Persiste:

- `approval_id`, `apply_id`, revisión y hash del origen;
- JSON completo e inmutable del plan;
- producto resuelto o `local_id` reservado para alta nueva;
- base autoritativa, conteo físico y delta;
- `inventory_command_id` y `inventory_operation_id` durables;
- metadata before/after y decisión humana.

Aprobar no crea productos, no envía RPC y no persiste barcodes.

## Pre-flight y CAS

Antes de obtener el lease se relee cada balance existente. Si la base aprobada
ya no coincide, la fila queda `STALE_BALANCE`, se presenta el delta recalculado
y el batch vuelve a review. El plan nuevo debe aprobarse otra vez.

El mismo expected base viaja además en la operación del gateway. PostgreSQL
vuelve a validar CAS dentro del coordinador central, cubriendo dos estaciones
que compiten después del pre-flight.

## Saga por fila

Estados relevantes:

`APPROVED → PRODUCT_CREATING → PRODUCT_CREATED → METADATA_APPLYING → METADATA_APPLIED → INVENTORY_SUBMITTING → INVENTORY_APPLIED → VERIFYING → VERIFIED`

También existen `INVENTORY_UNKNOWN`, `STALE_BALANCE`, `FAILED_RETRYABLE` y
`FAILED_BLOCKING`. Una fila sin delta termina `NO_CHANGE_VERIFIED` sin crear un
comando vacío.

No hay transacción distribuida SQLite/PostgreSQL. El contrato es una saga
recuperable: no borra productos como compensación y nunca crea una identidad
nueva al reintentar.

## Producto nuevo

El mapeo conserva nombre, categoría, marca, precios, stock mínimo, unidad base,
presentación, cantidad por empaque, decimales y formas de venta. Los campos
existentes `usar_unidades_categoria`, `unidades_venta_custom` y
`unidad_base_producto` se escriben por el repositorio canónico.

El conteo físico no se copia a `productos.stock`: se envía como
`AJUSTE/INITIAL_INVENTORY` con base esperada cero.

El engine no envía ese comando mientras el alta local-first siga
`sync_status=pending`. Deja `PRODUCT_SYNC_PENDING` sin consumir la identidad
remota y reanuda con el mismo `command_id` una vez que el producto esté
confirmado en la autoridad central. Así se evita convertir `UNKNOWN_PRODUCT`
en un rechazo durable imposible de reutilizar.

## Lease

`BEGIN IMMEDIATE` y CAS sobre `inventory_import_apply_batches` entregan un solo
lease local por batch. Otro worker recibe `ALREADY_APPLYING / CONFLICT`. Esta
primitive coordina procesos que comparten el mismo staging SQLite; entre
estaciones independientes la coordinación de cantidades corresponde al CAS de
PostgreSQL.
