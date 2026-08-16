# Regularización operacional de barcodes

## Cola

La vista se deriva de `productos.barcode_status`, `product_barcodes` y staging.
Estados: `BARCODE_PENDING`, `BARCODE_MISSING_LEGACY`, `BARCODE_VERIFIED` y
`BARCODE_CONFLICT`. Filtros: TODOS, PENDIENTES, LEGACY SIN BARCODE, STAGING SIN
BARCODE, VERIFICADOS y CON CONFLICTO. La búsqueda cubre nombre, marca,
categoría y barcode.

Un producto `BARCODE_VERIFIED` no vuelve a `pending_products()` tras reiniciar.
Los candidates Excel son referencia: MATCH informa; una diferencia muestra
WARNING; ninguno se promueve automáticamente a VERIFIED.

## Flujo seguro

```text
scan A -> WAITING_CONFIRMATION
scan A -> persist -> DB read-back -> PERSISTENCE_VERIFIED -> siguiente
scan B -> MISMATCH -> 0 persistencia -> mismo producto
```

El valor permanece TEXT exacto: no hay conversión numérica ni cambio global de
case. Duplicado del mismo producto es idempotente; duplicado de otro producto
es conflicto. Un fallo DB/read-back no avanza el modo continuo.

## Presentaciones y FRP

`BASE_UNIT`, `FULL_PACKAGE` y `CUSTOM_PRESENTATION` son metadata del barcode.
Todos apuntan al mismo producto y stock; no existe conversión automática de
caja ni barcode inventado para medio empaque.

FRP usa `FRP-XXXXXXXXXXXXXXXX` con `secrets.token_hex(8).upper()`. Solo el flujo
Generar → mostrar → confirmar → persistir → read-back puede crearlo. Generación
automática: **0**.
