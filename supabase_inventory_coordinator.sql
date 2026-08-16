-- FERREPRO Fase 1D — coordinador autoritativo de inventario.
-- SOLO PostgreSQL/Supabase. Nunca ejecutar contra SQLite.
-- Idempotente. No modifica productos.stock. No entra al sync LWW.
-- Autoridad online: inventory_balances.quantity_scaled (BIGINT, escala 1000).
-- apply_inventory_command: una RPC → una transacción.
-- Fase 1D.3: gate session_user + constraints nombradas.

CREATE TABLE IF NOT EXISTS inventory_balances (
    producto_local_id TEXT NOT NULL,
    quantity_scaled BIGINT NOT NULL CHECK (quantity_scaled >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CONSTRAINT pk_inventory_balances PRIMARY KEY (producto_local_id)
);

CREATE TABLE IF NOT EXISTS inventory_balance_init (
    producto_local_id TEXT NOT NULL,
    quantity_scaled BIGINT NOT NULL,
    source TEXT NOT NULL,
    initialized_at TEXT NOT NULL,
    CONSTRAINT pk_inventory_balance_init PRIMARY KEY (producto_local_id)
);

CREATE TABLE IF NOT EXISTS inventory_balance_init_state (
    init_key TEXT NOT NULL CHECK (init_key = 'legacy_cutover'),
    initialized_at TEXT NOT NULL,
    CONSTRAINT pk_inventory_balance_init_state PRIMARY KEY (init_key)
);

CREATE INDEX IF NOT EXISTS idx_inventory_balances_updated
    ON inventory_balances(updated_at);

-- Compatibilidad con bases ya creadas por Fase 1D (nombres implícitos).
DO $ferrepro_rename$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM pg_catalog.pg_constraint c
          JOIN pg_catalog.pg_class t ON t.oid = c.conrelid
          JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
         WHERE n.nspname = 'public'
           AND t.relname = 'inventory_balances'
           AND c.conname = 'inventory_balances_pkey'
    ) THEN
        ALTER TABLE public.inventory_balances
            RENAME CONSTRAINT inventory_balances_pkey TO pk_inventory_balances;
    END IF;
    IF EXISTS (
        SELECT 1
          FROM pg_catalog.pg_constraint c
          JOIN pg_catalog.pg_class t ON t.oid = c.conrelid
          JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
         WHERE n.nspname = 'public'
           AND t.relname = 'inventory_balance_init'
           AND c.conname = 'inventory_balance_init_pkey'
    ) THEN
        ALTER TABLE public.inventory_balance_init
            RENAME CONSTRAINT inventory_balance_init_pkey TO pk_inventory_balance_init;
    END IF;
    IF EXISTS (
        SELECT 1
          FROM pg_catalog.pg_constraint c
          JOIN pg_catalog.pg_class t ON t.oid = c.conrelid
          JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
         WHERE n.nspname = 'public'
           AND t.relname = 'inventory_balance_init_state'
           AND c.conname = 'inventory_balance_init_state_pkey'
    ) THEN
        ALTER TABLE public.inventory_balance_init_state
            RENAME CONSTRAINT inventory_balance_init_state_pkey
            TO pk_inventory_balance_init_state;
    END IF;
END
$ferrepro_rename$;

ALTER TABLE inventory_balances ENABLE ROW LEVEL SECURITY;
ALTER TABLE inventory_balance_init ENABLE ROW LEVEL SECURITY;
ALTER TABLE inventory_balance_init_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE inventory_commands ENABLE ROW LEVEL SECURITY;
ALTER TABLE inventory_operations ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS inventory_reversal_allocations (
    command_id TEXT NOT NULL,
    original_documento_local_id TEXT NOT NULL,
    producto_local_id TEXT NOT NULL,
    qty_scaled BIGINT NOT NULL CHECK (qty_scaled > 0),
    created_at TEXT NOT NULL,
    CONSTRAINT pk_inventory_reversal_allocations
        PRIMARY KEY (command_id, producto_local_id)
);
CREATE INDEX IF NOT EXISTS idx_reversal_alloc_original
    ON inventory_reversal_allocations(original_documento_local_id, producto_local_id);
