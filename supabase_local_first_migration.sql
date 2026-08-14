-- Ejecutar una vez en el editor SQL de Supabase antes de activar sincronizacion.
-- UNIQUE(local_id): mismo predicado pg_index que sync_registry.postgres_identity_sql().
-- Un UNIQUE equivalente ya existente (cualquier nombre, p.ej. ux_* legado) se
-- respeta. No DROP para renombrar. No crear uq_* redundante junto a ux_*.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Historial de precios (no existía en Supabase): se crea para poder replicarlo.
CREATE TABLE IF NOT EXISTS historial_precios (
    id integer PRIMARY KEY,
    producto_id integer,
    tipo text,
    precio_anterior real,
    precio_nuevo real,
    usuario_id integer,
    fecha text
);

DO $$
DECLARE
    table_name text;
    t text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'usuarios', 'productos', 'clientes', 'proveedores', 'ventas',
        'detalle_ventas', 'movimientos', 'movimientos_inventario',
        'cuentas_por_cobrar', 'pagos_cuentas', 'cierres_caja',
        'abonos_ventas', 'abonos_compras', 'egresos_caja', 'configuracion',
        'compras', 'detalle_compras', 'auditoria', 'historial_precios'
    ]
    LOOP
        IF to_regclass('public.' || table_name) IS NOT NULL THEN
            EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS local_id text', table_name);
            EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS remote_id text', table_name);
            EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS updated_at timestamp', table_name);
            EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS deleted_at timestamp', table_name);
            EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS is_deleted integer NOT NULL DEFAULT 0', table_name);
            EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS sync_status text NOT NULL DEFAULT ''pending''', table_name);
            EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS last_synced_at timestamp', table_name);
            EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS version integer NOT NULL DEFAULT 1', table_name);
            EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS device_id text', table_name);
            EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS created_by integer', table_name);
            EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS updated_by integer', table_name);
            -- t debe coincidir con el predicado canónico (trel.relname = t).
            t := table_name;
            IF NOT EXISTS (
                    SELECT 1
                    FROM pg_index i
                    JOIN pg_class trel ON trel.oid = i.indrelid
                    JOIN pg_namespace nsp ON nsp.oid = trel.relnamespace
                    JOIN pg_attribute a ON a.attrelid = trel.oid
                         AND a.attnum = i.indkey[0]
                         AND NOT a.attisdropped
                    WHERE nsp.nspname = 'public'
                      AND trel.relname = t
                      AND i.indisunique
                      AND i.indpred IS NULL
                      AND i.indnkeyatts = 1
                      AND a.attname = 'local_id'
                ) THEN
                EXECUTE format(
                    'CREATE UNIQUE INDEX IF NOT EXISTS %I ON %I(local_id)',
                    'uq_' || t || '_local_id',
                    t
                );
            END IF;
        END IF;
    END LOOP;
END $$;

CREATE INDEX IF NOT EXISTS idx_productos_activo_nombre ON productos(activo, nombre);
CREATE INDEX IF NOT EXISTS idx_productos_codigo ON productos(codigo_barras);
CREATE INDEX IF NOT EXISTS idx_productos_nombre_trgm ON productos USING gin (lower(nombre) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_clientes_activo_nombre ON clientes(activo, nombre);
CREATE INDEX IF NOT EXISTS idx_clientes_documento ON clientes(numero_documento);
CREATE INDEX IF NOT EXISTS idx_ventas_fecha ON ventas(fecha);
CREATE INDEX IF NOT EXISTS idx_detalle_ventas_venta ON detalle_ventas(venta_id);
CREATE INDEX IF NOT EXISTS idx_movimientos_fecha ON movimientos(fecha);
