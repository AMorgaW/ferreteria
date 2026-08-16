# Reconciliación y dry-run

## Matching

- `MATCH_EXACT`: barcode ya existente o identidad fuerte única.
- `MATCH_CANDIDATE`: similitud de nombre; nunca auto-merge.
- `NEW_PRODUCT`: sin coincidencia suficiente.
- `AMBIGUOUS`: múltiples identidades o conflicto barcode/producto.
- `INVALID`: errores de validación.

La prioridad es barcode persistido existente, luego nombre + marca +
presentación + categoría exactos. La similitud textual siempre requiere revisión.

## Autoridad de stock

En `AUTHORITATIVE`, el saldo se lee de `inventory_balances.quantity_scaled`.
Si no está disponible, el dry-run falla cerrado y no usa `productos.stock`.

En `PRE_CUTOVER`, se respeta el contrato legacy y `productos.stock` se convierte
a escala 1000 mediante Decimal.

Caso crítico: stock legacy 100, balance authoritative 80 y conteo 75 produce
delta `-5` (`-5000` scaled), nunca `-25`.

## Plan sin ejecución

`InventoryImportApplyPlan` contiene productos nuevos, saldos iniciales,
metadata, ajustes, candidatos barcode y filas bloqueadas. Un producto existente
genera `PROPOSE_INVENTORY_ADJUSTMENT`, no una compra histórica. Un producto
nuevo genera `PROPOSE_CREATE_PRODUCT` + `PROPOSE_INITIAL_BALANCE`, sin `local_id`.

`dry_run()` realiza SELECTs. No crea productos, balances, movimientos ni
barcodes, y la UI no presenta botón de APPLY.
