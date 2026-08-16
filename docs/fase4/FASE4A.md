# Fase 4A — Reportes y analítica confiable

**Veredicto:** GO. Inventario comercial real: no ejecutado. Caja comercial real: no operada.

## Alcance cerrado

Reporting local-first sobre SQLite. Misma fuente de cantidad para dashboard de stock crítico y reporte de inventario. Ventas y compras en gross / returns / net. Métodos de pago y crédito separados de efectivo físico. Caja vía `CajaService` / `cash_movements`. Rentabilidad marcada ESTIMATED cuando no hay snapshot de costo. Dinero en Decimal. XLSX consume los mismos datasets.

## No incluido

4B, 4C, 4D, facturación electrónica, DIAN, contabilidad, OCR, inventario comercial real, deployment, sync cloud nuevo.

## Inventario

Cantidad actual: SQLite `inventory_balances.quantity_scaled` (SCALE=1000) cuando la tabla local existe. `productos.stock` no es autoridad. Sin consulta remota por producto.

## Limitación de rentabilidad

`detalle_ventas` no guarda costo histórico. El costo de ventas usa `productos.precio_compra` actual y se etiqueta `LEGACY_UNVERIFIED` / `ESTIMATED`.
