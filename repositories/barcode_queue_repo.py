# -*- coding: utf-8 -*-
"""Cola operacional de regularización de barcodes (Fase 2F).

La cola se deriva exclusivamente de DB: ``productos.barcode_status`` y el
staging de Fase 2D (``inventory_import_rows``). No hay estado en memoria que
sobreviva a un reinicio; un producto ``PERSISTENCE_VERIFIED`` (status
``BARCODE_VERIFIED``) no reaparece como pendiente.

Ningún método escribe en la base de datos.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List, Optional

from barcode_scanner import normalize_barcode


# Estados operacionales de la cola.
QUEUE_STATUS_PENDING = "BARCODE_PENDING"
QUEUE_STATUS_LEGACY = "BARCODE_MISSING_LEGACY"
QUEUE_STATUS_VERIFIED = "BARCODE_VERIFIED"
QUEUE_STATUS_CONFLICT = "BARCODE_CONFLICT"

# Filtros de la vista administrativa.
FILTER_ALL = "TODOS"
FILTER_PENDING = "PENDIENTES"
FILTER_LEGACY = "LEGACY SIN BARCODE"
FILTER_STAGING = "STAGING SIN BARCODE"
FILTER_VERIFIED = "VERIFICADOS"
FILTER_CONFLICT = "CON CONFLICTO"
QUEUE_FILTERS = (
    FILTER_ALL,
    FILTER_PENDING,
    FILTER_LEGACY,
    FILTER_STAGING,
    FILTER_VERIFIED,
    FILTER_CONFLICT,
)

KIND_PRODUCT = "PRODUCT"
KIND_STAGING_ROW = "STAGING_ROW"

_ORIGEN_BY_STATUS = {
    QUEUE_STATUS_PENDING: "STAGING",
    QUEUE_STATUS_LEGACY: "LEGACY",
    QUEUE_STATUS_VERIFIED: "VERIFICADO",
    QUEUE_STATUS_CONFLICT: "IMPORT_STAGING",
}

_ACCION_BY_STATUS = {
    QUEUE_STATUS_PENDING: "ESCANEAR DOBLE VEZ",
    QUEUE_STATUS_LEGACY: "ESCANEAR DOBLE VEZ",
    QUEUE_STATUS_VERIFIED: "REVISAR / AGREGAR ADICIONAL",
    QUEUE_STATUS_CONFLICT: "RESOLVER CONFLICTO",
}


@dataclass(frozen=True)
class BarcodeQueueItem:
    """Una fila de la cola; nunca dos items representan el mismo producto."""

    key: str
    item_kind: str
    nombre: str
    marca: str = ""
    categoria: str = ""
    unidad_base: str = ""
    presentacion: str = ""
    barcode_status: str = QUEUE_STATUS_PENDING
    origen: str = "LEGACY"
    accion: str = "ESCANEAR DOBLE VEZ"
    producto_id: Optional[int] = None
    producto_local_id: Optional[str] = None
    staging_row_id: Optional[str] = None
    excel_candidate: Optional[str] = None
    primary_barcode: Optional[str] = None
    barcodes: tuple = field(default_factory=tuple)

    @property
    def selectable(self) -> bool:
        """Solo un producto materializado acepta doble scan operacional."""
        return self.item_kind == KIND_PRODUCT and self.producto_local_id is not None


def _execute(conn, sql: str, params=()):
    return conn.execute(sql, params)


def _table_exists(conn, table: str) -> bool:
    return _execute(
        conn,
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


class BarcodeQueueRepository:
    """Construye la cola desde DB; no persiste nada."""

    def __init__(self, db_manager):
        self.db = db_manager

    # ------------------------------------------------------------------
    # Lecturas internas
    # ------------------------------------------------------------------
    @staticmethod
    def _product_rows(conn) -> list:
        return _execute(
            conn,
            """
            SELECT p.id, p.local_id, p.nombre, p.marca, p.categoria,
                   p.unidad_medida, p.presentacion, p.barcode_status
            FROM productos p
            WHERE COALESCE(p.activo, 1) = 1
              AND COALESCE(p.is_deleted, 0) = 0
            ORDER BY p.nombre
            """,
        ).fetchall()

    @staticmethod
    def _barcodes_by_product(conn) -> dict:
        if not _table_exists(conn, "product_barcodes"):
            return {}
        rows = _execute(
            conn,
            """
            SELECT producto_local_id, barcode, is_primary
            FROM product_barcodes
            WHERE active = 1 AND COALESCE(is_deleted, 0) = 0
            ORDER BY is_primary DESC, created_at, barcode
            """,
        ).fetchall()
        result = {}
        for row in rows:
            data = dict(row)
            result.setdefault(str(data["producto_local_id"]), []).append(
                (str(data["barcode"]), bool(data["is_primary"]))
            )
        return result

    @staticmethod
    def _staging_candidates(conn) -> dict:
        """candidate Excel por producto ya matcheado (referencia, nunca VERIFIED)."""
        if not _table_exists(conn, "inventory_import_rows"):
            return {}
        rows = _execute(
            conn,
            """
            SELECT matched_producto_local_id, barcode_candidate
            FROM inventory_import_rows
            WHERE matched_producto_local_id IS NOT NULL
              AND barcode_candidate IS NOT NULL
              AND barcode_candidate != ''
            """,
        ).fetchall()
        result = {}
        for row in rows:
            data = dict(row)
            result[str(data["matched_producto_local_id"])] = str(
                data["barcode_candidate"]
            )
        return result

    @staticmethod
    def _conflict_products(conn) -> set:
        if not _table_exists(conn, "inventory_import_rows"):
            return set()
        rows = _execute(
            conn,
            """
            SELECT DISTINCT matched_producto_local_id
            FROM inventory_import_rows
            WHERE barcode_status = 'CONFLICT_BARCODE_PRODUCT'
              AND matched_producto_local_id IS NOT NULL
            """,
        ).fetchall()
        return {str(dict(row)["matched_producto_local_id"]) for row in rows}

    @staticmethod
    def _staging_rows(conn) -> list:
        """Filas staging sin producto materializado y sin barcode confirmado."""
        if not (
            _table_exists(conn, "inventory_import_rows")
            and _table_exists(conn, "inventory_import_batches")
        ):
            return []
        rows = _execute(
            conn,
            """
            SELECT r.row_id, r.barcode_status, r.barcode_candidate,
                   r.normalized_payload, r.matched_product_name
            FROM inventory_import_rows r
            JOIN inventory_import_batches b ON b.batch_id = r.batch_id
            WHERE r.matched_producto_local_id IS NULL
              AND r.barcode_status IN ('BARCODE_PENDING', 'BARCODE_EXCEL_CANDIDATE')
              AND r.duplicate_candidate = 0
              AND b.status NOT IN ('APPLIED', 'INVALID')
            ORDER BY r.batch_id, r.excel_row_number
            """,
        ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------
    def list_queue(
        self,
        queue_filter: str = FILTER_ALL,
        search: str = "",
    ) -> List[BarcodeQueueItem]:
        if queue_filter not in QUEUE_FILTERS:
            raise ValueError(f"Filtro de cola inválido: {queue_filter}")
        conn = self.db.conectar()
        try:
            if not _table_exists(conn, "productos"):
                return []
            has_status = any(
                row[1] == "barcode_status"
                for row in _execute(conn, "PRAGMA table_info(productos)").fetchall()
            )
            candidates = self._staging_candidates(conn)
            conflicts = self._conflict_products(conn)
            barcodes = self._barcodes_by_product(conn)

            items: List[BarcodeQueueItem] = []
            seen_products = set()
            for row in self._product_rows(conn):
                data = dict(row)
                local_id = str(data["local_id"])
                if local_id in seen_products:
                    continue
                seen_products.add(local_id)
                status = str(
                    data.get("barcode_status") or QUEUE_STATUS_LEGACY
                    if has_status
                    else QUEUE_STATUS_LEGACY
                )
                if local_id in conflicts and status != QUEUE_STATUS_VERIFIED:
                    status = QUEUE_STATUS_CONFLICT
                if status not in (
                    QUEUE_STATUS_PENDING,
                    QUEUE_STATUS_LEGACY,
                    QUEUE_STATUS_VERIFIED,
                    QUEUE_STATUS_CONFLICT,
                ):
                    continue
                codes = barcodes.get(local_id, [])
                primary = next(
                    (code for code, is_primary in codes if is_primary), None
                )
                items.append(
                    BarcodeQueueItem(
                        key=local_id,
                        item_kind=KIND_PRODUCT,
                        producto_id=data.get("id"),
                        producto_local_id=local_id,
                        nombre=str(data.get("nombre") or ""),
                        marca=str(data.get("marca") or ""),
                        categoria=str(data.get("categoria") or ""),
                        unidad_base=str(data.get("unidad_medida") or ""),
                        presentacion=str(data.get("presentacion") or ""),
                        barcode_status=status,
                        origen=_ORIGEN_BY_STATUS.get(status, "LEGACY"),
                        accion=_ACCION_BY_STATUS.get(status, "ESCANEAR DOBLE VEZ"),
                        excel_candidate=candidates.get(local_id),
                        primary_barcode=primary,
                        barcodes=tuple(code for code, _p in codes),
                    )
                )

            if queue_filter in (FILTER_ALL, FILTER_STAGING):
                for data in self._staging_rows(conn):
                    payload = json.loads(data.get("normalized_payload") or "{}")
                    candidate = data.get("barcode_candidate") or None
                    items.append(
                        BarcodeQueueItem(
                            key=str(data["row_id"]),
                            item_kind=KIND_STAGING_ROW,
                            staging_row_id=str(data["row_id"]),
                            nombre=str(
                                payload.get("nombre")
                                or data.get("matched_product_name")
                                or ""
                            ),
                            marca=str(payload.get("marca") or ""),
                            categoria=str(payload.get("categoria") or ""),
                            unidad_base=str(payload.get("unidad_base") or ""),
                            presentacion=str(
                                payload.get("presentacion_empaque") or ""
                            ),
                            barcode_status=QUEUE_STATUS_PENDING,
                            origen="IMPORT_STAGING",
                            accion="PENDIENTE DE APPLY",
                            excel_candidate=candidate,
                        )
                    )

            items = [item for item in items if self._matches_filter(item, queue_filter)]
            search = (search or "").strip()
            if search:
                items = [item for item in items if self._matches_search(item, search)]
            return items
        finally:
            conn.close()

    def pending_products(self) -> List[BarcodeQueueItem]:
        """Productos materializados aún sin barcode confirmado."""
        items = self.list_queue(FILTER_ALL)
        return [
            item
            for item in items
            if item.selectable
            and item.barcode_status
            in (QUEUE_STATUS_PENDING, QUEUE_STATUS_LEGACY)
        ]

    # ------------------------------------------------------------------
    # Filtro y búsqueda
    # ------------------------------------------------------------------
    @staticmethod
    def _matches_filter(item: BarcodeQueueItem, queue_filter: str) -> bool:
        if queue_filter == FILTER_ALL:
            return True
        if queue_filter == FILTER_STAGING:
            return item.item_kind == KIND_STAGING_ROW
        if queue_filter == FILTER_PENDING:
            return (
                item.item_kind == KIND_PRODUCT
                and item.barcode_status == QUEUE_STATUS_PENDING
            )
        if queue_filter == FILTER_LEGACY:
            return (
                item.item_kind == KIND_PRODUCT
                and item.barcode_status == QUEUE_STATUS_LEGACY
            )
        if queue_filter == FILTER_VERIFIED:
            return item.barcode_status == QUEUE_STATUS_VERIFIED
        if queue_filter == FILTER_CONFLICT:
            return item.barcode_status == QUEUE_STATUS_CONFLICT
        return False

    @staticmethod
    def _matches_search(item: BarcodeQueueItem, search: str) -> bool:
        needle = search.casefold()
        for value in (item.nombre, item.marca, item.categoria):
            if needle in value.casefold():
                return True
        # La búsqueda textual es de UI; el barcode almacenado jamás se altera.
        for code in item.barcodes:
            if search in code:
                return True
        if item.excel_candidate and search in item.excel_candidate:
            return True
        return False


def candidate_matches_scan(candidate: Optional[str], raw_scan: str) -> Optional[bool]:
    """Compara el primer scan físico con el candidate Excel.

    Devuelve None si no hay candidate; la comparación es exacta tras la
    normalización permitida (sin tocar ceros iniciales ni case).
    """
    if not candidate:
        return None
    return normalize_barcode(raw_scan) == candidate
