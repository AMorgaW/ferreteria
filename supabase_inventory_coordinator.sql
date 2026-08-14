-- FERREPRO Fase 1D — coordinador autoritativo de inventario.
-- SOLO PostgreSQL/Supabase. Nunca ejecutar contra SQLite.
-- Idempotente. No modifica productos.stock. No entra al sync LWW.
-- Autoridad online: inventory_balances.quantity_scaled (BIGINT, escala 1000).
-- apply_inventory_command: una RPC → una transacción.

CREATE TABLE IF NOT EXISTS inventory_balances (
    producto_local_id TEXT PRIMARY KEY,
    quantity_scaled BIGINT NOT NULL CHECK (quantity_scaled >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inventory_balance_init (
    producto_local_id TEXT PRIMARY KEY,
    quantity_scaled BIGINT NOT NULL,
    source TEXT NOT NULL,
    initialized_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_inventory_balances_updated
    ON inventory_balances(updated_at);

ALTER TABLE inventory_balances ENABLE ROW LEVEL SECURITY;
ALTER TABLE inventory_balance_init ENABLE ROW LEVEL SECURITY;
ALTER TABLE inventory_commands ENABLE ROW LEVEL SECURITY;
ALTER TABLE inventory_operations ENABLE ROW LEVEL SECURITY;

-- FASE1D-BEGIN apply_inventory_command
CREATE OR REPLACE FUNCTION public.apply_inventory_command(
    p_command_id text,
    p_tipo text,
    p_documento_tipo text,
    p_documento_local_id text,
    p_device_id text,
    p_usuario_id integer,
    p_request_hash text,
    p_operations jsonb
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $ferrepro_fn$
DECLARE
    v_command_id text;
    v_device_id text;
    v_doc_id text;
    v_tipo text;
    v_hash text;
    v_existing_hash text;
    v_now text;
    v_op jsonb;
    v_parsed jsonb := '[]'::jsonb;
    v_line int;
    v_delta numeric;
    v_opid text;
    v_pid text;
    v_seen_lines int[] := ARRAY[]::int[];
    v_seen_ops text[] := ARRAY[]::text[];
    v_owner text;
    v_missing text[] := ARRAY[]::text[];
    v_pid_list text[];
    v_net numeric;
    v_qty bigint;
    v_next numeric;
    v_failures text := '';
    v_plan jsonb := '[]'::jsonb;
    v_item jsonb;
    v_motivo text;
    v_estado text;
    v_constraint text;
    BIGINT_MIN numeric := -9223372036854775808;
    BIGINT_MAX numeric := 9223372036854775807;
BEGIN
    IF p_command_id IS NULL OR btrim(p_command_id) = '' THEN
        RAISE EXCEPTION 'INVALID_COMMAND: command_id es obligatorio'
            USING ERRCODE = '22023';
    END IF;
    BEGIN
        v_command_id := (btrim(p_command_id))::uuid::text;
    EXCEPTION WHEN invalid_text_representation THEN
        RAISE EXCEPTION 'INVALID_COMMAND: command_id debe ser UUID'
            USING ERRCODE = '22023';
    END;
    IF p_device_id IS NULL OR btrim(p_device_id) = '' THEN
        RAISE EXCEPTION 'INVALID_COMMAND: device_id es obligatorio'
            USING ERRCODE = '22023';
    END IF;
    BEGIN
        v_device_id := (btrim(p_device_id))::uuid::text;
    EXCEPTION WHEN invalid_text_representation THEN
        RAISE EXCEPTION 'INVALID_COMMAND: device_id debe ser UUID'
            USING ERRCODE = '22023';
    END;
    IF p_documento_local_id IS NULL OR btrim(p_documento_local_id) = '' THEN
        v_doc_id := NULL;
    ELSE
        BEGIN
            v_doc_id := (btrim(p_documento_local_id))::uuid::text;
        EXCEPTION WHEN invalid_text_representation THEN
            RAISE EXCEPTION 'INVALID_COMMAND: documento_local_id debe ser UUID'
                USING ERRCODE = '22023';
        END;
    END IF;
    v_tipo := upper(btrim(COALESCE(p_tipo, '')));
    IF v_tipo NOT IN ('VENTA', 'COMPRA', 'DEVOLUCION', 'AJUSTE', 'MEZCLA', 'RECEPCION') THEN
        RAISE EXCEPTION USING ERRCODE = '22023',
            MESSAGE = 'INVALID_COMMAND: tipo desconocido ' || coalesce(p_tipo, '');
    END IF;
    v_hash := lower(btrim(COALESCE(p_request_hash, '')));
    IF v_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'INVALID_COMMAND: request_hash debe ser SHA-256 hex'
            USING ERRCODE = '22023';
    END IF;
    IF p_operations IS NULL OR jsonb_typeof(p_operations) <> 'array' THEN
        RAISE EXCEPTION 'INVALID_COMMAND: operations debe ser un array JSON'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(
        pg_catalog.hashtextextended('ferrepro.invcmd:' || v_command_id, 0)
    );

    SELECT request_hash
      INTO v_existing_hash
      FROM public.inventory_commands
     WHERE command_id = v_command_id
     FOR UPDATE;

    IF FOUND THEN
        IF v_existing_hash IS DISTINCT FROM v_hash THEN
            RAISE EXCEPTION USING ERRCODE = '22023',
                MESSAGE = 'IDEMPOTENCY_CONFLICT: command_id ' || v_command_id
                    || ' ya existe con otro request_hash';
        END IF;
        RETURN public.inventory_command_to_json(v_command_id, true);
    END IF;

    IF jsonb_array_length(p_operations) = 0 THEN
        RAISE EXCEPTION 'EMPTY_COMMAND: el comando debe tener al menos una operación'
            USING ERRCODE = '22023';
    END IF;

    FOR v_op IN
        SELECT value FROM jsonb_array_elements(p_operations)
    LOOP
        IF jsonb_typeof(v_op) <> 'object' THEN
            RAISE EXCEPTION 'INVALID_COMMAND: cada operación debe ser un objeto'
                USING ERRCODE = '22023';
        END IF;
        BEGIN
            v_opid := (v_op->>'operation_id')::uuid::text;
            v_pid := (v_op->>'producto_local_id')::uuid::text;
        EXCEPTION WHEN invalid_text_representation THEN
            RAISE EXCEPTION 'INVALID_COMMAND: operation_id y producto_local_id deben ser UUID'
                USING ERRCODE = '22023';
        END;
        BEGIN
            v_line := (v_op->>'line_no')::int;
        EXCEPTION WHEN others THEN
            RAISE EXCEPTION 'INVALID_COMMAND: line_no debe ser entero'
                USING ERRCODE = '22023';
        END;
        IF v_line IS NULL OR v_line < 1 THEN
            RAISE EXCEPTION 'INVALID_COMMAND: line_no debe ser >= 1'
                USING ERRCODE = '22023';
        END IF;
        IF v_line = ANY (v_seen_lines) THEN
            RAISE EXCEPTION USING ERRCODE = '22023',
                MESSAGE = 'INVALID_COMMAND: line_no duplicado ' || v_line::text;
        END IF;
        IF v_opid = ANY (v_seen_ops) THEN
            RAISE EXCEPTION USING ERRCODE = '22023',
                MESSAGE = 'INVALID_COMMAND: operation_id duplicado ' || v_opid;
        END IF;
        v_seen_lines := array_append(v_seen_lines, v_line);
        v_seen_ops := array_append(v_seen_ops, v_opid);
        BEGIN
            v_delta := (v_op->>'delta_scaled')::numeric;
        EXCEPTION WHEN others THEN
            RAISE EXCEPTION 'INVALID_DELTA: delta_scaled no numérico'
                USING ERRCODE = '22023';
        END;
        IF v_delta IS NULL OR v_delta <> trunc(v_delta) THEN
            RAISE EXCEPTION 'INVALID_DELTA: delta_scaled debe ser entero exacto'
                USING ERRCODE = '22023';
        END IF;
        IF v_delta = 0 THEN
            RAISE EXCEPTION 'ZERO_DELTA: delta 0 no tiene razón de dominio'
                USING ERRCODE = '22023';
        END IF;
        IF v_delta < BIGINT_MIN OR v_delta > BIGINT_MAX THEN
            RAISE EXCEPTION 'INVALID_DELTA: delta_scaled fuera de rango BIGINT'
                USING ERRCODE = '22023';
        END IF;
        SELECT o.command_id
          INTO v_owner
          FROM public.inventory_operations o
         WHERE o.operation_id = v_opid;
        IF FOUND AND v_owner IS DISTINCT FROM v_command_id THEN
            RAISE EXCEPTION USING ERRCODE = '22023',
                MESSAGE = 'DUPLICATE_OPERATION: operation_id ' || v_opid
                    || ' ya pertenece a otro comando (' || v_owner || ')';
        END IF;
        v_parsed := v_parsed || jsonb_build_array(
            jsonb_build_object(
                'operation_id', v_opid,
                'producto_local_id', v_pid,
                'delta_scaled', v_delta::bigint,
                'line_no', v_line
            )
        );
    END LOOP;

    SELECT coalesce(array_agg(pid ORDER BY pid), ARRAY[]::text[])
      INTO v_pid_list
      FROM (
          SELECT DISTINCT e->>'producto_local_id' AS pid
            FROM jsonb_array_elements(v_parsed) e
      ) d;

    SELECT coalesce(array_agg(pid ORDER BY pid), ARRAY[]::text[])
      INTO v_missing
      FROM unnest(v_pid_list) AS pid
     WHERE NOT EXISTS (
        SELECT 1
          FROM public.productos p
         WHERE p.local_id = pid
     );

    v_now := to_char(
        timezone('UTC', clock_timestamp()),
        'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'
    );

    IF array_length(v_missing, 1) IS NOT NULL THEN
        v_motivo := 'UNKNOWN_PRODUCT: ' || array_to_string(v_missing, ', ');
        v_estado := 'REJECTED';
        INSERT INTO public.inventory_commands (
            command_id, tipo, documento_tipo, documento_local_id,
            device_id, usuario_id, request_hash, estado, resultado,
            motivo, created_at, updated_at
        ) VALUES (
            v_command_id, v_tipo, p_documento_tipo, v_doc_id,
            v_device_id, p_usuario_id, v_hash, v_estado, v_estado,
            v_motivo, v_now, v_now
        );
        INSERT INTO public.inventory_operations (
            operation_id, command_id, producto_local_id, delta_scaled, line_no
        )
        SELECT
            e->>'operation_id',
            v_command_id,
            e->>'producto_local_id',
            (e->>'delta_scaled')::bigint,
            (e->>'line_no')::int
        FROM jsonb_array_elements(v_parsed) e;
        RETURN public.inventory_command_to_json(v_command_id, false);
    END IF;

    FOR v_pid, v_net IN
        SELECT e->>'producto_local_id',
               SUM((e->>'delta_scaled')::numeric)
          FROM jsonb_array_elements(v_parsed) e
         GROUP BY 1
         ORDER BY 1
    LOOP
        PERFORM pg_advisory_xact_lock(
            pg_catalog.hashtextextended('ferrepro.invbal:' || v_pid, 0)
        );
        SELECT b.quantity_scaled
          INTO v_qty
          FROM public.inventory_balances b
         WHERE b.producto_local_id = v_pid
         FOR UPDATE;
        IF NOT FOUND THEN
            IF v_net < 0 THEN
                v_failures := v_failures || 'BALANCE_NOT_FOUND: producto='
                    || v_pid || '; ';
                CONTINUE;
            END IF;
            v_qty := 0;
            IF v_net > BIGINT_MAX THEN
                v_failures := v_failures || 'QUANTITY_OVERFLOW: producto='
                    || v_pid || '; ';
                CONTINUE;
            END IF;
            v_plan := v_plan || jsonb_build_array(
                jsonb_build_object(
                    'producto_local_id', v_pid,
                    'next_qty', v_net::bigint,
                    'missing', true
                )
            );
        ELSE
            IF v_net > 0 AND v_qty::numeric > BIGINT_MAX - v_net THEN
                v_failures := v_failures || 'QUANTITY_OVERFLOW: producto='
                    || v_pid || '; ';
                CONTINUE;
            END IF;
            v_next := v_qty::numeric + v_net;
            IF v_next < 0 THEN
                v_failures := v_failures || 'INSUFFICIENT_STOCK: producto='
                    || v_pid || ' available=' || v_qty::text
                    || ' required=' || (abs(v_net))::text || '; ';
                CONTINUE;
            END IF;
            IF v_next > BIGINT_MAX THEN
                v_failures := v_failures || 'QUANTITY_OVERFLOW: producto='
                    || v_pid || '; ';
                CONTINUE;
            END IF;
            v_plan := v_plan || jsonb_build_array(
                jsonb_build_object(
                    'producto_local_id', v_pid,
                    'next_qty', v_next::bigint,
                    'missing', false
                )
            );
        END IF;
    END LOOP;

    IF v_failures <> '' THEN
        v_motivo := rtrim(v_failures, '; ');
        v_estado := 'REJECTED';
        INSERT INTO public.inventory_commands (
            command_id, tipo, documento_tipo, documento_local_id,
            device_id, usuario_id, request_hash, estado, resultado,
            motivo, created_at, updated_at
        ) VALUES (
            v_command_id, v_tipo, p_documento_tipo, v_doc_id,
            v_device_id, p_usuario_id, v_hash, v_estado, v_estado,
            v_motivo, v_now, v_now
        );
        INSERT INTO public.inventory_operations (
            operation_id, command_id, producto_local_id, delta_scaled, line_no
        )
        SELECT
            e->>'operation_id',
            v_command_id,
            e->>'producto_local_id',
            (e->>'delta_scaled')::bigint,
            (e->>'line_no')::int
        FROM jsonb_array_elements(v_parsed) e;
        RETURN public.inventory_command_to_json(v_command_id, false);
    END IF;

    v_estado := 'APPLIED';
    BEGIN
        FOR v_item IN SELECT value FROM jsonb_array_elements(v_plan)
        LOOP
            IF (v_item->>'missing')::boolean THEN
                INSERT INTO public.inventory_balances (
                    producto_local_id, quantity_scaled, created_at, updated_at
                ) VALUES (
                    v_item->>'producto_local_id',
                    (v_item->>'next_qty')::bigint,
                    v_now,
                    v_now
                );
            ELSE
                UPDATE public.inventory_balances
                   SET quantity_scaled = (v_item->>'next_qty')::bigint,
                       updated_at = v_now
                 WHERE producto_local_id = v_item->>'producto_local_id';
            END IF;
        END LOOP;

        INSERT INTO public.inventory_commands (
            command_id, tipo, documento_tipo, documento_local_id,
            device_id, usuario_id, request_hash, estado, resultado,
            motivo, created_at, updated_at
        ) VALUES (
            v_command_id, v_tipo, p_documento_tipo, v_doc_id,
            v_device_id, p_usuario_id, v_hash, v_estado, v_estado,
            NULL, v_now, v_now
        );
        INSERT INTO public.inventory_operations (
            operation_id, command_id, producto_local_id, delta_scaled, line_no
        )
        SELECT
            e->>'operation_id',
            v_command_id,
            e->>'producto_local_id',
            (e->>'delta_scaled')::bigint,
            (e->>'line_no')::int
        FROM jsonb_array_elements(v_parsed) e;
    EXCEPTION
        WHEN unique_violation THEN
            GET STACKED DIAGNOSTICS v_constraint = CONSTRAINT_NAME;
            IF v_constraint = 'inventory_commands_pkey' THEN
                SELECT request_hash
                  INTO v_existing_hash
                  FROM public.inventory_commands
                 WHERE command_id = v_command_id;
                IF FOUND THEN
                    IF v_existing_hash IS DISTINCT FROM v_hash THEN
                        RAISE EXCEPTION USING ERRCODE = '22023',
                            MESSAGE = 'IDEMPOTENCY_CONFLICT: command_id ' || v_command_id
                                || ' ya existe con otro request_hash';
                    END IF;
                    RETURN public.inventory_command_to_json(v_command_id, true);
                END IF;
                RAISE;
            ELSIF v_constraint IN (
                'inventory_operations_pkey',
                'inventory_operations_command_id_line_no_key'
            ) THEN
                RAISE EXCEPTION
                    'DUPLICATE_OPERATION: operation_id repetido en otro comando'
                    USING ERRCODE = '22023';
            ELSIF v_constraint IN (
                'inventory_balances_pkey',
                'inventory_balance_init_pkey'
            ) THEN
                RAISE;
            ELSE
                RAISE;
            END IF;
    END;

    RETURN public.inventory_command_to_json(v_command_id, false);
END;
$ferrepro_fn$;
-- FASE1D-END apply_inventory_command

CREATE OR REPLACE FUNCTION public.inventory_command_to_json(
    p_command_id text,
    p_replayed boolean
) RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $ferrepro_fn$
DECLARE
    v_ops jsonb;
    v_json jsonb;
BEGIN
    SELECT jsonb_build_object(
        'command_id', c.command_id,
        'tipo', c.tipo,
        'documento_tipo', c.documento_tipo,
        'documento_local_id', c.documento_local_id,
        'device_id', c.device_id,
        'usuario_id', c.usuario_id,
        'request_hash', c.request_hash,
        'estado', c.estado,
        'resultado', c.resultado,
        'motivo', c.motivo,
        'created_at', c.created_at,
        'updated_at', c.updated_at,
        'replayed', p_replayed
    )
      INTO STRICT v_json
      FROM public.inventory_commands c
     WHERE c.command_id = p_command_id;
    SELECT coalesce(
        jsonb_agg(
            jsonb_build_object(
                'operation_id', o.operation_id,
                'producto_local_id', o.producto_local_id,
                'delta_scaled', o.delta_scaled,
                'line_no', o.line_no
            )
            ORDER BY o.line_no
        ),
        '[]'::jsonb
    )
      INTO v_ops
      FROM public.inventory_operations o
     WHERE o.command_id = p_command_id;
    RETURN v_json || jsonb_build_object('operations', v_ops);
END;
$ferrepro_fn$;

-- FASE1D-BEGIN seed_inventory_balance
CREATE OR REPLACE FUNCTION public.seed_inventory_balance(
    p_producto_local_id text,
    p_quantity_scaled bigint
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $ferrepro_fn$
DECLARE
    v_pid text;
    v_now text;
    v_qty bigint;
    v_n integer := 0;
BEGIN
    BEGIN
        v_pid := (btrim(p_producto_local_id))::uuid::text;
    EXCEPTION WHEN invalid_text_representation THEN
        RAISE EXCEPTION 'INVALID_COMMAND: producto_local_id debe ser UUID'
            USING ERRCODE = '22023';
    END;
    IF p_quantity_scaled IS NULL OR p_quantity_scaled < 0 THEN
        RAISE EXCEPTION 'INVALID_DELTA: quantity_scaled de semilla debe ser >= 0'
            USING ERRCODE = '22023';
    END IF;
    v_now := to_char(
        timezone('UTC', clock_timestamp()),
        'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'
    );
    INSERT INTO public.inventory_balances (
        producto_local_id, quantity_scaled, created_at, updated_at
    ) VALUES (
        v_pid, p_quantity_scaled, v_now, v_now
    )
    ON CONFLICT (producto_local_id) DO NOTHING;
    GET DIAGNOSTICS v_n = ROW_COUNT;
    INSERT INTO public.inventory_balance_init (
        producto_local_id, quantity_scaled, source, initialized_at
    ) VALUES (
        v_pid, p_quantity_scaled, 'explicit', v_now
    )
    ON CONFLICT (producto_local_id) DO NOTHING;
    SELECT quantity_scaled INTO STRICT v_qty
      FROM public.inventory_balances
     WHERE producto_local_id = v_pid;
    RETURN jsonb_build_object(
        'producto_local_id', v_pid,
        'quantity_scaled', v_qty,
        'created', (v_n > 0)
    );
END;
$ferrepro_fn$;
-- FASE1D-END seed_inventory_balance

-- FASE1D-BEGIN initialize_inventory_balances_from_legacy
-- One-shot de corte. NO la ejecuta el coordinador ni el sync automático.
-- Lee la columna legacy de productos solo para copiar filas AUSENTES.
-- ON CONFLICT DO NOTHING: nunca pisa un balance más nuevo.
CREATE OR REPLACE FUNCTION public.initialize_inventory_balances_from_legacy()
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $ferrepro_fn$
DECLARE
    v_now text;
    v_inserted bigint := 0;
BEGIN
    v_now := to_char(
        timezone('UTC', clock_timestamp()),
        'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'
    );
    INSERT INTO public.inventory_balances (
        producto_local_id, quantity_scaled, created_at, updated_at
    )
    SELECT
        p.local_id,
        round((COALESCE(p.stock, 0))::numeric * 1000, 0)::bigint,
        v_now,
        v_now
    FROM public.productos p
    WHERE p.local_id IS NOT NULL
      AND btrim(p.local_id) <> ''
    ON CONFLICT (producto_local_id) DO NOTHING;
    GET DIAGNOSTICS v_inserted = ROW_COUNT;
    INSERT INTO public.inventory_balance_init (
        producto_local_id, quantity_scaled, source, initialized_at
    )
    SELECT
        b.producto_local_id,
        b.quantity_scaled,
        'legacy_cutover',
        v_now
    FROM public.inventory_balances b
    ON CONFLICT (producto_local_id) DO NOTHING;
    RETURN jsonb_build_object(
        'inserted', v_inserted,
        'source', 'legacy_cutover'
    );
END;
$ferrepro_fn$;
-- FASE1D-END initialize_inventory_balances_from_legacy

REVOKE ALL ON FUNCTION public.apply_inventory_command(text, text, text, text, text, integer, text, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.inventory_command_to_json(text, boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.seed_inventory_balance(text, bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.initialize_inventory_balances_from_legacy() FROM PUBLIC;
REVOKE ALL ON TABLE public.inventory_balances FROM PUBLIC;
REVOKE ALL ON TABLE public.inventory_balance_init FROM PUBLIC;

DO $ferrepro_do$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON FUNCTION public.apply_inventory_command(text, text, text, text, text, integer, text, jsonb) FROM anon;
        REVOKE ALL ON FUNCTION public.inventory_command_to_json(text, boolean) FROM anon;
        REVOKE ALL ON FUNCTION public.seed_inventory_balance(text, bigint) FROM anon;
        REVOKE ALL ON FUNCTION public.initialize_inventory_balances_from_legacy() FROM anon;
        REVOKE ALL ON TABLE public.inventory_balances FROM anon;
        REVOKE ALL ON TABLE public.inventory_balance_init FROM anon;
        REVOKE ALL ON TABLE public.inventory_commands FROM anon;
        REVOKE ALL ON TABLE public.inventory_operations FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON FUNCTION public.apply_inventory_command(text, text, text, text, text, integer, text, jsonb) FROM authenticated;
        REVOKE ALL ON FUNCTION public.inventory_command_to_json(text, boolean) FROM authenticated;
        REVOKE ALL ON FUNCTION public.seed_inventory_balance(text, bigint) FROM authenticated;
        REVOKE ALL ON FUNCTION public.initialize_inventory_balances_from_legacy() FROM authenticated;
        REVOKE ALL ON TABLE public.inventory_balances FROM authenticated;
        REVOKE ALL ON TABLE public.inventory_balance_init FROM authenticated;
        REVOKE ALL ON TABLE public.inventory_commands FROM authenticated;
        REVOKE ALL ON TABLE public.inventory_operations FROM authenticated;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        REVOKE ALL ON FUNCTION public.apply_inventory_command(text, text, text, text, text, integer, text, jsonb) FROM service_role;
        REVOKE ALL ON FUNCTION public.inventory_command_to_json(text, boolean) FROM service_role;
        REVOKE ALL ON FUNCTION public.seed_inventory_balance(text, bigint) FROM service_role;
        REVOKE ALL ON FUNCTION public.initialize_inventory_balances_from_legacy() FROM service_role;
        REVOKE ALL ON TABLE public.inventory_balances FROM service_role;
        REVOKE ALL ON TABLE public.inventory_balance_init FROM service_role;
        REVOKE ALL ON TABLE public.inventory_commands FROM service_role;
        REVOKE ALL ON TABLE public.inventory_operations FROM service_role;
    END IF;
END
$ferrepro_do$;
