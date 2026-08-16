# Fase 3 — Cierre final software/operacional

**Veredicto final:** GO.

Fase 3 está completa a nivel de software y operación validada en entornos temporales:

- 3A Ventas/POS — **GO**.
- 3B Compras/Recepción — **GO**.
- 3C Devoluciones/Reversos — **GO**.
- 3D Caja/Cierre — **GO**.

## Acceptance final de 3D

La caja conserva una sesión durable por estación, una sola OPEN por estación,
ledger `cash_movements` con identidad UUID de fuente, cálculo monetario canónico
con `Decimal`, recuperación exactly-once, aislamiento de métodos de pago,
reembolsos y pagos a proveedor sin doble conteo, cruce de medianoche y cierre
inmutable bajo transacción SQLite `BEGIN IMMEDIATE`.

Si un efecto físico comercial se confirma sin una sesión OPEN, queda durable y
sin sesión en `cash_movements`; la próxima OPEN de la misma estación lo reclama
atómicamente. Nunca se agrega después a una CLOSED ni se pierde por restart.

## Evidencia automatizada

- `tests/fase3d`: **27 passed**, 0 failed, 0 errors, 0 skipped.
- `tests/fase3a` a `tests/fase3d`: **115 passed**, 0 failed, 0 errors, 0 skipped.
- regresión `tests/fase2g1` + 3A–3D: **129 passed**, 0 failed, 0 errors, 0 skipped.
- migración dirigida `tests/fase2/test_migrations.py`: **7 passed**.

Todas las pruebas usaron SQLite temporal, fixtures y mocks. No se abrió ni cerró
caja comercial, no se creó una venta comercial y no se ejecutó inventario real.

## Fuera de Fase 3

- Inventario comercial real y su aceptación operativa.
- Puesta en producción y operación de caja comercial real.
- Limitaciones cross-station de discovery de documentos.
- Replicación remota completa de `cash_movements`; hoy el outbox es best-effort y
  la integridad local no depende del catálogo remoto.

**FASE 3 SOFTWARE/OPERACIONAL: COMPLETE.**

Ready for checkpoint; sin `git add`, commit ni push en este review.
