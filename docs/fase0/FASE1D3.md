# Fase 1D.3 — Gate de autorización empresarial + reconexión

**Estado:** implementada y certificada en laboratorio Docker local el 2026-08-14
(recuperación post-crash + QA adversarial GO el mismo día).
**No autoriza Fase 1E.** No migra POS, compras ni writers productivos.
**No declara INV-01 resuelto en SQLite.** **No declara INV-02 resuelto.**

Cierra los dos HIGH de la auditoría posterior a 1D.1:

1. Autorización empresarial del inventario online (roles PostgreSQL no-owner).
2. Reconexión segura tras pérdida de conexión ambigua / post-COMMIT.

## Qué quedó certificado (y qué no)

| Capa | Qué certifica 1D.3 | Qué no certifica |
|---|---|---|
| Autorización **técnica** | `session_user` + `GRANT EXECUTE` + `REVOKE PUBLIC` + RLS deny-all para DML directo + signos estructurales | JWT, `anon`/`authenticated`, `AuthManager` |
| Autorización **empresarial mínima** | Un LOGIN no-owner miembro de `ferrepro_inventory_app` puede invocar `apply_inventory_command`; un LOGIN sin membresía y PUBLIC no | Roles comerciales SQLite (`VENDEDOR`, `BODEGUERO`, …) en PostgreSQL |
| Identidad confiable | Rol de la conexión PostgreSQL | `p_usuario_id`, `p_device_id` (metadato de auditoría) |
| Reconexión | Mismo `command_id` / `request_hash` / payload sobre conexión **nueva**; UNKNOWN si el COMMIT es ambiguo | Cortar el DSN productivo a un rol no-owner |

## Modelo de confianza

FERREPRO **no** se autentica hoy contra PostgreSQL con JWT `anon` / `authenticated`.
Se conecta con `psycopg2.connect(SUPABASE_URI)`: un **rol de base** (URI de
Postgres). `AuthManager` autentica usuarios SQLite (`ADMIN`, `GERENTE`,
`VENDEDOR`, `BODEGUERO`, `CONTADOR`) en el cliente; esa identidad **no** llega
como `session_user`.

| Dato | ¿Confiable en el servidor? |
|---|---|
| `session_user` de la conexión PostgreSQL | Sí. Identidad SQL real del caller |
| `GRANT EXECUTE` sobre `apply_inventory_command` | Sí. Gate de invocación |
| Owner de la función (`SECURITY DEFINER`) | Sí para provisionar. No certifica autorización de app |
| `p_usuario_id` | No. Entero del cliente; manipulable |
| `p_device_id` | No. UUID del cliente; manipulable |
| Rol comercial SQLite (`VENDEDOR`, etc.) | No visible en PostgreSQL |
| RLS en tablas del coordinador | Niega DML directo. No autoriza comandos `SECURITY DEFINER` |
| `REVOKE PUBLIC` | Necesario, insuficiente por sí solo |

Un cliente que solo tiene `EXECUTE` de `apply_inventory_command` **no** puede:

- hacer `UPDATE`/`INSERT` directo sobre `inventory_balances`
- llamar `seed_inventory_balance` ni el corte legacy
- ejecutar tipos con signo estructuralmente imposible (p.ej. `VENTA` positiva)

Sí puede, si tiene `EXECUTE`, enviar un comando **del tipo permitido** con
`p_usuario_id` / `device_id` inventados. Esos campos son metadato de auditoría,
no autorización. El RBAC comercial sigue en `AuthManager.tiene_permiso` hasta
que una fase posterior conecte writers con identidad confiable.

## Matriz de autorización (v1 — 1D.3)

Versión: `ferrepro.inventory.authz.v1`.

Quien puede **invocar** la RPC en PostgreSQL: miembro de `ferrepro_inventory_app`
(o el owner, solo para provisionar el laboratorio). No se inventaron roles
comerciales nuevos. Los roles reales de FERREPRO viven en SQLite.

