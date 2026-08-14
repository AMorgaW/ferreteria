# Fase 1B.1 — Hardening del registry e identidad remota

**Estado:** implementada. QA de 1B.1: **GO FASE 1C** (blockers de identidad/registry cerrados).
**Prohibido avanzar a Fase 1C** sin GO humano. Este documento no autoriza implementar 1C.

## Qué es Fase 1B.1

No introduce ledger, coordinador, barcodes ni recepción. Cierra:

1. El sync genérico ya no asume PK entera `id`. El registry declara `pk`.
2. Identidad `local_id` UNIQUE en PostgreSQL: una sola fuente
   (`tables_requiring_postgres_local_id_unique` + `postgres_identity_sql`).
   `uq_*` es el nombre canónico; `ux_*` legado es la misma identidad.
3. `REMOTE_TABLES_REQUIRED_FOR_STARTUP` es política de arranque (subconjunto
   derivado del registry), no el conjunto de sync.
4. `historial_precios` en BD nueva tiene `local_id` UNIQUE y bootstrap
   repetido conserva identidad.

No hecho (Fase 1C+):

- `APPLY_AUTHORITATIVE_EXCLUDE` sigue `False`
- InventoryOperation / coordinador / RPC
- barcodes, recepción, autoridad offline, fixed-point

## Tests

```text
python -m unittest discover -s tests/fase0 -v
python -m unittest discover -s tests/fase1a -v
python -m unittest discover -s tests/fase1b -v
python -m unittest discover -s tests/fase1b1 -v
```

QA (adversarial): GO FASE 1C respecto de los blockers de 1B.1. Los HIGH residual
de `_remote_identity_ensured` tras fallo y de `uq_*` redundante junto a `ux_*`
los cierra Fase 1B.2 (`docs/fase0/FASE1B2.md`). **No autoriza implementar 1C.**
