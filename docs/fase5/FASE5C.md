# Fase 5C — Legacy writer hardening

**Veredicto de implementación:** GO si `tests/fase5` y la regresión transversal pasan.

5C resuelve únicamente F5-M1 (writer LAN de ventas/inventario) y F5-L1 (rehash PBKDF2 silencioso). No es Fase 6, no toca `ferreteria.db` comercial, no abre inventario/caja/abonos reales y no crea `FASE5_FINAL.md`.

## Decisión F5-M1 — LAN DISABLED

El servidor HTTP LAN (`local_server.py`) **no es un writer comercial**.

El POS productivo (`ui/ventas_ui_modern.py`) llama `VentasService.registrar_venta`. Eso es el único camino de venta. El cliente LAN histórico (`client_app.py` / `LocalAPIClient.create_sale`) deja de poder vender.

No se mantiene un segundo writer paralelo. No se delegó `create_sale` a `VentasService`: el servidor LAN ya no es consumidor productivo necesario. La sincronización local-first corre in-app (push/pull), no depende del listener LAN.

### Auto-start

- `DEFAULT_CONFIG["auto_start_server"]` = `False`
- `lan_auto_start_enabled(config)` es True **solo** si `auto_start_server is True`
- Clave ausente → False. `main.py` ya no usa `.get("auto_start_server", True)`
- Un JSON histórico con `true` puede arrancar el listener de diagnóstico; **no** puede escribir `productos.stock` ni crear ventas
- Esta ejecución no reescribe `config/local_first_config.json` comercial

### Writer

`LocalFerreteriaAPI.create_sale` y `_create_sale_authoritative` responden **403** `LAN_SALES_DISABLED` en PRE_CUTOVER y POST_CUTOVER. No hay `float` de cantidad ni `UPDATE productos SET stock` en esa ruta.

GET de diagnóstico (`/health`, `/products`, `/sales/{id}` lectura) se conserva. POST `/customers` y sync no son el hallazgo F5-M1; no se convierten en autoridad de inventario.

### Inventario

| Estado | LAN | POS moderno |
| --- | --- | --- |
| PRE_CUTOVER | fail-closed; no escribe stock | `VentasService` (camino canónico) |
| POST_CUTOVER | fail-closed; no puede volver a ser autoridad de `productos.stock` | `VentasService` / command path |

`productos.stock` post-cutover sigue siendo proyección/cache. Ningún endpoint LAN reintroduce autoridad.

## F5-L1 — Auth rehash warning

`AuthManager.login` sigue permitiendo el acceso si las credenciales son válidas y el UPDATE de rehash PBKDF2 falla.

- No convierte un login válido en fallo
- No crea bypass
- Emite `WARNING` en el logger `auth` con `usuario_id`
- No registra password, hash, secrets ni connection string
- Hace `rollback` del error para no dejar la transacción SQLite abortada

## No hecho en 5C

- `FASE5_FINAL.md`
- Fase 6 / ingreso de productos / inventario real
- Cutover comercial de `inventory_cutover_state`
- Rediseño de autenticación o RBAC
- Borrado masivo de `local_server.py` / `client_app.py`