| tipo | Caller PG | Signo delta | Documento | usuario_id | device_id | Valida el coordinador | Capa de negocio futura |
|---|---|---|---|---|---|---|---|
| VENTA | `ferrepro_inventory_app` | todas las líneas `< 0` | no exigido | metadato no confiable | UUID obligatorio, no confiable | EXECUTE + signo + stock | `realizar_ventas` (ADMIN/GERENTE/VENDEDOR) |
| COMPRA | idem | todas `> 0` | no exigido | metadato | UUID obligatorio | EXECUTE + signo + overflow | movimientos/compras de ADMIN/GERENTE |
| RECEPCION | idem | todas `> 0` | no exigido | metadato | UUID obligatorio | EXECUTE + signo | CONTRATO: admin/gerente/bodeguero |
| DEVOLUCION | idem | signo uniforme (todo + o todo −) | no exigido | metadato | UUID obligatorio | EXECUTE + signo uniforme | `gestionar_movimientos` |
| AJUSTE | idem | cualquier no-cero | no exigido | metadato | UUID obligatorio | EXECUTE; sin cupo comercial | ADMIN/GERENTE/BODEGUERO (aún no en PG) |
| MEZCLA | idem | al menos un `< 0` y un `> 0` | no exigido | metadato | UUID obligatorio | EXECUTE + mixto | ADMIN/GERENTE/BODEGUERO (aún no en PG) |

No se inventó un máximo comercial tipo “1000 unidades”. El coordinador solo
impone rango BIGINT y las reglas estructurales de la tabla.

`seed_inventory_balance` e `initialize_inventory_balances_from_legacy` quedan
restringidos al **owner**. No son primitivas de la app.

## Roles PostgreSQL de prueba

Creados solo en el laboratorio. No SUPERUSER. No BYPASSRLS. No dueños de tablas.

| Rol | LOGIN | Membresía | EXECUTE apply | seed / DML tablas |
|---|---|---|---|---|
| `ferrepro_inventory_app` | no | grupo | GRANT condicional en el DDL | REVOKE |
| `ferrepro_inventory_allowed_test` | sí | miembro del grupo | sí (heredado) | no |
| `ferrepro_inventory_denied_test` | sí | ninguna | no | no |
| PUBLIC | — | — | no | no |
| owner/`postgres` | sí | dueño | sí (provisionar) | sí |

El DDL canónico **no** hace `CREATE ROLE` (Supabase puede no tener `CREATEROLE`).
Si existe `ferrepro_inventory_app`, otorga `EXECUTE` de `apply_inventory_command`
y nada más.

## SECURITY DEFINER

| Control | Estado |
|---|---|
| Owner de la función | rol de provisionamiento (laboratorio: postgres) |
| `SET search_path = pg_catalog, public` | sí |
| SQL dinámico | no |
| `REVOKE ALL … FROM PUBLIC` | apply, to_json, seed, legacy, helper, tablas |
| `REVOKE` anon / authenticated / service_role | si existen |
| Identidad del caller | `session_user` (no `current_user` del DEFINER) |
| Helper `ferrepro_inventory_caller_is_allowed()` | DEFINER; `pg_has_role(session_user, 'ferrepro_inventory_app', 'USAGE')` **o** owner |
| Shadowing | search_path fijo; adapter llama `public.apply_inventory_command` |

`EXECUTE` no equivale a DML arbitrario: el rol autorizado no tiene GRANT sobre
tablas. RLS sigue habilitado (deny-all para no-owner).

## Protocolo de reconexión / UNKNOWN

1. El caller prepara `command_id`, `request_hash` y payload **antes** del transporte.
2. Envía el RPC en una transacción con `autocommit=False`.
3. Si se pierde la conexión (OperationalError, InterfaceError, reset, EOF,
   `pg_terminate_backend`, timeout ambiguo de red):
   - el resultado local es **UNKNOWN** (`CoordinatorUnknownOutcomeError`);
   - se **descarta** la conexión muerta (no se “revive”);
   - se abre una sesión PostgreSQL **nueva** (`connection_factory`);
   - se reintenta el **mismo** `command_id` / hash / operaciones.
