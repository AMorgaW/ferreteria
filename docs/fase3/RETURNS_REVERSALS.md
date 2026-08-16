# Contrato devoluciones / anulaciones / reversos (Fase 3C)

## Regla

Un documento COMPLETED no se corrige editándolo. Toda corrección es:

**nuevo documento** + **operación inversa** + **referencia al original**.

## Customer return

Venta original (p. ej. A:5, B:2) → devolución parcial A:2 → inventario A +2.  
No se puede devolver más que el neto (`vendido − ya devuelto`).  
Devolución total = todo lo pendiente. Retry del mismo `command_id` no duplica efecto.

## Sale void

Anulación operacional = reverso explícito (`SALE_VOID`), no DELETE.  
Si ya hay devoluciones parciales, el void solo cubre el neto pendiente. No hay doble devolución.

No hay reglas fiscales nuevas.

## Supplier return

Recepción +10 → devolución proveedor 3 → inventario −3.  
No se puede devolver más que lo recibido neto.  
Si el balance actual no alcanza (se recibieron 10, se vendieron 8, devolver 5): REJECT `INSUFFICIENT_STOCK`. No hay stock autoritativo negativo silencioso.

## Packaging

Módulo canónico: `packaging_conversion.py` (el mismo de 3A/3B).

1 FULL_PACKAGE con factor 50 KG → devolución +50 KG (mismo `inventory_balance`).  
1 CAJA ×12 en compra → devolución proveedor 1 CAJA → −12 unidades base.  
No hay stock por empaque.

## Inventory authority

ONLINE: `inventory_balances` PostgreSQL. Writer: `tipo=DEVOLUCION`, operations positivas (cliente/void) o negativas (proveedor), `command_id` durable antes del RPC.

`productos.stock` no es autoridad.

## Atomicidad

Un command, N operations. Si B falla: 0 efecto, 0 documento COMPLETED.

## Idempotencia y recovery

`inventory_command_id` se persiste en `reversal_documents` **antes** del RPC. Retry / respuesta perdida reanuda el mismo id. APPLIED + documento local COMPLETED = un reverso. UNKNOWN: el DRAFT/APPLYING conserva el id.

## Concurrencia

El coordinador serializa el cupo retornable del documento original (`inventory_reversal_allocations`) en la misma transacción que el inventario.

Venta cantidad=1, W01 y W02 devuelven 1: 1 SUCCESS + 1 REJECT.  
Recepción 5, W01 y W02 devuelven 3: neto ≤ 5.

Laboratorio: `ferrepro-pg-test` / `localhost:55432`.

## Trazabilidad

Cada reverso tiene `local_id`, `kind`, original (`tipo` + `id` + `local_id`), líneas, cantidades, fecha, usuario, `command_id`, estado.

Se puede responder: qué documento originó el movimiento, y qué reverso afectó el original.

## Local-first / UI

Historial y DRAFT abren desde SQLite. CONFIRMAR respeta el gate ONLINE (`return_finalize_allowed`). ENTER del scanner no confirma. Botón deshabilitado en vuelo. `FunctionWorker` fuera del hilo GUI.

Desde venta completada: **Devolver / Anular**.  
Desde recepción completada: **Devolver a proveedor**.

## Limitaciones

- El camino legado `VentasService.registrar_devolucion` / `cancelar_venta` (W04/W05) no se certificó como 3C y **no es alcanzable desde la UI de producción**. `ui/ventas_ui_modern.cancelar_venta` solo vacía el carrito. Los botones **Devolver / Anular** y **Devolver a proveedor** llaman `ReturnsService`. Las APIs W04/W05 se conservan por tests/compatibilidad; no son el escritor productivo de reversos.
- `agregar_productos_a_factura` / `eliminar_linea_factura` (W06/W18) siguen existiendo para crédito legado; 3C no los usa.
- Cross-station: el central impide over-return (`inventory_reversal_allocations` + cap por `original_command_id`). Una estación distinta **no** puede completar un reverso solo con el `id` SQLite local de otra caja. Hace falta el `local_id` del documento original **y** el `command_id` de inventario en el SQLite de esa estación. `ventas` puede llegar por LWW; `inventory_commands` no. 3A no persiste `ventas.inventory_command_id`. Sin esa identidad el coordinador falla cerrado (`ORIGINAL_DOCUMENT_NOT_FOUND`). No es sync completo de documentos comerciales.
- Identidad canónica del original = `original_command_id` (UUID durable del ledger). No se usa el `id` entero SQLite como identidad remota. 3A no siempre envía `documento_local_id` al submit inicial; el bind local posterior no actualiza PostgreSQL. El cupo remoto se resuelve por `original_command_id`.
- Empaquetado: `postgres_coordinator_sql()` carga `supabase_inventory_coordinator.sql` junto al módulo / `sys._MEIPASS`. `Ferreteria.spec` debe incluir ese archivo en `datas` (ya no va embebido en el `.py`).

## Inventario comercial

Diferido. Tests no usan `ferreteria.db` ni Supabase real.
