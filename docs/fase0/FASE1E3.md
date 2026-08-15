# Fase 1E.3 — Cutover único de autoridad de inventario (laboratorio)

**Estado:** mecanismo implementado y ensayado contra PostgreSQL Docker
de pruebas (`ferrepro-pg-test`, localhost:55432, `ferrepro_test`).
**No declara producción activada.** No toca Supabase real.
**No usa `SUPABASE_URI`.** No modifica datos comerciales.
**No declara INV-01 resuelto en dos SQLite.**
INV-02 queda cerrado **para autoridad ONLINE** tras estado `AUTHORITATIVE`.

`INVENTORY_CUTOVER_ENABLED = False` sigue en fuente. La autoridad se
lee de estado persistente (`inventory_cutover_state` / control PG).
`APPLY_AUTHORITATIVE_EXCLUDE = False` sigue en fuente. El runtime aplica
el exclude declarado de `productos.stock` **solo** si el estado es
`AUTHORITATIVE`.

## Qué es 1E.3

Un **cutover único** desde `productos.stock` (legacy/LWW) hacia
`inventory_balances.quantity_scaled` como autoridad ONLINE.

No es writer por writer. No es equipo por equipo. No es una constante
Python mutable.

```
PRE_CUTOVER → CUTOVER_IN_PROGRESS → AUTHORITATIVE
                                 ↘ FAILED / ROLLBACK_SAFE
```

Procedimiento: `inventory_cutover.run_cutover()`:

1. `verify_preconditions()` — fail closed
2. `freeze_inventory_writes()`
3. seed one-shot `initialize_inventory_balances_from_legacy()`
4. `reconcile_seed()` — igualdad exacta `stock * 1000 == quantity_scaled`
5. `activate_authority()` — epoch++, timestamps, evidencia
6. unfreeze implícito al pasar a `AUTHORITATIVE`

Si una etapa falla: no se activa. Antes del primer APPLY autoritativo
cabe `abort_pre_activation()` → `ROLLBACK_SAFE`. Después del primer
APPLY autoritativo: **no** se vuelve a `productos.stock` legacy
(`UnsafeRollbackError`). Recovery post-activación es hacia adelante.

## Preconditions (todas o NO CUTOVER)

1. W01–W18 preparados (W15 DEPRECATED, W04 sin UI, ambos preparados).
2. Scanner: 0 `UNTRACKED_DIRECT_WRITER`.
3. Productos activos con `local_id` UUID válido.
4. No hay commands `AUTHORITATIVE` + `PERSISTED` ambiguos.
5. `LEGACY_OBSERVED` nunca transmissible.
6. PostgreSQL accesible.
7. DSN de aplicación = `FERREPRO_INVENTORY_DSN` (nunca `SUPABASE_URI`).
8. Caller de app: rol no-owner, miembro de `ferrepro_inventory_app`.
9. Seed no ejecutado o estado verificable (one-shot).
10. Tras seed: `productos.stock` reconciliado con balances.
11. Freeze global durante `CUTOVER_IN_PROGRESS` (writers rechazan).
12. Rollback pre-activación disponible.

## Freeze

Estado persistente `CUTOVER_IN_PROGRESS`. Los writers (venta, compra,
ajuste, LAN) rechazan con `InventoryFrozenError`. No se confía en
“que nadie venda”.

## Seed

`initialize_inventory_balances_from_legacy()`:

- solo explícito (`run_cutover` / owner de laboratorio)
- one-shot (`inventory_balance_init_state`)
- no corre en startup ni en sync
- no sobrescribe balances existentes
- owner/admin de laboratorio; operación normal posterior = no-owner

## Reconciliación

No basta con “SQL no lanzó excepción”. Por cada producto con
`local_id`:

`round(legacy_stock * 1000) == inventory_balances.quantity_scaled`

Reporte: productos legacy, seeded, missing, duplicates, mismatch,
`local_id` inválidos. Cualquier mismatch: **no se activa**.

## Activation persistente

SQLite `inventory_cutover_state` (singleton) y PostgreSQL
`inventory_cutover_control`. Tras reboot la aplicación relée el
estado. `resolve_writer_mode()` sin kwargs devuelve `authoritative`
si el estado persistente es `AUTHORITATIVE`.

## Rollback

| Ventana | Significado |
|---|---|
| PRE-ACTIVATION | Abortar a `ROLLBACK_SAFE` / legacy si no hubo APPLY autoritativo. |
| POST-ACTIVATION | Forward recovery/reconciliation. **Prohibido** `flag=False`. |

## `productos.stock` después del cutover

Autoridad: `inventory_balances.quantity_scaled`.
`productos.stock` = **proyección / caché legacy** (D05
`project_local_stock`). Se refresca tras APPLIED **solo** si el
estado persistente es `AUTHORITATIVE`. No es segunda autoridad.
Si la proyección falla, el APPLY remoto ya ocurrió.

## LWW / INV-02 (online)

PRE_CUTOVER: UPSERT LWW de `stock` intacto (INV-02 xfail de dos
SQLite / payload sigue).

AUTHORITATIVE: `productos.stock` se excluye de push y pull LWW.
Nombre, precio, código y metadata de `productos` **siguen**
sincronizando. `APPLY_AUTHORITATIVE_EXCLUDE` no se pone `True` en
fuente: el exclude es runtime según estado.

No se declara INV-01 de dos SQLite resuelto.

## command_id estable

- W03 POS: `inventory_act_identities` (`pos_checkout`) ligado al
  checkout local **antes** de red. UNKNOWN no limpia el carrito;
  reintenta el mismo id.
- W16 LAN: `inventory_command_id` en JSON HTTP **no** crea identidad
  nueva. Solo se reutiliza si ya existe en el ledger (retry). El
  servidor genera el id. UNKNOWN HTTP 503 + `retryable` + `command_id`.

## No-owner

Camino productivo: `FERREPRO_INVENTORY_DSN` → `autocommit=False` →
`assert_non_owner_app_role`. Superuser y owner de
`inventory_balances` no son callers normales. Seed/cutover admin
puede ser owner de laboratorio. Lectura de balance para proyección/CAS:
RPC `fetch_inventory_balance` (SECURITY DEFINER), no GRANT de DML.

## Laboratorio

`ferrepro-pg-test`, PostgreSQL 16, `localhost:55432`, `ferrepro_test`.
Fixtures: stock 0, positivo, fraccionario, varios `local_id`.
Ensayos: freeze, seed, reconcile, activate, venta/compra/ajuste,
REJECTED sin documento, dos cajas writer-level, cross-writer
(venta vs ajuste, W03 vs W16), restart, LWW stale, no-owner.

**Este laboratorio certifica el MECANISMO. No autoriza cutover
productivo.**

## Riesgos restantes para 1E.4 — cerrados en laboratorio

Ver [FASE1E4.md](FASE1E4.md). Congelar todas las estaciones, fail-closed
si PostgreSQL no responde, snapshot no-LWW y `verify_preconditions` sin
`tests/` están implementados contra `ferrepro-pg-test`.

## STOP

**STOP — 1E.3 cerrada.** Continúa en [FASE1E4.md](FASE1E4.md).
No cutover en Supabase real. No barcodes. No recepción. No fencing.
