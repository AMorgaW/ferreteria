# Fase 2E — aplicación controlada del inventario físico

## Estado

El APPLY engine está implementado y certificado sobre fixtures SQLite. No se
ejecutó ningún batch comercial, no se migró `ferreteria.db` y no se usó
Supabase real.

Flujo cerrado:

`STAGING → VALIDACIÓN → MATCHING → REVIEW → DRY-RUN → APPROVAL → PRE-FLIGHT → APPLY → VERIFY → COMPLETED`

No existe transición directa de staging a aplicación. La migración
`20260815_005 controlled_inventory_apply` añade sidecars locales para workflow,
plan aprobado, lease, estados por fila, identidades y auditoría.

## Decisiones de seguridad

- `MATCH_CANDIDATE` y `AMBIGUOUS` requieren `CONFIRM MATCH` durable.
- Warnings requieren confirmación explícita.
- Un cambio de metadata requiere `APPLY` o `KEEP_CURRENT`; identidad y metadata
  son decisiones separadas.
- La aprobación persiste un snapshot canónico y su SHA-256. Una edición del
  staging invalida la aprobación; durante APPLY el staging está bloqueado.
- Los balances se leen de `inventory_balances.quantity_scaled` mediante el
  reader autoritativo. `productos.stock` no participa en el cálculo ONLINE.
- Toda diferencia usa `AJUSTE`, causa `INVENTARIO_FISICO` y documento
  `inventory_reconciliation`.
- `expected_base_scaled` protege el race entre aprobación y RPC.
- Cada fila conserva `inventory_command_id` y `inventory_operation_id` antes
  del RPC. Los retries reutilizan exactamente ambas identidades.
- Un producto nuevo se crea con `ProductosRepository.crear_producto`, política
  `STAGING`, stock local cero y `BARCODE_PENDING`. El balance inicial usa el
  gateway. No se genera FRP ni se persiste el candidato del Excel.
- Solo todas las filas `VERIFIED`/`NO_CHANGE_VERIFIED` permiten `COMPLETED`.

## Resultado de pruebas 2E

La suite `tests/fase2e` cubre aprobación, resolución durable, plan inmutable,
metadata, reconciliación positiva/negativa/cero, stale balance, producto nuevo,
empaques, idempotencia, UNKNOWN, restart, fallo parcial, lease concurrente,
read-back, auditoría y barreras estáticas contra SQL directo/barcodes/Supabase.

La autorización humana para ejecutar el inventario comercial queda fuera de
esta fase.

