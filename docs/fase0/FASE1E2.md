# Fase 1E.2 — Writers positivos y mixtos preparados, cutover OFF

**Estado:** implementada. Cutover **OFF** en 1E.2. 1E.3 (laboratorio) en
[FASE1E3.md](FASE1E3.md). **No autoriza 1E.4.**

## Qué es 1E.2

Preparó en código los **5 writers positivos** y **8 mixtos** para la
autoridad central futura, **sin activar cutover**. El default productivo
sigue siendo legacy: `productos.stock` es la ruta efectiva.

El camino autoritativo solo se activa con `inventory_mode="authoritative"`
más transport/factory inyectados (harness/tests). No se activa desde
JSON de UI/HTTP.

## Deudas de 1E.1 cerradas

### A. `intent_class` fail-closed

- CREATE TABLE y ALTER: `DEFAULT 'LEGACY_OBSERVED'`.
- `_normalize_intent_class(None/"")` → `LEGACY_OBSERVED`.
- Valor inválido → error.
- `AUTHORITATIVE` solo si el caller lo pide explícito.
- `command_is_transmittable` / `list_transmittable_command_ids`: ausencia,
  NULL, vacío o `LEGACY_OBSERVED` **no** transmiten.
- Dataclass `InventoryCommandRecord.intent_class` default local =
  `LEGACY_OBSERVED`.

No se convierten filas legacy observadas en `AUTHORITATIVE`. No hay replay
de backlog.

### B. Recovery post-APPLY W06 / W02 / W15

Si PostgreSQL deja `APPLIED` y el commit local falla:

- no segundo APPLY;
- mismo `command_id`;
- side effects locales (detalle/movimiento/estado) se completan con
  binding `[invcmd:{command_id}]` de forma idempotente.

W15 sigue DEPRECATED/DEAD; su camino autoritativo no es inseguro.

## Builders (`inventory_writer_support.py`)

Escala **1000**. Sin float autoritativo.

| Builder | Uso |
|---|---|
| `build_negative_operations` | 1E.1, deltas `< 0` |
| `build_positive_operations` | compras, devoluciones, restituciones |
| `build_signed_operations` | delta comercial firmado; omite delta 0 |
| `build_absolute_operations` | `SET stock = N`; `delta = target - base` + `expected_base_scaled` |

Delta total 0 → lista vacía = `NO_INVENTORY_CHANGE`. No se crea
`InventoryOperation` inválida. Los side effects no-stock (p. ej. cambiar
precio de línea) sí se aplican.

## Semántica de stock absoluto

`base_scaled` **no** sale de `productos.stock` en camino autoritativo.

1. Inyección de test: `inventory_stock_base_scaled`.
2. Producción futura: `resolve_authoritative_base_scaled` lee
   `inventory_balances` vía `fetch_inventory_balance`.
3. CAS en `apply_inventory_command`: si el JSON trae
   `expected_base_scaled`, el RPC compara bajo `FOR UPDATE`.
   Mismatch → `REJECTED` `STALE_BALANCE`.
4. El valor se persiste en SQLite `inventory_operations.expected_base_scaled`
   (nullable). **No** entra al `request_hash`. Un retry UNKNOWN reutiliza
   el payload original; no relée una base stale.

No hay workaround LWW (`SET stock = N` remoto).

## Writers positivos

| ID | Función | Tipo ledger | Notas |
|---|---|---|---|
| W01 | `ComprasRepository.crear_compra` | `COMPRA` + | Un command por compra, N operations. Bind `compras.local_id`. Sin `stock = stock +` en authoritative. |
| W04 | `VentasService.cancelar_venta` | `DEVOLUCION` + | **Sin caller de UI** (`ventas_ui_modern.cancelar_venta` vacía el carrito). No se borra. Preparado e idempotente. |
| W05 | `VentasService.registrar_devolucion` | `DEVOLUCION` + | Identidad = `command_id`. Retry APPLIED no duplica `devoluciones`. |
| W09 | `ProductosRepository.crear_producto` | `AJUSTE` + si stock>0 | Stock 0 → no command. `local_id` **antes** de `InventoryOperation`. INSERT local con `stock=0`. |
| W18 | `VentasService.eliminar_linea_factura` | `DEVOLUCION` + | Extraído de closure PySide. Dashboard solo llama al servicio. |