ALTER TABLE inventory_reversal_allocations ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION public.ferrepro_inventory_caller_is_allowed()
RETURNS boolean
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $ferrepro_fn$
DECLARE
    v_has_app boolean := false;
BEGIN
    BEGIN
        v_has_app := pg_catalog.pg_has_role(
            session_user,
            'ferrepro_inventory_app',
            'USAGE'
        );
    EXCEPTION
        WHEN undefined_object THEN
            v_has_app := false;
    END;
    RETURN v_has_app
        OR session_user = current_user;
END;
$ferrepro_fn$;

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
    v_documento_tipo text;
    v_tipo text;
    v_hash text;
    v_canonical text;
    v_computed_hash text;
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
    v_exp_min bigint;
    v_exp_max bigint;
    v_has_expected boolean;
    v_current_base bigint;
    v_balance_found boolean;
    v_plan jsonb := '[]'::jsonb;
    v_item jsonb;
    v_motivo text;
    v_estado text;
    v_constraint text;
    BIGINT_MIN numeric := -9223372036854775808;
    BIGINT_MAX numeric := 9223372036854775807;
    v_pos int := 0;
    v_neg int := 0;
    v_orig_doc text;
    v_orig_cmd text;
    v_orig_n int;
    v_cap numeric;
    v_already numeric;
