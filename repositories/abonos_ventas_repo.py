# -*- coding: utf-8 -*-
"""
Repositorio para gestión de abonos en ventas
Maneja la persistencia de cobros parciales a facturas de clientes
"""
import pg_compat
from typing import List, Dict, Optional
from models import AbonoVenta


class AbonosVentasRepository:
    """Repositorio para gestión de abonos a facturas de venta"""
    
    def __init__(self, db_path: str):
        pass  # db_path ignorado; se usa PostgreSQL
    
    def crear_abono(self, abono: AbonoVenta) -> int:
        """
        Registra un abono (cobro) a una factura de venta
        Returns: ID del abono creado
        """
        conn = pg_compat.connect()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO abonos_ventas 
                (id_venta, monto_abono, fecha_abono, tipo_pago, 
                 numero_comprobante, usuario, observaciones)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                abono.id_venta,
                abono.monto_abono,
                abono.fecha_abono,
                abono.tipo_pago,
                abono.numero_comprobante,
                abono.usuario,
                abono.observaciones
            ))
            
            abono_id = cursor.lastrowid
            
            # Obtener información de la venta para el movimiento
            cursor.execute('''
                SELECT numero_factura, cliente_id 
                FROM ventas 
                WHERE id = ?
            ''', (abono.id_venta,))
            venta_info = cursor.fetchone()
            numero_factura = venta_info[0] if venta_info else 'N/A'
            
            # Registrar movimiento de cobro
            from datetime import datetime
            cursor.execute('''
                INSERT INTO movimientos (
                    tipo, producto_id, cantidad,
                    precio_unitario, costo_total, motivo, num_factura, fecha
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                'COBRO_CREDITO',
                -1,  # Valor especial para indicar que no es movimiento de producto
                1,   # Cantidad 1 para que no sea NULL
                abono.monto_abono,  # El monto del cobro
                abono.monto_abono,  # El monto del cobro va en costo_total
                f'Cobro de factura {numero_factura} - {abono.tipo_pago}',
                numero_factura,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            ))
            
            # Actualizar estado de la venta automáticamente
            self._actualizar_estado_venta(cursor, abono.id_venta)
            
            conn.commit()
            return abono_id
            
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def obtener_abonos_factura(self, id_venta: int) -> List[Dict]:
        """Obtiene todos los abonos de una factura"""
        conn = pg_compat.connect()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                id, id_venta, monto_abono, fecha_abono, tipo_pago,
                numero_comprobante, usuario, observaciones, created_at
            FROM abonos_ventas 
            WHERE id_venta = ?
            ORDER BY fecha_abono DESC
        ''', (id_venta,))
        
        abonos = cursor.fetchall()
        conn.close()
        
        return [
            {
                'id': a[0],
                'id_venta': a[1],
                'monto_abono': a[2],
                'fecha_abono': a[3],
                'tipo_pago': a[4],
                'numero_comprobante': a[5],
                'usuario': a[6],
                'observaciones': a[7],
                'created_at': a[8]
            }
            for a in abonos
        ]
    
    def obtener_total_abonado(self, id_venta: int) -> float:
        """Obtiene el total abonado a una factura"""
        conn = pg_compat.connect()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT COALESCE(SUM(monto_abono), 0) FROM abonos_ventas 
            WHERE id_venta = ?
        ''', (id_venta,))
        
        total = cursor.fetchone()[0]
        conn.close()
        
        return total
    
    def eliminar_abono(self, id_abono: int) -> bool:
        """Elimina un abono (solo si se necesita corregir)"""
        conn = pg_compat.connect()
        cursor = conn.cursor()
        
        try:
            # Obtener id_venta antes de eliminar
            cursor.execute('SELECT id_venta FROM abonos_ventas WHERE id = ?', (id_abono,))
            resultado = cursor.fetchone()
            
            if not resultado:
                return False
            
            id_venta = resultado[0]
            
            # Eliminar abono
            cursor.execute('DELETE FROM abonos_ventas WHERE id = ?', (id_abono,))
            
            # Actualizar estado de la venta
            self._actualizar_estado_venta(cursor, id_venta)
            
            conn.commit()
            return True
            
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def _actualizar_estado_venta(self, cursor, id_venta: int):
        """
        Actualiza el estado y saldo pendiente de una venta
        basado en los abonos registrados (INTERNA)
        """
        # Obtener total abonado
        cursor.execute('''
            SELECT COALESCE(SUM(monto_abono), 0) FROM abonos_ventas 
            WHERE id_venta = ?
        ''', (id_venta,))
        total_abonado = cursor.fetchone()[0]
        
        # Obtener monto total de la factura
        cursor.execute('''
            SELECT total FROM ventas WHERE id = ?
        ''', (id_venta,))
        resultado = cursor.fetchone()
        
        if not resultado:
            return
        
        total_factura = resultado[0]
        
        # Calcular estado
        if total_abonado == 0:
            estado_pago = 'PENDIENTE'
        elif total_abonado >= total_factura:
            estado_pago = 'PAGADO'
        else:
            estado_pago = 'PARCIAL'
        
        # Actualizar venta
        cursor.execute('''
            UPDATE ventas 
            SET estado_pago = ?, monto_pagado = ?
            WHERE id = ?
        ''', (estado_pago, total_abonado, id_venta))
    
    def obtener_abonos_por_usuario(self, usuario: str, 
                                  fecha_inicio: str = None, 
                                  fecha_fin: str = None) -> List[Dict]:
        """
        Obtiene los abonos registrados por un usuario en un rango de fechas
        Útil para auditoría
        """
        conn = pg_compat.connect()
        cursor = conn.cursor()
        
        query = '''
            SELECT 
                a.id, a.id_venta, a.monto_abono, a.fecha_abono, a.tipo_pago,
                a.numero_comprobante, a.usuario, a.observaciones, a.created_at,
                v.numero_factura, v.total
            FROM abonos_ventas a
            INNER JOIN ventas v ON a.id_venta = v.id
            WHERE a.usuario = ?
        '''
        
        params = [usuario]
        
        if fecha_inicio:
            query += ' AND a.fecha_abono >= ?'
            params.append(fecha_inicio)
        
        if fecha_fin:
            query += ' AND a.fecha_abono <= ?'
            params.append(fecha_fin)
        
        query += ' ORDER BY a.fecha_abono DESC'
        
        cursor.execute(query, params)
        abonos = cursor.fetchall()
        conn.close()
        
        return [
            {
                'id': a[0],
                'id_venta': a[1],
                'monto_abono': a[2],
                'fecha_abono': a[3],
                'tipo_pago': a[4],
                'numero_comprobante': a[5],
                'usuario': a[6],
                'observaciones': a[7],
                'created_at': a[8],
                'numero_factura': a[9],
                'total_factura': a[10]
            }
            for a in abonos
        ]
