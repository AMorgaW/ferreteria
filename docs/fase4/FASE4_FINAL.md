# FASE 4 FINAL ACCEPTANCE

## Veredicto

**GO**

Auditoría final pre-commit sobre `fase4d-release-readiness`. Nada fue agregado
al staging y no se ejecutó commit, push, merge, rebase, reset, restore ni clean.

## 4A — Reportes / Analítica: GO

- Reporting authority: SQLite local; inventario canónico desde
  `inventory_balances.quantity_scaled`, no `productos.stock`.
- Gross/net: ventas y compras separan original, reversos y neto; caja conserva
  la autoridad 3D.
- XLSX: consume los mismos datasets y reglas que la UI, con dinero `Decimal`.

## 4B — CxC / CxP / Saldos: GO

- Canonical balances: `NET = ORIGINAL COMPLETED - REVERSALS`;
  `BALANCE = max(NET - PAYMENTS, 0)`;
  `CREDIT = max(PAYMENTS - NET, 0)`.
- Legacy payments: baseline de migración `20260816_010` preservado, sin duplicar
  abonos; rerun idempotente.
- Financial limitation: el fence 4D es operacional. No implementa autoridad ni
  serialización financiera distribuida.

## 4C — Documentos: GO

- Documents: venta, recepción/compra, devolución cliente, anulación, devolución
  proveedor, cierre de caja y comprobantes de pago.
- Historical values: precio/costo/subtotal salen de las líneas durables;
  reversos de `reversal_lines`; cierre de los valores CLOSED de la sesión.
- Read-only: dos reimpresiones no crean ventas, inventario, movimientos de caja,
  abonos ni reversos.
- Print/PDF: cancelar, no tener impresora, fallar o reintentar no confirma ni
  modifica una operación comercial.
- Non-fiscal: `DOCUMENTO OPERACIONAL / NO FISCAL`; no afirma autorización DIAN
  ni factura electrónica válida.

Limitación histórica aceptada: el nombre del producto puede provenir del
catálogo actual porque no existe snapshot durable del nombre.

## 4D — Release Readiness: GO

### Financial writer fence

- Configured: mecanismo explícito mediante `FINANCIAL_WRITER_STATION_ID` o
  `financial_writer_station_id`; el valor de deployment sigue pendiente.
- Non-writer: W02 puede leer saldos y recibe `FINANCIAL_WRITER_FENCE` al intentar
  finalizar abono de cliente o pago a proveedor; W01 designada puede hacerlo.
- Fail-closed: producción o flota multiestación sin writer queda `NOT_READY` y
  el writer productivo rechaza pagos.
- Distributed authority: **NO implementada**. Es operational fence only.

### Backup

- Consistency: `sqlite3.Connection.backup`, consistente con WAL y sin cloud.
- Manifest: sidecar durable/atómico con timestamp, estación/device, versión de
  schema, nombre restaurable y origen `sqlite_backup_api`.
- Checksum: SHA-256 corresponde exactamente al `.db` restaurable; archivo o
  manifest alterado/ausente/inválido falla cerrado.

### Restore

- Validation: header SQLite, `integrity_check`, manifest obligatorio y checksum.
- Safety backup: se crea antes de restaurar; si falla, el restore aborta.
- Failure safety: un fallo posterior recupera automáticamente el destino desde
  el safety backup; si la recuperación falla, declara estado `INCIERTO` y
  conserva su ruta. No existe auto-restore de startup.

### Migrations

DB legacy temporal migra hasta `20260816_009` y `20260816_010`, llega a latest,
preserva datos y admite rerun. 4D no añadió migración innecesaria. Preflight
distingue migraciones pendientes de schema correcto.

### Deployment preflight

- CLI: `python services/deployment_readiness.py --production` funciona desde la
  raíz sin error de imports ni de encoding de consola.
- READY contract: SQLite existente/escribible, schema current, station válida,
  writer designado, SQL coordinador, backup usable y modo local-first.
- NOT_READY contract: estado más blockers exactos. El diagnóstico local actual
  devolvió `SCHEMA_MIGRATIONS_PENDING` y `FINANCIAL_WRITER_FENCE_REQUIRED`, como
  corresponde a un deployment comercial aún no ejecutado.
- Side effects: no crea DB ausente ni escribe negocio; solo puede crear/probar el
  directorio de backup según la política explícita.

### Packaging

- Build status: PyInstaller PASS certificado previamente; no se repitió porque
  la auditoría no cambió packaging.
- `.env`: no empaquetado.
- `ferreteria.db`: no empaquetada.
- Coordinator SQL: presente en `dist/Ferreteria/_internal` y exigido por spec.
- Frozen resources: resuelve por `_MEIPASS` o junto al ejecutable; ausente produce
  `CoordinatorError` explícito.
- Developer paths: no hay fallback ni path absoluto del desarrollador en runtime.

### Offline startup

Supabase no es requisito de startup. GUI, reporting, documentos, balances y caja
local operan desde SQLite; sincronización remota se inicia en background.

### Secrets

No se encontraron secretos en los cambios runtime. Preflight no imprime valores
sensibles. `.env` permanece ignorado y no empaquetado.

## Correcciones realizadas

1. Se reparó el CLI documentado para ejecutarse desde la raíz del repositorio.
2. Se hizo portable su JSON en consolas Windows CP1252.
3. Preflight ya no crea una SQLite ausente y reporta `SQLITE_NOT_FOUND`.
4. Manifest de backup durable, obligatorio y validado estrictamente.
5. Restore recupera desde safety backup y declara inequívocamente cualquier
   fallo de recuperación.

## Tests

- `fase4c+fase4d`: **49 PASS**.
- Direct acceptance (`fase2g1` + 4A–4D): **126 PASS**.
- Final regression (3A–4D): **227 PASS**.

Resumen de la regresión final:

- PASS: **227**
- FAIL: **0**
- ERROR: **0**
- SKIP: **0**
- Critical skip: **0**

## Seguridad

- `ferreteria.db` real mutated: **NO**.
- `.env` packaged/tracked: **NO**.
- Supabase real destructive: **NO**.
- Inventario comercial real: **NO**.
- Caja comercial real: **NO**.
- Deployment comercial: **NO**.

## Remaining limitations

1. Inventario físico real y aplicación del inventario real pendientes.
2. Configuración de `FINANCIAL_WRITER_STATION_ID` pendiente.
3. Instalación en estaciones pendiente.
4. Caja comercial real pendiente.
5. Validación operacional final pendiente.

## FASE 4

- 4A GO
- 4B GO
- 4C GO
- 4D GO

FASE 4 SOFTWARE / OPERACIONAL:
**COMPLETE**

READY FOR FINAL CHECKPOINT.
