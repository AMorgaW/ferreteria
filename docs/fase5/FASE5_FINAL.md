# Fase 5 — Final pre-inventory acceptance

## Veredicto

**FASE 5 FINAL ACCEPTANCE: GO.**

El NO-GO provisional de 5D, causado exclusivamente por la pérdida del DSN del
laboratorio PostgreSQL local entre sesiones PowerShell, queda **superseded**.
Con `ferrepro-pg-test` activo y el DSN reconstruido desde el contenedor, las
seis pruebas PostgreSQL críticas y la suite transversal final pasaron sin
fallos, errores ni skips.

| Microfase | Resultado |
| --- | --- |
| 5A — Caja / roles | **GO** |
| 5B — Migration lifecycle | **GO** |
| 5C — Legacy writer hardening | **GO** |
| 5D — Final acceptance | **GO** |

## 5A — Caja / roles

- ADMIN y GERENTE pueden abrir/cerrar caja, registrar ingreso o egreso manual,
  consultar el resumen administrativo y realizar arqueo.
- VENDEDOR y EMPLEADO acceden a la sección y ven estado/estación, pero no
  reciben monto inicial, efectivo esperado, resumen, arqueo ni historial
  administrativo desde la UI o el service layer.
- Los comandos administrativos se validan en `CajaService`; no dependen de
  esconder botones.
- Una venta EFECTIVO válida de VENDEDOR/EMPLEADO queda COMPLETED y genera
  exactamente un `cash_movements` `DRAWER_IN`. Tarjeta/no efectivo queda
  `INFORMATIONAL` y no aumenta el efectivo esperado.
- Se conservan Decimal, exactly-once, station scope, cross-midnight, CLOSED
  inmutable y recovery.

Durante 5D se corrigió una exposición HIGH demostrada: un rol operativo podía
consultar directamente información sensible de arqueo en `CajaService` aunque
la UI la ocultaba. La vista operacional del servicio quedó saneada y los reads
administrativos exigen ADMIN/GERENTE.

## 5B — Migration lifecycle

- `schema_lifecycle.ensure_sqlite_schema_current` es el lifecycle productivo
  para SQLite; no crea silenciosamente el archivo esperado si falta.
- Legacy con pendientes: detecta → backup WAL-safe + manifest/SHA-256 →
  `MigrationRunner.run(dry_run=False)` → verifica latest.
- Latest: no crea backup innecesario ni reaplica DDL.
- Backup fallido: no migra. Archivo corrupto/no SQLite: fail closed.
- Catálogo oficial único: `20260815_001` a `20260816_010`.
- El guard defensivo de Caja reutiliza el schema 009 y no reemplaza al catálogo
  versionado.
- Atomicidad real por migración: una anterior puede quedar aplicada; la fallida
  revierte, no se registra, el backup permanece y el rerun la ve `PENDING`.

### Migración 010

Ventas y compras cumplen el contrato 4B:

- 100 / pagado 30 / sin abonos → baseline 30, balance 70.
- 100 / pagado 100 / sin abonos → balance 0.
- pagado 30 / abono durable 30 → no duplica.
- pagado 50 / abono durable 30 → no sintetiza diferencia 20.
- rerun → una sola baseline.

Después del cutover, `operational_balance` continúa como autoridad; las
proyecciones legacy no vuelven a decidir el saldo.

### Consumidores de schema

- 2D/2E: `InventoryImportRepository._require_schema` PASS; se preserva el
  workflow REVIEW → DRY-RUN → APPROVE → PRE-FLIGHT → APPLY → VERIFY → COMPLETED.
- 3C: `reversal_documents` y `reversal_lines` disponibles; operación dirigida
  no falla por schema ausente.
- 4B: NET, BALANCE y CREDIT permanecen derivados de documentos, reversos y
  pagos válidos canónicos.
- 4D: no aparece `SCHEMA_MIGRATIONS_PENDING`; el preflight conserva
  `FINANCIAL_WRITER_FENCE_REQUIRED` cuando no hay writer comercial designado.

## 5C — Legacy writer hardening

- Decisión vigente: **LAN DISABLED AS COMMERCIAL WRITER**.
- POST `/sales` y el camino authoritative responden 403
  `LAN_SALES_DISABLED` en PRE_CUTOVER y POST_CUTOVER.
- `auto_start_server` es `False` por defecto; solo `True` explícito puede
  iniciar el listener diagnóstico y nunca reactiva ventas LAN.
- La ruta LAN no usa float como autoridad, no actualiza `productos.stock` y no
  implementa una segunda venta comercial.
- El POS canónico permanece en `VentasService.registrar_venta`.
- Si falla el rehash PBKDF2 tras credenciales válidas, el login continúa,
  revierte apropiadamente y emite WARNING sin password, hash, token, secreto o
  connection string.

## Contratos cross-phase

- Inventario ONLINE post-cutover: PostgreSQL
  `inventory_balances.quantity_scaled`; `productos.stock` es legacy/proyección
  según estado.
- Caja: SQLite `cash_movements`.
- Saldos: `operational_balance`.
- Documentos: read-only.
- Reporting: adaptador canónico de inventario.
- Rentabilidad: `LEGACY_UNVERIFIED` / `ESTIMATED`.
- Financial writer: fence operacional; no se declara autoridad financiera
  distribuida.
- Startup, Caja, Ventas, Reporting, Documents, Balances y migration lifecycle
  operan local-first sin requerir Supabase ni el listener LAN.

## Pruebas finales

- PostgreSQL críticas recuperadas: **6 passed**; FAIL 0, ERROR 0, SKIP 0.
- Suite transversal final única:
  `tests/fase2d tests/fase2e tests/fase2g1 tests/fase3a tests/fase3b
  tests/fase3c tests/fase3d tests/fase4a tests/fase4b tests/fase4c
  tests/fase4d tests/fase5`: **416 passed, 4 subtests passed**.
- FAIL 0, ERROR 0, SKIP 0, CRITICAL SKIP 0.
- PostgreSQL usado: exclusivamente `ferrepro-pg-test` local desechable en
  `127.0.0.1:55432`. `SUPABASE_URI` no se usó.

## Safety

- `ferreteria.db` comercial no fue iniciada ni migrada.
- SHA-256 inicial de 5D:
  `CB0314897600F79E75ECFF65555E2296AC6E7BCA25AD501CD5DB38465B9D0DFF`.
- No se ejecutó inventario, caja, productos, Excel, cutover, Supabase
  destructivo ni deployment comercial.
- No se configuró comercialmente `FINANCIAL_WRITER_STATION_ID`.

## Declaración final

**FASE 5 — PRE-INVENTORY STABILIZATION: COMPLETE.**

FERREPRO queda **READY FOR PRODUCT CATALOG / INVENTORY PREPARATION**.

Esto no declara productos reales cargados, Excel definitivo procesado,
inventario real aplicado, cutover realizado, writer financiero comercialmente
configurado ni deployment comercial realizado.

