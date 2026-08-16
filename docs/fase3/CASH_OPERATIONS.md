# Caja operacional (Fase 3D)

## Autoridad

El cajón pertenece a una estación local (`station_id`, reutiliza `device_id` si no se inyecta otro). Abrir, consultar, mover, arquear y cerrar persisten primero en SQLite. No hay autoridad central síncrona de caja. Cloud no es prerrequisito.

## Estación

W01 y W02 pueden tener sesiones OPEN simultáneas e independientes. Una estación: máximo una sesión OPEN. Constraint: índice único `cierres_caja(station_id) WHERE fecha_cierre IS NULL`.

## Apertura

Acción explícita ADMIN/GERENTE. Guarda `local_id`, `station_id`, usuario, monto inicial ≥ 0, `fecha_apertura`, estado OPEN. No se abre al arrancar ni tras un cierre.

Restart: recupera la misma sesión OPEN. Segundo OPEN: `EXISTING_OPEN_SESSION`.

## Ledger

`cash_movements` es la fuente canónica del cajón. Cada efecto: identidad durable, `cash_session_id`, kind, amount (TEXT Decimal), método, direction IN/OUT, `cash_effect_kind`, source_kind + source_identity, timestamp, usuario, descripción.

Un efecto físico comercial confirmado sin OPEN queda durable con `cash_session_id` nulo y `station_id` definido. La próxima OPEN de esa estación lo reclama dentro de la transacción de apertura. Los movimientos manuales sí exigen una OPEN y nunca quedan pendientes.

Exactly-once: UNIQUE `(source_kind, source_identity, cash_effect_kind)`. Retry/restart no duplica.

## Métodos

| Evento | Resumen | Cajón físico |
| --- | --- | --- |
| Venta EFECTIVO COMPLETED | ventas efectivo | IN |
| Tarjeta / transferencia | informativo | 0 |
| Venta CRÉDITO | informativo | 0 |
| Abono cliente EFECTIVO | abonos | IN |
| Abono cliente no efectivo | informativo | 0 |
| Pago proveedor EFECTIVO | pagos proveedor | UN OUT (identidad `abono_compra`) |
| Egreso manual EFECTIVO | egresos | OUT |
| Egreso no efectivo | reportable | 0 |
| Devolución/anulación reembolso EFECTIVO | devoluciones | OUT |
| Reembolso tarjeta/transferencia | informativo | 0 |
| Devolución a proveedor | inventario 3C | 0 (no inventa dinero) |

SCAN/DRAFT/venta rechazada: 0 movimientos.

`egresos_caja` legacy se conserva para Movimientos. El esperado NO suma abono + egreso del mismo pago.

## Expected cash

```
EXPECTED = OPENING + CASH_IN − CASH_OUT
```

Una función: `CajaService.obtener_resumen_sesion` / `compute_session_summary`. La UI no recalcula con reglas paralelas.

La sesión, no el día: medianoche no parte el cajón. Autoridad = `cash_session_id` / `fecha_apertura`→`fecha_cierre`.

## Arqueo y cierre

Usuario ingresa monto contado ≥ 0. Diferencia = contado − esperado. 0 CUADRA, >0 SOBRANTE, <0 FALTANTE. La diferencia es evidencia; no se reescriben movimientos. Observación requerida si diferencia ≠ 0.

Cierre explícito, snapshot durable, estado CLOSED inmutable. Segundo cierre: `ALREADY_CLOSED`. Tras CLOSED no entran movimientos.

Cierre vs venta: transacción SQLite IMMEDIATE. Un movimiento no queda enlazado a sesión cerrada fuera del snapshot.

## Restart / recovery

OPEN persiste. Movimiento perdido se rehidrata exactly-once. Movimiento ya persistido + retry = 1 fila. Cierre persistido permanece CLOSED.

## Local-first / UI

`CajaService` usa `db_manager` SQLite. Sync/remoto en background. Scanner HID (Enter) no confirma cierre. Identidad visual FERREPRO conservada.

## Limitaciones

- `cierres_caja`/`egresos_caja` siguen con REAL legacy; la capa canónica normaliza Decimal.
- `cash_movements` se encola best-effort; no se añadió al catálogo remoto 1B en esta etapa.
- Inventario comercial real y caja comercial real no se operan aquí.
