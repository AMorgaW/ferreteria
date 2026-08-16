# Fase 4B — Cuentas por cobrar / pagar / saldos operacionales

**Veredicto de implementación:** GO. Receivable/payable canónicos, abonos parciales/finales, overpayment rechazado, reversos 3C, exactly-once, caja 3D, Decimal, atomicidad local, aging neto, local-first, UI en el writer canónico, `ferreteria.db` comercial intacta.

## Alcance

Certificar obligación original, abonos, saldo, reversos, crédito a favor, aging, caja 3D, exactly-once y local-first. No contabilidad, no 4C.

Contrato: [BALANCE_CONTRACT.md](BALANCE_CONTRACT.md).

## Arquitectura encontrada

Writer productivo de cobro: `AbonosVentasRepository.crear_abono`.
Writer productivo de pago proveedor: `AbonosaComprasRepository.crear_abono` / `registrar_abono_compra_en_transaccion`.
Lectura: `CuentasPorCobrarService` y `DeudasService` ahora consumen `services/operational_balance.py`.
`cuentas_por_cobrar` / `pagos_cuentas` / columnas `monto_pagado` son proyección.

## Cross-station

No existe coordinador financiero distribuido reutilizable para saldos. 4B no inventa uno. Atomicidad local PASS; W01+W02 sobre el mismo documento es limitación de deployment.

## Migración

`20260816_010` — `abonos_ventas.local_id` UNIQUE y `abonos_compras.local_id` UNIQUE. Idempotente. No reescribe REAL.
