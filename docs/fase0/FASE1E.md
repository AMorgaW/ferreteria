# Fase 1E — Migración de writers al coordinador

**Estado 1E.4:** hardening de flota + certificación de cutover en
laboratorio PostgreSQL. **Fase 1 técnicamente implementada.**
**No declara Fase 1 completa** (falta auditoría final Luna).
Ver [FASE1E4.md](FASE1E4.md). **No cutover productivo / Supabase real.**

## Subfases

| Subfase | Qué es | Estado |
|---|---|---|
| **1E.0** | Inventario definitivo de writers + `InventoryGateway`. Cutover default OFF. Writers productivos **no** llaman al gateway ni al coordinador. | **Cerrada.** |
| **1E.1** | Migrar writers **negativos** (uno a uno) para que *puedan* usar el gateway, **sin activar autoridad**. Cutover sigue OFF. | **Cerrada.** Ver [FASE1E1.md](FASE1E1.md). |
| **1E.2** | Migrar writers **positivos y mixtos**, mismo régimen: código listo, autoridad apagada. | **Cerrada.** Ver [FASE1E2.md](FASE1E2.md). |
| **1E.3** | **Cutover único.** Estado persistente. Seed. Freeze. `productos.stock` proyección. LWW de stock excluido en AUTHORITATIVE. Laboratorio PG. | **Cerrada en laboratorio.** Ver [FASE1E3.md](FASE1E3.md). |
| **1E.4** | Hardening de flota + certificación final de cutover. Control PG común, fail-closed, snapshot reconciliado. | **Implementada en laboratorio. Pendiente auditoría Luna.** Ver [FASE1E4.md](FASE1E4.md). |

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

Tras APPLIED en 1E.3 laboratorio (`AUTHORITATIVE`): `productos.stock` es
**proyección/caché** reconstruible desde `inventory_balances` (D05). No es
segunda autoridad. Ver [FASE1E3.md](FASE1E3.md).

## Dual authority — cómo se evita

- Cutover default OFF.
- Writers negativos importan el gateway para el camino inyectable, pero el
  default **no** llama `submit()` ni `apply_inventory_command`.
- No hay dual-write permanente. En camino autoritativo de tests no hay
  `UPDATE productos.stock`.
- `APPLY_AUTHORITATIVE_EXCLUDE` sigue False **en fuente**. En estado
  `AUTHORITATIVE` el runtime excluye `productos.stock` de LWW. PRE_CUTOVER
  conserva el UPSERT legacy.
- `inventory_balances` está en `COORDINATOR_REMOTE_TABLES`, no en
  `SYNC_REGISTRY`. No entra a LWW.

## Precondiciones de 1E.3 (laboratorio)

Cerradas en laboratorio PostgreSQL. Ver [FASE1E3.md](FASE1E3.md).
**No** equivalen a cutover productivo.

## Proyección vs autoridad

| Recurso | PRE_CUTOVER | AUTHORITATIVE (lab 1E.3) |
|---|---|---|
| `inventory_balances.quantity_scaled` | Autoridad diseñada; vacía hasta seed | Autoridad ONLINE |
| `productos.stock` | Legacy / LWW | Proyección/caché (D05), no LWW |
| `inventory_commands` local | `LEGACY_OBSERVED` no transmissible | Intent `AUTHORITATIVE` |

Riesgo de dual authority: si un writer migrado aplicara en PostgreSQL
**y** otro siguiera haciendo `UPDATE productos.stock`, el pull LWW
pisaría o divergería. Por eso el cutover es único y 1E.0 no activa nada.

## Deuda de 1E.0 — estado en 1E.2

1. Scanner a nivel función/SQL: **cerrada** en 1E.1.
2. Reconnect test sin `transport=` inyectado: **cerrada** (pasa por
   `apply_inventory_command`).
3. Caracterización W17/W18 con closures PySide: **cerrada** en 1E.2
   (mutación en `VentasService`).
4. Timeout/deadlock post-persist → UNKNOWN: **cerrada** en 1E.1.
5. `intent_class` fail-closed + recovery post-APPLY W06/W02/W15: **cerrada**
   en 1E.2.

## STOP

**STOP — no declarar FASE 1 COMPLETA.** El detalle de 1E.4 está en
[FASE1E4.md](FASE1E4.md). No cutover en Supabase real. No Fase 2.
