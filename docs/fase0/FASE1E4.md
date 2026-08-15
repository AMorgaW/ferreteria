# Fase 1E.4 — Hardening de flota + certificación final de cutover

**Estado:** implementada contra PostgreSQL Docker de pruebas
(`ferrepro-pg-test`, localhost:55432, `ferrepro_test`, PostgreSQL 16).
**No declara Fase 1 completa.** Falta auditoría final humana (Luna).
**No toca Supabase real.** **No usa `SUPABASE_URI`.**
`INVENTORY_CUTOVER_ENABLED = False` y `APPLY_AUTHORITATIVE_EXCLUDE = False`
siguen en fuente. La autoridad runtime se lee del control PostgreSQL de
flota y de su cache SQLite.

## Qué es 1E.4

Cierra los riesgos de 1E.3 que impedían declarar Fase 1 técnicamente
implementada:

1. freeze/autoridad ya no dependen solo del SQLite de cada estación;
2. cada caja online observa `inventory_cutover_control`;
3. si no se puede leer el estado global, la mutación falla cerrada;
4. el seed no se basa a ciegas en `productos.stock` LWW;
5. `verify_preconditions` no importa `tests/`;
6. `productos.stock` es proyección/caché; no muta `inventory_balances`.

No implementa Fase 2, barcodes, recepción, OCR ni fencing/offline (INV-01
de dos SQLite independientes sigue siendo limitación conocida).

## Source of truth del cutover (ONLINE)

PostgreSQL `inventory_cutover_control` es la autoridad de flota.

La copia SQLite `inventory_cutover_state` es cache/auditoría. No puede
declarar `PRE_CUTOVER`/`LEGACY` si PostgreSQL ya dice `AUTHORITATIVE`.
No puede ignorar `CUTOVER_IN_PROGRESS`.

Estados observables:

`PRE_CUTOVER` · `CUTOVER_IN_PROGRESS` · `AUTHORITATIVE` ·
`FAILED` / `ROLLBACK_SAFE` + epoch/versión.

## Fail-closed

Estación online + mutación de inventario + estado global ilegible:

- no asume LEGACY;
- no escribe `productos.stock`;
- error explícito `CUTOVER_STATE_UNAVAILABLE` (retryable).

Las lecturas/caché pueden degradar. Las mutaciones no.

## Freeze de flota

`CUTOVER_IN_PROGRESS` se publica primero en PostgreSQL. Una caja con
cache SQLite `PRE_CUTOVER` que observa el control remoto queda bloqueada
(venta, compra, ajuste, LAN).

## Snapshot de corte

Procedimiento de `run_cutover()`:

1. `verify_preconditions()` (marcador productivo `inventory_writer_contract`)
2. publicar `CUTOVER_IN_PROGRESS` global (PG primero)
3. confirmar que no hay operaciones de inventario en vuelo
4. reconciliar fuentes legacy (SQLite vs PostgreSQL `productos.stock`)
5. capturar snapshot congelado
6. seed one-shot desde el snapshot
7. comparar exactamente snapshot ↔ `inventory_balances`
8. activar `AUTHORITATIVE`

Si las fuentes legacy no convergen: **NO CUTOVER**. No se elige el último
LWW. INV-01 de dos SQLite independientes no se finge resuelto.

El snapshot incluye `producto_local_id`, `quantity_scaled`, `cutover_id`,
epoch, timestamp y checksum SHA-256. Un snapshot mutado no se acepta.

## Proyección

Tras `AUTHORITATIVE`: `inventory_balances` es autoridad.
`productos.stock` es caché reconstruible (D05). Un pull/push LWW stale no
deshace balances. Metadata de producto sigue sincronizando. Si la
proyección falla después de APPLY, el command sigue APPLIED.

W03 POS y W16 LAN persisten el acto en SQLite (`inventory_open_acts`)
antes del primer envío. UNKNOWN + restart de proceso reutiliza el mismo
`command_id`. No vive solo en RAM.

## Rollback

Antes de `AUTHORITATIVE` y sin APPLY autoritativo: `ROLLBACK_SAFE`.
Después de `AUTHORITATIVE` o del primer APPLY (en cualquier estación):
`UnsafeRollbackError`. Recovery hacia adelante.

## Laboratorio

`ferrepro-pg-test`. Rol de operación: miembro de `ferrepro_inventory_app`,
no owner, no superuser, no `BYPASSRLS`. Seed/cutover admin puede ser
owner de laboratorio.

## STOP

**STOP — no declarar FASE 1 COMPLETA.** Auditoría Luna sobre 1E.4:
**NO-GO FASE 1** (3 BLOCKER + 4 HIGH). Correctiva: [FASE1E4B.md](FASE1E4B.md).
No cutover en Supabase real. No Fase 2. No barcodes. No recepción.
No fencing.
