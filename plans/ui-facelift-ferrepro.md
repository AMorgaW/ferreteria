# Plan: Rediseño visual "FERREPRO" — Sistema de Ferretería (PySide6)

> **Objetivo:** Modernizar TODA la interfaz para que luzca como los mockups FERREPRO
> (sidebar navy oscuro, acento ámbar, tarjetas limpias con sombra suave, tablas con
> header oscuro, botones redondeados, hover/transiciones naturales).
>
> **Restricciones duras (no negociables):**
> 1. NO tocar la capa de datos: `database.py`, `pg_compat.py`, `repositories/`,
>    `services/`, `local_*`, `models.py`, `auth.py`. Solo presentación.
> 2. NO cambiar lógica ni funcionalidad. Solo aspecto visual y micro-interacciones.
> 3. Conservar las claves semánticas existentes en `COLORS` para no romper los
>    cientos de `setStyleSheet` que las referencian.

---

## Fase 0 — Discovery (COMPLETADA)

**Arquitectura de tema:** `ui_config.py` expone `COLORS` (dict) + `GLOBAL_QSS`
(generado por `_build_qss()`), aplicado globalmente vía `app.setStyleSheet(GLOBAL_QSS)`.
Componentes reutilizables en `ui/widgets.py`: `ShadowCard`, `HoverButton`,
`ActionButton`, `KpiCard` — todos leen de `COLORS`.

**Inventario de superficie a re-estilizar (líneas / nº de `setStyleSheet`):**

| Archivo | Líneas | styles | usa widgets.py |
|---|---|---|---|
| ui/reportes_ui.py | 3350 | 217 | no |
| ui/dashboard_ui.py | 2540 | 100 | sí |
| ui/ventas_ui_modern.py | 2097 | 117 | sí |
| ui/compras_ui.py | 1742 | 101 | sí |
| ui/movimientos_ui.py | 1675 | 91 | no |
| ui/caja_ui.py | 1274 | 74 | no |
| ui/productos_ui.py | 811 | 33 | no |
| ui/clientes_ui.py | 788 | 21 | no |
| main.py (shell+login) | 647 | 30 | sí |
| ui/usuarios_ui.py | 426 | 25 | no |
| ui/proveedores_ui.py | 419 | 17 | no |
| ui/alertas_ui.py | 310 | 23 | no |
| ui/local_first_admin_ui.py | 227 | 7 | no |
| ui/buscar_proveedor_dialog.py | 152 | 8 | no |
| ui/buscar_producto_dialog.py | 135 | 8 | no |

**Riesgo principal:** muchos `setStyleSheet` hardcodean hex (p.ej. el navy viejo
`#0C3547`, blancos, grises). Repaletizar `COLORS` arregla el QSS global y los widgets,
pero **cada estilo inline con hex literal debe auditarse** por sección.

---

## Tokens de diseño FERREPRO (la "fuente de verdad" nueva)

Se actualizan VALORES en `COLORS` (mismas claves) y se AÑADEN claves nuevas:

```
# Marca / acento (ámbar FERREPRO)
accent           #F5A623   accent_dark   #D98E1F   accent_light #FCEFD6
# Sidebar oscuro
sidebar_bg       #0E1726   sidebar_fg    #AEB9C7
sidebar_active_bg #F5A623  sidebar_active_fg #0E1726
sidebar_hover_bg #1B2940   sidebar_hover_fg #FFFFFF
sidebar_brand    #FFFFFF
# Fondos
bg_secondary     #F4F5F7   (content)     bg_primary #FFFFFF (cards)
# Tabla header oscuro
table_header     #1E2A3C   table_header_fg #E5E9F0
# Texto
text_primary     #1A2332   text_secondary #64748B
# Estados (se conservan): success #22C55E/#16A34A, danger, warning≈accent, info
```

`primaryBtn` → ámbar (CTA de marca). Se añade `successBtn` (verde) para "Guardar/
Finalizar Venta". `dangerBtn`, `warningBtn` se mantienen. Foco de inputs → ámbar.

---

## Fase 1 — Sistema de diseño  (`ui_config.py` + `ui/widgets.py`)

**Qué hacer:**
1. `ui_config.py` → reescribir VALORES de `COLORS` a los tokens FERREPRO de arriba,
   AÑADIENDO las claves nuevas (`accent*`, `sidebar_*`, `table_header_fg`). Mantener
   todas las claves existentes para compatibilidad.
2. `_build_qss()` → `QPushButton#primaryBtn` ámbar; añadir `#successBtn` verde;
   radios "pill" (botones 10px, inputs 8–10px); foco ámbar; `QHeaderView::section`
   con `table_header` + `table_header_fg`; refinar scrollbars/menus/tooltips.
3. `ui/widgets.py`:
   - `HoverButton._apply_style()` ya soporta active/hover por args — sin cambio de API.
   - Añadir `AnimatedCard` (subclase de `ShadowCard`) con `enterEvent`/`leaveEvent`
     que animan blur/offset de la sombra vía `QPropertyAnimation` → "elevación" suave
     al pasar el mouse (transición natural). `KpiCard` puede heredar de ella.
   - Añadir helper `Badge`/`pill(text,color)` y `section_title()` reutilizables.

