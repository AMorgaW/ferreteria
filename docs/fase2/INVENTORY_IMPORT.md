# Contrato de importación XLSX

## Encabezados e identidad

El workbook operacional contiene una fila por producto y los 18 encabezados
humanos definidos en `OPERATIONAL_INVENTORY_FIELDS`. El orden puede cambiar.
Las columnas adicionales se ignoran y reportan como WARNING; si falta un
encabezado requerido se rechaza el archivo completo.

No se solicitan IDs técnicos. `row_id` y `batch_id` son UUID internos de
staging; el `local_id` de un producto nuevo no se genera hasta una futura
aprobación.

## Seguridad

- Solo `.xlsx`, máximo 20 MiB y 10.000 filas con contenido.
- Límite descomprimido y relación de compresión contra zip-bomb.
- No se admiten macros.
- `keep_links=False` y `data_only=True`: no se ejecutan fórmulas ni vínculos.
- Longitud acotada de strings y snapshots JSON del origen.
- Validación completa antes de iniciar la transacción de staging.

## Cantidades y empaques

La cantidad se recalcula como:

`empaques completos × cantidad base por empaque + unidades sueltas`

El total Excel solo comprueba el cálculo; una diferencia produce
`ERROR_COUNT_MISMATCH`.

`SIN EMPAQUE` acepta cantidad por empaque vacía o 1, exige cero empaques
completos y usa unidades sueltas. El DTO conserva `Decimal('40')`; el staging
guarda `40000` únicamente en `cantidad_contada_scaled`.

Medio empaque es `cantidad_base_por_empaque / 2`. Si queda fraccionario y el
producto no admite decimales se emite `REVIEW_HALF_PACKAGE_FRACTION`; nunca se
redondea.

## Precios, catálogos y barcode

Compra debe ser `>= 0`; venta `> 0` y `>= compra`. Las celdas monetarias se
convierten a Decimal.

Categorías, unidades o presentaciones nuevas no se crean: se marcan para
revisión.

- Ambos barcodes vacíos: `BARCODE_PENDING`.
- Ambos idénticos: `BARCODE_EXCEL_CANDIDATE`.
- Diferentes o incompletos: ERROR.

Los ceros iniciales se conservan. Un candidato puede encontrar un barcode ya
persistido, pero nunca provoca INSERT en `product_barcodes`.

## Duplicados e idempotencia

Se marcan sin eliminar ni sumar: mismo row hash, mismo barcode candidate o
misma identidad fuerte. El SHA-256 del archivo es UNIQUE por batch: un archivo
modificado crea otro batch; uno idéntico reutiliza el anterior.
