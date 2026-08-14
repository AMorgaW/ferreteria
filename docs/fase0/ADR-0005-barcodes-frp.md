# ADR-0005 — Barcodes y código interno FRP

- **Estado:** aceptado (diseño). No implementado.
- **Fase de código:** posterior a Fase 0.

## Decisión

Todo producto **nuevo** tiene ≥ 1 código escaneable.

| Caso | Acción |
|---|---|
| Trae barcode comercial | Escanear, validar formato/checksum si aplica, UNIQUE global |
| No trae | Generar interno |

Formato interno (cerrado; no reabrir a 12 hex ni Crockford):

```text
FRP- + secrets.token_hex(8).upper()
regex: ^FRP-[0-9A-F]{16}$
ejemplo: FRP-7A91D2E48BC3814F
```

Generación: retry limitado ante colisión UNIQUE (p.ej. 8 intentos).
Prohibido: consecutivos, `max()+1`, `id` local, fecha, nombre,
tabla `consecutivos`.

Un producto puede tener varios códigos. El código identifica el **SKU**.
Dos cajas físicas del mismo SKU usan el mismo stock aunque se escaneen
códigos distintos asociados al mismo producto.

Alias / código de proveedor es **otro concepto**: no ocupa el espacio
de barcodes globales sin namespacing. No se imprime como FRP.

Históricos: no se reutilizan. Soft-delete del código no libera UNIQUE.
Productos actuales sin código no reciben FRP masivo en la migración.
Herramienta administrativa posterior.

Hoy: `productos.codigo_barras TEXT UNIQUE`, una sola columna.
`ProductosRepository._generar_sku_unico` usa categoría/marca/`id` local
y 4 hex — incompatible con este ADR.

Compatibilidad futura (no Fase 0): tabla `producto_codigos` + la columna
`productos.codigo_barras` como denormalización del principal de venta.
