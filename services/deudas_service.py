# -*- coding: utf-8 -*-
"""
Servicio de gestión de deudas en compras
Proporciona cálculos y reportes de deudas por proveedor
"""
import pg_compat
from typing import List, Dict
from datetime import datetime, timedelta
from models import ResumenDeuda


class DeudasService:
    """Servicio para gestión y análisis de deudas en compras"""
    
    def __init__(self, db_path: str):
        pass  # db_path ignorado; se usa PostgreSQL
    
    def obtener_resumen_deudas(self) -> List[Dict]:
        """
        Obtiene resumen completo de deudas por proveedor
        Incluye métricas de vencimiento y análisis de flujo
        """
        conn = pg_compat.connect()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                p.id as id_proveedor,
                p.nombre as nombre_proveedor,
                COALESCE(SUM(c.saldo_pendiente), 0) as total_deuda,
                COUNT(CASE WHEN c.estado_pago != 'PAGADO' THEN 1 END) as facturas_pendientes,
                COALESCE(SUM(CASE 
                    WHEN (julianday('now') - julianday(c.fecha)) <= 30 AND c.estado_pago != 'PAGADO'
                    THEN c.saldo_pendiente ELSE 0 END), 0) as deuda_30,
                COALESCE(SUM(CASE 
                    WHEN (julianday('now') - julianday(c.fecha)) BETWEEN 31 AND 60 AND c.estado_pago != 'PAGADO'
                    THEN c.saldo_pendiente ELSE 0 END), 0) as deuda_60,
                COALESCE(SUM(CASE 
                    WHEN (julianday('now') - julianday(c.fecha)) > 60 AND c.estado_pago != 'PAGADO'
                    THEN c.saldo_pendiente ELSE 0 END), 0) as deuda_90,
                MIN(c.fecha) as factura_mas_antigua
            FROM proveedores p
            LEFT JOIN compras c ON p.id = c.proveedor_id
            WHERE c.id IS NULL OR c.estado_pago != 'PAGADO' OR c.saldo_pendiente > 0
            GROUP BY p.id, p.nombre
            ORDER BY total_deuda DESC
        ''')
        
        resultados = cursor.fetchall()
        conn.close()
        
        return [
            {
                'id_proveedor': r[0],
                'nombre_proveedor': r[1],
                'total_deuda': r[2] or 0,
                'facturas_pendientes': r[3] or 0,
                'deuda_30': r[4] or 0,
                'deuda_60': r[5] or 0,
                'deuda_90': r[6] or 0,
                'factura_mas_antigua': r[7],
                'estado_vencimiento': self._calcular_vencimiento(r[6] or 0, r[7]),
                'dias_antiguo': self._calcular_dias_antiguo(r[7]) if r[7] else 0
            }
            for r in resultados if r[2] > 0  # Solo proveedores con deuda
        ]
    
    def obtener_deudas_proveedor(self, id_proveedor: int) -> Dict:
        """Obtiene detalles de deuda de un proveedor específico"""
        conn = pg_compat.connect()
        cursor = conn.cursor()
        
        # Información general del proveedor
        cursor.execute('''
            SELECT nombre, nit, telefono, correo FROM proveedores WHERE id = ?
        ''', (id_proveedor,))
        
        proveedor = cursor.fetchone()
        
        if not proveedor:
            conn.close()
            return None
        
        # Facturas pendientes
        cursor.execute('''
            SELECT 
                id, numero_factura, fecha, total, monto_pagado, 
                saldo_pendiente, estado_pago, tipo_compra
            FROM compras
            WHERE proveedor_id = ? AND estado_pago != 'PAGADO'
            ORDER BY fecha ASC
        ''', (id_proveedor,))
        
        facturas = [
            {
                'id': f[0],
                'numero_factura': f[1],
                'fecha': f[2],
                'total': f[3],
                'monto_pagado': f[4],
                'saldo_pendiente': f[5],
                'estado_pago': f[6],
                'tipo_compra': f[7],
                'dias_antiguo': self._calcular_dias_antiguo(f[2])
            }
            for f in cursor.fetchall()
        ]
        
        conn.close()
        
        # Cálculos totales
        total_deuda = sum(f['saldo_pendiente'] for f in facturas)
        total_pagado = sum(f['monto_pagado'] for f in facturas)
        
        return {
            'id_proveedor': id_proveedor,
            'nombre': proveedor[0],
            'nit': proveedor[1],
            'telefono': proveedor[2],
            'correo': proveedor[3],
            'total_deuda': total_deuda,
            'total_pagado': total_pagado,
            'cantidad_facturas': len(facturas),
            'facturas': facturas
        }
    
    def obtener_totales_deudas(self) -> Dict:
        """Obtiene totales globales de deudas"""
        conn = pg_compat.connect()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT
                COALESCE(SUM(saldo_pendiente), 0) as total_deuda_general,
                COUNT(DISTINCT CASE WHEN saldo_pendiente > 0 THEN id END) as total_facturas_pendientes,
                COUNT(DISTINCT proveedor_id) as total_proveedores,
                COALESCE(SUM(CASE 
                    WHEN (julianday('now') - julianday(fecha)) <= 30 AND estado_pago != 'PAGADO'
                    THEN saldo_pendiente ELSE 0 END), 0) as deuda_30,
                COALESCE(SUM(CASE 
                    WHEN (julianday('now') - julianday(fecha)) BETWEEN 31 AND 60 AND estado_pago != 'PAGADO'
                    THEN saldo_pendiente ELSE 0 END), 0) as deuda_60,
                COALESCE(SUM(CASE 
                    WHEN (julianday('now') - julianday(fecha)) > 60 AND estado_pago != 'PAGADO'
                    THEN saldo_pendiente ELSE 0 END), 0) as deuda_90
            FROM compras
            WHERE estado_pago != 'PAGADO' OR saldo_pendiente > 0
        ''')
        
        resultado = cursor.fetchone()
        conn.close()
        
        return {
            'total_deuda': resultado[0] or 0,
            'facturas_pendientes': resultado[1] or 0,
            'proveedores_con_deuda': resultado[2] or 0,
            'deuda_30_dias': resultado[3] or 0,
            'deuda_31_60_dias': resultado[4] or 0,
            'deuda_91_mas_dias': resultado[5] or 0
        }
    
    def obtener_facturas_vencidas(self, dias: int = 60) -> List[Dict]:
        """
        Obtiene facturas cuya deuda tiene más de X días sin pagar
        Por defecto 60 días
        """
        conn = pg_compat.connect()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                c.id, c.numero_factura, p.nombre, c.fecha, c.total,
                c.saldo_pendiente, c.tipo_compra,
                CAST(julianday('now') - julianday(c.fecha) AS INTEGER) as dias_antiguo
            FROM compras c
            JOIN proveedores p ON c.proveedor_id = p.id
            WHERE c.estado_pago != 'PAGADO' AND saldo_pendiente > 0
                AND (julianday('now') - julianday(c.fecha)) > ?
            ORDER BY c.fecha ASC
        ''', (dias,))
        
        resultados = cursor.fetchall()
        conn.close()
        
        return [
            {
                'id': r[0],
                'numero_factura': r[1],
                'proveedor': r[2],
                'fecha': r[3],
                'total': r[4],
                'saldo_pendiente': r[5],
                'tipo_compra': r[6],
                'dias_antiguo': r[7]
            }
            for r in resultados
        ]
    
    def _calcular_vencimiento(self, deuda_90: float, fecha_mas_antigua: str) -> str:
        """Calcula el estado de vencimiento"""
        if deuda_90 > 0:
            return '[AVISO] VENCIDA (90+ días)'
        elif fecha_mas_antigua:
            dias = self._calcular_dias_antiguo(fecha_mas_antigua)
            if dias > 60:
                return '[AVISO] Próxima a vencer'
            elif dias > 30:
                return '⏳ En plazo'
            else:
                return '[OK] Al día'
        return '[OK] Al día'
    
    def _calcular_dias_antiguo(self, fecha_str: str) -> int:
        """Calcula cuántos días hace que es una fecha"""
        try:
            # Parsear fecha en formato ISO
            if isinstance(fecha_str, str):
                fecha = datetime.fromisoformat(fecha_str.replace('Z', '+00:00').split('+')[0])
            else:
                fecha = fecha_str
            
            dias = (datetime.now() - fecha).days
            return max(0, dias)
        except Exception:
            return 0
