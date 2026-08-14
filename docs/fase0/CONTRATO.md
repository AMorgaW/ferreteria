# Contrato arquitectónico — inventario distribuido, recepción, barcodes

Este documento es la fuente de verdad de **Fase 0**. Los ADRs detallan decisiones.
El código productivo **no** cumple este contrato hoy. Ver [INVARIANTES.md](INVARIANTES.md).

## 1. Autoridad de inventario

### Online

PostgreSQL/Supabase es la autoridad global. Toda confirmación de operación
de inventario (venta, compra/recepción, devolución, ajuste, mezcla) debe
pasar por una operación central **atómica e idempotente**.

Ejemplo obligatorio:

- stock global = 50
- venta A = 50 y venta B = 50 concurrentes
- resultado: A aprobada y B rechazada, o viceversa
- **nunca ambas**

Reducir el intervalo de sync (~45 s hoy) **no** resuelve la race:
cada PC tiene su propio SQLite y aprueba sin transacción compartida.

### Offline (v1)

Dos dispositivos aislados no pueden garantizar unicidad global.
v1 elige disponibilidad acotada, no milagro matemático:

- Una sola terminal estable, `OFFLINE_INVENTORY_AUTHORITY`, puede confirmar
  movimientos de inventario sin conectividad.
- Cualquier otra terminal **offline no confirma** stock. Puede consultar,
  armar borradores de recepción y preparar operaciones; la confirmación
  espera red (autoridad online) o se rechaza.
- El fencing está en [ADR-0003](ADR-0003-fencing-y-device-id.md).
  Sin fencing implementado **no** se habilita el modo autoridad.

### Proyección `productos.stock`

La columna puede seguir existiendo como **caché/proyección local**.
No es snapshot autoritativo last-write-wins publicado por cada dispositivo.

Hoy `enqueue_entity` serializa la fila completa de `productos` (incluye
`stock`) y el UPSERT remoto/local hace `stock=EXCLUDED.stock`. Eso permite
que un valor obsoleto pise stock más reciente. Eso viola este contrato.

## 2. Ledger mínimo

Contrato de operación (aún no existe en el esquema):

```text
InventoryOperation
  operation_id     UUID UNIQUE
  producto         identidad global (local_id de productos)
  delta            cantidad con signo, fixed-point
  tipo             VENTA | RECEPCION | DEVOLUCION | AJUSTE | MEZCLA | ...
  documento_origen tipo + identidad de negocio
  documento_local_id UUID del documento local
  device_id        UUID del dispositivo
  usuario          identidad del usuario
  timestamp        tiempo de la operación
  resultado        APPROVED | REJECTED | ...
  motivo_rechazo   opcional
```

Reglas:

- Retry con el mismo `operation_id` **no** aplica el delta dos veces.
  Devuelve el resultado original.
- Timeout después de commit: el retry **recupera** ese resultado; no crea
  una segunda operación.
- `productos.stock` se actualiza como proyección **después** (o dentro)
  de aplicar el ledger, nunca como fuente.

Detalle: [ADR-0002](ADR-0002-ledger-operaciones.md).

## 3. Recepción inteligente

Flujo:

```text
documento (XML | PDF texto | PDF escaneado | foto)
        → extractor (worker, fuera de TX de stock)
        → BORRADOR (recepcion_documentos + recepcion_lineas)
        → revisión humana (admin/gerente/bodeguero)
        → confirmación → operación de inventario (solo cantidad_aceptada)
```

Invariantes de recepción:

1. La extracción documental **jamás** modifica inventario.
2. Un administrador/gerente/bodeguero revisa producto, cantidad facturada,
   recibida, dañada, aceptada, faltantes, sobrantes, rechazados, pendientes.
3. Solo `cantidad_aceptada` puede ingresar al inventario.
4. OCR/IA propone; nunca aprueba ni crea SKU.
5. Producto nuevo desde recepción nace con **stock 0**. El ingreso posterior
   es la recepción confirmada.
