# Fase 2 — migración y saneamiento legacy

**Estado:** FASE 2 SOFTWARE COMPLETE. PENDING DIG-X6266 HUMAN VERIFICATION.

Fase 2G certificó sobre fixtures temporales la integración completa desde
Excel/staging hasta APPLY, cola `BARCODE_PENDING`, doble scan, persistencia,
read-back y restart. La certificación física definitiva sigue bloqueada hasta
que un humano ejecute la prueba con el DIG-X6266 real.

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
- [FASE2C.md](FASE2C.md): cierre técnico y gate de barcodes.
- [BARCODES.md](BARCODES.md): modelo, unicidad, múltiples códigos y FRP.
- [SCANNER_HID.md](SCANNER_HID.md): contrato HID, doble scan y prueba manual.
- [FASE2D.md](FASE2D.md): cierre técnico de la importación controlada.
- [INVENTORY_IMPORT.md](INVENTORY_IMPORT.md): contrato XLSX y staging.
- [INVENTORY_RECONCILIATION.md](INVENTORY_RECONCILIATION.md): matching,
  autoridad y dry-run.
- [FASE2E.md](FASE2E.md): cierre técnico del APPLY controlado.
- [INVENTORY_APPLY.md](INVENTORY_APPLY.md): aprobación, CAS, saga e idempotencia.
- [INVENTORY_RECOVERY.md](INVENTORY_RECOVERY.md): restart, UNKNOWN y fallo parcial.
- [FASE2F.md](FASE2F.md): cierre de regularización operacional de barcodes.
- [BARCODE_REGULARIZATION.md](BARCODE_REGULARIZATION.md): cola, doble scan,
  modo continuo, `package_role`, FRP y candidate Excel.
- [DIG_X6266_MANUAL_TEST.md](DIG_X6266_MANUAL_TEST.md): prueba física pendiente.
- [PRE_REAL_INVENTORY_CHECKLIST.md](PRE_REAL_INVENTORY_CHECKLIST.md): gate previo
  a cualquier inventario real.

## Uso seguro

Solo análisis de la base comercial:

```powershell
python scripts/report_legacy_sanitation.py --db ferreteria.db
```

La salida `DRY_RUN` incluye una fila por cada columna encontrada y el plan de
migraciones. No se ejecuta ninguna migración al importar módulos. El bootstrap
local-first materializa idempotentemente el esquema vacío de barcodes en una
instalación fresca, sin backfill ni FRP; el catálogo/checksum de upgrades sigue
perteneciendo a `migration_runner`.

No se hizo cutover productivo, no se tocó Supabase real y no se implementaron
OCR, recepción inteligente ni autoridad OFFLINE. Fase 2C implementó barcodes
en SQLite y PostgreSQL de laboratorio, sin importar el Excel ni cambiar stock.

## Inventario físico

El entregable operativo es `plantillas/FERREPRO_Inventario_Maestro.xlsx`.
Fue generado desde `ferreteria.db` en modo read-only con 141 productos y 300
espacios para productos nuevos. El barcode físico permanece pendiente.

La finalización técnica de Fase 2 no significa que el inventario comercial se
haya ejecutado. El primer inventario real será una operación posterior,
controlada por el checklist y por autorización humana explícita.
