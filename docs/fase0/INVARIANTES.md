# Invariantes — deseado vs código actual

Cada invariante tiene un test en `tests/fase0/`.

- **CAR** = caracterización: el test **pasa** porque demuestra la violación.
- **XFAIL** = contrato: el test **falla hoy** (`unittest.expectedFailure`).
  Un XPASS es una alarma.

| ID | Invariante deseado | Hoy | Test |
|---|---|---|---|
| INV-01 | Dos dispositivos no confirman ambos el último stock | Dos SQLite con stock=50 venden 50 cada una; ambas aprueban | CAR `test_carrera_dos_sqlite_venden_el_ultimo_stock` + XFAIL `test_contrato_coordinador_inventario_existe`. El xfail `test_contrato_unicidad_global_ultimo_stock` es un **centinela local** (`applied==1` sobre el mismo UPDATE); hay que reescribirlo cuando exista el coordinador. |
| INV-02 | `productos.stock` no es snapshot LWW autoritativo | `enqueue_entity` + UPSERT `stock=EXCLUDED.stock` pisan valores | CAR `test_snapshot_lww_pisa_stock` + XFAIL `test_contrato_payload_productos_sin_stock_autoritativo` |
| INV-03 | Un solo writer de ingreso por factura de proveedor | `crear_compra`, `MovimientosService` y `InventarioRepository` incrementan con `ENTRADA_COMPRA` | CAR `test_tres_caminos_entrada_compra` + XFAIL `test_contrato_entrada_compra_unica` |
| INV-04 | Extracción/borrador no muta stock | No hay tablas de recepción; las compras sí mutan | XFAIL `test_contrato_tablas_recepcion_existen` |
| INV-05 | Solo `cantidad_aceptada` entra a stock | `crear_compra` usa la cantidad del ítem sin dañada/faltante | XFAIL `test_contrato_cantidad_aceptada` |
| INV-06 | `operation_id` UNIQUE; retry no doble-cuenta | No existe tabla/ledger | XFAIL `test_contrato_ledger_operation_id` |
| INV-07 | Timeout post-commit recupera resultado | No hay recuperación por operation_id | XFAIL `test_contrato_retry_recupera_resultado` |
| INV-08 | Producto nuevo con ≥1 barcode; FRP- + 16 hex | Columna única; SKU con `id` local y 4 hex | XFAIL `test_contrato_frp_y_producto_codigos` |
| INV-09 | Varios barcodes por SKU; no reutilización | `productos.codigo_barras` UNIQUE de una columna | CAR `test_un_solo_codigo_barras` |
| INV-10 | Alias proveedor ≠ barcode | No hay modelo de alias | XFAIL junto a INV-08 |
| INV-11 | `device_id` UUID persistente ≠ hostname | **Identidad básica en Fase 1B:** `config/device_identity.json`. Sin fencing ni autoridad offline | PASS `test_contrato_device_identity` + `tests/fase1b` |
| INV-12 | Offline: solo la autoridad confirma | Cualquier PC muta stock local | XFAIL `test_contrato_offline_authority` |
| INV-13 | Outbox no traga errores en TX de inventario | `encolar()` absorbe excepciones | CAR `test_outbox_traga_excepciones` + XFAIL `test_contrato_outbox_propaga` |
| INV-14 | Tests oficiales no copian `ferreteria.db` | `tests/test_local_first_integration.py` hace `shutil.copy2` | CAR `test_legacy_integration_copia_ferreteria_db` + CAR harness no copia |
| INV-15 | DDL SQLite: `id` usable con `lastrowid` | **Resuelto en Fase 1A:** `INTEGER PRIMARY KEY` por motor; ver `schema_bootstrap.py` | PASS `test_integer_pk_asigna_id` + `test_contrato_integer_primary_key` + `tests/fase1a` |
| INV-16 | Factura única por proveedor normalizada | `compras.numero_factura` sin UNIQUE | XFAIL `test_contrato_factura_unica_por_proveedor` |
| INV-17 | Cantidades fixed-point | INTEGER + float + REAL mezclados | XFAIL `test_contrato_fixed_point` |
| INV-18 | Registries de sync coherentes | **Resuelto en Fase 1B:** `sync_registry.SYNC_REGISTRY` es la fuente única; las listas se derivan | PASS `test_registries_divergen` + `tests/fase1b` |
| INV-19 | Writers de stock conocidos | Ver `STOCK_WRITERS.md` | CAR `test_scanner_coincide_con_inventario` |
| INV-20 | Esquema oficial SQLite usable por `crear_compra` | **Resuelto en Fase 1A:** columnas de pago se crean/migran de verdad | PASS `test_crear_compra_en_esquema_oficial` + `tests/fase1a` |

## Fencing (ADR-0003) — aún no testeable en runtime

La identidad persistente (`device_identity.json`) existe desde Fase 1B.
No hay lease ni epoch. El XFAIL de INV-12 afirma la ausencia de
`OFFLINE_INVENTORY_AUTHORITY`. No se implementa fencing en 1B.
