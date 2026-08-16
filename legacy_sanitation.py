# -*- coding: utf-8 -*-
"""Análisis no destructivo de schema y datos legacy (Fase 2A)."""
from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

import schema_bootstrap
from sync_registry import NON_SYNC_TABLES, SYNC_REGISTRY


FOCUS_TABLES = (
    "productos",
    "compras",
    "detalle_compras",
    "ventas",
    "detalle_ventas",
    "movimientos",
    "movimientos_inventario",
    "devoluciones",
    "proveedores",
    "usuarios",
    "configuracion",
    "inventory_commands",
    "inventory_operations",
)

NUMERIC_HINTS = (
    "stock",
    "cantidad",
    "precio",
    "total",
    "subtotal",
    "saldo",
    "monto",
    "descuento",
    "iva",
)

POSTGRES_TYPE_POLICY = {
    "inventory_balances.quantity_scaled": "BIGINT (fixed-point 1000)",
    "inventory_operations.delta_scaled": "BIGINT (fixed-point 1000)",
    "productos.stock": "NUMERIC legacy projection only",
    "default_quantity": "NUMERIC/BIGINT fixed-point in future structures",
    "default_money": "NUMERIC(p,s) in future structures",
}


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    table: str
    column: Optional[str]
    affected: int
    message: str
    action: str


@dataclass(frozen=True)
class SchemaCell:
    table: str
    column: str
    sqlite_type: str
    postgres_type: str
    nullable: bool
    default: Optional[str]
    pk: bool
    fk: Optional[str]
    unique: bool
    sync_status: str
    risk: str
    migration: str


@dataclass(frozen=True)
class SanitationReport:
    schema: Tuple[SchemaCell, ...]
    findings: Tuple[Finding, ...]
    table_counts: Mapping[str, int]

    def as_dict(self) -> dict:
        return {
            "schema": [asdict(item) for item in self.schema],
            "findings": [asdict(item) for item in self.findings],
            "table_counts": dict(self.table_counts),
        }


