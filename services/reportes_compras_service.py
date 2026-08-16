# -*- coding: utf-8 -*-
"""Reportes de compras alineados con recepción 3B / reversos 3C."""
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

import schema_bootstrap
from returns_schema import ESTADO_COMPLETED, KIND_SUPPLIER_RETURN
from services.caja_service import money
from services.reportes_service import PURCHASES_COMPLETED_SQL, _date_range_sql, _local_date


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


class ReportesComprasService:
    """Compras COMPLETED (documentos 3B). DRAFT no cuenta. Supplier return reduce neto."""

    def __init__(self, db_manager, proveedores_repo):
        self.db = db_manager
        self.proveedores_repo = proveedores_repo

    def _connect(self):
        return self.db.conectar()

    def obtener_proveedores_activos(self) -> List[Dict]:
        try:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT id, nombre, nit
                      FROM proveedores
                     WHERE activo = 1
                     ORDER BY nombre
                    """
                ).fetchall()
                return [
                    {
                        "id": row["id"],
                        "nombre": row["nombre"],
                        "nit": row["nit"],
                    }
                    for row in rows
                ]
            finally:
                conn.close()
        except Exception as exc:
            print(f"Error obteniendo proveedores: {exc}")
            return []

    def _supplier_returns_total(
        self, conn, fecha_inicio=None, fecha_fin=None, proveedor_id=None, producto_id=None
    ) -> Decimal:
        if not schema_bootstrap.table_exists(conn, "reversal_documents"):
            return Decimal("0.00")
        sql = f"""
            SELECT COALESCE(SUM(l.subtotal), 0) AS total
              FROM reversal_lines l
              JOIN reversal_documents d ON d.id = l.reversal_id
              LEFT JOIN compras c ON c.id = d.original_id
               AND d.original_tipo = 'compra'
             WHERE UPPER(COALESCE(d.estado, '')) = ?
               AND d.kind = ?
               AND d.original_tipo = 'compra'
        """
        params: list = [ESTADO_COMPLETED, KIND_SUPPLIER_RETURN]
        if fecha_inicio and fecha_fin:
            sql += f" AND {_date_range_sql('d.fecha')}"
            params.extend([fecha_inicio, fecha_fin])
        if proveedor_id:
            sql += " AND c.proveedor_id = ?"
            params.append(proveedor_id)
        if producto_id:
            sql += " AND l.producto_id = ?"
            params.append(producto_id)
        row = _row_dict(conn.execute(sql, params).fetchone())
        return _as_money(row.get("total"))

    def resumen_compras_periodo(
        self,
        fecha_inicio: Optional[str] = None,
        fecha_fin: Optional[str] = None,
        proveedor_id: Optional[int] = None,
    ) -> Dict:
        hoy = datetime.now().strftime("%Y-%m-%d")
        fecha_inicio = fecha_inicio or (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        fecha_fin = fecha_fin or hoy
        conn = self._connect()
        try:
            sql = f"""
                SELECT COUNT(*) AS total_compras,
                       COALESCE(SUM(c.total), 0) AS gross_purchases
                  FROM compras c
                 WHERE {PURCHASES_COMPLETED_SQL.format(alias='c')}
                   AND {_date_range_sql('c.fecha')}
            """
            params: list = [fecha_inicio, fecha_fin]
            if proveedor_id:
                sql += " AND c.proveedor_id = ?"
                params.append(proveedor_id)
            row = _row_dict(conn.execute(sql, params).fetchone())
            gross = _as_money(row.get("gross_purchases"))
            returns = self._supplier_returns_total(
                conn, fecha_inicio, fecha_fin, proveedor_id=proveedor_id
            )
            return {
                "fecha_inicio": fecha_inicio,
                "fecha_fin": fecha_fin,
                "total_compras": int(row.get("total_compras") or 0),
                "gross_purchases": gross,
                "supplier_returns": returns,
                "net_purchases": gross - returns,
            }
        finally:
            conn.close()

    def obtener_compras_por_proveedor(
        self,
        proveedor_id: Optional[int] = None,
        fecha_inicio: Optional[str] = None,
        fecha_fin: Optional[str] = None,
        producto_id: Optional[int] = None,
    ) -> List[Dict]:
        conn = self._connect()
        try:
            sql = f"""
                SELECT c.id, c.fecha, c.numero_factura, c.estado, c.total,
                       c.tipo_compra, c.estado_pago, c.saldo_pendiente,
                       dc.cantidad, dc.precio_unitario, dc.subtotal,
                       p.id AS producto_id, p.nombre AS producto_nombre,
                       p.codigo_barras, p.categoria, p.marca,
                       prov.id AS proveedor_id, prov.nombre AS proveedor_nombre,
                       prov.nit, u.nombre_completo AS usuario_nombre
                  FROM compras c
                  JOIN detalle_compras dc ON dc.compra_id = c.id
                  JOIN productos p ON dc.producto_id = p.id
                  LEFT JOIN proveedores prov ON c.proveedor_id = prov.id
                  LEFT JOIN usuarios u ON c.usuario_id = u.id
                 WHERE {PURCHASES_COMPLETED_SQL.format(alias='c')}
            """
            params: list = []
            if proveedor_id:
                sql += " AND c.proveedor_id = ?"
                params.append(proveedor_id)
            if fecha_inicio:
                sql += f" AND {_local_date('c.fecha')} >= DATE(?)"
                params.append(fecha_inicio)
            if fecha_fin:
                sql += f" AND {_local_date('c.fecha')} <= DATE(?)"
                params.append(fecha_fin)
            if producto_id:
                sql += " AND dc.producto_id = ?"
                params.append(producto_id)
            sql += " ORDER BY c.fecha DESC, prov.nombre"
            compras = []
            for raw in conn.execute(sql, params).fetchall():
                row = _row_dict(raw)
                compras.append(
                    {
                        "id": row.get("id"),
                        "fecha": row.get("fecha"),
                        "tipo": "COMPRA",
                        "cantidad": _as_qty(row.get("cantidad")),
                        "precio_unitario": _as_money(row.get("precio_unitario")),
                        "costo_total": _as_money(row.get("subtotal")),
                        "num_factura": row.get("numero_factura"),
                        "en_cajas": False,
                        "num_cajas": 0,
                        "observaciones": None,
                        "producto_id": row.get("producto_id"),
                        "producto_nombre": row.get("producto_nombre"),
                        "codigo_barras": row.get("codigo_barras"),
                        "categoria": row.get("categoria"),
                        "marca": row.get("marca"),
                        "proveedor_id": row.get("proveedor_id"),
                        "proveedor_nombre": row.get("proveedor_nombre") or "Sin proveedor",
                        "nit": row.get("nit"),
                        "usuario_nombre": row.get("usuario_nombre"),
                        "estado": row.get("estado"),
                        "total": _as_money(row.get("total")),
                    }
                )
            return compras
        finally:
            conn.close()

    def obtener_resumen_por_proveedor(
        self, fecha_inicio: Optional[str] = None, fecha_fin: Optional[str] = None
    ) -> List[Dict]:
        conn = self._connect()
        try:
            sql = f"""
                SELECT prov.id, prov.nombre, prov.nit,
                       COUNT(DISTINCT c.id) AS total_compras,
                       COALESCE(SUM(dc.cantidad), 0) AS total_unidades,
                       COALESCE(SUM(dc.subtotal), 0) AS monto_total,
                       COUNT(DISTINCT dc.producto_id) AS productos_diferentes,
                       MAX(c.fecha) AS ultima_compra
                  FROM compras c
                  JOIN detalle_compras dc ON dc.compra_id = c.id
                  JOIN proveedores prov ON c.proveedor_id = prov.id
                 WHERE {PURCHASES_COMPLETED_SQL.format(alias='c')}
            """
            params: list = []
            if fecha_inicio:
                sql += f" AND {_local_date('c.fecha')} >= DATE(?)"
                params.append(fecha_inicio)
            if fecha_fin:
                sql += f" AND {_local_date('c.fecha')} <= DATE(?)"
                params.append(fecha_fin)
            sql += " GROUP BY prov.id, prov.nombre, prov.nit ORDER BY monto_total DESC"
            resumen = []
            for raw in conn.execute(sql, params).fetchall():
                row = _row_dict(raw)
                gross = _as_money(row.get("monto_total"))
                returns = self._supplier_returns_total(
                    conn, fecha_inicio, fecha_fin, proveedor_id=row.get("id")
                )
                resumen.append(
                    {
                        "proveedor_id": row.get("id"),
                        "proveedor_nombre": row.get("nombre"),
                        "nit": row.get("nit"),
                        "total_compras": int(row.get("total_compras") or 0),
                        "total_unidades": _as_qty(row.get("total_unidades")),
                        "monto_total": gross - returns,
                        "gross_purchases": gross,
                        "supplier_returns": returns,
                        "productos_diferentes": int(row.get("productos_diferentes") or 0),
                        "ultima_compra": row.get("ultima_compra"),
                    }
                )
            return resumen
        finally:
            conn.close()

    def obtener_productos_mas_comprados(
        self,
        proveedor_id: Optional[int] = None,
        fecha_inicio: Optional[str] = None,
        fecha_fin: Optional[str] = None,
        limite: int = 10,
    ) -> List[Dict]:
        conn = self._connect()
        try:
            sql = f"""
                SELECT p.id, p.nombre, p.codigo_barras, p.categoria, p.marca,
                       COUNT(dc.id) AS veces_comprado,
                       COALESCE(SUM(dc.cantidad), 0) AS total_unidades,
                       COALESCE(SUM(dc.subtotal), 0) AS monto_total,
                       AVG(dc.precio_unitario) AS precio_promedio,
                       MAX(c.fecha) AS ultima_compra
                  FROM detalle_compras dc
                  JOIN compras c ON c.id = dc.compra_id
                  JOIN productos p ON dc.producto_id = p.id
                 WHERE {PURCHASES_COMPLETED_SQL.format(alias='c')}
            """
            params: list = []
            if proveedor_id:
                sql += " AND c.proveedor_id = ?"
                params.append(proveedor_id)
            if fecha_inicio:
                sql += f" AND {_local_date('c.fecha')} >= DATE(?)"
                params.append(fecha_inicio)
            if fecha_fin:
                sql += f" AND {_local_date('c.fecha')} <= DATE(?)"
                params.append(fecha_fin)
            sql += " GROUP BY p.id ORDER BY total_unidades DESC LIMIT ?"
            params.append(limite)
            productos = []
            for raw in conn.execute(sql, params).fetchall():
                row = _row_dict(raw)
                productos.append(
                    {
                        "producto_id": row.get("id"),
                        "nombre": row.get("nombre"),
                        "codigo_barras": row.get("codigo_barras"),
                        "categoria": row.get("categoria"),
                        "marca": row.get("marca"),
                        "veces_comprado": int(row.get("veces_comprado") or 0),
                        "total_unidades": _as_qty(row.get("total_unidades")),
                        "monto_total": _as_money(row.get("monto_total")),
                        "precio_promedio": _as_money(row.get("precio_promedio") or 0),
                        "ultima_compra": row.get("ultima_compra"),
                    }
                )
            return productos
        finally:
            conn.close()

    def obtener_resumen_temporal(
        self,
        tipo: str = "mensual",
        fecha_inicio: Optional[str] = None,
        fecha_fin: Optional[str] = None,
        proveedor_id: Optional[int] = None,
    ) -> List[Dict]:
        conn = self._connect()
        try:
            if tipo == "semanal":
                agrupacion = "strftime('%Y-W%W', c.fecha)"
                formato = "strftime('%Y-W%W', c.fecha) AS periodo"
            else:
                agrupacion = "strftime('%Y-%m', c.fecha)"
                formato = "strftime('%Y-%m', c.fecha) AS periodo"
            sql = f"""
                SELECT {formato},
                       COUNT(DISTINCT c.id) AS total_compras,
                       COALESCE(SUM(dc.cantidad), 0) AS total_unidades,
                       COALESCE(SUM(dc.subtotal), 0) AS monto_total,
                       COUNT(DISTINCT c.proveedor_id) AS proveedores_diferentes,
                       COUNT(DISTINCT dc.producto_id) AS productos_diferentes
                  FROM compras c
                  JOIN detalle_compras dc ON dc.compra_id = c.id
                 WHERE {PURCHASES_COMPLETED_SQL.format(alias='c')}
            """
            params: list = []
            if proveedor_id:
                sql += " AND c.proveedor_id = ?"
                params.append(proveedor_id)
            if fecha_inicio:
                sql += f" AND {_local_date('c.fecha')} >= DATE(?)"
                params.append(fecha_inicio)
            if fecha_fin:
                sql += f" AND {_local_date('c.fecha')} <= DATE(?)"
                params.append(fecha_fin)
            sql += f" GROUP BY {agrupacion} ORDER BY periodo DESC"
            resumen = []
            for raw in conn.execute(sql, params).fetchall():
                row = _row_dict(raw)
                resumen.append(
                    {
                        "periodo": row.get("periodo"),
                        "total_compras": int(row.get("total_compras") or 0),
                        "total_unidades": _as_qty(row.get("total_unidades")),
                        "monto_total": _as_money(row.get("monto_total")),
                        "proveedores_diferentes": int(row.get("proveedores_diferentes") or 0),
                        "productos_diferentes": int(row.get("productos_diferentes") or 0),
                    }
                )
            return resumen
        finally:
            conn.close()

    def obtener_estadisticas_generales(
        self, fecha_inicio: Optional[str] = None, fecha_fin: Optional[str] = None
    ) -> Dict:
        periodo = self.resumen_compras_periodo(fecha_inicio, fecha_fin)
        conn = self._connect()
        try:
            sql = f"""
                SELECT COUNT(DISTINCT c.proveedor_id) AS proveedores,
                       COUNT(DISTINCT dc.producto_id) AS productos,
                       COALESCE(SUM(dc.cantidad), 0) AS unidades
                  FROM compras c
                  JOIN detalle_compras dc ON dc.compra_id = c.id
                 WHERE {PURCHASES_COMPLETED_SQL.format(alias='c')}
            """
            params: list = []
            if fecha_inicio:
                sql += f" AND {_local_date('c.fecha')} >= DATE(?)"
                params.append(fecha_inicio)
            if fecha_fin:
                sql += f" AND {_local_date('c.fecha')} <= DATE(?)"
                params.append(fecha_fin)
            row = _row_dict(conn.execute(sql, params).fetchone())
            total = periodo["total_compras"]
            net = periodo["net_purchases"]
            return {
                "total_compras": total,
                "monto_total": net,
                "gross_purchases": periodo["gross_purchases"],
                "supplier_returns": periodo["supplier_returns"],
                "net_purchases": net,
                "proveedores_activos": int(row.get("proveedores") or 0),
                "productos_comprados": int(row.get("productos") or 0),
                "unidades_totales": _as_qty(row.get("unidades")),
                "ticket_promedio": (net / total) if total else Decimal("0.00"),
            }
        finally:
            conn.close()

    def obtener_proveedores_principales(
        self,
        limite: int = 5,
        fecha_inicio: Optional[str] = None,
        fecha_fin: Optional[str] = None,
    ) -> List[Dict]:
        resumen = self.obtener_resumen_por_proveedor(fecha_inicio, fecha_fin)
        return resumen[:limite]

    def exportar_reporte_csv(self, compras: List[Dict], archivo: str):
        import csv

        with open(archivo, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ["Fecha", "Proveedor", "Producto", "Cantidad", "Costo", "Factura"]
            )
            for item in compras:
                writer.writerow(
                    [
                        item.get("fecha"),
                        item.get("proveedor_nombre"),
                        item.get("producto_nombre"),
                        item.get("cantidad"),
                        item.get("costo_total"),
                        item.get("num_factura"),
                    ]
                )
