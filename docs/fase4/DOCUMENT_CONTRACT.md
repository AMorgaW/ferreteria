# Contrato documental operacional (Fase 4C)

## Qué es

Un documento operacional es un comprobante **read-only** de una operación ya COMPLETED o de un cierre CLOSED. No es factura fiscal, DIAN ni documento electrónico.

Etiqueta obligatoria:

`DOCUMENTO OPERACIONAL / NO FISCAL`

## Efectos

Generar, previsualizar, imprimir o guardar PDF:

- 0 escrituras de inventario
- 0 `cash_movements` nuevos
- 0 pagos / ventas / compras / reversos
- 0 sync de red

Reimprimir N veces produce el mismo texto (mismos valores durables).

## Identidad

| Documento | Identidad preferida |
|-----------|---------------------|
| Venta | `ventas.local_id`, `numero_factura` |
| Recepción | `compras.local_id`, factura proveedor |
| Reverso | `reversal_documents.local_id` + original |
| Cierre | `cierres_caja.local_id` |
| Abono | `abonos_*.local_id` |

DRAFT / OPEN no emite documento final (`DocumentNotFinal`).

## Fuentes canónicas

- Venta: `ventas` + `detalle_ventas` (precio/cantidad/subtotal durables)
- Compra: `compras` + `detalle_compras` COMPLETED
- Reverso: `reversal_documents` + `reversal_lines` COMPLETED
- Caja: snapshot `cierres_caja` CLOSED + `cash_movements` de esa sesión
- Saldos de abono: `operational_balance` + abonos hasta ese `id`

## Renderer

Única capa de reglas: `services/document_service.py`.

UI: `ui/imprimir_factura.py` (preview / QPrinter 58mm / PDF).

## Dinero y cantidades

Decimal vía `money()` antes de `$`. No float. No `productos.stock`. No recálculo de empaque comercial.

## Reversos

Una devolución de 30 sobre venta 100 imprime el reverso = 30. No reescribe la venta original a 70.

`SUPPLIER_RETURN` no afirma reembolso de dinero. Cash IN exige evento financiero explícito (3D no crea caja para devolución a proveedor).

## Local-first

Sin Supabase, PostgreSQL ni Internet para reimprimir un documento ya persistido.
