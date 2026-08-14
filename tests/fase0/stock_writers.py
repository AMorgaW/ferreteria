# -*- coding: utf-8 -*-
"""Inventario canónico de writers de stock (Fase 0). El scanner falla si aparece otro."""

# Archivos de producción que contienen `UPDATE productos … stock`.
# Si se añade un writer, hay que actualizar este set Y docs/fase0/STOCK_WRITERS.md.
UPDATE_STOCK_FILES = frozenset({
    "repositories/compras_repo.py",
    "services/ventas_service.py",
    "repositories/productos_repo.py",
    "services/movimientos_service.py",
    "repositories/inventario_repository.py",
    "services/mezclas_service.py",
    "local_server.py",
    "ui/dashboard_ui.py",
})

# INSERT de stock inicial (no es UPDATE, se rastrea aparte).
INSERT_STOCK_FILES = frozenset({
    "repositories/productos_repo.py",
})

# Publicación LWW del snapshot de stock.
SYNC_STOCK_SNAPSHOT_FILES = frozenset({
    "local_first_db.py",
    "local_sync.py",
    "repositories/_outbox.py",
})
