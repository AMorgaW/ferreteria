# -*- coding: utf-8 -*-
"""
Repositorio para gestión de inventario
Maneja movimientos de entrada y salida de productos
"""
from typing import List, Optional, Tuple
from datetime import datetime
from models import MovimientoInventario

class InventarioRepository:
    """Repositorio de movimientos de inventario"""
    
    def __init__(self, db_manager):
        self.db = db_manager
    
    def registrar_movimiento(self, movimiento: MovimientoInventario) -> Tuple[bool, str]:
        """
        Registra un movimiento de inventario (entrada o salida)
        Actualiza automáticamente el stock del producto
        """
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        try:
            # [OK] CORREGIDO: Usar método estándar conectar() en lugar de ejecutar_query()
            # Verificar que el producto existe y obtener stock actual
            cursor.execute(
                "SELECT id, stock FROM productos WHERE id = ?",
                (movimiento.producto_id,)
            )
            producto = cursor.fetchone()
            
            if not producto:
                conn.close()
                return False, "Producto no encontrado"
            
            stock_actual = producto['stock']
            
            # Calcular nuevo stock según tipo de movimiento
            if movimiento.tipo_movimiento.startswith('ENTRADA'):
                nuevo_stock = stock_actual + movimiento.cantidad
            elif movimiento.tipo_movimiento.startswith('SALIDA'):
                if stock_actual < movimiento.cantidad:
                    conn.close()
                    return False, f"Stock insuficiente. Disponible: {stock_actual}"
                nuevo_stock = stock_actual - movimiento.cantidad
            else:
                conn.close()
                return False, "Tipo de movimiento inválido"
            
            # Insertar movimiento en la tabla
            cursor.execute('''
                INSERT INTO movimientos_inventario (
                    tipo_movimiento, producto_id, proveedor_id, cliente_id,
                    cantidad, precio_unitario, numero_factura, observaciones,
                    usuario_id, fecha
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                movimiento.tipo_movimiento,
                movimiento.producto_id,
                movimiento.proveedor_id,
                movimiento.cliente_id,
                movimiento.cantidad,
                movimiento.precio_unitario,
                movimiento.numero_factura,
                movimiento.observaciones,
                movimiento.usuario_id,
                movimiento.fecha.strftime('%Y-%m-%d %H:%M:%S') if isinstance(movimiento.fecha, datetime) else movimiento.fecha
            ))
            
            movimiento_id = cursor.lastrowid
            
            # Actualizar stock del producto
            cursor.execute('''
                UPDATE productos 
                SET stock = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (nuevo_stock, movimiento.producto_id))
            
            # Si es una entrada de compra, actualizar precio de compra
            if movimiento.tipo_movimiento == 'ENTRADA_COMPRA' and movimiento.precio_unitario > 0:
                cursor.execute('''
                    UPDATE productos
                    SET precio_compra = ?
                    WHERE id = ?
                ''', (movimiento.precio_unitario, movimiento.producto_id))

            from repositories._outbox import encolar
            encolar(conn, "inventory_movement2", movimiento_id, "create", "movimientos_inventario")
            encolar(conn, "product", movimiento.producto_id, "update", "productos")

            conn.commit()
            conn.close()

            return True, f"Movimiento registrado. Nuevo stock: {nuevo_stock}"
            
        except Exception as e:
            conn.rollback()
            conn.close()
            return False, f"Error al registrar movimiento: {str(e)}"
    
    def obtener_movimientos(self, producto_id: Optional[int] = None, 
                           limite: int = 100) -> List[dict]:
        """
        Obtiene el historial de movimientos
        Si producto_id es None, retorna todos los movimientos
        """
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        if producto_id:
            cursor.execute('''
                SELECT 
                    m.*,
                    p.nombre as producto_nombre,
                    p.unidad_medida,
                    prov.nombre as proveedor_nombre,
                    c.nombre as cliente_nombre,
                    u.nombre_completo as usuario_nombre
                FROM movimientos_inventario m
                INNER JOIN productos p ON m.producto_id = p.id
                LEFT JOIN proveedores prov ON m.proveedor_id = prov.id
                LEFT JOIN clientes c ON m.cliente_id = c.id
                LEFT JOIN usuarios u ON m.usuario_id = u.id
                WHERE m.producto_id = ?
                ORDER BY m.fecha DESC
                LIMIT ?
            ''', (producto_id, limite))
        else:
            cursor.execute('''
                SELECT 
                    m.*,
                    p.nombre as producto_nombre,
                    p.unidad_medida,
                    prov.nombre as proveedor_nombre,
                    c.nombre as cliente_nombre,
                    u.nombre_completo as usuario_nombre
                FROM movimientos_inventario m
                INNER JOIN productos p ON m.producto_id = p.id
                LEFT JOIN proveedores prov ON m.proveedor_id = prov.id
                LEFT JOIN clientes c ON m.cliente_id = c.id
                LEFT JOIN usuarios u ON m.usuario_id = u.id
                ORDER BY m.fecha DESC
                LIMIT ?
            ''', (limite,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def obtener_movimiento_por_id(self, movimiento_id: int) -> Optional[dict]:
        """Obtiene un movimiento específico por su ID"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                m.*,
                p.nombre as producto_nombre,
                p.unidad_medida,
                prov.nombre as proveedor_nombre,
                c.nombre as cliente_nombre,
                u.nombre_completo as usuario_nombre
            FROM movimientos_inventario m
            INNER JOIN productos p ON m.producto_id = p.id
            LEFT JOIN proveedores prov ON m.proveedor_id = prov.id
            LEFT JOIN clientes c ON m.cliente_id = c.id
            LEFT JOIN usuarios u ON m.usuario_id = u.id
            WHERE m.id = ?
        ''', (movimiento_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        return dict(row) if row else None
    
    def verificar_factura_existente(self, numero_factura: str, 
                                    proveedor_id: int) -> bool:
        """
        Verifica si ya existe una entrada con el mismo número de factura
        del mismo proveedor
        """
        if not numero_factura or not proveedor_id:
            return False
        
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT COUNT(*) 
            FROM movimientos_inventario
            WHERE numero_factura = ? 
            AND proveedor_id = ?
            AND tipo_movimiento LIKE 'ENTRADA%'
        ''', (numero_factura, proveedor_id))
        
        count = cursor.fetchone()[0]
        conn.close()
        
        return count > 0
    
    def verificar_factura_venta_existente(self, numero_factura: str) -> bool:
        """
        Verifica si ya existe una salida/venta con el mismo número de factura
        """
        if not numero_factura:
            return False
        
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT COUNT(*) 
            FROM movimientos_inventario
            WHERE numero_factura = ?
            AND tipo_movimiento LIKE 'SALIDA%'
        ''', (numero_factura,))
        
        count = cursor.fetchone()[0]
        conn.close()
        
        return count > 0
    
    def obtener_resumen_movimientos(self, fecha_inicio: str = None, 
                                    fecha_fin: str = None) -> dict:
        """
        Obtiene un resumen de movimientos en un rango de fechas
        """
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        # Query base
        where_clause = "WHERE 1=1"
        params = []
        
        if fecha_inicio:
            where_clause += " AND DATE(fecha) >= ?"
            params.append(fecha_inicio)
        
        if fecha_fin:
            where_clause += " AND DATE(fecha) <= ?"
            params.append(fecha_fin)
        
        # Total de entradas
        cursor.execute(f'''
            SELECT 
                COUNT(*) as total_movimientos,
                COALESCE(SUM(cantidad), 0) as total_unidades
            FROM movimientos_inventario
            {where_clause} AND tipo_movimiento LIKE 'ENTRADA%'
        ''', params)
        
        entradas = cursor.fetchone()
        
        # Total de salidas
        cursor.execute(f'''
            SELECT 
                COUNT(*) as total_movimientos,
                COALESCE(SUM(cantidad), 0) as total_unidades
            FROM movimientos_inventario
            {where_clause} AND tipo_movimiento LIKE 'SALIDA%'
        ''', params)
        
        salidas = cursor.fetchone()
        
        conn.close()
        
        return {
            'entradas': {
                'movimientos': entradas['total_movimientos'],
                'unidades': entradas['total_unidades']
            },
            'salidas': {
                'movimientos': salidas['total_movimientos'],
                'unidades': salidas['total_unidades']
            },
            'diferencia_unidades': entradas['total_unidades'] - salidas['total_unidades']
        }
    
    def obtener_productos_mas_movidos(self, tipo_movimiento: str = None, 
                                     limite: int = 10) -> List[dict]:
        """
        Obtiene los productos con más movimientos
        """
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        if tipo_movimiento:
            cursor.execute('''
                SELECT 
                    p.id,
                    p.nombre,
                    p.categoria,
                    COUNT(m.id) as total_movimientos,
                    SUM(m.cantidad) as total_unidades
                FROM movimientos_inventario m
                INNER JOIN productos p ON m.producto_id = p.id
                WHERE m.tipo_movimiento = ?
                GROUP BY p.id, p.nombre, p.categoria
                ORDER BY total_unidades DESC
                LIMIT ?
            ''', (tipo_movimiento, limite))
        else:
            cursor.execute('''
                SELECT 
                    p.id,
                    p.nombre,
                    p.categoria,
                    COUNT(m.id) as total_movimientos,
                    SUM(m.cantidad) as total_unidades
                FROM movimientos_inventario m
                INNER JOIN productos p ON m.producto_id = p.id
                GROUP BY p.id, p.nombre, p.categoria
                ORDER BY total_movimientos DESC
                LIMIT ?
            ''', (limite,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def calcular_valor_inventario(self) -> dict:
        """
        Calcula el valor total del inventario actual
        basado en precio de compra
        """
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                COUNT(*) as total_productos,
                COALESCE(SUM(stock), 0) as total_unidades,
                COALESCE(SUM(stock * precio_compra), 0) as valor_compra,
                COALESCE(SUM(stock * precio_venta), 0) as valor_venta,
                COALESCE(SUM(stock * (precio_venta - precio_compra)), 0) as ganancia_potencial
            FROM productos
            WHERE activo = 1
        ''')
        
        row = cursor.fetchone()
        conn.close()
        
        return dict(row) if row else {}
    
    def obtener_kardex_producto(self, producto_id: int, 
                               fecha_inicio: str = None,
                               fecha_fin: str = None) -> List[dict]:
        """
        Genera el kardex (historial detallado) de un producto
        """
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        where_clause = "WHERE m.producto_id = ?"
        params = [producto_id]
        
        if fecha_inicio:
            where_clause += " AND DATE(m.fecha) >= ?"
            params.append(fecha_inicio)
        
        if fecha_fin:
            where_clause += " AND DATE(m.fecha) <= ?"
            params.append(fecha_fin)
        
        cursor.execute(f'''
            SELECT 
                m.fecha,
                m.tipo_movimiento,
                m.cantidad,
                m.precio_unitario,
                m.numero_factura,
                m.observaciones,
                prov.nombre as proveedor,
                c.nombre as cliente,
                u.nombre_completo as usuario
            FROM movimientos_inventario m
            LEFT JOIN proveedores prov ON m.proveedor_id = prov.id
            LEFT JOIN clientes c ON m.cliente_id = c.id
            LEFT JOIN usuarios u ON m.usuario_id = u.id
            {where_clause}
            ORDER BY m.fecha ASC
        ''', params)
        
        rows = cursor.fetchall()
        
        # Calcular stock acumulado
        kardex = []
        stock_acumulado = 0
        
        for row in rows:
            row_dict = dict(row)
            
            if row_dict['tipo_movimiento'].startswith('ENTRADA'):
                stock_acumulado += row_dict['cantidad']
                entrada = row_dict['cantidad']
                salida = 0
            else:
                stock_acumulado -= row_dict['cantidad']
                entrada = 0
                salida = row_dict['cantidad']
            
            row_dict['entrada'] = entrada
            row_dict['salida'] = salida
            row_dict['stock_acumulado'] = stock_acumulado
            
            kardex.append(row_dict)
        
        conn.close()
        return kardex
    
    def ajustar_stock_directo(self, producto_id: int, nuevo_stock: int, 
                             motivo: str, usuario_id: int) -> Tuple[bool, str]:
        """
        Ajusta el stock de un producto directamente
        Útil para correcciones o inventarios físicos
        """
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        try:
            # Obtener stock actual
            cursor.execute("SELECT stock FROM productos WHERE id = ?", (producto_id,))
            row = cursor.fetchone()
            
            if not row:
                conn.close()
                return False, "Producto no encontrado"
            
            stock_actual = row['stock']
            diferencia = nuevo_stock - stock_actual
            
            # Determinar tipo de ajuste
            if diferencia > 0:
                tipo_movimiento = 'ENTRADA_AJUSTE'
                cantidad = diferencia
            elif diferencia < 0:
                tipo_movimiento = 'SALIDA_AJUSTE'
                cantidad = abs(diferencia)
            else:
                conn.close()
                return True, "No hay diferencia en el stock"
            
            # Registrar movimiento de ajuste
            cursor.execute('''
                INSERT INTO movimientos_inventario (
                    tipo_movimiento, producto_id, cantidad, precio_unitario,
                    observaciones, usuario_id, fecha
                ) VALUES (?, ?, ?, 0, ?, ?, CURRENT_TIMESTAMP)
            ''', (tipo_movimiento, producto_id, cantidad, motivo, usuario_id))
            _mov_aj_id = cursor.lastrowid

            # Actualizar stock
            cursor.execute('''
                UPDATE productos
                SET stock = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (nuevo_stock, producto_id))

            from repositories._outbox import encolar
            encolar(conn, "inventory_movement2", _mov_aj_id, "create", "movimientos_inventario")
            encolar(conn, "product", producto_id, "update", "productos")

            conn.commit()
            conn.close()

            return True, f"Stock ajustado de {stock_actual} a {nuevo_stock}"
            
        except Exception as e:
            conn.rollback()
            conn.close()
            return False, f"Error al ajustar stock: {str(e)}"
    
    def eliminar_movimiento(self, movimiento_id: int, 
                           revertir_stock: bool = True) -> Tuple[bool, str]:
        """
        Elimina un movimiento de inventario
        Si revertir_stock=True, ajusta el stock del producto
        """
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        try:
            # Obtener datos del movimiento
            cursor.execute('''
                SELECT producto_id, tipo_movimiento, cantidad
                FROM movimientos_inventario
                WHERE id = ?
            ''', (movimiento_id,))
            
            movimiento = cursor.fetchone()
            
            if not movimiento:
                conn.close()
                return False, "Movimiento no encontrado"
            
            if revertir_stock:
                # Revertir el efecto en el stock
                cursor.execute("SELECT stock FROM productos WHERE id = ?", 
                             (movimiento['producto_id'],))
                stock_actual = cursor.fetchone()['stock']
                
                if movimiento['tipo_movimiento'].startswith('ENTRADA'):
                    nuevo_stock = stock_actual - movimiento['cantidad']
                else:
                    nuevo_stock = stock_actual + movimiento['cantidad']
                
                if nuevo_stock < 0:
                    conn.close()
                    return False, "No se puede revertir: resultaría en stock negativo"
                
                cursor.execute('''
                    UPDATE productos 
                    SET stock = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (nuevo_stock, movimiento['producto_id']))
            
            # Eliminar el movimiento
            from repositories._outbox import encolar, encolar_borrado
            if revertir_stock:
                encolar(conn, "product", movimiento['producto_id'], "update", "productos")
            encolar_borrado(conn, "inventory_movement2", movimiento_id, "movimientos_inventario")
            cursor.execute('DELETE FROM movimientos_inventario WHERE id = ?',
                         (movimiento_id,))

            conn.commit()
            conn.close()
            
            return True, "Movimiento eliminado exitosamente"
            
        except Exception as e:
            conn.rollback()
            conn.close()
            return False, f"Error al eliminar movimiento: {str(e)}"