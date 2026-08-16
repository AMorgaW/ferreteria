# Modelo de barcodes FERREPRO

## Identidad y relación con inventario

`product_barcodes` representa códigos físicos escaneables. Su identidad global
es `local_id` UUID textual; `barcode` nunca es una PK técnica. Cada fila apunta
a `productos.local_id` mediante `producto_local_id`.

Un producto puede tener uno o muchos barcodes. Todos resuelven el mismo SKU y
el mismo `productos.stock`; la tabla no contiene cantidad ni balance. Un futuro
barcode de unidad y otro de caja pueden apuntar al mismo producto, pero la
conversión de presentación pertenece a otra capa y no se deduce en Fase 2C.

Campos:

| Campo | Contrato |
|---|---|
| `local_id` | UUID global, PK técnica |
| `producto_local_id` | FK global a `productos.local_id` |
| `barcode` | TEXT exacto, UNIQUE global y no reciclable |
| `barcode_type` | `MANUFACTURER`, `INTERNAL_FRP` o extensión futura |
| `source` | procedencia explícita (`HID_DOUBLE_SCAN`, `EXPLICIT_FRP`) |
| `is_primary` | preferido del SKU; no invalida secundarios |
| `active` | disponibilidad actual; desactivar no libera UNIQUE |
| timestamps/sync | auditoría y sincronización canónica |

Existe como máximo un PRIMARY activo por producto. Cualquier barcode activo,
principal o secundario, es escaneable.

## Comparación

El valor permanece TEXT. Se eliminan CR, LF/ENTER y espacios o tabuladores
accidentales exteriores. No se usa `int`, `float`, `lower()` ni transformación
interna. Por ello `0012345678905` conserva sus ceros y `AbC-19` no equivale a
`abc-19`.

No se rechaza un código manufacturer solo por no reconocer EAN/UPC/CODE128. La
simbología puede incorporarse después como metadata sin cambiar el valor.

## Unicidad

SQLite y PostgreSQL imponen UNIQUE sobre el texto completo, incluyendo
históricos inactivos. Si pertenece a otro SKU se devuelve
`Código ya asignado a: <producto>` y no se reasigna.

PostgreSQL es el árbitro central de concurrencia. Un precheck de aplicación es
solo amigable; la restricción de DB decide la carrera real.

## FRP interno

Formato cerrado:

```text
FRP-XXXXXXXXXXXXXXXX
```

`XXXXXXXXXXXXXXXX` son 16 hexadecimales uppercase producidos mediante
`secrets.token_hex(8).upper()`. No deriva de ID, fecha, nombre ni secuencia. El
generador consulta históricos y reintenta hasta 10 veces; la UNIQUE protege la
carrera final. Al agotar intentos presenta un error visible.

FRP solo aparece tras una acción explícita y una confirmación explícita. No se
genera en migrations, startup, sync ni recorridos legacy. Si ya hay barcode de
fabricante, la generación interna se rechaza salvo override explícito futuro.

## Conceptos separados

Alias/código de proveedor no es barcode físico y nunca se promociona de forma
automática. Tampoco se confunde `productos.codigo_barras` histórico (usado por
builds anteriores como SKU) con el nuevo registro físico especializado.

## Lookup futuro

`ProductBarcodesRepository.lookup_product(barcode)` y
`ProductosRepository.obtener_por_codigo` resuelven cualquier barcode activo.
POS, compras e inventario pueden consumir ese contrato en fases posteriores
sin crear stocks por barcode.

