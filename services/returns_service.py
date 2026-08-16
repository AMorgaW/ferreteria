# -*- coding: utf-8 -*-
"""Reversos 3C: DRAFT local-first; CONFIRMAR aplica inventario exactamente una vez."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from packaging_conversion import (
    PackagingConversionBlocked,
    PackagingError,
    as_decimal,
    quantity_in_base_units,
    sqlite_number,
    validate_quantity,
)
from returns_schema import (
    COMPLETED_IMMUTABLE,
    ESTADO_APPLYING,
    ESTADO_COMPLETED,
    ESTADO_DRAFT,
    ESTADO_REJECTED,
    KIND_CUSTOMER_RETURN,
    KIND_SALE_VOID,
    KIND_SUPPLIER_RETURN,
    ORIGINAL_TIPO_COMPRA,
    ORIGINAL_TIPO_VENTA,
    OVER_RETURN,
    STATUS_FULLY_RETURNED,
    STATUS_PARTIALLY_RETURNED,
    STATUS_VOIDED,
)
from services.return_cart import ReturnCartError, line_subtotal


class ReturnsService:
    def __init__(self, db_manager, auth=None, productos_repo=None):
        self.db = db_manager
        self.auth = auth
        self.productos_repo = productos_repo
        self.last_inventory_command_id = None
        self.last_gateway_result = None

    def _usuario_id(self):
        if self.auth and getattr(self.auth, "usuario_actual", None):
            return self.auth.usuario_actual.id
        return None

    def _load_product(self, producto_id: int):
        if self.productos_repo is not None:
            return self.productos_repo.obtener_por_id(producto_id)
        conn = self.db.conectar()
        try:
            row = conn.execute(
                "SELECT * FROM productos WHERE id = ?", (producto_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def edit_completed_original(self, *args, **kwargs):
        """3C: un COMPLETED no se muta. Corrección = documento inverso nuevo."""
        return False, COMPLETED_IMMUTABLE, None

    def preview(self, *, original_tipo: str, original_id: int) -> Dict[str, Any]:
        conn = self.db.conectar()
        try:
            original, lines = self._load_original(conn, original_tipo, original_id)
            derived = self._derived_status(lines)
            return {
                "original": original,
                "lines": lines,
                "derived_status": derived,
            }
        finally:
            conn.close()

    def guardar_borrador(
        self,
        *,
        kind: str,
        original_tipo: str,
        original_id: int,
        items: Optional[List[dict]] = None,
        motivo: str = "",
        reversal_id: Optional[int] = None,
    ) -> Tuple[bool, str, Optional[int]]:
        if kind not in (
            KIND_CUSTOMER_RETURN,
            KIND_SALE_VOID,
            KIND_SUPPLIER_RETURN,
        ):
            return False, f"kind de reverso desconocido: {kind}", None
        expected_orig = (
            ORIGINAL_TIPO_COMPRA
            if kind == KIND_SUPPLIER_RETURN
            else ORIGINAL_TIPO_VENTA
        )
        if original_tipo != expected_orig:
            return False, "El tipo de documento original no coincide con el reverso", None
        conn = self.db.conectar()
        try:
            original, preview_lines = self._load_original(
                conn, original_tipo, original_id
            )
            if not original:
                return False, "Documento original no encontrado", None
            estado_orig = str(original.get("estado") or "").upper()
            if estado_orig in ("CANCELADA", "CANCELADO"):
                return False, "El documento original no admite reversos", None
            if original_tipo == ORIGINAL_TIPO_COMPRA and estado_orig not in (
                "COMPLETADA",
                "COMPLETED",
            ):
                return False, "Solo una recepción COMPLETED admite devolución a proveedor", None
            if original_tipo == ORIGINAL_TIPO_VENTA and estado_orig not in (
                "COMPLETADA",
                "COMPLETED",
                "DEVUELTA",
                "",
            ):
                return False, "Solo una venta COMPLETED admite reverso", None
            try:
                lines = self._normalized_items(
                    preview_lines, items, kind=kind, full_remaining=(not items)
                )
            except (PackagingConversionBlocked, PackagingError, ReturnCartError) as exc:
                return False, str(exc), None
            if reversal_id is not None:
                row = conn.execute(
                    "SELECT id, estado, inventory_command_id FROM reversal_documents "
                    "WHERE id = ?",
                    (reversal_id,),
                ).fetchone()
                if not row:
                    return False, "Borrador de reverso no encontrado", None
                estado = str(row["estado"] or "").upper()
                if estado == ESTADO_COMPLETED:
                    return False, COMPLETED_IMMUTABLE, None
                if estado not in (ESTADO_DRAFT, ESTADO_REJECTED):
                    return False, COMPLETED_IMMUTABLE, None
                if row["inventory_command_id"]:
                    return False, (
                        "Reverso en vuelo: no edite el borrador; "
                        "reintente CONFIRMAR con la misma identidad"
                    ), None
                conn.execute(
                    """
                    UPDATE reversal_documents SET
                        kind = ?, motivo = ?, usuario_id = ?,
                        updated_at = ?, estado = ?
                    WHERE id = ?
                    """,
                    (
                        kind,
                        motivo,
                        self._usuario_id(),
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        ESTADO_DRAFT,
                        reversal_id,
                    ),
                )
                conn.execute(
                    "DELETE FROM reversal_lines WHERE reversal_id = ?",
                    (reversal_id,),
                )
            else:
                from local_first_db import ensure_local_id
                import uuid as _uuid

                local_id = str(_uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO reversal_documents (
                        local_id, kind, original_tipo, original_id,
                        original_local_id, estado, usuario_id, motivo, fecha
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        local_id,
                        kind,
                        original_tipo,
                        original_id,
                        original.get("local_id"),
                        ESTADO_DRAFT,
                        self._usuario_id(),
                        motivo,
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                )
                reversal_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                ensure_local_id(conn, "reversal_documents", reversal_id)
            for item in lines:
                conn.execute(
                    """
                    INSERT INTO reversal_lines (
                        reversal_id, original_line_id, producto_id, package_role,
                        cantidad_presentacion, cantidad_base, precio_unitario, subtotal
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        reversal_id,
                        item.get("original_line_id"),
                        item["producto_id"],
                        item["package_role"],
                        sqlite_number(item["cantidad_presentacion"]),
                        sqlite_number(item["cantidad_base"]),
                        sqlite_number(item.get("precio_unitario") or 0),
                        sqlite_number(item.get("subtotal") or 0),
                    ),
                )
            conn.commit()
            return True, "Borrador de reverso guardado", reversal_id
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            return False, f"Error al guardar borrador de reverso: {exc}", None
        finally:
            conn.close()

    def confirmar(
        self,
        reversal_id: int,
        *,
        inventory_mode: Optional[str] = None,
        inventory_command_id: Optional[str] = None,
        inventory_gateway=None,
        inventory_transport=None,
        inventory_connection_factory=None,
    ) -> Tuple[bool, str, Optional[int]]:
        from inventory_writer_support import (
            WRITER_MODE_AUTHORITATIVE,
            resolve_writer_mode_or_frozen,
        )

        mode, frozen = resolve_writer_mode_or_frozen(
            inventory_mode,
            db=self.db,
            connection_factory=inventory_connection_factory,
        )
        if frozen:
            return False, frozen, None
        if mode == WRITER_MODE_AUTHORITATIVE:
            return self._confirmar_authoritative(
                reversal_id,
                inventory_command_id=inventory_command_id,
                inventory_gateway=inventory_gateway,
                inventory_transport=inventory_transport,
                inventory_connection_factory=inventory_connection_factory,
            )
        return self._confirmar_legacy(reversal_id)

    def _confirmar_legacy(self, reversal_id: int) -> Tuple[bool, str, Optional[int]]:
        from database import obtener_fecha_actual
        from inventory_cutover import commit_legacy_inventory

        conn = self.db.conectar()
        try:
            conn.isolation_level = "IMMEDIATE"
            doc, lines = self._load_reversal(conn, reversal_id)
            if not doc:
                return False, "Reverso no encontrado", None
            estado = str(doc.get("estado") or "").upper()
            if estado == ESTADO_COMPLETED:
                return True, "Reverso ya confirmado", reversal_id
            if estado not in (ESTADO_DRAFT, ESTADO_APPLYING, ESTADO_REJECTED):
                return False, COMPLETED_IMMUTABLE, None
            blocked = self._over_return_message(conn, doc, lines)
            if blocked:
                return False, blocked, None
            self._apply_local_kardex(conn, doc, lines, obtener_fecha_actual())
            conn.execute(
                "UPDATE reversal_documents SET estado = ?, updated_at = ? WHERE id = ?",
                (
                    ESTADO_COMPLETED,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    reversal_id,
                ),
            )
            commit_legacy_inventory(conn)
            conn.commit()
            return True, "Reverso confirmado", reversal_id
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            return False, f"Error al confirmar reverso: {exc}", None
        finally:
            conn.close()

    def _confirmar_authoritative(
        self,
        reversal_id: int,
        *,
        inventory_command_id,
        inventory_gateway,
        inventory_transport,
        inventory_connection_factory,
    ) -> Tuple[bool, str, Optional[int]]:
        from database import obtener_fecha_actual
        from inventory_cutover import (
            ACT_KIND_CUSTOMER_RETURN,
            ACT_KIND_SALE_VOID,
            ACT_KIND_SUPPLIER_RETURN,
        )
        from inventory_gateway import OUTCOME_APPLIED, OUTCOME_REJECTED
        from inventory_ledger import (
            QuantityScaleError,
            UnknownProductError,
            bind_inventory_command_documento,
        )
        from inventory_writer_support import (
            DOCUMENTO_TIPO_CUSTOMER_RETURN,
            DOCUMENTO_TIPO_SALE_VOID,
            DOCUMENTO_TIPO_SUPPLIER_RETURN,
            MissingProductLocalIdError,
            attach_original_document,
            bind_inventory_gateway,
            build_negative_operations,
            build_positive_operations,
            command_already_applied,
            durable_act_command_id,
            notify_after_remote_apply,
            unknown_writer_message,
        )
        from local_first_db import ensure_local_id

        act_by_kind = {
            KIND_CUSTOMER_RETURN: ACT_KIND_CUSTOMER_RETURN,
            KIND_SALE_VOID: ACT_KIND_SALE_VOID,
            KIND_SUPPLIER_RETURN: ACT_KIND_SUPPLIER_RETURN,
        }
        doc_tipo_by_kind = {
            KIND_CUSTOMER_RETURN: DOCUMENTO_TIPO_CUSTOMER_RETURN,
            KIND_SALE_VOID: DOCUMENTO_TIPO_SALE_VOID,
            KIND_SUPPLIER_RETURN: DOCUMENTO_TIPO_SUPPLIER_RETURN,
        }
        conn = self.db.conectar()
        try:
            conn.isolation_level = "IMMEDIATE"
            doc, lines = self._load_reversal(conn, reversal_id)
            if not doc:
                return False, "Reverso no encontrado", None
            estado = str(doc.get("estado") or "").upper()
            if estado == ESTADO_COMPLETED:
                self.last_inventory_command_id = doc.get("inventory_command_id")
                return True, "Reverso ya confirmado", reversal_id
            if estado not in (ESTADO_DRAFT, ESTADO_APPLYING, ESTADO_REJECTED):
                return False, COMPLETED_IMMUTABLE, None
            blocked = self._over_return_message(conn, doc, lines, skip_self=True)
            if blocked:
                return False, blocked, None

            reversal_local = doc.get("local_id") or ensure_local_id(
                conn, "reversal_documents", reversal_id
            )
            original_local = doc.get("original_local_id")
            if not original_local:
                table = (
                    "compras"
                    if doc["original_tipo"] == ORIGINAL_TIPO_COMPRA
                    else "ventas"
                )
                original_local = ensure_local_id(conn, table, doc["original_id"])
                conn.execute(
                    "UPDATE reversal_documents SET original_local_id = ? WHERE id = ?",
                    (original_local, reversal_id),
                )
            stored_cmd = doc.get("inventory_command_id") or inventory_command_id
            try:
                command_id = durable_act_command_id(
                    conn,
                    act_by_kind[doc["kind"]],
                    act_key=str(reversal_local),
                    explicit_command_id=stored_cmd,
                )
            except Exception as exc:
                return False, str(exc), None
            self.last_inventory_command_id = command_id
            conn.execute(
                """
                UPDATE reversal_documents
                   SET inventory_command_id = ?, local_id = ?, estado = ?,
                       original_local_id = ?, updated_at = ?
                 WHERE id = ?
                """,
                (
                    command_id,
                    reversal_local,
                    ESTADO_APPLYING,
                    original_local,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    reversal_id,
                ),
            )
            conn.commit()

            already = command_already_applied(conn, command_id)
            if already is None:
                op_lines = [
                    {
                        "producto_id": item["producto_id"],
                        "cantidad": item["cantidad_base"],
                    }
                    for item in lines
                ]
                try:
                    if doc["kind"] == KIND_SUPPLIER_RETURN:
                        operations = build_negative_operations(
                            conn, op_lines, command_id=command_id
                        )
                    else:
                        operations = build_positive_operations(
                            conn, op_lines, command_id=command_id
                        )
                    operations = attach_original_document(
                        operations,
                        original_documento_tipo=doc["original_tipo"],
                        original_documento_local_id=original_local,
                        original_command_id=self._original_command_id(
                            conn, doc, original_local
                        ),
                    )
                except MissingProductLocalIdError as exc:
                    return False, str(exc), None
                except (QuantityScaleError, UnknownProductError) as exc:
                    return False, str(exc), None
                gw = bind_inventory_gateway(
                    conn,
                    gateway=inventory_gateway,
                    transport=inventory_transport,
                    connection_factory=inventory_connection_factory,
                    cutover_enabled=True,
                )
                try:
                    result = gw.submit(
                        tipo="DEVOLUCION",
                        operations=operations,
                        command_id=command_id,
                        documento_tipo=doc_tipo_by_kind[doc["kind"]],
                        documento_local_id=reversal_local,
                        device_id=None,
                        usuario_id=doc.get("usuario_id") or self._usuario_id(),
                    )
                except Exception as exc:
                    return False, unknown_writer_message(command_id, str(exc)), None
                self.last_gateway_result = result
                if result.outcome == OUTCOME_REJECTED:
                    conn.execute(
                        """
                        UPDATE reversal_documents
                           SET estado = ?, inventory_command_id = NULL, updated_at = ?
                         WHERE id = ?
                        """,
                        (
                            ESTADO_REJECTED,
                            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            reversal_id,
                        ),
                    )
                    conn.commit()
                    return False, (
                        result.error or "Inventario rechazado por el coordinador"
                    ), None
                if result.outcome != OUTCOME_APPLIED:
                    return False, unknown_writer_message(
                        result.command_id, result.error or result.outcome
                    ), None
                notify_after_remote_apply(command_id)

            bind_inventory_command_documento(conn, command_id, reversal_local)
            self._apply_local_kardex(conn, doc, lines, obtener_fecha_actual())
            conn.execute(
                """
                UPDATE reversal_documents
                   SET estado = ?, updated_at = ?
                 WHERE id = ? AND estado != ?
                """,
                (
                    ESTADO_COMPLETED,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    reversal_id,
                    ESTADO_COMPLETED,
                ),
            )
            conn.commit()
            return True, "Reverso confirmado", reversal_id
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            cid = self.last_inventory_command_id or inventory_command_id or "?"
            from inventory_writer_support import unknown_writer_message

            return False, unknown_writer_message(cid, str(exc)), None
        finally:
            conn.close()

    def _load_original(self, conn, original_tipo: str, original_id: int):
        if original_tipo == ORIGINAL_TIPO_VENTA:
            header = conn.execute(
                "SELECT * FROM ventas WHERE id = ?", (original_id,)
            ).fetchone()
            if not header:
                return None, []
            original = dict(header)
            details = conn.execute(
                """
                SELECT d.*, p.nombre AS producto_nombre
                  FROM detalle_ventas d
                  LEFT JOIN productos p ON p.id = d.producto_id
                 WHERE d.venta_id = ?
                 ORDER BY d.id
                """,
                (original_id,),
            ).fetchall()
        elif original_tipo == ORIGINAL_TIPO_COMPRA:
            header = conn.execute(
                "SELECT * FROM compras WHERE id = ?", (original_id,)
            ).fetchone()
            if not header:
                return None, []
            original = dict(header)
            details = conn.execute(
                """
                SELECT d.*, p.nombre AS producto_nombre
                  FROM detalle_compras d
                  LEFT JOIN productos p ON p.id = d.producto_id
                 WHERE d.compra_id = ?
                 ORDER BY d.id
                """,
                (original_id,),
            ).fetchall()
        else:
            raise ReturnCartError(f"original_tipo desconocido: {original_tipo}")
        lines = []
        for row in details:
            item = dict(row)
            original_qty = as_decimal(item.get("cantidad") or 0)
            returned = self._returned_base(
                conn, original_tipo, original_id, item["producto_id"]
            )
            available = original_qty - returned
            if available < 0:
                available = Decimal("0")
            lines.append(
                {
                    "original_line_id": item.get("id"),
                    "producto_id": item["producto_id"],
                    "producto_nombre": item.get("producto_nombre")
                    or f"producto {item['producto_id']}",
                    "package_role": item.get("package_role") or "BASE_UNIT",
                    "original_qty": original_qty,
                    "returned_qty": returned,
                    "available_qty": available,
                    "precio_unitario": item.get("precio_unitario") or 0,
                    "requested_qty": Decimal("0"),
                }
            )
        return original, lines

    def _returned_base(self, conn, original_tipo, original_id, producto_id) -> Decimal:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(CAST(l.cantidad_base AS REAL)), 0) AS c
              FROM reversal_lines l
              JOIN reversal_documents d ON d.id = l.reversal_id
             WHERE d.original_tipo = ?
               AND d.original_id = ?
               AND d.estado IN ('COMPLETED', 'APPLYING')
               AND l.producto_id = ?
            """,
            (original_tipo, original_id, producto_id),
        ).fetchone()
        total = as_decimal(row["c"] if row else 0)
        if original_tipo == ORIGINAL_TIPO_VENTA:
            legacy = conn.execute(
                """
                SELECT COALESCE(SUM(cantidad), 0) AS c
                  FROM devolucion_detalle
                 WHERE venta_id = ? AND producto_id = ?
                """,
                (original_id, producto_id),
            ).fetchone()
            total += as_decimal(legacy["c"] if legacy else 0)
        return total

    def _derived_status(self, lines: List[dict]) -> Optional[str]:
        if not lines:
            return None
        orig = sum((as_decimal(x["original_qty"]) for x in lines), Decimal("0"))
        ret = sum((as_decimal(x["returned_qty"]) for x in lines), Decimal("0"))
        if ret <= 0:
            return None
        if ret + Decimal("0.0000001") >= orig:
            return STATUS_FULLY_RETURNED
        return STATUS_PARTIALLY_RETURNED

    def derived_status(self, *, original_tipo: str, original_id: int) -> Optional[str]:
        data = self.preview(original_tipo=original_tipo, original_id=original_id)
        status = data.get("derived_status")
        conn = self.db.conectar()
        try:
            voided = conn.execute(
                """
                SELECT 1 FROM reversal_documents
                 WHERE original_tipo = ? AND original_id = ?
                   AND kind = ? AND estado = ?
                 LIMIT 1
                """,
                (
                    original_tipo,
                    original_id,
                    KIND_SALE_VOID,
                    ESTADO_COMPLETED,
                ),
            ).fetchone()
        finally:
            conn.close()
        if voided:
            return STATUS_VOIDED
        return status

    def _normalized_items(
        self,
        preview_lines: List[dict],
        items: Optional[List[dict]],
        *,
        kind: str,
        full_remaining: bool,
    ) -> List[dict]:
        by_pid = {line["producto_id"]: line for line in preview_lines}
        work = items
        if full_remaining or not work:
            work = []
            for line in preview_lines:
                available = as_decimal(line["available_qty"])
                if available > 0:
                    work.append(
                        {
                            "producto_id": line["producto_id"],
                            "cantidad_presentacion": available,
                            "package_role": "BASE_UNIT",
                            "original_line_id": line.get("original_line_id"),
                            "precio_unitario": line.get("precio_unitario") or 0,
                        }
                    )
            if not work:
                raise ReturnCartError("No hay unidades pendientes por devolver")
        normalized = []
        requested_by_pid: Dict[int, Decimal] = {}
        for raw in work:
            pid = raw.get("producto_id")
            if pid not in by_pid:
                raise ReturnCartError(f"El producto {pid} no pertenece al documento original")
            product = self._load_product(pid) or {"id": pid, "permite_decimales": 1}
            qty_pres = raw.get("cantidad_presentacion")
            if qty_pres in (None, ""):
                qty_pres = raw.get("cantidad")
            qty_pres = validate_quantity(product, qty_pres)
            if qty_pres <= 0:
                raise ReturnCartError("La cantidad a devolver debe ser mayor a 0")
            role = raw.get("package_role") or "BASE_UNIT"
            qty_base = quantity_in_base_units(product, role, qty_pres)
            requested_by_pid[pid] = requested_by_pid.get(pid, Decimal("0")) + qty_base
            available = as_decimal(by_pid[pid]["available_qty"])
            if requested_by_pid[pid] > available:
                raise ReturnCartError(
                    f"{OVER_RETURN}: no se pueden devolver {requested_by_pid[pid]} "
                    f"de '{by_pid[pid]['producto_nombre']}': "
                    f"original {by_pid[pid]['original_qty']}, "
                    f"ya devuelto {by_pid[pid]['returned_qty']}, "
                    f"disponible {available}"
                )
            price = as_decimal(raw.get("precio_unitario", by_pid[pid].get("precio_unitario") or 0))
            normalized.append(
                {
                    "producto_id": pid,
                    "original_line_id": raw.get("original_line_id")
                    or by_pid[pid].get("original_line_id"),
                    "package_role": role,
                    "cantidad_presentacion": qty_pres,
                    "cantidad_base": qty_base,
                    "precio_unitario": price,
                    "subtotal": line_subtotal(qty_pres, price),
                }
            )
        return normalized

    def _original_command_id(self, conn, doc, original_local: str) -> Optional[str]:
        import schema_bootstrap

        if original_local and schema_bootstrap.table_exists(conn, "inventory_commands"):
            row = conn.execute(
                """
                SELECT command_id FROM inventory_commands
                 WHERE documento_local_id = ?
                   AND estado = 'APPLIED'
                   AND tipo IN ('VENTA', 'COMPRA', 'RECEPCION')
                 ORDER BY created_at
                 LIMIT 1
                """,
                (original_local,),
            ).fetchone()
            if row and row["command_id"]:
                return row["command_id"]
        table = (
            "compras" if doc["original_tipo"] == ORIGINAL_TIPO_COMPRA else "ventas"
        )
        try:
            row = conn.execute(
                f"SELECT inventory_command_id FROM {table} WHERE id = ?",
                (doc["original_id"],),
            ).fetchone()
        except Exception:
            return None
        if row and row["inventory_command_id"]:
            return row["inventory_command_id"]
        return None

    def _load_reversal(self, conn, reversal_id: int):
        row = conn.execute(
            "SELECT * FROM reversal_documents WHERE id = ?", (reversal_id,)
        ).fetchone()
        if not row:
            return None, []
        doc = dict(row)
        lines = [
            dict(item)
            for item in conn.execute(
                "SELECT * FROM reversal_lines WHERE reversal_id = ? ORDER BY id",
                (reversal_id,),
            ).fetchall()
        ]
        return doc, lines

    def _over_return_message(self, conn, doc, lines, *, skip_self: bool = False) -> Optional[str]:
        _, preview = self._load_original(conn, doc["original_tipo"], doc["original_id"])
        if not preview:
            return "Documento original no encontrado"
        available = {line["producto_id"]: as_decimal(line["available_qty"]) for line in preview}
        if skip_self and str(doc.get("estado") or "").upper() == ESTADO_APPLYING:
            for line in lines:
                pid = line["producto_id"]
                available[pid] = available.get(pid, Decimal("0")) + as_decimal(
                    line["cantidad_base"]
                )
        for line in lines:
            pid = line["producto_id"]
            need = as_decimal(line["cantidad_base"])
            have = available.get(pid, Decimal("0"))
            if need > have:
                return (
                    f"{OVER_RETURN}: requerido {need}, disponible {have} "
                    f"(producto {pid})"
                )
            available[pid] = have - need
        return None

    def _apply_local_kardex(self, conn, doc, lines, fecha: str) -> None:
        from local_first_db import ensure_local_id
        from repositories._outbox import encolar

        existing = conn.execute(
            "SELECT COUNT(*) AS c FROM movimientos WHERE observaciones = ?",
            (f"Reverso #{doc['id']}",),
        ).fetchone()["c"]
        if existing:
            return
        kind = doc["kind"]
        if kind == KIND_SUPPLIER_RETURN:
            kardex = "SALIDA_DEVOLUCION_PROVEEDOR"
        elif kind == KIND_SALE_VOID:
            kardex = "ENTRADA_ANULACION"
        else:
            kardex = "ENTRADA_DEVOLUCION"
        usuario_id = doc.get("usuario_id") or self._usuario_id()
        for item in lines:
            qty = as_decimal(item["cantidad_base"])
            price = as_decimal(item.get("precio_unitario") or 0)
            conn.execute(
                """
                INSERT INTO movimientos (
                    tipo, producto_id, usuario_id, cantidad,
                    precio_unitario, costo_total, motivo, observaciones, fecha
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kardex,
                    item["producto_id"],
                    usuario_id,
                    sqlite_number(qty),
                    sqlite_number(price),
                    sqlite_number(qty * price),
                    doc.get("motivo") or "",
                    f"Reverso #{doc['id']}",
                    fecha,
                ),
            )
            mov_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            ensure_local_id(conn, "movimientos", mov_id)
            encolar(conn, "inventory_movement", mov_id, "create", "movimientos")
