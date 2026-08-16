# Fase 4D — Release hardening / deployment readiness

**Veredicto de implementación:** GO si `tests/fase4d` y la regresión 3A–4C pasan.

4D no es Fase 5, no es DIAN, no es inventario comercial real, no es caja comercial real y no es deployment comercial.

## Alcance cerrado

- Fence operacional de writer financiero (W01 designado / W02 bloqueado al pagar).
- Backup SQLite consistente + manifest SHA-256.
- Restore explícito con safety backup.
- Migraciones rerunnable hasta `009` / `010`.
- Preflight READY / NOT_READY.
- Recursos PyInstaller (SQL del coordinador).
- Startup local-first sin red síncrona.

Contrato operativo: [DEPLOYMENT_READINESS.md](DEPLOYMENT_READINESS.md).

## Financial writer fence

`services/financial_writer_fence.py` (`FinancialWriterFence`).

Comparación:

```
current_station == configured_financial_writer  → ALLOW
current_station != configured_financial_writer  → FINANCIAL_WRITER_FENCE
```

Configuración: `financial_writer_station_id` / `FINANCIAL_WRITER_STATION_ID`.
Estación actual: `FERREPRO_STATION_ID` o `device_id` / `resolve_station_id()`.

El gate vive en el writer productivo **antes de persistir**:

- `AbonosVentasRepository.crear_abono`
- `registrar_abono_compra_en_transaccion`

La UI muestra `Pago no permitido` + el código. No se confía solo en UI.

No bloquea ventas, recepción, inventario, reporting ni impresión.

Esto es un **operational fence**. No es serialización distribuida. W01 y W02 no comparten un coordinador financiero.

Producción fail-closed: si hay más de una estación prevista y no hay writer designado, el preflight es `NOT_READY` (`FINANCIAL_WRITER_FENCE_REQUIRED`) y el pago también se rechaza.

## Backup / restore

`backup_manager.py` usa `sqlite3.Connection.backup` (incluye WAL). No copia cruda del archivo activo.

El snapshot lleva:

- DB consistente
- timestamp
- station / device
- schema version
- SHA-256 + manifest sidecar

Restore:

1. valida SQLite + manifest obligatorio + checksum
2. crea safety backup del destino
3. restaura por backup API
4. si falla después de comenzar, recupera el destino desde el safety backup
5. no corre en startup

Solo tests sobre tmp. No se restaura `ferreteria.db` comercial.

## Migraciones

Runner existente. 4D no añade migración de esquema. Una DB legacy temporal recorre hasta `20260816_009` y `20260816_010`. Idempotente, rerunnable, non-destructive.

Flujo certificado: backup → migrate → read.

## Preflight

`services/deployment_readiness.py` (CLI: `python services/deployment_readiness.py --production`).

Revisa sin mutar negocio: SQLite escribible, migraciones, station_id, writer financiero, SQL del coordinador, directorio de backup, local-first, config.

No requiere Supabase para arrancar.

## Inventario y caja comerciales

INVENTARIO COMERCIAL REAL: **PENDING FINAL DEPLOYMENT**.

Flujo futuro intacto:

XLSX → VALIDATE → STAGING → MATCHING → REVIEW → DRY-RUN → APPROVE → PRE-FLIGHT → APPLY → VERIFY → COMPLETED.

CAJA COMERCIAL REAL: **NOT EXECUTED**.

## Packaging

`Ferreteria.spec` exige `supabase_inventory_coordinator.sql` en `datas`. No incluye `.env`, `ferreteria.db` comercial, docs ni tests.

En frozen, el SQL solo se busca en `_MEIPASS` y junto al ejecutable. Recurso ausente → error explícito, sin fallback al árbol fuente del desarrollador.

## Local-first / secretos

Startup no hace gate remoto síncrono. `_gate_supabase()` retorna `False` y no bloquea la GUI.

El preflight no emite passwords, tokens, service-role keys ni connection strings.

## Limitaciones

1. El fence no serializa dos estaciones contra la misma obligación: solo designa un writer.
2. Inventario comercial real sigue pendiente del deployment final.
3. Caja comercial real no se abre ni se cierra en 4D.
4. No hay backup a la nube ni coordinador financiero distribuido.
