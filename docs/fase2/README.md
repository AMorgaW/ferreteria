# Fase 2 — migración y saneamiento legacy

**Estado:** Fase 2A y Fase 2B completadas. Inventario físico autorizado;
importación y scanner pendientes.

Fase 2 comenzó después de cerrar técnicamente el gate de Fase 1. Su propósito
es hacer explícito el drift de esquema y calidad de datos, introducir
migraciones versionadas y preparar saneamientos seguros. No cambia la
autoridad ONLINE certificada de inventario.

## Entregables 2A

- `legacy_sanitation.py`: análisis de esquema, identidad, numéricos, facturas,
  movimientos y claves foráneas, sin escrituras.
- `scripts/report_legacy_sanitation.py`: reporte JSON y dry-run; rechaza aplicar
  sobre `ferreteria.db` salvo autorización humana explícita.
- `migration_runner.py`: runner SQLite versionado, idempotente, con checksum,
  savepoint, rollback visible y dry-run.
- [FASE2A.md](FASE2A.md): alcance, resultados y plan de Fase 2B.
- [SCHEMA_SANITATION.md](SCHEMA_SANITATION.md): matriz de drift y clasificación.
- `tests/fase2`: fixtures fresh/legacy, reejecución, rollback, identidad,
  duplicados, numéricos, drift y no mutación.
- [FASE2B.md](FASE2B.md): cierre de catálogo maestro e inventario físico.
- [PRODUCT_CONTRACT.md](PRODUCT_CONTRACT.md): contrato real de creación.
- [INVENTARIO_EXCEL.md](INVENTARIO_EXCEL.md): operación del workbook.

## Uso seguro

Solo análisis de la base comercial:

```powershell
python scripts/report_legacy_sanitation.py --db ferreteria.db
```

La salida `DRY_RUN` incluye una fila por cada columna encontrada y el plan de
migraciones. No se ejecuta ninguna migración al importar módulos ni al iniciar
la aplicación.

No se hizo cutover productivo, no se tocó Supabase real y no se implementaron
barcodes, OCR, recepción inteligente ni autoridad OFFLINE.

## Inventario físico

El entregable operativo es `plantillas/FERREPRO_Inventario_Maestro.xlsx`.
Fue generado desde `ferreteria.db` en modo read-only con 141 productos y 300
espacios para productos nuevos. El barcode físico permanece pendiente.
