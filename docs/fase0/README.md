# Fase 0 — Contrato arquitectónico y pruebas de ruptura

**Estado:** ejecutada. **Producción (Fase 0): no modificada.**  
Fase 1A (bootstrap SQLite) se implementó después, con GO humano, en
`schema_bootstrap.py` + DDL por motor. No reabre este contrato.
**Siguiente paso de inventario/recepción:** Fase 1E.2 (positivos y mixtos
preparados) está **implementada**; ver [FASE1E2.md](FASE1E2.md). Cutover
**OFF**. **No autoriza 1E.3, cutover, ni seed.** Fase 1D
(coordinador PostgreSQL de stock) está hecha. La certificación PostgreSQL
real de laboratorio está en [FASE1D1.md](FASE1D1.md). El gate de
autorización y la reconexión post-desconexión están en
[FASE1D3.md](FASE1D3.md).

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
| [FASE1C.md](FASE1C.md) | Ledger de comandos e idempotencia (implementada; no aplica stock) |
| [FASE1D.md](FASE1D.md) | Coordinador PostgreSQL / inventory_balances (implementada; no migra writers) |
| [FASE1D1.md](FASE1D1.md) | Certificación PostgreSQL real en Docker local (no migra writers) |
| [FASE1D3.md](FASE1D3.md) | Gate `session_user` + reconexión post-desconexión (no migra writers) |
| [FASE1E.md](FASE1E.md) | 1E.0–1E.2: gateway + writers preparados. Cutover OFF. |
| [FASE1E1.md](FASE1E1.md) | 1E.1 implementada: writers negativos preparados. Cutover OFF. |
| [FASE1E2.md](FASE1E2.md) | 1E.2 implementada: positivos y mixtos preparados. Cutover OFF. No autoriza 1E.3. |

Código de ruptura: `tests/fase0/`.

```text
python -m unittest discover -s tests/fase0 -v
```

Los tests `test_contrato_xfail.py` usan `unittest.expectedFailure`:
fallan contra el código de hoy y **deben** seguir fallando hasta que una
fase posterior implemente el contrato. Un XPASS significa que el contrato
se cumplió en silencio o que el test se volvió trivial.

Suite actual: **37 tests en fase0** (scanner 1E.0 endurecido). INV-15 (1A), INV-11/INV-18 (1B), INV-06/INV-07
(1C, ledger persistido) pasan. INV-19 se re-inventarió en 1E.0. El coordinador online vive en Fase 1D
(`tests/fase1d`, PostgreSQL real opt-in; certificación de laboratorio en
[FASE1D1.md](FASE1D1.md)). El xfail de dos SQLite, LWW de
stock, barcodes, recepción y fencing siguen xfail. **No declara INV-02
resuelto. INV-01 no se declara resuelto en SQLite.**

## NO-GO de producción (sigue vigente)

La auditoría previa concluyó **NO-GO** para modificar producción.
Fase 0 no revoca ese NO-GO. Solo lo documenta y lo convierte en tests.
