-- FERREPRO Fase 1C — ledger de comandos de inventario.
-- SOLO PostgreSQL/Supabase. Nunca ejecutar contra SQLite.
-- Idempotente. No modifica productos.stock. No crea RPC.
-- Identidades UUID como TEXT (paridad con productos.local_id).
-- Tablas append-only/idempotentes: no entran al sync LWW genérico.

CREATE TABLE IF NOT EXISTS inventory_commands (
    command_id TEXT PRIMARY KEY,
    tipo TEXT NOT NULL CHECK (
        tipo IN (
            'VENTA', 'COMPRA', 'DEVOLUCION',
            'AJUSTE', 'MEZCLA', 'RECEPCION'
        )
    ),
    documento_tipo TEXT,
    documento_local_id TEXT,
    device_id TEXT NOT NULL,
    usuario_id INTEGER,
    request_hash TEXT NOT NULL,
    estado TEXT NOT NULL CHECK (
        estado IN ('PERSISTED', 'APPLIED', 'REJECTED')
    ),
    resultado TEXT NOT NULL CHECK (
        resultado IN ('PERSISTED', 'APPLIED', 'REJECTED')
    ),
    motivo TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inventory_operations (
    operation_id TEXT PRIMARY KEY,
    command_id TEXT NOT NULL REFERENCES inventory_commands(command_id),
    producto_local_id TEXT NOT NULL,
    delta_scaled BIGINT NOT NULL,
    line_no INTEGER NOT NULL,
    UNIQUE (command_id, line_no)
);

CREATE INDEX IF NOT EXISTS idx_inventory_operations_command
    ON inventory_operations(command_id);
CREATE INDEX IF NOT EXISTS idx_inventory_operations_producto
    ON inventory_operations(producto_local_id);
CREATE INDEX IF NOT EXISTS idx_inventory_commands_hash
    ON inventory_commands(request_hash);