def normalize_supplier_document(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().upper()
    return re.sub(r"[^A-Z0-9]", "", text)


def _uuid_valid(value: Any) -> bool:
    try:
        uuid.UUID(str(value).strip())
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def _ident(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(value)):
        raise ValueError(f"identificador SQLite inválido: {value!r}")
    return str(value)


def _table_info(conn, table: str):
    table = _ident(table)
    return conn.execute(f"PRAGMA table_info({table})").fetchall()


def _unique_columns(conn, table: str) -> set:
    table = _ident(table)
    result = set()
    for idx in conn.execute(f"PRAGMA index_list({table})").fetchall():
        unique = idx["unique"] if hasattr(idx, "keys") else idx[2]
        name = idx["name"] if hasattr(idx, "keys") else idx[1]
        if not unique:
            continue
        cols = conn.execute(f"PRAGMA index_info('{name}')").fetchall()
        if len(cols) == 1:
            result.add(cols[0]["name"] if hasattr(cols[0], "keys") else cols[0][2])
    return result


def _fk_map(conn, table: str) -> dict:
    table = _ident(table)
    result = {}
    for row in conn.execute(f"PRAGMA foreign_key_list({table})").fetchall():
        source = row["from"] if hasattr(row, "keys") else row[3]
        target_table = row["table"] if hasattr(row, "keys") else row[2]
        target_col = row["to"] if hasattr(row, "keys") else row[4]
        result[source] = f"{target_table}.{target_col}"
    return result


def _postgres_type(table: str, column: str, sqlite_type: str) -> str:
    key = f"{table}.{column}"
    if key in POSTGRES_TYPE_POLICY:
        return POSTGRES_TYPE_POLICY[key]
    lower = column.lower()
    if any(hint in lower for hint in NUMERIC_HINTS):
        if any(token in lower for token in ("precio", "total", "saldo", "monto", "iva", "descuento")):
            return POSTGRES_TYPE_POLICY["default_money"]
        return POSTGRES_TYPE_POLICY["default_quantity"]
    mapping = {
        "INTEGER": "INTEGER/BIGINT según PK/FK",
        "REAL": "DOUBLE PRECISION legacy",
        "TEXT": "TEXT",
        "DATE": "DATE",
        "TIMESTAMP": "TIMESTAMPTZ recomendado",
        "VARCHAR": "TEXT/VARCHAR",
    }
    return mapping.get((sqlite_type or "").upper(), sqlite_type or "UNDECLARED")


def _numeric_classification(table: str, column: str) -> Tuple[str, str]:
    key = f"{table}.{column}"
    if key in ("inventory_balances.quantity_scaled", "inventory_operations.delta_scaled"):
        return "LOW", "MUST_MIGRATE: ya fixed-point; impedir regresión"
    if key == "productos.stock":
        return "MEDIUM", "PROJECTION_ONLY: no convertir como autoridad"
    if any(token in column.lower() for token in ("precio", "total", "saldo", "monto")):
        return "MEDIUM", "CAN_REMAIN_LEGACY: migrar dinero en microfase posterior"
    return "MEDIUM", "CAN_REMAIN_LEGACY: nueva estructura no debe usar float"


def analyze_sqlite(conn, *, tables: Sequence[str] = FOCUS_TABLES) -> SanitationReport:
    schema = []
    findings = []
    counts: Dict[str, int] = {}
    for table in tables:
        table = _ident(table)
        if not schema_bootstrap.table_exists(conn, table):
            findings.append(
                Finding(
                    "SCHEMA_TABLE_MISSING",
                    "HIGH" if table in SYNC_REGISTRY else "MEDIUM",
                    table,
                    None,
                    0,
                    "Tabla esperada ausente",
                    "Revisar bootstrap/migración antes de sincronizar",
                )
            )
            continue
        count = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        counts[table] = count
        info = _table_info(conn, table)
        unique = _unique_columns(conn, table)
        fks = _fk_map(conn, table)
        sync = "SYNC" if table in SYNC_REGISTRY else (
            "NON_SYNC" if table in NON_SYNC_TABLES else "INTERNAL"
        )
        for row in info:
            name = row["name"] if hasattr(row, "keys") else row[1]
            declared = row["type"] if hasattr(row, "keys") else row[2]
            notnull = row["notnull"] if hasattr(row, "keys") else row[3]
            default = row["dflt_value"] if hasattr(row, "keys") else row[4]
            pk = row["pk"] if hasattr(row, "keys") else row[5]
            risk, migration = ("LOW", "CAN_REMAIN_LEGACY")
            if any(hint in name.lower() for hint in NUMERIC_HINTS):
                risk, migration = _numeric_classification(table, name)
            schema.append(
                SchemaCell(
                    table,
                    name,
                    str(declared or ""),
                    _postgres_type(table, name, str(declared or "")),
                    not bool(notnull or pk),
                    None if default is None else str(default),
                    bool(pk),
                    fks.get(name),
                    bool(pk) or name in unique,
                    sync,
                    risk,
                    migration,
                )
            )

        columns = {item.column for item in schema if item.table == table}
        if table in SYNC_REGISTRY and "local_id" in columns:
            rows = conn.execute(
                f"SELECT local_id, COUNT(*) n FROM {table} GROUP BY local_id"
            ).fetchall()
            nulls = sum(
                int(row[1]) for row in rows
                if row[0] is None or not str(row[0]).strip()
            )
            invalid = sum(
                int(row[1]) for row in rows
                if row[0] is not None and str(row[0]).strip() and not _uuid_valid(row[0])
            )
            duplicates = sum(
                int(row[1]) - 1 for row in rows
                if row[0] is not None and str(row[0]).strip() and int(row[1]) > 1
            )
            for code, affected, message, action in (
                ("LOCAL_ID_MISSING", nulls, "local_id NULL/vacío", "Backfill idempotente solo tras verificar remote_id"),
                ("LOCAL_ID_INVALID", invalid, "local_id no UUID", "No reemplazar sin mapa de identidad remoto"),
                ("LOCAL_ID_DUPLICATE", duplicates, "local_id duplicado", "Requiere decisión humana/merge"),
            ):
                if affected:
                    findings.append(Finding(code, "HIGH", table, "local_id", affected, message, action))

        if table in SYNC_REGISTRY and "remote_id" in columns:
            duplicate_remote_ids = int(
                conn.execute(
                    f"SELECT COALESCE(SUM(n - 1), 0) FROM ("
                    f"SELECT remote_id, COUNT(*) n FROM {table} "
                    "WHERE remote_id IS NOT NULL AND TRIM(CAST(remote_id AS TEXT)) <> '' "
                    "GROUP BY remote_id HAVING COUNT(*) > 1)"
                ).fetchone()[0]
            )
            if duplicate_remote_ids:
                findings.append(
                    Finding(
                        "REMOTE_ID_DUPLICATE",
                        "HIGH",
                        table,
                        "remote_id",
                        duplicate_remote_ids,
                        "remote_id repetido dentro de la misma entidad",
                        "Resolver el mapa remoto; no regenerar local_id válido",
                    )
                )

        for row in info:
            name = row["name"] if hasattr(row, "keys") else row[1]
            if not any(hint in name.lower() for hint in NUMERIC_HINTS):
                continue
            storage = conn.execute(
                f"SELECT typeof({name}), COUNT(*) FROM {table} GROUP BY typeof({name})"
            ).fetchall()
            bad = sum(int(item[1]) for item in storage if item[0] not in ("integer", "real", "null"))
            if bad:
                findings.append(
                    Finding(
                        "NUMERIC_STORAGE_ANOMALY",
                        "HIGH",
                        table,
                        name,
                        bad,
                        "Valor numérico almacenado como BLOB/TEXT",
                        "Reportar y convertir solo con regla explícita",
                    )
                )

    if schema_bootstrap.table_exists(conn, "compras"):
        groups = {}
        rows = conn.execute(
            "SELECT id, proveedor_id, numero_factura FROM compras"
        ).fetchall()
        missing_invoice_numbers = 0
        for row in rows:
            key = (row[1], normalize_supplier_document(row[2]))
            if not key[1]:
                missing_invoice_numbers += 1
                continue
            groups.setdefault(key, []).append(int(row[0]))
        if missing_invoice_numbers:
            findings.append(
                Finding(
                    "SUPPLIER_INVOICE_IDENTITY_MISSING",
                    "MEDIUM",
                    "compras",
                    "numero_factura",
                    missing_invoice_numbers,
                    "Compra sin número de factura normalizable",
                    "Clasificar documento antes de exigir identidad única",
                )
            )
        duplicate_rows = sum(len(ids) for ids in groups.values() if len(ids) > 1)
        if duplicate_rows:
            findings.append(
                Finding(
                    "SUPPLIER_INVOICE_DUPLICATE",
                    "HIGH",
                    "compras",
                    "numero_factura",
                    duplicate_rows,
                    "Duplicados bajo proveedor + número normalizado",
                    "No crear UNIQUE hasta resolver grupos manualmente",
                )
            )

    if schema_bootstrap.table_exists(conn, "movimientos") and schema_bootstrap.table_exists(conn, "movimientos_inventario"):
        first = int(conn.execute("SELECT COUNT(*) FROM movimientos").fetchone()[0])
        second = int(conn.execute("SELECT COUNT(*) FROM movimientos_inventario").fetchone()[0])
        findings.append(
            Finding(
                "DUAL_MOVEMENT_MODELS",
                "MEDIUM",
                "movimientos/movimientos_inventario",
                None,
                first + second,
                f"Dos modelos activos/compatibles ({first} y {second} filas)",
                "Definir tabla canónica y mapa de tipos en Fase 2B; no fusionar aún",
            )
        )

    fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_violations:
        by_table: Dict[str, int] = {}
        for row in fk_violations:
            by_table[str(row[0])] = by_table.get(str(row[0]), 0) + 1
        for table, affected in sorted(by_table.items()):
            findings.append(
                Finding(
                    "FOREIGN_KEY_VIOLATION",
                    "HIGH",
                    table,
                    None,
                    affected,
                    "Fila huérfana detectada por PRAGMA foreign_key_check",
                    "Resolver en fixture y solicitar decisión humana antes de aplicar",
                )
            )

    return SanitationReport(tuple(schema), tuple(findings), counts)
