# -*- coding: utf-8 -*-
"""Cutover único de autoridad de inventario (Fase 1E.3 + hardening 1E.4).

Estado persistente:

    PRE_CUTOVER → CUTOVER_IN_PROGRESS → AUTHORITATIVE
                                   ↘ FAILED / ROLLBACK_SAFE

ONLINE: PostgreSQL inventory_cutover_control es la autoridad de flota.
SQLite inventory_cutover_state es cache/auditoría y no se sobrepone a un
estado remoto más reciente. Si el estado global no se puede leer, las
MUTACIONES fallan cerradas (no asumen LEGACY).

No es una constante Python. Tras reboot la aplicación relée este estado.
No ejecuta seed en startup ni en sync. No usa SUPABASE_URI.

Laboratorio: ferrepro-pg-test. Cutover productivo real (Supabase) exige
autorización humana. Este módulo no declara Fase 1 completa.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple

import schema_bootstrap
from inventory_gateway import (
    INVENTORY_DSN_ENV,
    InventoryGatewayConfigError,
    InventoryGatewayError,
    list_transmittable_command_ids,
    read_inventory_dsn,
)
from inventory_ledger import QUANTITY_SCALE, INTENT_CLASS_AUTHORITATIVE

STATUS_PRE_CUTOVER = "PRE_CUTOVER"
STATUS_CUTOVER_IN_PROGRESS = "CUTOVER_IN_PROGRESS"
STATUS_AUTHORITATIVE = "AUTHORITATIVE"
STATUS_FAILED = "FAILED"
STATUS_ROLLBACK_SAFE = "ROLLBACK_SAFE"

CUTOVER_STATUSES = (
    STATUS_PRE_CUTOVER,
    STATUS_CUTOVER_IN_PROGRESS,
    STATUS_AUTHORITATIVE,
    STATUS_FAILED,
    STATUS_ROLLBACK_SAFE,
)

SINGLETON_ID = 1

STATUS_RANK = {
    STATUS_PRE_CUTOVER: 0,
    STATUS_ROLLBACK_SAFE: 1,
    STATUS_FAILED: 2,
    STATUS_CUTOVER_IN_PROGRESS: 3,
    STATUS_AUTHORITATIVE: 4,
}

CUTOVER_STATE_UNAVAILABLE_MSG = (
    "CUTOVER_STATE_UNAVAILABLE retryable: no se puede determinar el estado "
    "global de cutover; no se asume LEGACY ni se escribe productos.stock"
)


class InventoryCutoverError(InventoryGatewayError):
    """Fallo de cutover. Fail closed: no activa autoridad."""


class InventoryFrozenError(InventoryCutoverError):
    """Writers de stock rechazados durante CUTOVER_IN_PROGRESS."""


class UnsafeRollbackError(InventoryCutoverError):
    """Rollback a legacy después del primer command autoritativo."""


class CutoverPreconditionError(InventoryCutoverError):
    """Falta una precondición. NO CUTOVER."""


class CutoverStateUnavailableError(InventoryCutoverError):
    """Estación online sin estado global confiable. Retryable. Fail closed."""

    retryable = True


class StaleCutoverStateError(InventoryCutoverError):
    """STALE_CUTOVER_STATE: expected_state/expected_epoch no coinciden."""


class LegacyReconciliationRequiredError(InventoryCutoverError):
    """Fuentes legacy (SQLite vs PostgreSQL productos.stock) no convergen."""


STATION_MODE_ENV = "FERREPRO_INVENTORY_STATION_MODE"
STATION_MODE_ONLINE = "ONLINE"
STATION_MODE_OFFLINE = "OFFLINE"
CUTOVER_EXPECTED_STATIONS_ENV = "FERREPRO_CUTOVER_EXPECTED_STATIONS"

ALLOWED_CUTOVER_TRANSITIONS = frozenset(
    {
        (STATUS_PRE_CUTOVER, STATUS_CUTOVER_IN_PROGRESS),
        (STATUS_ROLLBACK_SAFE, STATUS_CUTOVER_IN_PROGRESS),
        (STATUS_CUTOVER_IN_PROGRESS, STATUS_AUTHORITATIVE),
        (STATUS_CUTOVER_IN_PROGRESS, STATUS_ROLLBACK_SAFE),
        (STATUS_PRE_CUTOVER, STATUS_ROLLBACK_SAFE),
    }
)

LEGACY_WRITE_ALLOWED_STATUSES = frozenset(
    {
        STATUS_PRE_CUTOVER,
        STATUS_ROLLBACK_SAFE,
        STATUS_FAILED,
    }
)

# Tests pueden inyectar una barrera entre el check inicial y el fence real.
_after_legacy_allow_hook = None
_after_legacy_share_hook = None
_after_postgres_freeze_hook = None
_pos_open_act_lock = threading.RLock()


@contextmanager
def serialize_implicit_pos_act():
    """Evita que dos checkouts implícitos compartan el mismo OPEN act.

    La identidad sigue persistida en SQLite. Este lock solo ordena callers
    concurrentes del mismo proceso cuando la UI no entregó command_id; tras un
    crash, ``inventory_open_acts`` continúa siendo la fuente de recuperación.
    """
    with _pos_open_act_lock:
        yield


@dataclass(frozen=True)
class CutoverState:
    status: str = STATUS_PRE_CUTOVER
    epoch: int = 0
    seed_at: Optional[str] = None
    activated_at: Optional[str] = None
    device_id: Optional[str] = None
    reconciliation_json: Optional[str] = None
    updated_at: Optional[str] = None
    cutover_id: Optional[str] = None
    snapshot_checksum: Optional[str] = None
    source: str = "sqlite"

    @property
    def is_authoritative(self) -> bool:
        return self.status == STATUS_AUTHORITATIVE

    @property
    def is_frozen(self) -> bool:
        return self.status == STATUS_CUTOVER_IN_PROGRESS

    @property
    def seed_done(self) -> bool:
        return bool(self.seed_at)


@dataclass
class SeedReconciliation:
    productos_legacy: int = 0
    seeded: int = 0
    missing: Tuple[str, ...] = ()
    duplicates: Tuple[str, ...] = ()
    mismatch: Tuple[dict, ...] = ()
    invalid_local_id: Tuple[str, ...] = ()
    sqlite_only: Tuple[str, ...] = ()
    postgres_only: Tuple[str, ...] = ()
    extra_unexpected: Tuple[str, ...] = ()
    null_local_id: Tuple[str, ...] = ()
    already_initialized: bool = False

    @property
    def ok(self) -> bool:
        return (
            not self.missing
            and not self.duplicates
            and not self.mismatch
            and not self.invalid_local_id
            and not self.sqlite_only
            and not self.postgres_only
            and not self.extra_unexpected
            and not self.null_local_id
            and self.productos_legacy == self.seeded
        )

    def as_dict(self) -> dict:
        return {
            "productos_legacy": self.productos_legacy,
            "seeded": self.seeded,
            "missing": list(self.missing),
            "duplicates": list(self.duplicates),
            "mismatch": list(self.mismatch),
            "invalid_local_id": list(self.invalid_local_id),
            "sqlite_only": list(self.sqlite_only),
            "postgres_only": list(self.postgres_only),
            "extra_unexpected": list(self.extra_unexpected),
            "null_local_id": list(self.null_local_id),
            "already_initialized": self.already_initialized,
            "ok": self.ok,
        }


@dataclass(frozen=True)
class CutoverSnapshotLine:
    producto_local_id: str
    quantity_scaled: int


@dataclass(frozen=True)
class CutoverSnapshot:
    cutover_id: str
    epoch: int
    captured_at: str
    lines: Tuple[CutoverSnapshotLine, ...]
    checksum: str
    source: str = "legacy_reconciled"

    def as_dict(self) -> dict:
        return {
            "cutover_id": self.cutover_id,
            "epoch": self.epoch,
            "captured_at": self.captured_at,
            "checksum": self.checksum,
            "source": self.source,
            "lines": [
                {
                    "producto_local_id": line.producto_local_id,
                    "quantity_scaled": line.quantity_scaled,
                }
                for line in self.lines
            ],
        }

    def quantity_identity(self) -> Tuple[Tuple[str, int], ...]:
        return tuple(
            (line.producto_local_id, line.quantity_scaled) for line in self.lines
        )


@dataclass
class CutoverResult:
    state: CutoverState
    reconciliation: SeedReconciliation = field(default_factory=SeedReconciliation)
    preconditions: Tuple[str, ...] = ()
    aborted: bool = False
    error: Optional[str] = None
    snapshot: Optional[CutoverSnapshot] = None
    legacy_reconciliation: Optional[SeedReconciliation] = None


def _now_iso() -> str:
    from local_first_db import now_iso

    return now_iso()


def sqlite_cutover_statements() -> Tuple[str, ...]:
    return (
        """
        CREATE TABLE IF NOT EXISTS inventory_cutover_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            status TEXT NOT NULL CHECK (
                status IN (
                    'PRE_CUTOVER', 'CUTOVER_IN_PROGRESS', 'AUTHORITATIVE',
                    'FAILED', 'ROLLBACK_SAFE'
                )
            ),
            epoch INTEGER NOT NULL DEFAULT 0,
            seed_at TEXT,
            activated_at TEXT,
            device_id TEXT,
            reconciliation_json TEXT,
            updated_at TEXT NOT NULL,
            cutover_id TEXT,
            snapshot_json TEXT,
            snapshot_checksum TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS inventory_cutover_snapshot (
            cutover_id TEXT PRIMARY KEY,
            epoch INTEGER NOT NULL,
            captured_at TEXT NOT NULL,
            checksum TEXT NOT NULL,
            source TEXT NOT NULL,
            lines_json TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS inventory_act_identities (
            act_kind TEXT NOT NULL,
            act_key TEXT NOT NULL,
            command_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            PRIMARY KEY (act_kind, act_key)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS inventory_open_acts (
            act_kind TEXT NOT NULL,
            fingerprint TEXT NOT NULL DEFAULT '',
            act_key TEXT NOT NULL,
            command_id TEXT NOT NULL,
            opened_at TEXT NOT NULL,
            PRIMARY KEY (act_kind, fingerprint)
        )
        """,
    )


def postgres_cutover_sql() -> str:
    """DDL PostgreSQL del control de cutover + lectura de balance no-owner."""
    return """
CREATE TABLE IF NOT EXISTS inventory_cutover_control (
    id smallint PRIMARY KEY CHECK (id = 1),
    status text NOT NULL CHECK (
        status IN (
            'PRE_CUTOVER', 'CUTOVER_IN_PROGRESS', 'AUTHORITATIVE',
            'FAILED', 'ROLLBACK_SAFE'
        )
    ),
    epoch integer NOT NULL DEFAULT 0,
    seed_at text,
    activated_at text,
    device_id text,
    reconciliation jsonb,
    updated_at text NOT NULL,
    cutover_id text,
    snapshot jsonb,
    snapshot_checksum text
);
INSERT INTO inventory_cutover_control (id, status, epoch, updated_at)
VALUES (1, 'PRE_CUTOVER', 0, to_char(timezone('UTC', clock_timestamp()),
        'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'))
ON CONFLICT (id) DO NOTHING;
ALTER TABLE inventory_cutover_control ADD COLUMN IF NOT EXISTS cutover_id text;
ALTER TABLE inventory_cutover_control ADD COLUMN IF NOT EXISTS snapshot jsonb;
ALTER TABLE inventory_cutover_control ADD COLUMN IF NOT EXISTS snapshot_checksum text;
CREATE OR REPLACE FUNCTION public.fetch_inventory_balance(p_producto_local_id text)
RETURNS bigint
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $ferrepro_fetch$
DECLARE
    v_qty bigint;
BEGIN
    IF NOT public.ferrepro_inventory_caller_is_allowed() THEN
        RAISE EXCEPTION 'INVENTORY_FORBIDDEN: fetch_inventory_balance'
            USING ERRCODE = '42501';
    END IF;
    SELECT b.quantity_scaled
      INTO v_qty
      FROM public.inventory_balances b
     WHERE b.producto_local_id = p_producto_local_id;
    RETURN v_qty;
END;
$ferrepro_fetch$;
REVOKE ALL ON FUNCTION public.fetch_inventory_balance(text) FROM PUBLIC;
CREATE OR REPLACE FUNCTION public.lock_legacy_cutover_fence()
RETURNS TABLE(status text, epoch integer)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $ferrepro_fence$
BEGIN
    IF NOT public.ferrepro_inventory_caller_is_allowed() THEN
        RAISE EXCEPTION 'INVENTORY_FORBIDDEN: lock_legacy_cutover_fence'
            USING ERRCODE = '42501';
    END IF;
    RETURN QUERY
    SELECT c.status, c.epoch
      FROM public.inventory_cutover_control c
     WHERE c.id = 1
     FOR SHARE;
END;
$ferrepro_fence$;
REVOKE ALL ON FUNCTION public.lock_legacy_cutover_fence() FROM PUBLIC;
CREATE TABLE IF NOT EXISTS public.inventory_cutover_snapshots (
    cutover_id text PRIMARY KEY,
    epoch bigint NOT NULL,
    status text NOT NULL CHECK (status IN ('COLLECTING', 'APPROVED', 'SEEDED')),
    checksum text,
    product_count bigint,
    created_at text NOT NULL,
    approved_at text,
    seeded_at text
);
CREATE TABLE IF NOT EXISTS public.inventory_cutover_expected_stations (
    cutover_id text NOT NULL REFERENCES public.inventory_cutover_snapshots(cutover_id) ON DELETE CASCADE,
    epoch bigint NOT NULL,
    device_id text NOT NULL,
    PRIMARY KEY (cutover_id, device_id)
);
CREATE TABLE IF NOT EXISTS public.inventory_cutover_attestations (
    cutover_id text NOT NULL,
    epoch bigint NOT NULL,
    device_id text NOT NULL,
    checksum text NOT NULL,
    product_count bigint NOT NULL,
    attested_at text NOT NULL,
    PRIMARY KEY (cutover_id, device_id),
    FOREIGN KEY (cutover_id, device_id)
        REFERENCES public.inventory_cutover_expected_stations(cutover_id, device_id)
        ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS public.inventory_cutover_attestation_lines (
    cutover_id text NOT NULL,
    device_id text NOT NULL,
    producto_local_id text NOT NULL,
    quantity_scaled bigint NOT NULL,
    PRIMARY KEY (cutover_id, device_id, producto_local_id),
    FOREIGN KEY (cutover_id, device_id)
        REFERENCES public.inventory_cutover_attestations(cutover_id, device_id)
        ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS public.inventory_cutover_snapshot_lines (
    cutover_id text NOT NULL REFERENCES public.inventory_cutover_snapshots(cutover_id) ON DELETE CASCADE,
    producto_local_id text NOT NULL,
    quantity_scaled bigint NOT NULL,
    PRIMARY KEY (cutover_id, producto_local_id)
);
REVOKE ALL ON TABLE public.inventory_cutover_snapshots FROM PUBLIC;
REVOKE ALL ON TABLE public.inventory_cutover_expected_stations FROM PUBLIC;
REVOKE ALL ON TABLE public.inventory_cutover_attestations FROM PUBLIC;
REVOKE ALL ON TABLE public.inventory_cutover_attestation_lines FROM PUBLIC;
REVOKE ALL ON TABLE public.inventory_cutover_snapshot_lines FROM PUBLIC;

CREATE OR REPLACE FUNCTION public.inventory_cutover_checksum(
    p_cutover_id text,
    p_epoch bigint,
    p_lines jsonb
) RETURNS text
LANGUAGE plpgsql
IMMUTABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $ferrepro_checksum$
DECLARE
    v_count bigint;
    v_distinct bigint;
    v_lines text;
    v_material text;
BEGIN
    IF p_cutover_id IS NULL OR btrim(p_cutover_id) = ''
       OR p_lines IS NULL OR jsonb_typeof(p_lines) <> 'array' THEN
        RAISE EXCEPTION 'INVENTORY_SNAPSHOT_INVALID: referencia o líneas inválidas'
            USING ERRCODE = '22023';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(p_lines) e
         WHERE jsonb_typeof(e) <> 'object'
            OR btrim(COALESCE(e->>'producto_local_id', '')) = ''
            OR COALESCE(e->>'quantity_scaled', '') !~ '^-?[0-9]+$'
    ) THEN
        RAISE EXCEPTION 'INVENTORY_SNAPSHOT_INVALID: línea inválida'
            USING ERRCODE = '22023';
    END IF;
    SELECT COUNT(*), COUNT(DISTINCT btrim(e->>'producto_local_id'))
      INTO v_count, v_distinct
      FROM jsonb_array_elements(p_lines) e;
    IF v_count IS DISTINCT FROM v_distinct THEN
        RAISE EXCEPTION 'INVENTORY_SNAPSHOT_INVALID: producto duplicado'
            USING ERRCODE = '22023';
    END IF;
    SELECT string_agg(
               btrim(e->>'producto_local_id') || ':'
               || ((e->>'quantity_scaled')::bigint)::text || E'\n',
               '' ORDER BY btrim(e->>'producto_local_id')
           )
      INTO v_lines
      FROM jsonb_array_elements(p_lines) e;
    v_material := p_cutover_id || E'\n' || p_epoch::text || E'\n'
        || v_count::text || E'\n' || COALESCE(v_lines, '');
    RETURN encode(
        pg_catalog.sha256(pg_catalog.convert_to(v_material, 'UTF8')),
        'hex'
    );
END;
$ferrepro_checksum$;

CREATE OR REPLACE FUNCTION public.register_inventory_cutover_fleet(
    p_cutover_id text,
    p_epoch bigint,
    p_expected_device_ids jsonb
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $ferrepro_register$
DECLARE
    v_status text;
    v_epoch bigint;
    v_now text;
    v_count bigint;
    v_distinct bigint;
BEGIN
    IF session_user IS DISTINCT FROM current_user THEN
        RAISE EXCEPTION 'INVENTORY_FORBIDDEN: register fleet solo el owner'
            USING ERRCODE = '42501';
    END IF;
    IF p_expected_device_ids IS NULL
       OR jsonb_typeof(p_expected_device_ids) <> 'array'
       OR jsonb_array_length(p_expected_device_ids) = 0 THEN
        RAISE EXCEPTION 'FLEET_ATTESTATION_REQUIRED: estaciones esperadas obligatorias'
            USING ERRCODE = '22023';
    END IF;
    SELECT COUNT(*), COUNT(DISTINCT value)
      INTO v_count, v_distinct
      FROM jsonb_array_elements_text(p_expected_device_ids);
    IF v_count IS DISTINCT FROM v_distinct THEN
        RAISE EXCEPTION 'FLEET_ATTESTATION_INVALID: device_id duplicado'
            USING ERRCODE = '22023';
    END IF;
    BEGIN
        PERFORM (value::uuid)
          FROM jsonb_array_elements_text(p_expected_device_ids);
    EXCEPTION WHEN invalid_text_representation THEN
        RAISE EXCEPTION 'FLEET_ATTESTATION_INVALID: device_id debe ser UUID'
            USING ERRCODE = '22023';
    END;
    SELECT status, epoch INTO v_status, v_epoch
      FROM public.inventory_cutover_control WHERE id = 1 FOR UPDATE;
    IF v_status IS DISTINCT FROM 'CUTOVER_IN_PROGRESS'
       OR v_epoch IS DISTINCT FROM p_epoch THEN
        RAISE EXCEPTION 'STALE_CUTOVER_STATE: fleet plan exige CUTOVER_IN_PROGRESS/epoch actual'
            USING ERRCODE = '40001';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.inventory_cutover_snapshots
         WHERE cutover_id = p_cutover_id
    ) THEN
        RAISE EXCEPTION 'FLEET_ATTESTATION_INVALID: cutover_id ya registrado'
            USING ERRCODE = '22023';
    END IF;
    v_now := to_char(timezone('UTC', clock_timestamp()), 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"');
    INSERT INTO public.inventory_cutover_snapshots (
        cutover_id, epoch, status, created_at
    ) VALUES (p_cutover_id, p_epoch, 'COLLECTING', v_now);
    INSERT INTO public.inventory_cutover_expected_stations (
        cutover_id, epoch, device_id
    )
    SELECT p_cutover_id, p_epoch, value
      FROM jsonb_array_elements_text(p_expected_device_ids);
    UPDATE public.inventory_cutover_control
       SET cutover_id = p_cutover_id,
           snapshot = NULL,
           snapshot_checksum = NULL,
           updated_at = v_now
     WHERE id = 1 AND status = 'CUTOVER_IN_PROGRESS' AND epoch = p_epoch;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'STALE_CUTOVER_STATE: fleet plan perdió CAS'
            USING ERRCODE = '40001';
    END IF;
    RETURN jsonb_build_object(
        'cutover_id', p_cutover_id,
        'epoch', p_epoch,
        'expected_stations', v_count,
        'status', 'COLLECTING'
    );
END;
$ferrepro_register$;

CREATE OR REPLACE FUNCTION public.submit_inventory_cutover_attestation(
    p_cutover_id text,
    p_epoch bigint,
    p_device_id text,
    p_checksum text,
    p_product_count bigint,
    p_lines jsonb
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $ferrepro_attest$
DECLARE
    v_status text;
    v_epoch bigint;
    v_plan_status text;
    v_checksum text;
    v_count bigint;
    v_now text;
BEGIN
    IF session_user IS DISTINCT FROM current_user THEN
        RAISE EXCEPTION 'INVENTORY_FORBIDDEN: atestación solo el cutover admin'
            USING ERRCODE = '42501';
    END IF;
    SELECT status, epoch INTO v_status, v_epoch
      FROM public.inventory_cutover_control WHERE id = 1 FOR SHARE;
    IF v_status IS DISTINCT FROM 'CUTOVER_IN_PROGRESS'
       OR v_epoch IS DISTINCT FROM p_epoch THEN
        RAISE EXCEPTION 'STALE_CUTOVER_STATE: atestación fuera del epoch activo'
            USING ERRCODE = '40001';
    END IF;
    SELECT status INTO v_plan_status
      FROM public.inventory_cutover_snapshots
     WHERE cutover_id = p_cutover_id AND epoch = p_epoch
     FOR UPDATE;
    IF NOT FOUND OR v_plan_status IS DISTINCT FROM 'COLLECTING' THEN
        RAISE EXCEPTION 'FLEET_ATTESTATION_CLOSED: snapshot no acepta atestaciones'
            USING ERRCODE = '22023';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.inventory_cutover_expected_stations
         WHERE cutover_id = p_cutover_id
           AND epoch = p_epoch
           AND device_id = p_device_id
    ) THEN
        RAISE EXCEPTION 'FLEET_ATTESTATION_UNEXPECTED_STATION: %', p_device_id
            USING ERRCODE = '22023';
    END IF;
    v_count := jsonb_array_length(p_lines);
    IF p_product_count IS DISTINCT FROM v_count THEN
        RAISE EXCEPTION 'FLEET_ATTESTATION_INVALID: product_count divergente'
            USING ERRCODE = '22023';
    END IF;
    v_checksum := public.inventory_cutover_checksum(p_cutover_id, p_epoch, p_lines);
    IF lower(COALESCE(p_checksum, '')) IS DISTINCT FROM v_checksum THEN
        RAISE EXCEPTION 'FLEET_ATTESTATION_INVALID: checksum inválido'
            USING ERRCODE = '22023';
    END IF;
    DELETE FROM public.inventory_cutover_attestation_lines
     WHERE cutover_id = p_cutover_id AND device_id = p_device_id;
    DELETE FROM public.inventory_cutover_attestations
     WHERE cutover_id = p_cutover_id AND device_id = p_device_id;
    v_now := to_char(timezone('UTC', clock_timestamp()), 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"');
    INSERT INTO public.inventory_cutover_attestations (
        cutover_id, epoch, device_id, checksum, product_count, attested_at
    ) VALUES (
        p_cutover_id, p_epoch, p_device_id, v_checksum, v_count, v_now
    );
    INSERT INTO public.inventory_cutover_attestation_lines (
        cutover_id, device_id, producto_local_id, quantity_scaled
    )
    SELECT p_cutover_id, p_device_id,
           btrim(e->>'producto_local_id'),
           (e->>'quantity_scaled')::bigint
      FROM jsonb_array_elements(p_lines) e;
    RETURN jsonb_build_object(
        'cutover_id', p_cutover_id,
        'epoch', p_epoch,
        'device_id', p_device_id,
        'checksum', v_checksum,
        'product_count', v_count
    );
END;
$ferrepro_attest$;

CREATE OR REPLACE FUNCTION public.approve_inventory_cutover_snapshot(
    p_cutover_id text,
    p_epoch bigint
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $ferrepro_approve$
DECLARE
    v_status text;
    v_epoch bigint;
    v_control_cutover text;
    v_plan_status text;
    v_expected bigint;
    v_received bigint;
    v_checksums bigint;
    v_counts bigint;
    v_checksum text;
    v_product_count bigint;
    v_reference text;
    v_lines jsonb;
    v_now text;
BEGIN
    IF session_user IS DISTINCT FROM current_user THEN
        RAISE EXCEPTION 'INVENTORY_FORBIDDEN: approve snapshot solo el owner'
            USING ERRCODE = '42501';
    END IF;
    SELECT status, epoch, cutover_id
      INTO v_status, v_epoch, v_control_cutover
      FROM public.inventory_cutover_control WHERE id = 1 FOR UPDATE;
    IF v_status IS DISTINCT FROM 'CUTOVER_IN_PROGRESS'
       OR v_epoch IS DISTINCT FROM p_epoch
       OR v_control_cutover IS DISTINCT FROM p_cutover_id THEN
        RAISE EXCEPTION 'STALE_CUTOVER_STATE: aprobación fuera del cutover activo'
            USING ERRCODE = '40001';
    END IF;
    SELECT status INTO v_plan_status
      FROM public.inventory_cutover_snapshots
     WHERE cutover_id = p_cutover_id AND epoch = p_epoch
     FOR UPDATE;
    IF NOT FOUND OR v_plan_status IS DISTINCT FROM 'COLLECTING' THEN
        RAISE EXCEPTION 'FLEET_ATTESTATION_INVALID: snapshot no está COLLECTING'
            USING ERRCODE = '22023';
    END IF;
    SELECT COUNT(*) INTO v_expected
      FROM public.inventory_cutover_expected_stations
     WHERE cutover_id = p_cutover_id AND epoch = p_epoch;
    SELECT COUNT(*), COUNT(DISTINCT checksum), COUNT(DISTINCT product_count),
           MIN(checksum), MIN(product_count), MIN(device_id)
      INTO v_received, v_checksums, v_counts,
           v_checksum, v_product_count, v_reference
      FROM public.inventory_cutover_attestations
     WHERE cutover_id = p_cutover_id AND epoch = p_epoch;
    IF v_expected = 0 OR v_received IS DISTINCT FROM v_expected THEN
        RAISE EXCEPTION 'FLEET_ATTESTATION_MISSING: expected=% received=%',
            v_expected, v_received USING ERRCODE = '22023';
    END IF;
    IF v_checksums IS DISTINCT FROM 1 OR v_counts IS DISTINCT FROM 1 THEN
        RAISE EXCEPTION 'FLEET_ATTESTATION_DIVERGENT: estaciones no convergen'
            USING ERRCODE = '22023';
    END IF;
    DELETE FROM public.inventory_cutover_snapshot_lines
     WHERE cutover_id = p_cutover_id;
    INSERT INTO public.inventory_cutover_snapshot_lines (
        cutover_id, producto_local_id, quantity_scaled
    )
    SELECT cutover_id, producto_local_id, quantity_scaled
      FROM public.inventory_cutover_attestation_lines
     WHERE cutover_id = p_cutover_id AND device_id = v_reference;
    SELECT COALESCE(
               jsonb_agg(
                   jsonb_build_object(
                       'producto_local_id', producto_local_id,
                       'quantity_scaled', quantity_scaled
                   ) ORDER BY producto_local_id
               ),
               '[]'::jsonb
           )
      INTO v_lines
      FROM public.inventory_cutover_snapshot_lines
     WHERE cutover_id = p_cutover_id;
    IF public.inventory_cutover_checksum(p_cutover_id, p_epoch, v_lines)
       IS DISTINCT FROM v_checksum THEN
        RAISE EXCEPTION 'FLEET_ATTESTATION_DIVERGENT: líneas no coinciden con checksum'
            USING ERRCODE = '22023';
    END IF;
    v_now := to_char(timezone('UTC', clock_timestamp()), 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"');
    UPDATE public.inventory_cutover_snapshots
       SET status = 'APPROVED', checksum = v_checksum,
           product_count = v_product_count, approved_at = v_now
     WHERE cutover_id = p_cutover_id AND epoch = p_epoch
       AND status = 'COLLECTING';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'STALE_CUTOVER_STATE: aprobación perdió CAS'
            USING ERRCODE = '40001';
    END IF;
    UPDATE public.inventory_cutover_control
       SET snapshot = jsonb_build_object(
               'cutover_id', p_cutover_id,
               'epoch', p_epoch,
               'checksum', v_checksum,
               'product_count', v_product_count,
               'status', 'APPROVED'
           ),
           snapshot_checksum = v_checksum,
           updated_at = v_now
     WHERE id = 1 AND status = 'CUTOVER_IN_PROGRESS'
       AND epoch = p_epoch AND cutover_id = p_cutover_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'STALE_CUTOVER_STATE: metadata approval perdió CAS'
            USING ERRCODE = '40001';
    END IF;
    RETURN jsonb_build_object(
        'cutover_id', p_cutover_id,
        'epoch', p_epoch,
        'checksum', v_checksum,
        'product_count', v_product_count,
        'status', 'APPROVED'
    );
END;
$ferrepro_approve$;

DROP FUNCTION IF EXISTS public.initialize_inventory_balances_from_snapshot(jsonb);
CREATE OR REPLACE FUNCTION public.initialize_inventory_balances_from_snapshot(
    p_cutover_id text,
    p_epoch bigint
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $ferrepro_snap$
DECLARE
    v_status text;
    v_epoch bigint;
    v_control_cutover text;
    v_snapshot_status text;
    v_checksum text;
    v_computed_checksum text;
    v_product_count bigint;
    v_lines jsonb;
    v_now text;
    v_inserted bigint := 0;
    v_pid text;
    v_qty bigint;
    v_inserted_one integer;
BEGIN
    IF session_user IS DISTINCT FROM current_user THEN
        RAISE EXCEPTION 'INVENTORY_FORBIDDEN: initialize_inventory_balances_from_snapshot solo el owner'
            USING ERRCODE = '42501';
    END IF;
    SELECT status, epoch, cutover_id
      INTO v_status, v_epoch, v_control_cutover
      FROM public.inventory_cutover_control WHERE id = 1 FOR UPDATE;
    IF v_status IS DISTINCT FROM 'CUTOVER_IN_PROGRESS'
       OR v_epoch IS DISTINCT FROM p_epoch
       OR v_control_cutover IS DISTINCT FROM p_cutover_id THEN
        RAISE EXCEPTION 'STALE_CUTOVER_STATE: seed fuera del cutover aprobado'
            USING ERRCODE = '40001';
    END IF;
    SELECT status, checksum, product_count
      INTO v_snapshot_status, v_checksum, v_product_count
      FROM public.inventory_cutover_snapshots
     WHERE cutover_id = p_cutover_id AND epoch = p_epoch
     FOR UPDATE;
    IF NOT FOUND OR v_snapshot_status NOT IN ('APPROVED', 'SEEDED')
       OR v_checksum IS NULL THEN
        RAISE EXCEPTION 'INVENTORY_SNAPSHOT_NOT_APPROVED'
            USING ERRCODE = '22023';
    END IF;
    PERFORM 1
      FROM public.inventory_cutover_snapshot_lines
     WHERE cutover_id = p_cutover_id
     FOR SHARE;
    SELECT COALESCE(
               jsonb_agg(
                   jsonb_build_object(
                       'producto_local_id', producto_local_id,
                       'quantity_scaled', quantity_scaled
                   ) ORDER BY producto_local_id
               ),
               '[]'::jsonb
           )
      INTO v_lines
      FROM public.inventory_cutover_snapshot_lines
     WHERE cutover_id = p_cutover_id;
    v_computed_checksum := public.inventory_cutover_checksum(
        p_cutover_id, p_epoch, v_lines
    );
    IF jsonb_array_length(v_lines) IS DISTINCT FROM v_product_count
       OR v_computed_checksum IS DISTINCT FROM v_checksum THEN
        RAISE EXCEPTION 'INVENTORY_SNAPSHOT_INVALID: líneas aprobadas no coinciden con checksum'
            USING ERRCODE = '22023';
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
            'source', 'cutover_snapshot',
            'already_initialized', true,
            'checksum', v_checksum
        );
    END IF;
    v_now := to_char(
        timezone('UTC', clock_timestamp()),
        'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'
    );
    FOR v_pid, v_qty IN
        SELECT producto_local_id, quantity_scaled
          FROM public.inventory_cutover_snapshot_lines
         WHERE cutover_id = p_cutover_id
         ORDER BY producto_local_id
    LOOP
        PERFORM pg_advisory_xact_lock(
            pg_catalog.hashtextextended('ferrepro.invbal:' || v_pid, 0)
        );
        INSERT INTO public.inventory_balances (
            producto_local_id, quantity_scaled, created_at, updated_at
        ) VALUES (v_pid, v_qty, v_now, v_now)
        ON CONFLICT (producto_local_id) DO NOTHING;
        GET DIAGNOSTICS v_inserted_one = ROW_COUNT;
        v_inserted := v_inserted + v_inserted_one;
        IF v_inserted_one > 0 THEN
            INSERT INTO public.inventory_balance_init (
                producto_local_id, quantity_scaled, source, initialized_at
            ) VALUES (v_pid, v_qty, 'cutover_snapshot', v_now)
            ON CONFLICT (producto_local_id) DO NOTHING;
        END IF;
    END LOOP;
    INSERT INTO public.inventory_balance_init_state (init_key, initialized_at)
    VALUES ('legacy_cutover', v_now);
    UPDATE public.inventory_cutover_snapshots
       SET status = 'SEEDED', seeded_at = v_now
     WHERE cutover_id = p_cutover_id AND epoch = p_epoch
       AND status = 'APPROVED';
    RETURN jsonb_build_object(
        'inserted', v_inserted,
        'source', 'cutover_snapshot',
        'already_initialized', false,
        'checksum', v_checksum
    );
END;
$ferrepro_snap$;
REVOKE ALL ON FUNCTION public.inventory_cutover_checksum(text, bigint, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.register_inventory_cutover_fleet(text, bigint, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.submit_inventory_cutover_attestation(text, bigint, text, text, bigint, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.approve_inventory_cutover_snapshot(text, bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.initialize_inventory_balances_from_snapshot(text, bigint) FROM PUBLIC;
DO $ferrepro_cutover_grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ferrepro_inventory_app') THEN
        GRANT SELECT ON TABLE public.inventory_cutover_control TO ferrepro_inventory_app;
        REVOKE INSERT, UPDATE, DELETE ON TABLE public.inventory_cutover_control
            FROM ferrepro_inventory_app;
        GRANT EXECUTE ON FUNCTION public.fetch_inventory_balance(text)
            TO ferrepro_inventory_app;
        GRANT EXECUTE ON FUNCTION public.lock_legacy_cutover_fence()
            TO ferrepro_inventory_app;
        REVOKE ALL ON TABLE public.inventory_cutover_snapshots,
            public.inventory_cutover_expected_stations,
            public.inventory_cutover_attestations,
            public.inventory_cutover_attestation_lines,
            public.inventory_cutover_snapshot_lines
            FROM ferrepro_inventory_app;
        REVOKE ALL ON FUNCTION public.register_inventory_cutover_fleet(text, bigint, jsonb)
            FROM ferrepro_inventory_app;
        REVOKE ALL ON FUNCTION public.submit_inventory_cutover_attestation(
            text, bigint, text, text, bigint, jsonb
        ) FROM ferrepro_inventory_app;
        REVOKE ALL ON FUNCTION public.approve_inventory_cutover_snapshot(text, bigint)
            FROM ferrepro_inventory_app;
        REVOKE ALL ON FUNCTION public.initialize_inventory_balances_from_snapshot(text, bigint)
            FROM ferrepro_inventory_app;
    END IF;
END
$ferrepro_cutover_grants$;
"""


def ensure_cutover_schema(conn) -> None:
    """SQLite: estado de cutover + identidades de acto. Idempotente."""
    if not schema_bootstrap.is_sqlite_connection(conn):
        raise InventoryCutoverError("ensure_cutover_schema solo aplica a SQLite")
    for statement in sqlite_cutover_statements():
        conn.execute(statement)
    row = conn.execute(
        "SELECT 1 FROM inventory_cutover_state WHERE id = ?", (SINGLETON_ID,)
    ).fetchone()
    if row is None:
        conn.execute(
            """
            INSERT INTO inventory_cutover_state (id, status, epoch, updated_at)
            VALUES (?, ?, 0, ?)
            """,
            (SINGLETON_ID, STATUS_PRE_CUTOVER, _now_iso()),
        )
        conn.commit()
    _ensure_sqlite_cutover_columns(conn)


def _ensure_sqlite_cutover_columns(conn) -> None:
    cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(inventory_cutover_state)").fetchall()
    }
    added = False
    for name, decl in (
        ("cutover_id", "TEXT"),
        ("snapshot_json", "TEXT"),
        ("snapshot_checksum", "TEXT"),
    ):
        if name not in cols:
            conn.execute(
                f"ALTER TABLE inventory_cutover_state ADD COLUMN {name} {decl}"
            )
            added = True
    if added:
        conn.commit()


def ensure_postgres_cutover_schema(pg_conn) -> None:
    if schema_bootstrap.is_sqlite_connection(pg_conn):
        raise InventoryCutoverError("schema de cutover remoto solo PostgreSQL")
    with pg_conn.cursor() as cur:
        cur.execute(postgres_cutover_sql())
    pg_conn.commit()


def _mapping_get(row, key, index, default=None):
    if row is None:
        return default
    if hasattr(row, "keys"):
        try:
            return row[key]
        except (KeyError, IndexError, TypeError):
            return default
    try:
        return row[index]
    except (IndexError, TypeError):
        return default


def _row_status(row, *, source: str = "sqlite") -> CutoverState:
    if row is None:
        return CutoverState(source=source)
    return CutoverState(
        status=str(_mapping_get(row, "status", 1) or STATUS_PRE_CUTOVER),
        epoch=int(_mapping_get(row, "epoch", 2) or 0),
        seed_at=_mapping_get(row, "seed_at", 3),
        activated_at=_mapping_get(row, "activated_at", 4),
        device_id=_mapping_get(row, "device_id", 5),
        reconciliation_json=_mapping_get(row, "reconciliation_json", 6),
        updated_at=_mapping_get(row, "updated_at", 7),
        cutover_id=_mapping_get(row, "cutover_id", 8),
        snapshot_checksum=_mapping_get(row, "snapshot_checksum", 9),
        source=source,
    )


def load_cutover_state(conn) -> CutoverState:
    """Relée cache SQLite. No usa el flag INVENTORY_CUTOVER_ENABLED."""
    if not schema_bootstrap.is_sqlite_connection(conn):
        raise InventoryCutoverError("load_cutover_state espera SQLite local")
    ensure_cutover_schema(conn)
    row = conn.execute(
        "SELECT id, status, epoch, seed_at, activated_at, device_id, "
        "reconciliation_json, updated_at, cutover_id, snapshot_checksum "
        "FROM inventory_cutover_state WHERE id = ?",
        (SINGLETON_ID,),
    ).fetchone()
    return _row_status(row, source="sqlite")


def station_mode_is_online(*, environ: Optional[Mapping[str, str]] = None) -> bool:
    """ONLINE por defecto. OFFLINE solo si el modo está explícito.

    No se infiere OFFLINE por ausencia de FERREPRO_INVENTORY_DSN.
    """
    env = environ if environ is not None else os.environ
    raw = str(env.get(STATION_MODE_ENV, STATION_MODE_ONLINE) or STATION_MODE_ONLINE)
    return raw.strip().upper() not in ("OFFLINE", "0", "FALSE", "NO")


def _station_must_observe_remote(
    *,
    pg_conn=None,
    connection_factory=None,
    require_remote: Optional[bool] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> bool:
    if require_remote is True:
        return True
    if require_remote is False:
        return False
    if pg_conn is not None or connection_factory is not None:
        return True
    return station_mode_is_online(environ=environ)


def _open_observer_connection(pg_conn=None, connection_factory=None):
    if pg_conn is not None:
        return pg_conn, False
    factory = connection_factory
    if factory is None:
        factory = app_connection_factory_from_env()
    return factory(), True


def load_postgres_cutover_state(pg_conn, *, ensure_schema: bool = True) -> CutoverState:
    if ensure_schema:
        try:
            ensure_postgres_cutover_schema(pg_conn)
        except Exception:
            try:
                pg_conn.rollback()
            except Exception:
                pass
    try:
        with pg_conn.cursor() as cur:
            cur.execute(
                "SELECT status, epoch, seed_at, activated_at, device_id, "
                "reconciliation::text, updated_at, cutover_id, snapshot_checksum "
                "FROM inventory_cutover_control WHERE id = 1"
            )
            row = cur.fetchone()
        try:
            pg_conn.rollback()
        except Exception:
            pass
    except Exception as exc:
        try:
            pg_conn.rollback()
        except Exception:
            pass
        raise CutoverStateUnavailableError(CUTOVER_STATE_UNAVAILABLE_MSG) from exc
    if row is None:
        return CutoverState(source="postgres")
    return CutoverState(
        status=str(row[0]),
        epoch=int(row[1] or 0),
        seed_at=row[2],
        activated_at=row[3],
        device_id=row[4],
        reconciliation_json=row[5],
        updated_at=row[6],
        cutover_id=row[7],
        snapshot_checksum=row[8],
        source="postgres",
    )


def observe_cutover_state(
    sqlite_conn,
    *,
    pg_conn=None,
    connection_factory=None,
    require_remote: Optional[bool] = None,
    cache: bool = True,
) -> CutoverState:
    """ONLINE: PostgreSQL gana. SQLite es cache. Mutaciones no asumen LEGACY."""
    local = load_cutover_state(sqlite_conn)
    if not _station_must_observe_remote(
        pg_conn=pg_conn,
        connection_factory=connection_factory,
        require_remote=require_remote,
    ):
        return local
    owned = False
    remote_conn = None
    try:
        remote_conn, owned = _open_observer_connection(
            pg_conn=pg_conn, connection_factory=connection_factory
        )
        remote = load_postgres_cutover_state(remote_conn, ensure_schema=False)
    except CutoverStateUnavailableError:
        raise
    except Exception as exc:
        raise CutoverStateUnavailableError(CUTOVER_STATE_UNAVAILABLE_MSG) from exc
    finally:
        if owned and remote_conn is not None:
            try:
                remote_conn.close()
            except Exception:
                pass
    if cache and (
        local.status != remote.status
        or local.epoch != remote.epoch
        or local.cutover_id != remote.cutover_id
    ):
        try:
            _cache_sqlite_from_remote(sqlite_conn, remote)
        except Exception:
            pass
    return remote


def _cache_sqlite_from_remote(sqlite_conn, remote: CutoverState) -> None:
    _write_sqlite_state(
        sqlite_conn,
        status=remote.status,
        epoch=remote.epoch,
        seed_at=remote.seed_at,
        activated_at=remote.activated_at,
        device_id=remote.device_id,
        reconciliation_json=remote.reconciliation_json,
        cutover_id=remote.cutover_id,
        snapshot_checksum=remote.snapshot_checksum,
    )


def is_cutover_authoritative(
    conn,
    *,
    pg_conn=None,
    connection_factory=None,
    require_remote: Optional[bool] = None,
) -> bool:
    if _station_must_observe_remote(
        pg_conn=pg_conn,
        connection_factory=connection_factory,
        require_remote=require_remote,
    ):
        return observe_cutover_state(
            conn,
            pg_conn=pg_conn,
            connection_factory=connection_factory,
            require_remote=require_remote,
        ).is_authoritative
    try:
        return load_cutover_state(conn).is_authoritative
    except Exception:
        return False


def is_inventory_frozen(
    conn,
    *,
    pg_conn=None,
    connection_factory=None,
    require_remote: Optional[bool] = None,
) -> bool:
    if _station_must_observe_remote(
        pg_conn=pg_conn,
        connection_factory=connection_factory,
        require_remote=require_remote,
    ):
        return observe_cutover_state(
            conn,
            pg_conn=pg_conn,
            connection_factory=connection_factory,
            require_remote=require_remote,
        ).is_frozen
    try:
        return load_cutover_state(conn).is_frozen
    except Exception:
        return False


def assert_inventory_writes_allowed(
    conn,
    *,
    pg_conn=None,
    connection_factory=None,
    require_remote: Optional[bool] = None,
    cache: bool = True,
) -> CutoverState:
    """Mutaciones: freeze global o estado ilegible → error. No asume LEGACY.

    cache=False en el fence de commit: observe no debe commitear la
    transacción SQLite de stock antes del candado central.
    """
    state = observe_cutover_state(
        conn,
        pg_conn=pg_conn,
        connection_factory=connection_factory,
        require_remote=require_remote,
        cache=cache,
    )
    if state.is_frozen:
        raise InventoryFrozenError(
            "Inventario congelado: CUTOVER_IN_PROGRESS. "
            "No se aceptan ventas, compras, ajustes ni operaciones LAN."
        )
    return state


def set_after_legacy_allow_hook(hook: Optional[Callable]) -> None:
    """Barrera de test entre check inicial y fence de mutación. No usar en producción."""
    global _after_legacy_allow_hook
    _after_legacy_allow_hook = hook


def set_after_legacy_share_hook(hook: Optional[Callable]) -> None:
    """Barrera de test con FOR KEY SHARE ya tomado. No usar en producción."""
    global _after_legacy_share_hook
    _after_legacy_share_hook = hook


def set_after_postgres_freeze_hook(hook: Optional[Callable]) -> None:
    """Barrera de test tras CAS PG de freeze, antes del cache SQLite."""
    global _after_postgres_freeze_hook
    _after_postgres_freeze_hook = hook


def cas_postgres_cutover_state(
    pg_conn,
    *,
    expected_status: str,
    expected_epoch: int,
    new_status: str,
    new_epoch: int,
    seed_at: Optional[str] = None,
    activated_at: Optional[str] = None,
    device_id: Optional[str] = None,
    reconciliation: Optional[Mapping[str, Any]] = None,
    cutover_id: Optional[str] = None,
    snapshot: Optional[Mapping[str, Any]] = None,
    snapshot_checksum: Optional[str] = None,
) -> None:
    """Transición global condicional. Epoch nunca retrocede. Verifica rowcount."""
    if int(new_epoch) != int(expected_epoch) + 1:
        raise StaleCutoverStateError(
            "STALE_CUTOVER_STATE: epoch debe avanzar exactamente +1; "
            f"expected_epoch={expected_epoch} new_epoch={new_epoch}"
        )
    if (expected_status, new_status) not in ALLOWED_CUTOVER_TRANSITIONS:
        raise StaleCutoverStateError(
            f"STALE_CUTOVER_STATE: transición {expected_status} → {new_status} "
            "no permitida"
        )
    stamp = _now_iso()
    recon = json.dumps(dict(reconciliation)) if reconciliation is not None else None
    snap = json.dumps(dict(snapshot)) if snapshot is not None else None
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT status, epoch FROM inventory_cutover_control WHERE id = 1 FOR UPDATE"
        )
        row = cur.fetchone()
        if row is None:
            pg_conn.rollback()
            raise CutoverStateUnavailableError(CUTOVER_STATE_UNAVAILABLE_MSG)
        got_status = str(row[0])
        got_epoch = int(row[1] or 0)
        if got_status != expected_status or got_epoch != int(expected_epoch):
            pg_conn.rollback()
            raise StaleCutoverStateError(
                f"STALE_CUTOVER_STATE: expected {expected_status}/{expected_epoch} "
                f"got {got_status}/{got_epoch}"
            )
        cur.execute(
            """
            UPDATE inventory_cutover_control
               SET status = %s,
                   epoch = %s,
                   seed_at = COALESCE(%s, seed_at),
                   activated_at = COALESCE(%s, activated_at),
                   device_id = COALESCE(%s, device_id),
                   reconciliation = COALESCE(%s::jsonb, reconciliation),
                   updated_at = %s,
                   cutover_id = COALESCE(%s, cutover_id),
                   snapshot = COALESCE(%s::jsonb, snapshot),
                   snapshot_checksum = COALESCE(%s, snapshot_checksum)
             WHERE id = 1 AND status = %s AND epoch = %s
            """,
            (
                new_status,
                int(new_epoch),
                seed_at,
                activated_at,
                device_id,
                recon,
                stamp,
                cutover_id,
                snap,
                snapshot_checksum,
                expected_status,
                int(expected_epoch),
            ),
        )
        if cur.rowcount != 1:
            pg_conn.rollback()
            raise StaleCutoverStateError("STALE_CUTOVER_STATE: CAS rowcount 0")
    pg_conn.commit()


def touch_postgres_cutover_metadata(
    pg_conn,
    *,
    expected_status: str,
    expected_epoch: int,
    seed_at: Optional[str] = None,
    device_id: Optional[str] = None,
    reconciliation: Optional[Mapping[str, Any]] = None,
    cutover_id: Optional[str] = None,
    snapshot: Optional[Mapping[str, Any]] = None,
    snapshot_checksum: Optional[str] = None,
) -> None:
    """Actualiza metadata sin cambiar state/epoch. CAS sobre el par actual."""
    stamp = _now_iso()
    recon = json.dumps(dict(reconciliation)) if reconciliation is not None else None
    snap = json.dumps(dict(snapshot)) if snapshot is not None else None
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            UPDATE inventory_cutover_control
               SET seed_at = COALESCE(%s, seed_at),
                   device_id = COALESCE(%s, device_id),
                   reconciliation = COALESCE(%s::jsonb, reconciliation),
                   updated_at = %s,
                   cutover_id = COALESCE(%s, cutover_id),
                   snapshot = COALESCE(%s::jsonb, snapshot),
                   snapshot_checksum = COALESCE(%s, snapshot_checksum)
             WHERE id = 1 AND status = %s AND epoch = %s
            """,
            (
                seed_at,
                device_id,
                recon,
                stamp,
                cutover_id,
                snap,
                snapshot_checksum,
                expected_status,
                int(expected_epoch),
            ),
        )
        if cur.rowcount != 1:
            pg_conn.rollback()
            raise StaleCutoverStateError(
                "STALE_CUTOVER_STATE: metadata CAS rowcount 0"
            )
    pg_conn.commit()


@contextmanager
def legacy_write_fence(
    sqlite_conn,
    *,
    pg_conn=None,
    connection_factory=None,
    require_remote: Optional[bool] = None,
):
    """Fence real de mutación legacy.

    FOR SHARE via lock_legacy_cutover_fence() (SECURITY DEFINER). El rol
    de aplicación solo tiene SELECT; PostgreSQL 16 exige UPDATE para
    SELECT ... FOR SHARE/KEY SHARE directo. Freeze usa FOR UPDATE + CAS.
    Si el freeze ya publicó CUTOVER_IN_PROGRESS, esta guarda no commitea stock.
    Si el writer sostiene el lock, freeze espera a que termine.
    Observe del fence usa cache=False: un cache SQLite no puede commitear
    productos.stock antes del candado central.
    """
    state = assert_inventory_writes_allowed(
        sqlite_conn,
        pg_conn=pg_conn,
        connection_factory=connection_factory,
        require_remote=require_remote,
        cache=False,
    )
    hook = _after_legacy_allow_hook
    if callable(hook):
        hook(state)
    if not _station_must_observe_remote(
        pg_conn=pg_conn,
        connection_factory=connection_factory,
        require_remote=require_remote,
    ):
        if state.is_frozen:
            raise InventoryFrozenError(
                "Inventario congelado: CUTOVER_IN_PROGRESS. "
                "No se aceptan ventas, compras, ajustes ni operaciones LAN."
            )
        yield state
        return
    owned = False
    fence_conn = pg_conn
    try:
        if fence_conn is None:
            factory = connection_factory
            if factory is None:
                factory = app_connection_factory_from_env()
            fence_conn = factory()
            owned = True
        with fence_conn.cursor() as cur:
            cur.execute("SELECT status, epoch FROM lock_legacy_cutover_fence()")
            row = cur.fetchone()
        if row is None:
            fence_conn.rollback()
            raise CutoverStateUnavailableError(CUTOVER_STATE_UNAVAILABLE_MSG)
        status = str(row[0])
        epoch = int(row[1] or 0)
        if status == STATUS_CUTOVER_IN_PROGRESS:
            fence_conn.rollback()
            raise InventoryFrozenError(
                "Inventario congelado: CUTOVER_IN_PROGRESS. "
                "No se aceptan ventas, compras, ajustes ni operaciones LAN."
            )
        if status not in LEGACY_WRITE_ALLOWED_STATUSES:
            fence_conn.rollback()
            raise InventoryCutoverError(
                f"legacy write no permitido en estado {status}"
            )
        share_hook = _after_legacy_share_hook
        if callable(share_hook):
            share_hook(status, epoch)
        yield CutoverState(status=status, epoch=epoch, source="postgres")
        fence_conn.commit()
    except InventoryGatewayConfigError as exc:
        try:
            if fence_conn is not None:
                fence_conn.rollback()
        except Exception:
            pass
        raise CutoverStateUnavailableError(CUTOVER_STATE_UNAVAILABLE_MSG) from exc
    except Exception:
        try:
            if fence_conn is not None:
                fence_conn.rollback()
        except Exception:
            pass
        raise
    finally:
        if owned and fence_conn is not None:
            try:
                fence_conn.close()
            except Exception:
                pass


def commit_legacy_inventory(
    sqlite_conn,
    *,
    pg_conn=None,
    connection_factory=None,
    require_remote: Optional[bool] = None,
) -> None:
    """Commit SQLite de stock solo si el fence central sigue permitiendo legacy."""
    with legacy_write_fence(
        sqlite_conn,
        pg_conn=pg_conn,
        connection_factory=connection_factory,
        require_remote=require_remote,
    ):
        sqlite_conn.commit()


def legacy_stock_to_scaled(value: Any) -> int:
    """stock legacy → quantity_scaled. Decimal/str/int. Nunca float * 1000."""
    from inventory_ledger import QuantityScaleError, quantity_to_scaled

    if value is None:
        value = 0
    if isinstance(value, float):
        raise QuantityScaleError(
            "stock binario float no es exacto; use Decimal o texto canónico"
        )
    if isinstance(value, Decimal):
        return quantity_to_scaled(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return quantity_to_scaled(value)
    text = str(value).strip()
    if not text:
        return quantity_to_scaled(0)
    try:
        decimal_value = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise QuantityScaleError(f"stock no numérico: {value!r}") from exc
    return quantity_to_scaled(decimal_value)


def _write_sqlite_state(
    conn,
    *,
    status: str,
    epoch: Optional[int] = None,
    seed_at: Optional[str] = None,
    activated_at: Optional[str] = None,
    device_id: Optional[str] = None,
    reconciliation_json: Optional[str] = None,
    cutover_id: Optional[str] = None,
    snapshot_json: Optional[str] = None,
    snapshot_checksum: Optional[str] = None,
) -> CutoverState:
    ensure_cutover_schema(conn)
    current = load_cutover_state(conn)
    stamp = _now_iso()
    new_epoch = current.epoch if epoch is None else int(epoch)
    conn.execute(
        """
        UPDATE inventory_cutover_state
           SET status = ?,
               epoch = ?,
               seed_at = COALESCE(?, seed_at),
               activated_at = COALESCE(?, activated_at),
               device_id = COALESCE(?, device_id),
               reconciliation_json = COALESCE(?, reconciliation_json),
               updated_at = ?,
               cutover_id = COALESCE(?, cutover_id),
               snapshot_json = COALESCE(?, snapshot_json),
               snapshot_checksum = COALESCE(?, snapshot_checksum)
         WHERE id = ?
        """,
        (
            status,
            new_epoch,
            seed_at,
            activated_at,
            device_id,
            reconciliation_json,
            stamp,
            cutover_id,
            snapshot_json,
            snapshot_checksum,
            SINGLETON_ID,
        ),
    )
    conn.commit()
    return load_cutover_state(conn)


def _write_postgres_state(
    pg_conn,
    *,
    status: str,
    epoch: Optional[int] = None,
    seed_at: Optional[str] = None,
    activated_at: Optional[str] = None,
    device_id: Optional[str] = None,
    reconciliation: Optional[Mapping[str, Any]] = None,
    cutover_id: Optional[str] = None,
    snapshot: Optional[Mapping[str, Any]] = None,
    snapshot_checksum: Optional[str] = None,
) -> None:
    ensure_postgres_cutover_schema(pg_conn)
    stamp = _now_iso()
    recon = json.dumps(dict(reconciliation)) if reconciliation is not None else None
    snap = json.dumps(dict(snapshot)) if snapshot is not None else None
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            UPDATE inventory_cutover_control
               SET status = %s,
                   epoch = COALESCE(%s, epoch),
                   seed_at = COALESCE(%s, seed_at),
                   activated_at = COALESCE(%s, activated_at),
                   device_id = COALESCE(%s, device_id),
                   reconciliation = COALESCE(%s::jsonb, reconciliation),
                   updated_at = %s,
                   cutover_id = COALESCE(%s, cutover_id),
                   snapshot = COALESCE(%s::jsonb, snapshot),
                   snapshot_checksum = COALESCE(%s, snapshot_checksum)
             WHERE id = 1
            """,
            (
                status,
                None if epoch is None else int(epoch),
                seed_at,
                activated_at,
                device_id,
                recon,
                stamp,
                cutover_id,
                snap,
                snapshot_checksum,
            ),
        )
    pg_conn.commit()


def get_or_create_act_command_id(
    conn,
    act_kind: str,
    act_key: str,
    *,
    command_id: Optional[str] = None,
) -> str:
    """Identidad estable de un acto comercial. Retry reutiliza el mismo UUID.

    No acepta un command_id arbitrario si el acto ya tiene identidad propia.
    """
    ensure_cutover_schema(conn)
    kind = str(act_kind or "").strip()
    key = str(act_key or "").strip()
    if not kind or not key:
        raise InventoryCutoverError("act_kind y act_key son obligatorios")
    row = conn.execute(
        """
        SELECT command_id FROM inventory_act_identities
         WHERE act_kind = ? AND act_key = ?
        """,
        (kind, key),
    ).fetchone()
    if row is not None:
        stored = row["command_id"] if hasattr(row, "keys") else row[0]
        if command_id and str(command_id).strip() and str(command_id) != str(stored):
            raise InventoryCutoverError(
                f"El acto {kind}/{key} ya tiene command_id {stored}; "
                "no se acepta un id nuevo para el mismo acto"
            )
        return str(stored)
    new_id = str(command_id or uuid.uuid4())
    try:
        uuid.UUID(new_id)
    except (ValueError, AttributeError, TypeError) as exc:
        raise InventoryCutoverError(f"command_id inválido: {new_id!r}") from exc
    conn.execute(
        """
        INSERT INTO inventory_act_identities (act_kind, act_key, command_id, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (kind, key, new_id, _now_iso()),
    )
    conn.commit()
    return new_id


ACT_KIND_POS_CHECKOUT = "pos_checkout"
ACT_KIND_LAN_SALE = "lan_sale"
ACT_KIND_PURCHASE_CREATE = "PURCHASE_CREATE"
ACT_KIND_PURCHASE_DELETE = "PURCHASE_DELETE"
ACT_KIND_SALE_CANCEL = "SALE_CANCEL"
ACT_KIND_RETURN = "RETURN"
ACT_KIND_PRODUCT_INITIAL_STOCK = "PRODUCT_INITIAL_STOCK"
ACT_KIND_PRODUCT_STOCK_EDIT = "PRODUCT_STOCK_EDIT"
ACT_KIND_PRODUCT_STOCK_SET = "PRODUCT_STOCK_SET"
ACT_KIND_MOVEMENT = "MOVEMENT"
ACT_KIND_MOVEMENT_REVERSAL = "MOVEMENT_REVERSAL"
ACT_KIND_INVENTORY_MOVEMENT = "INVENTORY_MOVEMENT"
ACT_KIND_INVENTORY_ADJUSTMENT = "INVENTORY_ADJUSTMENT"
ACT_KIND_INVENTORY_MOVEMENT_DELETE = "INVENTORY_MOVEMENT_DELETE"
ACT_KIND_INVOICE_LINE_ADD = "INVOICE_LINE_ADD"
ACT_KIND_INVOICE_LINE_EDIT = "INVOICE_LINE_EDIT"
ACT_KIND_INVOICE_LINE_DELETE = "INVOICE_LINE_DELETE"
ACT_KIND_MEZCLA_DEPRECATED = "MEZCLA_DEPRECATED"


def sale_items_fingerprint(items: Sequence[Mapping[str, Any]]) -> str:
    canon = tuple(
        sorted(
            (
                int(item.get("producto_id") or 0),
                str(item.get("cantidad")),
                str(item.get("descuento") or 0),
            )
            for item in items
        )
    )
    return hashlib.sha256(repr(canon).encode("utf-8")).hexdigest()


def purchase_create_fingerprint(
    proveedor_id: Any,
    numero_factura: Any,
    productos: Sequence[Mapping[str, Any]],
) -> str:
    canon = (
        int(proveedor_id or 0),
        str(numero_factura or ""),
        tuple(
            sorted(
                (
                    int(item.get("producto_id") or 0),
                    str(item.get("cantidad")),
                    str(item.get("precio_unitario")),
                )
                for item in productos
            )
        ),
    )
    return hashlib.sha256(repr(canon).encode("utf-8")).hexdigest()


def begin_or_resume_open_act(
    conn,
    act_kind: str,
    *,
    fingerprint: str = "",
) -> str:
    """Identidad durable de un acto en vuelo. Sobrevive restart de proceso.

    Un acto OPEN se reanuda hasta APPLIED/REJECTED. No vive solo en RAM.
    """
    ensure_cutover_schema(conn)
    kind = str(act_kind or "").strip()
    fp = str(fingerprint or "")
    if not kind:
        raise InventoryCutoverError("act_kind es obligatorio")
    row = conn.execute(
        """
        SELECT act_key, command_id FROM inventory_open_acts
         WHERE act_kind = ? AND fingerprint = ?
        """,
        (kind, fp),
    ).fetchone()
    if row is not None:
        stored = row["command_id"] if hasattr(row, "keys") else row[1]
        return str(stored)
    act_key = str(uuid.uuid4())
    command_id = get_or_create_act_command_id(conn, kind, act_key)
    conn.execute(
        """
        INSERT OR IGNORE INTO inventory_open_acts
            (act_kind, fingerprint, act_key, command_id, opened_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (kind, fp, act_key, command_id, _now_iso()),
    )
    conn.commit()
    row = conn.execute(
        """
        SELECT command_id FROM inventory_open_acts
         WHERE act_kind = ? AND fingerprint = ?
        """,
        (kind, fp),
    ).fetchone()
    stored = row["command_id"] if hasattr(row, "keys") else row[0]
    return str(stored)


def complete_open_act(conn, act_kind: str, *, fingerprint: str = "") -> None:
    """Cierra el acto en vuelo tras APPLIED o REJECTED (terminal)."""
    ensure_cutover_schema(conn)
    kind = str(act_kind or "").strip()
    fp = str(fingerprint or "")
    if not kind:
        return
    conn.execute(
        "DELETE FROM inventory_open_acts WHERE act_kind = ? AND fingerprint = ?",
        (kind, fp),
    )
    conn.commit()


def scaled_to_commercial(quantity_scaled: int) -> float:
    return int(quantity_scaled) / float(QUANTITY_SCALE)


def project_local_stock(
    sqlite_conn,
    producto_local_id: str,
    quantity_scaled: int,
) -> None:
    """Proyección/caché reconstruible. No es autoridad.

    UI/reportes legacy pueden leer productos.stock. Un fallo aquí no
    reinterpretan el APPLY remoto: la autoridad ya está en inventory_balances.
    """
    lid = str(producto_local_id or "").strip()
    if not lid:
        return
    commercial = scaled_to_commercial(int(quantity_scaled))
    sqlite_conn.execute(
        "UPDATE productos SET stock = ? WHERE local_id = ?",
        (commercial, lid),
    )


def project_operations_from_authority(
    sqlite_conn,
    operations: Sequence[Mapping[str, Any]],
    *,
    connection_factory=None,
    pg_conn=None,
) -> None:
    """Tras APPLIED: refresca caché local desde inventory_balances si hay PG."""
    from inventory_coordinator import fetch_inventory_balance

    owned = None
    conn = pg_conn
    if conn is None and connection_factory is not None:
        owned = connection_factory()
        conn = owned
    if conn is None:
        return
    try:
        seen = set()
        for raw in operations:
            lid = str((raw or {}).get("producto_local_id") or "").strip()
            if not lid or lid in seen:
                continue
            seen.add(lid)
            qty = fetch_inventory_balance(conn, lid)
            if qty is None:
                continue
            project_local_stock(sqlite_conn, lid, int(qty))
    finally:
        if owned is not None:
            try:
                owned.close()
            except Exception:
                pass


def assert_non_owner_app_role(pg_conn) -> str:
    """Impide usar owner/superuser como caller normal. No imprime DSN."""
    if schema_bootstrap.is_sqlite_connection(pg_conn):
        raise InventoryGatewayConfigError("El caller de app no puede ser SQLite")
    with pg_conn.cursor() as cur:
        cur.execute("SELECT session_user, current_user")
        session_user, current_user = cur.fetchone()
        cur.execute(
            "SELECT rolsuper FROM pg_roles WHERE rolname = session_user"
        )
        super_row = cur.fetchone()
        cur.execute(
            """
            SELECT pg_catalog.pg_get_userbyid(c.relowner)
              FROM pg_catalog.pg_class c
              JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public' AND c.relname = 'inventory_balances'
            """
        )
        owner_row = cur.fetchone()
        cur.execute(
            "SELECT pg_has_role(session_user, 'ferrepro_inventory_app', 'member')"
        )
        member_row = cur.fetchone()
    try:
        pg_conn.rollback()
    except Exception:
        pass
    session_name = str(session_user or "")
    if super_row and bool(super_row[0]):
        raise InventoryGatewayConfigError(
            "El caller normal no puede ser superuser; use ferrepro_inventory_app"
        )
    if owner_row and session_name == str(owner_row[0]):
        raise InventoryGatewayConfigError(
            "El owner de inventory_balances no es caller de aplicación"
        )
    if session_name == str(current_user or "") and not (member_row and member_row[0]):
        # session_user = current_user suele ser owner de SECURITY DEFINER.
        raise InventoryGatewayConfigError(
            "Caller de aplicación debe ser miembro de ferrepro_inventory_app"
        )
    if not (member_row and member_row[0]):
        raise InventoryGatewayConfigError(
            "Caller de aplicación debe ser miembro de ferrepro_inventory_app"
        )
    return session_name


def app_connection_factory_from_env(
    *, environ: Optional[Mapping[str, str]] = None
) -> Callable:
    """Factory productiva: FERREPRO_INVENTORY_DSN, autocommit=False, no-owner."""
    dsn = read_inventory_dsn(environ=environ)

    def factory():
        import psycopg2

        conn = psycopg2.connect(dsn)
        conn.autocommit = False
        assert_non_owner_app_role(conn)
        return conn

    return factory


def _uuid_ok(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        uuid.UUID(text)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def list_invalid_product_local_ids(sqlite_conn) -> Tuple[str, ...]:
    rows = sqlite_conn.execute(
        """
        SELECT id, local_id FROM productos
         WHERE COALESCE(activo, 1) = 1
           AND COALESCE(is_deleted, 0) = 0
        """
    ).fetchall()
    bad = []
    for row in rows:
        lid = row["local_id"] if hasattr(row, "keys") else row[1]
        pid = row["id"] if hasattr(row, "keys") else row[0]
        if not _uuid_ok(lid):
            bad.append(str(pid))
    return tuple(bad)


def verify_preconditions(
    sqlite_conn,
    *,
    app_factory=None,
    admin_conn=None,
    environ: Optional[Mapping[str, str]] = None,
    require_app_dsn: bool = True,
) -> Tuple[str, ...]:
    """Fail closed: cualquier falta impide cutover.

    No importa tests/ ni el scanner. El scanner es certificación estática.
    """
    from inventory_writer_contract import (
        CUTOVER_READY,
        EXPECTED_PREPARED_COUNT,
        PREPARED_DIRECT_WRITER_IDS,
        WRITER_CONTRACT_VERSION,
    )

    failures = []
    if not CUTOVER_READY or len(PREPARED_DIRECT_WRITER_IDS) != EXPECTED_PREPARED_COUNT:
        failures.append(
            f"contrato writers {WRITER_CONTRACT_VERSION} incompleto: "
            f"{len(PREPARED_DIRECT_WRITER_IDS)}/{EXPECTED_PREPARED_COUNT}"
        )

    invalid = list_invalid_product_local_ids(sqlite_conn)
    if invalid:
        failures.append(f"productos activos sin local_id válido: {len(invalid)}")

    pending = list_transmittable_command_ids(sqlite_conn)
    if pending:
        failures.append(
            f"comandos AUTHORITATIVE PERSISTED ambiguos: {len(pending)}"
        )

    from inventory_gateway import command_is_transmittable
    from inventory_ledger import INTENT_CLASS_LEGACY_OBSERVED, get_inventory_command

    observed = sqlite_conn.execute(
        "SELECT command_id FROM inventory_commands WHERE intent_class = ?",
        (INTENT_CLASS_LEGACY_OBSERVED,),
    ).fetchall()
    for row in observed:
        cid = row["command_id"] if hasattr(row, "keys") else row[0]
        rec = get_inventory_command(sqlite_conn, cid)
        if command_is_transmittable(rec):
            failures.append("LEGACY_OBSERVED resultó transmissible")
            break

    env = environ if environ is not None else None
    dsn_ok = True
    try:
        read_inventory_dsn(environ=env)
    except InventoryGatewayConfigError:
        dsn_ok = False
    if require_app_dsn and not dsn_ok:
        failures.append(f"{INVENTORY_DSN_ENV} no configurado")

    probe = None
    try:
        if app_factory is not None:
            probe = app_factory()
            assert_non_owner_app_role(probe)
        elif require_app_dsn:
            if not dsn_ok:
                pass
            else:
                probe = app_connection_factory_from_env(environ=env)()
                assert_non_owner_app_role(probe)
    except Exception as exc:
        failures.append(f"PostgreSQL app/no-owner: {exc}")
    finally:
        if probe is not None:
            try:
                probe.close()
            except Exception:
                pass

    if admin_conn is not None:
        try:
            with admin_conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            admin_conn.rollback()
        except Exception as exc:
            failures.append(f"PostgreSQL admin no accesible: {exc}")

    return tuple(failures)


def reconcile_seed(admin_conn) -> SeedReconciliation:
    """Compara stock legacy vs inventory_balances.quantity_scaled (fixed-point)."""
    report = SeedReconciliation()
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT local_id::text, COALESCE(stock::text, '0')
              FROM productos
             WHERE local_id IS NOT NULL AND btrim(local_id) <> ''
             ORDER BY local_id
            """
        )
        products = cur.fetchall()
        cur.execute(
            """
            SELECT producto_local_id, COUNT(*)
              FROM inventory_balances
             GROUP BY producto_local_id
            HAVING COUNT(*) > 1
            """
        )
        dups = [str(row[0]) for row in cur.fetchall()]
        cur.execute(
            "SELECT producto_local_id, quantity_scaled FROM inventory_balances"
        )
        balances = {str(row[0]): int(row[1]) for row in cur.fetchall()}
        cur.execute(
            """
            SELECT 1 FROM inventory_balance_init_state
             WHERE init_key = 'legacy_cutover'
            """
        )
        report.already_initialized = cur.fetchone() is not None
    try:
        admin_conn.rollback()
    except Exception:
        pass

    report.duplicates = tuple(dups)
    report.productos_legacy = len(products)
    missing = []
    mismatch = []
    invalid = []
    seeded = 0
    for lid, stock in products:
        text = str(lid or "").strip()
        if not _uuid_ok(text):
            invalid.append(text or "<empty>")
            continue
        expected = legacy_stock_to_scaled(stock)
        if text not in balances:
            missing.append(text)
            continue
        seeded += 1
        actual = int(balances[text])
        if actual != expected:
            mismatch.append(
                {
                    "producto_local_id": text,
                    "legacy_scaled": expected,
                    "balance_scaled": actual,
                }
            )
    report.seeded = seeded
    report.missing = tuple(missing)
    report.mismatch = tuple(mismatch)
    report.invalid_local_id = tuple(invalid)
    return report


def _sqlite_legacy_rows(sqlite_conn):
    return sqlite_conn.execute(
        """
        SELECT id, local_id, COALESCE(activo, 1) AS activo,
               COALESCE(is_deleted, 0) AS is_deleted,
               CAST(COALESCE(stock, 0) AS TEXT) AS stock
          FROM productos
        """
    ).fetchall()


def _postgres_legacy_rows(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'productos'
            """
        )
        cols = {str(row[0]) for row in cur.fetchall()}
        activo_expr = "COALESCE(activo, TRUE)" if "activo" in cols else "TRUE"
        deleted_expr = (
            "COALESCE(is_deleted, FALSE)" if "is_deleted" in cols else "FALSE"
        )
        cur.execute(
            f"""
            SELECT id, local_id::text, {activo_expr}, {deleted_expr},
                   COALESCE(stock::text, '0')
              FROM productos
            """
        )
        rows = cur.fetchall()
    try:
        admin_conn.rollback()
    except Exception:
        pass
    return rows


def _classify_product_rows(rows, *, sqlite: bool) -> dict:
    valid = {}
    invalid = []
    null_ids = []
    duplicates = []
    seen = {}
    extras_inactive_dup = []
    for row in rows:
        if sqlite and hasattr(row, "keys"):
            pid = row["id"]
            lid_raw = row["local_id"]
            activo = int(row["activo"] or 0)
            deleted = int(row["is_deleted"] or 0)
            stock = row["stock"]
            active = activo == 1 and deleted == 0
        else:
            pid = row[0]
            lid_raw = row[1]
            activo = row[2]
            deleted = row[3]
            stock = row[4]
            if sqlite:
                active = int(activo or 0) == 1 and int(deleted or 0) == 0
            else:
                active = bool(activo) and not bool(deleted)
        if not active:
            continue
        if lid_raw is None or str(lid_raw).strip() == "":
            null_ids.append(str(pid))
            continue
        text = str(lid_raw).strip()
        if not _uuid_ok(text):
            invalid.append(text)
            continue
        if text in seen:
            duplicates.append(text)
            continue
        seen[text] = pid
        valid[text] = legacy_stock_to_scaled(stock)
    return {
        "valid": valid,
        "invalid": tuple(invalid),
        "null": tuple(null_ids),
        "duplicates": tuple(duplicates),
        "extras_inactive_dup": tuple(extras_inactive_dup),
    }


def _sqlite_legacy_scaled(sqlite_conn) -> dict:
    return dict(_classify_product_rows(_sqlite_legacy_rows(sqlite_conn), sqlite=True)["valid"])


def _postgres_legacy_scaled(admin_conn) -> dict:
    return dict(_classify_product_rows(_postgres_legacy_rows(admin_conn), sqlite=False)["valid"])


def reconcile_legacy_sources(sqlite_conn, admin_conn) -> SeedReconciliation:
    """SET(local_ids SQLite) vs SET(local_ids PostgreSQL) en ambos sentidos."""
    local_info = _classify_product_rows(_sqlite_legacy_rows(sqlite_conn), sqlite=True)
    remote_info = _classify_product_rows(_postgres_legacy_rows(admin_conn), sqlite=False)
    local = local_info["valid"]
    remote = remote_info["valid"]
    report = SeedReconciliation()
    sqlite_ids = set(local)
    postgres_ids = set(remote)
    sqlite_only = tuple(sorted(sqlite_ids - postgres_ids))
    postgres_only = tuple(sorted(postgres_ids - sqlite_ids))
    mismatch = []
    seeded = 0
    for lid in sorted(sqlite_ids & postgres_ids):
        if int(remote[lid]) != int(local[lid]):
            mismatch.append(
                {
                    "producto_local_id": lid,
                    "sqlite_scaled": int(local[lid]),
                    "postgres_scaled": int(remote[lid]),
                }
            )
            continue
        seeded += 1
    report.productos_legacy = len(local)
    report.seeded = seeded
    report.missing = sqlite_only
    report.sqlite_only = sqlite_only
    report.postgres_only = postgres_only
    report.extra_unexpected = postgres_only
    report.mismatch = tuple(mismatch)
    report.duplicates = tuple(
        sorted(set(local_info["duplicates"]) | set(remote_info["duplicates"]))
    )
    report.invalid_local_id = tuple(
        sorted(set(local_info["invalid"]) | set(remote_info["invalid"]))
    )
    report.null_local_id = tuple(
        sorted(set(local_info["null"]) | set(remote_info["null"]))
    )
    return report


def snapshot_checksum(payload: Mapping[str, Any]) -> str:
    """Checksum canónico de snapshot 1E.4D.

    La fuente no participa: la identidad aprobada es cutover/epoch + conjunto
    completo de cantidades. El formato coincide byte a byte con la función
    PostgreSQL ``inventory_cutover_checksum``.
    """
    lines = payload.get("lines") or ()
    pairs = tuple(
        sorted(
            (
                str(item["producto_local_id"]),
                int(item["quantity_scaled"]),
            )
            for item in lines
        )
    )
    material = (
        f"{str(payload['cutover_id'])}\n{int(payload['epoch'])}\n"
        f"{len(pairs)}\n"
        + "".join(f"{lid}:{qty}\n" for lid, qty in pairs)
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def build_cutover_snapshot(
    lines: Sequence[Tuple[str, int]],
    *,
    epoch: int,
    captured_at: Optional[str] = None,
    cutover_id: Optional[str] = None,
    source: str = "legacy_reconciled",
) -> CutoverSnapshot:
    ordered = tuple(
        CutoverSnapshotLine(producto_local_id=str(lid), quantity_scaled=int(qty))
        for lid, qty in sorted((str(a), int(b)) for a, b in lines)
    )
    cid = str(cutover_id or uuid.uuid4())
    stamp = captured_at or _now_iso()
    identity = {
        "cutover_id": cid,
        "epoch": int(epoch),
        "source": source,
        "lines": [
            {"producto_local_id": line.producto_local_id, "quantity_scaled": line.quantity_scaled}
            for line in ordered
        ],
    }
    checksum = snapshot_checksum(identity)
    return CutoverSnapshot(
        cutover_id=cid,
        epoch=int(epoch),
        captured_at=stamp,
        lines=ordered,
        checksum=checksum,
        source=source,
    )


def persist_cutover_snapshot(sqlite_conn, snapshot: CutoverSnapshot, *, admin_conn=None) -> None:
    ensure_cutover_schema(sqlite_conn)
    payload = json.dumps(snapshot.as_dict())
    sqlite_conn.execute(
        """
        INSERT OR REPLACE INTO inventory_cutover_snapshot
            (cutover_id, epoch, captured_at, checksum, source, lines_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot.cutover_id,
            snapshot.epoch,
            snapshot.captured_at,
            snapshot.checksum,
            snapshot.source,
            json.dumps([line.__dict__ for line in snapshot.lines]),
        ),
    )
    _write_sqlite_state(
        sqlite_conn,
        status=load_cutover_state(sqlite_conn).status,
        cutover_id=snapshot.cutover_id,
        snapshot_json=payload,
        snapshot_checksum=snapshot.checksum,
    )
    if admin_conn is not None:
        remote = load_postgres_cutover_state(admin_conn, ensure_schema=False)
        touch_postgres_cutover_metadata(
            admin_conn,
            expected_status=remote.status,
            expected_epoch=int(remote.epoch),
            cutover_id=snapshot.cutover_id,
            snapshot=snapshot.as_dict(),
            snapshot_checksum=snapshot.checksum,
        )


def load_cutover_snapshot(sqlite_conn, cutover_id: Optional[str] = None) -> Optional[CutoverSnapshot]:
    ensure_cutover_schema(sqlite_conn)
    if cutover_id:
        row = sqlite_conn.execute(
            "SELECT cutover_id, epoch, captured_at, checksum, source, lines_json "
            "FROM inventory_cutover_snapshot WHERE cutover_id = ?",
            (cutover_id,),
        ).fetchone()
    else:
        row = sqlite_conn.execute(
            "SELECT cutover_id, epoch, captured_at, checksum, source, lines_json "
            "FROM inventory_cutover_snapshot ORDER BY captured_at DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return None
    getter = row.keys if hasattr(row, "keys") else None
    if getter is not None:
        cid, epoch, captured, checksum, source, lines_json = (
            row["cutover_id"], row["epoch"], row["captured_at"],
            row["checksum"], row["source"], row["lines_json"],
        )
    else:
        cid, epoch, captured, checksum, source, lines_json = row
    raw_lines = json.loads(lines_json)
    lines = tuple(
        CutoverSnapshotLine(
            producto_local_id=str(item["producto_local_id"]),
            quantity_scaled=int(item["quantity_scaled"]),
        )
        for item in raw_lines
    )
    snap = CutoverSnapshot(
        cutover_id=str(cid),
        epoch=int(epoch),
        captured_at=str(captured),
        lines=lines,
        checksum=str(checksum),
        source=str(source),
    )
    identity = {
        "cutover_id": snap.cutover_id,
        "epoch": snap.epoch,
        "source": snap.source,
        "lines": [
            {"producto_local_id": line.producto_local_id, "quantity_scaled": line.quantity_scaled}
            for line in snap.lines
        ],
    }
    if snapshot_checksum(identity) != snap.checksum:
        raise InventoryCutoverError("snapshot checksum inválido; snapshot mutable o corrupto")
    return snap


def capture_cutover_snapshot(sqlite_conn, admin_conn, *, epoch: int) -> CutoverSnapshot:
    recon = reconcile_legacy_sources(sqlite_conn, admin_conn)
    if not recon.ok:
        raise LegacyReconciliationRequiredError(
            "Fuentes legacy no convergen; no se elige LWW. NO CUTOVER. "
            + json.dumps(recon.as_dict())
        )
    local = _sqlite_legacy_scaled(sqlite_conn)
    remote = _postgres_legacy_scaled(admin_conn)
    lines = []
    for lid, qty in local.items():
        if lid in remote and int(remote[lid]) == int(qty):
            lines.append((lid, qty))
    return build_cutover_snapshot(tuple(lines), epoch=epoch)


def _station_attestation_lines(sqlite_conn, admin_conn) -> Tuple[Tuple[str, int], ...]:
    """Valida identidad de productos y devuelve cantidades de UNA estación.

    PostgreSQL ``productos.stock`` no decide cantidades. Solo se usa el
    conjunto de ``local_id`` remotos para impedir productos faltantes/extra.
    La convergencia de cantidades se decide entre todas las atestaciones.
    """
    local_info = _classify_product_rows(_sqlite_legacy_rows(sqlite_conn), sqlite=True)
    remote_info = _classify_product_rows(_postgres_legacy_rows(admin_conn), sqlite=False)
    local_ids = set(local_info["valid"])
    remote_ids = set(remote_info["valid"])
    problems = {
        "sqlite_only": sorted(local_ids - remote_ids),
        "postgres_only": sorted(remote_ids - local_ids),
        "invalid_local_id": sorted(
            set(local_info["invalid"]) | set(remote_info["invalid"])
        ),
        "null_local_id": sorted(
            set(local_info["null"]) | set(remote_info["null"])
        ),
        "duplicates": sorted(
            set(local_info["duplicates"]) | set(remote_info["duplicates"])
        ),
    }
    if any(problems.values()):
        raise LegacyReconciliationRequiredError(
            "FLEET_PRODUCT_SET_MISMATCH: " + json.dumps(problems, sort_keys=True)
        )
    return tuple(sorted((lid, int(qty)) for lid, qty in local_info["valid"].items()))


def register_inventory_cutover_fleet(
    admin_conn,
    *,
    cutover_id: str,
    epoch: int,
    expected_station_ids: Sequence[str],
) -> dict:
    expected = tuple(str(item).strip() for item in expected_station_ids)
    if not expected or any(not item for item in expected):
        raise InventoryCutoverError(
            "FLEET_ATTESTATION_REQUIRED: expected_station_ids explícito y no vacío"
        )
    if len(set(expected)) != len(expected):
        raise InventoryCutoverError("FLEET_ATTESTATION_INVALID: device_id duplicado")
    for item in expected:
        try:
            uuid.UUID(item)
        except (ValueError, TypeError, AttributeError) as exc:
            raise InventoryCutoverError(
                f"FLEET_ATTESTATION_INVALID: device_id no UUID: {item!r}"
            ) from exc
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "SELECT public.register_inventory_cutover_fleet(%s, %s, %s::jsonb)",
                (str(cutover_id), int(epoch), json.dumps(expected)),
            )
            row = cur.fetchone()
        admin_conn.commit()
    except Exception:
        admin_conn.rollback()
        raise
    data = row[0] if row else {}
    if isinstance(data, str):
        data = json.loads(data)
    return dict(data or {})


def submit_inventory_cutover_attestation(
    sqlite_conn,
    pg_conn,
    *,
    cutover_id: str,
    epoch: int,
    device_id: str,
    product_catalog_conn=None,
) -> CutoverSnapshot:
    lines = _station_attestation_lines(
        sqlite_conn, product_catalog_conn if product_catalog_conn is not None else pg_conn
    )
    snapshot = build_cutover_snapshot(
        lines,
        epoch=int(epoch),
        cutover_id=str(cutover_id),
        source="fleet_attestation",
    )
    payload = json.dumps(
        [
            {
                "producto_local_id": line.producto_local_id,
                "quantity_scaled": line.quantity_scaled,
            }
            for line in snapshot.lines
        ]
    )
    try:
        with pg_conn.cursor() as cur:
            cur.execute(
                "SELECT public.submit_inventory_cutover_attestation("
                "%s, %s, %s, %s, %s, %s::jsonb)",
                (
                    snapshot.cutover_id,
                    snapshot.epoch,
                    str(device_id),
                    snapshot.checksum,
                    len(snapshot.lines),
                    payload,
                ),
            )
            cur.fetchone()
        pg_conn.commit()
    except Exception:
        pg_conn.rollback()
        raise
    return snapshot


def load_approved_inventory_cutover_snapshot(
    admin_conn, *, cutover_id: str, epoch: int
) -> CutoverSnapshot:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT status, checksum, approved_at FROM "
            "public.inventory_cutover_snapshots "
            "WHERE cutover_id = %s AND epoch = %s",
            (str(cutover_id), int(epoch)),
        )
        head = cur.fetchone()
        if head is None or str(head[0]) not in ("APPROVED", "SEEDED"):
            admin_conn.rollback()
            raise InventoryCutoverError("INVENTORY_SNAPSHOT_NOT_APPROVED")
        cur.execute(
            "SELECT producto_local_id, quantity_scaled FROM "
            "public.inventory_cutover_snapshot_lines "
            "WHERE cutover_id = %s ORDER BY producto_local_id",
            (str(cutover_id),),
        )
        lines = tuple((str(row[0]), int(row[1])) for row in cur.fetchall())
    admin_conn.rollback()
    snapshot = build_cutover_snapshot(
        lines,
        epoch=int(epoch),
        cutover_id=str(cutover_id),
        captured_at=str(head[2] or _now_iso()),
        source="fleet_approved",
    )
    if snapshot.checksum != str(head[1]):
        raise InventoryCutoverError("INVENTORY_SNAPSHOT_INVALID: checksum aprobado")
    return snapshot


def approve_inventory_cutover_snapshot(
    admin_conn, *, cutover_id: str, epoch: int
) -> CutoverSnapshot:
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "SELECT public.approve_inventory_cutover_snapshot(%s, %s)",
                (str(cutover_id), int(epoch)),
            )
            cur.fetchone()
        admin_conn.commit()
    except Exception:
        admin_conn.rollback()
        raise
    return load_approved_inventory_cutover_snapshot(
        admin_conn, cutover_id=str(cutover_id), epoch=int(epoch)
    )


def list_in_flight_inventory(sqlite_conn, admin_conn=None) -> Tuple[str, ...]:
    inflight = list(list_transmittable_command_ids(sqlite_conn))
    if admin_conn is None:
        return tuple(inflight)
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT command_id FROM inventory_commands
             WHERE estado NOT IN ('APPLIED', 'REJECTED')
            """
        )
        remote = [str(row[0]) for row in cur.fetchall()]
        try:
            cur.execute(
                """
                SELECT COUNT(*) FROM pg_stat_activity
                 WHERE query ILIKE '%apply_inventory_command%'
                   AND state = 'active'
                   AND pid <> pg_backend_pid()
                """
            )
            active = int(cur.fetchone()[0])
        except Exception as exc:
            try:
                admin_conn.rollback()
            except Exception:
                pass
            raise InventoryCutoverError(
                "pg_stat_activity no consultable; NO SEED / NO ACTIVATE"
            ) from exc
    try:
        admin_conn.rollback()
    except Exception:
        pass
    if active:
        inflight.append("pg_stat_activity:apply_inventory_command")
    inflight.extend(remote)
    return tuple(inflight)


def initialize_inventory_balances_from_snapshot(admin_conn, snapshot: CutoverSnapshot) -> dict:
    """One-shot por referencia al snapshot aprobado en PostgreSQL.

    Las líneas del objeto Python se ignoran deliberadamente: después de la
    aprobación el servidor solo acepta ``cutover_id``/``epoch`` y siembra las
    líneas inmutables persistidas en PostgreSQL.
    """
    if schema_bootstrap.is_sqlite_connection(admin_conn):
        raise InventoryCutoverError("seed de snapshot solo PostgreSQL")
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT public.initialize_inventory_balances_from_snapshot(%s, %s)",
            (snapshot.cutover_id, int(snapshot.epoch)),
        )
        row = cur.fetchone()
    admin_conn.commit()
    data = row[0] if row else {}
    if isinstance(data, str):
        data = json.loads(data)
    return dict(data or {})


def reconcile_snapshot(admin_conn, snapshot: CutoverSnapshot) -> SeedReconciliation:
    report = SeedReconciliation()
    expected = {
        line.producto_local_id: line.quantity_scaled for line in snapshot.lines
    }
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT producto_local_id, COUNT(*) FROM inventory_balances "
            "GROUP BY producto_local_id HAVING COUNT(*) > 1"
        )
        dups = [str(row[0]) for row in cur.fetchall()]
        cur.execute("SELECT producto_local_id, quantity_scaled FROM inventory_balances")
        balances = {str(row[0]): int(row[1]) for row in cur.fetchall()}
        cur.execute(
            "SELECT 1 FROM inventory_balance_init_state WHERE init_key = 'legacy_cutover'"
        )
        report.already_initialized = cur.fetchone() is not None
    try:
        admin_conn.rollback()
    except Exception:
        pass
    report.duplicates = tuple(dups)
    report.productos_legacy = len(expected)
    missing = []
    mismatch = []
    extras = []
    seeded = 0
    for lid, qty in sorted(expected.items()):
        if lid not in balances:
            missing.append(lid)
            continue
        seeded += 1
        if int(balances[lid]) != int(qty):
            mismatch.append(
                {
                    "producto_local_id": lid,
                    "snapshot_scaled": int(qty),
                    "balance_scaled": int(balances[lid]),
                }
            )
    for lid in balances:
        if lid not in expected:
            extras.append(lid)
    report.seeded = seeded
    report.missing = tuple(missing)
    report.mismatch = tuple(mismatch)
    if extras:
        report.duplicates = tuple(list(report.duplicates) + extras)
    return report


def freeze_inventory_writes(
    sqlite_conn, *, admin_conn=None, device_id: Optional[str] = None
) -> CutoverState:
    current = load_cutover_state(sqlite_conn)
    if admin_conn is not None:
        remote = load_postgres_cutover_state(admin_conn, ensure_schema=True)
        if remote.is_authoritative:
            raise InventoryCutoverError("No se congela un cutover ya AUTHORITATIVE")
        cas_postgres_cutover_state(
            admin_conn,
            expected_status=remote.status,
            expected_epoch=int(remote.epoch),
            new_status=STATUS_CUTOVER_IN_PROGRESS,
            new_epoch=int(remote.epoch) + 1,
            device_id=device_id,
        )
        published = _after_postgres_freeze_hook
        if callable(published):
            published()
        remote = load_postgres_cutover_state(admin_conn, ensure_schema=False)
        return _write_sqlite_state(
            sqlite_conn,
            status=remote.status,
            epoch=remote.epoch,
            device_id=device_id,
        )
    if current.is_authoritative:
        raise InventoryCutoverError("No se congela un cutover ya AUTHORITATIVE")
    return _write_sqlite_state(
        sqlite_conn,
        status=STATUS_CUTOVER_IN_PROGRESS,
        epoch=int(current.epoch) + 1,
        device_id=device_id,
    )


def abort_pre_activation(
    sqlite_conn, *, admin_conn=None, reason: str = "aborted"
) -> CutoverState:
    """PRE-ACTIVATION rollback: vuelve a legacy si no hubo APPLY autoritativo."""
    if admin_conn is not None:
        remote = load_postgres_cutover_state(admin_conn, ensure_schema=True)
        if remote.is_authoritative:
            raise UnsafeRollbackError(
                "Estado AUTHORITATIVE global: recovery hacia adelante, no flag False"
            )
        with admin_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM inventory_commands WHERE estado = 'APPLIED'"
            )
            applied_remote = int(cur.fetchone()[0])
        try:
            admin_conn.rollback()
        except Exception:
            pass
        if applied_remote:
            raise UnsafeRollbackError(
                "POST-ACTIVATION: ya hubo APPLY autoritativo en PostgreSQL; "
                "no se vuelve a productos.stock legacy"
            )
    pending = list_transmittable_command_ids(sqlite_conn)
    applied = sqlite_conn.execute(
        """
        SELECT COUNT(*) FROM inventory_commands
         WHERE intent_class = ? AND estado = 'APPLIED'
        """,
        (INTENT_CLASS_AUTHORITATIVE,),
    ).fetchone()[0]
    if applied:
        raise UnsafeRollbackError(
            "POST-ACTIVATION: ya hubo APPLY autoritativo; "
            "no se vuelve a productos.stock legacy"
        )
    if pending:
        raise UnsafeRollbackError(
            "Hay commands AUTHORITATIVE PERSISTED; rollback inseguro"
        )
    current = load_cutover_state(sqlite_conn)
    if current.is_authoritative:
        raise UnsafeRollbackError(
            "Estado AUTHORITATIVE: recovery hacia adelante, no flag False"
        )
    payload = {"reason": reason, "window": "PRE_ACTIVATION"}
    if admin_conn is not None:
        remote = load_postgres_cutover_state(admin_conn, ensure_schema=False)
        if remote.status != STATUS_ROLLBACK_SAFE:
            cas_postgres_cutover_state(
                admin_conn,
                expected_status=remote.status,
                expected_epoch=int(remote.epoch),
                new_status=STATUS_ROLLBACK_SAFE,
                new_epoch=int(remote.epoch) + 1,
                reconciliation=payload,
            )
            remote = load_postgres_cutover_state(admin_conn, ensure_schema=False)
        return _write_sqlite_state(
            sqlite_conn,
            status=remote.status,
            epoch=remote.epoch,
            reconciliation_json=json.dumps(payload),
        )
    current = load_cutover_state(sqlite_conn)
    return _write_sqlite_state(
        sqlite_conn,
        status=STATUS_ROLLBACK_SAFE,
        epoch=int(current.epoch) + 1,
        reconciliation_json=json.dumps(payload),
    )


def activate_authority(
    sqlite_conn,
    *,
    admin_conn=None,
    device_id: Optional[str] = None,
    reconciliation: Optional[SeedReconciliation] = None,
) -> CutoverState:
    current = load_cutover_state(sqlite_conn)
    if current.status != STATUS_CUTOVER_IN_PROGRESS:
        raise InventoryCutoverError(
            f"activate exige CUTOVER_IN_PROGRESS, no {current.status}"
        )
    if reconciliation is not None and not reconciliation.ok:
        raise InventoryCutoverError("reconciliación no exacta; no se activa")
    payload = json.dumps(reconciliation.as_dict()) if reconciliation else None
    stamp = _now_iso()
    if admin_conn is not None:
        remote = load_postgres_cutover_state(admin_conn, ensure_schema=True)
        if remote.status != STATUS_CUTOVER_IN_PROGRESS:
            raise StaleCutoverStateError(
                f"STALE_CUTOVER_STATE: activate exige CUTOVER_IN_PROGRESS, "
                f"got {remote.status}/{remote.epoch}"
            )
        cas_postgres_cutover_state(
            admin_conn,
            expected_status=STATUS_CUTOVER_IN_PROGRESS,
            expected_epoch=int(remote.epoch),
            new_status=STATUS_AUTHORITATIVE,
            new_epoch=int(remote.epoch) + 1,
            activated_at=stamp,
            device_id=device_id,
            reconciliation=reconciliation.as_dict() if reconciliation else None,
        )
        remote = load_postgres_cutover_state(admin_conn, ensure_schema=False)
        return _write_sqlite_state(
            sqlite_conn,
            status=remote.status,
            epoch=remote.epoch,
            activated_at=stamp,
            device_id=device_id,
            reconciliation_json=payload,
        )
    if current.status != STATUS_CUTOVER_IN_PROGRESS:
        raise InventoryCutoverError(
            f"activate exige CUTOVER_IN_PROGRESS, no {current.status}"
        )
    epoch = int(current.epoch) + 1
    return _write_sqlite_state(
        sqlite_conn,
        status=STATUS_AUTHORITATIVE,
        epoch=epoch,
        activated_at=stamp,
        device_id=device_id,
        reconciliation_json=payload,
    )


def run_cutover(
    sqlite_conn,
    *,
    admin_conn,
    app_factory,
    device_id: Optional[str] = None,
    expected_station_ids: Optional[Sequence[str]] = None,
    station_sqlite_connections: Optional[Mapping[str, Any]] = None,
    environ: Optional[Mapping[str, str]] = None,
    require_app_dsn: bool = True,
) -> CutoverResult:
    """precondiciones → freeze → atestación completa → snapshot aprobado →
    seed por referencia → comparar → activate.

    Seed usa owner/admin de laboratorio. Operación normal posterior: app_factory
    no-owner. No activa si una etapa falla. No toca Supabase real.
    ``expected_station_ids`` es obligatorio: no se infiere consenso porque
    haya respondido una sola estación. PostgreSQL ``productos.stock`` solo
    valida el conjunto de productos; las cantidades salen del consenso de
    estaciones esperado.
    """
    ensure_cutover_schema(sqlite_conn)
    ensure_postgres_cutover_schema(admin_conn)
    remote = load_postgres_cutover_state(admin_conn, ensure_schema=False)
    if remote.is_authoritative:
        _cache_sqlite_from_remote(sqlite_conn, remote)
        recon = SeedReconciliation()
        if remote.reconciliation_json:
            try:
                data = json.loads(remote.reconciliation_json)
                recon.productos_legacy = int(data.get("productos_legacy") or 0)
                recon.seeded = int(data.get("seeded") or 0)
            except Exception:
                pass
        return CutoverResult(
            state=observe_cutover_state(sqlite_conn, pg_conn=admin_conn),
            reconciliation=recon,
        )

    failures = verify_preconditions(
        sqlite_conn,
        app_factory=app_factory,
        admin_conn=admin_conn,
        environ=environ,
        require_app_dsn=require_app_dsn,
    )
    if failures:
        return CutoverResult(
            state=load_cutover_state(sqlite_conn),
            preconditions=failures,
            aborted=True,
            error="preconditions",
        )

    configured_expected = expected_station_ids
    if configured_expected is None:
        env_source = environ if environ is not None else os.environ
        raw_expected = str(env_source.get(CUTOVER_EXPECTED_STATIONS_ENV, "") or "")
        configured_expected = tuple(
            item.strip() for item in raw_expected.split(",") if item.strip()
        )
    expected = tuple(str(item).strip() for item in (configured_expected or ()))
    if not expected:
        return CutoverResult(
            state=load_cutover_state(sqlite_conn),
            aborted=True,
            error="FLEET_ATTESTATION_REQUIRED: expected_station_ids obligatorio",
        )
    if device_id is None and len(expected) == 1:
        device_id = expected[0]
    if not device_id or str(device_id).strip() not in set(expected):
        return CutoverResult(
            state=load_cutover_state(sqlite_conn),
            aborted=True,
            error="FLEET_ATTESTATION_REQUIRED: device_id coordinador debe ser esperado",
        )

    freeze_inventory_writes(sqlite_conn, admin_conn=admin_conn, device_id=device_id)
    snapshot = None
    legacy_recon = None
    try:
        inflight = list_in_flight_inventory(sqlite_conn, admin_conn)
        if inflight:
            raise InventoryCutoverError(
                f"operaciones de inventario en vuelo: {len(inflight)}"
            )
        current = load_postgres_cutover_state(admin_conn, ensure_schema=False)
        cutover_id = str(uuid.uuid4())
        register_inventory_cutover_fleet(
            admin_conn,
            cutover_id=cutover_id,
            epoch=int(current.epoch),
            expected_station_ids=expected,
        )
        stations = dict(station_sqlite_connections or {})
        stations[str(device_id).strip()] = sqlite_conn
        unexpected = sorted(set(stations) - set(expected))
        if unexpected:
            raise InventoryCutoverError(
                "FLEET_ATTESTATION_UNEXPECTED_STATION: " + ", ".join(unexpected)
            )
        for station_id in expected:
            station_conn = stations.get(station_id)
            if station_conn is None:
                continue
            submit_inventory_cutover_attestation(
                station_conn,
                admin_conn,
                cutover_id=cutover_id,
                epoch=int(current.epoch),
                device_id=station_id,
                product_catalog_conn=admin_conn,
            )
        snapshot = approve_inventory_cutover_snapshot(
            admin_conn, cutover_id=cutover_id, epoch=int(current.epoch)
        )
        legacy_recon = SeedReconciliation(
            productos_legacy=len(snapshot.lines),
            seeded=len(snapshot.lines),
        )
        persist_cutover_snapshot(sqlite_conn, snapshot, admin_conn=admin_conn)
        seed_info = initialize_inventory_balances_from_snapshot(admin_conn, snapshot)
        stamp = _now_iso()
        current = load_postgres_cutover_state(admin_conn, ensure_schema=False)
        touch_postgres_cutover_metadata(
            admin_conn,
            expected_status=STATUS_CUTOVER_IN_PROGRESS,
            expected_epoch=int(current.epoch),
            seed_at=stamp,
            reconciliation={"seed": seed_info, "checksum": snapshot.checksum},
            cutover_id=snapshot.cutover_id,
            snapshot=snapshot.as_dict(),
            snapshot_checksum=snapshot.checksum,
        )
        _write_sqlite_state(
            sqlite_conn,
            status=STATUS_CUTOVER_IN_PROGRESS,
            seed_at=stamp,
            cutover_id=snapshot.cutover_id,
            snapshot_json=json.dumps(snapshot.as_dict()),
            snapshot_checksum=snapshot.checksum,
        )
        frozen = load_cutover_snapshot(sqlite_conn, snapshot.cutover_id)
        if frozen is None or frozen.checksum != snapshot.checksum:
            raise InventoryCutoverError("snapshot no quedó congelado")
        if frozen.quantity_identity() != snapshot.quantity_identity():
            raise InventoryCutoverError("snapshot mutable tras persistir")
        recon = reconcile_snapshot(admin_conn, snapshot)
        if not recon.ok:
            abort_pre_activation(sqlite_conn, admin_conn=admin_conn, reason="mismatch")
            return CutoverResult(
                state=load_cutover_state(sqlite_conn),
                reconciliation=recon,
                legacy_reconciliation=legacy_recon,
                snapshot=snapshot,
                aborted=True,
                error="reconciliation",
            )
        state = activate_authority(
            sqlite_conn,
            admin_conn=admin_conn,
            device_id=device_id,
            reconciliation=recon,
        )
        return CutoverResult(
            state=state,
            reconciliation=recon,
            legacy_reconciliation=legacy_recon,
            snapshot=snapshot,
        )
    except LegacyReconciliationRequiredError as exc:
        try:
            abort_pre_activation(
                sqlite_conn, admin_conn=admin_conn, reason="legacy_reconciliation"
            )
        except UnsafeRollbackError:
            pass
        return CutoverResult(
            state=load_cutover_state(sqlite_conn),
            legacy_reconciliation=legacy_recon,
            snapshot=snapshot,
            aborted=True,
            error="legacy_reconciliation",
        )
    except Exception as exc:
        try:
            abort_pre_activation(sqlite_conn, admin_conn=admin_conn, reason=str(exc))
        except UnsafeRollbackError:
            # Recovery hacia adelante: no degradar AUTHORITATIVE ni un APPLY
            # ya ocurrido a FAILED. FAILED haría que otras cajas asuman
            # LEGACY y escriban productos.stock con balances ya autoritativos.
            try:
                remote = load_postgres_cutover_state(
                    admin_conn, ensure_schema=False
                )
                if remote.is_authoritative:
                    try:
                        _cache_sqlite_from_remote(sqlite_conn, remote)
                    except Exception:
                        pass
                    return CutoverResult(
                        state=remote,
                        reconciliation=SeedReconciliation(),
                        legacy_reconciliation=legacy_recon,
                        snapshot=snapshot,
                        aborted=False,
                    )
            except Exception:
                pass
        return CutoverResult(
            state=load_cutover_state(sqlite_conn),
            legacy_reconciliation=legacy_recon,
            snapshot=snapshot,
            aborted=True,
            error=str(exc),
        )


assert QUANTITY_SCALE == 1000
