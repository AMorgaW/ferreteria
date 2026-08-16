# Fase 3B — Compras + recepción de mercancía + proveedores

**Veredicto:** GO. Inventario comercial: diferido.

## Alcance cerrado

Proveedor existente → documento/borrador local → líneas con presentación canónica → costo documental → confirmación humana **CONFIRMAR RECEPCIÓN** → inventory gateway/coordinator (delta positivo `COMPRA`) → documento `COMPLETADA` durable.

El stock cambia al **recibir**, no al crear el DRAFT.

## No incluido

3C, cuentas por pagar completas, facturación electrónica, devoluciones complejas a proveedor, OCR, XML/PDF, inventario comercial, nueva autoridad offline, reportes nuevos.

## Limitación de costo maestro

El costo de cada línea se persiste en `detalle_compras`. 3B **no** sobrescribe `precio_venta`. El camino legado `ComprasRepository.crear_compra` (W01, cutover OFF) sigue actualizando `precio_compra`; el camino 3B de confirmación no lo hace. No hay política inequívoca de actualización de costo maestro.

## Aliases de proveedor

`supplier_product_aliases` es identidad/SKU del proveedor. No se escribe en `product_barcodes`. Un alias no es barcode físico escaneable salvo que exista también como barcode del producto.

## Inventario comercial

Diferido. Tests: SQLite temporal + fixtures + `ferrepro-pg-test`.
