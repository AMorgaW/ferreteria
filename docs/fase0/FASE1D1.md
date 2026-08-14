# Fase 1D.1 — Certificación PostgreSQL real

**Estado:** certificada en laboratorio Docker local el 2026-08-14.
**No autoriza Fase 1E.** No migra POS, compras ni writers productivos.
**No declara INV-01 resuelto en SQLite.** **No declara INV-02 resuelto.**

## Entorno

| Dato | Valor |
|---|---|
| Motor | PostgreSQL 16.15 (Debian 16.15-1.pgdg13+2) |
| Contenedor | `ferrepro-pg-test` (no destruido) |
| Base | `ferrepro_test` |
| Puerto host | 55432 → 5432 |
| Variable de tests | `FERREPRO_PG_TEST_DSN` (opt-in; no se documenta el valor) |
| `SUPABASE_URI` | no usada |
| Credenciales en git/docs/tests | no |
| Rol de la conexión de laboratorio | owner/superuser del contenedor de pruebas |

Esa conexión **no** certifica autorización empresarial (quién puede invocar
la RPC en producción, JWT, roles de negocio). Certifica la lógica del
coordinador: atomicidad, locking, idempotencia y separación de
`productos.stock`.

## Correcciones realizadas durante 1D.1

1. **SQL con `\` inicial.** `_POSTGRES_COORDINATOR_SQL = r"""\` preservaba
   el backslash (raw string ≠ continuación de línea). PostgreSQL fallaba
   con `syntax error at or near "\"`. Fuente canónica corregida a
   `r"""-- FERREPRO...`. Artefacto
   `supabase_inventory_coordinator.sql` en paridad. CONTRACT
   `test_sql_no_empieza_con_backslash_ni_basura`.
   `apply_postgres_coordinator_sql()` no sanitiza SQL inválido.
2. **`unique_violation` mal clasificada.** El handler del RPC trataba
   cualquier unique como replay o `DUPLICATE_OPERATION`. Ahora usa
   `GET STACKED DIAGNOSTICS … CONSTRAINT_NAME`:
   - `inventory_commands_pkey` → replay o `IDEMPOTENCY_CONFLICT`
   - `inventory_operations_pkey` / `…command_id_line_no_key` →
     `DUPLICATE_OPERATION`
   - `inventory_balances_pkey` / `inventory_balance_init_pkey` / otra →
     re-raise; no es “ya se procesó”

## Tests ejecutados

```text
python -m unittest discover -s tests/fase1d -v
```

Clasificación (suite `tests/fase1d`, DSN presente):

| Capa | PASS | FAIL | SKIPPED |
|---|---|---|---|
| UNIT | 9 | 0 | 0 |
| CONTRACT | 14 | 0 | 0 |
| POSTGRES INTEGRATION | 26 | 0 | 0 |
| **Total** | **49** | **0** | **0** |

SKIP no se cuenta como certificación. Aquí SKIPPED = 0 en pruebas
PostgreSQL críticas.

## Escenarios obligatorios (PostgreSQL real)

| Escenario | Test | Resultado |
|---|---|---|
| Dos cajas, balance 50000, dos `delta=-50000` concurrentes → APPLIED=1, REJECTED=1, balance=0 | `test_03_y_escenario_dos_cajas_ultimo_stock` | PASS |
| Multilínea X=10000 Y=1000, X-5000 Y-2000 → REJECTED, X=10000 Y=1000 | `test_09_multilinea_parcial_no_aplica` | PASS |
| Retry post-commit mismo command_id/hash → `replayed=True`, delta una vez | `test_04_retry_applied_no_doble_delta`, `test_07_timeout_simulado_post_commit`, `test_22_persistencia_nueva_conexion` | PASS |
| REJECTED idempotente (INSUFFICIENT_STOCK se conserva) | `test_05_retry_rejected_conserva_motivo` | PASS |
| Hash distinto → IdempotencyConflict, balance intacto respecto del primer apply | `test_06_hash_distinto_conflicto` | PASS |
| Orden inverso X/Y vs Y/X sin deadlock; ambos APPLIED | `test_10_orden_inverso_sin_deadlock` | PASS |
| unique_violation distinguida; operation_id duplicado no es replay | `test_unique_violation_no_es_replay` + CONTRACT | PASS |
| SET LOCAL statement_timeout no fugas tras commit; rollback recupera la conexión | `test_set_local_timeout_no_fuga_y_rollback` | PASS |
| 50 u = 50000; 1.5 = 1500; 0.125 = 125; overflow BIGINT no muta | `test_01_*`, `test_14_*`, `test_fixed_point_0125`, `test_overflow_bigint_real_no_cambia_balance` | PASS |
| Delta negativo sin fila → BALANCE_NOT_FOUND; positivo crea fila | `test_13_negativo_sin_balance`, `test_positivo_crea_fila_ausente` | PASS |
| Semilla no pisa; legacy init no automática | `test_29_semilla_no_pisa_balance_nuevo` | PASS |
| RPC SECURITY DEFINER, search_path, REVOKE PUBLIC | `test_26_27_rpc_no_public_search_path` + CONTRACT | PASS |
| `productos.stock` no lo toca el coordinador | `test_23_24_stock_legacy_no_contamina` | PASS |

## Estabilidad

Tres ejecuciones completas consecutivas de `tests/fase1d` con DSN:

| Run | ran | ok | fail | skip |
|---|---|---|---|---|
| 1 | 49 | 49 | 0 | 0 |
| 2 | 49 | 49 | 0 | 0 |
| 3 | 49 | 49 | 0 | 0 |

Sin flakiness observada en carreras, locks, deadlocks, cleanup ni UUIDs.

## Regresión Fase 0 → 1D

| Suite | ran | ok | expected failure | unexpected success | skipped | fail |
|---|---|---|---|---|---|---|
| fase0 | 34 | 21 | 13 | 0 | 0 | 0 |
| fase1a | 8 | 8 | 0 | 0 | 0 | 0 |
| fase1b | 22 | 22 | 0 | 0 | 0 | 0 |
| fase1b1 | 19 | 19 | 0 | 0 | 0 | 0 |
| fase1b2 | 28 | 28 | 0 | 0 | 0 | 0 |
| fase1c | 28 | 28 | 0 | 0 | 0 | 0 |
| fase1d | 49 | 49 | 0 | 0 | 0 | 0 |

Los xfail arquitectónicos de Fase 0 (dos SQLite de INV-01, LWW de stock,
barcodes, recepción, fencing, etc.) **siguen** expected-failure.

## Riesgos que siguen abiertos

- Writers productivos (POS, compras, devoluciones, mezclas, ajustes) no
  usan el coordinador. `APPLY_AUTHORITATIVE_EXCLUDE` sigue `False`.
- INV-02: `productos.stock` sigue viajando por UPSERT LWW.
- INV-01 en dos SQLite independientes sigue xfail (centinela local).
- Autorización de negocio de la RPC (quién puede mandar deltas) no está
  certificada; el laboratorio usa el rol owner del contenedor.
- Autoridad offline / fencing / barcodes / recepción: Fase 1E+; no hechas.

**STOP — no migrar writers productivos.**
