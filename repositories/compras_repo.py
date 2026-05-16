# -*- coding: utf-8 -*-
"""
Repositorio para gestión de compras
Capa de acceso a datos para compras a proveedores
"""
from typing import List, Optional, Tuple, Dict
from datetime import datetime
from database import obtener_fecha_actual


class ComprasRepository:
    """Repositorio de compras"""

    def __init__(self, db_manager):
        self.db = db_manager

    def crear_compra(
        self,
        proveedor_id: int,
        productos: List[Dict],  # [{"producto_id": int, "cantidad": int, "precio_unitario": float}]
        numero_factura: str = None,
        tipo_compra: str = 'CONTADO',
        observaciones: str = None,
        usuario_id: int = None,
        monto_pagado_inicial: float = 0.0
    ) -> Tuple[bool, str, Optional[int]]:
        """
        Crea una nueva compra con múltiples productos

        Args:
            proveedor_id: ID del proveedor
            productos: Lista de productos con cantidad y precio
            numero_factura: Número de factura del proveedor
            tipo_compra: 'CONTADO' o 'CREDITO'
            observaciones: Observaciones generales
            usuario_id: ID del usuario que registra la compra

        Returns:
            (éxito, mensaje, id_compra)
        """
        conn = self.db.conectar()
        cursor = conn.cursor()

        try:
            # Validar que hay productos
            if not productos or len(productos) == 0:
                return False, "Debe agregar al menos un producto a la compra", None

            # Calcular totales
            total = 0
            for item in productos:
                subtotal = item['cantidad'] * item['precio_unitario']
                total += subtotal
            # Insertar encabezado de compra (inicializar estado de pago y saldos)
            # Ajustar monto pagado y saldo si se indicó un pago inicial
            monto_pagado = float(monto_pagado_inicial or 0)
            if monto_pagado < 0:
                monto_pagado = 0.0

            saldo_inicial = max(0.0, total - monto_pagado)

            # Determinar estado de pago
            if monto_pagado <= 0:
                estado_pago = 'PENDIENTE'
            elif monto_pagado >= total:
                estado_pago = 'PAGADO'
            else:
                estado_pago = 'PARCIAL'

            cursor.execute('''
                INSERT INTO compras (
                    proveedor_id, numero_factura, fecha, tipo_compra,
                    total, observaciones, usuario_id, estado,
                    estado_pago, monto_pagado, saldo_pendiente
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                proveedor_id,
                numero_factura,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                tipo_compra,
                total,
                observaciones,
                usuario_id,
                'COMPLETADA',
                estado_pago,
                monto_pagado,
                saldo_inicial
            ))

            compra_id = cursor.lastrowid

            # Insertar detalles de compra y actualizar inventario
            for item in productos:
                producto_id = item['producto_id']
                cantidad = item['cantidad']
                precio_unitario = item['precio_unitario']
                subtotal = cantidad * precio_unitario

                # Insertar detalle
                cursor.execute('''
                    INSERT INTO detalle_compras (
                        compra_id, producto_id, cantidad, precio_unitario, subtotal
                    ) VALUES (?, ?, ?, ?, ?)
                ''', (compra_id, producto_id, cantidad, precio_unitario, subtotal))

                # Actualizar stock del producto
                cursor.execute('''
                    UPDATE productos
                    SET stock = stock + ?,
                        precio_compra = ?
                    WHERE id = ?
                ''', (cantidad, precio_unitario, producto_id))

                # Registrar movimiento en inventario (para trazabilidad)
                cursor.execute('''
                    INSERT INTO movimientos (
                        tipo, producto_id, proveedor_id, usuario_id,
                        cantidad, precio_unitario, costo_total,
                        num_factura, observaciones, fecha
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    'ENTRADA_COMPRA',
                    producto_id,
                    proveedor_id,
                    usuario_id,
                    cantidad,
                    precio_unitario,
                    subtotal,
                    numero_factura,
                    f"Compra #{compra_id}",
                    obtener_fecha_actual()
                ))

            conn.commit()
            conn.close()

            return True, f"Compra registrada exitosamente (Total: ${total:,.0f})", compra_id

        except Exception as e:
            conn.rollback()
            conn.close()
            return False, f"Error al crear compra: {str(e)}", None

    def obtener_compra_por_id(self, compra_id: int) -> Optional[Dict]:
        """
        Obtiene una compra por su ID con todos sus detalles

        Returns:
            Diccionario con datos de la compra y lista de productos
        """
        conn = self.db.conectar()
        cursor = conn.cursor()

        try:
            # Obtener encabezado de compra
            cursor.execute('''
                SELECT
                    c.*,
                    p.nombre as proveedor_nombre,
                    u.nombre_completo as usuario_nombre
                FROM compras c
                LEFT JOIN proveedores p ON c.proveedor_id = p.id
                LEFT JOIN usuarios u ON c.usuario_id = u.id
                WHERE c.id = ?
            ''', (compra_id,))

            row = cursor.fetchone()
            if not row:
                conn.close()
                return None

            compra = dict(row)

            # Obtener detalles (productos)
            cursor.execute('''
                SELECT
                    dc.*,
                    p.nombre as producto_nombre,
                    p.codigo_barras,
                    p.unidad_medida
                FROM detalle_compras dc
                INNER JOIN productos p ON dc.producto_id = p.id
                WHERE dc.compra_id = ?
                ORDER BY dc.id
            ''', (compra_id,))

            productos = [dict(row) for row in cursor.fetchall()]
            compra['productos'] = productos

            conn.close()
            return compra

        except Exception as e:
            conn.close()
            print(f"Error obteniendo compra: {e}")
            return None

    def listar_compras_recientes(self, dias: int = 30, limite: int = 100) -> List[Dict]:
        """
        Lista las compras recientes

        Args:
            dias: Número de días hacia atrás
            limite: Cantidad máxima de registros

        Returns:
            Lista de compras
        """
        conn = self.db.conectar()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                SELECT
                    c.id,
                    c.fecha,
                    c.numero_factura,
                    c.tipo_compra,
                    c.total,
                    c.estado,
                    c.estado_pago,
                    c.saldo_pendiente,
                    p.nombre as proveedor_nombre,
                    u.nombre_completo as usuario_nombre,
                    COUNT(dc.id) as cantidad_productos
                FROM compras c
                LEFT JOIN proveedores p ON c.proveedor_id = p.id
                LEFT JOIN usuarios u ON c.usuario_id = u.id
                LEFT JOIN detalle_compras dc ON c.id = dc.compra_id
                WHERE DATE(c.fecha) >= DATE('now', '-' || ? || ' days')
                    OR (c.estado_pago != 'PAGADO' AND c.saldo_pendiente > 0)
                GROUP BY c.id
                ORDER BY c.fecha DESC
                LIMIT ?
            ''', (dias, limite))

            compras = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return compras

        except Exception as e:
            conn.close()
            print(f"Error listando compras: {e}")
            return []

    def obtener_compras_por_proveedor(self, proveedor_id: int, limite: int = 50) -> List[Dict]:
        """
        Obtiene el historial de compras de un proveedor

        Returns:
            Lista de compras realizadas a ese proveedor
        """
        conn = self.db.conectar()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                SELECT
                    c.id,
                    c.fecha,
                    c.numero_factura,
                    c.tipo_compra,
                    c.total,
                    c.estado,
                    u.nombre_completo as usuario_nombre,
                    COUNT(dc.id) as cantidad_productos
                FROM compras c
                LEFT JOIN usuarios u ON c.usuario_id = u.id
                LEFT JOIN detalle_compras dc ON c.id = dc.compra_id
                WHERE c.proveedor_id = ?
                GROUP BY c.id
                ORDER BY c.fecha DESC
                LIMIT ?
            ''', (proveedor_id, limite))

            compras = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return compras

        except Exception as e:
            conn.close()
            print(f"Error obteniendo compras por proveedor: {e}")
            return []

    def obtener_ultimo_precio_compra(self, producto_id: int, proveedor_id: int = None) -> Optional[float]:
        """
        Obtiene el último precio de compra de un producto

        Args:
            producto_id: ID del producto
            proveedor_id: ID del proveedor (opcional, para filtrar por proveedor)

        Returns:
            Precio unitario de la última compra, o None si no hay registros
        """
        conn = self.db.conectar()
        cursor = conn.cursor()

        try:
            if proveedor_id:
                cursor.execute('''
                    SELECT dc.precio_unitario
                    FROM detalle_compras dc
                    INNER JOIN compras c ON dc.compra_id = c.id
                    WHERE dc.producto_id = ? AND c.proveedor_id = ?
                    ORDER BY c.fecha DESC
                    LIMIT 1
                ''', (producto_id, proveedor_id))
            else:
                cursor.execute('''
                    SELECT dc.precio_unitario
                    FROM detalle_compras dc
                    INNER JOIN compras c ON dc.compra_id = c.id
                    WHERE dc.producto_id = ?
                    ORDER BY c.fecha DESC
                    LIMIT 1
                ''', (producto_id,))

            row = cursor.fetchone()
            conn.close()

            return row['precio_unitario'] if row else None

        except Exception as e:
            conn.close()
            print(f"Error obteniendo último precio: {e}")
            return None

    def obtener_estadisticas_compras(self, fecha_inicio: str = None, fecha_fin: str = None) -> Dict:
        """
        Obtiene estadísticas de compras en un rango de fechas

        Returns:
            Diccionario con estadísticas
        """
        conn = self.db.conectar()
        cursor = conn.cursor()

        try:
            where_clause = ""
            params = []

            if fecha_inicio and fecha_fin:
                where_clause = "WHERE DATE(c.fecha) BETWEEN ? AND ?"
                params = [fecha_inicio, fecha_fin]

            cursor.execute(f'''
                SELECT
                    COUNT(DISTINCT c.id) as total_compras,
                    COALESCE(SUM(c.total), 0) as total_monto,
                    COUNT(DISTINCT c.proveedor_id) as total_proveedores,
                    COALESCE(AVG(c.total), 0) as promedio_compra
                FROM compras c
                {where_clause}
            ''', params)

            stats = dict(cursor.fetchone())
            conn.close()
            return stats

        except Exception as e:
            conn.close()
            print(f"Error obteniendo estadísticas: {e}")
            return {
                'total_compras': 0,
                'total_monto': 0,
                'total_proveedores': 0,
                'promedio_compra': 0
            }

    def eliminar_compra(self, compra_id: int) -> Tuple[bool, str]:
        """
        Elimina una compra (marca como cancelada y revierte el inventario)
        IMPORTANTE: Esto es una operación delicada

        Returns:
            (éxito, mensaje)
        """
        conn = self.db.conectar()
        cursor = conn.cursor()

        try:
            # Obtener detalles de la compra
            cursor.execute('''
                SELECT producto_id, cantidad
                FROM detalle_compras
                WHERE compra_id = ?
            ''', (compra_id,))

            detalles = cursor.fetchall()

            # Revertir inventario
            for detalle in detalles:
                cursor.execute('''
                    UPDATE productos
                    SET stock = stock - ?
                    WHERE id = ?
                ''', (detalle['cantidad'], detalle['producto_id']))

            # Marcar compra como cancelada
            cursor.execute('''
                UPDATE compras
                SET estado = 'CANCELADA'
                WHERE id = ?
            ''', (compra_id,))

            conn.commit()
            conn.close()

            return True, "Compra cancelada y stock revertido exitosamente"

        except Exception as e:
            conn.rollback()
            conn.close()
            return False, f"Error al cancelar compra: {str(e)}"
