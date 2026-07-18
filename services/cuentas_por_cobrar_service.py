# -*- coding: utf-8 -*-
"""
Servicio de gestión de cuentas por cobrar (ventas a crédito)
Proporciona cálculos y reportes de deudas por cliente
"""
import pg_compat
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from models import ResumenCuentaPorCobrar


class CuentasPorCobrarService:
    """Servicio para gestión y análisis de cuentas por cobrar"""
    
    def __init__(self, db_path: str):
        pass  # db_path ignorado; se usa PostgreSQL
    
    def obtener_resumen_cuentas_por_cobrar(self) -> List[Dict]:
        """
        Obtiene resumen completo de cuentas por cobrar por cliente
        Incluye métricas de vencimiento y análisis de flujo
        """
        conn = pg_compat.connect()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                c.id as id_cliente,
                c.nombre as nombre_cliente,
                COALESCE(SUM(v.total - v.monto_pagado), 0) as total_deuda,
                COUNT(CASE WHEN v.estado_pago != 'PAGADO' THEN 1 END) as facturas_pendientes,
                COALESCE(SUM(CASE 
                    WHEN (julianday('now') - julianday(v.fecha)) <= 30 AND v.estado_pago != 'PAGADO'
                    THEN (v.total - v.monto_pagado) ELSE 0 END), 0) as deuda_30,
                COALESCE(SUM(CASE 
                    WHEN (julianday('now') - julianday(v.fecha)) BETWEEN 31 AND 60 AND v.estado_pago != 'PAGADO'
                    THEN (v.total - v.monto_pagado) ELSE 0 END), 0) as deuda_60,
                COALESCE(SUM(CASE 
                    WHEN (julianday('now') - julianday(v.fecha)) > 60 AND v.estado_pago != 'PAGADO'
                    THEN (v.total - v.monto_pagado) ELSE 0 END), 0) as deuda_90,
                MIN(v.fecha) as factura_mas_antigua
            FROM clientes c
            LEFT JOIN ventas v ON c.id = v.cliente_id
            WHERE v.metodo_pago = 'CREDITO' AND (v.estado_pago = 'PENDIENTE' OR v.estado_pago = 'PARCIAL')
            GROUP BY c.id, c.nombre
            ORDER BY total_deuda DESC
        ''')
        
        resultados = cursor.fetchall()
        conn.close()
        
        return [
            {
                'id_cliente': r[0],
                'nombre_cliente': r[1],
                'total_deuda': r[2] or 0,
                'facturas_pendientes': r[3] or 0,
                'deuda_30': r[4] or 0,
                'deuda_60': r[5] or 0,
                'deuda_90': r[6] or 0,
                'factura_mas_antigua': r[7],
                'estado_vencimiento': self._calcular_vencimiento(r[6] or 0, r[7]),
                'dias_antiguo': self._calcular_dias_antiguo(r[7]) if r[7] else 0
            }
            for r in resultados if r[2] > 0  # Solo clientes con deuda
        ]
    
    def obtener_cuentas_cliente(self, id_cliente: int) -> Dict:
        """Obtiene detalles de cuentas por cobrar de un cliente específico"""
        conn = pg_compat.connect()
        cursor = conn.cursor()
        
        # Información general del cliente
        cursor.execute('''
            SELECT nombre, documento, telefono, correo, limite_credito 
            FROM clientes WHERE id = ?
        ''', (id_cliente,))
        
        cliente = cursor.fetchone()
        
        if not cliente:
            conn.close()
            return None
        
        # Facturas pendientes
        cursor.execute('''
            SELECT 
                id, numero_factura, fecha, total, monto_pagado, 
                (total - monto_pagado) as saldo_pendiente, estado_pago
            FROM ventas
            WHERE cliente_id = ? 
                AND metodo_pago = 'CREDITO' 
                AND estado_pago != 'PAGADO'
            ORDER BY fecha ASC
        ''', (id_cliente,))
        
        facturas = [
            {
                'id': f[0],
                'numero_factura': f[1],
                'fecha': f[2],
                'total': f[3],
                'monto_pagado': f[4],
                'saldo_pendiente': f[5],
                'estado_pago': f[6],
                'dias_vencido': self._calcular_dias_antiguo(f[2])
            }
            for f in cursor.fetchall()
        ]
        
        # Totales
        total_deuda = sum(f['saldo_pendiente'] for f in facturas)
        total_pagado = sum(f['monto_pagado'] for f in facturas)
        
        conn.close()
        
        return {
            'cliente': {
                'id': id_cliente,
                'nombre': cliente[0],
                'documento': cliente[1],
                'telefono': cliente[2],
                'correo': cliente[3],
                'limite_credito': cliente[4]
            },
            'facturas': facturas,
            'total_deuda': total_deuda,
            'total_pagado': total_pagado,
            'cantidad_facturas': len(facturas)
        }
    
    def obtener_totales_cuentas_por_cobrar(self) -> Dict:
        """Obtiene totales generales de cuentas por cobrar"""
        conn = pg_compat.connect()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                COUNT(DISTINCT v.id) as total_facturas,
                COUNT(DISTINCT v.cliente_id) as total_clientes,
                COALESCE(SUM(v.total - v.monto_pagado), 0) as total_por_cobrar
            FROM ventas v
            WHERE v.metodo_pago = 'CREDITO' 
                AND (v.estado_pago = 'PENDIENTE' OR v.estado_pago = 'PARCIAL')
        ''')
        
        resultado = cursor.fetchone()
        conn.close()
        
        return {
            'total_facturas_pendientes': resultado[0] or 0,
            'total_clientes_con_deuda': resultado[1] or 0,
            'total_por_cobrar': resultado[2] or 0
        }
    
    def obtener_facturas_vencidas(self, dias_vencimiento: int = 60) -> List[Dict]:
        """
        Obtiene facturas con más de X días de vencimiento
        Por defecto, 60 días
        """
        conn = pg_compat.connect()
        cursor = conn.cursor()
        
        fecha_limite = (datetime.now() - timedelta(days=dias_vencimiento)).strftime('%Y-%m-%d')
        
        cursor.execute('''
            SELECT 
                v.id, v.numero_factura, v.fecha, v.total, v.monto_pagado,
                (v.total - v.monto_pagado) as saldo_pendiente,
                v.estado_pago, c.nombre as cliente_nombre,
                (julianday('now') - julianday(v.fecha)) as dias_vencido
            FROM ventas v
            INNER JOIN clientes c ON v.cliente_id = c.id
            WHERE v.metodo_pago = 'CREDITO'
                AND v.estado_pago != 'PAGADO'
                AND v.fecha <= ?
            ORDER BY v.fecha ASC
        ''', (fecha_limite,))
        
        facturas = [
            {
                'id': f[0],
                'numero_factura': f[1],
                'fecha': f[2],
                'total': f[3],
                'monto_pagado': f[4],
                'saldo_pendiente': f[5],
                'estado_pago': f[6],
                'cliente_nombre': f[7],
                'dias_vencido': int(f[8])
            }
            for f in cursor.fetchall()
        ]
        
        conn.close()
        return facturas
    
    def obtener_ventas_credito_pendientes(self) -> List[Dict]:
        """
        Obtiene todas las ventas a crédito con saldo pendiente
        Para mostrar en panel de ventas
        """
        conn = pg_compat.connect()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                v.id, v.numero_factura, v.fecha, v.total, 
                COALESCE(v.monto_pagado, 0) as monto_pagado,
                (v.total - COALESCE(v.monto_pagado, 0)) as saldo_pendiente,
                v.estado_pago, c.nombre as cliente_nombre, c.id as cliente_id,
                (julianday('now') - julianday(v.fecha)) as dias_transcurridos
            FROM ventas v
            LEFT JOIN clientes c ON v.cliente_id = c.id
            WHERE v.metodo_pago = 'CREDITO'
                AND v.estado_pago != 'PAGADO'
            ORDER BY v.fecha ASC
        ''')
        
        ventas = [
            {
                'id': f[0],
                'numero_factura': f[1],
                'fecha': f[2],
                'total': f[3],
                'monto_pagado': f[4],
                'saldo_pendiente': f[5],
                'estado_pago': f[6],
                'cliente_nombre': f[7] or 'CLIENTE GENERAL',
                'cliente_id': f[8],
                'dias_transcurridos': int(f[9])
            }
            for f in cursor.fetchall()
        ]
        
        conn.close()
        return ventas
    
    def _calcular_vencimiento(self, deuda_90_dias: float, fecha_antigua: str) -> str:
        """Calcula estado de vencimiento"""
        if deuda_90_dias > 0:
            return 'VENCIDA'
        
        if fecha_antigua:
            dias = self._calcular_dias_antiguo(fecha_antigua)
            if dias > 60:
                return 'ALERTA'
            elif dias > 30:
                return 'PROXIMO'
        
        return 'RECIENTE'
    
    def _calcular_dias_antiguo(self, fecha_str: str) -> int:
        """Calcula días transcurridos desde una fecha"""
        if not fecha_str:
            return 0
        
        try:
            fecha = datetime.fromisoformat(fecha_str.replace(' ', 'T'))
            dias = (datetime.now() - fecha).days
            return dias
        except Exception:
            return 0
