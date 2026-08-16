# -*- coding: utf-8 -*-
"""Cuentas por cobrar: lectura canónica local-first. No reescribe ventas COMPLETED."""
from decimal import Decimal
from typing import Dict, List, Optional

from services.operational_balance import (
    add_aging,
    compute_receivable,
    connect_local,
    days_outstanding,
    empty_aging,
    list_receivable_snapshots,
    reconcile_receivable,
)


class CuentasPorCobrarService:
    """Servicio para gestión y análisis de cuentas por cobrar"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _connect(self):
        return connect_local(self.db_path)

    def obtener_resumen_cuentas_por_cobrar(self) -> List[Dict]:
        conn = self._connect()
        try:
            grouped = {}
            for venta, snap in list_receivable_snapshots(conn):
                if snap.balance <= 0:
                    continue
                cid = venta.get("cliente_id") or venta.get("cliente_id_join")
                key = cid if cid is not None else f"venta-{venta['id']}"
                bucket = grouped.setdefault(
                    key,
                    {
                        "id_cliente": cid,
                        "nombre_cliente": venta.get("cliente_nombre") or "CLIENTE GENERAL",
                        "total_deuda": Decimal("0.00"),
                        "facturas_pendientes": 0,
                        "aging": empty_aging(),
                        "factura_mas_antigua": venta.get("fecha"),
                    },
                )
                bucket["total_deuda"] += snap.balance
                bucket["facturas_pendientes"] += 1
                days = days_outstanding(venta.get("fecha"))
                add_aging(bucket["aging"], days, snap.balance)
                antigua = bucket["factura_mas_antigua"]
                if venta.get("fecha") and (not antigua or str(venta["fecha"]) < str(antigua)):
                    bucket["factura_mas_antigua"] = venta.get("fecha")
            resultados = []
            for item in grouped.values():
                aging = item["aging"]
                resultados.append(
                    {
                        "id_cliente": item["id_cliente"],
                        "nombre_cliente": item["nombre_cliente"],
                        "total_deuda": item["total_deuda"],
                        "facturas_pendientes": item["facturas_pendientes"],
                        "deuda_30": aging["deuda_30"],
                        "deuda_60": aging["deuda_60"],
                        "deuda_90": aging["deuda_90"],
                        "aging_0_30": aging["aging_0_30"],
                        "aging_31_60": aging["aging_31_60"],
                        "aging_61_90": aging["aging_61_90"],
                        "aging_90_plus": aging["aging_90_plus"],
                        "factura_mas_antigua": item["factura_mas_antigua"],
                        "estado_vencimiento": self._calcular_vencimiento(
                            aging["deuda_90"], item["factura_mas_antigua"]
                        ),
                        "dias_antiguo": days_outstanding(item["factura_mas_antigua"])
                        if item["factura_mas_antigua"]
                        else 0,
                    }
                )
            resultados.sort(key=lambda r: r["total_deuda"], reverse=True)
            return resultados
        finally:
            conn.close()

    def obtener_cuentas_cliente(self, id_cliente: int) -> Optional[Dict]:
        conn = self._connect()
        try:
            cliente_row = conn.execute(
                """
                SELECT id, nombre, numero_documento, telefono,
                       COALESCE(email, '') AS correo, limite_credito
                  FROM clientes WHERE id = ?
                """,
                (id_cliente,),
            ).fetchone()
            if not cliente_row:
                return None
            cliente = dict(cliente_row)
            facturas = []
            creditos = []
            for venta, snap in list_receivable_snapshots(conn):
                if venta.get("cliente_id") != id_cliente:
                    continue
                item = {
                    "id": venta["id"],
                    "numero_factura": venta.get("numero_factura"),
                    "fecha": venta.get("fecha"),
                    "total": snap.original,
                    "monto_pagado": snap.payments,
                    "saldo_pendiente": snap.balance,
                    "credito_a_favor": snap.credit_balance,
                    "credit_kind": snap.credit_kind,
                    "reversals": snap.reversals,
                    "net_obligation": snap.net_obligation,
                    "estado_pago": snap.estado_pago,
                    "dias_vencido": days_outstanding(venta.get("fecha")),
                }
                if snap.balance > 0:
                    facturas.append(item)
                elif snap.credit_balance > 0:
                    creditos.append(item)
            return {
                "cliente": {
                    "id": id_cliente,
                    "nombre": cliente["nombre"],
                    "documento": cliente.get("numero_documento"),
                    "telefono": cliente.get("telefono"),
                    "correo": cliente.get("correo"),
                    "limite_credito": cliente.get("limite_credito"),
                },
                "facturas": facturas,
                "creditos_a_favor": creditos,
                "total_deuda": sum((f["saldo_pendiente"] for f in facturas), Decimal("0.00")),
                "total_pagado": sum((f["monto_pagado"] for f in facturas), Decimal("0.00")),
                "cantidad_facturas": len(facturas),
            }
        finally:
            conn.close()

    def obtener_totales_cuentas_por_cobrar(self) -> Dict:
        conn = self._connect()
        try:
            clientes = set()
            facturas = 0
            total = Decimal("0.00")
            for venta, snap in list_receivable_snapshots(conn):
                if snap.balance <= 0:
                    continue
                facturas += 1
                total += snap.balance
                if venta.get("cliente_id") is not None:
                    clientes.add(venta["cliente_id"])
            return {
                "total_facturas_pendientes": facturas,
                "total_clientes_con_deuda": len(clientes),
                "total_por_cobrar": total,
            }
        finally:
            conn.close()

    def obtener_facturas_vencidas(self, dias_vencimiento: int = 60) -> List[Dict]:
        conn = self._connect()
        try:
            facturas = []
            for venta, snap in list_receivable_snapshots(conn):
                if snap.balance <= 0:
                    continue
                days = days_outstanding(venta.get("fecha"))
                if days < dias_vencimiento:
                    continue
                facturas.append(
                    {
                        "id": venta["id"],
                        "numero_factura": venta.get("numero_factura"),
                        "fecha": venta.get("fecha"),
                        "total": snap.original,
                        "monto_pagado": snap.payments,
                        "saldo_pendiente": snap.balance,
                        "credito_a_favor": snap.credit_balance,
                        "estado_pago": snap.estado_pago,
                        "cliente_nombre": venta.get("cliente_nombre"),
                        "dias_vencido": days,
                    }
                )
            return facturas
        finally:
            conn.close()

    def obtener_ventas_credito_pendientes(self) -> List[Dict]:
        conn = self._connect()
        try:
            ventas = []
            for venta, snap in list_receivable_snapshots(conn):
                if snap.balance <= 0 and snap.credit_balance <= 0:
                    continue
                if snap.balance <= 0 and snap.credit_balance > 0:
                    # Crédito a favor: visible, no es deuda vencida.
                    pass
                item = {
                    "id": venta["id"],
                    "numero_factura": venta.get("numero_factura"),
                    "fecha": venta.get("fecha"),
                    "total": snap.original,
                    "monto_pagado": snap.payments,
                    "saldo_pendiente": snap.balance,
                    "credito_a_favor": snap.credit_balance,
                    "credit_kind": snap.credit_kind,
                    "reversals": snap.reversals,
                    "net_obligation": snap.net_obligation,
                    "estado_pago": snap.estado_pago,
                    "cliente_nombre": venta.get("cliente_nombre") or "CLIENTE GENERAL",
                    "cliente_id": venta.get("cliente_id"),
                    "dias_transcurridos": days_outstanding(venta.get("fecha")),
                }
                ventas.append(item)
            return ventas
        finally:
            conn.close()

    def obtener_saldo_venta(self, venta_id: int):
        conn = self._connect()
        try:
            snap = compute_receivable(conn, venta_id)
            return None if snap is None else snap.as_dict()
        finally:
            conn.close()

    def reconciliar_venta(self, venta_id: int):
        conn = self._connect()
        try:
            snap = reconcile_receivable(conn, venta_id)
            conn.commit()
            return snap.as_dict()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _calcular_vencimiento(self, deuda_90_dias, fecha_antigua: str) -> str:
        if deuda_90_dias and deuda_90_dias > 0:
            return "VENCIDA"
        if fecha_antigua:
            dias = days_outstanding(fecha_antigua)
            if dias > 60:
                return "ALERTA"
            if dias > 30:
                return "PROXIMO"
        return "RECIENTE"

    def _calcular_dias_antiguo(self, fecha_str: str) -> int:
        return days_outstanding(fecha_str)
