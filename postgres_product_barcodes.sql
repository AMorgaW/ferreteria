-- FERREPRO Fase 2C — SOLO PostgreSQL de laboratorio.
-- No modifica stock, no genera FRP y no hace backfill de productos legacy.

ALTER TABLE productos
    ADD COLUMN IF NOT EXISTS barcode_status TEXT NOT NULL
    DEFAULT 'BARCODE_MISSING_LEGACY';

CREATE TABLE IF NOT EXISTS product_barcodes (
    local_id TEXT PRIMARY KEY,
    producto_local_id TEXT NOT NULL,
    barcode TEXT NOT NULL,
    barcode_type TEXT NOT NULL DEFAULT 'MANUFACTURER',
    source TEXT NOT NULL DEFAULT 'HID_DOUBLE_SCAN',
    is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0, 1)),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    remote_id TEXT,
    deleted_at TIMESTAMPTZ,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    sync_status TEXT NOT NULL DEFAULT 'pending',
    last_synced_at TIMESTAMPTZ,
    version INTEGER NOT NULL DEFAULT 1,
    device_id TEXT,
    created_by INTEGER,
    updated_by INTEGER,
    CONSTRAINT fk_product_barcodes_product_local_id
        FOREIGN KEY (producto_local_id) REFERENCES productos(local_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT uq_product_barcodes_barcode UNIQUE (barcode),
    CONSTRAINT ck_product_barcodes_nonempty CHECK (length(barcode) > 0)
);

CREATE INDEX IF NOT EXISTS idx_product_barcodes_product
    ON product_barcodes(producto_local_id, active);

CREATE UNIQUE INDEX IF NOT EXISTS uq_product_barcodes_primary_active
    ON product_barcodes(producto_local_id)
    WHERE active = 1 AND is_primary = 1;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ferrepro_barcode_app') THEN
        CREATE ROLE ferrepro_barcode_app NOLOGIN NOSUPERUSER NOBYPASSRLS
            NOCREATEDB NOCREATEROLE INHERIT;
    END IF;
END $$;

REVOKE ALL ON TABLE product_barcodes FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO ferrepro_barcode_app;
GRANT SELECT, INSERT, UPDATE ON TABLE product_barcodes TO ferrepro_barcode_app;
