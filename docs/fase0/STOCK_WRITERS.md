# Writers actuales de `productos.stock`

Re-inventario **Fase 1E.0** (verificado contra código). Writers negativos **preparados en 1E.1**; positivos y mixtos **preparados
en 1E.2** (código listo). 1E.3 implementa el cutover único en laboratorio. 1E.4 endurece el control
de flota PostgreSQL, fail-closed y snapshot reconciliado. Ver [FASE1E4.md](FASE1E4.md).
La lista canónica ejecutable está en `tests/fase0/stock_writers.py`.
El scanner (`tests/fase0/test_stock_writers.py`, `tests/fase1e`,
`tests/fase1e2`, `tests/fase1e3`) falla si aparece un `UPDATE`/`INSERT` directo de
`productos.stock` que no esté listado, ahora a **nivel función + SQL**.
1E.4B cierra hallazgos Luna del freeze/identidad; ver [FASE1E4B.md](FASE1E4B.md).
1E.4C cierra el HIGH residual de freeze (fleet fence); ver [FASE1E4C.md](FASE1E4C.md).

El default de fuente sigue OFF (`INVENTORY_CUTOVER_ENABLED = False`).
La autoridad ONLINE se activa por estado persistente `AUTHORITATIVE`,
no por esa constante. `APPLY_AUTHORITATIVE_EXCLUDE` sigue `False` en
fuente; en AUTHORITATIVE el runtime excluye `productos.stock` del LWW.

**Ninguna de las rutas W01–W18 es autoridad ONLINE tras el cutover.**
`inventory_balances.quantity_scaled` es la autoridad. `productos.stock`
es proyección/caché (D05). Ver [FASE1E3.md](FASE1E3.md).

Clasificación:

- **NEGATIVO:** puede reducir stock
- **POSITIVO:** solo aumenta (o INSERT ≥ 0)
- **MIXTO:** puede sumar o restar
- **DERIVADO:** no debería ser autoridad; proyecta/cachea/sincroniza
- **UNKNOWN:** blocker; en 1E.0 hay **0**

No hay `CREATE TRIGGER` sobre `productos`. `scripts/` no mutan stock.
No hay importaciones masivas de stock.

## Conteos 1E.0

| Total | Negativos | Positivos | Mixtos | Derivados | Unknown |
|---|---|---|---|---|---|
| 23 | 5 | 5 | 8 | 5 | 0 |

Directos (W01–W18) = 18. Derivados (D01–D05) = 5.

## Writers directos

