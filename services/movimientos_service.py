# -*- coding: utf-8 -*-
"""
Servicio de gestión de movimientos de inventario
Maneja entradas, salidas y actualización de stock
"""
from typing import Tuple, List, Optional
from datetime import datetime


class MovimientosService:
    """Servicio para gestión de movimientos de inventario"""
    
    def __init__(self, db_manager, productos_repo, proveedores_repo, auth):
        self.db = db_manager
        self.productos_repo = productos_repo
        self.proveedores_repo = proveedores_repo
        self.auth = auth
    
    def registrar_movimiento(self, tipo: str, producto_id: int, cantidad: int,
                            precio_unitario: float = 0, proveedor_id: Optional[int] = None,
                            num_factura: Optional[str] = None, 
                            observaciones: Optional[str] = None,
                            en_cajas: bool = False, num_cajas: int = 0) -> Tuple[bool, str]:
        """
        Registra un movimiento de inventario y actualiza el stock
        Returns: (éxito, mensaje)
        """
        # Verificar permisos
        if not self.auth.tiene_permiso('gestionar_movimientos'):
            return False, "No tiene permisos para gestionar movimientos"
        
        # Validar producto
        producto = self.productos_repo.obtener_por_id(producto_id)
        if not producto:
            return False, "Producto no encontrado"
        
        # Validar cantidad
        if cantidad <= 0:
            return False, "La cantidad debe ser mayor a cero"
        
        # Para salidas, verificar que haya stock suficiente
        if tipo.startswith('SALIDA'):
            if producto.stock < cantidad:
                return False, f"Stock insuficiente. Disponible: {producto.stock}"
        
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        try:
            # Calcular costo total
            costo_total = cantidad * precio_unitario
            
            # Registrar movimiento
            cursor.execute('''
                INSERT INTO movimientos (
                    tipo, producto_id, proveedor_id, usuario_id, cantidad,
                    precio_unitario, costo_total, motivo, num_factura,
                    en_cajas, num_cajas, observaciones
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                tipo,
                producto_id,
                proveedor_id,
                self.auth.usuario_actual.id if self.auth.usuario_actual else None,
                cantidad,
                precio_unitario,
                costo_total,
                None,  # motivo (deprecated, usar observaciones)
                num_factura,
                1 if en_cajas else 0,
                num_cajas,
                observaciones
            ))
            
            movimiento_id = cursor.lastrowid
            
            # Actualizar stock
            if tipo.startswith('ENTRADA'):
                nuevo_stock = producto.stock + cantidad
            else:  # SALIDA
                nuevo_stock = producto.stock - cantidad
            
            cursor.execute('''
                UPDATE productos 
                SET stock = ?
                WHERE id = ?
            ''', (nuevo_stock, producto_id))
            
            # Si es entrada por compra, actualizar precio de compra del producto
            if tipo == 'ENTRADA_COMPRA' and precio_unitario > 0:
                cursor.execute('''
                    UPDATE productos 
                    SET precio_compra = ?, proveedor_id = ?
                    WHERE id = ?
                ''', (precio_unitario, proveedor_id, producto_id))
            
            conn.commit()
            
            # Registrar en auditoría
            self.auth.registrar_auditoria(
                self.auth.usuario_actual.id if self.auth.usuario_actual else None,
                "MOVIMIENTO_INVENTARIO",
                "Movimientos",
                f"{tipo}: {producto.nombre} - Cantidad: {cantidad} - Nuevo stock: {nuevo_stock}"
            )
            
            conn.close()
            
            tipo_texto = tipo.replace('_', ' ').title()
            return True, f"{tipo_texto} registrada exitosamente. Stock actualizado a {nuevo_stock}"
        
        except Exception as e:
            conn.rollback()
            conn.close()
            return False, f"Error al registrar movimiento: {str(e)}"
    
    def obtener_historial(self, producto_id: Optional[int] = None,
                         proveedor_id: Optional[int] = None,
                         tipo: Optional[str] = None,
                         fecha_inicio: Optional[str] = None,
                         fecha_fin: Optional[str] = None,
                         limite: int = 100) -> List[dict]:
        """
        Obtiene el historial de movimientos con filtros opcionales
        """
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        # Construir query con filtros
        query = '''
            SELECT 
                m.*,
                p.nombre as producto_nombre,
                p.codigo_barras as producto_codigo,
                prov.nombre as proveedor_nombre,
                u.nombre_completo as usuario_nombre
            FROM movimientos m
            LEFT JOIN productos p ON m.producto_id = p.id
            LEFT JOIN proveedores prov ON m.proveedor_id = prov.id
            LEFT JOIN usuarios u ON m.usuario_id = u.id
            WHERE 1=1
        '''
        
        params = []
        
        if producto_id:
            query += " AND m.producto_id = ?"
            params.append(producto_id)
        
        if proveedor_id:
            query += " AND m.proveedor_id = ?"
            params.append(proveedor_id)
        
        if tipo:
            query += " AND m.tipo = ?"
            params.append(tipo)
        
        if fecha_inicio:
            query += " AND DATE(m.fecha) >= DATE(?)"
            params.append(fecha_inicio)
        
        if fecha_fin:
            query += " AND DATE(m.fecha) <= DATE(?)"
            params.append(fecha_fin)
        
        query += " ORDER BY m.fecha DESC LIMIT ?"
        params.append(limite)
        
        cursor.execute(query, params)
        movimientos = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        return movimientos
    
    def obtener_movimiento_por_id(self, movimiento_id: int) -> Optional[dict]:
        """Obtiene un movimiento específico por ID"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                m.*,
                p.nombre as producto_nombre,
                p.codigo_barras as producto_codigo,
                prov.nombre as proveedor_nombre,
                u.nombre_completo as usuario_nombre
            FROM movimientos m
            LEFT JOIN productos p ON m.producto_id = p.id
            LEFT JOIN proveedores prov ON m.proveedor_id = prov.id
            LEFT JOIN usuarios u ON m.usuario_id = u.id
            WHERE m.id = ?
        ''', (movimiento_id,))
        
        resultado = cursor.fetchone()
        conn.close()
        
        return dict(resultado) if resultado else None
    
    def obtener_estadisticas_movimientos(self, fecha_inicio: str = None, 
                                        fecha_fin: str = None) -> dict:
        """
        Obtiene estadísticas de movimientos en un período
        """
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        # Construir filtros de fecha
        fecha_filter = ""
        params = []
        
        if fecha_inicio and fecha_fin:
            fecha_filter = "WHERE DATE(fecha) BETWEEN DATE(?) AND DATE(?)"
            params = [fecha_inicio, fecha_fin]
        elif fecha_inicio:
            fecha_filter = "WHERE DATE(fecha) >= DATE(?)"
            params = [fecha_inicio]
        elif fecha_fin:
            fecha_filter = "WHERE DATE(fecha) <= DATE(?)"
            params = [fecha_fin]
        
        stats = {}
        
        # Total de movimientos por tipo
        cursor.execute(f'''
            SELECT tipo, COUNT(*) as cantidad, SUM(cantidad) as unidades
            FROM movimientos
            {fecha_filter}
            GROUP BY tipo
        ''', params)
        
        movimientos_por_tipo = {}
        for row in cursor.fetchall():
            movimientos_por_tipo[row['tipo']] = {
                'cantidad': row['cantidad'],
                'unidades': row['unidades']
            }
        
        stats['movimientos_por_tipo'] = movimientos_por_tipo
        
        # Costo total de entradas
        cursor.execute(f'''
            SELECT COALESCE(SUM(costo_total), 0) as total
            FROM movimientos
            WHERE tipo LIKE 'ENTRADA%'
            {fecha_filter.replace('WHERE', 'AND') if fecha_filter else ''}
        ''', params)
        
        stats['costo_entradas'] = cursor.fetchone()['total']
        
        # Productos más movidos
        cursor.execute(f'''
            SELECT 
                p.nombre,
                SUM(m.cantidad) as total_movido
            FROM movimientos m
            JOIN productos p ON m.producto_id = p.id
            {fecha_filter}
            GROUP BY m.producto_id
            ORDER BY total_movido DESC
            LIMIT 10
        ''', params)
        
        stats['productos_mas_movidos'] = [dict(row) for row in cursor.fetchall()]
        
        # Proveedores con más entradas
        cursor.execute(f'''
            SELECT 
                prov.nombre,
                COUNT(*) as num_entradas,
                SUM(m.costo_total) as total_comprado
            FROM movimientos m
            JOIN proveedores prov ON m.proveedor_id = prov.id
            WHERE m.tipo LIKE 'ENTRADA%'
            {fecha_filter.replace('WHERE', 'AND') if fecha_filter else ''}
            GROUP BY m.proveedor_id
            ORDER BY total_comprado DESC
            LIMIT 10
        ''', params)
        
        stats['principales_proveedores'] = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        return stats
    
    def anular_movimiento(self, movimiento_id: int, motivo: str) -> Tuple[bool, str]:
        """
        Anula un movimiento y revierte el cambio en el stock
        NOTA: Usar con precaución
        """
        if not self.auth.tiene_permiso('gestionar_movimientos'):
            return False, "No tiene permisos para anular movimientos"
        
        # Obtener el movimiento
        movimiento = self.obtener_movimiento_por_id(movimiento_id)
        if not movimiento:
            return False, "Movimiento no encontrado"
        
        # Obtener producto actual
        producto = self.productos_repo.obtener_por_id(movimiento['producto_id'])
        if not producto:
            return False, "Producto no encontrado"
        
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        try:
            # Revertir el stock
            if movimiento['tipo'].startswith('ENTRADA'):
                nuevo_stock = producto.stock - movimiento['cantidad']
            else:  # SALIDA
                nuevo_stock = producto.stock + movimiento['cantidad']
            
            # Verificar que el nuevo stock no sea negativo
            if nuevo_stock < 0:
                return False, "No se puede anular: resultaría en stock negativo"
            
            # Actualizar stock
            cursor.execute('''
                UPDATE productos 
                SET stock = ?
                WHERE id = ?
            ''', (nuevo_stock, movimiento['producto_id']))
            
            # Marcar movimiento como anulado (agregar observación)
            observacion_anulacion = f"[ANULADO] {motivo}"
            if movimiento['observaciones']:
                observacion_anulacion = f"{movimiento['observaciones']} | {observacion_anulacion}"
            
            cursor.execute('''
                UPDATE movimientos
                SET observaciones = ?
                WHERE id = ?
            ''', (observacion_anulacion, movimiento_id))
            
            conn.commit()
            
            # Registrar en auditoría
            self.auth.registrar_auditoria(
                self.auth.usuario_actual.id if self.auth.usuario_actual else None,
                "ANULAR_MOVIMIENTO",
                "Movimientos",
                f"Movimiento {movimiento_id} anulado. Motivo: {motivo}"
            )
            
            conn.close()
            return True, f"Movimiento anulado. Stock actualizado a {nuevo_stock}"
        
        except Exception as e:
            conn.rollback()
            conn.close()
            return False, f"Error al anular movimiento: {str(e)}"
    
    def obtener_kardex_producto(self, producto_id: int, limite: int = 50) -> List[dict]:
        """
        Obtiene el kardex (historial de movimientos) de un producto específico
        con el stock después de cada movimiento
        """
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                m.id,
                m.fecha,
                m.tipo,
                m.cantidad,
                m.precio_unitario,
                m.costo_total,
                m.num_factura,
                m.observaciones,
                prov.nombre as proveedor_nombre,
                u.nombre_completo as usuario_nombre
            FROM movimientos m
            LEFT JOIN proveedores prov ON m.proveedor_id = prov.id
            LEFT JOIN usuarios u ON m.usuario_id = u.id
            WHERE m.producto_id = ?
            ORDER BY m.fecha DESC
            LIMIT ?
        ''', (producto_id, limite))
        
        movimientos = [dict(row) for row in cursor.fetchall()]
        
        # Obtener stock actual
        producto = self.productos_repo.obtener_por_id(producto_id)
        stock_actual = producto.stock if producto else 0
        
        # Calcular stock en cada punto (yendo hacia atrás desde el actual)
        for i, mov in enumerate(movimientos):
            if i == 0:
                mov['stock_despues'] = stock_actual
            else:
                mov_anterior = movimientos[i-1]
                if mov['tipo'].startswith('ENTRADA'):
                    mov['stock_despues'] = mov_anterior['stock_despues'] - mov['cantidad']
                else:
                    mov['stock_despues'] = mov_anterior['stock_despues'] + mov['cantidad']
        
        conn.close()
        return movimientos