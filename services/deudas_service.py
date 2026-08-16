# -*- coding: utf-8 -*-
"""Cuentas por pagar: lectura canónica local-first. No reescribe compras COMPLETED."""
from decimal import Decimal
from typing import Dict, List, Optional

from services.operational_balance import (
    add_aging,
    compute_payable,
    connect_local,
    days_outstanding,
    empty_aging,
    list_payable_snapshots,
    reconcile_payable,
)


class DeudasService:
    """Servicio para gestión y análisis de deudas en compras"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _connect(self):
        return connect_local(self.db_path)

    def obtener_resumen_deudas(self) -> List[Dict]:
        conn = self._connect()
        try:
            grouped = {}
            for compra, snap in list_payable_snapshots(conn):
                if snap.balance <= 0:
                    continue
                pid = compra.get("proveedor_id")
                key = pid if pid is not None else f"compra-{compra['id']}"
                bucket = grouped.setdefault(
                    key,
                    {
                        "id_proveedor": pid,
                        "nombre_proveedor": compra.get("proveedor_nombre") or "Proveedor",
                        "total_deuda": Decimal("0.00"),
                        "facturas_pendientes": 0,
                        "aging": empty_aging(),
                        "factura_mas_antigua": compra.get("fecha"),
                    },
                )
                bucket["total_deuda"] += snap.balance
                bucket["facturas_pendientes"] += 1
                days = days_outstanding(compra.get("fecha"))
                add_aging(bucket["aging"], days, snap.balance)
                antigua = bucket["factura_mas_antigua"]
                if compra.get("fecha") and (not antigua or str(compra["fecha"]) < str(antigua)):
                    bucket["factura_mas_antigua"] = compra.get("fecha")
            resultados = []
            for item in grouped.values():
                aging = item["aging"]
                resultados.append(
                    {
                        "id_proveedor": item["id_proveedor"],
                        "nombre_proveedor": item["nombre_proveedor"],
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

    def obtener_deudas_proveedor(self, id_proveedor: int) -> Optional[Dict]:
        conn = self._connect()
        try:
            proveedor_row = conn.execute(
                "SELECT id, nombre, nit, telefono, correo FROM proveedores WHERE id = ?",
                (id_proveedor,),
            ).fetchone()
            if not proveedor_row:
                return None
            proveedor = dict(proveedor_row)
            facturas = []
            creditos = []
            for compra, snap in list_payable_snapshots(conn):
                if compra.get("proveedor_id") != id_proveedor:
                    continue
                item = {
                    "id": compra["id"],
                    "numero_factura": compra.get("numero_factura"),
                    "fecha": compra.get("fecha"),
                    "total": snap.original,
                    "monto_pagado": snap.payments,
                    "saldo_pendiente": snap.balance,
                    "credito_a_favor": snap.credit_balance,
                    "credit_kind": snap.credit_kind,
                    "reversals": snap.reversals,
                    "net_obligation": snap.net_obligation,
                    "estado_pago": snap.estado_pago,
                    "tipo_compra": compra.get("tipo_compra"),
                    "dias_antiguo": days_outstanding(compra.get("fecha")),
                }
                if snap.balance > 0:
                    facturas.append(item)
                elif snap.credit_balance > 0:
                    creditos.append(item)
            return {
                "id_proveedor": id_proveedor,
                "nombre": proveedor.get("nombre"),
                "nit": proveedor.get("nit"),
                "telefono": proveedor.get("telefono"),
                "correo": proveedor.get("correo"),
                "total_deuda": sum((f["saldo_pendiente"] for f in facturas), Decimal("0.00")),
                "total_pagado": sum((f["monto_pagado"] for f in facturas), Decimal("0.00")),
                "cantidad_facturas": len(facturas),
                "facturas": facturas,
                "creditos_a_favor": creditos,
            }
        finally:
            conn.close()

    def obtener_totales_deudas(self) -> Dict:
        conn = self._connect()
        try:
            aging = empty_aging()
            proveedores = set()
            facturas = 0
            total = Decimal("0.00")
            for compra, snap in list_payable_snapshots(conn):
                if snap.balance <= 0:
                    continue
                facturas += 1
                total += snap.balance
                if compra.get("proveedor_id") is not None:
                    proveedores.add(compra["proveedor_id"])
                add_aging(aging, days_outstanding(compra.get("fecha")), snap.balance)
            return {
                "total_deuda": total,
                "facturas_pendientes": facturas,
                "proveedores_con_deuda": len(proveedores),
                "deuda_30_dias": aging["deuda_30"],
                "deuda_31_60_dias": aging["deuda_60"],
                "deuda_91_mas_dias": aging["deuda_90"],
                "aging_0_30": aging["aging_0_30"],
                "aging_31_60": aging["aging_31_60"],
                "aging_61_90": aging["aging_61_90"],
                "aging_90_plus": aging["aging_90_plus"],
            }
        finally:
            conn.close()

    def obtener_facturas_vencidas(self, dias: int = 60) -> List[Dict]:
        conn = self._connect()
        try:
            resultados = []
            for compra, snap in list_payable_snapshots(conn):
                if snap.balance <= 0:
                    continue
                days = days_outstanding(compra.get("fecha"))
                if days <= dias:
                    continue
                resultados.append(
                    {
                        "id": compra["id"],
                        "numero_factura": compra.get("numero_factura"),
                        "proveedor": compra.get("proveedor_nombre"),
                        "fecha": compra.get("fecha"),
                        "total": snap.original,
                        "saldo_pendiente": snap.balance,
                        "credito_a_favor": snap.credit_balance,
                        "tipo_compra": compra.get("tipo_compra"),
                        "dias_antiguo": days,
                    }
                )
            return resultados
        finally:
            conn.close()

    def obtener_saldo_compra(self, compra_id: int):
        conn = self._connect()
        try:
            snap = compute_payable(conn, compra_id)
            return None if snap is None else snap.as_dict()
        finally:
            conn.close()

    def reconciliar_compra(self, compra_id: int):
        conn = self._connect()
        try:
            snap = reconcile_payable(conn, compra_id)
            conn.commit()
            return snap.as_dict()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _calcular_vencimiento(self, deuda_90, fecha_mas_antigua: str) -> str:
        if deuda_90 and deuda_90 > 0:
            return "[AVISO] VENCIDA (90+ días)"
        if fecha_mas_antigua:
            dias = days_outstanding(fecha_mas_antigua)
            if dias > 60:
                return "[AVISO] Próxima a vencer"
            if dias > 30:
                return "⏳ En plazo"
        return "[OK] Al día"

    def _calcular_dias_antiguo(self, fecha_str: str) -> int:
        return days_outstanding(fecha_str)
