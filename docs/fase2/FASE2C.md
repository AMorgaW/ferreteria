# Fase 2C — barcodes, scanner HID y doble verificación

**Estado técnico:** completa. **Alcance:** base local + laboratorio PostgreSQL.

Fase 2C introduce el modelo definitivo de múltiples barcodes por SKU, captura
HID tipo keyboard wedge, doble escaneo obligatorio, verificación posterior a
persistencia, códigos internos FRP y las políticas diferenciadas de alta.

No importó el Excel, no modificó stock, no ejecutó cutover, no se conectó a
Supabase y no implementó OCR ni recepción inteligente.

## Gate

| Criterio | Resultado |
|---|---|
| Double scan / mismatch sin persistencia | PASS |
| Read-back exacto desde DB | PASS |
| Ceros iniciales y case | PASS |
| Múltiples barcodes, un solo SKU/stock | PASS |
| UNIQUE SQLite y PostgreSQL central | PASS |
| FRP + retry acotado | PASS |
| FINAL / STAGING / LEGACY | PASS |
| Migración rerun + checksum | PASS |
| PostgreSQL real y carrera de estaciones | PASS |
| Critical SKIP | 0 |

Suite `tests/fase2c`: **40 PASS, 0 FAIL, 0 ERROR, 0 SKIP**. Incluye
**5/5** pruebas PostgreSQL reales.

## Componentes

- `barcode_scanner.py`: captura HID y `BarcodeDoubleScanVerifier`, sin Qt.
- `repositories/product_barcodes_repo.py`: asignación, lookup, PRIMARY, FRP y
  read-back.
- `services/barcode_service.py`: estados `SCANNED`, `VERIFIED`, `PERSISTED` y
  `PERSISTENCE_VERIFIED`; solo el último es éxito.
- `ui/barcode_widget.py`: panel compacto navy/naranja en Productos.
- `barcode_schema.py` + `migration_runner.py`: migración SQLite
  `20260815_003`.
- `postgres_product_barcodes.sql`: migración exclusivamente de laboratorio,
  aplicada por `apply_postgres_barcode_migration` con checksum.
- `sync_registry.py`: `product_barcodes` está en el registry canónico; no existe
  una lista paralela.

## Alta de producto

- `FINAL`: requiere `verified_barcode`; el formulario normal usa esta política.
- `STAGING`: permite vacío y guarda `BARCODE_PENDING`.
- `LEGACY_COMPAT`: conserva accesibilidad y marca
  `BARCODE_MISSING_LEGACY`; existe para flujos históricos ya caracterizados.

El producto FINAL y su primer barcode se insertan en la misma transacción. Tras
el commit se resuelve nuevamente el producto mediante `product_barcodes`; un
resultado ausente o distinto devuelve ERROR, no éxito.

## Excel de inventario

Los campos `CÓDIGO DE BARRAS - 1er ESCANEO` y
`VERIFICACIÓN CÓDIGO DE BARRAS - 2do ESCANEO` siguen siendo staging. Un futuro
importador no puede tratarlos como confirmados solo por estar llenos. La
confirmación final se realizará desde FERREPRO con este flujo de doble scan.

## PostgreSQL de laboratorio

Se usó únicamente `ferrepro-pg-test`, `localhost:55432`, base
`ferrepro_test`. La UNIQUE central decide carreras concurrentes: una estación
obtiene SUCCESS y la otra CONFLICT. El rol `ferrepro_barcode_app` recibe
`SELECT`, `INSERT` y `UPDATE`, no `DELETE` ni permisos públicos.

La migración PostgreSQL permanece como artefacto controlado de laboratorio; no
se aplicó a Supabase real. Antes de habilitar sync remoto en una fase futura se
debe desplegar explícitamente ese esquema en el entorno autorizado.

## Fuera de alcance

Importación del Excel, conciliación de cantidades, cambios masivos, generación
masiva de FRP, deducción unidad/caja por barcode, actualización de stock,
Supabase productivo, OCR, IA y cutover.
