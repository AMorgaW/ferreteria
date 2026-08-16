# -*- coding: utf-8 -*-
"""Esquema mínimo 4B: identidad durable de abonos. No contabilidad."""
from __future__ import annotations

import schema_bootstrap

SQLITE_MIGRATION_VERSION = "20260816_010"
LEGACY_PAYMENT_TABLE = "operational_balance_legacy_payments"


def _capture_legacy_payment_baselines(conn) -> None:
    """Congela pagos pre-4B demostrados por la proyección legacy.

    Solo captura documentos sin ninguna fila de abono. Así un documento que ya
    tiene historial durable nunca suma también ``monto_pagado``. Los abonos
    creados después del cutover se suman al baseline congelado.
    """
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {LEGACY_PAYMENT_TABLE} (
            document_tipo TEXT NOT NULL
                CHECK (document_tipo IN ('venta', 'compra')),
            document_id INTEGER NOT NULL,
            amount TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'CUTOVER_MONTO_PAGADO',
            captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (document_tipo, document_id)
        )
        """
    )

    specs = (
        ("venta", "ventas", "abonos_ventas", "id_venta"),
        ("compra", "compras", "abonos_compras", "id_compra"),
    )
    for document_tipo, documents, payments, payment_fk in specs:
        if not schema_bootstrap.table_exists(conn, documents):
            continue
        if not schema_bootstrap.column_exists(conn, documents, "monto_pagado"):
            continue
        if schema_bootstrap.table_exists(conn, payments):
            no_payment_row = (
                f"NOT EXISTS (SELECT 1 FROM {payments} p "
                f"WHERE p.{payment_fk} = d.id)"
            )
        else:
            no_payment_row = "1 = 1"
        conn.execute(
            f"""
            INSERT OR IGNORE INTO {LEGACY_PAYMENT_TABLE}
                (document_tipo, document_id, amount, source)
            SELECT ?, d.id, CAST(d.monto_pagado AS TEXT), 'CUTOVER_MONTO_PAGADO'
              FROM {documents} d
             WHERE CAST(COALESCE(d.monto_pagado, 0) AS NUMERIC) > 0
               AND {no_payment_row}
            """,
            (document_tipo,),
        )


def ensure_sqlite_operational_balance_schema(conn) -> None:
    """Identidad de abonos y baseline legacy durable, idempotentes."""
    if not schema_bootstrap.is_sqlite_connection(conn):
        raise schema_bootstrap.SchemaBootstrapError(
            "El esquema SQLite de saldos 4B no admite PostgreSQL"
        )
    for table in ("abonos_ventas", "abonos_compras"):
        if not schema_bootstrap.table_exists(conn, table):
            continue
        schema_bootstrap.add_column_if_missing(conn, table, "local_id", "TEXT")
        schema_bootstrap.create_index_if_missing(
            conn,
            f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_local_id ON {table}(local_id)",
        )
        schema_bootstrap.create_index_if_missing(
            conn,
            f"CREATE INDEX IF NOT EXISTS idx_{table}_documento ON {table}"
            f"({'id_venta' if table == 'abonos_ventas' else 'id_compra'})",
        )
    _capture_legacy_payment_baselines(conn)
