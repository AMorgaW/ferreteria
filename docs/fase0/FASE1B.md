# Fase 1B — Identidad canónica y registry de sincronización

**Estado:** implementada. Autorizada tras GO de QA de Fase 1A.
**Prohibido avanzar a Fase 1C** sin GO humano.

## Qué es Fase 1B

Prepara identidades globales y la infraestructura de sync **antes** de
introducir `InventoryOperation` y el coordinador central.

Hecho:

- Registry único `sync_registry.SYNC_REGISTRY`. Las listas históricas se derivan.
- `productos.local_id` reutilizado como UUID global del SKU (no se creó otra).
- `crear_producto` inserta `local_id` en el alta.
- Backfill idempotente de `local_id` en bases viejas (`ensure_local_id_unique`).
- Identidad de dispositivo persistente: `config/device_identity.json`.
- Contrato de `productos.stock` como proyección **declarado**, no aplicado.

No hecho (Fase 1C+):

- ledger productivo / `InventoryOperation`
- reserva central de stock / RPC de venta
- exclusión autoritativa de `stock` en UPSERT (`APPLY_AUTHORITATIVE_EXCLUDE` sigue `False`)
- leases, fencing, `OFFLINE_INVENTORY_AUTHORITY`
- recepción, barcodes múltiples, OCR, UI nueva

## Identidad

Cada fila sincronizada tiene `id` entero local (FKs del DDL) y `local_id` UUID
de sync. El push/pull traduce FKs enteras usando el UUID del padre.

Excepciones documentadas en el código:

- `configuracion` usa PK `clave`, no `id`.
- `devoluciones` / `formulas_mezcla` fuera de sync.
- Columna `device_id` de fila ≠ identidad del equipo.

## Tests

```text
python -m unittest discover -s tests/fase0 -v
python -m unittest discover -s tests/fase1a -v
python -m unittest discover -s tests/fase1b -v
```

INV-02 (stale stock), INV-01 (overselling), INV-06 (operation_id), INV-08
(barcodes), INV-04 (recepción) e INV-12 (autoridad offline) siguen xfail.

## Riesgos pendientes (no 1C)

- Fase 1B.1 cerró: PK genérica en el UPSERT (`pk_column` / `RETURNING` declarado),
  identidad PostgreSQL canónica (`postgres_identity_sql` + equivalencia `uq_*`/`ux_*`)
  y la política de arranque `REMOTE_TABLES_REQUIRED_FOR_STARTUP` (subconjunto
  derivado, no Kahn).
- El cobro real de CxC sigue siendo `abonos_ventas`. No hay escritor productivo
  de `configuracion` hacia el outbox.
- `APPLY_AUTHORITATIVE_EXCLUDE` sigue `False`. No declarar INV-02 resuelto.
