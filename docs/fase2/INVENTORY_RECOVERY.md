# Recuperación de Inventory Apply

## Reinicio o timeout

Al abrir un batch `APPLYING` cuyo lease expiró, o `PARTIALLY_FAILED`, la UI debe
mostrar `REANUDAR / RECONCILIAR`. Nunca inicia desde cero.

1. Leer el plan aprobado y verificar su hash.
2. Saltar filas `VERIFIED` y `NO_CHANGE_VERIFIED`.
3. Para `INVENTORY_UNKNOWN`, reenviar el mismo `command_id` y la misma operación.
4. El coordinador PostgreSQL devuelve el resultado ya aplicado o aplica una
   única vez.
5. Releer producto, metadata y balance antes de marcar la fila verificada.

Si el producto ya fue creado, se conserva. No se borra ni se crea otro; su
`producto_local_id` reservado permite una relectura determinista.

## Fallo parcial

Las filas completadas permanecen verificadas y no se reenvían. Las fallidas se
reanundan con sus identidades originales. El batch permanece
`PARTIALLY_FAILED` hasta resolver todas las filas; nunca se declara completo
con UNKNOWN, ERROR o STALE.

## Detención operativa

`Detener nuevas filas` persiste `stop_requested`. El worker termina después de
la operación en curso y deja el batch `PARTIALLY_FAILED / NEEDS_RECONCILIATION`.
No existe rollback masivo ni compensación destructiva.

## Stale balance

No se reenvía el delta anterior. Se muestra base aprobada, base actual, conteo
físico y delta recalculado; luego se requiere una aprobación nueva.

## Runbook de laboratorio

- SQLite: fixture o copia temporal creada por el harness.
- PostgreSQL: exclusivamente `ferrepro-pg-test`, `localhost:55432`, base
  `ferrepro_test`.
- Nunca usar `SUPABASE_URI`, service role, owner ni `ferreteria.db` comercial.
- Antes de un diagnóstico físico de la DB real, detener `local_server` o hacer
  una copia estable. Este runbook no autoriza APPLY comercial.

