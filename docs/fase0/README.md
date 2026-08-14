# Fase 0 — Contrato arquitectónico y pruebas de ruptura

**Estado:** ejecutada. **Producción (Fase 0): no modificada.**  
Fase 1A (bootstrap SQLite) se implementó después, con GO humano, en
`schema_bootstrap.py` + DDL por motor. No reabre este contrato.
**Siguiente paso de inventario/recepción:** autorización humana de Fase 1C
(InventoryOperation / coordinador). Fase 1B (identidad + registry), Fase 1B.1
(hardening de PK genérica e identidad PostgreSQL) y Fase 1B.2 (hardening
final de identidad remota) están hechas. **No autoriza implementar 1C.**

## Qué es Fase 0

Fase 0 no implementa recepción, barcodes, OCR ni el coordinador central.
Deja por escrito el contrato que las fases siguientes deben cumplir, y deja
tests que **hoy fallan de forma esperada** (o caracterizan el bug actual).

Permitido:

- documentación y ADRs
- inventario de writers de stock
- invariantes
- harness de BD temporal + fixtures
- tests adversariales expected-failure
- análisis estático
- agentes Cursor de arquitecto/QA

Prohibido (y no se hizo):

- modificar ventas, compras, stock, sync productivo
- esquema o migraciones productivas
- UI productiva, permisos efectivos, comportamiento offline

## Índice

| Documento | Contenido |
|---|---|
| [CONTRATO.md](CONTRATO.md) | Contrato único: autoridad, ledger, recepción, barcodes |
| [ADR-0001-autoridad-inventario.md](ADR-0001-autoridad-inventario.md) | Online PostgreSQL / offline OFFLINE_INVENTORY_AUTHORITY |
| [ADR-0002-ledger-operaciones.md](ADR-0002-ledger-operaciones.md) | InventoryOperation idempotente |
| [ADR-0003-fencing-y-device-id.md](ADR-0003-fencing-y-device-id.md) | device_id UUID + lease/epoch |
| [ADR-0004-recepcion-sin-stock.md](ADR-0004-recepcion-sin-stock.md) | Extracción = borrador; aceptada = único ingreso |
| [ADR-0005-barcodes-frp.md](ADR-0005-barcodes-frp.md) | FRP- + 16 hex; múltiples códigos; alias ≠ barcode |
| [STOCK_WRITERS.md](STOCK_WRITERS.md) | Rutas actuales que mutan `productos.stock` |
| [INVARIANTES.md](INVARIANTES.md) | Invariantes deseados vs violación actual |
| [FASE1B.md](FASE1B.md) | Identidad UUID + registry canónico de sync (implementada) |
| [FASE1B1.md](FASE1B1.md) | Hardening 1B.1: PK genérica, identidad PG única, arranque |
| [FASE1B2.md](FASE1B2.md) | Hardening 1B.2: garantía remota, paridad UNIQUE, PgCursor |

Código de ruptura: `tests/fase0/`.

```text
python -m unittest discover -s tests/fase0 -v
```

Los tests `test_contrato_xfail.py` usan `unittest.expectedFailure`:
fallan contra el código de hoy y **deben** seguir fallando hasta que una
fase posterior implemente el contrato. Un XPASS significa que el contrato
se cumplió en silencio o que el test se volvió trivial.

Suite actual: **34 tests, OK, 15 expected failures** (INV-15 en 1A, INV-11 e
INV-18 en 1B). El schema SQLite de 1A y el registry/identidad de 1B no cierran
los xfail de autoridad, ledger, barcodes, recepción ni fencing.

## NO-GO de producción (sigue vigente)

La auditoría previa concluyó **NO-GO** para modificar producción.
Fase 0 no revoca ese NO-GO. Solo lo documenta y lo convierte en tests.