4. Nunca se genera un `command_id` nuevo para resolver incertidumbre.
5. El servidor: APPLIED persistido → replay; REJECTED persistido → mismo
   REJECTED (no se reevalúa); hash distinto → `IDEMPOTENCY_CONFLICT`.

`InventoryCoordinatorClient` acepta `conn` y/o `connection_factory`. Sin factory,
el UNKNOWN se propaga al caller.

## Constraint naming

El handler de `unique_violation` ya no depende solo de nombres implícitos.
Nombres canónicos + legado reconocidos:

| Objeto | Canónico | Legado 1D |
|---|---|---|
| PK commands | `pk_inventory_commands` | `inventory_commands_pkey` |
| PK operations | `pk_inventory_operations` | `inventory_operations_pkey` |
| UNIQUE (command, line) | `uq_inventory_operations_command_line` | `inventory_operations_command_id_line_no_key` |
| PK balances | `pk_inventory_balances` | `inventory_balances_pkey` |
| PK init | `pk_inventory_balance_init` | `inventory_balance_init_pkey` |

Migración: `RENAME CONSTRAINT` idempotente. Sin DROP destructivo. Compatible
con bases creadas por Fase 1D.

## Pruebas reales

Laboratorio: contenedor `ferrepro-pg-test`, `localhost:55432`, `ferrepro_test`,
PostgreSQL 16. Variable `FERREPRO_PG_TEST_DSN`. No se usa `SUPABASE_URI`.

Roles no-owner de laboratorio: `ferrepro_inventory_allowed_test` (miembro del
grupo) y `ferrepro_inventory_denied_test` (sin EXECUTE). La pérdida de sesión
se induce con `pg_terminate_backend` del PID de **esa** prueba.

```text
python -m unittest discover -s tests/fase1d -v
```

Certificado con DSN presente: **75 tests, 0 FAIL, 0 SKIP** (incluye authz
`device_id` inventado, UNKNOWN pre-COMMIT tipado y REJECTED replay con stock
mutado). Authz+reconnect: 5 corridas estables antes del endurecimiento de
cobertura; revalidar tras el cierre.

La certificación post-COMMIT usa COMMIT real + `pg_terminate_backend` de esa
sesión; el `OperationalError` de transporte lo inyecta el proxy de test
(`_CommitThenTerminate`). El replay en PID nuevo es real. Un corte libpq
crudo durante `COMMIT` no está instrumentado aparte.

## Riesgos restantes

- El DSN productivo (`SUPABASE_URI`) sigue siendo, en la práctica, un rol owner.
  El gate existe; el corte de credenciales de inventario a `ferrepro_inventory_app`
  es trabajo operativo / Fase 1E+. No se cambió el sync.
- Reaplicar el DDL **no** revoca un `GRANT EXECUTE` extra que el owner haya
  dado a un rol cualquiera. Solo limpia PUBLIC / anon / authenticated /
  service_role (si existen) y otorga al grupo de app si el rol existe.
- AJUSTE con `EXECUTE` puede sumar o restar sin cupo comercial. Eso es estructural
  y queda a la capa de negocio cuando existan writers.
- `p_usuario_id` / `device_id` siguen siendo metadato. No hay JWT de usuario.
- Writers productivos no usan el coordinador. `APPLY_AUTHORITATIVE_EXCLUDE` sigue
  `False`. INV-02 (LWW de `productos.stock`) sigue abierto. INV-01 no se declara
  resuelto en SQLite (el xfail de dos archivos locales sigue).
- Autoridad offline / fencing / barcodes / recepción: no hechas.

**STOP — no migrar writers productivos.**
