# Fase 2B — catálogo maestro e inventario físico Excel

**Estado:** COMPLETADA — GO INVENTARIO FÍSICO.

## Resultado

Se derivó el contrato real desde `models.Producto`,
`ProductosRepository.crear_producto/actualizar_producto`, `ProductosUI`, DDL,
bootstrap, sync y tests. El contrato quedó centralizado en
`product_inventory_contract.py` y es compartido por generador y validador.

El workbook operacional fue generado en:

`plantillas/FERREPRO_Inventario_Maestro.xlsx`

Contiene 141 productos existentes y 300 filas reservadas con identidad estable
para productos nuevos. `cantidad_contada` está vacía en todos los productos;
`stock_sistema_actual` se muestra únicamente como referencia.

## Gate operacional

- XLSX real y reabrible con openpyxl: PASS.
- Seis hojas obligatorias: PASS.
- Fórmulas y validaciones: PASS.
- Render visual de todas las hojas: PASS tras corregir dashboard y vista barcode.
- Errores de fórmula `#REF/#DIV0/#VALUE/#NAME/#N/A`: 0.
- SQLite from-db: `mode=ro` + `PRAGMA query_only`: PASS.
- SHA-256/tamaño/mtime de `ferreteria.db`: idénticos antes/después.
- Productos precargados: 141.
- Estado inicial: 141 INCOMPLETO solo por `cantidad_contada`; 0 REVISAR.
- Barcode staging generado: 0.

SHA-256 observado antes y después:

`B97D1A6B04F738163471F8CEEE89698312E840BB6F8938BCEEA8688E8838B0C0`

## Validación

Fase 2B: 24 PASS. Se cubrieron contrato, required fields, barcode opcional,
IDs estables, blank/from-db, no mutación, conteo vacío, fórmulas, precios,
cantidades fixed-point, duplicados, mapeo y estados.

## Alcance deliberadamente no implementado

- scanner DIG-X6266/HID;
- persistencia productiva de barcodes;
- generación productiva FRP/EAN;
- importación a SQLite/PostgreSQL;
- creación de productos o ajuste de stock;
- Supabase/cutover productivo;
- recepción XML/PDF/OCR.

## Flujo autorizado

Inventario Excel completo → todos `LISTO_SIN_BARCODE` → fase de escaneo →
scan físico asociado por `registro_inventario_id` → `LISTO_COMPLETO` →
importación/alta controlada posterior.
