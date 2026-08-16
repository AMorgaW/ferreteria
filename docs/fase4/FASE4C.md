# Fase 4C — Documentos / impresión / exportación operacional

**Veredicto de implementación:** GO si la suite `tests/fase4c` y la regresión 3A–4B pasan.

## Alcance cerrado

Comprobantes operacionales read-only para documentos COMPLETED/CLOSED:

- venta (ticket)
- recepción/compra
- devolución cliente / anulación
- devolución a proveedor
- cierre/arqueo de caja
- abono cliente / pago proveedor (capa pequeña sobre el mismo renderer)

No es factura fiscal, electrónica ni DIAN. No hay motor PDF nuevo: se reutiliza PySide6 58mm ya existente.

## Arquitectura

`services/document_service.py` carga por identidad durable, arma un `OperationalDocument` inmutable y formatea texto.

La UI (`ui/imprimir_factura.py`) solo hace preview / imprimir / guardar PDF.

Render **no** escribe inventario, caja, pagos, ventas, compras ni sync.

## Identidad

Preferencia: `local_id` UUID, luego `numero_factura` / `inventory_command_id`. SQLite ROWID es respaldo.

Reversos muestran documento reverso y documento original.

## Reprint histórico

Líneas usan cantidad / precio / subtotal persistidos en el documento. No se usa `precio_venta` ni `precio_compra` actuales, ni `productos.stock`.

El nombre de producto se toma del catálogo actual porque no hay snapshot durable de nombre: limitación documentada, no se inventa.

Crédito: se muestra método CREDITO y total facturado. `monto_pagado` es proyección 4B, no se presenta como pagado inicial.

Cierre de caja: `monto_inicial`, `monto_esperado`, `monto_real`, `diferencia` y fechas del snapshot CLOSED. Cash IN/OUT salen del ledger `cash_movements` de **esa** sesión, no de ventas de otro día.

## Dinero

`services.caja_service.money` (Decimal, 2 decimales) antes de formatear `$100.10`.

## Local-first

Preview / reprint / PDF leen SQLite local. Sin red síncrona.

## Impresión / PDF

Preview, selector de impresora, PDF 58mm. Sin impresora o cancelar diálogo: 0 efectos comerciales. Reimprimir es seguro. No hay auto-print al confirmar la operación.

Nombres: `VENTA_<id>.pdf`, `RECEPCION_<id>.pdf`, `DEVOLUCION_<id>.pdf`, `CIERRE_CAJA_<id>.pdf`. La UI pregunta la ruta.

## XLSX

4A (`exportar.py`) no se rehízo. 4C no crea XLSX por cada comprobante.

## Permisos / auditoría

Reimpresión reutiliza roles actuales. El usuario que reimprime no sustituye al autor original.

No hay bitácora de reimpresión: limitación, no se crea infraestructura.

## Limitaciones

1. Nombre de producto en líneas históricas usa el catálogo actual (no hay snapshot de nombre).
2. Pagado/pendiente inicial de crédito no se reconstruye: `monto_pagado` es proyección.
3. No hay auditoría durable de “quién reimprimió”.
4. `PHASE4D_DEPLOYMENT_FENCE_REQUIRED` queda para 4D. 4C no implementa el fence.