6. `ENTRADA_COMPRA` manual (Movimientos / Entrada inventario) desaparece.
   Hoy hay al menos tres caminos; ver [STOCK_WRITERS.md](STOCK_WRITERS.md).
7. Líneas no inventariables: FLETE, DESCUENTO, SERVICIO, REDONDEO, IMPUESTO, OTRO.
8. Factura: número original + número normalizado. Unicidad por
   `(proveedor, numero_normalizado)` entre documentos no anulados.
9. PDF/XML no se sincronizan como BLOB. Metadatos + hash + ruta local de dispositivo.
10. Cancelación compleja de compras confirmadas: fuera de v1.

Detalle: [ADR-0004](ADR-0004-recepcion-sin-stock.md).

## 4. Códigos de barras

- Todo producto **nuevo** debe tener al menos un código escaneable.
- Si tiene barcode comercial: se escanea y se valida (UNIQUE global).
- Si no: FERREPRO genera interno:

```text
FRP- + secrets.token_hex(8).upper()
ejemplo: FRP-7A91D2E48BC3814F
```

- UNIQUE + retry limitado. Nunca consecutivos / max()+1 / id local / fecha / nombre.
- Un producto puede tener **varios** barcodes.
- Barcode identifica **SKU**, no unidad física. Dos cajas del mismo producto
  comparten SKU/stock aunque se escaneen códigos distintos asociados.
- Alias/código de proveedor ≠ barcode escaneable (concepto distinto, namespaced).
- Códigos históricos no se reutilizan (retiro lógico; UNIQUE sigue ocupado).
- Productos históricos sin barcode: regularización progresiva por herramienta
  administrativa. **No** generar FRP masivo en migración.
- Hoy existe `productos.codigo_barras TEXT UNIQUE` (una columna). No hay tabla
  de múltiples códigos.

Detalle: [ADR-0005](ADR-0005-barcodes-frp.md).

## 5. Cantidades

Hoy INTEGER en DDL de stock/cantidad de compra/movimiento, `float` en UI,
REAL en mezclas/devoluciones. Dual-engine SQLite/PostgreSQL no es uniforme.

Evolución: representación **fixed-point** (cuantización de dominio con
`Decimal`; escala 3 recomendada: `0.001`). No se aplica en Fase 0.

## 6. Identidad de dispositivo

`device_id` UUID estable, persistente, revocable.
La columna `device_id TEXT` que `ensure_local_first_schema` añade a
`SYNC_TABLES` es metadato de **última escritura de fila**, no identidad
del dispositivo. No reutilizarla como `OFFLINE_INVENTORY_AUTHORITY`.

## 7. Tests y esquema

- Harness: tempfile + `DatabaseManager.crear_estructura_completa` +
  `ensure_local_first_schema`. `DB_MODE=local`. Nunca `shutil.copy` de
  `ferreteria.db`.
- **Fase 1A:** el DDL SQLite usa `INTEGER PRIMARY KEY` (sustitución por motor;
  PostgreSQL conserva `SERIAL`). Las columnas que el código ya espera
  (`compras.estado_pago`, etc.) se añaden con helpers que consultan el
  catálogo, no con `ADD COLUMN IF NOT EXISTS` de Postgres tragado por
  `except`. Ver `schema_bootstrap.py`.
- Hallazgo histórico (Fase 0, ya cerrado en 1A): `id SERIAL PRIMARY KEY` en
  SQLite fresco dejaba `id` NULL; el ALTER PostgreSQL no aplicaba.
- Outbox: `_outbox.encolar()` absorbe excepciones. El contrato futuro
  exige que un fallo de cola aborte la TX de inventario.

## 8. Lo que Fase 0 no autoriza implementar

Coordinador central, tablas nuevas, FRP en productos, UI de recepción,
permiso `gestionar_recepcion`, quitar `ENTRADA_COMPRA` de la UI,
cambiar sync, cambiar ventas/compras.

Esperar autorización humana para Fase 1.
