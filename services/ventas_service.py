# -*- coding: utf-8 -*-
"""
Servicio de Ventas
Gestiona el proceso de ventas y facturación
"""
from datetime import datetime
from typing import Tuple, List, Optional
from models import Venta, DetalleVenta, MetodoPago, EstadoVenta
from database import obtener_fecha_actual


class VentasService:
    """Servicio para gestionar ventas"""
    
    def __init__(self, db_manager, productos_repo, clientes_repo, auth):
        self.db = db_manager
        self.productos_repo = productos_repo
        self.clientes_repo = clientes_repo
        self.auth = auth
    
    def generar_numero_factura(self) -> str:
        """Genera un número de factura único basado en el MAX del consecutivo del día"""
        conn = self.db.conectar()
        cursor = conn.cursor()

        fecha = datetime.now().strftime("%Y%m%d")
        prefijo = f"{fecha}-"

        # Obtener el mayor consecutivo usado hoy
        cursor.execute('''
            SELECT MAX(CAST(SUBSTR(numero_factura, 10) AS INTEGER)) as ultimo
            FROM ventas
            WHERE numero_factura LIKE ? || '%'
        ''', (prefijo,))

        row = cursor.fetchone()
        ultimo = row['ultimo'] if row and row['ultimo'] is not None else 0
        conn.close()

        numero = f"{prefijo}{ultimo + 1:04d}"
        return numero
    
    def crear_venta(self, cliente_id: Optional[int], detalles: List[DetalleVenta],
                   metodo_pago: str = 'EFECTIVO', descuento_general: float = 0,
                   observaciones: str = None) -> Tuple[bool, str, Optional[int]]:
        """
        Crea una nueva venta
        Returns: (éxito, mensaje, id_venta)
        """
        
        if not detalles:
            return False, "No hay productos en la venta", None
        
        # [OK] CORREGIDO: Validar stock de todos los productos
        for detalle in detalles:
            producto_dict = self.productos_repo.obtener_por_id(detalle.producto_id)
            if not producto_dict:
                return False, f"Producto ID {detalle.producto_id} no encontrado", None

            # Acceso correcto a diccionario
            stock_disponible = producto_dict['stock']
            nombre_producto = producto_dict['nombre']

            if stock_disponible < detalle.cantidad:
                return False, f"Stock insuficiente para {nombre_producto}. Disponible: {stock_disponible}", None

        # Calcular totales (sin IVA)
        subtotal = sum(d.subtotal for d in detalles)
        descuento_total = descuento_general
        total = subtotal - descuento_total

        # Límite de crédito deshabilitado - permitir ventas a crédito sin límite
        # if metodo_pago == 'CREDITO' and cliente_id:
        #     cliente = self.clientes_repo.obtener_cliente(cliente_id)
        #     if cliente and not cliente.tiene_credito_disponible(total):
        #         return False, "Cliente ha excedido su límite de crédito", None
        
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        try:
            # Generar número de factura
            num_factura = self.generar_numero_factura()
            
            # Validar usuario autenticado
            usuario_id = self.auth.usuario_actual.id if self.auth.usuario_actual else None
            if not usuario_id:
                return False, "Error: Usuario no autenticado. No se puede registrar venta", None
            
            # Insertar venta (con fecha y estado explícitos)
            cursor.execute('''
                INSERT INTO ventas 
                (numero_factura, cliente_id, usuario_id, subtotal, descuento, 
                 iva, total, metodo_pago, observaciones, fecha, estado)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 'COMPLETADA')
            ''', (num_factura, cliente_id, usuario_id, subtotal, descuento_total,
                  0, total, metodo_pago, observaciones))
            
            venta_id = cursor.lastrowid
            
            # Insertar detalles y actualizar stock
            for detalle in detalles:
                cursor.execute('''
                    INSERT INTO detalle_ventas
                    (venta_id, producto_id, cantidad, precio_unitario, descuento, subtotal, iva)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (venta_id, detalle.producto_id, detalle.cantidad,
                      detalle.precio_unitario, detalle.descuento,
                      detalle.subtotal, 0))
                
                # Actualizar stock
                cursor.execute('''
                    UPDATE productos
                    SET stock = stock - ?
                    WHERE id = ?
                ''', (detalle.cantidad, detalle.producto_id))

                # [OK] MEJORA: Registrar movimiento de salida automáticamente
                cursor.execute('''
                    INSERT INTO movimientos (
                        tipo, producto_id, usuario_id, cantidad,
                        precio_unitario, costo_total, motivo, num_factura, fecha
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    'SALIDA_VENTA',
                    detalle.producto_id,
                    usuario_id,
                    detalle.cantidad,
                    detalle.precio_unitario,
                    detalle.subtotal,
                    f'Venta {num_factura}',
                    num_factura,
                    obtener_fecha_actual()
                ))
            
            # Si es crédito, crear cuenta por cobrar
            if metodo_pago == 'CREDITO' and cliente_id:
                cursor.execute('''
                    INSERT INTO cuentas_por_cobrar
                    (venta_id, cliente_id, monto_total, saldo_pendiente, fecha_vencimiento)
                    VALUES (?, ?, ?, ?, datetime('now', '+30 days'))
                ''', (venta_id, cliente_id, total, total))
                
                # Actualizar saldo del cliente
                cursor.execute('''
                    UPDATE clientes
                    SET saldo_pendiente = saldo_pendiente + ?
                    WHERE id = ?
                ''', (total, cliente_id))
            
            conn.commit()
            
            # Registrar auditoría
            if self.auth.usuario_actual:
                self.auth.registrar_auditoria(
                    self.auth.usuario_actual.id,
                    "VENTA",
                    "Ventas",
                    f"Venta {num_factura} por ${total:,.0f}"
                )
            
            conn.close()
            return True, f"Venta {num_factura} registrada exitosamente", venta_id
            
        except Exception as e:
            conn.rollback()
            conn.close()
            return False, f"Error al registrar venta: {str(e)}", None

    def registrar_venta(self, items: List[dict], cliente_id: Optional[int] = None,
                       metodo_pago: str = 'EFECTIVO', descuento_general: float = 0,
                       observaciones: str = None) -> Tuple[bool, str, Optional[Venta]]:
        """
        [OK] MÉTODO MEJORADO: Recibe items como lista de diccionarios
        Compatible con VentasUI
        Returns: (éxito, mensaje, objeto_venta)
        """
        try:
            # Convertir items de dict a DetalleVenta
            detalles = []
            for item in items:
                # Obtener producto para calcular IVA
                producto_dict = self.productos_repo.obtener_por_id(item['producto_id'])
                if not producto_dict:
                    return False, f"Producto ID {item['producto_id']} no encontrado", None

                precio_unitario = item['precio_unitario']
                cantidad = item['cantidad']
                descuento_item = item.get('descuento', 0)

                # Calcular subtotal (sin IVA)
                subtotal_item = (precio_unitario * cantidad) - descuento_item
                iva_item = 0  # IVA eliminado

                detalle = DetalleVenta(
                    producto_id=item['producto_id'],
                    cantidad=cantidad,
                    precio_unitario=precio_unitario,
                    descuento=descuento_item,
                    subtotal=subtotal_item,
                    iva=iva_item
                )
                detalles.append(detalle)

            # Usar el método principal
            exito, mensaje, venta_id = self.crear_venta(
                cliente_id=cliente_id,
                detalles=detalles,
                metodo_pago=metodo_pago,
                descuento_general=descuento_general,
                observaciones=observaciones
            )

            if exito and venta_id:
                # Obtener la venta completa y convertir a objeto
                venta_dict = self.obtener_venta(venta_id)
                if venta_dict:
                    venta = Venta(
                        id=venta_dict['id'],
                        numero_factura=venta_dict['numero_factura'],
                        fecha=venta_dict['fecha'],
                        cliente_id=venta_dict.get('cliente_id'),
                        usuario_id=venta_dict.get('usuario_id'),
                        subtotal=venta_dict['subtotal'],
                        descuento=venta_dict['descuento'],
                        iva=venta_dict['iva'],
                        total=venta_dict['total'],
                        metodo_pago=venta_dict['metodo_pago'],
                        estado=venta_dict.get('estado', 'COMPLETADA'),
                        observaciones=venta_dict.get('observaciones')
                    )
                    return True, mensaje, venta
                else:
                    return True, mensaje, None
            else:
                return False, mensaje, None

        except Exception as e:
            return False, f"Error procesando venta: {str(e)}", None

    def obtener_venta(self, venta_id: int) -> Optional[dict]:
        """Obtiene una venta con sus detalles"""
        
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        # Obtener venta
        cursor.execute('''
            SELECT v.*, c.nombre as cliente_nombre, u.nombre_completo as vendedor
            FROM ventas v
            LEFT JOIN clientes c ON v.cliente_id = c.id
            LEFT JOIN usuarios u ON v.usuario_id = u.id
            WHERE v.id = ?
        ''', (venta_id,))
        
        venta = cursor.fetchone()
        if not venta:
            conn.close()
            return None
        
        venta_dict = dict(venta)
        
        # Obtener detalles
        cursor.execute('''
            SELECT dv.*, p.nombre as producto_nombre
            FROM detalle_ventas dv
            JOIN productos p ON dv.producto_id = p.id
            WHERE dv.venta_id = ?
        ''', (venta_id,))
        
        venta_dict['detalles'] = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        return venta_dict
    
    def obtener_venta_por_factura(self, numero_factura: str) -> Optional[dict]:
        """Obtiene una venta por número de factura"""
        
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        # Obtener venta
        cursor.execute('''
            SELECT v.*, c.nombre as cliente_nombre, u.nombre_completo as vendedor
            FROM ventas v
            LEFT JOIN clientes c ON v.cliente_id = c.id
            LEFT JOIN usuarios u ON v.usuario_id = u.id
            WHERE v.numero_factura = ?
        ''', (numero_factura,))
        
        venta = cursor.fetchone()
        if not venta:
            conn.close()
            return None
        
        venta_dict = dict(venta)
        
        # Obtener detalles
        cursor.execute('''
            SELECT dv.*, p.nombre as producto_nombre
            FROM detalle_ventas dv
            JOIN productos p ON dv.producto_id = p.id
            WHERE dv.venta_id = ?
        ''', (venta_dict['id'],))
        
        venta_dict['detalles'] = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        return venta_dict
    
    def listar_ventas(self, fecha_inicio: str = None, fecha_fin: str = None,
                     cliente_id: int = None, limite: int = 100) -> List[dict]:
        """Lista ventas con filtros opcionales"""
        
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        query = '''
            SELECT v.*, c.nombre as cliente_nombre, u.nombre_completo as vendedor
            FROM ventas v
            LEFT JOIN clientes c ON v.cliente_id = c.id
            LEFT JOIN usuarios u ON v.usuario_id = u.id
            WHERE 1=1
        '''
        params = []
        
        if fecha_inicio:
            query += " AND DATE(v.fecha) >= ?"
            params.append(fecha_inicio)
        
        if fecha_fin:
            query += " AND DATE(v.fecha) <= ?"
            params.append(fecha_fin)
        
        if cliente_id:
            query += " AND v.cliente_id = ?"
            params.append(cliente_id)
        
        query += " ORDER BY v.fecha DESC LIMIT ?"
        params.append(limite)
        
        cursor.execute(query, params)
        ventas = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        return ventas
    
    def cancelar_venta(self, venta_id: int, motivo: str) -> Tuple[bool, str]:
        """Cancela una venta y revierte el inventario"""
        
        # Obtener venta con detalles
        venta = self.obtener_venta(venta_id)
        if not venta:
            return False, "Venta no encontrada"
        
        if venta['estado'] == 'CANCELADA':
            return False, "La venta ya está cancelada"
        
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        try:
            # Marcar venta como cancelada
            cursor.execute('''
                UPDATE ventas
                SET estado = 'CANCELADA',
                    observaciones = observaciones || ' | CANCELADA: ' || ?
                WHERE id = ?
            ''', (motivo, venta_id))
            
            # Revertir stock y registrar movimiento
            usuario_id = self.auth.usuario_actual.id if self.auth.usuario_actual else None

            for detalle in venta['detalles']:
                cursor.execute('''
                    UPDATE productos
                    SET stock = stock + ?
                    WHERE id = ?
                ''', (detalle['cantidad'], detalle['producto_id']))

                # [OK] MEJORA: Registrar movimiento de devolución
                cursor.execute('''
                    INSERT INTO movimientos (
                        tipo, producto_id, usuario_id, cantidad,
                        precio_unitario, costo_total, motivo, num_factura, fecha
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    'ENTRADA_DEVOLUCION',
                    detalle['producto_id'],
                    usuario_id,
                    detalle['cantidad'],
                    detalle['precio_unitario'],
                    detalle['subtotal'],
                    f'Cancelación de venta {venta["numero_factura"]}: {motivo}',
                    venta['numero_factura'],
                    obtener_fecha_actual()
                ))
            
            # Si era crédito, revertir cuenta por cobrar
            if venta['metodo_pago'] == 'CREDITO':
                cursor.execute('''
                    UPDATE cuentas_por_cobrar
                    SET estado = 'CANCELADA'
                    WHERE venta_id = ?
                ''', (venta_id,))
                
                if venta['cliente_id']:
                    cursor.execute('''
                        UPDATE clientes
                        SET saldo_pendiente = saldo_pendiente - ?
                        WHERE id = ?
                    ''', (venta['total'], venta['cliente_id']))
            
            conn.commit()
            
            # Registrar auditoría
            if self.auth.usuario_actual:
                self.auth.registrar_auditoria(
                    self.auth.usuario_actual.id,
                    "CANCELAR_VENTA",
                    "Ventas",
                    f"Venta {venta['numero_factura']} cancelada. Motivo: {motivo}"
                )
            
            conn.close()
            return True, "Venta cancelada exitosamente"
            
        except Exception as e:
            conn.rollback()
            conn.close()
            return False, f"Error al cancelar venta: {str(e)}"
    
    def agregar_productos_a_factura(self, venta_id: int, nuevos_items: List[dict]) -> Tuple[bool, str]:
        """
        Agrega productos a una factura de crédito existente
        Args:
            venta_id: ID de la venta existente
            nuevos_items: Lista de dicts con {producto_id, cantidad, precio_unitario, descuento}
        Returns: (éxito, mensaje)
        """
        if not nuevos_items:
            return False, "No hay productos para agregar"
        
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        try:
            # Verificar que la venta existe y es a crédito
            cursor.execute('''
                SELECT id, numero_factura, metodo_pago, total, estado_pago, cliente_id
                FROM ventas WHERE id = ?
            ''', (venta_id,))
            
            venta = cursor.fetchone()
            if not venta:
                conn.close()
                return False, "Venta no encontrada"
            
            if venta['metodo_pago'] != 'CREDITO':
                conn.close()
                return False, "Solo se pueden agregar productos a ventas a crédito"
            
            if venta['estado_pago'] == 'PAGADO':
                conn.close()
                return False, "No se pueden agregar productos a una venta ya pagada"
            
            # Validar stock y agregar productos
            nuevos_detalles = []
            total_nuevo = 0
            
            for item in nuevos_items:
                producto_dict = self.productos_repo.obtener_por_id(item['producto_id'])
                if not producto_dict:
                    conn.close()
                    return False, f"Producto ID {item['producto_id']} no encontrado"
                
                stock_disponible = producto_dict['stock']
                if stock_disponible < item['cantidad']:
                    conn.close()
                    return False, f"Stock insuficiente para {producto_dict['nombre']}. Disponible: {stock_disponible}"
                
                # Calcular subtotal (sin IVA)
                precio = item['precio_unitario']
                cantidad = item['cantidad']
                descuento = item.get('descuento', 0)
                subtotal = (precio * cantidad) - descuento
                
                nuevos_detalles.append({
                    'producto_id': item['producto_id'],
                    'cantidad': cantidad,
                    'precio_unitario': precio,
                    'descuento': descuento,
                    'subtotal': subtotal,
                    'iva': 0,
                    'nombre_producto': producto_dict['nombre'],
                    'tipo_unidad': item.get('tipo_unidad', 'Unidad'),
                })
                
                total_nuevo += subtotal
            
            # Insertar nuevos detalles
            for detalle in nuevos_detalles:
                cursor.execute('''
                    INSERT INTO detalle_ventas (
                        venta_id, producto_id, cantidad, precio_unitario, 
                        descuento, subtotal, iva, tipo_unidad
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    venta_id,
                    detalle['producto_id'],
                    detalle['cantidad'],
                    detalle['precio_unitario'],
                    detalle['descuento'],
                    detalle['subtotal'],
                    detalle['iva'],
                    detalle.get('tipo_unidad', 'Unidad'),
                ))
                
                # Reducir stock
                cursor.execute('''
                    UPDATE productos 
                    SET stock = stock - ? 
                    WHERE id = ?
                ''', (detalle['cantidad'], detalle['producto_id']))
                
                # Registrar movimiento
                usuario_id = self.auth.usuario_actual.id if self.auth.usuario_actual else None
                cursor.execute('''
                    INSERT INTO movimientos (
                        tipo, producto_id, usuario_id, cantidad,
                        precio_unitario, costo_total, motivo, num_factura, fecha
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    'SALIDA_VENTA',
                    detalle['producto_id'],
                    usuario_id,
                    detalle['cantidad'],
                    detalle['precio_unitario'],
                    detalle['subtotal'],  # Costo total sin IVA
                    f'Adición a factura {venta["numero_factura"]}',
                    venta['numero_factura'],
                    obtener_fecha_actual()
                ))
            
            # Actualizar total de la venta
            nuevo_total = venta['total'] + total_nuevo
            cursor.execute('''
                UPDATE ventas 
                SET total = ?, subtotal = subtotal + ?
                WHERE id = ?
            ''', (
                nuevo_total,
                sum(d['subtotal'] for d in nuevos_detalles),
                venta_id
            ))
            
            # Actualizar saldo pendiente del cliente si es a crédito
            # NOTA: saldo_pendiente se calcula dinámicamente desde ventas, no se almacena
            # if venta['cliente_id']:
            #     cursor.execute('''
            #         UPDATE clientes
            #         SET saldo_pendiente = saldo_pendiente + ?
            #         WHERE id = ?
            #     ''', (total_nuevo, venta['cliente_id']))
            
            # El saldo pendiente se calcula dinámicamente, no se actualiza en la tabla
            
            conn.commit()
            
            # Registrar auditoría
            if self.auth.usuario_actual:
                self.auth.registrar_auditoria(
                    self.auth.usuario_actual.id,
                    "AGREGAR_PRODUCTOS_FACTURA",
                    "Ventas",
                    f"Se agregaron {len(nuevos_items)} productos a factura {venta['numero_factura']} por ${total_nuevo:,.0f}"
                )
            
            conn.close()
            return True, f"Productos agregados exitosamente. Nuevo total: ${nuevo_total:,.0f}"
            
        except Exception as e:
            conn.rollback()
            conn.close()
            return False, f"Error al agregar productos: {str(e)}"