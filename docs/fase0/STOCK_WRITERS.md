# Writers actuales de `productos.stock`

Inventario estático de Fase 0. La lista canónica ejecutable está en
`tests/fase0/stock_writers.py`. El test `test_stock_writers.py` falla
si aparece un `UPDATE productos … stock` que no esté listado.

**Ninguna de estas rutas es la autoridad futura.** Todas mutan la
proyección local y (casi todas) encolan un snapshot LWW.

## UPDATE / SET stock

| # | Archivo | Función | Forma SQL | Kardex | Notas |
|---|---|---|---|---|---|
| 1 | `repositories/compras_repo.py` | `ComprasRepository.crear_compra` | `stock = stock + ?` | `movimientos.ENTRADA_COMPRA` | Incremento directo. Encola fila `productos`. |
| 2 | `repositories/compras_repo.py` | `ComprasRepository.eliminar_compra` | `stock = stock - ?` | reversa en `movimientos` | Sin piso `stock >=`. Código con cero llamadores de UI. |
| 3 | `services/ventas_service.py` | crear venta | `stock = stock - ? WHERE stock >= ?` | `SALIDA_VENTA` | Guard local; no serializa dos SQLite. |
| 4 | `services/ventas_service.py` | cancelar venta | `stock = stock + ?` | `ENTRADA_DEVOLUCION` | |
| 5 | `services/ventas_service.py` | devolución | `stock = stock + ?` | `ENTRADA_DEVOLUCION` | `devoluciones` está fuera de `SYNC_TABLES`. |
| 6 | `services/ventas_service.py` | `agregar_productos_a_factura` | `stock = stock - ?` **sin** `stock >=` | `SALIDA_VENTA` | Puede ir negativo. |
| 7 | `repositories/productos_repo.py` | `actualizar_stock` | `SET stock = ?` (calculado) | ninguno | Writer genérico sumar/restar. |
| 7b | `repositories/productos_repo.py` | `actualizar_producto` | `SET … stock = ?` (valor de ficha) | ninguno | Editar producto publica snapshot LWW del stock. |
| 8 | `services/movimientos_service.py` | `registrar_movimiento` | `SET stock = ?` | `movimientos` | Incluye `ENTRADA_COMPRA`. |
| 9 | `services/movimientos_service.py` | anular movimiento | `SET stock = ?` | observa anulación | |
| 10 | `repositories/inventario_repository.py` | `registrar_movimiento` | `SET stock = ?` | `movimientos_inventario` | Segundo kardex. Incluye `ENTRADA_COMPRA`. |
| 11 | `repositories/inventario_repository.py` | ajustar stock | `SET stock = ?` | `movimientos_inventario` | |
| 12 | `repositories/inventario_repository.py` | `eliminar_movimiento` | `SET stock = ?` | borra `movimientos_inventario` | |
| 13 | `services/mezclas_service.py` | descontar componentes | `stock = stock - ?` **sin** guard | `SALIDA_VENTA` (tipo reutilizado) | |
| 14 | `local_server.py` | `create_sale` | `stock = stock - ?` **sin** `stock >=` | `SALIDA_VENTA` | POS LAN. |
| 15 | `ui/dashboard_ui.py` | editar línea de factura | `stock = stock - ?` | no necesariamente | Writer en UI. |
| 16 | `ui/dashboard_ui.py` | quitar línea de factura | `stock = stock + ?` | DELETE `movimientos` | Writer en UI. |

## Escritura de stock sin UPDATE (insert de producto)

| # | Archivo | Función | Notas |
|---|---|---|---|
| 17 | `repositories/productos_repo.py` | `crear_producto` | `INSERT` con `producto.stock`. Si stock > 0 escribe `movimientos.ENTRADA_AJUSTE`. Viola “producto nuevo nace en 0” para el flujo de recepción futuro. |

## Sync que puede **pisar** stock sin vender

| # | Archivo | Función | Notas |
|---|---|---|---|
| 18 | `local_first_db.py` | `enqueue_entity` | Payload = `SELECT *` de `productos` (incluye `stock`). |
| 19 | `local_sync.py` | `_upsert` (push) | `ON CONFLICT (local_id) DO UPDATE SET … stock=EXCLUDED.stock`. |
| 20 | `local_sync.py` | `pull_from_remote` | Mismo patrón LWW sobre SQLite local. |

## UI que ofrece `ENTRADA_COMPRA` (dispara writers 8 o 10)

- `ui/movimientos_ui.py` — alta con tipo `ENTRADA_COMPRA`.
- `ui/entrada_inventario_ui.py` — combo incluye `ENTRADA_COMPRA`.

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

`formulas_mezcla`, `formula_detalle`, `devoluciones` están fuera de sync
(`NON_SYNC_TABLES`). `productos.stock` está declarado como proyección /
`authoritative_exclude`, pero `APPLY_AUTHORITATIVE_EXCLUDE = False`: el UPSERT
LWW de stock **sigue vigente** (INV-02 xfail).
