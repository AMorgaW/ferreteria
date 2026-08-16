# Fase 3C — Devoluciones + anulaciones + reversos controlados

**Veredicto:** GO. Inventario comercial: diferido.

## Alcance cerrado

Venta o recepción COMPLETED → seleccionar cantidades → confirmación humana → documento inverso durable (`reversal_documents`) → inventory gateway/coordinator (`tipo=DEVOLUCION`) → inventario +/- una vez.

El documento original no se edita. No hay DELETE de venta/detalle ni `UPDATE productos.stock` como autoridad.

## Operaciones

| Kind | Original | Signo inventario | `documento_tipo` |
| --- | --- | --- | --- |
| `CUSTOMER_RETURN` | venta | + | `customer_return` |
| `SALE_VOID` | venta (neto pendiente) | + | `sale_void` |
| `SUPPLIER_RETURN` | recepción | − | `supplier_return` |

Estados del reverso: `DRAFT` / `APPLYING` / `COMPLETED` / `REJECTED`. Solo CONFIRMAR aplica inventario.

Estado informativo derivado del original: `PARTIALLY_RETURNED` / `FULLY_RETURNED` / `VOIDED`. El `estado` histórico `COMPLETADA` no se destruye.

## No incluido

3D, caja, facturación fiscal, notas crédito fiscales, OCR, PDF/XML, inventario comercial, nueva autoridad offline.

## Inventario comercial

Diferido. Tests: SQLite temporal + fixtures + `ferrepro-pg-test`.
