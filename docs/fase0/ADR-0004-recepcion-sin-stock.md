# ADR-0004 — Recepción documental no toca stock

- **Estado:** aceptado (diseño). No implementado.
- **Fase de código:** posterior a Fase 0.

## Decisión

La recepción es un **borrador** (`recepcion_documentos` /
`recepcion_lineas`) independiente de `compras`. Analizar XML/PDF/foto
escribe borrador + `extraction_payload`. Cero `UPDATE productos`.

Confirmación humana (admin / gerente / bodeguero):

- resuelve producto (match o alta con barcode, nunca SKU inventado por OCR)
- cantidades: documento, recibida, dañada, faltante, aceptada, …
- invariantes de cantidad (servidor, no UI):

```text
todas ≥ 0
recibida + faltante = cantidad_documento   (salvo líneas no inventariables)
aceptada + dañada = recibida
solo aceptada genera delta de inventario
```

Producto nuevo: stock 0 al nacer; el ingreso es la recepción confirmada.
`ENTRADA_COMPRA` en Movimientos y Entrada inventario desaparece.
OCR/IA fuera de la TX. PDF/XML no viajan por `sync_queue`.

Factura: `numero_original` + `numero_normalizado`. UNIQUE por
`(proveedor_id, numero_normalizado)` en documentos no anulados y en
compras no canceladas (decisión de reingreso tras CANCELADA: pendiente
de GO de negocio; el índice parcial lo permite).

Líneas FLETE / DESCUENTO / SERVICIO / REDONDEO / IMPUESTO / OTRO no
mueven stock.

Cancelación de compra ya confirmada: fuera de v1.

## Relación con el ledger

`confirmar(local_id)` no hace `stock = stock + aceptada` en SQLite como
autoridad. Crea `InventoryOperation` (una por línea inventariable, o
una por documento con deltas hijos — detalle de implementación posterior)
con `operation_id` estable derivado del `local_id` de línea + tipo.
Retry del confirmar es idempotente.
