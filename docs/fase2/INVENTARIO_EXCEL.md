# Uso del inventario maestro Excel

## Archivo operacional

`plantillas/FERREPRO_Inventario_Maestro.xlsx`

Una fila representa un SKU/producto. Variantes de tamaño, medida o color deben
ser filas diferentes; múltiples barcodes del mismo SKU no deben duplicar stock.

## Hojas

1. `INSTRUCCIONES`: reglas breves y leyenda visual.
2. `PRODUCTOS`: fuente de verdad del staging y del conteo físico.
3. `CATALOGOS`: categorías, marcas, unidades y proveedores read-only de origen.
4. `RESUMEN`: indicadores formula-driven.
5. `MAPEO_FERREPRO`: contrato técnico para el futuro importador.
6. `BARCODES_PENDIENTES`: vista viva para la fase de escaneo posterior.

## Captura

- No cambiar encabezados.
- No borrar `registro_inventario_id`, IDs locales ni fórmulas.
- Escribir `cantidad_contada` en unidades base físicas.
- `stock_sistema_actual` nunca prellena ni sustituye el conteo.
- Precios y cantidades deben ser celdas numéricas.
- Cantidades admiten máximo tres decimales; si son fraccionarias,
  `permite_decimales` debe ser `SI`.
- Marca es catálogo abierto. Categoría y unidad se seleccionan de listas reales.
- Proveedor es opcional; uno nuevo queda para resolución antes de importar.
- Barcode puede permanecer vacío con estado `PENDIENTE`.

## Estado de fila

`INCOMPLETO`: falta nombre, categoría, precio de compra, precio de venta,
stock mínimo, unidad o cantidad contada.

`REVISAR`: existe un tipo/valor inválido, catálogo no resoluble, inconsistencia
barcode/estado o posible duplicado.

`LISTO_SIN_BARCODE`: todos los campos anteriores son válidos, no hay conflicto
y el barcode permanece vacío/PENDIENTE.

`LISTO_COMPLETO`: lo anterior más barcode no vacío y estado `ESCANEADO`.

## Productos existentes y nuevos

Los 141 existentes conservan `producto_id_sistema`, `producto_local_id` y
`codigo_sistema_actual`. Este último no se presume barcode físico porque el
código actual también puede ser un SKU autogenerado.

Las 300 filas `NUEVO` tienen `registro_inventario_id` estable. Su
`producto_local_id` queda vacío para generación controlada durante una futura
importación.

## Generación

```powershell
python scripts/generate_inventory_workbook.py --blank
python scripts/generate_inventory_workbook.py --from-db ferreteria.db
```

Opciones: `--output` y `--blank-rows`. El modo from-db usa SQLite read-only.

## Validación

```powershell
python scripts/validate_inventory_workbook.py plantillas/FERREPRO_Inventario_Maestro.xlsx
```

Puede emitir detalle con `--json reporte.json` o `--csv errores.csv`. No importa
ni modifica bases de datos o el workbook.

## Fase posterior

Excel completo → `LISTO_SIN_BARCODE` → operador selecciona físicamente el
producto → escanea DIG-X6266 → se asocia el código al
`registro_inventario_id`/producto → `LISTO_COMPLETO` → importación controlada.

El scanner y esa persistencia no forman parte de Fase 2B.
