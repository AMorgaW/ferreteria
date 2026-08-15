# Fase 1E.4B — Hardening correctivo tras auditoría Luna

**Estado:** implementada contra PostgreSQL Docker de pruebas
(`ferrepro-pg-test`, localhost:55432, `ferrepro_test`).
**No declara Fase 1 completa.** **No toca Supabase real.**
**No usa `SUPABASE_URI`.** `INVENTORY_CUTOVER_ENABLED = False` y
`APPLY_AUTHORITATIVE_EXCLUDE = False` siguen en fuente.

Microfase correctiva. No reconstruye Fase 1. No implementa Fase 2,
barcodes, recepción, OCR ni fencing offline.

## NO-GO histórico (no revocado)

La auditoría final Luna sobre 1E.4 concluyó **NO-GO FASE 1** con
3 BLOCKER y 4 HIGH, pese a 396 PASS / 0 FAIL / 0 SKIP crítico en
laboratorio. Ese veredicto histórico **no se borra**. 1E.4B reproduce
y cierra esos hallazgos en código y tests. El re-gate humano es Luna.

## BLOCKER 1 — freeze TOCTOU

**REPRODUCIDO:** W03 leía PRE_CUTOVER, otra estación publicaba
`CUTOVER_IN_PROGRESS`, y el `UPDATE productos.stock` + commit SQLite
seguían. `assert_inventory_writes_allowed()` no es fence.

**CAUSA:** el check de estado y el commit de stock no compartían un
candado transaccional central. Además, `observe_cutover_state(cache=True)`
sobre la conexión del writer podía `COMMIT` SQLite (caché de cutover)
antes del candado, persistiendo stock a medias. En PostgreSQL 16 el rol
de aplicación tiene `SELECT` sobre `inventory_cutover_control` y
`UPDATE` revocado; `SELECT … FOR SHARE` / `FOR KEY SHARE` exigen
`UPDATE`, así que un lock de fila directo en el writer fallaba.

**CORRECCIÓN:** `commit_legacy_inventory()` toma
`lock_legacy_cutover_fence()` (`SECURITY DEFINER`, `FOR SHARE` como
owner, `GRANT EXECUTE` al rol app, sin `GRANT UPDATE` de tabla). Freeze
usa `SELECT … FOR UPDATE` + CAS. El fence observa con `cache=False`.
Si el freeze ya publicó `CUTOVER_IN_PROGRESS`, el writer no commitea.
Si el writer sostiene el lock, freeze espera. Cableado en W01, W03,
W13 y W16.

**TEST:** `test_writer_started_before_freeze_cannot_commit_legacy_stock`
(5×), `test_writer_that_wins_fence_is_visible_before_snapshot` (5×),
`test_w01_w03_w13_w16_freeze_primitive`.

**RESULTADO:** cerrado en W01/W03/W13/W16. Writers con UI que aún
commitean stock sin fence (W06, W08, W09, W10, W12, W17, W18) pueden
ganar una carrera TOCTOU si el freeze se publica **después** del
`resolve_writer_mode` inicial; una llamada **nueva** tras freeze sí
queda bloqueada. No reabre el repro Luna de W03. No es Fase 2.

## BLOCKER 2 — conjuntos de productos

**REPRODUCIDO:** PostgreSQL `{A,B}` vs SQLite `{A}` devolvía `ok=True`
porque el walk era solo SQLite→PG.

**CAUSA:** no se comparaba `SET(local_ids SQLite)` vs
`SET(local_ids PostgreSQL)` en ambos sentidos.

**CORRECCIÓN:** `reconcile_legacy_sources` clasifica sqlite_only,
postgres_only, extra_unexpected, null_local_id, invalid_local_id,
duplicados. Cualquier diferencia: NO CUTOVER / NO SEED / NO
AUTHORITATIVE.

**TEST:** `test_cutover_rejects_postgres_products_missing_locally`,
faltante remoto, `local_id` inválido/NULL.

**RESULTADO:** cerrado.

## BLOCKER 3 — identidad durable

**REPRODUCIDO:** W01 APPLY remoto → crash antes del INSERT local → UI
reintenta → nuevo UUID → segundo APPLY.

**CAUSA:** el `command_id` no era identidad del acto de negocio. Un
retry de UI mintaba otro UUID.

**CORRECCIÓN:** `durable_act_command_id` / `inventory_act_identities` /
`inventory_open_acts`. W01 UI: `registrar_compra_desde_ui()` deriva
fingerprint de factura+proveedor+líneas y **nunca** recibe
`inventory_command_id` del caller. Hook de crash
`notify_after_remote_apply` entre APPLY y INSERT local.

**TEST:** `test_w01_crash_after_apply_ui_retry_same_command`,
`test_restart_identity_recovery_representative_writers`,
`test_no_new_command_id_after_process_restart_pos`.

**RESULTADO:** cerrado para el acto W01 de UI y writers productivos
clasificados abajo. W15 sigue deprecated. W04 sigue sin caller UI.

### Cobertura W01–W18