BEGIN
    IF NOT public.ferrepro_inventory_caller_is_allowed() THEN
        RAISE EXCEPTION 'INVENTORY_FORBIDDEN: el caller no está autorizado para apply_inventory_command'
            USING ERRCODE = '42501';
    END IF;
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
    v_documento_tipo := NULLIF(btrim(COALESCE(p_documento_tipo, '')), '');
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
        IF v_op ? 'expected_base_scaled' THEN
            BEGIN
                IF (v_op->>'expected_base_scaled') IS NULL
                   OR (v_op->>'expected_base_scaled')::numeric <> trunc((v_op->>'expected_base_scaled')::numeric) THEN
                    RAISE EXCEPTION 'INVALID_DELTA: expected_base_scaled debe ser entero'
                        USING ERRCODE = '22023';
                END IF;
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'INVALID_DELTA: expected_base_scaled debe ser entero'
                    USING ERRCODE = '22023';
            END;
            v_parsed := v_parsed || jsonb_build_array(
                jsonb_build_object(
                    'operation_id', v_opid,
                    'producto_local_id', v_pid,
                    'delta_scaled', v_delta::bigint,
                    'line_no', v_line,
                    'expected_base_scaled', (v_op->>'expected_base_scaled')::bigint
                )
            );
        ELSE
            v_parsed := v_parsed || jsonb_build_array(
                jsonb_build_object(
                    'operation_id', v_opid,
                    'producto_local_id', v_pid,
                    'delta_scaled', v_delta::bigint,
                    'line_no', v_line
                )
            );
        END IF;
    END LOOP;

    v_parsed := COALESCE(
        (
            SELECT jsonb_agg(value ORDER BY (value->>'line_no')::int)
              FROM jsonb_array_elements(v_parsed)
        ),
        '[]'::jsonb
    );

    SELECT
        COUNT(*) FILTER (WHERE (e->>'delta_scaled')::bigint > 0),
        COUNT(*) FILTER (WHERE (e->>'delta_scaled')::bigint < 0)
      INTO v_pos, v_neg
      FROM jsonb_array_elements(v_parsed) e;
    IF v_tipo = 'VENTA' AND v_pos > 0 THEN
        RAISE EXCEPTION 'INVALID_DELTA_SIGN: VENTA exige todas las líneas con delta < 0'
            USING ERRCODE = '22023';
    ELSIF v_tipo IN ('COMPRA', 'RECEPCION') AND v_neg > 0 THEN
        RAISE EXCEPTION USING ERRCODE = '22023',
            MESSAGE = 'INVALID_DELTA_SIGN: ' || v_tipo
                || ' exige todas las líneas con delta > 0';
    ELSIF v_tipo = 'DEVOLUCION' AND v_pos > 0 AND v_neg > 0 THEN
        RAISE EXCEPTION 'INVALID_DELTA_SIGN: DEVOLUCION no admite signos mixtos en el mismo comando'
            USING ERRCODE = '22023';
    ELSIF v_tipo = 'MEZCLA' AND (v_pos = 0 OR v_neg = 0) THEN
        RAISE EXCEPTION 'INVALID_DELTA_SIGN: MEZCLA exige al menos un delta < 0 y uno > 0'
            USING ERRCODE = '22023';
    END IF;

    SELECT
        '{"command_id":' || pg_catalog.to_jsonb(v_command_id)::text
        || ',"documento_local_id":'
        || COALESCE(pg_catalog.to_jsonb(v_doc_id)::text, 'null')
        || ',"documento_tipo":'
        || COALESCE(pg_catalog.to_jsonb(v_documento_tipo)::text, 'null')
        || ',"operations":['
        || COALESCE(
            (
                SELECT string_agg(
                    '{"delta_scaled":' || (e->>'delta_scaled')
                    || CASE
                        WHEN e ? 'expected_base_scaled' THEN
                            ',"expected_base_scaled":' || (e->>'expected_base_scaled')
                        ELSE ''
                       END
                    || ',"line_no":' || (e->>'line_no')
                    || ',"operation_id":'
                    || pg_catalog.to_jsonb(e->>'operation_id')::text
                    || ',"producto_local_id":'
                    || pg_catalog.to_jsonb(e->>'producto_local_id')::text
                    || '}',
                    ',' ORDER BY (e->>'line_no')::int
                )
                  FROM jsonb_array_elements(v_parsed) e
            ),
            ''
        )
        || '],"tipo":' || pg_catalog.to_jsonb(v_tipo)::text
        || '}'
      INTO v_canonical;
    v_computed_hash := encode(
        pg_catalog.sha256(pg_catalog.convert_to(v_canonical, 'UTF8')),
        'hex'
    );
    IF v_computed_hash IS DISTINCT FROM v_hash THEN
        RAISE EXCEPTION USING ERRCODE = '22023',
            MESSAGE = 'INVALID_COMMAND: request_hash no coincide con el payload';
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
            v_command_id, v_tipo, v_documento_tipo, v_doc_id,
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

    SELECT NULLIF(btrim(COALESCE(value->>'original_documento_local_id', '')), '')
      INTO v_orig_doc
      FROM jsonb_array_elements(p_operations)
     WHERE NULLIF(btrim(COALESCE(value->>'original_documento_local_id', '')), '') IS NOT NULL
     LIMIT 1;
    IF v_orig_doc IS NOT NULL THEN
        BEGIN
            v_orig_doc := (btrim(v_orig_doc))::uuid::text;
        EXCEPTION WHEN invalid_text_representation THEN
            RAISE EXCEPTION 'INVALID_COMMAND: original_documento_local_id debe ser UUID'
                USING ERRCODE = '22023';
        END;
        SELECT COUNT(*) INTO v_orig_n
          FROM (
              SELECT DISTINCT (btrim(value->>'original_documento_local_id'))::uuid::text AS d
                FROM jsonb_array_elements(p_operations)
               WHERE NULLIF(btrim(COALESCE(value->>'original_documento_local_id', '')), '') IS NOT NULL
          ) s;
        IF v_orig_n > 1 THEN
            RAISE EXCEPTION 'INVALID_COMMAND: original_documento_local_id mixto'
                USING ERRCODE = '22023';
        END IF;
        IF EXISTS (
            SELECT 1 FROM jsonb_array_elements(p_operations) e
             WHERE NULLIF(btrim(COALESCE(e->>'original_documento_local_id', '')), '') IS NULL
        ) THEN
            RAISE EXCEPTION 'INVALID_COMMAND: original_documento_local_id incompleto'
                USING ERRCODE = '22023';
        END IF;
        PERFORM pg_advisory_xact_lock(
            pg_catalog.hashtextextended('ferrepro.revdoc:' || v_orig_doc, 0)
        );
        SELECT NULLIF(btrim(COALESCE(value->>'original_command_id', '')), '')
          INTO v_orig_cmd
          FROM jsonb_array_elements(p_operations)
         WHERE NULLIF(btrim(COALESCE(value->>'original_command_id', '')), '') IS NOT NULL
         LIMIT 1;
        IF v_orig_cmd IS NOT NULL THEN
            BEGIN
                v_orig_cmd := (btrim(v_orig_cmd))::uuid::text;
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'INVALID_COMMAND: original_command_id debe ser UUID'
                    USING ERRCODE = '22023';
            END;
        END IF;
        FOR v_pid, v_net IN
            SELECT e->>'producto_local_id',
                   SUM(ABS((e->>'delta_scaled')::numeric))
              FROM jsonb_array_elements(v_parsed) e
             GROUP BY 1
             ORDER BY 1
        LOOP
            SELECT COALESCE(SUM(ABS(o.delta_scaled)), 0)
              INTO v_cap
              FROM public.inventory_operations o
              JOIN public.inventory_commands c ON c.command_id = o.command_id
             WHERE o.producto_local_id = v_pid
               AND c.estado = 'APPLIED'
               AND c.tipo IN ('VENTA', 'COMPRA', 'RECEPCION')
               AND (
                    (v_orig_cmd IS NOT NULL AND c.command_id = v_orig_cmd)
                    OR (v_orig_cmd IS NULL AND c.documento_local_id = v_orig_doc)
               );
            SELECT COALESCE(SUM(a.qty_scaled), 0)
              INTO v_already
              FROM public.inventory_reversal_allocations a
             WHERE a.original_documento_local_id = v_orig_doc
               AND a.producto_local_id = v_pid;
            IF v_cap <= 0 THEN
                v_failures := v_failures || 'ORIGINAL_DOCUMENT_NOT_FOUND: producto='
                    || v_pid || '; ';
            ELSIF v_already + v_net > v_cap THEN
                v_failures := v_failures || 'RETURNABLE_QTY_EXCEEDED: producto='
                    || v_pid || ' available=' || (v_cap - v_already)::text
                    || ' required=' || v_net::text || '; ';
            END IF;
        END LOOP;
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
        v_balance_found := FOUND;
        SELECT MIN((e->>'expected_base_scaled')::bigint),
               MAX((e->>'expected_base_scaled')::bigint),
               bool_or(e ? 'expected_base_scaled')
          INTO v_exp_min, v_exp_max, v_has_expected
          FROM jsonb_array_elements(v_parsed) e
         WHERE e->>'producto_local_id' = v_pid;
        IF COALESCE(v_has_expected, false) THEN
            IF v_exp_min IS DISTINCT FROM v_exp_max THEN
                v_failures := v_failures || 'STALE_BALANCE: expected_base conflict producto='
                    || v_pid || '; ';
                CONTINUE;
            END IF;
            IF v_balance_found THEN
                v_current_base := v_qty;
            ELSE
                v_current_base := 0;
            END IF;
            IF v_current_base IS DISTINCT FROM v_exp_min THEN
                v_failures := v_failures || 'STALE_BALANCE: producto='
                    || v_pid || ' expected=' || v_exp_min::text
                    || ' actual=' || v_current_base::text || '; ';
                CONTINUE;
            END IF;
        END IF;
        IF NOT v_balance_found THEN
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
            v_command_id, v_tipo, v_documento_tipo, v_doc_id,
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
            v_command_id, v_tipo, v_documento_tipo, v_doc_id,
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
        IF v_orig_doc IS NOT NULL THEN
            INSERT INTO public.inventory_reversal_allocations (
                command_id, original_documento_local_id, producto_local_id,
                qty_scaled, created_at
            )
            SELECT
                v_command_id,
                v_orig_doc,
                e->>'producto_local_id',
                SUM(ABS((e->>'delta_scaled')::bigint)),
                v_now
              FROM jsonb_array_elements(v_parsed) e
             GROUP BY e->>'producto_local_id';
        END IF;
    EXCEPTION
        WHEN unique_violation THEN
            GET STACKED DIAGNOSTICS v_constraint = CONSTRAINT_NAME;
            IF v_constraint IN (
                'pk_inventory_commands',
                'inventory_commands_pkey'
            ) THEN
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
                'pk_inventory_operations',
                'inventory_operations_pkey',
                'uq_inventory_operations_command_line',
                'inventory_operations_command_id_line_no_key'
            ) THEN
                RAISE EXCEPTION
                    'DUPLICATE_OPERATION: operation_id repetido en otro comando'
                    USING ERRCODE = '22023';
            ELSIF v_constraint IN (
                'pk_inventory_balances',
                'inventory_balances_pkey',
                'pk_inventory_balance_init',
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
    IF session_user IS DISTINCT FROM current_user THEN
        RAISE EXCEPTION 'INVENTORY_FORBIDDEN: seed_inventory_balance solo el owner'
            USING ERRCODE = '42501';
    END IF;
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
    PERFORM pg_advisory_xact_lock(
        pg_catalog.hashtextextended('ferrepro.invbal:' || v_pid, 0)
    );
    IF NOT EXISTS (
        SELECT 1
          FROM public.productos p
         WHERE p.local_id = v_pid
    ) THEN
        RAISE EXCEPTION 'UNKNOWN_PRODUCT: producto_local_id no existe'
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
    v_pid text;
    v_inserted_one integer;
BEGIN
    IF session_user IS DISTINCT FROM current_user THEN
        RAISE EXCEPTION 'INVENTORY_FORBIDDEN: initialize_inventory_balances_from_legacy solo el owner'
            USING ERRCODE = '42501';
    END IF;
    PERFORM pg_advisory_xact_lock(
        pg_catalog.hashtextextended('ferrepro.invbal.init:legacy_cutover', 0)
    );
    IF EXISTS (
        SELECT 1
          FROM public.inventory_balance_init_state
         WHERE init_key = 'legacy_cutover'
    ) THEN
        RETURN jsonb_build_object(
            'inserted', 0,
            'source', 'legacy_cutover',
            'already_initialized', true
        );
    END IF;
    v_now := to_char(
        timezone('UTC', clock_timestamp()),
        'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'
    );
    FOR v_pid IN
        SELECT p.local_id
          FROM public.productos p
         WHERE p.local_id IS NOT NULL
           AND btrim(p.local_id) <> ''
         ORDER BY p.local_id
    LOOP
        PERFORM pg_advisory_xact_lock(
            pg_catalog.hashtextextended('ferrepro.invbal:' || v_pid, 0)
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
         WHERE p.local_id = v_pid
        ON CONFLICT (producto_local_id) DO NOTHING;
        GET DIAGNOSTICS v_inserted_one = ROW_COUNT;
        v_inserted := v_inserted + v_inserted_one;
        IF v_inserted_one > 0 THEN
            INSERT INTO public.inventory_balance_init (
                producto_local_id, quantity_scaled, source, initialized_at
            )
            SELECT
                b.producto_local_id,
                b.quantity_scaled,
                'legacy_cutover',
                v_now
              FROM public.inventory_balances b
             WHERE b.producto_local_id = v_pid
            ON CONFLICT (producto_local_id) DO NOTHING;
        END IF;
    END LOOP;
    INSERT INTO public.inventory_balance_init_state (init_key, initialized_at)
    VALUES ('legacy_cutover', v_now);
    RETURN jsonb_build_object(
        'inserted', v_inserted,
        'source', 'legacy_cutover',
        'already_initialized', false
    );
END;
$ferrepro_fn$;
-- FASE1D-END initialize_inventory_balances_from_legacy

REVOKE ALL ON FUNCTION public.apply_inventory_command(text, text, text, text, text, integer, text, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.inventory_command_to_json(text, boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.seed_inventory_balance(text, bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.initialize_inventory_balances_from_legacy() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.ferrepro_inventory_caller_is_allowed() FROM PUBLIC;
REVOKE ALL ON TABLE public.inventory_balances FROM PUBLIC;
REVOKE ALL ON TABLE public.inventory_balance_init FROM PUBLIC;
REVOKE ALL ON TABLE public.inventory_balance_init_state FROM PUBLIC;
REVOKE ALL ON TABLE public.inventory_commands FROM PUBLIC;
REVOKE ALL ON TABLE public.inventory_operations FROM PUBLIC;
REVOKE ALL ON TABLE public.inventory_reversal_allocations FROM PUBLIC;

DO $ferrepro_do$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON FUNCTION public.apply_inventory_command(text, text, text, text, text, integer, text, jsonb) FROM anon;
        REVOKE ALL ON FUNCTION public.inventory_command_to_json(text, boolean) FROM anon;
        REVOKE ALL ON FUNCTION public.seed_inventory_balance(text, bigint) FROM anon;
        REVOKE ALL ON FUNCTION public.initialize_inventory_balances_from_legacy() FROM anon;
        REVOKE ALL ON FUNCTION public.ferrepro_inventory_caller_is_allowed() FROM anon;
        REVOKE ALL ON TABLE public.inventory_balances FROM anon;
        REVOKE ALL ON TABLE public.inventory_balance_init FROM anon;
        REVOKE ALL ON TABLE public.inventory_balance_init_state FROM anon;
        REVOKE ALL ON TABLE public.inventory_commands FROM anon;
        REVOKE ALL ON TABLE public.inventory_operations FROM anon;
        REVOKE ALL ON TABLE public.inventory_reversal_allocations FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON FUNCTION public.apply_inventory_command(text, text, text, text, text, integer, text, jsonb) FROM authenticated;
        REVOKE ALL ON FUNCTION public.inventory_command_to_json(text, boolean) FROM authenticated;
        REVOKE ALL ON FUNCTION public.seed_inventory_balance(text, bigint) FROM authenticated;
        REVOKE ALL ON FUNCTION public.initialize_inventory_balances_from_legacy() FROM authenticated;
        REVOKE ALL ON FUNCTION public.ferrepro_inventory_caller_is_allowed() FROM authenticated;
        REVOKE ALL ON TABLE public.inventory_balances FROM authenticated;
        REVOKE ALL ON TABLE public.inventory_balance_init FROM authenticated;
        REVOKE ALL ON TABLE public.inventory_balance_init_state FROM authenticated;
        REVOKE ALL ON TABLE public.inventory_commands FROM authenticated;
        REVOKE ALL ON TABLE public.inventory_operations FROM authenticated;
        REVOKE ALL ON TABLE public.inventory_reversal_allocations FROM authenticated;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        REVOKE ALL ON FUNCTION public.apply_inventory_command(text, text, text, text, text, integer, text, jsonb) FROM service_role;
        REVOKE ALL ON FUNCTION public.inventory_command_to_json(text, boolean) FROM service_role;
        REVOKE ALL ON FUNCTION public.seed_inventory_balance(text, bigint) FROM service_role;
        REVOKE ALL ON FUNCTION public.initialize_inventory_balances_from_legacy() FROM service_role;
        REVOKE ALL ON FUNCTION public.ferrepro_inventory_caller_is_allowed() FROM service_role;
        REVOKE ALL ON TABLE public.inventory_balances FROM service_role;
        REVOKE ALL ON TABLE public.inventory_balance_init FROM service_role;
        REVOKE ALL ON TABLE public.inventory_balance_init_state FROM service_role;
        REVOKE ALL ON TABLE public.inventory_commands FROM service_role;
        REVOKE ALL ON TABLE public.inventory_operations FROM service_role;
        REVOKE ALL ON TABLE public.inventory_reversal_allocations FROM service_role;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ferrepro_inventory_app') THEN
        GRANT EXECUTE ON FUNCTION public.apply_inventory_command(text, text, text, text, text, integer, text, jsonb) TO ferrepro_inventory_app;
        GRANT USAGE ON SCHEMA public TO ferrepro_inventory_app;
        REVOKE ALL ON FUNCTION public.inventory_command_to_json(text, boolean) FROM ferrepro_inventory_app;
        REVOKE ALL ON FUNCTION public.seed_inventory_balance(text, bigint) FROM ferrepro_inventory_app;
        REVOKE ALL ON FUNCTION public.initialize_inventory_balances_from_legacy() FROM ferrepro_inventory_app;
        REVOKE ALL ON FUNCTION public.ferrepro_inventory_caller_is_allowed() FROM ferrepro_inventory_app;
        REVOKE ALL ON TABLE public.inventory_balances FROM ferrepro_inventory_app;
        REVOKE ALL ON TABLE public.inventory_balance_init FROM ferrepro_inventory_app;
        REVOKE ALL ON TABLE public.inventory_balance_init_state FROM ferrepro_inventory_app;
        REVOKE ALL ON TABLE public.inventory_commands FROM ferrepro_inventory_app;
        REVOKE ALL ON TABLE public.inventory_operations FROM ferrepro_inventory_app;
        REVOKE ALL ON TABLE public.inventory_reversal_allocations FROM ferrepro_inventory_app;
    END IF;
END
$ferrepro_do$;
