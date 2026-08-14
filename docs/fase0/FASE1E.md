# Fase 1E — Migración de writers al coordinador

**Estado 1E.1:** implementada (writers negativos preparados). Cutover **OFF**.
**No autoriza 1E.2+.** No activa autoridad. No seed.
**No declara INV-01 resuelto en SQLite.** **No declara INV-02 resuelto.**
`APPLY_AUTHORITATIVE_EXCLUDE` sigue `False`.

## Subfases

| Subfase | Qué es | Estado |
|---|---|---|
| **1E.0** | Inventario definitivo de writers + `InventoryGateway`. Cutover default OFF. Writers productivos **no** llaman al gateway ni al coordinador. | **Cerrada.** |
| **1E.1** | Migrar writers **negativos** (uno a uno) para que *puedan* usar el gateway, **sin activar autoridad**. Cutover sigue OFF. | **Esta fase. Implementada.** Ver [FASE1E1.md](FASE1E1.md). |
| **1E.2** | Migrar writers **positivos y mixtos**, mismo régimen: código listo, autoridad apagada. | **No autorizada.** STOP. |
| **1E.3** | **Cutover único.** Activar `INVENTORY_CUTOVER_ENABLED`. Semilla. Retirar writers legacy. Decisión sobre `productos.stock` / LWW. | **No autorizada.** Ver precondiciones abajo. |
| **1E.4** | Certificación final (PostgreSQL real, no dual authority, scanners, rollback operativo documentado). | **No autorizada.** |

Regla crítica (no negociable):

> Se puede migrar código writer por writer.
> **No** se puede activar autoridad writer por writer.
> Mientras exista un writer que altere inventario solo vía `productos.stock`,
> ningún writer migrado debe entrar en modo autoritativo real de forma aislada.

La activación es un **CUTOVER ÚNICO** (1E.3). En 1E.0 el default es legacy /
cutover OFF.

## Qué es 1E.0

Hecho:

- Re-inventario de writers (INV-19) en `docs/fase0/STOCK_WRITERS.md` y
  `tests/fase0/stock_writers.py`, verificado contra código.
- Scanner endurecido: UPDATE **y** INSERT directos de `productos.stock`.
- Módulo `inventory_gateway.py`, clase `InventoryGateway`.
- Flag `INVENTORY_CUTOVER_ENABLED = False`.
- Tests `tests/fase1e/` con harness tempfile oficial (nunca `ferreteria.db`).
- Caracterización de writers **antes** de modificarlos (no se modificaron).

No hecho (y prohibido aquí):

- Migrar ventas / compras / POS / devoluciones / mezclas / ajustes
- Activar el coordinador productivo
- `APPLY_AUTHORITATIVE_EXCLUDE = True`
- Dual-write (APPLY PostgreSQL + `UPDATE productos.stock` independiente)
- Shadow mutante
- Seed / fencing / barcodes / recepción / OCR
- Hardcodear credenciales o usar `SUPABASE_URI` owner como DSN del gateway

## Gateway (1E.0)

Archivo: `inventory_gateway.py`.

API pública:

- `INVENTORY_CUTOVER_ENABLED` (bool, default `False`)
- `INVENTORY_DSN_ENV = "FERREPRO_INVENTORY_DSN"`
- `read_inventory_dsn()` / `connection_factory_from_env()` — **no-owner**.
  Exigen `FERREPRO_INVENTORY_DSN`. **Nunca** fallback a `SUPABASE_URI`.
  No imprimen secretos.
- `InventoryGateway(sqlite_conn, *, connection_factory=..., cutover_enabled=..., ...)`
- `InventoryGateway.submit(...)` → `GatewaySubmitResult`

Separación:

| Capa | Qué hace |
|---|---|
| A. Persistencia local | `create_inventory_command` (ledger 1C, SQLite, estado `PERSISTED`) |
| B. Envío | `InventoryCoordinatorClient` / `apply_inventory_command` **solo si cutover ON** |
| C. Outcomes | `PENDING_CUTOVER` \| `APPLIED` \| `REJECTED` \| `UNKNOWN` |
| D. Reconnect | `connection_factory` certificado en 1D.3 |
| E. Retorno | dataclass frozen al writer |

