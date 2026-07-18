# Arquitectura Local-First

Este proyecto ahora puede trabajar en modo local-first:

- La base principal de trabajo es `ferreteria.db` en el computador administrador.
- Las PCs trabajadoras se conectan al servidor local por WiFi/LAN.
- Supabase queda como respaldo remoto y destino de sincronizacion.
- Si no hay internet, las ventas se siguen guardando localmente y quedan en `sync_queue`.
- Cuando vuelve internet, el sincronizador reintenta subir los pendientes.

## Modo Servidor Administrador

1. En el computador principal, conecta la PC a la red WiFi/LAN de la tienda.
2. Opcionalmente configura variables:

```bat
set LOCAL_SERVER_HOST=0.0.0.0
set LOCAL_SERVER_PORT=8000
set LOCAL_DB_PATH=C:\ruta\ferreteria.db
set SUPABASE_URI=postgresql://...
set SYNC_INTERVAL_SECONDS=10
```

3. Ejecuta:

```bat
run_local_server.bat
```

O manualmente:

```bat
python local_server.py --host 0.0.0.0 --port 8000
```

4. Busca la IP local del servidor:

```bat
ipconfig
```

Ejemplo para PCs trabajadoras:

```text
http://192.168.1.10:8000
```

## Modo App Administrador

La app PySide puede trabajar contra SQLite local si `DB_MODE` es `local` o si no se define `DB_MODE`.

```bat
set DB_MODE=local
python main.py
```

Para volver temporalmente a Supabase directo:

```bat
set DB_MODE=supabase
python main.py
```

## Endpoints Locales

### Estado

```http
GET /health
```

### Login

```http
POST /auth/login
Content-Type: application/json

{
  "username": "admin",
  "password": "admin123"
}
```

La respuesta incluye `token`. Las siguientes llamadas usan:

```http
Authorization: Bearer TOKEN
```

### Productos

```http
GET /products?search=clavo&limit=100
```

Roles permitidos: `ADMIN`, `GERENTE`, `VENDEDOR`, `BODEGUERO`.

### Crear Venta

```http
POST /sales
Authorization: Bearer TOKEN
Content-Type: application/json

{
  "metodo_pago": "EFECTIVO",
  "cliente_id": null,
  "descuento": 0,
  "items": [
    {
      "producto_id": 5,
      "cantidad": 1,
      "precio_unitario": 350,
      "descuento": 0
    }
  ]
}
```

La venta se guarda localmente, descuenta inventario, crea movimiento y deja registros pendientes en `sync_queue`.

### Estado de Sincronizacion

```http
GET /sync/status
```

Solo administradores.

### Forzar Sincronizacion

```http
POST /sync/run
```

Solo administradores.

### Ver Cola

```http
GET /sync/queue?limit=100
```

Solo administradores.

## Nuevas Tablas

### `sync_queue`

Registra operaciones pendientes, sincronizadas o fallidas:

- `entity_type`
- `entity_id`
- `table_name`
- `operation`
- `payload`
- `status`
- `attempts`
- `last_error`
- `created_at`
- `updated_at`
- `synced_at`

### `sync_conflicts`

Guarda conflictos para revision del administrador.

### `sync_state`

Guarda estado global de sincronizacion:

- `last_attempt`
- `last_success`
- `last_error`

### `local_sessions`

Guarda sesiones emitidas por el servidor local.

## Columnas de Sincronizacion

En tablas principales se agregan, si faltan:

- `local_id`
- `remote_id`
- `updated_at`
- `deleted_at`
- `is_deleted`
- `sync_status`
- `last_synced_at`
- `version`
- `device_id`
- `created_by`
- `updated_by`

## Pruebas Manuales

### Escenario 1: venta local con internet

1. Ejecuta `run_local_server.bat`.
2. Inicia sesion con `POST /auth/login`.
3. Consulta `GET /products`.
4. Registra una venta con `POST /sales`.
5. Verifica que `GET /sync/status` muestre pendientes.
6. Espera 10 segundos o ejecuta `POST /sync/run`.
7. Verifica que los pendientes pasen a `synced` si Supabase esta disponible.

### Escenario 2: sin internet

1. Desconecta internet.
2. Mantén la red local WiFi/LAN activa.
3. Registra una venta con `POST /sales`.
4. Confirma que la respuesta sea exitosa.
5. Verifica que `GET /sync/status` muestre pendientes o fallidos.
6. Reconecta internet.
7. Espera el reintento automatico o ejecuta `POST /sync/run`.

### Escenario 3: permisos

1. Inicia sesion como vendedor.
2. Consulta productos: debe permitir.
3. Intenta `GET /sync/queue`: debe responder `403`.
4. Intenta `POST /sync/run`: debe responder `403`.

## Uso Diario

### Computador administrador

1. Ejecuta `run_admin.bat`.
2. Inicia sesion normalmente.
3. Abre `Configuracion`.
4. En la pestana `Servidor local`, confirma que el estado sea `activo`.
5. Copia la URL mostrada para las PCs trabajadoras.
6. En `Sincronizacion`, revisa pendientes, fallidos y conflictos. Tambien puedes forzar un intento con `Sincronizar ahora`.

El administrador trabaja directamente sobre `ferreteria.db`. El servidor HTTP se inicia automaticamente en segundo plano.

### Computadores trabajadores

1. Conecta el equipo a la misma red WiFi o LAN del administrador.
2. Ejecuta `run_client.bat`.
3. Si aparece la configuracion inicial, escribe la URL copiada desde el administrador. Ejemplo: `http://192.168.1.10:8000`.
4. Pulsa `Probar conexion`, guarda e inicia sesion.
5. Busca productos, agregalos al carrito y confirma la venta.

La aplicacion trabajadora no abre SQLite ni usa credenciales de Supabase. Solo consume la API HTTP local.

## Preparar Supabase

Antes de activar sincronizacion remota, ejecuta una vez `supabase_local_first_migration.sql` en el editor SQL de Supabase. El script agrega las columnas e indices requeridos por `ON CONFLICT(local_id)`.

Configura `SUPABASE_URI` en `.env` o como variable de entorno del computador administrador.

## Herramientas Operativas

- `run_admin.bat`: abre la aplicacion administrativa local.
- `run_client.bat`: abre el punto de venta remoto para trabajadores.
- `run_local_server.bat`: inicia solo el servidor HTTP para diagnostico.
- `run_sync_once.bat`: fuerza una sincronizacion remota desde consola.
- `check_local_first.bat`: revisa esquema, aislamiento del cliente y disponibilidad del servidor.

## Validacion Automatica

Ejecuta:

```bat
python -m unittest tests.test_local_first_integration -v
```

La prueba levanta un servidor temporal, inicia sesion, registra una venta remota sobre una copia de la base, valida stock, movimientos, cola, permisos y aislamiento del cliente.

## Siguiente Mejora Recomendada

- Programar backup local diario de `ferreteria.db`, incluyendo archivos WAL/SHM cuando esten activos.