| ID | Archivo | Función | Tipo | Signo | TX | `productos.stock` | Movimiento | Outbox | Offline | Callers | Riesgo |
|---|---|---|---|---|---|---|---|---|---|---|---|
| W01 | `repositories/compras_repo.py` | `ComprasRepository.crear_compra` | POSITIVO | + | sí | `stock = stock + ?` | `movimientos.ENTRADA_COMPRA` | sí | sí | `ui/compras_ui.py` | Tercer camino de ingreso (INV-03). |
| W02 | `repositories/compras_repo.py` | `ComprasRepository.eliminar_compra` | NEGATIVO | − | sí | `stock = stock - ?` sin `stock>=` | `SALIDA_AJUSTE` (asiento nuevo) | sí | sí | *ninguno en UI* | 1E.1: preparado. Semántica = CANCELADA + AJUSTE compensatorio, no DELETE. Default legacy. |
| W03 | `services/ventas_service.py` | `VentasService.registrar_venta` | NEGATIVO | − | sí | `stock = stock - ? WHERE stock >= ?` | `SALIDA_VENTA` | sí | sí | `ui/ventas_ui_modern.py` | 1E.1: preparado. Un command VENTA multilínea. Default legacy. Mezclas descuentan por aquí. |
| W04 | `services/ventas_service.py` | `VentasService.cancelar_venta` | POSITIVO | + | sí | `stock = stock + ?` | `ENTRADA_DEVOLUCION` | sí | sí | *ninguno* | `ui/ventas_ui_modern.cancelar_venta` solo vacía el carrito. |
| W05 | `services/ventas_service.py` | `VentasService.registrar_devolucion` | POSITIVO | + | sí | `stock = stock + ?` | `ENTRADA_DEVOLUCION` | sí | sí | *ninguno en UI* | `devoluciones` fuera de SYNC. |
| W06 | `services/ventas_service.py` | `VentasService.agregar_productos_a_factura` | NEGATIVO | − | sí | `stock = stock - ?` **sin** `stock>=` | `SALIDA_VENTA` | sí | sí | `ventas_ui_modern`, `dashboard_ui` | 1E.1: preparado. Legacy puede ir negativo (no se “arregló”). Autoritativo: coordinador decide. |
| W07 | `repositories/productos_repo.py` | `ProductosRepository.actualizar_stock` | MIXTO | ± | sí | `SET stock = ?` | ninguno | sí | sí | *ninguno* | Sin kardex. Writer genérico. |
| W08 | `repositories/productos_repo.py` | `ProductosRepository.actualizar_producto` | MIXTO | ± (ficha) | sí | `SET stock = ?` | ninguno | sí | sí | `ui/productos_ui.py` | Editar ficha publica LWW de stock. |
| W09 | `repositories/productos_repo.py` | `ProductosRepository.crear_producto` | POSITIVO | + INSERT | sí | `INSERT … stock` | `ENTRADA_AJUSTE` si stock>0 | sí | sí | `ui/productos_ui.py` | SKU nuevo puede nacer con stock>0. |
| W10 | `services/movimientos_service.py` | `MovimientosService.registrar_movimiento` | MIXTO | ± | sí | `SET stock = ?` | `movimientos` | sí | sí | `ui/movimientos_ui.py` | Incluye `ENTRADA_COMPRA` (INV-03). |
| W11 | `services/movimientos_service.py` | `MovimientosService.anular_movimiento` | MIXTO | ± inverso | sí | `SET stock = ?` | marca `[ANULADO]` | sí | sí | *ninguno en UI* | Piso `<0` en Python. |
| W12 | `repositories/inventario_repository.py` | `InventarioRepository.registrar_movimiento` | MIXTO | ± | sí | `SET stock = ?` | `movimientos_inventario` | sí | sí | `ui/entrada_inventario_ui.py` | Segundo kardex; incluye `ENTRADA_COMPRA`. |
| W13 | `repositories/inventario_repository.py` | `InventarioRepository.ajustar_stock_directo` | MIXTO | ± | sí | `SET stock = ?` | `movimientos_inventario` ajuste | sí | sí | *ninguno en UI* | Pisa a un entero arbitrario. |
| W14 | `repositories/inventario_repository.py` | `InventarioRepository.eliminar_movimiento` | MIXTO | ± inverso | sí | `SET stock = ?` | DELETE `movimientos_inventario` | sí | sí | *ninguno en UI* | Piso `<0` en Python. |
| W15 | `services/mezclas_service.py` | `MezclasService.descontar_stock_mezcla` | NEGATIVO | − | sí | `stock = stock - ?` **sin** guard SQL | `SALIDA_VENTA` reutilizado | sí | sí | *ninguno* | 1E.1: DEPRECATED/DEAD + gateway. UI usa W03. No borrar. |
| W16 | `local_server.py` | `LocalFerreteriaAPI.create_sale` | NEGATIVO | − | sí | `stock = stock - ?` **sin** `stock>=` | `SALIDA_VENTA` | sí | sí | `local_api_client`, `remote_adapters` | 1E.1: preparado. Mismo contrato que W03. Default legacy. |
| W17 | `services/ventas_service.py` | `VentasService.editar_linea_factura` | MIXTO | ± `dif_cant` | sí | `stock = stock - ?` | no | no | sí | `dashboard_ui` | 1E.2: extraído de closure. Default legacy. |
| W18 | `services/ventas_service.py` | `VentasService.eliminar_linea_factura` | POSITIVO | + | sí | `stock = stock + ?` | DELETE `movimientos` | no | sí | `dashboard_ui` | 1E.2: extraído de closure. Default legacy. |

## Sync que puede **pisar** stock sin vender (DERIVADO)

