# Fase 3A — Ventas / POS local-first + scanner

**Veredicto:** ver el cierre de ejecución. Inventario comercial: diferido.

## Alcance cerrado

Scanner HID → `product_barcodes` → carrito local → confirmación humana → `VentasService.registrar_venta` → inventory gateway/coordinator existente → comprobante mínimo.

## No incluido

3B, compras, devoluciones nuevas, caja nueva, facturación fiscal, PDF/XML, impresora avanzada, inventario real, fencing offline nuevo.

## Limitación de empaque

`FULL_PACKAGE` / `CUSTOM_PRESENTATION` solo descuentan si existe metadata canónica inequívoca (`unidades_por_caja` + flag de caja/empaque, o un único factor custom). Si falta: `BLOCKED_BY_PACKAGING_CONVERSION_CONTRACT`. `BASE_UNIT` no se bloquea.

## Datos

No se mutó `ferreteria.db` comercial ni Supabase real.
