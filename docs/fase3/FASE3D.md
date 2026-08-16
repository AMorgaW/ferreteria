# Fase 3D — Caja operacional: apertura, movimientos, arqueo y cierre

**Veredicto:** GO. Inventario comercial: diferido. Caja comercial real: no operada.

## Alcance cerrado

Ciclo local-first: ABRIR → operar (ventas/cobros/egresos/devoluciones) → resumen → arqueo → CIERRE → diferencia como evidencia → historial inmutable.

La caja es el cajón físico de una estación. SQLite es la autoridad. Cloud es auditoría/sync posterior.

## Reutilizado

`cierres_caja`, `egresos_caja`, `abonos_ventas`, `abonos_compras`, outbox `cash_session`/`cash_expense`, roles ADMIN/GERENTE, `device_id`.

## Corregido

- Resumen y cierre ya no usan `DATE('now')`.
- Una sesión OPEN por estación (índice único).
- Autocierre 23:59 y reapertura automática eliminados.
- Egreso productivo deja de escribir por `pg_compat`/`ferreteria.db`.
- Pago a proveedor: un solo efecto OUT en el ledger (no doble conteo con egreso legacy).

## Añadido

Migración `20260816_009`: `cierres_caja.local_id/station_id/estado` + tabla `cash_movements` con UNIQUE `(source_kind, source_identity, cash_effect_kind)`. Un efecto físico sin OPEN queda pendiente (`cash_session_id` nulo) y la próxima OPEN de su estación lo reclama atómicamente.

## No incluido

Fase 4, contabilidad de doble partida, facturación fiscal, conciliación bancaria, split payment nuevo, FASE3_FINAL.
