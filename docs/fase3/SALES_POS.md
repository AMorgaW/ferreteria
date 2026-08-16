# Contrato POS / ventas (Fase 3A)

## Scanner

DIG-X6266 = USB HID keyboard wedge. ENTER confirma el código.  
`normalize_barcode` conserva ceros iniciales, mayúsculas y texto exacto. No hay `int(barcode)`.

Scan → `product_barcodes` (PRIMARY o secundario) → mismo `inventory_balance` del SKU. El scan **no** registra venta.

## Carrito

Local-first. Agregar por scan o búsqueda/tarjeta. Scan repetido del mismo SKU + misma presentación incrementa la línea. Presentaciones distintas no se fusionan. Quitar línea y cambiar cantidad están soportados.

## Cantidades y precio

Cantidad > 0. Decimales solo si `permite_decimales`. Totales del carrito en `Decimal`. COP existente; no hay moneda nueva.

## Confirmación

`AUTORIZAR VENTA` es la única vía de commit. ENTER del scanner no vende. Mientras el checkout está en vuelo el botón queda deshabilitado; un segundo evento no abre otra venta. `registrar_venta` corre fuera del hilo GUI.

## Inventory authority

ONLINE: `inventory_balances` PostgreSQL. `productos.stock` es cache/proyección. La venta autoritativa no hace `UPDATE productos SET stock` como autoridad. Reutiliza gateway, coordinator, `command_id` y `ACT_KIND_POS_CHECKOUT`.

Una venta COMPLETED = un efecto de inventario, atómico e idempotente. Stock insuficiente o fallo de línea B: 0 venta, 0 descuento parcial, 0 detalle huérfano.

## Offline

Abrir POS, buscar y armar carrito: sí.  
Confirmar con autoridad central ausente (estación OFFLINE + modo AUTHORITATIVE, sin factory/gateway): FINALIZAR bloqueado. No hay stock autoritativo offline multi-estación.

## Recovery

Identidad durable en SQLite antes del RPC. UNKNOWN/retry reanuda el mismo `command_id`. Si el documento local ya está ligado, no se inserta una segunda venta.

## Concurrencia

Última unidad entre dos estaciones: 1 SUCCESS + 1 REJECT. Laboratorio: `ferrepro-pg-test` / `localhost:55432`.

## Comprobante

Mínimo no fiscal: `sale_id`, fecha, líneas, cantidad, precio, subtotal, total. Reutiliza `ui/imprimir_factura.py`. Sin facturación fiscal.

## Inventario comercial

Diferido hasta la puesta en producción. Tests: SQLite temporal + fixtures + ferrepro-pg-test.
