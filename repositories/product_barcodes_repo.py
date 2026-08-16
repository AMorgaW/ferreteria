# -*- coding: utf-8 -*-
"""Repositorio especializado para múltiples barcodes por SKU."""
from __future__ import annotations

import secrets
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Callable, List, Optional

from barcode_scanner import normalize_barcode


BARCODE_TYPE_MANUFACTURER = "MANUFACTURER"
BARCODE_TYPE_INTERNAL_FRP = "INTERNAL_FRP"
SOURCE_HID_DOUBLE_SCAN = "HID_DOUBLE_SCAN"
SOURCE_EXPLICIT_FRP = "EXPLICIT_FRP"
FRP_MAX_ATTEMPTS = 10

# Presentación física que identifica el barcode (misma SKU, mismo stock).
PACKAGE_ROLE_BASE_UNIT = "BASE_UNIT"
PACKAGE_ROLE_FULL_PACKAGE = "FULL_PACKAGE"
PACKAGE_ROLE_CUSTOM_PRESENTATION = "CUSTOM_PRESENTATION"
PACKAGE_ROLES = (
    PACKAGE_ROLE_BASE_UNIT,
    PACKAGE_ROLE_FULL_PACKAGE,
    PACKAGE_ROLE_CUSTOM_PRESENTATION,
)


def _execute(conn, sql: str, params=()):
    """API común para sqlite3.Connection y PgConnection/PgCompat."""
    if hasattr(conn, "execute"):
        return conn.execute(sql, params)
    cursor = conn.cursor()
    cursor.execute(sql, params)
    return cursor


class BarcodeRepositoryError(RuntimeError):
    pass


class BarcodeSchemaMissingError(BarcodeRepositoryError):
    pass


class BarcodeConflictError(BarcodeRepositoryError):
    def __init__(self, barcode: str, product_name: str):
        self.barcode = barcode
        self.product_name = product_name
        super().__init__(f"Código ya asignado a: {product_name}")


class FrpGenerationError(BarcodeRepositoryError):
    pass


@dataclass(frozen=True)
class BarcodeRecord:
    local_id: str
    producto_local_id: str
    barcode: str
    barcode_type: str
    source: str
    is_primary: bool
    active: bool
    package_role: str = PACKAGE_ROLE_BASE_UNIT


class FrpBarcodeGenerator:
    """Genera FRP no secuenciales y reintenta colisiones de forma acotada."""

    def __init__(
        self,
        exists: Callable[[str], bool],
        *,
        max_attempts: int = FRP_MAX_ATTEMPTS,
        token_hex: Callable[[int], str] = secrets.token_hex,
    ) -> None:
        if max_attempts <= 0:
            raise ValueError("max_attempts debe ser positivo")
        self.exists = exists
        self.max_attempts = max_attempts
        self.token_hex = token_hex

    def generate(self) -> str:
        for _ in range(self.max_attempts):
            candidate = f"FRP-{self.token_hex(8).upper()}"
            if not self.exists(candidate):
                return candidate
        raise FrpGenerationError(
            f"No fue posible generar un FRP único tras {self.max_attempts} intentos"
        )