**Verificación:** `python main.py` (o `run.bat`) → login y sidebar ya muestran navy +
ámbar; ninguna sección crashea al abrir (el QSS global aplica). `grep` que no queden
referencias rotas a claves de COLORS eliminadas (no se elimina ninguna).

**Anti-patrones:** no borrar claves de `COLORS`; no usar propiedades CSS inexistentes
en Qt (`box-shadow`, `transition`, `transform` NO existen en QSS — las sombras van por
`QGraphicsDropShadowEffect`, las transiciones por `QPropertyAnimation`).

---

## Fase 2 — Shell de la app  (`main.py`: sidebar + header + login)

1. **Sidebar** (`_build_sidebar`, ~L293): fondo `sidebar_bg`; marca FERREPRO (logo
   hexagonal/placeholder + "FERRE" blanco + "PRO" ámbar + "SISTEMA DE INVENTARIO");
   `HoverButton` con `bg=transparent, fg=sidebar_fg, hover_bg=sidebar_hover_bg,
   active_bg=sidebar_active_bg, active_fg=sidebar_active_fg`. Reemplazar textos en
   inglés ("Main Hub/Sector 7G", "New Requisition", "Support", "Log Out") por
   "Nueva Requisición", "Soporte", "Cerrar Sesión".
2. **Header** (~L227): avatar con nombre/rol, campana de alertas, engranaje, chip de
   fecha — fondo blanco con borde inferior sutil.
3. **LoginDialog** (~L48): fondo oscuro, tarjeta translúcida, logo hexagonal, labels
   con iconos (Usuario/Contraseña), botón "Iniciar Sesión" ámbar, ojo show/hide,
   "¿Olvidaste tu contraseña?".

**Verificación:** login luce como el mockup oscuro; sidebar navy con ítem activo ámbar;
navegación entre secciones resalta el ítem correcto.

---

## Fase 3 — Dashboard  (`ui/dashboard_ui.py`)

KPI cards de colores (Ventas Hoy navy, Ventas Mes verde, Stock Crítico ámbar, Cuentas
por Cobrar navy) usando `KpiCard`/`AnimatedCard`; tarjeta "Análisis de Ventas - Últimos
7 Días"; auditar los 100 estilos inline → tokens. Verificación: abrir Dashboard, KPIs y
gráfico con el nuevo look, hover eleva las cards.

## Fase 4 — Catálogo  (`ui/productos_ui.py`)

Tabla con header oscuro + filas limpias; toolbar de búsqueda/Filtros; "Nuevo Producto"
ámbar; formulario "Nuevo Producto" en 3 columnas (Información Básica / Inventario /
Información) con panel de ayuda ámbar claro. Introducir `ShadowCard`+tokens (hoy no usa
widgets). Verificación: lista y alta de producto como en mockups.

## Fase 5 — Proveedores y Compras  (`ui/proveedores_ui.py`, `ui/compras_ui.py`)

Gestión de Proveedores (tabla, estrellas de calificación, badges Activo); form "Nuevo
Proveedor" con panel "Información" lateral; Compras: 4 KPIs, banner "DEUDAS | RESUMEN"
marrón, tabla "Historial de Transacciones". Verificación: ambas secciones y sus forms.

## Fase 6 — Punto de Venta y Caja  (`ui/ventas_ui_modern.py`, `ui/caja_ui.py`)

POS: pestañas Contado/Crédito, buscador + chips de categoría, lista de productos con
avatar de iniciales y badge de stock, panel "Resumen de Venta" lateral (cliente, método
de pago en tiles, carrito, totales, "FINALIZAR VENTA" verde). Caja: tarjetas/arqueo.
Verificación: flujo de venta visualmente nuevo, sin tocar la lógica de cálculo.

## Fase 7 — Movimientos y Reportes  (`ui/movimientos_ui.py`, `ui/reportes_ui.py`)

Archivos más grandes. Tablas, filtros, tabs y tarjetas de reportes al nuevo sistema.
Auditar hex inline (217 + 91). Verificación: cada pestaña de reportes y movimientos.

## Fase 8 — Secundarios  (`clientes_ui.py`, `usuarios_ui.py`, `alertas_ui.py`,
`local_first_admin_ui.py`, `buscar_producto_dialog.py`, `buscar_proveedor_dialog.py`)

Consistencia final de tablas/forms/diálogos con los tokens. Verificación: abrir cada uno.

---

## Fase 9 — Verificación final

1. `grep` de hex legacy huérfanos (p.ej. `#0C3547`, `#091F32`) fuera de `ui_config.py`
   → idealmente 0; los restantes, justificados.
2. Abrir cada sección desde la app (admin) y revisar: colores, header de tablas,
   botones, hover/elevación de cards, foco ámbar en inputs.
3. Regenerar el ejecutable: `python -m PyInstaller Ferreteria.spec` (o el comando
   onefile) y arranque rápido de humo.

---

## Estrategia de ejecución

- Fases **1–2 dan el ~70% del impacto visual** (tema + shell + login) y son las más
  seguras. Se hacen primero y se verifican corriendo la app.
- Cada fase es autocontenida y verificable corriendo la app → ideal para checkpoints.
- Orden por impacto/uso: 1 → 2 → 3 → 6 (POS) → 4 → 5 → 7 → 8 → 9.