| ID | Archivo | Función | Notas |
|---|---|---|---|
| D01 | `local_first_db.py` | `enqueue_entity` | Payload = `SELECT *` de `productos` (incluye `stock`). No hace `SET stock`. |
| D02 | `local_sync.py` | `_upsert` / `build_remote_upsert_sql` | Push: `ON CONFLICT (local_id) DO UPDATE SET … stock=EXCLUDED.stock`. |
| D03 | `local_sync.py` | `pull_from_remote` | Mismo patrón LWW sobre SQLite local. **Sí pisa** `productos.stock`. |
| D04 | `repositories/_outbox.py` | `encolar()` / `encolar_borrado()` | No muta stock. Traga excepciones (INV-13). |
| D05 | `inventory_cutover.py` | `project_local_stock` | Proyección post-APPLY desde `inventory_balances`. Caché reconstruible, no autoridad. En AUTHORITATIVE no viaja por LWW. |

## UI que dispara writers (no UPDATE directo)

- `ui/movimientos_ui.py` — alta con tipo `ENTRADA_COMPRA` → W10
- `ui/entrada_inventario_ui.py` — combo incluye `ENTRADA_COMPRA` → W12
- `ui/productos_ui.py` — `stock=stock_total` al crear/editar → W09 / W08

## Hallazgos de callers (1E.0)

Métodos **sin caller de UI/producción** (siguen siendo writers; no se borran):

- W02 `eliminar_compra`
- W04 `VentasService.cancelar_venta` (el botón “cancelar” de POS vacía el carrito)
- W05 `registrar_devolucion`
- W07 `actualizar_stock`
- W11 `anular_movimiento`
- W13 `ajustar_stock_directo`
- W14 `eliminar_movimiento`
- W15 `descontar_stock_mezcla` (la venta de mezcla usa W03)

## Dual authority — cómo se evita en 1E.2

W01–W18 tienen código autoritativo **inyectable**, no activado.
El default es legacy. No hay dual-write (APPLY + `UPDATE productos.stock`
independiente) en el camino autoritativo. Cutover OFF. La activación
sigue siendo un **cutover único** (1E.3 laboratorio).

Commands `LEGACY_OBSERVED` no pueden aplicarse tras el seed.
No hay replay de backlog.

Tras APPLIED en AUTHORITATIVE, `productos.stock` es proyección/caché
reconstruible (D05 `project_local_stock`). No es segunda autoridad.

## Outbox

`repositories/_outbox.py` `encolar()` / `encolar_borrado()` capturan
cualquier excepción y hacen `print`. Un fallo de cola **no** aborta la
TX de stock.

## Registries de sync (no writers, pero el contrato futuro depende de ellos)

| Lista | Archivo | Rol |
|---|---|---|
| `SYNC_REGISTRY` | `sync_registry.py` | **Fuente canónica (Fase 1B).** Tablas, FKs, push/pull, entity_type, pk, proyecciones. |
| `SYNC_TABLES` | `local_first_db.py` | Derivado: `sync_tables()`. Schema local_id + pull. |
| `SYNCED_TABLES` | `local_sync.py` | Derivado: `synced_tables()`. Backfill/push. Incluye `configuracion` y `pagos_cuentas`. |
| `FK_MAP` | `local_sync.py` | Derivado: `fk_map()`. Traducción FKs. |
| `TOPO_ORDER` | `local_sync.py` | Derivado: `topo_order()`. Orden de pull **usado**. |
| `PULL_ORDER` | `local_sync.py` | Alias de `TOPO_ORDER`. Ya no es lista independiente. |
| `COORDINATOR_REMOTE_TABLES` | `sync_registry.py` | `inventory_balances` y tablas de init. **No LWW. No SYNC_REGISTRY.** |

`formulas_mezcla`, `formula_detalle`, `devoluciones` están fuera de sync
(`NON_SYNC_TABLES`). `productos.stock` está declarado como proyección /
`authoritative_exclude`. `APPLY_AUTHORITATIVE_EXCLUDE` sigue `False` en
fuente: PRE_CUTOVER conserva UPSERT LWW (INV-02 xfail default). En
AUTHORITATIVE el runtime excluye `stock` de push/pull LWW.
