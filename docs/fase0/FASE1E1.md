# Fase 1E.1 — Writers negativos preparados, cutover OFF

**Estado:** implementada. Cutover **OFF**. No activa autoridad.
**No autoriza 1E.2, 1E.3 ni cutover.**
**No declara INV-01 resuelto en SQLite.** **No declara INV-02 resuelto.**
`APPLY_AUTHORITATIVE_EXCLUDE` sigue `False`.

## Qué es 1E.1

Preparó en código los **5 writers negativos** para la autoridad central
futura, **sin activar cutover**. El default productivo sigue siendo
legacy: `productos.stock` es la ruta efectiva.

| Writer | Función | Preparado | Default |
|---|---|---|---|
| W03 | `VentasService.registrar_venta` | sí | legacy |
| W16 | `LocalFerreteriaAPI.create_sale` | sí | legacy |
| W06 | `VentasService.agregar_productos_a_factura` | sí | legacy |
| W02 | `ComprasRepository.eliminar_compra` | sí | legacy |
| W15 | `MezclasService.descontar_stock_mezcla` | sí (DEPRECATED/DEAD) | legacy |

No se migraron positivos ni mixtos (W01, W04, W05, W07–W14, W17, W18).

## Pre-cutover / backlog

Riesgo: si una venta legacy descuenta `productos.stock` **y** deja un
`inventory_commands` `PERSISTED` replayable, el seed de 1E.3 desde el
stock actual + replay aplicaría el descuento **otra vez**.

Solución (opción B, mínima y demostrable):

- Columna local SQLite `inventory_commands.intent_class`
  (`AUTHORITATIVE` \| `LEGACY_OBSERVED`). No es un estado del CHECK
  `PERSISTED/APPLIED/REJECTED`. No se añadió a PostgreSQL remoto: esos
  comandos **nunca** se envían.
- `submit()` con cutover OFF persiste `LEGACY_OBSERVED` y **no transmite**.
- El gateway se niega a transmitir `LEGACY_OBSERVED` **para siempre**,
  incluso si el cutover se enciende después
  (`GatewayPreCutoverBacklogError`, `list_transmittable_command_ids`).
- Los writers negativos en default **no llaman** `submit()`: 0 comandos
  autoritativos y 0 observados en una venta real.

Filas 1C/1E.0 sin columna reciben `LEGACY_OBSERVED` (no `AUTHORITATIVE`):
`ALTER TABLE … ADD COLUMN intent_class … DEFAULT 'LEGACY_OBSERVED'`.
`list_transmittable_command_ids` trata NULL como `LEGACY_OBSERVED`.
Un `PERSISTED` pre-cutover no entra a la lista transmissible.

## Dos caminos por writer

**LEGACY (default, `INVENTORY_CUTOVER_ENABLED = False`):**

- comportamiento de negocio caracterizado en 1E.0
- `UPDATE productos.stock` permanece
- no RPC, no dual-write, no command autoritativo replayable

**AUTHORITATIVE (solo tests / futuro cutover, inyección explícita):**

- un `InventoryCommand` por documento (multilínea = N operations)
- `command_id` persistido antes de red
- `producto.local_id`; sin `local_id` → fallo cerrado, no llega al coordinador
- cantidad vía `commercial_quantity_to_scaled` → entero escala 1000
- `operation_id = uuid5(command_id, line_N)` estable en retry
- APPLIED permite completar el documento. Un retry con el mismo
  `command_id` **no** inserta una segunda venta: el command queda ligado a
  `ventas.local_id` (`bind_inventory_command_documento`).
- REJECTED no finge éxito comercial
- UNKNOWN conserva `command_id`; no completa el documento; retry el mismo id
- validación comercial (descuento > subtotal) ocurre **antes** de APPLY
- no `UPDATE productos.stock` (no dual-write)

El camino autoritativo **no** está activado globalmente. Se prueba con
`inventory_mode="authoritative"` + transport/factory inyectados.
La UI de POS todavía no plombea `inventory_command_id` (cutover OFF).
Eso es precondición de 1E.3, no de 1E.1.

