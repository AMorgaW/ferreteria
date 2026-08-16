# Fase 2D — importación controlada de inventario físico

## Alcance

Fase 2D implementa exclusivamente la primera etapa:

`XLSX → validación → preview → staging durable → matching → dry-run`

No existe una operación de APPLY en el servicio ni en la UI. Importar o abrir
un batch no crea productos, no modifica `productos.stock`, no crea balances y
no inserta en `product_barcodes`.

## Componentes

- `product_inventory_contract.py`: encabezados y catálogos canónicos.
- `inventory_excel_importer.py`: seguridad, lectura, normalización, Decimal,
  validación, row hash y DTOs; no depende de Qt ni de base de datos.
- `inventory_import_schema.py`: tablas locales de staging.
- `repositories/inventory_import_repository.py`: SQL del staging y lecturas de
  autoridad; no contiene métodos productivos de APPLY.
- `services/inventory_import_service.py`: matching, plan y dry-run.
- `ui/inventory_import_ui.py`: selección, resumen, filtros y preview.

## Garantías

- SHA-256 único por batch; el mismo archivo reutiliza el staging existente.
- Inserción del batch y todas sus filas en una sola transacción.
- Hash canónico por fila, sin UUIDs aleatorios.
- Cantidades con `Decimal`, máximo tres decimales y escala 1000 aplicada una vez.
- Barcode Excel vacío = `BARCODE_PENDING`; doble valor coincidente =
  `BARCODE_EXCEL_CANDIDATE`, nunca VERIFIED.
- Fuzzy matching solo genera `MATCH_CANDIDATE` y requiere revisión humana.
- Un XLSX malformado falla antes de persistir staging.

## Migración

`20260815_004 inventory_import_staging` crea
`inventory_import_batches`, `inventory_import_rows` e índices locales. Es
transaccional, tiene checksum y es idempotente. No se aplica automáticamente a
la base real durante el desarrollo de esta fase.

## Estado

Fase 2D prepara el plan de aplicación, pero Fase 2E será responsable de la
aprobación y ejecución controlada. No adelantar Fase 2E.
