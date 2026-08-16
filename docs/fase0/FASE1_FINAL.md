# Fase 1 — cierre técnico definitivo

**Estado:** FASE 1 TÉCNICAMENTE COMPLETA.

**Gate ejecutado:** 2026-08-15, rama `fase2-migration-sanitation`.

La autoridad ONLINE de cantidad es exclusivamente PostgreSQL:
`inventory_balances.quantity_scaled`. `productos.stock` permanece como
proyección/cache legacy y queda fuera del LWW autoritativo.

## Cierres del NO-GO final

1. **Snapshot de flota:** PostgreSQL persiste el conjunto explícito de
   estaciones esperadas, sus atestaciones por `device_id/cutover_id/epoch`,
   checksums y líneas. Una estación ausente, stale o divergente impide aprobar.
2. **Identidad CAS:** `expected_base_scaled` participa en el hash canónico
   Python/SQLite/RPC/PostgreSQL cuando está presente. Ausente/NULL conserva la
   identidad histórica; `0` y demás BIGINT son valores semánticos distintos.
3. **Seed aprobado:** el seed recibe solo `cutover_id/epoch` y lee líneas
   `APPROVED` desde PostgreSQL. Un payload Python alterado no puede cambiar las
   cantidades sembradas.

También se cerró una carrera descubierta durante la regresión: dos checkouts
POS implícitos concurrentes ya no comparten un OPEN act dentro del proceso.
La identidad durable continúa persistida en SQLite para recuperación tras
reinicio.

## Certificación

- PostgreSQL: `ferrepro-pg-test`, `localhost:55432`, base `ferrepro_test`.
- Versión: PostgreSQL 16.
- Gate específico 1E.4B–1E.4D: **53 PASS**.
- Regresión Fase 0–1E.4D: **436 PASS**, **13 expectedFailure** históricos,
  **0 FAIL**, **0 ERROR**, **0 SKIP**, **0 XPASS**.
- Rol normal: no-owner; no modifica plan, atestaciones aprobadas ni seed.
- BLOCKER: **0**.
- HIGH: **0**.

El test 53 falsifica además una modificación admin de líneas después de
`APPROVED`: el seed recalcula checksum y product count dentro de su transacción
y aborta sin crear balances si no coinciden.

Los expected failures restantes corresponden a contratos legacy o fases
posteriores: autoridad OFFLINE completa, recepción, barcodes, aliases,
unicidad de factura proveedor y saneamiento general.

## Producción

El cutover productivo **NO fue ejecutado**. No se usó Supabase real ni datos
comerciales. La implementación está lista para un procedimiento productivo
controlado posterior, separado de este cierre.

## Autorización

Fase 1 técnicamente completa. Se autoriza iniciar Fase 2A de migración y
saneamiento legacy.