Invariante **command_id antes de red**:

1. crear/persistir intent
2. conservar `command_id` / `request_hash` / payload
3. enviar
4. resolver estado

Ante UNKNOWN: **mismo** `command_id`, hash y payload. El gateway **no**
genera IDs en retry. Puede generar `command_id` / `operation_id` **solo**
en el primer persist, antes de cualquier transporte.

UNKNOWN no es REJECTED. UNKNOWN no es APPLIED. El ledger local permanece
`PERSISTED`. No se añade UNKNOWN al CHECK de `inventory_commands.estado`.

SQLite no es autoridad online. Una conexión SQLite pasada al transporte
falla (el coordinador ya lo hace; el gateway también lo rechaza).

Cuando cutover está OFF: `submit` persiste el intent como
`LEGACY_OBSERVED` (no `AUTHORITATIVE`) y devuelve `LEGACY_OBSERVED`.
No finge `APPLIED`. No llama al coordinador. Esos comandos **nunca**
se transmiten, ni después del cutover. Ver [FASE1E1.md](FASE1E1.md).

Tras APPLIED futuro (1E.3): `productos.stock` sería **proyección/caché**
reconstruible desde `inventory_balances`. No implementado en writers en 1E.0.

## Dual authority — cómo se evita

- Cutover default OFF.
- Writers negativos importan el gateway para el camino inyectable, pero el
  default **no** llama `submit()` ni `apply_inventory_command`.
- No hay dual-write permanente. En camino autoritativo de tests no hay
  `UPDATE productos.stock`.
- `APPLY_AUTHORITATIVE_EXCLUDE` sigue False: LWW de `productos.stock` sigue
  vigente a propósito, hasta 1E.3.
- `inventory_balances` está en `COORDINATOR_REMOTE_TABLES`, no en
  `SYNC_REGISTRY`. No entra a LWW.

## Precondiciones explícitas para 1E.3 (cutover)

Todas deben cumplirse **antes** de autorizar 1E.3. 1E.0 no las cumple:

1. Todos los writers conocidos (W01–W18) migrados al gateway.
2. DSN no-owner (`FERREPRO_INVENTORY_DSN`); no usar `SUPABASE_URI` owner
   como solución productiva.
3. `connection_factory` en el camino productivo (reconnect 1D.3).
4. `command_id` persistido antes de red, en todos los writers.
5. Reconciliation (ledger local vs coordinador) definida y testeada.
6. Seed completo de `inventory_balances` (`seed_inventory_balance` /
   corte legacy one-shot, no arranque silencioso).
7. Cobertura de `producto.local_id` en todo SKU que mueva stock.
8. Ningún writer legacy capaz de alterar `productos.stock` como autoridad.
9. Decisión explícita sobre `productos.stock` / LWW
   (`APPLY_AUTHORITATIVE_EXCLUDE = True` o retiro del campo del UPSERT).
10. Rollback operativo documentado y ensayable.

## Proyección vs autoridad

| Recurso | Rol hasta 1E.3 |
|---|---|
| `inventory_balances.quantity_scaled` | Autoridad online **diseñada**. Vacía/sin writers. |
| `productos.stock` | Legacy / LWW. Sigue siendo lo que las cajas mutan. |
| `inventory_commands` local | Intent. 1E.0: `PERSISTED` (o APPLIED/REJECTED solo si un test enciende cutover contra fakes). |

Riesgo de dual authority: si un writer migrado aplicara en PostgreSQL
**y** otro siguiera haciendo `UPDATE productos.stock`, el pull LWW
pisaría o divergería. Por eso el cutover es único y 1E.0 no activa nada.

## Deuda de 1E.0 — estado en 1E.1

1. Scanner a nivel función/SQL: **cerrada** en 1E.1.
2. Reconnect test sin `transport=` inyectado: **cerrada** (pasa por
   `apply_inventory_command`).
3. Caracterización W17/W18 con closures PySide: **aplazada a 1E.2**.
4. Timeout/deadlock post-persist → UNKNOWN: **cerrada** en 1E.1.

## STOP

**STOP — no implementar 1E.2.** No cutover. No seed. No migrar positivos/mixtos.
El detalle de 1E.1 está en [FASE1E1.md](FASE1E1.md).
