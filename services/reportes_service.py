# -*- coding: utf-8 -*-
"""
Servicio de Reportes y EstadÃ­sticas
Genera reportes del sistema
"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import sqlite3


class ReportesService:
    """Servicio para generar reportes y estadÃ­sticas"""
    
    def __init__(self, db_manager):
        self.db = db_manager
    
    def dashboard_principal(self, usuario_id=None) -> Dict:
        """Obtiene datos para el dashboard principal.
        Si se pasa usuario_id, filtra ventas sólo de ese usuario."""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        resultado = {}
        
        # Ventas de hoy (dinero real: para crédito usa monto_pagado)
        if usuario_id is not None:
            cursor.execute("""
                SELECT COUNT(*) as ventas,
                       COALESCE(SUM(
                           CASE WHEN metodo_pago='CREDITO' THEN monto_pagado
                                ELSE total END
                       ), 0) as monto
                FROM ventas
                WHERE DATE(datetime(fecha,'localtime')) = DATE('now','localtime')
                  AND estado = 'COMPLETADA'
                  AND usuario_id = ?
            """, (usuario_id,))
        else:
            cursor.execute("""
                SELECT COUNT(*) as ventas,
                       COALESCE(SUM(
                           CASE WHEN metodo_pago='CREDITO' THEN monto_pagado
                                ELSE total END
                       ), 0) as monto
                FROM ventas
                WHERE DATE(datetime(fecha,'localtime')) = DATE('now','localtime')
                  AND estado = 'COMPLETADA'
            """)
        row = cursor.fetchone()
        resultado['ventas_hoy'] = {
            'ventas_hoy': row['ventas'],
            'monto_hoy': row['monto']
        }
        
        # Ventas del mes (dinero real: para crédito usa monto_pagado)
        if usuario_id is not None:
            cursor.execute("""
                SELECT COUNT(*) as ventas,
                       COALESCE(SUM(
                           CASE WHEN metodo_pago='CREDITO' THEN monto_pagado
                                ELSE total END
                       ), 0) as monto
                FROM ventas
                WHERE strftime('%Y-%m', datetime(fecha,'localtime')) = strftime('%Y-%m','now','localtime')
                  AND estado = 'COMPLETADA'
                  AND usuario_id = ?
            """, (usuario_id,))
        else:
            cursor.execute("""
                SELECT COUNT(*) as ventas,
                       COALESCE(SUM(
                           CASE WHEN metodo_pago='CREDITO' THEN monto_pagado
                                ELSE total END
                       ), 0) as monto
                FROM ventas
                WHERE strftime('%Y-%m', datetime(fecha,'localtime')) = strftime('%Y-%m','now','localtime')
                  AND estado = 'COMPLETADA'
            """)
        row = cursor.fetchone()
        resultado['ventas_mes'] = {
            'ventas_mes': row['ventas'],
            'monto_mes': row['monto']
        }
        
        # Productos con stock crÃ­tico
        cursor.execute("""
            SELECT COUNT(*) as total
            FROM productos
            WHERE stock <= stock_minimo AND activo = 1
        """)
        resultado['stock_critico'] = cursor.fetchone()['total']
        
        # Cuentas por cobrar
        cursor.execute("""
            SELECT COUNT(*) as cuentas, COALESCE(SUM(saldo_pendiente), 0) as monto
            FROM cuentas_por_cobrar
            WHERE estado = 'PENDIENTE'
        """)
        row = cursor.fetchone()
        resultado['cuentas_cobrar'] = {
            'cuentas_pendientes': row['cuentas'],
            'monto_pendiente': row['monto']
        }

        # Gráfico últimos 7 días (respeta filtro usuario si aplica)
        if usuario_id is not None:
            cursor.execute("""
                SELECT DATE(datetime(fecha,'localtime')) as fecha,
                       COALESCE(SUM(
                           CASE WHEN metodo_pago='CREDITO' THEN monto_pagado
                                ELSE total END
                       ), 0) as monto
                FROM ventas
                WHERE DATE(datetime(fecha,'localtime')) >= DATE('now','-6 days')
                  AND estado = 'COMPLETADA'
                  AND usuario_id = ?
                GROUP BY DATE(datetime(fecha,'localtime'))
                ORDER BY fecha
            """, (usuario_id,))
        else:
            cursor.execute("""
                SELECT DATE(datetime(fecha,'localtime')) as fecha,
                       COALESCE(SUM(
                           CASE WHEN metodo_pago='CREDITO' THEN monto_pagado
                                ELSE total END
                       ), 0) as monto
                FROM ventas
                WHERE DATE(datetime(fecha,'localtime')) >= DATE('now','-6 days')
                  AND estado = 'COMPLETADA'
                GROUP BY DATE(datetime(fecha,'localtime'))
                ORDER BY fecha
            """)
        rows_graf = cursor.fetchall()
        # Rellenar días sin ventas con 0
        from datetime import date, timedelta
        dias = {(date.today() - timedelta(days=i)).isoformat(): 0 for i in range(6, -1, -1)}
        for r in rows_graf:
            if r['fecha'] in dias:
                dias[r['fecha']] = r['monto']
        resultado['grafico_7_dias'] = [{'fecha': f, 'monto': m} for f, m in dias.items()]

        conn.close()
        return resultado

    def detalle_ventas_hoy(self, usuario_id=None) -> dict:
        """Devuelve lista de ventas de hoy + desglose por método de pago."""
        conn = self.db.conectar()
        cursor = conn.cursor()
        hoy = __import__('datetime').date.today().isoformat()

        uid_filter = "AND v.usuario_id = ?" if usuario_id else ""
        params_list = (usuario_id, hoy) if usuario_id else (hoy,)
        cursor.execute(f"""
            SELECT TIME(datetime(v.fecha,'localtime')) as hora,
                   COALESCE(c.nombre,'Consumidor Final') as cliente,
                   v.metodo_pago, v.total, v.monto_pagado,
                   v.estado_pago, u.nombre_completo as vendedor
            FROM ventas v
            LEFT JOIN clientes c ON v.cliente_id = c.id
            LEFT JOIN usuarios u ON v.usuario_id = u.id
            WHERE DATE(datetime(v.fecha,'localtime')) = ?
              {uid_filter}
            ORDER BY v.fecha DESC
        """, (hoy, usuario_id) if usuario_id else (hoy,))
        ventas = [dict(r) for r in cursor.fetchall()]

        cursor.execute(f"""
            SELECT metodo_pago,
                   COUNT(*) as cantidad,
                   COALESCE(SUM(
                       CASE WHEN metodo_pago='CREDITO' THEN monto_pagado
                            ELSE total END
                   ),0) as monto
            FROM ventas
            WHERE DATE(datetime(fecha,'localtime')) = ?
              {uid_filter}
            GROUP BY metodo_pago
        """, (hoy, usuario_id) if usuario_id else (hoy,))
        por_metodo = [dict(r) for r in cursor.fetchall()]

        conn.close()
        return {'ventas': ventas, 'por_metodo': por_metodo}

    def detalle_ventas_mes(self, usuario_id=None) -> dict:
        """Devuelve totales diarios del mes + desglose por método de pago."""
        conn = self.db.conectar()
        cursor = conn.cursor()
        uid_filter = "AND usuario_id = ?" if usuario_id else ""

        cursor.execute(f"""
            SELECT DATE(datetime(fecha,'localtime')) as fecha,
                   COUNT(*) as cantidad,
                   COALESCE(SUM(
                       CASE WHEN metodo_pago='CREDITO' THEN monto_pagado
                            ELSE total END
                   ),0) as monto
            FROM ventas
            WHERE strftime('%Y-%m', datetime(fecha,'localtime')) = strftime('%Y-%m','now')
              {uid_filter}
            GROUP BY DATE(datetime(fecha,'localtime'))
            ORDER BY fecha
        """, (usuario_id,) if usuario_id else ())
        por_dia = [dict(r) for r in cursor.fetchall()]

        cursor.execute(f"""
            SELECT metodo_pago,
                   COUNT(*) as cantidad,
                   COALESCE(SUM(
                       CASE WHEN metodo_pago='CREDITO' THEN monto_pagado
                            ELSE total END
                   ),0) as monto
            FROM ventas
            WHERE strftime('%Y-%m', datetime(fecha,'localtime')) = strftime('%Y-%m','now')
              {uid_filter}
            GROUP BY metodo_pago
        """, (usuario_id,) if usuario_id else ())
        por_metodo = [dict(r) for r in cursor.fetchall()]

        conn.close()
        return {'por_dia': por_dia, 'por_metodo': por_metodo}

    def reporte_ventas_periodo(self, fecha_inicio: str, fecha_fin: str) -> Dict:
        """Genera reporte de ventas en un perÃ­odo"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        resultado = {
            'fecha_inicio': fecha_inicio,
            'fecha_fin': fecha_fin,
            'ventas': [],
            'resumen': {}
        }
        
        # Obtener ventas del perÃ­odo
        cursor.execute("""
            SELECT v.*, c.nombre as cliente_nombre, u.nombre_completo as vendedor
            FROM ventas v
            LEFT JOIN clientes c ON v.cliente_id = c.id
            LEFT JOIN usuarios u ON v.usuario_id = u.id
            WHERE DATE(v.fecha) BETWEEN ? AND ?
            ORDER BY v.fecha DESC
        """, (fecha_inicio, fecha_fin))
        
        resultado['ventas'] = [dict(row) for row in cursor.fetchall()]
        
        # Calcular resumen
        cursor.execute("""
            SELECT 
                COUNT(*) as total_ventas,
                COALESCE(SUM(total), 0) as monto_total,
                COALESCE(SUM(subtotal), 0) as subtotal_total,
                COALESCE(SUM(descuento), 0) as descuento_total,
                COALESCE(SUM(iva), 0) as iva_total,
                COALESCE(AVG(total), 0) as promedio_venta
            FROM ventas
            WHERE DATE(fecha) BETWEEN ? AND ?
        """, (fecha_inicio, fecha_fin))
        
        row = cursor.fetchone()
        resultado['resumen'] = dict(row)
        
        # Ventas por mÃ©todo de pago
        cursor.execute("""
            SELECT metodo_pago, COUNT(*) as cantidad, SUM(total) as monto
            FROM ventas
            WHERE DATE(fecha) BETWEEN ? AND ?
            GROUP BY metodo_pago
        """, (fecha_inicio, fecha_fin))
        
        resultado['por_metodo_pago'] = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        return resultado
    
    def reporte_productos_mas_vendidos(self, fecha_inicio: str, fecha_fin: str, limite: int = 20) -> Dict:
        """Obtiene los productos más vendidos en un período con stock y porcentajes"""
        conn = self.db.conectar()
        cursor = conn.cursor()

        # Total de ingresos en el período para calcular porcentajes
        cursor.execute("""
            SELECT COALESCE(SUM(total), 0) as total_ingresos
            FROM ventas
            WHERE DATE(fecha) BETWEEN ? AND ?
        """, (fecha_inicio, fecha_fin))
        total_ingresos = cursor.fetchone()['total_ingresos'] or 1

        cursor.execute("""
            SELECT 
                p.id,
                p.nombre,
                p.categoria,
                p.marca,
                p.stock,
                p.stock_minimo,
                p.unidad_medida,
                SUM(dv.cantidad) as cantidad_vendida,
                SUM(dv.subtotal) as monto_total,
                COUNT(DISTINCT dv.venta_id) as num_ventas
            FROM detalle_ventas dv
            JOIN productos p ON dv.producto_id = p.id
            JOIN ventas v ON dv.venta_id = v.id
            WHERE DATE(v.fecha) BETWEEN ? AND ?
            GROUP BY p.id
            ORDER BY cantidad_vendida DESC
            LIMIT ?
        """, (fecha_inicio, fecha_fin, limite))

        productos = [dict(row) for row in cursor.fetchall()]

        # Calcular porcentaje de ingresos y estado de stock
        for p in productos:
            p['porcentaje_ingresos'] = round((p['monto_total'] / total_ingresos) * 100, 1)
            stock = p.get('stock', 0) or 0
            stock_min = p.get('stock_minimo', 0) or 0
            if stock <= 0:
                p['estado_stock'] = 'AGOTADO'
            elif stock <= stock_min:
                p['estado_stock'] = 'BAJO'
            else:
                p['estado_stock'] = 'OK'

        # Categoría más rentable
        cursor.execute("""
            SELECT p.categoria, SUM(dv.subtotal) as total_cat
            FROM detalle_ventas dv
            JOIN productos p ON dv.producto_id = p.id
            JOIN ventas v ON dv.venta_id = v.id
            WHERE DATE(v.fecha) BETWEEN ? AND ?
            GROUP BY p.categoria
            ORDER BY total_cat DESC
            LIMIT 1
        """, (fecha_inicio, fecha_fin))
        cat_row = cursor.fetchone()
        categoria_top = dict(cat_row) if cat_row else {'categoria': '-', 'total_cat': 0}

        # Total unidades vendidas
        cursor.execute("""
            SELECT COALESCE(SUM(dv.cantidad), 0) as total_unidades
            FROM detalle_ventas dv
            JOIN ventas v ON dv.venta_id = v.id
            WHERE DATE(v.fecha) BETWEEN ? AND ?
        """, (fecha_inicio, fecha_fin))
        total_unidades = cursor.fetchone()['total_unidades']

        conn.close()
        return {
            'productos': productos,
            'producto_estrella': productos[0] if productos else None,
            'categoria_top': categoria_top,
            'total_unidades': total_unidades,
            'total_ingresos': total_ingresos
        }
    
    def reporte_inventario_actual(self) -> List[Dict]:
        """Genera reporte del inventario actual"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                id,
                codigo_barras,
                nombre,
                categoria,
                marca,
                stock,
                stock_minimo,
                precio_compra,
                precio_venta,
                (stock * precio_compra) as valor_inventario,
                CASE 
                    WHEN stock <= stock_minimo THEN 'CRITICO'
                    WHEN stock <= stock_minimo * 1.5 THEN 'BAJO'
                    ELSE 'NORMAL'
                END as estado_stock
            FROM productos
            WHERE activo = 1
            ORDER BY nombre
        """)
        
        resultado = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return resultado
    
    def reporte_clientes_top(self, limite: int = 20) -> List[Dict]:
        """Obtiene los mejores clientes por volumen de compras"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                c.id,
                c.nombre,
                c.numero_documento,
                c.telefono,
                COUNT(v.id) as total_compras,
                COALESCE(SUM(v.total), 0) as monto_total,
                COALESCE(AVG(v.total), 0) as promedio_compra,
                c.saldo_pendiente
            FROM clientes c
            LEFT JOIN ventas v ON c.id = v.cliente_id
            WHERE c.activo = 1
            GROUP BY c.id
            ORDER BY monto_total DESC
            LIMIT ?
        """, (limite,))
        
        resultado = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return resultado
    
    def reporte_movimientos_inventario(self, fecha_inicio: str, fecha_fin: str) -> List[Dict]:
        """Genera reporte de movimientos de inventario"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                m.*,
                p.nombre as producto_nombre,
                pr.nombre as proveedor_nombre,
                u.nombre_completo as usuario_nombre
            FROM movimientos m
            JOIN productos p ON m.producto_id = p.id
            LEFT JOIN proveedores pr ON m.proveedor_id = pr.id
            LEFT JOIN usuarios u ON m.usuario_id = u.id
            WHERE DATE(m.fecha) BETWEEN ? AND ?
            ORDER BY m.fecha DESC
        """, (fecha_inicio, fecha_fin))
        
        resultado = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return resultado
    
    def reporte_rentabilidad(self, fecha_inicio: str, fecha_fin: str) -> Dict:
        """Calcula la rentabilidad en un perÃ­odo"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        resultado = {}
        
        # Ingresos por ventas
        cursor.execute("""
            SELECT COALESCE(SUM(total), 0) as ingresos_ventas
            FROM ventas
            WHERE DATE(fecha) BETWEEN ? AND ? AND estado = 'COMPLETADA'
        """, (fecha_inicio, fecha_fin))
        resultado['ingresos_ventas'] = cursor.fetchone()['ingresos_ventas']
        
        # Costo de ventas (basado en precio de compra de productos vendidos)
        cursor.execute("""
            SELECT COALESCE(SUM(dv.cantidad * p.precio_compra), 0) as costo_ventas
            FROM detalle_ventas dv
            JOIN productos p ON dv.producto_id = p.id
            JOIN ventas v ON dv.venta_id = v.id
            WHERE DATE(v.fecha) BETWEEN ? AND ?
        """, (fecha_inicio, fecha_fin))
        resultado['costo_ventas'] = cursor.fetchone()['costo_ventas']
        
        # Calcular utilidad bruta
        resultado['utilidad_bruta'] = resultado['ingresos_ventas'] - resultado['costo_ventas']
        
        # Margen de utilidad
        if resultado['ingresos_ventas'] > 0:
            resultado['margen_utilidad'] = (resultado['utilidad_bruta'] / resultado['ingresos_ventas']) * 100
        else:
            resultado['margen_utilidad'] = 0
        
        conn.close()
        return resultado
    
    def reporte_cuentas_por_cobrar(self) -> List[Dict]:
        """Genera reporte de cuentas por cobrar"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                cpc.*,
                c.nombre as cliente_nombre,
                c.numero_documento,
                c.telefono,
                v.numero_factura,
                v.fecha as fecha_venta,
                julianday('now') - julianday(v.fecha) as dias_vencidos
            FROM cuentas_por_cobrar cpc
            JOIN clientes c ON cpc.cliente_id = c.id
            JOIN ventas v ON cpc.venta_id = v.id
            WHERE cpc.estado = 'PENDIENTE'
              AND v.estado_pago != 'PAGADO'
            ORDER BY v.fecha ASC
        """)
        
        resultado = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return resultado

    # ========== MÉTODOS WRAPPER PARA UI (sin parámetros obligatorios) ==========

    def productos_mas_vendidos(self) -> Dict:
        """Wrapper: productos más vendidos del último mes"""
        hoy = datetime.now()
        inicio = (hoy - timedelta(days=30)).strftime('%Y-%m-%d')
        fin = hoy.strftime('%Y-%m-%d')
        productos = self.reporte_productos_mas_vendidos(inicio, fin, 20)
        return {
            'periodo': f'{inicio} a {fin}',
            'top_productos': productos
        }

    def ventas_por_metodo_pago(self, fecha_inicio: str = None, fecha_fin: str = None) -> Dict:
        """Ventas agrupadas por método de pago con porcentajes y comparativa"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        hoy = datetime.now()
        if not fecha_inicio:
            fecha_inicio = (hoy - timedelta(days=30)).strftime('%Y-%m-%d')
        if not fecha_fin:
            fecha_fin = hoy.strftime('%Y-%m-%d')

        # Métodos de pago del período
        cursor.execute("""
            SELECT 
                metodo_pago,
                COUNT(*) as cantidad_ventas,
                COALESCE(SUM(total), 0) as monto_total,
                COALESCE(AVG(total), 0) as promedio_venta
            FROM ventas
            WHERE DATE(fecha) BETWEEN ? AND ?
            GROUP BY metodo_pago
            ORDER BY monto_total DESC
        """, (fecha_inicio, fecha_fin))
        metodos = [dict(row) for row in cursor.fetchall()]

        # Resumen general
        cursor.execute("""
            SELECT COUNT(*) as total_ventas, COALESCE(SUM(total), 0) as total_monto
            FROM ventas WHERE DATE(fecha) BETWEEN ? AND ?
        """, (fecha_inicio, fecha_fin))
        resumen = dict(cursor.fetchone())

        # Calcular porcentajes
        total_monto = resumen.get('total_monto', 0) or 1
        total_ventas = resumen.get('total_ventas', 0) or 1
        for m in metodos:
            m['porcentaje_monto'] = round((m['monto_total'] / total_monto) * 100, 1)
            m['porcentaje_ventas'] = round((m['cantidad_ventas'] / total_ventas) * 100, 1)

        # Método predominante
        metodo_predominante = metodos[0]['metodo_pago'] if metodos else '-'
        pct_predominante = metodos[0]['porcentaje_monto'] if metodos else 0

        # Comparativa con período anterior (misma duración)
        from datetime import date
        d_inicio = datetime.strptime(fecha_inicio, '%Y-%m-%d')
        d_fin = datetime.strptime(fecha_fin, '%Y-%m-%d')
        duracion = (d_fin - d_inicio).days
        ant_fin = (d_inicio - timedelta(days=1)).strftime('%Y-%m-%d')
        ant_inicio = (d_inicio - timedelta(days=duracion + 1)).strftime('%Y-%m-%d')

        cursor.execute("""
            SELECT metodo_pago, COALESCE(SUM(total), 0) as monto_total
            FROM ventas
            WHERE DATE(fecha) BETWEEN ? AND ?
            GROUP BY metodo_pago
        """, (ant_inicio, ant_fin))
        anterior = {row['metodo_pago']: row['monto_total'] for row in cursor.fetchall()}

        for m in metodos:
            monto_ant = anterior.get(m['metodo_pago'], 0)
            if monto_ant > 0:
                m['variacion'] = round(((m['monto_total'] - monto_ant) / monto_ant) * 100, 1)
            else:
                m['variacion'] = None  # Sin datos previos para comparar

        # ── Info de crédito: cobrado vs pendiente ──────────────────────
        credito_info = {}
        cursor.execute("""
            SELECT
                COUNT(*) as facturas_total,
                COALESCE(SUM(total), 0) as total_facturado,
                COALESCE(SUM(monto_pagado), 0) as total_cobrado,
                COUNT(CASE WHEN estado_pago = 'PAGADO' THEN 1 END) as facturas_pagadas
            FROM ventas
            WHERE metodo_pago = 'CREDITO'
              AND DATE(fecha) BETWEEN ? AND ?
        """, (fecha_inicio, fecha_fin))
        row_cred = cursor.fetchone()
        if row_cred and row_cred['facturas_total'] > 0:
            facturado = row_cred['total_facturado']
            cobrado = row_cred['total_cobrado']
            pendiente = facturado - cobrado
            fact_total = row_cred['facturas_total']
            fact_pagadas = row_cred['facturas_pagadas']
            credito_info = {
                'total_facturado': facturado,
                'total_cobrado': cobrado,
                'pendiente': max(pendiente, 0),
                'facturas_total': fact_total,
                'facturas_pagadas': fact_pagadas,
                'facturas_pendientes': fact_total - fact_pagadas,
                'pct_cobrado': round((cobrado / facturado) * 100, 1) if facturado > 0 else 0,
            }

            # Agregar info de pendiente al método CREDITO en la lista
            for m in metodos:
                if m['metodo_pago'] == 'CREDITO':
                    m['pendiente'] = credito_info['pendiente']
                    m['cobrado'] = credito_info['total_cobrado']
                    m['pct_cobrado'] = credito_info['pct_cobrado']
                    break

        conn.close()

        return {
            'fecha_inicio': fecha_inicio,
            'fecha_fin': fecha_fin,
            'resumen': resumen,
            'por_metodo': metodos,
            'metodo_predominante': metodo_predominante,
            'pct_predominante': pct_predominante,
            'credito_info': credito_info,
        }

    def estadisticas_generales(self, fecha_inicio: str = None, fecha_fin: str = None) -> Dict:
        """Estadísticas generales del negocio"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        resultado = {}

        # Total productos activos
        cursor.execute("SELECT COUNT(*) as total FROM productos WHERE activo = 1")
        resultado['total_productos'] = cursor.fetchone()['total']

        # Valor del inventario
        cursor.execute("""
            SELECT COALESCE(SUM(stock * precio_compra), 0) as valor_costo,
                   COALESCE(SUM(stock * precio_venta), 0) as valor_venta
            FROM productos WHERE activo = 1
        """)
        row = cursor.fetchone()
        resultado['valor_inventario_costo'] = row['valor_costo']
        resultado['valor_inventario_venta'] = row['valor_venta']

        # Ventas (filtradas por periodo si se proporcionan fechas)
        if fecha_inicio and fecha_fin:
            cursor.execute(
                "SELECT COUNT(*) as total, COALESCE(SUM(total), 0) as monto FROM ventas WHERE DATE(fecha) BETWEEN ? AND ?",
                (fecha_inicio, fecha_fin))
        else:
            cursor.execute("SELECT COUNT(*) as total, COALESCE(SUM(total), 0) as monto FROM ventas")
        row = cursor.fetchone()
        resultado['total_ventas'] = row['total']
        resultado['monto_total_ventas'] = row['monto']

        # Total clientes
        cursor.execute("SELECT COUNT(*) as total FROM clientes WHERE activo = 1")
        resultado['total_clientes'] = cursor.fetchone()['total']

        # Total proveedores
        cursor.execute("SELECT COUNT(*) as total FROM proveedores WHERE activo = 1")
        resultado['total_proveedores'] = cursor.fetchone()['total']

        # Rentabilidad del periodo
        hoy = datetime.now()
        inicio_r = fecha_inicio if fecha_inicio else hoy.replace(day=1).strftime('%Y-%m-%d')
        fin_r = fecha_fin if fecha_fin else hoy.strftime('%Y-%m-%d')

        cursor.execute("""
            SELECT COALESCE(SUM(v.total), 0) as ingresos,
                   COALESCE(SUM(dv.cantidad * p.precio_compra), 0) as costos
            FROM ventas v
            JOIN detalle_ventas dv ON v.id = dv.venta_id
            JOIN productos p ON dv.producto_id = p.id
            WHERE DATE(v.fecha) BETWEEN ? AND ?
        """, (inicio_r, fin_r))
        row = cursor.fetchone()
        resultado['ingresos_mes'] = row['ingresos']
        resultado['costos_mes'] = row['costos']
        resultado['utilidad_mes'] = row['ingresos'] - row['costos']
        if row['ingresos'] > 0:
            resultado['margen_mes'] = round((row['ingresos'] - row['costos']) / row['ingresos'] * 100, 2)
        else:
            resultado['margen_mes'] = 0

        conn.close()
        return resultado

    # ========== NUEVOS REPORTES ==========

    def comparativa_periodos(self, inicio1: str, fin1: str, inicio2: str, fin2: str) -> Dict:
        """Compara ventas entre dos períodos"""
        conn = self.db.conectar()
        cursor = conn.cursor()

        def obtener_datos_periodo(inicio, fin):
            cursor.execute("""
                SELECT COUNT(*) as total_ventas,
                       COALESCE(SUM(total), 0) as monto_total,
                       COALESCE(AVG(total), 0) as promedio_venta
                FROM ventas WHERE DATE(fecha) BETWEEN ? AND ?
            """, (inicio, fin))
            datos = dict(cursor.fetchone())
            cursor.execute("""
                SELECT COALESCE(SUM(dv.cantidad * p.precio_compra), 0) as costo_total
                FROM detalle_ventas dv
                JOIN productos p ON dv.producto_id = p.id
                JOIN ventas v ON dv.venta_id = v.id
                WHERE DATE(v.fecha) BETWEEN ? AND ?
            """, (inicio, fin))
            datos['costo_total'] = cursor.fetchone()['costo_total']
            datos['utilidad'] = datos['monto_total'] - datos['costo_total']
            return datos

        periodo1 = obtener_datos_periodo(inicio1, fin1)
        periodo2 = obtener_datos_periodo(inicio2, fin2)

        # Calcular variaciones
        variacion = {}
        for key in ['total_ventas', 'monto_total', 'promedio_venta', 'utilidad']:
            val1 = periodo1.get(key, 0)
            val2 = periodo2.get(key, 0)
            if val2 > 0:
                variacion[key] = round(((val1 - val2) / val2) * 100, 2)
            else:
                variacion[key] = 0

        conn.close()
        return {
            'periodo_1': {'rango': f'{inicio1} a {fin1}', **periodo1},
            'periodo_2': {'rango': f'{inicio2} a {fin2}', **periodo2},
            'variacion_porcentual': variacion
        }

    def rotacion_inventario(self) -> List[Dict]:
        """Calcula la rotación de inventario por producto (últimos 90 días)"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        hoy = datetime.now()
        inicio = (hoy - timedelta(days=90)).strftime('%Y-%m-%d')
        fin = hoy.strftime('%Y-%m-%d')

        cursor.execute("""
            SELECT 
                p.id, p.nombre, p.categoria, p.marca,
                p.stock as stock_actual,
                p.precio_compra, p.precio_venta,
                COALESCE(SUM(dv.cantidad), 0) as unidades_vendidas,
                COUNT(DISTINCT dv.venta_id) as num_ventas,
                CASE 
                    WHEN p.stock > 0 THEN ROUND(CAST(COALESCE(SUM(dv.cantidad), 0) AS REAL) / p.stock, 2)
                    ELSE 0
                END as indice_rotacion
            FROM productos p
            LEFT JOIN detalle_ventas dv ON p.id = dv.producto_id
                AND dv.venta_id IN (SELECT id FROM ventas WHERE DATE(fecha) BETWEEN ? AND ?)
            WHERE p.activo = 1
            GROUP BY p.id
            ORDER BY indice_rotacion DESC
        """, (inicio, fin))

        resultado = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return resultado

    def flujo_caja(self, fecha_inicio: str, fecha_fin: str) -> Dict:
        """Genera reporte de flujo de caja (entradas vs salidas)"""
        conn = self.db.conectar()
        cursor = conn.cursor()

        # Ingresos: ventas
        cursor.execute("""
            SELECT COALESCE(SUM(total), 0) as total
            FROM ventas WHERE DATE(fecha) BETWEEN ? AND ?
        """, (fecha_inicio, fecha_fin))
        ingresos_ventas = cursor.fetchone()['total']

        # Ingresos: abonos de cuentas por cobrar
        cursor.execute("""
            SELECT COALESCE(SUM(monto), 0) as total
            FROM pagos_cuentas WHERE DATE(fecha_pago) BETWEEN ? AND ?
        """, (fecha_inicio, fecha_fin))
        ingresos_abonos = cursor.fetchone()['total']

        # Egresos: compras
        cursor.execute("""
            SELECT COALESCE(SUM(total), 0) as total
            FROM compras WHERE DATE(fecha) BETWEEN ? AND ?
        """, (fecha_inicio, fecha_fin))
        egresos_compras = cursor.fetchone()['total']

        # Egresos: gastos de caja
        cursor.execute("""
            SELECT COALESCE(SUM(monto), 0) as total
            FROM egresos_caja WHERE DATE(fecha_egreso) BETWEEN ? AND ?
        """, (fecha_inicio, fecha_fin))
        egresos_gastos = cursor.fetchone()['total']

        # Egresos: desglose por categoría
        cursor.execute("""
            SELECT categoria, COALESCE(SUM(monto), 0) as total
            FROM egresos_caja WHERE DATE(fecha_egreso) BETWEEN ? AND ?
            GROUP BY categoria ORDER BY total DESC
        """, (fecha_inicio, fecha_fin))
        gastos_por_categoria = [dict(row) for row in cursor.fetchall()]

        total_ingresos = ingresos_ventas + ingresos_abonos
        total_egresos = egresos_compras + egresos_gastos
        flujo_neto = total_ingresos - total_egresos

        # Desglose diario
        cursor.execute("""
            SELECT DATE(fecha) as dia, COALESCE(SUM(total), 0) as monto
            FROM ventas WHERE DATE(fecha) BETWEEN ? AND ?
            GROUP BY DATE(fecha) ORDER BY dia
        """, (fecha_inicio, fecha_fin))
        ventas_diarias = [dict(row) for row in cursor.fetchall()]

        conn.close()
        return {
            'periodo': f'{fecha_inicio} a {fecha_fin}',
            'ingresos': {
                'ventas': ingresos_ventas,
                'abonos_cobrados': ingresos_abonos,
                'total': total_ingresos
            },
            'egresos': {
                'compras': egresos_compras,
                'gastos': egresos_gastos,
                'gastos_por_categoria': gastos_por_categoria,
                'total': total_egresos
            },
            'flujo_neto': flujo_neto,
            'ventas_diarias': ventas_diarias
        }