## Writers mixtos

| ID | Función | Semántica | Tipo ledger |
|---|---|---|---|
| W07 | `actualizar_stock` | **DELTA** (`sumar`/`restar`), no absoluto | `AJUSTE` ± |
| W08 | `actualizar_producto` | Metadata sin `SET stock`. Si cambia stock → AJUSTE absoluto + CAS | `AJUSTE` |
| W10 | `MovimientosService.registrar_movimiento` | Prefijos `ENTRADA`/`SALIDA` validados | `COMPRA`/`VENTA`/`AJUSTE`/`DEVOLUCION` |
| W11 | `anular_movimiento` | Delta inverso exacto. `[ANULADO]` idempotente | `AJUSTE` |
| W12 | `InventarioRepository.registrar_movimiento` | Mismo mapa que W10; kardex `movimientos_inventario` | igual que W10 |
| W13 | `ajustar_stock_directo` | SET absoluto → AJUSTE + CAS. Sin `SET stock` authoritative | `AJUSTE` |
| W14 | `eliminar_movimiento` | Reversión exacta + DELETE. Segunda vez no altera stock | `AJUSTE` |
| W17 | `VentasService.editar_linea_factura` | `delta = -(nueva - anterior)`. Extraído de closure | `AJUSTE` ± |

Mapeo W10/W12 (`movement_tipo_to_ledger`): no usa texto libre como
autoridad. `ENTRADA_COMPRA`→`COMPRA`+, `SALIDA_VENTA`→`VENTA`−,
`ENTRADA_DEVOLUCION`→`DEVOLUCION`+, resto `ENTRADA*`/`SALIDA*`→`AJUSTE`.

## Closures W17 / W18

Mutación extraída a `VentasService`. `ui/dashboard_ui.py` ya no contiene
`UPDATE productos SET stock`. El scanner apunta a archivo+método reales.

## Binding / recovery

Documento comercial: `command_id` ↔ `documento_local_id` vía
`bind_inventory_command_documento`.

Sin documento: marker `[invcmd:{id}]` en `motivo`/`observaciones`
(movimientos, kardex, anulaciones).

UNKNOWN conserva `command_id`, `request_hash`, payload, `operation_id`.
No es REJECTED. No es APPLIED. No crea un documento nuevo para reintentar.

REJECTED remoto: no documento SUCCESS, no movimiento completado, no
`productos.stock` autoritativo, no éxito HTTP/UI. Preserva motivo.

## No dual-write

Camino authoritative: PostgreSQL APPLY **sin** `UPDATE productos.stock`
como segunda autoridad. La proyección/caché (D05) se implementó en
laboratorio 1E.3; ver [FASE1E3.md](FASE1E3.md).

## Scanner

`GATEWAY_PREPARED_IDS = frozenset(DIRECT_WRITER_IDS)` (W01–W18).
W15 DEPRECATED (preparado). W04 preparado, sin UI.
0 `UNTRACKED_DIRECT_WRITER`. 0 unknown.

## Condiciones para 1E.3

Cerradas en laboratorio. Ver [FASE1E3.md](FASE1E3.md). El default de
fuente sigue `INVENTORY_CUTOVER_ENABLED = False`; la autoridad se lee
del estado persistente. **No autoriza 1E.4 ni cutover productivo.**

## STOP

**STOP — no implementar 1E.4 desde 1E.2.** El cutover de laboratorio está
en [FASE1E3.md](FASE1E3.md).
