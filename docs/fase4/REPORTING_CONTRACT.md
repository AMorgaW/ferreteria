# Contrato de reporting — Fase 4A

## Inventario

| Concepto | Fuente |
| --- | --- |
| Cantidad actual | SQLite `inventory_balances.quantity_scaled` si existe; si no, proyección `LEGACY_PROJECTION` |
| Conversión | `scaled_to_decimal` = `Decimal(quantity_scaled) / Decimal(1000)` |
| Stock mínimo / unidad / precio catálogo | `productos` (maestro, no autoridad de cantidad) |
| Valor inventario | cantidad canónica × `precio_compra` actual, `ESTIMATED` |
| Autoridad online | PostgreSQL `inventory_balances` — no se consulta al abrir reportes |
| `productos.stock` | Cache/proyección. Nunca autoridad de reporting |

Dashboard stock crítico y `reporte_inventario_actual` usan `services/inventory_reporting_adapter.py`.

## Ventas

Documentos `COMPLETADA`/`COMPLETED`. `DRAFT`/`REJECTED`/`ANULADA` no cuentan. El documento original no se modifica.

| Métrica | Definición |
| --- | --- |
| Gross sales | `SUM(ventas.total)` del período (fecha local inclusive) |
| Customer returns | `reversal_documents` `CUSTOMER_RETURN` `COMPLETED` |
| Sale voids | `reversal_documents` `SALE_VOID` `COMPLETED` |
| Net sales | Gross − returns − voids |

Fecha: `DATE(datetime(col, 'localtime'))` inclusive en ambos extremos.

## Top productos

Cantidad base almacenada (`detalle_ventas.cantidad` / `reversal_lines.cantidad_base`). Gross / returned / net. No se reimplementa packaging.

## Compras

Documentos `compras` `COMPLETADA`. No se usa `movimientos.tipo = ENTRADA_COMPRA` como fuente única. DRAFT no cuenta. Supplier return (`SUPPLIER_RETURN` COMPLETED) reduce el neto.

## Pagos y crédito

`EFECTIVO` = efectivo físico de caja. `TARJETA_*` y `TRANSFERENCIA` no son cajón. `CREDITO`: facturado / cobrado / pendiente. Venta a crédito no es dinero recibido.

## Caja

`cash_movements` vía `CajaService.obtener_resumen_sesion` / `compute_period_cash_summary`. No se recalcula `DATE('now') + ventas - egresos`.

## Rentabilidad

Si no hay snapshot durable en la línea de venta: `cost_basis = LEGACY_UNVERIFIED`, `profitability_contract = ESTIMATED`. No se presenta como costo histórico exacto.

## Dinero

Decimal. Float solo para rendering gráfico. Excel recibe los mismos Decimal/datasets que la UI.

## Local-first

Abrir un reporte no hace red remota. SQLite es la fuente de lectura.
