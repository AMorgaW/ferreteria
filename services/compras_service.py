# -*- coding: utf-8 -*-
"""Recepción 3B: DRAFT local-first; CONFIRMAR aplica inventario exactamente una vez."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from packaging_conversion import (
    PackagingConversionBlocked,
    PackagingError,
    as_decimal,
    sqlite_number,
    validate_cost,
    validate_quantity,
)
from repositories.compras_repo import ComprasRepository
from repositories.productos_repo import ProductosRepository
from repositories.proveedores_repo import ProveedoresRepository
from repositories.supplier_product_aliases_repo import SupplierProductAliasesRepository
from services.purchase_cart import (
    COMPLETED_IMMUTABLE,
    ESTADO_CANCELADA,
    ESTADO_COMPLETADA,
    ESTADO_DRAFT,
    PurchaseCartError,
    line_subtotal,
)


class ComprasService:
    def __init__(
        self,
        db_manager,
        compras_repo=None,
        productos_repo=None,
        proveedores_repo=None,
        auth=None,
        aliases_repo=None,
    ):
        self.db = db_manager
        self.compras_repo = compras_repo or ComprasRepository(db_manager)
        self.productos_repo = productos_repo or ProductosRepository(db_manager)
        self.proveedores_repo = proveedores_repo or ProveedoresRepository(db_manager)
        self.auth = auth
        self.aliases_repo = aliases_repo or SupplierProductAliasesRepository(db_manager)
        self.last_inventory_command_id = None
        self.last_gateway_result = None

    def _usuario_id(self):
        if self.auth and getattr(self.auth, "usuario_actual", None):
            return self.auth.usuario_actual.id
        return None

    def _load_product(self, producto_id: int) -> Optional[dict]:
        return self.productos_repo.obtener_por_id(producto_id)

    def _normalized_lines(self, productos: List[dict]) -> Tuple[List[dict], Decimal]:
        if not productos:
            raise PurchaseCartError("Debe agregar al menos un producto a la recepción")
        lines = []
        total = Decimal("0")
        for raw in productos:
            product = raw.get("producto") or self._load_product(raw["producto_id"])
            if not product:
                raise PurchaseCartError(f"Producto ID {raw.get('producto_id')} no encontrado")
            from packaging_conversion import quantity_in_base_units

            qty_pres = raw.get("cantidad_presentacion")
            if qty_pres in (None, ""):
                qty_pres = raw.get("cantidad")
            qty_pres = validate_quantity(product, qty_pres)
            role = raw.get("package_role")
            converted = quantity_in_base_units(product, role, qty_pres)
            stored = raw.get("cantidad")
            if stored not in (None, "") and raw.get("cantidad_presentacion") not in (None, ""):
                qty_base = as_decimal(stored)
            else:
                qty_base = converted
            cost = validate_cost(raw.get("precio_unitario", 0))
            subtotal = line_subtotal(qty_pres, cost)
            total += subtotal
            lines.append(
                {
                    "producto_id": product["id"],
                    "cantidad": sqlite_number(qty_base),
                    "cantidad_presentacion": sqlite_number(qty_pres),
                    "precio_unitario": sqlite_number(cost),
                    "subtotal": sqlite_number(subtotal),
                    "package_role": role or "BASE_UNIT",
                    "supplier_alias": raw.get("supplier_alias"),
                    "producto": product,
                }
            )
        return lines, total

    def guardar_borrador(
        self,
        *,
        proveedor_id: int,
        productos: List[dict],
        numero_factura: Optional[str] = None,
        tipo_compra: str = "CONTADO",
        observaciones: Optional[str] = None,
        usuario_id: Optional[int] = None,
        compra_id: Optional[int] = None,
        monto_pagado_inicial: Any = 0,
        tipo_pago_inicial: Optional[str] = None,
        numero_comprobante_inicial: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[int]]:
        if not proveedor_id:
            return False, "Seleccione un proveedor", None
        proveedor = self.proveedores_repo.obtener_por_id(proveedor_id)
        if not proveedor:
            return False, "Proveedor no encontrado", None
        try:
            lines, total = self._normalized_lines(productos)
        except (PackagingConversionBlocked, PackagingError, PurchaseCartError) as exc:
            return False, str(exc), None
        usuario_id = usuario_id if usuario_id is not None else self._usuario_id()
        conn = self.db.conectar()
        try:
            if compra_id is not None:
                row = conn.execute(
                    "SELECT id, estado, inventory_command_id FROM compras WHERE id = ?",
                    (compra_id,),
                ).fetchone()
                if not row:
                    return False, "Borrador no encontrado", None
                estado = str(row["estado"] or "").upper()
                if estado == ESTADO_COMPLETADA:
                    return False, COMPLETED_IMMUTABLE, None
                if estado == ESTADO_CANCELADA:
                    return False, "No se puede editar una compra cancelada", None
                if estado != ESTADO_DRAFT:
                    return False, COMPLETED_IMMUTABLE, None
                if row["inventory_command_id"]:
                    return False, (
                        "Recepción en vuelo: no edite el borrador; "
                        "reintente CONFIRMAR RECEPCIÓN con la misma identidad"
                    ), None
                conn.execute(
                    """
                    UPDATE compras SET
                        proveedor_id = ?, numero_factura = ?, tipo_compra = ?,
                        total = ?, observaciones = ?, usuario_id = ?,
                        saldo_pendiente = ?
                    WHERE id = ?
                    """,
                    (
                        proveedor_id,
                        numero_factura,
                        tipo_compra,
                        sqlite_number(total),
                        observaciones,
                        usuario_id,
                        sqlite_number(total),
                        compra_id,
                    ),
                )
                conn.execute("DELETE FROM detalle_compras WHERE compra_id = ?", (compra_id,))
            else:
                conn.execute(
                    """
                    INSERT INTO compras (
                        proveedor_id, numero_factura, fecha, tipo_compra,
                        total, observaciones, usuario_id, estado,
                        estado_pago, monto_pagado, saldo_pendiente
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        proveedor_id,
                        numero_factura,
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        tipo_compra,
                        sqlite_number(total),
                        observaciones,
                        usuario_id,
                        ESTADO_DRAFT,
                        "PENDIENTE",
                        0,
                        sqlite_number(total),
                    ),
                )
                compra_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            from local_first_db import ensure_local_id
            from repositories._outbox import encolar

            ensure_local_id(conn, "compras", compra_id)
            encolar(conn, "purchase", compra_id, "create", "compras")
            for item in lines:
                conn.execute(
                    """
                    INSERT INTO detalle_compras (
                        compra_id, producto_id, cantidad, precio_unitario, subtotal,
                        package_role, cantidad_presentacion, supplier_alias
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        compra_id,
                        item["producto_id"],
                        item["cantidad"],
                        item["precio_unitario"],
                        item["subtotal"],
                        item["package_role"],
                        item["cantidad_presentacion"],
                        item["supplier_alias"],
                    ),
                )
                encolar(conn, "purchase_detail", conn.execute(
                    "SELECT last_insert_rowid()"
                ).fetchone()[0], "create", "detalle_compras")
            conn.commit()
            return True, "Borrador guardado", int(compra_id)
        except Exception as exc:
            conn.rollback()
            return False, f"Error al guardar borrador: {exc}", None
        finally:
            conn.close()

    def eliminar_borrador(self, compra_id: int) -> Tuple[bool, str]:
        conn = self.db.conectar()
        try:
            row = conn.execute(
                "SELECT estado FROM compras WHERE id = ?", (compra_id,)
            ).fetchone()
            if not row:
                return False, "Borrador no encontrado"
            if str(row["estado"] or "").upper() != ESTADO_DRAFT:
                return False, COMPLETED_IMMUTABLE
            conn.execute("DELETE FROM detalle_compras WHERE compra_id = ?", (compra_id,))
            conn.execute("DELETE FROM compras WHERE id = ?", (compra_id,))
            conn.commit()
            return True, "Borrador eliminado"
        except Exception as exc:
            conn.rollback()
            return False, str(exc)
        finally:
            conn.close()

    def confirmar_recepcion(
        self,
        *,
        proveedor_id: Optional[int] = None,
        productos: Optional[List[dict]] = None,
        numero_factura: Optional[str] = None,
        tipo_compra: str = "CONTADO",
        observaciones: Optional[str] = None,
        usuario_id: Optional[int] = None,
        compra_id: Optional[int] = None,
        monto_pagado_inicial: Any = 0,
        tipo_pago_inicial: Optional[str] = None,
        numero_comprobante_inicial: Optional[str] = None,
        inventory_mode: Optional[str] = None,
        inventory_command_id: Optional[str] = None,
        inventory_gateway=None,
        inventory_transport=None,
        inventory_connection_factory=None,
    ) -> Tuple[bool, str, Optional[int]]:
        if compra_id is None:
            if proveedor_id is None or not productos:
                return False, "Seleccione un proveedor y al menos un producto", None
            ok, msg, compra_id = self.guardar_borrador(
                proveedor_id=proveedor_id,
                productos=productos,
                numero_factura=numero_factura,
                tipo_compra=tipo_compra,
                observaciones=observaciones,
                usuario_id=usuario_id,
            )
            if not ok:
                return False, msg, None
        return self._confirmar_draft(
            int(compra_id),
            inventory_mode=inventory_mode,
            inventory_command_id=inventory_command_id,
            inventory_gateway=inventory_gateway,
            inventory_transport=inventory_transport,
            inventory_connection_factory=inventory_connection_factory,
            monto_pagado_inicial=monto_pagado_inicial,
            tipo_pago_inicial=tipo_pago_inicial,
            numero_comprobante_inicial=numero_comprobante_inicial,
        )

    def _load_draft(self, conn, compra_id: int) -> Optional[Dict[str, Any]]:
        row = conn.execute("SELECT * FROM compras WHERE id = ?", (compra_id,)).fetchone()
        if not row:
            return None
        compra = dict(row)
        detalles = conn.execute(
            "SELECT * FROM detalle_compras WHERE compra_id = ? ORDER BY id",
            (compra_id,),
        ).fetchall()
        compra["productos"] = [dict(item) for item in detalles]
        return compra

    def _confirmar_draft(
        self,
        compra_id: int,
        *,
        inventory_mode,
        inventory_command_id,
        inventory_gateway,
        inventory_transport,
        inventory_connection_factory,
        monto_pagado_inicial,
        tipo_pago_inicial,
        numero_comprobante_inicial,
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
                compra_id,
                inventory_command_id=inventory_command_id,
                inventory_gateway=inventory_gateway,
                inventory_transport=inventory_transport,
                inventory_connection_factory=inventory_connection_factory,
            )
        return self._confirmar_legacy(compra_id)

    def _confirmar_legacy(self, compra_id: int) -> Tuple[bool, str, Optional[int]]:
        from database import obtener_fecha_actual
        from inventory_cutover import commit_legacy_inventory
        from repositories._outbox import encolar

        conn = self.db.conectar()
        try:
            compra = self._load_draft(conn, compra_id)
            if not compra:
                return False, "Borrador no encontrado", None
            estado = str(compra.get("estado") or "").upper()
            if estado == ESTADO_COMPLETADA:
                return True, "Recepción ya confirmada", compra_id
            if estado != ESTADO_DRAFT:
                return False, COMPLETED_IMMUTABLE, None
            try:
                lines, _total = self._normalized_lines(compra["productos"])
            except (PackagingConversionBlocked, PackagingError, PurchaseCartError) as exc:
                return False, str(exc), None
            for item in lines:
                conn.execute(
                    "UPDATE productos SET stock = stock + ? WHERE id = ?",
                    (item["cantidad"], item["producto_id"]),
                )
                conn.execute(
                    """
                    INSERT INTO movimientos (
                        tipo, producto_id, proveedor_id, usuario_id,
                        cantidad, precio_unitario, costo_total,
                        num_factura, observaciones, fecha
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ENTRADA_COMPRA",
                        item["producto_id"],
                        compra["proveedor_id"],
                        compra.get("usuario_id"),
                        item["cantidad"],
                        item["precio_unitario"],
                        item["subtotal"],
                        compra.get("numero_factura"),
                        f"Recepción #{compra_id}",
                        obtener_fecha_actual(),
                    ),
                )
                encolar(conn, "inventory_movement", conn.execute(
                    "SELECT last_insert_rowid()"
                ).fetchone()[0], "create", "movimientos")
                encolar(conn, "product", item["producto_id"], "update", "productos")
            marked = conn.execute(
                "UPDATE compras SET estado = ? WHERE id = ? AND estado = ?",
                (ESTADO_COMPLETADA, compra_id, ESTADO_DRAFT),
            )
            if marked.rowcount != 1:
                conn.rollback()
                row = conn.execute(
                    "SELECT estado FROM compras WHERE id = ?", (compra_id,)
                ).fetchone()
                if row and str(row["estado"] or "").upper() == ESTADO_COMPLETADA:
                    return True, "Recepción ya confirmada", compra_id
                return False, COMPLETED_IMMUTABLE, None
            commit_legacy_inventory(conn)
            return True, "Recepción confirmada", compra_id
        except Exception as exc:
            conn.rollback()
            return False, f"Error al confirmar recepción: {exc}", None
        finally:
            conn.close()

    def _confirmar_authoritative(
        self,
        compra_id: int,
        *,
        inventory_command_id,
        inventory_gateway,
        inventory_transport,
        inventory_connection_factory,
    ) -> Tuple[bool, str, Optional[int]]:
        from database import obtener_fecha_actual
        from inventory_cutover import ACT_KIND_PURCHASE_CREATE
        from inventory_gateway import OUTCOME_APPLIED, OUTCOME_REJECTED
        from inventory_ledger import (
            QuantityScaleError,
            UnknownProductError,
            bind_inventory_command_documento,
        )
        from inventory_writer_support import (
            DOCUMENTO_TIPO_COMPRA,
            MissingProductLocalIdError,
            bind_inventory_gateway,
            build_positive_operations,
            command_already_applied,
            durable_act_command_id,
            notify_after_remote_apply,
            unknown_writer_message,
        )
        from local_first_db import ensure_local_id
        from repositories._outbox import encolar

        conn = self.db.conectar()
        try:
            compra = self._load_draft(conn, compra_id)
            if not compra:
                return False, "Borrador no encontrado", None
            estado = str(compra.get("estado") or "").upper()
            if estado == ESTADO_COMPLETADA:
                self.last_inventory_command_id = compra.get("inventory_command_id")
                return True, "Recepción ya confirmada", compra_id
            if estado != ESTADO_DRAFT:
                return False, COMPLETED_IMMUTABLE, None
            try:
                lines, _total = self._normalized_lines(compra["productos"])
            except (PackagingConversionBlocked, PackagingError, PurchaseCartError) as exc:
                return False, str(exc), None

            compra_local = compra.get("local_id") or ensure_local_id(
                conn, "compras", compra_id
            )
            stored_cmd = compra.get("inventory_command_id") or inventory_command_id
            try:
                command_id = durable_act_command_id(
                    conn,
                    ACT_KIND_PURCHASE_CREATE,
                    act_key=str(compra_local),
                    explicit_command_id=stored_cmd,
                )
            except Exception as exc:
                return False, str(exc), None
            self.last_inventory_command_id = command_id
            conn.execute(
                "UPDATE compras SET inventory_command_id = ?, local_id = ? WHERE id = ?",
                (command_id, compra_local, compra_id),
            )
            conn.commit()

            already = command_already_applied(conn, command_id)
            if already is None:
                try:
                    operations = build_positive_operations(
                        conn, lines, command_id=command_id
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
                        tipo="COMPRA",
                        operations=operations,
                        command_id=command_id,
                        documento_tipo=DOCUMENTO_TIPO_COMPRA,
                        device_id=None,
                        usuario_id=compra.get("usuario_id"),
                    )
                except Exception as exc:
                    return False, unknown_writer_message(command_id, str(exc)), None
                self.last_gateway_result = result
                if result.outcome == OUTCOME_REJECTED:
                    conn.execute(
                        "UPDATE compras SET inventory_command_id = NULL WHERE id = ?",
                        (compra_id,),
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

            bind_inventory_command_documento(conn, command_id, compra_local)
            existing_mov = conn.execute(
                "SELECT COUNT(*) FROM movimientos WHERE observaciones = ?",
                (f"Recepción #{compra_id}",),
            ).fetchone()[0]
            if not existing_mov:
                for item in lines:
                    conn.execute(
                        """
                        INSERT INTO movimientos (
                            tipo, producto_id, proveedor_id, usuario_id,
                            cantidad, precio_unitario, costo_total,
                            num_factura, observaciones, fecha
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "ENTRADA_COMPRA",
                            item["producto_id"],
                            compra["proveedor_id"],
                            compra.get("usuario_id"),
                            item["cantidad"],
                            item["precio_unitario"],
                            item["subtotal"],
                            compra.get("numero_factura"),
                            f"Recepción #{compra_id}",
                            obtener_fecha_actual(),
                        ),
                    )
                    encolar(
                        conn,
                        "inventory_movement",
                        conn.execute("SELECT last_insert_rowid()").fetchone()[0],
                        "create",
                        "movimientos",
                    )
            conn.execute(
                "UPDATE compras SET estado = ? WHERE id = ? AND estado = ?",
                (ESTADO_COMPLETADA, compra_id, ESTADO_DRAFT),
            )
            conn.commit()
            return True, "Recepción confirmada", compra_id
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            cid = self.last_inventory_command_id or inventory_command_id or "?"
            from inventory_writer_support import unknown_writer_message

            return False, unknown_writer_message(str(cid), str(exc)), None
        finally:
            conn.close()
