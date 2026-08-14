# Fase 1D — Coordinador autoritativo PostgreSQL

**Estado:** implementada. Autorizada tras GO de QA de Fase 1C y GO humano.
**Prohibido avanzar a Fase 1E** (migrar writers productivos: POS, compras,
devoluciones, mezclas, ajustes) sin GO humano.

## Qué es Fase 1D

Crea la autoridad **online** capaz de recibir un `InventoryCommand` completo,
aplicarlo atómicamente al inventario central y devolver un resultado
idempotente.

Hecho:

- Tabla `inventory_balances` (PostgreSQL): autoridad online
- RPC `apply_inventory_command(...)` en una transacción
- Adapter Python `inventory_coordinator.py` (timeout, retry con el mismo
  `command_id`, APPLIED / REJECTED / IdempotencyConflict; exige conexión
  PostgreSQL `autocommit=False` sin transacción activa)
- Semilla explícita `seed_inventory_balance` (no pisa un balance existente)
- Infraestructura one-shot `initialize_inventory_balances_from_legacy`, con
  marcador persistente `inventory_balance_init_state` y locks por producto
  **no ejecutada** por arranque ni sync
- Tablas del coordinador fuera del sync LWW

No hecho (Fase 1E+):

- `VentasService` / POS LAN / `ComprasRepository` / devoluciones / mezclas /
  ajustes usando el coordinador
- `APPLY_AUTHORITATIVE_EXCLUDE = True`
- autoridad offline / fencing
- barcodes, recepción, OCR, UI nueva

INV-01 queda **demostrable en PostgreSQL real** (`tests/fase1d` integración).
El xfail de dos SQLite independientes **sigue**. INV-02 (LWW de
`productos.stock`) sigue abierto hasta retirar el flujo legacy.

## Autoridad

| Recurso | Rol en 1D |
|---|---|
| `inventory_balances.quantity_scaled` | Autoridad online (BIGINT, escala 1000) |
| `productos.stock` | Legacy/caché. El coordinador no lo lee ni lo escribe |
| `inventory_commands` / `inventory_operations` | Ledger 1C; el RPC escribe APPLIED/REJECTED |

Identidad de producto = `productos.local_id` = `inventory_balances.producto_local_id`.

## Fixed-point

Igual que 1C: **1000 = 1 unidad comercial**. 50 unidades = `50000`.
Cálculo autoritativo en BIGINT. No FLOAT/REAL.

## RPC

`public.apply_inventory_command(command_id, tipo, documento_tipo,
documento_local_id, device_id, usuario_id, request_hash, operations jsonb)`

Una llamada → una transacción PostgreSQL:

1. valida `command_id` / hash / operaciones
2. detecta retry (mismo hash → replay; hash distinto → conflicto)
3. bloquea balances en orden determinístico de `producto_local_id`
4. comprueba suficiencia de **todas** las líneas
5. aplica todos los deltas o ninguno
6. persiste APPLIED o REJECTED
7. devuelve un JSON estable

`APPLIED` solo después de actualizar `inventory_balances` en la misma TX.
`REJECTED` (stock insuficiente, balance inexistente, producto desconocido)
es resultado de negocio persistible; el retry recupera ese motivo.

Validación de payload inválido (comando vacío, delta 0, UUID mal formado)
sigue el contrato 1C: excepción, **no** se persiste.

## Locking

- Aislamiento: READ COMMITTED + `SELECT … FOR UPDATE` de las filas de
  `inventory_balances`
- `pg_advisory_xact_lock` por comando y por producto, en orden de
  `producto_local_id` canónico, para filas aún inexistentes y para reducir
  deadlock en comandos multilínea con productos compartidos en orden inverso
- No se hace SELECT de cantidad sin lock seguido de UPDATE independiente

## Inicialización de balance

Cómo nace una fila:

1. **Semilla explícita:** `seed_inventory_balance(producto_local_id, qty)`.
   `INSERT … ON CONFLICT DO NOTHING`. Una segunda llamada no pisa un
   balance más nuevo.
2. **Primer delta neto ≥ 0 aplicado** (p.ej. COMPRA futura): el RPC inserta
   la fila. Todavía no se conecta `ComprasRepository`.
3. **Delta neto negativo sin fila:** `REJECTED` con `BALANCE_NOT_FOUND`.
   No se interpreta como stock 0 silencioso ni como infinito.

### Corte legacy (NO automático)

`initialize_inventory_balances_from_legacy()` copia
`round(productos.stock::numeric * 1000)` **solo** a productos sin fila en
`inventory_balances`. `ON CONFLICT DO NOTHING`. Un marcador persistente evita
una segunda ejecución; la función toma el mismo advisory lock por producto que
el coordinador para no chocar con comandos concurrentes.

**No la ejecuta** `_ensure_remote_schema`, el adapter de aplicación ni el
POS. Un corte de producción exige fase de control posterior (1E+): ventana
sin ventas, semilla, verificación, entonces migrar writers.

## Seguridad

La función es `SECURITY DEFINER` con `SET search_path = pg_catalog, public`.
Sin SQL dinámico en el RPC. `REVOKE ALL … FROM PUBLIC`. Si existen roles
Supabase `anon` / `authenticated` / `service_role`, también se les revoca
EXECUTE y el acceso a las tablas. RLS habilitado en
`inventory_balances`, `inventory_balance_init`, `inventory_balance_init_state`,
`inventory_commands` e `inventory_operations` (el owner/BYPASSRLS de la URI de FERREPRO sigue
pudiendo ejecutar el RPC).

Autorización de negocio (quién puede mandar `delta = +999999999`) queda
para una fase posterior; 1D evita que la RPC quede pública por accidente.

FERREPRO se conecta hoy con `psycopg2` + `SUPABASE_URI` (rol de base,
no JWT anon). El adapter de 1D usa esa misma clase de conexión.

## Sync

`inventory_balances`, `inventory_balance_init` e
`inventory_balance_init_state` están en
`sync_registry.COORDINATOR_REMOTE_TABLES`, no en `SYNC_REGISTRY`.
`inventory_commands` / `inventory_operations` siguen en `NON_SYNC_TABLES`.
Ninguna viaja por UPSERT LWW.

## Tests

```text
python -m unittest discover -s tests/fase0 -v
python -m unittest discover -s tests/fase1a -v
python -m unittest discover -s tests/fase1b -v
python -m unittest discover -s tests/fase1b1 -v
python -m unittest discover -s tests/fase1b2 -v
python -m unittest discover -s tests/fase1c -v
python -m unittest discover -s tests/fase1d -v
```

`tests/fase1d` distingue **UNIT**, **CONTRACT** y **POSTGRES INTEGRATION**.

La integración PostgreSQL es opt-in:

```text
set FERREPRO_PG_TEST_DSN=postgresql://user:pass@127.0.0.1:5432/ferrepro_test
python -m unittest discover -s tests/fase1d -v
```

Nunca usa `SUPABASE_URI` (podría ser producción). Nunca simula locking
con SQLite. Si no hay DSN, esos tests se saltan y **no** se declara
concurrencia PostgreSQL certificada.

**STOP — no migrar writers productivos.**
