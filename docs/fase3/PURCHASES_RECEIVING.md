# Contrato compras / recepción (Fase 3B)

## Proveedores

Se reutiliza `proveedores` + `ProveedoresRepository`. El proveedor es obligatorio en el borrador y en la confirmación. No hay CRUD nuevo.

## Compra vs recepción

El documento vive en `compras` / `detalle_compras` (sin tabla paralela de recepción).

| Estado | Stock | Editable |
| --- | --- | --- |
| `DRAFT` | no | sí (si no hay `inventory_command_id` en vuelo) |
| `COMPLETADA` | sí, una vez | no; corrección = operación posterior |
| `CANCELADA` | camino W02 existente | no en 3B |

Crear/editar DRAFT no llama al coordinador. Solo **CONFIRMAR RECEPCIÓN** aplica inventario.

`CONFIRMED/RECEIVING` no se persiste: la confirmación es atómica (en vuelo el botón queda deshabilitado).

## Packaging conversion

Módulo canónico: `packaging_conversion.py` (POS 3A y compras 3B).

| Presentación | Factor |
| --- | --- |
| `BASE_UNIT` | 1 |
| `FULL_PACKAGE` | `get_base_units_per_package`: cantidad de **unidad base por empaque** (CAJA, SACO, ROLLO, BULTO, …). Storage legado `unidades_por_caja`. Requiere flag de venta/recepción por empaque. Si falta: `BLOCKED_BY_PACKAGING_CONVERSION_CONTRACT` |
| `CUSTOM_PRESENTATION` | un único `factor` en `unidades_venta_custom`. 0 o >1 factores: BLOCKED |
| `HALF_PACKAGE` | `factor_canónico / 2` si `vende_medio_empaque` y el resultado es representable (enteros o escala 1000). `unidades_por_media_caja` legado solo se valida; no es autoridad |

No se adivina por nombre, no se parsea "caja x12", no se supone 6/12/24. No hay stock separado por presentación: el empaque convierte a unidad base del mismo `inventory_balance`.

## Cantidades y dinero

Cantidad > 0. Decimales solo si `permite_decimales`. Escala fija 1000 del ledger. Totales en `Decimal`. Costo de línea >= 0. Subtotal = cantidad de presentación × costo unitario documental.

## Inventory authority

ONLINE: `inventory_balances` PostgreSQL. Writer: `tipo=COMPRA`, `build_positive_operations`, `command_id` durable (`ACT_KIND_PURCHASE_CREATE` + `local_id` del documento). No se usa `UPDATE productos SET stock` como autoridad.

## Atomicidad

Un command con N operations. Si el preflight o el coordinador rechaza, el documento no pasa a `COMPLETADA` y no queda incremento parcial.

## Idempotencia y recovery

El `command_id` se persiste en `compras.inventory_command_id` **antes** del RPC. Retry / respuesta perdida reanuda el mismo id. APPLIED + documento local `COMPLETADA` = un incremento. UNKNOWN: el DRAFT conserva el id; no se crea otra recepción.

## Concurrencia

Dos estaciones, dos `command_id` distintos, mismo SKU: ambos incrementos válidos se serializan en el coordinador. Laboratorio: `ferrepro-pg-test` / `localhost:55432`.

## Local-first / offline

La UI de Compras abre desde SQLite. Proveedor, producto y DRAFT son locales. CONFIRMAR con estación OFFLINE + modo AUTHORITATIVE sin gateway/factory: bloqueado (`receipt_finalize_allowed`). No hay autoridad offline multi-estación.

`CONFIRMAR RECEPCIÓN` corre fuera del hilo GUI (`FunctionWorker`).

## Supplier aliases

Tabla `supplier_product_aliases (proveedor_id, producto_local_id, alias_codigo)`. UNIQUE por proveedor+alias. Lookup de recepción puede resolver alias; nunca lo inserta en `product_barcodes`. Sync remoto de aliases queda fuera de 3B.

## Producto nuevo

El formulario de compra selecciona productos existentes (búsqueda/barcode). No crea automáticamente un producto incompleto ni genera FRP.

## Inventario comercial

Diferido. Tests no usan `ferreteria.db` ni Supabase real.