| ID | Clase | Identidad |
|---|---|---|
| W01 | DERIVED fingerprint (UI) | `purchase_create_fingerprint` en `inventory_act_identities` |
| W02 | DERIVED_FROM_DOCUMENT | `compra_id` |
| W03 | DURABLE_IDENTITY_OK | `pos_checkout` open_act |
| W04 | DERIVED_FROM_DOCUMENT | `venta_id`; sin caller UI; preparado |
| W05 | NEEDS_OPEN_ACT | fingerprint venta+ítems |
| W06 | NEEDS_OPEN_ACT | fingerprint + CAS de payload APPLIED |
| W07 | NEEDS_OPEN_ACT | fingerprint `producto:operacion:cantidad` |
| W08 | NEEDS_OPEN_ACT | fingerprint `id:stock` |
| W09 | NEEDS_OPEN_ACT | fingerprint `local_id:nombre:stock` |
| W10 | NEEDS_OPEN_ACT | fingerprint movimiento |
| W11 | DURABLE_IDENTITY_OK | `anular_movimiento` + `movimiento_id` |
| W12 | NEEDS_OPEN_ACT | fingerprint movimiento inventario |
| W13 | NEEDS_OPEN_ACT | fingerprint `producto:nuevo_stock:motivo` |
| W14 | DERIVED_FROM_DOCUMENT | `movimiento_id` |
| W15 | DEPRECATED_NO_CALLER | fingerprint; UI usa W03 |
| W16 | DURABLE_IDENTITY_OK | `lan_sale` open_act |
| W17 | NEEDS_OPEN_ACT | fingerprint + CAS de payload APPLIED |
| W18 | DERIVED_FROM_DOCUMENT | `venta_id:detalle_id` |

## HIGH — epoch / state CAS

**REPRODUCIDO:** `activate_authority()` podía escribir `epoch=1` sobre
AUTHORITATIVE epoch=5.

**CAUSA:** `_write_postgres_state` incondicional (sigue como helper de
laboratorio `force_postgres_status`). Freeze/activate/abort productivos
no eran CAS.

**CORRECCIÓN:** `cas_postgres_cutover_state(expected_status, expected_epoch,
new_status, new_epoch)` con `FOR UPDATE`, `UPDATE … WHERE status=? AND
epoch=?`, rowcount=1. Epoch exactamente +1. Transiciones:
PRE→IN_PROGRESS, ROLLBACK_SAFE→IN_PROGRESS, IN_PROGRESS→AUTHORITATIVE,
IN_PROGRESS→ROLLBACK_SAFE, PRE→ROLLBACK_SAFE. Conflicto:
`StaleCutoverStateError`.

**TEST:** `test_stale_epoch_cannot_overwrite_newer_authoritative`,
`test_concurrent_cutover_cas` (5×).

**RESULTADO:** cerrado en rutas productivas. El helper de lab no es
ruta de freeze/activate.

## HIGH — APPLIED + payload distinto

**REPRODUCIDO:** W06/W17 con command APPLIED + operaciones distintas
tomaban shortcut y mutaban local.

**CAUSA:** `command_already_applied()` no comparaba hash/ops/expected_base.

**CORRECCIÓN:** comparar `request_hash`, operaciones y `expected_base_scaled`
si aplica. Divergencia → `IdempotencyConflictError`. Hash incluye
`expected_base_scaled` cuando está presente.

**TEST:** `test_w06_applied_changed_payload_conflict`,
`test_w17_applied_changed_payload_conflict`.

**RESULTADO:** cerrado.

## HIGH — seed exacto (no float)

**REPRODUCIDO:** `float(stock)*1000` sobre `9007199254740.993` →
9007199254740992, no 9007199254740993.

**CAUSA:** redondeo binario.

**CORRECCIÓN:** `legacy_stock_to_scaled()` con Decimal/str/int;
rechaza `float`; fetch PG/SQLite de stock como texto;
`quantity_to_scaled`; overflow BIGINT.

**TEST:** seed exacto, >3 decimales, BIGINT, rechazo de float,
NUMERIC real en PG.

**RESULTADO:** cerrado. SQLite REAL no puede almacenar ese literal;
el caso PG NUMERIC sí.

## HIGH — DSN ausente ≠ offline

**REPRODUCIDO:** ausencia de `FERREPRO_INVENTORY_DSN` se interpretaba
como offline y permitía legacy.

**CAUSA:** inferir modo por credencial.

**CORRECCIÓN:** ONLINE por defecto (`FERREPRO_INVENTORY_STATION_MODE`).
OFFLINE solo explícito. Tests locales hacen `setdefault(OFFLINE)` en el
harness. ONLINE sin capacidad de observar autoridad: mutaciones
fail-closed.

**TEST:** `test_missing_dsn_online_fail_closed`.

**RESULTADO:** cerrado. Fencing offline completo sigue fuera de Fase 1.

## MEDIUM — pg_stat_activity fail-closed

**REPRODUCIDO:** fallo de `pg_stat_activity` ponía `active=0` y el
cutover seguía.

**CAUSA:** fail-open.

**CORRECCIÓN:** `list_in_flight_inventory` lanza `InventoryCutoverError`.
`run_cutover` aborta: NO SEED / NO ACTIVATE.

**TEST:** `test_pg_stat_activity_failure_blocks_cutover`.

**RESULTADO:** cerrado.

## APPLY_AUTHORITATIVE_EXCLUDE

Sigue `False` en fuente. No se cambió por estética. En AUTHORITATIVE el
runtime ya excluye LWW de `productos.stock`. Test de guarda de fuente.

## STOP

**STOP — no declarar FASE 1 COMPLETA.** Pendiente re-auditoría Luna.
No cutover en Supabase real. No Fase 2.
