# Contrato real de creación de producto

## Fuentes

- `models.Producto.validar`;
- `ProductosRepository.crear_producto`, `actualizar_producto` y anti-duplicado;
- formulario `ProductosUI.abrir_formulario/guardar_producto`;
- tabla SQLite `productos`, `schema_bootstrap` y `sync_registry`;
- tests de productos Fase 1A/1B/1E.

No existen en el flujo moderno campos de subcategoría, referencia/modelo o
descuento de producto. `precio_mayorista` y `stock_maximo` son columnas legacy
sin input/caller actual y no se convirtieron en requisitos.

## Capas de obligatoriedad

El repository exige nombre, precio de venta positivo, costo no negativo,
venta no inferior al costo, stock/stock mínimo no negativos y empaque válido.
El formulario marca además categoría, precio de compra, unidad y stock mínimo
como obligatorios, aunque varios tengan default. El workbook conserva esa capa
UI para no volver a pedir datos al importar. `cantidad_contada` es obligatoria
para cerrar el inventario físico, no es metadata del producto.

## Matriz contractual de captura

| Campo / Excel | Columna DB | Tipo | Required | Optional | Generated | User input | Default | Validación | Barcode |
|---|---|---|---|---|---|---|---|---|---|
| registro_inventario_id | — | UUID | No | No | Sí | No | UUIDv5 | único/estable | No |
| tipo_registro | — | ENUM | No | No | Sí | No | NUEVO/EXISTENTE | enum | No |
| activo_sistema | activo | ENUM | No | No | Sí | No | ACTIVO | referencia | No |
| producto_id_sistema | id | INTEGER | No | Sí | Sí | No | vacío nuevo | técnico | No |
| producto_local_id | local_id | UUID | No | Sí | Sí | No | vacío nuevo | UUID existente | No |
| codigo_sistema_actual | codigo_barras | TEXT | No | Sí | Sí | No | existente | no presume scan | Sí, referencia |
| nombre | nombre | TEXT | **Sí** | No | No | Sí | — | no vacío, <=150 | No |
| categoria | categoria | TEXT | **Sí** | No | No | Sí | — | CATALOGOS | No |
| marca | marca | TEXT | No | Sí | No | Sí | vacío | catálogo abierto | No |
| presentacion | presentacion | TEXT | No | Sí | No | Sí | vacío | distingue variantes | No |
| proveedor | proveedor_id | TEXT→FK | No | Sí | No | Sí | vacío | catálogo/resolución | No |
| proveedor_id | proveedor_id | INTEGER | No | Sí | Sí | No | existente | técnico | No |
| precio_compra | precio_compra | DECIMAL | **Sí** | No | No | Sí | UI 0 | >=0 | No |
| precio_venta | precio_venta | DECIMAL | **Sí** | No | No | Sí | — | >0 y >= costo | No |
| stock_minimo | stock_minimo | INTEGER | **Sí** | No | No | Sí | 10 | entero >=0 | No |
| unidad_medida | unidad_medida | ENUM | **Sí** | No | No | Sí | UNIDAD | CATALOGOS | No |
| permite_decimales | permite_decimales | BOOLEAN | No | Sí | No | Sí | NO | SI/NO | No |
| viene_en_caja | viene_en_caja | BOOLEAN | No | Sí | No | Sí | NO | SI/NO | No |
| unidades_por_caja | unidades_por_caja | INTEGER | Condicional | Sí | No | Sí | 1 | >=1 si caja | No |
| vende_por_empaque | vende_por_empaque | BOOLEAN | No | Sí | No | Sí | NO | SI/NO | No |
| ubicacion | ubicacion | TEXT | No | Sí | No | Sí | vacío | libre | No |
| descripcion | descripcion | TEXT | No | Sí | No | Sí | vacío | libre | No |
| stock_sistema_actual | stock | DECIMAL | No | Sí | Sí | No | existente | solo referencia | No |
| cantidad_contada | — | DECIMAL | **Sí** | No | No | Sí | vacío | >=0, escala x1000 | No |
| pasillo / estante | — | TEXT | No | Sí | No | Sí | vacío | staging | No |
| cálculos de valor/margen/diferencia | — | FORMULA | No | No | Sí | No | fórmula | informativo | No |
| codigo_barras | codigo_barras futuro | TEXT | No | Sí | No | Sí/scan | vacío | único si lleno | **Sí** |
| estado_barcode | — | ENUM | No | No | No | Sí/scan | PENDIENTE | PENDIENTE/ESCANEADO | **Sí** |
| estado_registro / errores / duplicado | — | FORMULA | No | No | Sí | No | fórmula | contrato canónico | Sí |
| observaciones_inventario | — | TEXT | No | Sí | No | Sí | vacío | staging | No |

La hoja `MAPEO_FERREPRO` contiene además campos no capturados:
`unidades_por_media_caja` derivado, IVA=0 según UI, timestamps/activo/sync
generados y columnas legacy sin caller.

## Duplicado potencial

El contrato productivo compara nombre + marca + presentación + unidad. El
validador reproduce esa llave y añade barcode duplicado. Nunca fusiona filas;
marca `REVISAR_POSIBLE_DUPLICADO`.

## Barcode desde Fase 2C

Los códigos físicos viven en `product_barcodes`; `productos.codigo_barras`
queda como referencia legacy y no almacena el nuevo conjunto multi-barcode.
El formulario normal crea con política `FINAL` y exige doble scan o FRP
explícito. El staging usa `BARCODE_PENDING`; los existentes sin código siguen
accesibles como `BARCODE_MISSING_LEGACY`. Véase [BARCODES.md](BARCODES.md).
