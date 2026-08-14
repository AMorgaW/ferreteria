# ADR-0002 — Ledger de operaciones de inventario

- **Estado:** aceptado (diseño). No implementado.
- **Fase de código:** posterior a Fase 0.

## Contexto

Hoy cada writer hace `UPDATE productos SET stock = stock ± ?` o
`SET stock = ?` y encola la **fila producto** completa. No hay
`operation_id`. Un retry, un doble clic o un timeout tras commit
pueden aplicar el delta otra vez o publicar un snapshot viejo.

`VentasService` al crear venta sí usa `stock = stock - ? WHERE stock >= ?`
en un solo SQLite. Eso no serializa dos archivos SQLite distintos.

## Decisión

Introducir un ledger mínimo `InventoryOperation`:

| Campo | Rol |
|---|---|
| `operation_id` | UUID UNIQUE. Identidad de la intención. |
| `producto` | `local_id` global del SKU |
| `delta` | signed fixed-point |
| `tipo` | VENTA, RECEPCION, DEVOLUCION, AJUSTE, MEZCLA, … |
| `documento_origen` | tipo + id de negocio |
| `documento_local_id` | UUID del documento en el dispositivo |
| `device_id` | UUID del dispositivo (ADR-0003) |
| `usuario` | quién confirmó |
| `timestamp` | tiempo de la operación |
| `resultado` | APPROVED / REJECTED |
| `motivo_rechazo` | stock insuficiente, no-autoridad, etc. |

Algoritmo (online, en PostgreSQL):

1. `BEGIN`
2. Si existe `operation_id` → devolver su `resultado` (no mutar).
3. Bloquear la fila de proyección/stock del producto.
4. Si `stock + delta < 0` (o la regla del tipo) → REJECTED, commit, return.
5. Insertar operación APPROVED, aplicar delta a la proyección, commit.
6. El cliente local alinea su SQLite a ese resultado.

Retry / timeout post-commit: mismo `operation_id`, paso 2.

## Fuera de v1 del ledger

- Reescritura histórica de kardex `movimientos` / `movimientos_inventario`.
- Compensaciones automáticas de ventas ya entregadas al cliente.
- Cancelación compleja de compras confirmadas.

## Consecuencia para sync

El payload de `productos` **deja de llevar `stock` como campo
autoritativo** en el UPSERT LWW. El stock viaja por el ledger (o por
una proyección que solo escribe la autoridad). Fase de implementación
posterior; hoy el test de contrato marca xfail.
