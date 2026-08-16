# -*- coding: utf-8 -*-
"""Alias SKU de proveedor. Identidad distinta de product_barcodes."""
from __future__ import annotations

import uuid
from typing import Optional

from barcode_scanner import BarcodeScanError, normalize_barcode


class SupplierAliasError(ValueError):
    pass


class SupplierProductAliasesRepository:
    def __init__(self, db_manager):
        self.db = db_manager

    def assign_alias(
        self,
        *,
        proveedor_id: int,
        producto_local_id: str,
        alias_codigo: str,
    ) -> str:
        code = str(alias_codigo or "").strip()
        if not code:
            raise SupplierAliasError("El alias de proveedor no puede estar vacío")
        try:
            # Normaliza como texto exacto; no lo convierte en barcode físico.
            code = normalize_barcode(code)
        except BarcodeScanError as exc:
            raise SupplierAliasError(str(exc)) from exc
        local_id = str(uuid.uuid4())
        conn = self.db.conectar()
        try:
            existing = conn.execute(
                "SELECT local_id, producto_local_id FROM supplier_product_aliases "
                "WHERE proveedor_id = ? AND alias_codigo = ?",
                (proveedor_id, code),
            ).fetchone()
            if existing:
                if existing["producto_local_id"] != producto_local_id:
                    raise SupplierAliasError(
                        "El alias de proveedor ya está asignado a otro producto"
                    )
                return existing["local_id"]
            conn.execute(
                """
                INSERT INTO supplier_product_aliases (
                    local_id, proveedor_id, producto_local_id, alias_codigo
                ) VALUES (?, ?, ?, ?)
                """,
                (local_id, proveedor_id, producto_local_id, code),
            )
            conn.commit()
            return local_id
        except SupplierAliasError:
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def lookup_product(self, proveedor_id: int, alias_codigo: str) -> Optional[dict]:
        code = str(alias_codigo or "").strip()
        if not code:
            return None
        try:
            code = normalize_barcode(code)
        except BarcodeScanError:
            return None
        conn = self.db.conectar()
        try:
            row = conn.execute(
                """
                SELECT p.*, a.alias_codigo AS supplier_alias
                  FROM supplier_product_aliases a
                  JOIN productos p ON p.local_id = a.producto_local_id
                 WHERE a.proveedor_id = ? AND a.alias_codigo = ?
                """,
                (proveedor_id, code),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
