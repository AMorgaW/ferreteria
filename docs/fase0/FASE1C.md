# Fase 1C — Inventory command, operaciones e idempotencia

**Estado:** implementada. Autorizada tras GO de QA de Fase 1B.2 y GO humano.
**Prohibido avanzar a Fase 1D** (coordinador PostgreSQL de stock) sin GO humano.

## Qué es Fase 1C

Crea la representación persistente, transaccional e idempotente de un
**comando** de inventario y sus **operaciones** por producto.

No descuenta `productos.stock`. No es autoridad. No activa
`APPLY_AUTHORITATIVE_EXCLUDE`. No migra ventas/compras/devoluciones/ajustes.

Hecho:

- Tablas `inventory_commands` / `inventory_operations` (SQLite y artefacto PG)
- `command_id` identifica la intención empresarial completa
- `operation_id` identifica el cambio por producto
- Persistencia atómica (command + líneas en una TX; fallo → ROLLBACK)
- Idempotencia por `command_id` + `request_hash`
- Fixed-point del ledger: escala 1000, sin float, sin migrar `productos.stock`
- Registry: tablas en `NON_SYNC_TABLES` (append-only; no LWW)

No hecho (Fase 1D+):

- coordinador / RPC / reserva central
- aplicar delta a stock autoritativo
- `APPLY_AUTHORITATIVE_EXCLUDE = True`
- fencing, autoridad offline, barcodes, recepción, OCR, UI nueva

INV-01 (overselling multi-PC) e INV-02 (stale stock LWW) siguen abiertos.

## Command vs Operation

`command_id` = una venta, compra, devolución, ajuste, recepción o mezcla.
Una venta de tres líneas tiene **un** command_id y **tres** operation_id.

El futuro coordinador decidirá atómicamente si el comando entero se aplica.
1C solo deja el modelo listo: no puede quedar A aplicado, B rechazado, C aplicado
a nivel de persistencia del comando.

## request_hash

SHA-256 hex de JSON canónico (`sort_keys=True`, `separators=(',', ':')`,
UTF-8) sobre:

- `command_id`
- `tipo`
- `documento_tipo`
- `documento_local_id`
- `operations` ordenadas por `line_no`: `operation_id`, `producto_local_id`,
  `delta_scaled` (entero)

**No entra:** `device_id`, `usuario_id`, timestamps, `estado`, `resultado`,
`motivo`.

Mismo command_id + mismo payload → retry. Payload distinto →
`IdempotencyConflictError`.

## Fixed-point del ledger

Escala 1000 = 1 unidad comercial. `Decimal(str(valor))` → máximo 3 decimales
→ entero exacto. Se rechaza `float` y más de 3 decimales.

Solo el ledger nuevo. `productos.stock` no se migra (INV-17 sigue xfail).

## Signo de delta

Tipos de **comando** (no copian `movimientos.tipo`):

| tipo | política (documental; 1C no valida signo) |
|---|---|
| VENTA | negativo (kardex `SALIDA_VENTA`) |
| COMPRA | positivo (kardex `ENTRADA_COMPRA`) |
| RECEPCION | positivo; mismo sentido que COMPRA (ADR-0002) |
| DEVOLUCION | según dirección real (`ENTRADA_DEVOLUCION` reingresa) |
| AJUSTE | ± |
| MEZCLA | mixto en el mismo comando |

`delta_scaled == 0` se rechaza. No hay línea de inventario vacía en v1.

## Estado

CHECK: `PERSISTED | APPLIED | REJECTED`.

1C solo escribe `PERSISTED` en `estado` y `resultado`. Significa **comando
almacenado**, no stock autoritativo aplicado. `APPLIED` queda para cuando
exista autoridad que realmente aplique el delta.

## Schema SQLite

Creado en `ensure_local_first_schema` → `ensure_inventory_ledger_schema`.
PK UUID TEXT. `UNIQUE(command_id, line_no)`. `operation_id` UNIQUE global.
FK operation → command. Identidad de producto = `productos.local_id`.
Sin columnas LWW (`local_id`/`remote_id`/`version` de sync).

## Schema PostgreSQL

`supabase_inventory_ledger.sql` ≡ `postgres_ledger_sql()`. TEXT UUID (paridad
con `productos.local_id`). `delta_scaled BIGINT`. Nunca contra SQLite
(`apply_postgres_ledger_sql`). No se añade al ARRAY de
`supabase_local_first_migration.sql`. Se aplica desde `_ensure_remote_schema`
después de la migración de sync. Sin RPC de stock.

## Sync

Las tablas **no** están en `SYNC_REGISTRY`. Están en `NON_SYNC_TABLES` +
`NON_SYNC_INSERT_PK` (`command_id` / `operation_id`). Append-only e
idempotentes; el transporte especial llega con el coordinador. 1C no llama
`enqueue_entity` ni `encolar`.

## Outbox

1C no rediseña el outbox. Punto futuro: cuando los writers migren, ledger y
outbox strict van en la misma TX; un fallo de cola aborta. Un fallo del
outbox legado **no** marca el ledger como aplicado (1C ni siquiera aplica).

## Tests

```text
python -m unittest discover -s tests/fase0 -v
python -m unittest discover -s tests/fase1a -v
python -m unittest discover -s tests/fase1b -v
python -m unittest discover -s tests/fase1b1 -v
python -m unittest discover -s tests/fase1b2 -v
python -m unittest discover -s tests/fase1c -v
```

INV-06 e INV-07 (existencia del ledger y centinela `operation_id`+`resultado`)
pasan. INV-01, INV-02 y el coordinador siguen xfail.

**STOP — no avanzar a Fase 1D.**