## Semántica por writer

### W03 `registrar_venta`

Valida líneas, abre TX, crea venta/detalles/movimientos `SALIDA_VENTA`,
mezclas llegan como componentes ya expandidos por la UI (no W15).
Guard SQL `WHERE stock >= ?`. Si una línea no tiene stock, rollback de
toda la venta. Autoritativo: un command `VENTA` con todas las líneas.

### W16 `create_sale`

POS LAN paralelo a W03. Mismo builder (`build_negative_operations`) y
mismos outcomes. UNKNOWN HTTP 503 + `command_id` retryable. El persist
del command ocurre **antes** de `BEGIN` del documento para que un
rollback de venta no borre la identidad. `inventory_mode` **no** se
lee del JSON HTTP: un cliente LAN no puede activar autoridad
writer-por-writer. Solo kwargs de test/inyección. Descuento inválido
se rechaza **antes** de APPLY. Retry APPLIED con el mismo
`inventory_command_id` no crea una segunda factura.

### W06 `agregar_productos_a_factura`

Legacy: check previo no atómico; `UPDATE` sin `stock>=`; **puede ir
negativo** (no se “arregló”). Autoritativo: el coordinador decide
insuficiencia (`REJECTED`). Tipo `VENTA`.

### W02 `eliminar_compra`

No borra la fila. Marca `CANCELADA` y crea `SALIDA_AJUSTE` compensatorio.
Anti-doble-cancelación conservado. Ledger: tipo **`AJUSTE`** (ya existía);
no se inventó un tipo nuevo.

### W15 `descontar_stock_mezcla`

Confirmado huérfano: 0 callers de producción. La UI de mezclas descuenta
vía W03. **No se borra.** Flag `W15_DEPRECATED`. Autoritativo usa tipo
`VENTA` (solo consumo negativo). `MEZCLA` del ledger exige signos mixtos
y no aplica a este writer. Test que impide reintroducir callers.

## UNKNOWN / timeout / deadlock

Tras persistir, `CoordinatorUnknownOutcomeError`,
`CoordinatorTimeoutError`, `CoordinatorDeadlockError`,
`OperationalError` e `InterfaceError` se mapean a outcome `UNKNOWN`
(ledger local `PERSISTED`, mismo `command_id`).
`InventoryGatewayError` local (p. ej. SQLite como autoridad) **no** es
UNKNOWN: se sabe que no hubo COMMIT remoto.

## Scanner

Asocia writer con archivo + función/método + SQL. Distingue
`LEGACY_ALLOWED_PRE_CUTOVER` de `UNTRACKED_DIRECT_WRITER`. Las closures
W17/W18 se atribuyen a la función anidada, no al padre. Cutover OFF:
el SQL legacy de los negativos **sigue permitido**.

## Deudas 1E.0

| Deuda | 1E.1 |
|---|---|
| Scanner a nivel función | cerrada |
| Timeout/deadlock → UNKNOWN | cerrada |
| Reconnect sin `transport=` inyectado | test adicional pasa por `apply_inventory_command` |
| W17/W18 closures PySide | **aplazada a 1E.2** (positivos/mixtos) |

## Qué ocurrirá en cutover (1E.3, no ahora)

1. Migrar el resto de writers (1E.2).
2. Seed one-shot de `inventory_balances` desde el stock actual.
3. Encender `INVENTORY_CUTOVER_ENABLED`.
4. Solo commands `AUTHORITATIVE` + `PERSISTED` son transmissible.
5. `LEGACY_OBSERVED` permanece inaplicable.
6. Decisión sobre `productos.stock` / LWW.

## Writers que faltan (1E.2)

Positivos: W01, W04, W05, W09, W18.
Mixtos: W07, W08, W10, W11, W12, W13, W14, W17.
Derivados D01–D04 no se migran como writers; LWW se decide en 1E.3.

## STOP

**STOP — no implementar 1E.2.** No cutover. No seed. No barcodes. No recepción.
