-- Ejecutar una vez en el editor SQL de Supabase antes de activar sincronizacion.
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
            EXECUTE format(
                'CREATE UNIQUE INDEX IF NOT EXISTS %I ON %I(local_id)',
                'uq_' || table_name || '_local_id',
                table_name
            );
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
