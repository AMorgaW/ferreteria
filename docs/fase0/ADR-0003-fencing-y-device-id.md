# ADR-0003 — Fencing, device_id y split-brain

- **Estado:** especificado. **No implementado.** Obligatorio antes de
  habilitar `OFFLINE_INVENTORY_AUTHORITY`.
- **Fase de código:** posterior a Fase 0.

## Problema

Sin identidad de dispositivo y sin lease, “solo la PC de bodega confirma
offline” es un comentario. Hostname, IP, MAC y username cambian, se
clonan y se falsifican. La columna `SYNC_TABLES.device_id` actual es
metadato de fila, no identidad del equipo, y **nadie la escribe** hoy
(solo se añade el ALTER).

Dos copias de la misma SQLite, o un cambio de autoridad mientras el
antiguo sigue aislado, son split-brain.

## Decisión: identidad

Archivo **no sincronizado** `{data_dir}/config/device_identity.json`:

```json
{
  "device_id": "<uuid4>",
  "created_at": "<iso local>",
  "instance_nonce": "<uuid4 al arrancar, no persistido como autoridad>"
}
```

Reglas:

- Se genera una vez con `uuid.uuid4()`. Nunca se deriva de hostname,
  IP, MAC, username ni `machine-id` del OS.
- No se pushea a Supabase como “quién soy”. Clonar el archivo clona la
  identidad: es riesgo operativo, no se resuelve en software v1.
- Revocación: tabla remota `device_registry(device_id PK, status,
  authority_epoch, lease_until, revoked_at, note)`.
- Un device revocado no confirma ni online ni offline.

`instance_nonce` en memoria detecta dos procesos contra el mismo archivo
en el mismo OS (lock file). No detecta dos máquinas con el archivo
copiado.

## Decisión: autoridad y lease

Registro remoto único (conceptual):

```text
inventory_authority
  device_id
  epoch          entero monotónico; sube en cada reasignación/revoke
  lease_until    timestamptz emitido por PostgreSQL
  lease_seconds  p.ej. 4 horas
```

Mientras está **online**, la autoridad renueva el lease en cada ciclo
de sync. Cache local (no autoridad por sí sola):

```text
{ device_id_autoridad, epoch, lease_remaining_monotonic }
```

`lease_remaining_monotonic` se captura en el último sync exitoso como
segundos restantes y se consume con `time.monotonic()`, **no** con el
reloj de pared. Un rollback de fecha del Windows no alarga el lease.

### Confirmar offline (v1)

Permitido solo si **todas** son verdaderas:

1. `device_id` local = `device_id_autoridad` cacheado.
2. `epoch` local = `epoch` cacheado (no hay epoch más nuevo conocido).
3. Queda lease monotonic > 0.
4. El device no está en la caché local de revocados.
5. La operación lleva `operation_id` y se registra en un outbox de
   ledger local con `resultado_local=APPROVED` y
   `estado_remoto=PENDING_REMOTE`.

Cualquier otra terminal offline: rechazo `NOT_INVENTORY_AUTHORITY`.

### Reconciliación al reconectar (obligatoria, no silenciar)

PostgreSQL revalida el mismo `operation_id`:

1. Si el remoto ya tiene esa operación → devolver su `resultado`
   (idempotencia). Alinear proyección local a la proyección remota.
2. Si no existe y el epoch/lease siguen vigentes y hay stock →
   APPROVED remoto. Marcar `estado_remoto=SYNCED`.
3. Si REJECTED (epoch subió, lease inválido, stock global insuficiente,
   device revocado):
   - El resultado **remoto** manda.
   - Aplicar compensación local: delta inverso sobre la proyección
     (`−delta` original) en la **misma** transacción local que marca
     `resultado_local=REJECTED_REMOTE` y `estado_remoto=REJECTED`.
   - El documento de negocio (venta/recepción) pasa a
     `CONFIRMACION_RECHAZADA_REMOTA`. No se borra.
   - Mostrar el rechazo al operador. Mercancía ya entregada al cliente
     es riesgo operativo aceptado en v1 (igual que el clon de disco).
   - **Prohibido** dejar local APPROVED y remoto REJECTED.

Sin este protocolo no se habilita autoridad offline.

### Reasignar autoridad

1. Incrementar `epoch`.
2. Cambiar `device_id`.
3. Emitir lease nuevo.
4. Procedimiento operativo: no reasignar si el anterior sigue aislado
   **dentro** de su lease, salvo destrucción confirmada del equipo.

## Split-brain que v1 **acepta** (no fingir que está resuelto)

| Caso | Por qué queda |
|---|---|
| Clon de disco de la autoridad (mismo `device_id`, mismo lease cacheado) | Dos procesos cumplen las 5 reglas |
| Reasignación dentro del lease mientras el viejo está aislado | El viejo sigue confirmando hasta `monotonic` 0 |
| Operador ignora el rechazo y entrega mercancía igual | Problema de proceso, no de serialización |

v1 documenta estos casos. No se implementa Paxos entre ferreterías.

## Lo que v1 **sí** cierra

- Terminal B offline, no autoridad: no confirma.
- Terminal B online: confirma vía PostgreSQL; serializa con A.
- Lease expirado: nadie confirma offline hasta renovar en línea.
- Identidad no es hostname.

## Implementación

Prohibida en Fase 0. Este ADR es el spec que faltaba antes de código.
