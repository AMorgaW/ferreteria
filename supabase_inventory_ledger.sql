-- FERREPRO Fase 1C — ledger de comandos de inventario.
-- SOLO PostgreSQL/Supabase. Nunca ejecutar contra SQLite.
-- Idempotente. No modifica productos.stock. No crea RPC.
-- Identidades UUID como TEXT (paridad con productos.local_id).
-- Tablas append-only/idempotentes: no entran al sync LWW genérico.

CREATE TABLE IF NOT EXISTS inventory_commands (
    command_id TEXT NOT NULL,
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
    updated_at TEXT NOT NULL,
    CONSTRAINT pk_inventory_commands PRIMARY KEY (command_id)
);

CREATE TABLE IF NOT EXISTS inventory_operations (
    operation_id TEXT NOT NULL,
    command_id TEXT NOT NULL,
    producto_local_id TEXT NOT NULL,
    delta_scaled BIGINT NOT NULL,
    line_no INTEGER NOT NULL,
    CONSTRAINT pk_inventory_operations PRIMARY KEY (operation_id),
    CONSTRAINT fk_inventory_operations_command
        FOREIGN KEY (command_id) REFERENCES inventory_commands(command_id),
    CONSTRAINT uq_inventory_operations_command_line UNIQUE (command_id, line_no)
);

CREATE INDEX IF NOT EXISTS idx_inventory_operations_command
    ON inventory_operations(command_id);
CREATE INDEX IF NOT EXISTS idx_inventory_operations_producto
    ON inventory_operations(producto_local_id);
CREATE INDEX IF NOT EXISTS idx_inventory_commands_hash
    ON inventory_commands(request_hash);

-- Compatibilidad con bases ya creadas por Fase 1C/1D (nombres implícitos).
DO $ferrepro_ledger_rename$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM pg_catalog.pg_constraint c
          JOIN pg_catalog.pg_class t ON t.oid = c.conrelid
          JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
         WHERE n.nspname = 'public'
           AND t.relname = 'inventory_commands'
           AND c.conname = 'inventory_commands_pkey'
    ) THEN
        ALTER TABLE public.inventory_commands
            RENAME CONSTRAINT inventory_commands_pkey TO pk_inventory_commands;
    END IF;
    IF EXISTS (
        SELECT 1
          FROM pg_catalog.pg_constraint c
          JOIN pg_catalog.pg_class t ON t.oid = c.conrelid
          JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
         WHERE n.nspname = 'public'
           AND t.relname = 'inventory_operations'
           AND c.conname = 'inventory_operations_pkey'
    ) THEN
        ALTER TABLE public.inventory_operations
            RENAME CONSTRAINT inventory_operations_pkey TO pk_inventory_operations;
    END IF;
    IF EXISTS (
        SELECT 1
          FROM pg_catalog.pg_constraint c
          JOIN pg_catalog.pg_class t ON t.oid = c.conrelid
          JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
         WHERE n.nspname = 'public'
           AND t.relname = 'inventory_operations'
           AND c.conname = 'inventory_operations_command_id_line_no_key'
    ) THEN
        ALTER TABLE public.inventory_operations
            RENAME CONSTRAINT inventory_operations_command_id_line_no_key
            TO uq_inventory_operations_command_line;
    END IF;
    IF EXISTS (
        SELECT 1
          FROM pg_catalog.pg_constraint c
          JOIN pg_catalog.pg_class t ON t.oid = c.conrelid
          JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
         WHERE n.nspname = 'public'
           AND t.relname = 'inventory_operations'
           AND c.conname = 'inventory_operations_command_id_fkey'
    ) THEN
        ALTER TABLE public.inventory_operations
            RENAME CONSTRAINT inventory_operations_command_id_fkey
            TO fk_inventory_operations_command;
    END IF;
END
$ferrepro_ledger_rename$;
