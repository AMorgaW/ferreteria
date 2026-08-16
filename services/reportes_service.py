# -*- coding: utf-8 -*-
"""Reportes y analítica local-first (Fase 4A).

Cantidad actual: inventory_reporting_adapter (inventory_balances local).
Dinero: Decimal. Caja: cash_movements / CajaService.
Ventas/compras: documentos COMPLETED; DRAFT/REJECTED no cuentan.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

import schema_bootstrap
from cash_schema import (
    KIND_CUSTOMER_PAYMENT,
    KIND_EXPENSE,
    KIND_REFUND,
    KIND_SUPPLIER_PAYMENT,
    METHOD_CASH,
    METHOD_CARD_CREDIT,
    METHOD_CARD_DEBIT,
    METHOD_CREDIT,
    METHOD_TRANSFER,
    normalize_payment_method,
)
from returns_schema import (
    ESTADO_COMPLETED,
    KIND_CUSTOMER_RETURN,
    KIND_SALE_VOID,
    KIND_SUPPLIER_RETURN,
)
from services.caja_service import compute_period_cash_summary, money
from services.inventory_reporting_adapter import (
    inventory_by_product_id,
    list_reporting_inventory,
    load_quantity_scaled_index,
    productos_stock_critico as adapter_stock_critico,
)

SALES_COMPLETED_SQL = (
    "UPPER(COALESCE({alias}.estado, 'COMPLETADA')) IN ('COMPLETADA', 'COMPLETED')"
)
SALES_EXCLUDED_SQL = (
    "UPPER(COALESCE({alias}.estado, '')) NOT IN "
    "('DRAFT', 'REJECTED', 'ANULADA', 'CANCELADA')"
)
PURCHASES_COMPLETED_SQL = (
    "UPPER(COALESCE({alias}.estado, '')) IN ('COMPLETADA', 'COMPLETED')"
)
COST_BASIS_LEGACY = "LEGACY_UNVERIFIED"
COST_BASIS_ESTIMATED = "ESTIMATED"


def _as_money(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0.00")
    return money(value)


def _as_qty(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(str(value))


def _row_dict(row) -> dict:
    if row is None:
        return {}
    if isinstance(row, dict):
        return row
    try:
        return dict(row)
    except Exception:
        return {}


def _local_date(column: str) -> str:
    return f"DATE(datetime({column}, 'localtime'))"


def _date_range_sql(column: str) -> str:
    expr = _local_date(column)
    return f"{expr} >= DATE(?) AND {expr} <= DATE(?)"


def _today() -> str:
    return date.today().isoformat()


def _month_start() -> str:
    return date.today().replace(day=1).isoformat()


class ReportesService:
    """Servicio para generar reportes y estadísticas."""

    def __init__(self, db_manager):
        self.db = db_manager

    def _connect(self):
        return self.db.conectar()

    def _has_table(self, conn, name: str) -> bool:
        return schema_bootstrap.table_exists(conn, name)

    def _has_column(self, conn, table: str, column: str) -> bool:
        return schema_bootstrap.column_exists(conn, table, column)

    def _sale_qty_expr(self, conn, alias: str = "dv") -> str:
        if self._has_column(conn, "detalle_ventas", "cantidad_base"):
            return f"COALESCE({alias}.cantidad_base, {alias}.cantidad)"
        return f"{alias}.cantidad"

    def _completed_sales_where(self, alias: str = "v") -> str:
        return (
            SALES_COMPLETED_SQL.format(alias=alias)
            + " AND "
            + SALES_EXCLUDED_SQL.format(alias=alias)
        )

    def _sum_reversals(
        self,
        conn,
        fecha_inicio: str,
        fecha_fin: str,
        kinds: tuple,
        *,
        amount: bool = True,
        product_id: Optional[int] = None,
    ) -> Decimal:
        if not self._has_table(conn, "reversal_documents"):
            return Decimal("0.00") if amount else Decimal("0")
        placeholders = ",".join("?" for _ in kinds)
        qty_col = "l.cantidad_base" if self._has_column(
            conn, "reversal_lines", "cantidad_base"
        ) else "l.cantidad_presentacion"
        select = f"COALESCE(SUM(l.subtotal), 0)" if amount else f"COALESCE(SUM({qty_col}), 0)"
        sql = f"""
            SELECT {select} AS total
              FROM reversal_lines l
              JOIN reversal_documents d ON d.id = l.reversal_id
             WHERE UPPER(COALESCE(d.estado, '')) = ?
               AND d.kind IN ({placeholders})
               AND {_date_range_sql('d.fecha')}
        """
        params: list = [ESTADO_COMPLETED, *kinds, fecha_inicio, fecha_fin]
        if product_id is not None:
            sql += " AND l.producto_id = ?"
            params.append(product_id)
        row = conn.execute(sql, params).fetchone()
        value = _row_dict(row).get("total") or 0
        return _as_money(value) if amount else _as_qty(value)

    def _gross_sales(self, conn, fecha_inicio: str, fecha_fin: str, usuario_id=None) -> dict:
        sql = f"""
            SELECT COUNT(*) AS total_ventas,
                   COALESCE(SUM(v.total), 0) AS monto_total,
                   COALESCE(SUM(v.subtotal), 0) AS subtotal_total,
                   COALESCE(SUM(v.descuento), 0) AS descuento_total,
                   COALESCE(SUM(v.iva), 0) AS iva_total,
                   COALESCE(AVG(v.total), 0) AS promedio_venta
              FROM ventas v
             WHERE {self._completed_sales_where('v')}
               AND {_date_range_sql('v.fecha')}
        """
        params: list = [fecha_inicio, fecha_fin]
        if usuario_id is not None:
            sql += " AND v.usuario_id = ?"
            params.append(usuario_id)
        row = _row_dict(conn.execute(sql, params).fetchone())
        count = int(row.get("total_ventas") or 0)
        gross = _as_money(row.get("monto_total"))
        return {
            "total_ventas": count,
            "gross_sales": gross,
            "subtotal_total": _as_money(row.get("subtotal_total")),
            "descuento_total": _as_money(row.get("descuento_total")),
            "iva_total": _as_money(row.get("iva_total")),
            "promedio_bruto": _as_money(row.get("promedio_venta")),
        }

    def _sales_breakdown(self, conn, fecha_inicio: str, fecha_fin: str, usuario_id=None) -> dict:
        gross = self._gross_sales(conn, fecha_inicio, fecha_fin, usuario_id)
        customer_returns = self._sum_reversals(
            conn, fecha_inicio, fecha_fin, (KIND_CUSTOMER_RETURN,)
        )
        sale_voids = self._sum_reversals(
            conn, fecha_inicio, fecha_fin, (KIND_SALE_VOID,)
        )
        returns_total = customer_returns + sale_voids
        net = gross["gross_sales"] - returns_total
        count = gross["total_ventas"]
        promedio = (net / count) if count else Decimal("0.00")
        return {
            **gross,
            "customer_returns": customer_returns,
            "sale_voids": sale_voids,
            "returns_sales": returns_total,
            "net_sales": net,
            "monto_total": net,
            "promedio_venta": promedio.quantize(Decimal("0.01")) if count else Decimal("0.00"),
        }

    def dashboard_principal(self, usuario_id=None) -> Dict:
        conn = self._connect()
        try:
            hoy = _today()
            mes_inicio = _month_start()
            hoy_stats = self._sales_breakdown(conn, hoy, hoy, usuario_id)
            mes_stats = self._sales_breakdown(conn, mes_inicio, hoy, usuario_id)
            criticos = adapter_stock_critico(conn)
            quantity_source = load_quantity_scaled_index(conn)[1]
            cuentas = {"cuentas_pendientes": 0, "monto_pendiente": Decimal("0.00")}
            if self._has_table(conn, "cuentas_por_cobrar"):
                row = _row_dict(conn.execute(
                    """
                    SELECT COUNT(*) AS cuentas,
                           COALESCE(SUM(saldo_pendiente), 0) AS monto
                      FROM cuentas_por_cobrar
                     WHERE estado = 'PENDIENTE'
                    """
                ).fetchone())
                cuentas = {
                    "cuentas_pendientes": int(row.get("cuentas") or 0),
                    "monto_pendiente": _as_money(row.get("monto")),
                }
            uid_sql = " AND v.usuario_id = ?" if usuario_id is not None else ""
            params = [usuario_id] if usuario_id is not None else []
            graf_rows = conn.execute(
                f"""
                SELECT {_local_date('v.fecha')} AS fecha,
                       COALESCE(SUM(v.total), 0) AS monto
                  FROM ventas v
                 WHERE {_local_date('v.fecha')} >= DATE('now', 'localtime', '-6 days')
                   AND {self._completed_sales_where('v')}
                   {uid_sql}
                 GROUP BY {_local_date('v.fecha')}
                 ORDER BY fecha
                """,
                params,
            ).fetchall()
            dias = {
                (date.today() - timedelta(days=i)).isoformat(): Decimal("0.00")
                for i in range(6, -1, -1)
            }
            for raw in graf_rows:
                row = _row_dict(raw)
                if row.get("fecha") in dias:
                    dias[row["fecha"]] = _as_money(row.get("monto"))
            return {
                "ventas_hoy": {
                    "ventas_hoy": hoy_stats["total_ventas"],
                    "monto_hoy": hoy_stats["net_sales"],
                    "gross_hoy": hoy_stats["gross_sales"],
                    "returns_hoy": hoy_stats["returns_sales"],
                },
                "ventas_mes": {
                    "ventas_mes": mes_stats["total_ventas"],
                    "monto_mes": mes_stats["net_sales"],
                    "gross_mes": mes_stats["gross_sales"],
                    "returns_mes": mes_stats["returns_sales"],
                },
                "stock_critico": len(criticos),
                "stock_critico_source": quantity_source,
                "cuentas_cobrar": cuentas,
                "grafico_7_dias": [{"fecha": f, "monto": m} for f, m in dias.items()],
            }
        finally:
            conn.close()

    def detalle_ventas_hoy(self, usuario_id=None) -> dict:
        conn = self._connect()
        try:
            hoy = _today()
            uid_filter = "AND v.usuario_id = ?" if usuario_id is not None else ""
            params = [hoy, usuario_id] if usuario_id is not None else [hoy]
            ventas = [
                _row_dict(r)
                for r in conn.execute(
                    f"""
                    SELECT TIME(datetime(v.fecha,'localtime')) AS hora,
                           COALESCE(c.nombre,'Consumidor Final') AS cliente,
                           v.metodo_pago, v.total, v.monto_pagado,
                           v.estado_pago, u.nombre_completo AS vendedor
                      FROM ventas v
                      LEFT JOIN clientes c ON v.cliente_id = c.id
                      LEFT JOIN usuarios u ON v.usuario_id = u.id
                     WHERE {_local_date('v.fecha')} = DATE(?)
                       AND {self._completed_sales_where('v')}
                       {uid_filter}
                     ORDER BY v.fecha DESC
                    """,
                    params,
                ).fetchall()
            ]
            for venta in ventas:
                venta["total"] = _as_money(venta.get("total"))
                venta["monto_pagado"] = _as_money(venta.get("monto_pagado"))
            por_metodo = self._metodos_pago_rows(conn, hoy, hoy, usuario_id)
            return {"ventas": ventas, "por_metodo": por_metodo}
        finally:
            conn.close()

    def detalle_ventas_mes(self, usuario_id=None) -> dict:
        conn = self._connect()
        try:
            uid_filter = "AND usuario_id = ?" if usuario_id is not None else ""
            params = (usuario_id,) if usuario_id is not None else ()
            por_dia = [
                _row_dict(r)
                for r in conn.execute(
                    f"""
                    SELECT {_local_date('fecha')} AS fecha,
                           COUNT(*) AS cantidad,
                           COALESCE(SUM(total), 0) AS monto
                      FROM ventas
                     WHERE strftime('%Y-%m', datetime(fecha,'localtime'))
                           = strftime('%Y-%m','now','localtime')
                       AND {self._completed_sales_where('ventas')}
                       {uid_filter}
                     GROUP BY {_local_date('fecha')}
                     ORDER BY fecha
                    """,
                    params,
                ).fetchall()
            ]
            for item in por_dia:
                item["monto"] = _as_money(item.get("monto"))
            hoy = _today()
            por_metodo = self._metodos_pago_rows(conn, _month_start(), hoy, usuario_id)
            return {"por_dia": por_dia, "por_metodo": por_metodo}
        finally:
            conn.close()

    def reporte_ventas_periodo(self, fecha_inicio: str, fecha_fin: str) -> Dict:
        conn = self._connect()
        try:
            ventas = [
                _row_dict(r)
                for r in conn.execute(
                    f"""
                    SELECT v.*, c.nombre AS cliente_nombre, u.nombre_completo AS vendedor
                      FROM ventas v
                      LEFT JOIN clientes c ON v.cliente_id = c.id
                      LEFT JOIN usuarios u ON v.usuario_id = u.id
                     WHERE {self._completed_sales_where('v')}
                       AND {_date_range_sql('v.fecha')}
                     ORDER BY v.fecha DESC
                    """,
                    (fecha_inicio, fecha_fin),
                ).fetchall()
            ]
            for venta in ventas:
                for key in ("total", "subtotal", "descuento", "iva", "monto_pagado"):
                    if key in venta:
                        venta[key] = _as_money(venta.get(key))
            resumen = self._sales_breakdown(conn, fecha_inicio, fecha_fin)
            por_metodo = self._metodos_pago_rows(conn, fecha_inicio, fecha_fin)
            return {
                "fecha_inicio": fecha_inicio,
                "fecha_fin": fecha_fin,
                "ventas": ventas,
                "resumen": resumen,
                "por_metodo_pago": por_metodo,
            }
        finally:
            conn.close()

    def detalle_venta_lineas(self, venta_id: int) -> List[Dict]:
        conn = self._connect()
        try:
            qty = self._sale_qty_expr(conn)
            rows = conn.execute(
                f"""
                SELECT p.nombre, {qty} AS cantidad, dv.precio_unitario,
                       dv.descuento, dv.subtotal
                  FROM detalle_ventas dv
                  JOIN productos p ON dv.producto_id = p.id
                 WHERE dv.venta_id = ?
                 ORDER BY dv.id
                """,
                (venta_id,),
            ).fetchall()
            result = []
            for raw in rows:
                row = _row_dict(raw)
                result.append(
                    {
                        "nombre": row.get("nombre"),
                        "cantidad": _as_qty(row.get("cantidad")),
                        "precio_unitario": _as_money(row.get("precio_unitario")),
                        "descuento": _as_money(row.get("descuento")),
                        "subtotal": _as_money(row.get("subtotal")),
                    }
                )
            return result
        finally:
            conn.close()

    def reporte_productos_mas_vendidos(
        self, fecha_inicio: str, fecha_fin: str, limite: int = 20
    ) -> Dict:
        conn = self._connect()
        try:
            qty_expr = self._sale_qty_expr(conn)
            breakdown = self._sales_breakdown(conn, fecha_inicio, fecha_fin)
            total_ingresos = breakdown["net_sales"] or Decimal("0.01")
            sold_rows = conn.execute(
                f"""
                SELECT p.id, p.nombre, p.categoria, p.marca, p.unidad_medida,
                       p.permite_decimales,
                       COALESCE(SUM({qty_expr}), 0) AS gross_quantity,
                       COALESCE(SUM(dv.subtotal), 0) AS gross_amount,
                       COUNT(DISTINCT dv.venta_id) AS num_ventas
                  FROM detalle_ventas dv
                  JOIN productos p ON dv.producto_id = p.id
                  JOIN ventas v ON dv.venta_id = v.id
                 WHERE {self._completed_sales_where('v')}
                   AND {_date_range_sql('v.fecha')}
                 GROUP BY p.id
                """,
                (fecha_inicio, fecha_fin),
            ).fetchall()
            returned = {}
            returned_amount = {}
            if self._has_table(conn, "reversal_documents"):
                qty_col = (
                    "l.cantidad_base"
                    if self._has_column(conn, "reversal_lines", "cantidad_base")
                    else "l.cantidad_presentacion"
                )
                for raw in conn.execute(
                    f"""
                    SELECT l.producto_id,
                           COALESCE(SUM({qty_col}), 0) AS returned_quantity,
                           COALESCE(SUM(l.subtotal), 0) AS returned_amount
                      FROM reversal_lines l
                      JOIN reversal_documents d ON d.id = l.reversal_id
                     WHERE UPPER(COALESCE(d.estado, '')) = ?
                       AND d.kind IN (?, ?)
                       AND {_date_range_sql('d.fecha')}
                     GROUP BY l.producto_id
                    """,
                    (
                        ESTADO_COMPLETED,
                        KIND_CUSTOMER_RETURN,
                        KIND_SALE_VOID,
                        fecha_inicio,
                        fecha_fin,
                    ),
                ).fetchall():
                    row = _row_dict(raw)
                    returned[row["producto_id"]] = _as_qty(row.get("returned_quantity"))
                    returned_amount[row["producto_id"]] = _as_money(row.get("returned_amount"))
            inventory = inventory_by_product_id(conn)
            productos = []
            for raw in sold_rows:
                row = _row_dict(raw)
                pid = row["id"]
                gross_q = _as_qty(row.get("gross_quantity"))
                ret_q = returned.get(pid, Decimal("0"))
                net_q = gross_q - ret_q
                gross_a = _as_money(row.get("gross_amount"))
                ret_a = returned_amount.get(pid, Decimal("0.00"))
                net_a = gross_a - ret_a
                inv = inventory.get(pid, {})
                stock = inv.get("cantidad_actual", Decimal("0"))
                stock_min = inv.get("stock_minimo", Decimal("0"))
                if stock <= 0:
                    estado = "AGOTADO"
                elif stock <= stock_min:
                    estado = "BAJO"
                else:
                    estado = "OK"
                productos.append(
                    {
                        "id": pid,
                        "nombre": row.get("nombre"),
                        "categoria": row.get("categoria"),
                        "marca": row.get("marca"),
                        "unidad_medida": row.get("unidad_medida") or inv.get("unidad_base"),
                        "permite_decimales": row.get("permite_decimales"),
                        "gross_quantity": gross_q,
                        "returned_quantity": ret_q,
                        "net_quantity": net_q,
                        "cantidad_vendida": net_q,
                        "gross_amount": gross_a,
                        "returned_amount": ret_a,
                        "monto_total": net_a,
                        "num_ventas": int(row.get("num_ventas") or 0),
                        "stock": stock,
                        "stock_minimo": stock_min,
                        "estado_stock": estado,
                        "quantity_source": inv.get("quantity_source"),
                        "porcentaje_ingresos": round(
                            float((net_a / total_ingresos) * 100) if total_ingresos else 0,
                            1,
                        ),
                    }
                )
            productos.sort(key=lambda p: p["net_quantity"], reverse=True)
            productos = productos[:limite]
            cat_row = conn.execute(
                f"""
                SELECT p.categoria, SUM(dv.subtotal) AS total_cat
                  FROM detalle_ventas dv
                  JOIN productos p ON dv.producto_id = p.id
                  JOIN ventas v ON dv.venta_id = v.id
                 WHERE {self._completed_sales_where('v')}
                   AND {_date_range_sql('v.fecha')}
                 GROUP BY p.categoria
                 ORDER BY total_cat DESC
                 LIMIT 1
                """,
                (fecha_inicio, fecha_fin),
            ).fetchone()
            categoria_top = _row_dict(cat_row) if cat_row else {"categoria": "-", "total_cat": 0}
            if "total_cat" in categoria_top:
                categoria_top["total_cat"] = _as_money(categoria_top.get("total_cat"))
            total_unidades = sum((p["net_quantity"] for p in productos), Decimal("0"))
            return {
                "productos": productos,
                "producto_estrella": productos[0] if productos else None,
                "categoria_top": categoria_top,
                "total_unidades": total_unidades,
                "total_ingresos": breakdown["net_sales"],
            }
        finally:
            conn.close()

    def reporte_inventario_actual(self) -> List[Dict]:
        conn = self._connect()
        try:
            return list_reporting_inventory(conn, solo_activos=True)
        finally:
            conn.close()

    def productos_stock_critico(self) -> List[Dict]:
        conn = self._connect()
        try:
            return adapter_stock_critico(conn)
        finally:
            conn.close()

    def reporte_clientes_top(self, limite: int = 20) -> List[Dict]:
        conn = self._connect()
        try:
            rows = conn.execute(
                f"""
                SELECT c.id, c.nombre, c.numero_documento, c.telefono,
                       COUNT(v.id) AS total_compras,
                       COALESCE(SUM(v.total), 0) AS monto_total,
                       COALESCE(AVG(v.total), 0) AS promedio_compra,
                       c.saldo_pendiente
                  FROM clientes c
                  LEFT JOIN ventas v ON c.id = v.cliente_id
                   AND {self._completed_sales_where('v')}
                 WHERE c.activo = 1
                 GROUP BY c.id
                 ORDER BY monto_total DESC
                 LIMIT ?
                """,
                (limite,),
            ).fetchall()
            result = []
            for raw in rows:
                row = _row_dict(raw)
                row["monto_total"] = _as_money(row.get("monto_total"))
                row["promedio_compra"] = _as_money(row.get("promedio_compra"))
                row["saldo_pendiente"] = _as_money(row.get("saldo_pendiente") or 0)
                result.append(row)
            return result
        finally:
            conn.close()

    def reporte_movimientos_inventario(self, fecha_inicio: str, fecha_fin: str) -> List[Dict]:
        conn = self._connect()
        try:
            rows = conn.execute(
                f"""
                SELECT m.*, p.nombre AS producto_nombre,
                       pr.nombre AS proveedor_nombre,
                       u.nombre_completo AS usuario_nombre
                  FROM movimientos m
                  JOIN productos p ON m.producto_id = p.id
                  LEFT JOIN proveedores pr ON m.proveedor_id = pr.id
                  LEFT JOIN usuarios u ON m.usuario_id = u.id
                 WHERE {_date_range_sql('m.fecha')}
                 ORDER BY m.fecha DESC
                """,
                (fecha_inicio, fecha_fin),
            ).fetchall()
            return [_row_dict(row) for row in rows]
        finally:
            conn.close()

    def _estimated_cogs(self, conn, fecha_inicio: str, fecha_fin: str) -> Decimal:
        qty_expr = self._sale_qty_expr(conn)
        row = _row_dict(
            conn.execute(
                f"""
                SELECT COALESCE(SUM(({qty_expr}) * p.precio_compra), 0) AS costo_ventas
                  FROM detalle_ventas dv
                  JOIN productos p ON dv.producto_id = p.id
                  JOIN ventas v ON dv.venta_id = v.id
                 WHERE {self._completed_sales_where('v')}
                   AND {_date_range_sql('v.fecha')}
                """,
                (fecha_inicio, fecha_fin),
            ).fetchone()
        )
        sold_cost = _as_money(row.get("costo_ventas"))
        returned_cost = Decimal("0.00")
        if self._has_table(conn, "reversal_documents"):
            qty_col = (
                "l.cantidad_base"
                if self._has_column(conn, "reversal_lines", "cantidad_base")
                else "l.cantidad_presentacion"
            )
            ret = _row_dict(
                conn.execute(
                    f"""
                    SELECT COALESCE(SUM(({qty_col}) * p.precio_compra), 0) AS costo
                      FROM reversal_lines l
                      JOIN reversal_documents d ON d.id = l.reversal_id
                      JOIN productos p ON p.id = l.producto_id
                     WHERE UPPER(COALESCE(d.estado, '')) = ?
                       AND d.kind IN (?, ?)
                       AND {_date_range_sql('d.fecha')}
                    """,
                    (
                        ESTADO_COMPLETED,
                        KIND_CUSTOMER_RETURN,
                        KIND_SALE_VOID,
                        fecha_inicio,
                        fecha_fin,
                    ),
                ).fetchone()
            )
            returned_cost = _as_money(ret.get("costo"))
        return sold_cost - returned_cost

    def reporte_rentabilidad(self, fecha_inicio: str, fecha_fin: str) -> Dict:
        conn = self._connect()
        try:
            breakdown = self._sales_breakdown(conn, fecha_inicio, fecha_fin)
            ingresos = breakdown["net_sales"]
            # Fase 4A no dispone de un snapshot durable de costo por línea.
            # _estimated_cogs usa el precio de compra actual y nunca puede
            # presentarse como rentabilidad histórica exacta.
            cost_basis = COST_BASIS_LEGACY
            profitability_contract = COST_BASIS_ESTIMATED
            costo = self._estimated_cogs(conn, fecha_inicio, fecha_fin)
            utilidad = ingresos - costo
            margen = (utilidad / ingresos * 100) if ingresos > 0 else Decimal("0")
            return {
                "ingresos_ventas": ingresos,
                "gross_sales": breakdown["gross_sales"],
                "returns_sales": breakdown["returns_sales"],
                "net_sales": ingresos,
                "costo_ventas": costo,
                "utilidad_bruta": utilidad,
                "margen_utilidad": margen,
                "cost_basis": cost_basis,
                "profitability_contract": profitability_contract,
            }
        finally:
            conn.close()

    def reporte_cuentas_por_cobrar(self) -> List[Dict]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT cpc.*, c.nombre AS cliente_nombre, c.numero_documento,
                       c.telefono, v.numero_factura, v.fecha AS fecha_venta,
                       julianday('now') - julianday(v.fecha) AS dias_vencidos
                  FROM cuentas_por_cobrar cpc
                  JOIN clientes c ON cpc.cliente_id = c.id
                  JOIN ventas v ON cpc.venta_id = v.id
                 WHERE cpc.estado = 'PENDIENTE'
                   AND v.estado_pago != 'PAGADO'
                 ORDER BY v.fecha ASC
                """
            ).fetchall()
            result = []
            for raw in rows:
                row = _row_dict(raw)
                for key in ("monto_total", "monto_pagado", "saldo_pendiente"):
                    if key in row:
                        row[key] = _as_money(row.get(key))
                result.append(row)
            return result
        finally:
            conn.close()

    def productos_mas_vendidos(self) -> Dict:
        hoy = datetime.now()
        inicio = (hoy - timedelta(days=30)).strftime("%Y-%m-%d")
        fin = hoy.strftime("%Y-%m-%d")
        productos = self.reporte_productos_mas_vendidos(inicio, fin, 20)
        return {"periodo": f"{inicio} a {fin}", "top_productos": productos}

    def _metodos_pago_rows(self, conn, fecha_inicio: str, fecha_fin: str, usuario_id=None) -> List[Dict]:
        sql = f"""
            SELECT v.metodo_pago,
                   COUNT(*) AS cantidad_ventas,
                   COALESCE(SUM(v.total), 0) AS monto_total,
                   COALESCE(SUM(v.monto_pagado), 0) AS monto_cobrado,
                   COALESCE(AVG(v.total), 0) AS promedio_venta
              FROM ventas v
             WHERE {self._completed_sales_where('v')}
               AND {_date_range_sql('v.fecha')}
        """
        params: list = [fecha_inicio, fecha_fin]
        if usuario_id is not None:
            sql += " AND v.usuario_id = ?"
            params.append(usuario_id)
        sql += " GROUP BY v.metodo_pago ORDER BY monto_total DESC"
        rows = []
        for raw in conn.execute(sql, params).fetchall():
            row = _row_dict(raw)
            method = normalize_payment_method(row.get("metodo_pago"))
            facturado = _as_money(row.get("monto_total"))
            cobrado = _as_money(row.get("monto_cobrado"))
            item = {
                "metodo_pago": row.get("metodo_pago"),
                "metodo_normalizado": method,
                "cantidad": int(row.get("cantidad_ventas") or 0),
                "cantidad_ventas": int(row.get("cantidad_ventas") or 0),
                "monto": facturado,
                "monto_total": facturado,
                "monto_cobrado": cobrado,
                "promedio_venta": _as_money(row.get("promedio_venta")),
                "es_efectivo": method == METHOD_CASH,
                "es_caja_fisica": method == METHOD_CASH,
            }
            if method == METHOD_CREDIT:
                item["pendiente"] = facturado - cobrado
                item["cobrado"] = cobrado
            rows.append(item)
        return rows

    def ventas_por_metodo_pago(self, fecha_inicio: str = None, fecha_fin: str = None) -> Dict:
        conn = self._connect()
        try:
            hoy = datetime.now()
            if not fecha_inicio:
                fecha_inicio = (hoy - timedelta(days=30)).strftime("%Y-%m-%d")
            if not fecha_fin:
                fecha_fin = hoy.strftime("%Y-%m-%d")
            metodos = self._metodos_pago_rows(conn, fecha_inicio, fecha_fin)
            breakdown = self._sales_breakdown(conn, fecha_inicio, fecha_fin)
            total_monto = breakdown["gross_sales"] or Decimal("0.01")
            total_ventas = breakdown["total_ventas"] or 1
            for item in metodos:
                item["porcentaje_monto"] = round(
                    float((item["monto_total"] / total_monto) * 100), 1
                )
                item["porcentaje_ventas"] = round(
                    (item["cantidad_ventas"] / total_ventas) * 100, 1
                )
            metodo_predominante = metodos[0]["metodo_pago"] if metodos else "-"
            pct_predominante = metodos[0].get("porcentaje_monto", 0) if metodos else 0
            d_inicio = datetime.strptime(fecha_inicio, "%Y-%m-%d")
            d_fin = datetime.strptime(fecha_fin, "%Y-%m-%d")
            duracion = (d_fin - d_inicio).days
            ant_fin = (d_inicio - timedelta(days=1)).strftime("%Y-%m-%d")
            ant_inicio = (d_inicio - timedelta(days=duracion + 1)).strftime("%Y-%m-%d")
            anterior = {
                row["metodo_pago"]: _as_money(row["monto_total"])
                for row in self._metodos_pago_rows(conn, ant_inicio, ant_fin)
            }
            for item in metodos:
                monto_ant = anterior.get(item["metodo_pago"], Decimal("0.00"))
                if monto_ant > 0:
                    item["variacion"] = round(
                        float(((item["monto_total"] - monto_ant) / monto_ant) * 100), 1
                    )
                else:
                    item["variacion"] = None
            credito_info = {}
            cred_row = _row_dict(
                conn.execute(
                    f"""
                    SELECT COUNT(*) AS facturas_total,
                           COALESCE(SUM(total), 0) AS total_facturado,
                           COALESCE(SUM(monto_pagado), 0) AS total_cobrado,
                           COUNT(CASE WHEN estado_pago = 'PAGADO' THEN 1 END) AS facturas_pagadas
                      FROM ventas v
                     WHERE {self._completed_sales_where('v')}
                       AND UPPER(COALESCE(v.metodo_pago, '')) = 'CREDITO'
                       AND {_date_range_sql('v.fecha')}
                    """,
                    (fecha_inicio, fecha_fin),
                ).fetchone()
            )
            if cred_row and int(cred_row.get("facturas_total") or 0) > 0:
                facturado = _as_money(cred_row.get("total_facturado"))
                cobrado = _as_money(cred_row.get("total_cobrado"))
                pendiente = facturado - cobrado
                fact_total = int(cred_row.get("facturas_total") or 0)
                fact_pagadas = int(cred_row.get("facturas_pagadas") or 0)
                credito_info = {
                    "total_facturado": facturado,
                    "total_cobrado": cobrado,
                    "pendiente": max(pendiente, Decimal("0.00")),
                    "facturas_total": fact_total,
                    "facturas_pagadas": fact_pagadas,
                    "facturas_pendientes": fact_total - fact_pagadas,
                    "pct_cobrado": round(
                        float((cobrado / facturado) * 100) if facturado > 0 else 0, 1
                    ),
                }
                for item in metodos:
                    if normalize_payment_method(item["metodo_pago"]) == METHOD_CREDIT:
                        item["pendiente"] = credito_info["pendiente"]
                        item["cobrado"] = credito_info["total_cobrado"]
                        item["pct_cobrado"] = credito_info["pct_cobrado"]
            efectivo_fisico = Decimal("0.00")
            no_efectivo = Decimal("0.00")
            for item in metodos:
                method = item["metodo_normalizado"]
                if method == METHOD_CASH:
                    efectivo_fisico += item["monto_total"]
                elif method == METHOD_CREDIT:
                    continue
                else:
                    no_efectivo += item["monto_total"]
            return {
                "fecha_inicio": fecha_inicio,
                "fecha_fin": fecha_fin,
                "resumen": {
                    "total_ventas": breakdown["total_ventas"],
                    "total_monto": breakdown["gross_sales"],
                    "net_sales": breakdown["net_sales"],
                },
                "por_metodo": metodos,
                "metodo_predominante": metodo_predominante,
                "pct_predominante": pct_predominante,
                "credito_info": credito_info,
                "efectivo_fisico": efectivo_fisico,
                "no_efectivo": no_efectivo,
            }
        finally:
            conn.close()

    def estadisticas_generales(self, fecha_inicio: str = None, fecha_fin: str = None) -> Dict:
        conn = self._connect()
        try:
            inventario = list_reporting_inventory(conn, solo_activos=True)
            quantity_source = (
                inventario[0]["quantity_source"]
                if inventario
                else load_quantity_scaled_index(conn)[1]
            )
            valor_costo = sum((row["valor_inventario"] for row in inventario), Decimal("0.00"))
            valor_venta = sum(
                (row["cantidad_actual"] * row["precio_venta"] for row in inventario),
                Decimal("0.00"),
            )
            hoy = datetime.now()
            inicio_r = fecha_inicio or hoy.replace(day=1).strftime("%Y-%m-%d")
            fin_r = fecha_fin or hoy.strftime("%Y-%m-%d")
            breakdown = self._sales_breakdown(conn, inicio_r, fin_r)
            rentabilidad = self.reporte_rentabilidad(inicio_r, fin_r)
            total_productos = int(
                _row_dict(
                    conn.execute(
                        "SELECT COUNT(*) AS total FROM productos WHERE activo = 1"
                    ).fetchone()
                ).get("total")
                or 0
            )
            total_clientes = int(
                _row_dict(
                    conn.execute(
                        "SELECT COUNT(*) AS total FROM clientes WHERE activo = 1"
                    ).fetchone()
                ).get("total")
                or 0
            )
            total_proveedores = int(
                _row_dict(
                    conn.execute(
                        "SELECT COUNT(*) AS total FROM proveedores WHERE activo = 1"
                    ).fetchone()
                ).get("total")
                or 0
            )
            return {
                "total_productos": total_productos,
                "valor_inventario_costo": valor_costo,
                "valor_inventario_venta": valor_venta,
                "valor_inventario_basis": COST_BASIS_ESTIMATED,
                "quantity_source": quantity_source,
                "total_ventas": breakdown["total_ventas"],
                "monto_total_ventas": breakdown["net_sales"],
                "total_clientes": total_clientes,
                "total_proveedores": total_proveedores,
                "ingresos_mes": rentabilidad["ingresos_ventas"],
                "costos_mes": rentabilidad["costo_ventas"],
                "utilidad_mes": rentabilidad["utilidad_bruta"],
                "margen_mes": rentabilidad["margen_utilidad"],
                "cost_basis": rentabilidad["cost_basis"],
                "profitability_contract": rentabilidad["profitability_contract"],
            }
        finally:
            conn.close()

    def comparativa_periodos(self, inicio1: str, fin1: str, inicio2: str, fin2: str) -> Dict:
        def datos(inicio, fin):
            conn = self._connect()
            try:
                breakdown = self._sales_breakdown(conn, inicio, fin)
                costo = self._estimated_cogs(conn, inicio, fin)
                return {
                    "total_ventas": breakdown["total_ventas"],
                    "monto_total": breakdown["net_sales"],
                    "gross_sales": breakdown["gross_sales"],
                    "returns_sales": breakdown["returns_sales"],
                    "promedio_venta": breakdown["promedio_venta"],
                    "costo_total": costo,
                    "utilidad": breakdown["net_sales"] - costo,
                    "cost_basis": COST_BASIS_LEGACY,
                    "profitability_contract": COST_BASIS_ESTIMATED,
                }
            finally:
                conn.close()

        periodo1 = datos(inicio1, fin1)
        periodo2 = datos(inicio2, fin2)
        variacion = {}
        for key in ("total_ventas", "monto_total", "promedio_venta", "utilidad"):
            val1 = periodo1.get(key, 0) or 0
            val2 = periodo2.get(key, 0) or 0
            if val2:
                variacion[key] = round(float(((val1 - val2) / val2) * 100), 2)
            else:
                variacion[key] = None
        return {"periodo1": periodo1, "periodo2": periodo2, "variacion": variacion}

    def rotacion_inventario(self) -> List[Dict]:
        conn = self._connect()
        try:
            hoy = datetime.now()
            inicio = (hoy - timedelta(days=90)).strftime("%Y-%m-%d")
            fin = hoy.strftime("%Y-%m-%d")
            qty_expr = self._sale_qty_expr(conn)
            inventory = inventory_by_product_id(conn)
            rows = conn.execute(
                f"""
                SELECT p.id, p.nombre,
                       COALESCE(SUM({qty_expr}), 0) AS cantidad_vendida
                  FROM productos p
                  LEFT JOIN detalle_ventas dv ON dv.producto_id = p.id
                  LEFT JOIN ventas v ON v.id = dv.venta_id
                   AND {self._completed_sales_where('v')}
                   AND {_date_range_sql('v.fecha')}
                 WHERE COALESCE(p.activo, 1) = 1
                 GROUP BY p.id
                 ORDER BY cantidad_vendida DESC
                """,
                (inicio, fin),
            ).fetchall()
            result = []
            for raw in rows:
                row = _row_dict(raw)
                inv = inventory.get(row["id"], {})
                stock = inv.get("cantidad_actual", Decimal("0"))
                vendida = _as_qty(row.get("cantidad_vendida"))
                indice = (vendida / stock).quantize(Decimal("0.01")) if stock > 0 else Decimal("0")
                result.append(
                    {
                        "id": row["id"],
                        "nombre": row.get("nombre"),
                        "stock_actual": stock,
                        "cantidad_vendida": vendida,
                        "indice_rotacion": indice,
                        "quantity_source": inv.get("quantity_source"),
                    }
                )
            result.sort(key=lambda x: x["indice_rotacion"], reverse=True)
            return result
        finally:
            conn.close()

    def flujo_caja(self, fecha_inicio: str, fecha_fin: str) -> Dict:
        conn = self._connect()
        try:
            caja = compute_period_cash_summary(conn, fecha_inicio, fecha_fin)
            ingresos_ventas = caja.get("total", Decimal("0.00")) - caja.get(
                "abonos_cliente", Decimal("0.00")
            )
            if ingresos_ventas < 0:
                ingresos_ventas = Decimal("0.00")
            abonos = caja.get("abonos_cliente", Decimal("0.00"))
            ingresos_total = caja.get("cash_in", Decimal("0.00")) + caja.get(
                "total_no_efectivo", Decimal("0.00")
            )
            egresos_compras = caja.get("pagos_proveedor", Decimal("0.00"))
            egresos_gastos = caja.get("egresos_total", Decimal("0.00"))
            gastos_por_categoria = []
            if self._has_table(conn, "cash_movements"):
                for raw in conn.execute(
                    f"""
                    SELECT kind AS categoria, COALESCE(SUM(amount), 0) AS total
                      FROM cash_movements
                     WHERE {_date_range_sql('created_at')}
                       AND kind IN (?, ?, ?)
                     GROUP BY kind
                     ORDER BY total DESC
                    """,
                    (
                        fecha_inicio,
                        fecha_fin,
                        KIND_EXPENSE,
                        KIND_SUPPLIER_PAYMENT,
                        KIND_REFUND,
                    ),
                ).fetchall():
                    row = _row_dict(raw)
                    gastos_por_categoria.append(
                        {
                            "categoria": row.get("categoria"),
                            "total": _as_money(row.get("total")),
                        }
                    )
            ventas_diarias = []
            for raw in conn.execute(
                f"""
                SELECT {_local_date('fecha')} AS dia,
                       COALESCE(SUM(total), 0) AS monto
                  FROM ventas v
                 WHERE {self._completed_sales_where('v')}
                   AND {_date_range_sql('v.fecha')}
                 GROUP BY {_local_date('fecha')}
                 ORDER BY dia
                """,
                (fecha_inicio, fecha_fin),
            ).fetchall():
                row = _row_dict(raw)
                ventas_diarias.append(
                    {"dia": row.get("dia"), "monto": _as_money(row.get("monto"))}
                )
            return {
                "periodo": f"{fecha_inicio} a {fecha_fin}",
                "ingresos": {
                    "ventas": ingresos_ventas,
                    "abonos_cobrados": abonos,
                    "total": ingresos_total,
                },
                "egresos": {
                    "compras": egresos_compras,
                    "gastos": egresos_gastos,
                    "gastos_por_categoria": gastos_por_categoria,
                    "total": egresos_gastos,
                },
                "flujo_neto": caja.get("esperado", Decimal("0.00")),
                "ventas_diarias": ventas_diarias,
                "caja": caja,
                "cash_source": "cash_movements",
            }
        finally:
            conn.close()

    def reporte_dia(self, fecha: str) -> Dict:
        conn = self._connect()
        try:
            metodos = self._metodos_pago_rows(conn, fecha, fecha)
            buckets = {
                "efectivo": Decimal("0.00"),
                "tarjeta": Decimal("0.00"),
                "transferencia": Decimal("0.00"),
                "otros": Decimal("0.00"),
                "credito_nuevo": Decimal("0.00"),
            }
            num_ventas = 0
            for item in metodos:
                num_ventas += item["cantidad_ventas"]
                method = item["metodo_normalizado"]
                if method == METHOD_CASH:
                    buckets["efectivo"] += item["monto_total"]
                elif method in (METHOD_CARD_DEBIT, METHOD_CARD_CREDIT):
                    buckets["tarjeta"] += item["monto_total"]
                elif method == METHOD_TRANSFER:
                    buckets["transferencia"] += item["monto_total"]
                elif method == METHOD_CREDIT:
                    buckets["credito_nuevo"] += item["monto_total"]
                else:
                    buckets["otros"] += item["monto_total"]
            caja = compute_period_cash_summary(conn, fecha, fecha)
            abonos_total = caja.get("abonos_cliente", Decimal("0.00"))
            total_egresos = caja.get("egresos_total", Decimal("0.00"))
            egresos_rows = []
            egresos_cat = []
            if self._has_table(conn, "cash_movements"):
                for raw in conn.execute(
                    f"""
                    SELECT kind AS categoria, descripcion, payment_method AS metodo_pago,
                           amount AS monto
                      FROM cash_movements
                     WHERE {_local_date('created_at')} = DATE(?)
                       AND kind IN (?, ?, ?)
                     ORDER BY kind, amount DESC
                    """,
                    (fecha, KIND_EXPENSE, KIND_SUPPLIER_PAYMENT, KIND_REFUND),
                ).fetchall():
                    row = _row_dict(raw)
                    row["monto"] = _as_money(row.get("monto"))
                    egresos_rows.append(row)
                for raw in conn.execute(
                    f"""
                    SELECT kind AS categoria, COALESCE(SUM(amount), 0) AS total
                      FROM cash_movements
                     WHERE {_local_date('created_at')} = DATE(?)
                       AND kind IN (?, ?, ?)
                     GROUP BY kind
                     ORDER BY total DESC
                    """,
                    (fecha, KIND_EXPENSE, KIND_SUPPLIER_PAYMENT, KIND_REFUND),
                ).fetchall():
                    row = _row_dict(raw)
                    row["total"] = _as_money(row.get("total"))
                    egresos_cat.append(row)
            credito = {}
            pagos = self.ventas_por_metodo_pago(fecha, fecha)
            if pagos.get("credito_info"):
                credito = pagos["credito_info"]
            return {
                "fecha": fecha,
                "num_ventas": num_ventas,
                "efectivo": buckets["efectivo"],
                "tarjeta": buckets["tarjeta"],
                "transferencia": buckets["transferencia"],
                "otros": buckets["otros"],
                "credito_nuevo": buckets["credito_nuevo"],
                "abonos_total": abonos_total,
                "total_egresos": total_egresos,
                "egresos_rows": egresos_rows,
                "egresos_cat": egresos_cat,
                "caja": caja,
                "credito_info": credito,
                "cash_source": "cash_movements",
            }
        finally:
            conn.close()
