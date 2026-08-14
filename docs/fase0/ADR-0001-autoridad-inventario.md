# ADR-0001 — Autoridad de inventario distribuido

- **Estado:** aceptado (diseño). No implementado.
- **Fase de código:** posterior a Fase 0, con GO humano.

## Contexto

Cada PC tiene SQLite independiente. `productos.stock` se muta localmente
y se publica como snapshot vía `sync_queue`. El pull/push hace
`ON CONFLICT(local_id) DO UPDATE SET stock=EXCLUDED.stock`.
El background sync ronda los 45 s (`pull_interval_seconds`).

Dos terminales con stock local 50 pueden vender 50 cada una. Ambas SQLite
aprueban. No hay transacción compartida. Acelerar el pull no elimina la
ventana; solo la estrecha.

## Decisión

1. **Online:** PostgreSQL es la autoridad. La confirmación de toda
   operación de inventario pasa por una función/operación central
   atómica e idempotente (ver ADR-0002).
2. **Offline v1:** una sola terminal `OFFLINE_INVENTORY_AUTHORITY`
   puede confirmar sin red. Las demás no.
3. `productos.stock` local es proyección, no autoridad LWW.

## Consecuencias

- Ventas, compras/recepción, devoluciones, ajustes y mezclas acaban
  en el mismo cuello de botella de autoridad. No se “arregla solo
  recepción”.
- El POS LAN (`local_server.create_sale`) y el admin
  (`VentasService`) dejan de ser autoridades.
- Sin red y sin ser la autoridad, el operador no cierra venta de stock
  ni recepción confirmada. Eso es un cambio de producto; requiere GO.
- Fencing: ADR-0003. No implementar autoridad offline sin fencing.

## Alternativas rechazadas

| Alternativa | Por qué no |
|---|---|
| Bajar intervalo de sync | Sigue habiendo dos commits locales |
| CRDT / LWW de stock | Stock no es mergeable; 50−50 y 50−50 no promedian |
| Bloqueo LAN entre PCs | No cubre aislamiento; el POS LAN no es el sync actual |
| “El primero que haga push gana” | El segundo ya vendió físicamente; el snapshot pisa al primero |