class ProductBarcodesRepository:
    """Acceso exacto/case-sensitive a ``product_barcodes``.

    Ningún método crea balances ni toca ``productos.stock``.
    """

    def __init__(self, db_manager):
        self.db = db_manager

    @staticmethod
    def _row_dict(row) -> Optional[dict]:
        if row is None:
            return None
        if isinstance(row, dict):
            return row
        try:
            return dict(row)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _record(row) -> Optional[BarcodeRecord]:
        data = ProductBarcodesRepository._row_dict(row)
        if not data:
            return None
        return BarcodeRecord(
            local_id=str(data["local_id"]),
            producto_local_id=str(data["producto_local_id"]),
            barcode=str(data["barcode"]),
            barcode_type=str(data.get("barcode_type") or BARCODE_TYPE_MANUFACTURER),
            source=str(data.get("source") or SOURCE_HID_DOUBLE_SCAN),
            is_primary=bool(data.get("is_primary")),
            active=bool(data.get("active", 1)),
            package_role=str(data.get("package_role") or PACKAGE_ROLE_BASE_UNIT),
        )

    @staticmethod
    def _has_package_role_column(conn) -> bool:
        """Tolerante a esquemas 2C sin la migración 20260815_006."""
        try:
            if isinstance(conn, sqlite3.Connection):
                rows = _execute(
                    conn, "PRAGMA table_info(product_barcodes)"
                ).fetchall()
                return any(row[1] == "package_role" for row in rows)
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema='public' "
                "AND table_name='product_barcodes' "
                "AND column_name='package_role'"
            )
            return cur.fetchone() is not None
        except Exception:
            return False

    @staticmethod
    def _is_sqlite(conn) -> bool:
        return isinstance(conn, sqlite3.Connection)

    @staticmethod
    def _table_exists(conn) -> bool:
        try:
            if isinstance(conn, sqlite3.Connection):
                return _execute(conn,
                    "SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='product_barcodes'"
                ).fetchone() is not None
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name='product_barcodes'"
            )
            return cur.fetchone() is not None
        except Exception:
            return False

    def _require_schema(self, conn) -> None:
        if not self._table_exists(conn):
            raise BarcodeSchemaMissingError(
                "Falta la migración Fase 2C product_barcodes"
            )

    @staticmethod
    def _enqueue_if_available(conn, local_id: str, operation: str) -> None:
        if not isinstance(conn, sqlite3.Connection):
            return
        has_queue = _execute(conn,
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sync_queue'"
        ).fetchone()
        if not has_queue:
            return
        from local_first_db import enqueue_entity

        enqueue_entity(
            conn,
            "product_barcode",
            local_id,
            operation,
            "product_barcodes",
        )

    @staticmethod
    def _product(conn, producto_local_id: str):
        return _execute(conn,
            "SELECT local_id, nombre FROM productos WHERE local_id = ? LIMIT 1",
            (producto_local_id,),
        ).fetchone()

    @staticmethod
    def _owner(conn, barcode: str):
        return _execute(conn,
            """
            SELECT b.producto_local_id, b.active, p.nombre
            FROM product_barcodes b
            LEFT JOIN productos p ON p.local_id = b.producto_local_id
            WHERE b.barcode = ?
            LIMIT 1
            """,
            (barcode,),
        ).fetchone()

    def assign_in_connection(
        self,
        conn,
        *,
        producto_local_id: str,
        barcode: str,
        barcode_type: str = BARCODE_TYPE_MANUFACTURER,
        source: str = SOURCE_HID_DOUBLE_SCAN,
        is_primary: Optional[bool] = None,
        package_role: str = PACKAGE_ROLE_BASE_UNIT,
    ) -> BarcodeRecord:
        """Inserta dentro de la transacción del caller; no hace commit."""
        self._require_schema(conn)
        if package_role not in PACKAGE_ROLES:
            raise BarcodeRepositoryError(
                f"package_role inválido: {package_role}"
            )
        has_role_column = self._has_package_role_column(conn)
        if package_role != PACKAGE_ROLE_BASE_UNIT and not has_role_column:
            raise BarcodeRepositoryError(
                "Falta la migración 20260815_006 barcode_package_role"
            )
        value = normalize_barcode(barcode)
        product = self._product(conn, producto_local_id)
        if product is None:
            raise BarcodeRepositoryError("Producto no encontrado")

        owner = self._owner(conn, value)
        if owner is not None:
            owner_data = self._row_dict(owner) or {}
            name = owner_data.get("nombre") or owner_data.get("producto_local_id") or "otro producto"
            if owner_data.get("producto_local_id") == producto_local_id and bool(owner_data.get("active")):
                _execute(
                    conn,
                    "UPDATE productos SET barcode_status = 'BARCODE_VERIFIED' "
                    "WHERE local_id = ?",
                    (producto_local_id,),
                )
                row = _execute(conn,
                    "SELECT * FROM product_barcodes WHERE barcode = ?", (value,)
                ).fetchone()
                record = self._record(row)
                if record is not None:
                    return record
            raise BarcodeConflictError(value, str(name))

        if is_primary is None:
            row = _execute(conn,
                "SELECT 1 FROM product_barcodes "
                "WHERE producto_local_id = ? AND active = 1 LIMIT 1",
                (producto_local_id,),
            ).fetchone()
            is_primary = row is None

        if is_primary:
            _execute(conn,
                "UPDATE product_barcodes SET is_primary = 0, updated_at = CURRENT_TIMESTAMP "
                "WHERE producto_local_id = ? AND active = 1 AND is_primary = 1",
                (producto_local_id,),
            )

        local_id = str(uuid.uuid4())
        try:
            if has_role_column:
                _execute(conn,
                    """
                    INSERT INTO product_barcodes (
                        local_id, producto_local_id, barcode, barcode_type,
                        source, is_primary, active, package_role
                    ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                    """,
                    (
                        local_id,
                        producto_local_id,
                        value,
                        barcode_type,
                        source,
                        1 if is_primary else 0,
                        package_role,
                    ),
                )
            else:
                # Esquema 2C sin package_role: solo BASE_UNIT llega aquí.
                _execute(conn,
                    """
                    INSERT INTO product_barcodes (
                        local_id, producto_local_id, barcode, barcode_type,
                        source, is_primary, active
                    ) VALUES (?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        local_id,
                        producto_local_id,
                        value,
                        barcode_type,
                        source,
                        1 if is_primary else 0,
                    ),
                )
        except Exception as exc:
            owner = self._owner(conn, value)
            if owner is not None:
                data = self._row_dict(owner) or {}
                raise BarcodeConflictError(
                    value,
                    str(data.get("nombre") or data.get("producto_local_id") or "otro producto"),
                ) from exc
            raise

        _execute(conn,
            "UPDATE productos SET barcode_status = 'BARCODE_VERIFIED' "
            "WHERE local_id = ?",
            (producto_local_id,),
        )
        self._enqueue_if_available(conn, local_id, "create")
        row = _execute(conn,
            "SELECT * FROM product_barcodes WHERE local_id = ?", (local_id,)
        ).fetchone()
        record = self._record(row)
        if record is None or record.barcode != value:
            raise BarcodeRepositoryError("No se pudo releer el barcode insertado")
        return record

    def assign_barcode(self, **kwargs) -> BarcodeRecord:
        conn = self.db.conectar()
        try:
            record = self.assign_in_connection(conn, **kwargs)
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            finally:
                conn.close()
            raise
        conn.close()
        persisted = self.get_by_local_id(record.local_id)
        if persisted is None or persisted.barcode != record.barcode:
            raise BarcodeRepositoryError(
                "Persistencia no verificada: la relectura no coincide"
            )
        return persisted

    def get_by_local_id(self, local_id: str) -> Optional[BarcodeRecord]:
        conn = self.db.conectar()
        try:
            self._require_schema(conn)
            row = _execute(conn,
                "SELECT * FROM product_barcodes WHERE local_id = ?", (local_id,)
            ).fetchone()
            return self._record(row)
        finally:
            conn.close()

    def get_by_barcode(self, barcode: str, *, active_only: bool = True) -> Optional[BarcodeRecord]:
        value = normalize_barcode(barcode)
        conn = self.db.conectar()
        try:
            self._require_schema(conn)
            sql = "SELECT * FROM product_barcodes WHERE barcode = ?"
            if active_only:
                sql += " AND active = 1"
            return self._record(_execute(conn, sql, (value,)).fetchone())
        finally:
            conn.close()

    def barcode_exists(self, barcode: str) -> bool:
        return self.get_by_barcode(barcode, active_only=False) is not None

    def list_for_product(self, producto_local_id: str, *, active_only: bool = True) -> List[BarcodeRecord]:
        conn = self.db.conectar()
        try:
            self._require_schema(conn)
            sql = "SELECT * FROM product_barcodes WHERE producto_local_id = ?"
            if active_only:
                sql += " AND active = 1"
            sql += " ORDER BY is_primary DESC, created_at, barcode"
            return [
                self._record(row)
                for row in _execute(conn, sql, (producto_local_id,)).fetchall()
            ]
        finally:
            conn.close()

    def lookup_product(self, barcode: str) -> Optional[dict]:
        value = normalize_barcode(barcode)
        conn = self.db.conectar()
        try:
            self._require_schema(conn)
            role_select = (
                ", b.package_role AS matched_package_role"
                if self._has_package_role_column(conn)
                else ""
            )
            row = _execute(conn,
                """
                SELECT p.*, b.local_id AS barcode_local_id,
                       b.barcode AS matched_barcode,
                       b.barcode_type AS matched_barcode_type,
                       b.is_primary AS matched_barcode_is_primary"""
                + role_select +
                """
                FROM product_barcodes b
                JOIN productos p ON p.local_id = b.producto_local_id
                WHERE b.barcode = ? AND b.active = 1
                  AND COALESCE(b.is_deleted, 0) = 0
                  AND COALESCE(p.activo, 1) = 1
                  AND COALESCE(p.is_deleted, 0) = 0
                LIMIT 1
                """,
                (value,),
            ).fetchone()
            return self._row_dict(row)
        finally:
            conn.close()

    def set_primary(self, barcode_local_id: str) -> BarcodeRecord:
        conn = self.db.conectar()
        try:
            self._require_schema(conn)
            row = _execute(conn,
                "SELECT producto_local_id FROM product_barcodes "
                "WHERE local_id = ? AND active = 1",
                (barcode_local_id,),
            ).fetchone()
            data = self._row_dict(row)
            if not data:
                raise BarcodeRepositoryError("Barcode activo no encontrado")
            producto_local_id = data["producto_local_id"]
            _execute(conn,
                "UPDATE product_barcodes SET is_primary = 0, updated_at = CURRENT_TIMESTAMP "
                "WHERE producto_local_id = ? AND active = 1",
                (producto_local_id,),
            )
            _execute(conn,
                "UPDATE product_barcodes SET is_primary = 1, updated_at = CURRENT_TIMESTAMP "
                "WHERE local_id = ?",
                (barcode_local_id,),
            )
            self._enqueue_if_available(conn, barcode_local_id, "update")
            conn.commit()
        except Exception:
            conn.rollback()
            conn.close()
            raise
        conn.close()
        record = self.get_by_local_id(barcode_local_id)
        if record is None or not record.is_primary:
            raise BarcodeRepositoryError("No se pudo verificar el barcode principal")
        return record

    def generate_and_assign_internal(
        self,
        producto_local_id: str,
        *,
        allow_when_barcode_exists: bool = False,
        max_attempts: int = FRP_MAX_ATTEMPTS,
        token_hex: Callable[[int], str] = secrets.token_hex,
    ) -> BarcodeRecord:
        if self.list_for_product(producto_local_id) and not allow_when_barcode_exists:
            raise BarcodeRepositoryError(
                "El producto ya tiene barcode; FRP requiere autorización explícita adicional"
            )
        if max_attempts <= 0:
            raise ValueError("max_attempts debe ser positivo")
        # El límite cubre prechecks y carreras: nunca supera max_attempts tokens.
        for _ in range(max_attempts):
            candidate = f"FRP-{token_hex(8).upper()}"
            if self.barcode_exists(candidate):
                continue
            try:
                return self.assign_barcode(
                    producto_local_id=producto_local_id,
                    barcode=candidate,
                    barcode_type=BARCODE_TYPE_INTERNAL_FRP,
                    source=SOURCE_EXPLICIT_FRP,
                )
            except BarcodeConflictError:
                continue
        raise FrpGenerationError(
            f"No fue posible persistir un FRP único tras {max_attempts} intentos"
        )
