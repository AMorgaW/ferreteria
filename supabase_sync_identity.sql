-- FERREPRO Fase 1B — identidad local_id en PostgreSQL.
-- SOLO PostgreSQL/Supabase. Nunca ejecutar contra SQLite.
-- Idempotente: no reasigna local_id existentes.
-- UNIQUE(local_id): nombre canónico uq_<tabla>_local_id.
-- Un UNIQUE equivalente ya existente (cualquier nombre, p.ej. ux_*) se respeta.
-- La lista de tablas DEBE coincidir con sync_registry.tables_requiring_postgres_local_id_unique().

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'usuarios',
        'proveedores',
        'clientes',
        'configuracion',
        'productos',
        'ventas',
        'compras',
        'cierres_caja',
        'auditoria',
        'detalle_ventas',
        'detalle_compras',
        'abonos_ventas',
        'abonos_compras',
        'movimientos',
        'movimientos_inventario',
        'egresos_caja',
        'historial_precios',
        'cuentas_por_cobrar',
        'pagos_cuentas'
    ]
    LOOP
        IF to_regclass('public.' || t) IS NOT NULL
           AND EXISTS (
               SELECT 1 FROM information_schema.columns c
               WHERE c.table_schema = 'public'
                 AND c.table_name = t
                 AND c.column_name = 'local_id'
           ) THEN
            EXECUTE format(
                'UPDATE %I SET local_id = gen_random_uuid()::text
                 WHERE local_id IS NULL OR local_id = %L',
                t, ''
            );
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
