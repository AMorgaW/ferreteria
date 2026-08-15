# Fase 1E.4C — Fleet fence en todos los writers legacy

**Estado:** implementada contra PostgreSQL Docker de pruebas
(`ferrepro-pg-test`, localhost:55432, `ferrepro_test`).
**No declara Fase 1 completa.** **No toca Supabase real.**
**No usa `SUPABASE_URI`.** `INVENTORY_CUTOVER_ENABLED = False` y
`APPLY_AUTHORITATIVE_EXCLUDE = False` siguen en fuente.

Microfase correctiva FINAL del HIGH residual de freeze. No reconstruye
Fase 1. No implementa Fase 2, barcodes, recepción, OCR ni fencing
offline. No hace cutover productivo.

## HIGH residual (1E.4B)

QA adversarial dejó un HIGH tras GO de re-auditoría Luna:

W06 / W08 / W09 / W10 / W12 / W17 / W18 podían commitear una mutación
legacy si:

1. el writer comenzó bajo `PRE_CUTOVER`;
2. otra estación publicaba `CUTOVER_IN_PROGRESS`;
3. el writer continuaba después del check inicial
   (`assert_inventory_writes_allowed` / `resolve_writer_mode`);
4. hacía `conn.commit()` sobre `productos.stock`.

W01 / W03 / W13 / W16 ya usaban `commit_legacy_inventory()` +
`lock_legacy_cutover_fence()`. Ese patrón es el certificado. Esta fase
lo extiende al resto de writers productivos que aún mutan stock
legacy.

`assert_inventory_writes_allowed()` por sí solo **no** es un fence.
El patrón prohibido es: check de estado → `UPDATE productos.stock` →
`conn.commit()`.

## Primitive

La misma de 1E.4B:

- `commit_legacy_inventory(sqlite_conn, connection_factory=...)`
- `legacy_write_fence()` → `lock_legacy_cutover_fence()` (`SECURITY DEFINER`,
  `FOR SHARE`)
- freeze: `SELECT … FOR UPDATE` + CAS a `CUTOVER_IN_PROGRESS`

Caso A — writer toma el fence primero: puede completar el commit
legacy; el freeze espera.

Caso B — freeze publica primero: el writer no commitea stock; falla
cerrado (`InventoryFrozenError`) y hace rollback.

No hay tercera posibilidad. No se copió locking arbitrario dentro de
cada writer.

## Writers afectados

| ID | Función | Fence |
|---|---|---|
| W06 | `VentasService.agregar_productos_a_factura` | siempre (mutación de stock) |
| W08 | `ProductosRepository.actualizar_producto` | solo si `stock` cambia. El UPDATE de metadata (nombre/precio/código) **no** escribe `productos.stock`. El SET de stock es un UPDATE aparte, bajo el fence. |
| W09 | `ProductosRepository.crear_producto` | INSERT nace con stock 0 (alta de SKU, no mutación de inventario). Si stock inicial ≠ 0, un UPDATE de stock aparte va bajo el fence. |
| W10 | `MovimientosService.registrar_movimiento` | siempre |
| W12 | `InventarioRepository.registrar_movimiento` | siempre |
| W17 | `VentasService.editar_linea_factura` | solo si `dif_cant != 0` |
| W18 | `VentasService.eliminar_linea_factura` | siempre |

También se cableó la misma primitive en writers sin caller de UI que
aún pueden mutar stock (0 bypass de flota): W02, W04, W05, W07, W11,
W14. W15 (deprecated, sin caller; la UI usa W03) también queda
fenced si alguien lo invoca.

En AUTHORITATIVE no hay SQL legacy de stock ni dual-write. No se
cambió el comportamiento authoritative ya certificado.

## Tests de carrera

Deterministas, sin `sleep` como única coordinación. Barreras:

- freeze-wins: `set_after_legacy_allow_hook` (writer observó
  PRE_CUTOVER, pausa antes del fence real) → otra conexión publica
  `CUTOVER_IN_PROGRESS` → el writer intenta commit → **no** hay
  mutación de stock.
- writer-wins (muestra W06/W08/W10): `set_after_legacy_share_hook`
  (FOR SHARE tomado) → freeze espera → la operación queda visible
  para reconciliación.

Cada clase freeze-wins y cada muestra writer-wins se repite 5 veces.

## Scanner

Búsqueda independiente de:

- `UPDATE productos SET stock`
- `INSERT INTO productos ... stock`
- `stock = stock +` / `stock = stock -`
- `conn.commit()`

W01–W18 inventariados. Todo writer legacy activo que muta stock:
**FENCED** o **DEPRECATED/NO CALLER**. UI (`dashboard_ui`,
`ventas_ui_modern`, etc.) no hace `commit` de stock directo; W17/W18
solo llaman al servicio. 0 BYPASS.

## STOP

**STOP — no declarar FASE 1 COMPLETA.** Pendiente re-auditoría Luna.
No cutover en Supabase real. No Fase 2.
