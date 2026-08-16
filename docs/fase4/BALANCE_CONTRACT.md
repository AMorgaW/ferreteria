# Contrato de saldo operacional — Fase 4B

No es contabilidad ni doble partida.

## Fórmula canónica

```
NET OBLIGATION = ORIGINAL COMPLETED AMOUNT − APPLICABLE COMMERCIAL REVERSALS
BALANCE        = NET OBLIGATION − VALID APPLIED PAYMENTS
CREDIT         = PAYMENTS − NET OBLIGATION   (si PAYMENTS > NET)
```

`BALANCE` nunca se oculta con `max(..., 0)` silencioso. Un intento de pago mayor al saldo se rechaza con `PAYMENT_EXCEEDS_BALANCE`. El crédito a favor solo aparece cuando un reverso comercial reduce la obligación neta por debajo de lo ya pagado.

## Receivables (cuentas por cobrar)

| Concepto | Fuente |
| --- | --- |
| Original | `ventas.total` de documento `COMPLETADA`/`COMPLETED` con `metodo_pago = CREDITO` |
| Reversals | `reversal_documents` `CUSTOMER_RETURN` / `SALE_VOID` `COMPLETED` (suma de `reversal_lines.subtotal`) |
| Payments | `abonos_ventas.monto_abono` |
| Balance | canónico, Decimal |
| Crédito a favor | `CUSTOMER_CREDIT` si pagos > obligación neta |

El documento original no se reescribe. Una corrección es un nuevo abono o un nuevo reverso.

## Payables (cuentas por pagar)

| Concepto | Fuente |
| --- | --- |
| Original | `compras.total` `COMPLETADA`/`COMPLETED` |
| Supplier returns | `reversal_documents` `SUPPLIER_RETURN` `COMPLETED` |
| Payments | `abonos_compras.monto_abono` |
| Balance | canónico, Decimal |
| Crédito proveedor | `SUPPLIER_CREDIT` si pagos > obligación neta |

Recepción de mercancía ≠ pago financiero.

## Proyección legacy (no autoridad)

`ventas.monto_pagado`, `ventas.estado_pago`, `cuentas_por_cobrar.*`, `compras.monto_pagado`, `compras.saldo_pendiente`, `compras.estado_pago` se actualizan idempotentemente desde el saldo canónico. `pagos_cuentas` no tiene escritor productivo.

`CuentasPorCobrarService` / `DeudasService` leen el modelo canónico. `reconciliar_venta` / `reconciliar_compra` detectan y corrigen proyección desfasada.

## Pagos y exactly-once

Cada abono lleva `local_id` UUID (UNIQUE). Retry con la misma identidad reutiliza la fila; no duplica. No se usa SQLite ROWID como identidad distribuida.

La secuencia read-validate-insert-project corre bajo `BEGIN IMMEDIATE`.

## Overpayment

Pago > saldo pendiente → rechazo `PAYMENT_EXCEEDS_BALANCE`. No se crea un concepto contable nuevo de anticipo.

## Returns / voids

Un return/void 3C reduce la obligación neta. No inventa efectivo. Si ya se pagó de más, se expone `CUSTOMER_CREDIT` / `SUPPLIER_CREDIT`. El reembolso de caja solo ocurre si 3D registra un refund method explícito.

## Caja

Abono cliente efectivo → un `cash_movements` `DRAWER_IN`. Pago proveedor efectivo → un `DRAWER_OUT`. Tarjeta/transferencia → `INFORMATIONAL`, drawer 0. Autoridad: `CajaService` / `cash_movements`. `egresos_caja` de pago a proveedor es proyección legacy y no entra en la fórmula de caja.

Lost cash effect: recovery exactly-once de 3D (`recover_session_movements`). 4B no añade otro mecanismo.

## Decimal

Frontera `money()` (2 decimales, `ROUND_HALF_UP`). No float como autoridad. Columnas REAL legacy no se migran; se normalizan al leer.

## Local-first

`connect_local()` abre SQLite (`DB_MODE=local|sqlite|server` → `pg_compat.LOCAL_DB_PATH` o `db_path` de test). No abre PostgreSQL remoto. `pg_compat.connect()` en modo local también es SQLite; los servicios 4B no dependen de red.

## Concurrencia

Estación única: `BEGIN IMMEDIATE` serializa dos pagos finales. Cross-station (W01/W02 con SQLite distintos): no hay coordinador financiero distribuido en 4B. Limitación de deployment; no se inventó autoridad remota.

## Aging

Buckets: 0–30, 31–60, 61–90, 90+. Alias visibles `deuda_30` / `deuda_60` / `deuda_90` (esta última agrupa 61+). Usa saldo **neto** pendiente. Factura con saldo 0 no envejece.
