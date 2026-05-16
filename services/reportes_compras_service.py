# -*- coding: utf-8 -*-
"""
Servicio para reportes de compras a proveedores
"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import sqlite3


class ReportesComprasService:
    """Servicio para generar reportes de compras a proveedores"""
    
    def __init__(self, db_manager, proveedores_repo):
        self.db = db_manager
        self.proveedores_repo = proveedores_repo
    
    def obtener_proveedores_activos(self) -> List[Dict]:
        """Obtiene lista de proveedores activos para los filtros"""
        try:
            conn = self.db.conectar()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT id, nombre, nit 
                FROM proveedores 
                WHERE activo = 1 
                ORDER BY nombre
            ''')
            
            rows = cursor.fetchall()
            conn.close()
            
            proveedores = []
            for row in rows:
                proveedores.append({
                    'id': row['id'],
                    'nombre': row['nombre'],
                    'nit': row['nit']
                })
            
            return proveedores
        except Exception as e:
            print(f"Error obteniendo proveedores: {e}")
            return []
    
    def obtener_compras_por_proveedor(self, proveedor_id: Optional[int] = None,
                                     fecha_inicio: Optional[str] = None,
                                     fecha_fin: Optional[str] = None,
                                     producto_id: Optional[int] = None) -> List[Dict]:
        """
        Obtiene todas las compras realizadas a proveedores con filtros
        
        Returns:
            Lista de diccionarios con información de cada compra
        """
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        query = '''
            SELECT 
                m.id,
                m.fecha,
                m.tipo,
                m.cantidad,
                m.precio_unitario,
                m.costo_total,
                m.num_factura,
                m.en_cajas,
                m.num_cajas,
                m.observaciones,
                p.id as producto_id,
                p.nombre as producto_nombre,
                p.codigo_barras,
                p.categoria,
                p.marca,
                prov.id as proveedor_id,
                prov.nombre as proveedor_nombre,
                prov.nit,
                u.nombre_completo as usuario_nombre
            FROM movimientos m
            INNER JOIN productos p ON m.producto_id = p.id
            LEFT JOIN proveedores prov ON m.proveedor_id = prov.id
            LEFT JOIN usuarios u ON m.usuario_id = u.id
            WHERE m.tipo = 'ENTRADA_COMPRA'
        '''
        
        params = []
        
        # Filtro por proveedor
        if proveedor_id:
            query += ' AND m.proveedor_id = ?'
            params.append(proveedor_id)
        
        # Filtro por fecha inicio
        if fecha_inicio:
            query += ' AND DATE(m.fecha) >= DATE(?)'
            params.append(fecha_inicio)
        
        # Filtro por fecha fin
        if fecha_fin:
            query += ' AND DATE(m.fecha) <= DATE(?)'
            params.append(fecha_fin)
        
        # Filtro por producto
        if producto_id:
            query += ' AND m.producto_id = ?'
            params.append(producto_id)
        
        query += ' ORDER BY m.fecha DESC, prov.nombre'
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        compras = []
        for row in rows:
            compra = {
                'id': row['id'],
                'fecha': row['fecha'],
                'tipo': row['tipo'],
                'cantidad': row['cantidad'],
                'precio_unitario': row['precio_unitario'],
                'costo_total': row['costo_total'],
                'num_factura': row['num_factura'],
                'en_cajas': bool(row['en_cajas']),
                'num_cajas': row['num_cajas'],
                'observaciones': row['observaciones'],
                'producto_id': row['producto_id'],
                'producto_nombre': row['producto_nombre'],
                'codigo_barras': row['codigo_barras'],
                'categoria': row['categoria'],
                'marca': row['marca'],
                'proveedor_id': row['proveedor_id'],
                'proveedor_nombre': row['proveedor_nombre'] or 'Sin proveedor',
                'nit': row['nit'],
                'usuario_nombre': row['usuario_nombre']
            }
            compras.append(compra)
        
        conn.close()
        return compras
    
    def obtener_resumen_por_proveedor(self, fecha_inicio: Optional[str] = None,
                                      fecha_fin: Optional[str] = None) -> List[Dict]:
        """
        Obtiene un resumen de compras agrupado por proveedor
        
        Returns:
            Lista con totales por proveedor
        """
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        query = '''
            SELECT 
                prov.id,
                prov.nombre,
                prov.nit,
                COUNT(DISTINCT m.id) as total_compras,
                SUM(m.cantidad) as total_unidades,
                SUM(m.costo_total) as monto_total,
                COUNT(DISTINCT m.producto_id) as productos_diferentes,
                MAX(m.fecha) as ultima_compra
            FROM movimientos m
            INNER JOIN proveedores prov ON m.proveedor_id = prov.id
            WHERE m.tipo = 'ENTRADA_COMPRA'
        '''
        
        params = []
        
        if fecha_inicio:
            query += ' AND DATE(m.fecha) >= DATE(?)'
            params.append(fecha_inicio)
        
        if fecha_fin:
            query += ' AND DATE(m.fecha) <= DATE(?)'
            params.append(fecha_fin)
        
        query += ' GROUP BY prov.id, prov.nombre, prov.nit ORDER BY monto_total DESC'
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        resumen = []
        for row in rows:
            item = {
                'proveedor_id': row['id'],
                'proveedor_nombre': row['nombre'],
                'nit': row['nit'],
                'total_compras': row['total_compras'],
                'total_unidades': row['total_unidades'],
                'monto_total': row['monto_total'],
                'productos_diferentes': row['productos_diferentes'],
                'ultima_compra': row['ultima_compra']
            }
            resumen.append(item)
        
        conn.close()
        return resumen
    
    def obtener_productos_mas_comprados(self, proveedor_id: Optional[int] = None,
                                       fecha_inicio: Optional[str] = None,
                                       fecha_fin: Optional[str] = None,
                                       limite: int = 10) -> List[Dict]:
        """
        Obtiene los productos más comprados (opcionalmente de un proveedor específico)
        """
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        query = '''
            SELECT 
                p.id,
                p.nombre,
                p.codigo_barras,
                p.categoria,
                p.marca,
                COUNT(m.id) as veces_comprado,
                SUM(m.cantidad) as total_unidades,
                SUM(m.costo_total) as monto_total,
                AVG(m.precio_unitario) as precio_promedio,
                MAX(m.fecha) as ultima_compra
            FROM movimientos m
            INNER JOIN productos p ON m.producto_id = p.id
            WHERE m.tipo = 'ENTRADA_COMPRA'
        '''
        
        params = []
        
        if proveedor_id:
            query += ' AND m.proveedor_id = ?'
            params.append(proveedor_id)
        
        if fecha_inicio:
            query += ' AND DATE(m.fecha) >= DATE(?)'
            params.append(fecha_inicio)
        
        if fecha_fin:
            query += ' AND DATE(m.fecha) <= DATE(?)'
            params.append(fecha_fin)
        
        query += ' GROUP BY p.id, p.nombre ORDER BY total_unidades DESC LIMIT ?'
        params.append(limite)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        productos = []
        for row in rows:
            producto = {
                'producto_id': row['id'],
                'nombre': row['nombre'],
                'codigo_barras': row['codigo_barras'],
                'categoria': row['categoria'],
                'marca': row['marca'],
                'veces_comprado': row['veces_comprado'],
                'total_unidades': row['total_unidades'],
                'monto_total': row['monto_total'],
                'precio_promedio': row['precio_promedio'],
                'ultima_compra': row['ultima_compra']
            }
            productos.append(producto)
        
        conn.close()
        return productos
    
    def obtener_resumen_temporal(self, tipo: str = 'mensual',
                                fecha_inicio: Optional[str] = None,
                                fecha_fin: Optional[str] = None,
                                proveedor_id: Optional[int] = None) -> List[Dict]:
        """
        Obtiene resumen de compras agrupado por período (semanal o mensual)
        
        Args:
            tipo: 'semanal' o 'mensual'
            fecha_inicio: Fecha inicio filtro
            fecha_fin: Fecha fin filtro
            proveedor_id: ID del proveedor (opcional)
        """
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        if tipo == 'semanal':
            agrupacion = "strftime('%Y-W%W', m.fecha)"
            formato = "strftime('%Y-W%W', m.fecha) as periodo"
        else:  # mensual
            agrupacion = "strftime('%Y-%m', m.fecha)"
            formato = "strftime('%Y-%m', m.fecha) as periodo"
        
        query = f'''
            SELECT 
                {formato},
                COUNT(DISTINCT m.id) as total_compras,
                SUM(m.cantidad) as total_unidades,
                SUM(m.costo_total) as monto_total,
                COUNT(DISTINCT m.proveedor_id) as proveedores_diferentes,
                COUNT(DISTINCT m.producto_id) as productos_diferentes
            FROM movimientos m
            WHERE m.tipo = 'ENTRADA_COMPRA'
        '''
        
        params = []
        
        if proveedor_id:
            query += ' AND m.proveedor_id = ?'
            params.append(proveedor_id)
        
        if fecha_inicio:
            query += ' AND DATE(m.fecha) >= DATE(?)'
            params.append(fecha_inicio)
        
        if fecha_fin:
            query += ' AND DATE(m.fecha) <= DATE(?)'
            params.append(fecha_fin)
        
        query += f' GROUP BY {agrupacion} ORDER BY periodo DESC'
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        resumen = []
        for row in rows:
            item = {
                'periodo': row['periodo'],
                'total_compras': row['total_compras'],
                'total_unidades': row['total_unidades'],
                'monto_total': row['monto_total'],
                'proveedores_diferentes': row['proveedores_diferentes'],
                'productos_diferentes': row['productos_diferentes']
            }
            resumen.append(item)
        
        conn.close()
        return resumen
    
    def obtener_estadisticas_generales(self, fecha_inicio: Optional[str] = None,
                                      fecha_fin: Optional[str] = None) -> Dict:
        """
        Obtiene estadísticas generales de compras
        """
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        query_base = '''
            FROM movimientos m
            WHERE m.tipo = 'ENTRADA_COMPRA'
        '''
        
        params = []
        
        if fecha_inicio:
            query_base += ' AND DATE(m.fecha) >= DATE(?)'
            params.append(fecha_inicio)
        
        if fecha_fin:
            query_base += ' AND DATE(m.fecha) <= DATE(?)'
            params.append(fecha_fin)
        
        # Total de compras y monto
        query = f'SELECT COUNT(*) as total, COALESCE(SUM(costo_total), 0) as monto {query_base}'
        cursor.execute(query, params)
        row = cursor.fetchone()
        total_compras = row['total']
        monto_total = row['monto']
        
        # Proveedores activos
        query = f'SELECT COUNT(DISTINCT proveedor_id) {query_base}'
        cursor.execute(query, params)
        proveedores_activos = cursor.fetchone()[0]
        
        # Productos comprados
        query = f'SELECT COUNT(DISTINCT producto_id) {query_base}'
        cursor.execute(query, params)
        productos_comprados = cursor.fetchone()[0]
        
        # Unidades totales
        query = f'SELECT COALESCE(SUM(cantidad), 0) {query_base}'
        cursor.execute(query, params)
        unidades_totales = cursor.fetchone()[0]
        
        # Ticket promedio
        ticket_promedio = monto_total / total_compras if total_compras > 0 else 0
        
        conn.close()
        
        return {
            'total_compras': total_compras,
            'monto_total': monto_total,
            'proveedores_activos': proveedores_activos,
            'productos_comprados': productos_comprados,
            'unidades_totales': unidades_totales,
            'ticket_promedio': ticket_promedio
        }
    
    def obtener_proveedores_principales(self, limite: int = 5,
                                       fecha_inicio: Optional[str] = None,
                                       fecha_fin: Optional[str] = None) -> List[Dict]:
        """
        Obtiene los proveedores principales ordenados por monto de compra
        """
        resumen = self.obtener_resumen_por_proveedor(fecha_inicio, fecha_fin)
        return resumen[:limite]
    
    def exportar_reporte_csv(self, compras: List[Dict], archivo: str):
        """
        Exporta el reporte de compras a un archivo CSV
        """
        import csv
        
        with open(archivo, 'w', newline='', encoding='utf-8-sig') as f:
            if not compras:
                return
            
            fieldnames = [
                'fecha', 'proveedor_nombre', 'nit', 'num_factura',
                'producto_nombre', 'categoria', 'marca', 'cantidad',
                'precio_unitario', 'costo_total', 'observaciones'
            ]
            
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for compra in compras:
                writer.writerow({
                    'fecha': compra['fecha'],
                    'proveedor_nombre': compra['proveedor_nombre'],
                    'nit': compra.get('nit', ''),
                    'num_factura': compra.get('num_factura', ''),
                    'producto_nombre': compra['producto_nombre'],
                    'categoria': compra.get('categoria', ''),
                    'marca': compra.get('marca', ''),
                    'cantidad': compra['cantidad'],
                    'precio_unitario': compra['precio_unitario'],
                    'costo_total': compra['costo_total'],
                    'observaciones': compra.get('observaciones', '')
                })
