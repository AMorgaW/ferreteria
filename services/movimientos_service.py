# -*- coding: utf-8 -*-
"""
Servicio de gestión de movimientos de inventario
Maneja entradas, salidas y actualización de stock
"""
from typing import Tuple, List, Optional
from datetime import datetime


def _reconciliar_pagos_proveedor():
    try:
        from repositories.abonos_compras_repo import reconciliar_pagos_proveedor_huerfanos
        reconciliar_pagos_proveedor_huerfanos()
    except Exception as e:
        print(f"[MOVIMIENTOS] No se pudieron reconciliar pagos a proveedor: {e}")


def _reconciliar_movimientos_inventario_huerfanos(db):
    conn = db.conectar()
    cursor = conn.cursor()
    creados = 0

    try:
        from repositories._outbox import encolar

        cursor.execute('''
            SELECT c.id AS compra_id, c.numero_factura, c.proveedor_id,
                   c.usuario_id, c.fecha, dc.producto_id, dc.cantidad,
                   dc.precio_unitario, dc.subtotal
            FROM compras c
            JOIN detalle_compras dc ON dc.compra_id = c.id
            WHERE c.estado = 'COMPLETADA'
              AND NOT EXISTS (
                  SELECT 1
                  FROM movimientos m
                  WHERE m.tipo = 'ENTRADA_COMPRA'
                    AND (
                        m.observaciones = ('Compra #' || CAST(c.id AS TEXT))
                        OR (
                            c.numero_factura IS NOT NULL
                            AND m.num_factura = c.numero_factura
                        )
                    )
              )
        ''')
        compras = cursor.fetchall()

        for row in compras:
            cursor.execute('''
                INSERT INTO movimientos (
                    tipo, producto_id, proveedor_id, usuario_id,
                    cantidad, precio_unitario, costo_total,
                    num_factura, observaciones, fecha
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                'ENTRADA_COMPRA',
                row['producto_id'],
                row['proveedor_id'],
                row['usuario_id'],
                row['cantidad'],
                row['precio_unitario'],
                row['subtotal'],
                row['numero_factura'],
                f"Compra #{row['compra_id']}",
                str(row['fecha'])[:19]
            ))
            encolar(conn, "inventory_movement", cursor.lastrowid, "create", "movimientos")
            creados += 1

        cursor.execute('''
            SELECT v.id AS venta_id, v.numero_factura, v.usuario_id, v.fecha,
                   dv.producto_id, dv.cantidad, dv.precio_unitario, dv.subtotal
            FROM ventas v
            JOIN detalle_ventas dv ON dv.venta_id = v.id
            WHERE v.estado = 'COMPLETADA'
              AND v.numero_factura IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM movimientos m
                  WHERE m.tipo = 'SALIDA_VENTA'
                    AND m.num_factura = v.numero_factura
              )
        ''')
        ventas = cursor.fetchall()

        for row in ventas:
            cursor.execute('''
                INSERT INTO movimientos (
                    tipo, producto_id, usuario_id, cantidad,
                    precio_unitario, costo_total, motivo, num_factura, fecha
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                'SALIDA_VENTA',
                row['producto_id'],
                row['usuario_id'],
                row['cantidad'],
                row['precio_unitario'],
                row['subtotal'],
                f"Venta {row['numero_factura']}",
                row['numero_factura'],
                str(row['fecha'])[:19]
            ))
            encolar(conn, "inventory_movement", cursor.lastrowid, "create", "movimientos")
            creados += 1

        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[MOVIMIENTOS] No se pudieron reconciliar movimientos huérfanos: {e}")
    finally:
        conn.close()

    return creados


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
                            en_cajas: bool = False, num_cajas: int = 0,
                            inventory_mode: Optional[str] = None,
                            inventory_command_id: Optional[str] = None,
                            inventory_gateway=None,
                            inventory_transport=None,
                            inventory_connection_factory=None) -> Tuple[bool, str]:
        """
        Registra un movimiento de inventario y actualiza el stock
        Returns: (éxito, mensaje)
        """
        from inventory_writer_support import WRITER_MODE_AUTHORITATIVE, resolve_writer_mode_or_frozen

        mode, frozen = resolve_writer_mode_or_frozen(
            inventory_mode, db=self.db,
            connection_factory=inventory_connection_factory,
        )
        if frozen:
            return False, frozen
        if mode == WRITER_MODE_AUTHORITATIVE:
            return self._registrar_movimiento_authoritative(
                tipo, producto_id, cantidad, precio_unitario, proveedor_id,
                num_factura, observaciones, en_cajas, num_cajas,
                inventory_command_id=inventory_command_id,
                inventory_gateway=inventory_gateway,
                inventory_transport=inventory_transport,
                inventory_connection_factory=inventory_connection_factory,
            )

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
            if producto['stock'] < cantidad:
                return False, f"Stock insuficiente. Disponible: {producto['stock']}"
        
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
                nuevo_stock = producto['stock'] + cantidad
            else:  # SALIDA
                nuevo_stock = producto['stock'] - cantidad
            
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

            # Local-first: encolar el movimiento y el producto (stock/precio).
            from repositories._outbox import encolar
            encolar(conn, "inventory_movement", movimiento_id, "create", "movimientos")
            encolar(conn, "product", producto_id, "update", "productos")

            from inventory_cutover import commit_legacy_inventory

            commit_legacy_inventory(
                conn, connection_factory=inventory_connection_factory
            )
            
            # Registrar en auditoría
            self.auth.registrar_auditoria(
                self.auth.usuario_actual.id if self.auth.usuario_actual else None,
                "MOVIMIENTO_INVENTARIO",
                "Movimientos",
                f"{tipo}: {producto['nombre']} - Cantidad: {cantidad} - Nuevo stock: {nuevo_stock}"
            )
            
            conn.close()
            
            tipo_texto = tipo.replace('_', ' ').title()
            return True, f"{tipo_texto} registrada exitosamente. Stock actualizado a {nuevo_stock}"
        
        except Exception as e:
            conn.rollback()
            conn.close()
            return False, f"Error al registrar movimiento: {str(e)}"

    def _registrar_movimiento_authoritative(
        self, tipo, producto_id, cantidad, precio_unitario, proveedor_id,
        num_factura, observaciones, en_cajas, num_cajas, *,
        inventory_command_id, inventory_gateway, inventory_transport,
        inventory_connection_factory,
    ) -> Tuple[bool, str]:
        import uuid as _uuid
        from inventory_gateway import OUTCOME_APPLIED, OUTCOME_REJECTED
        from inventory_ledger import QuantityScaleError, UnknownProductError
        from inventory_writer_support import (
            DOCUMENTO_TIPO_MOVIMIENTO, MissingProductLocalIdError,
            bind_inventory_gateway, build_signed_operations, command_already_applied,
            command_motivo_marker, find_rows_marked_for_command, movement_tipo_to_ledger,
            unknown_writer_message,
        )
        if not self.auth.tiene_permiso('gestionar_movimientos'):
            return False, "No tiene permisos para gestionar movimientos"
        producto = self.productos_repo.obtener_por_id(producto_id)
        if not producto:
            return False, "Producto no encontrado"
        if cantidad <= 0:
            return False, "La cantidad debe ser mayor a cero"
        try:
            ledger_tipo, sign = movement_tipo_to_ledger(tipo)
        except QuantityScaleError as exc:
            return False, str(exc)
        conn = self.db.conectar()
        cursor = conn.cursor()
        command_id = None
        try:
            from inventory_cutover import ACT_KIND_MOVEMENT
            from inventory_writer_support import durable_act_command_id
            command_id = durable_act_command_id(
                conn,
                ACT_KIND_MOVEMENT,
                fingerprint=f"{producto_id}:{tipo}:{cantidad}:{observaciones or ''}",
                explicit_command_id=inventory_command_id,
                open_act=True,
            )
            self.last_inventory_command_id = command_id
            already = command_already_applied(conn, command_id)
            if already is not None:
                marked = find_rows_marked_for_command(conn, command_id, table="movimientos")
                if marked:
                    conn.close()
                    return True, "Movimiento registrado"
            else:
                operations = build_signed_operations(
                    conn, [{"producto_id": producto_id, "delta": sign * cantidad}],
                    command_id=command_id,
                )
                gw = bind_inventory_gateway(
                    conn, gateway=inventory_gateway, transport=inventory_transport,
                    connection_factory=inventory_connection_factory, cutover_enabled=True,
                )
                try:
                    result = gw.submit(
                        tipo=ledger_tipo, operations=operations, command_id=command_id,
                        documento_tipo=DOCUMENTO_TIPO_MOVIMIENTO, device_id=None,
                        usuario_id=self.auth.usuario_actual.id if self.auth.usuario_actual else None,
                    )
                except Exception as exc:
                    conn.close()
                    return False, unknown_writer_message(command_id, str(exc))
                self.last_gateway_result = result
                if result.outcome == OUTCOME_REJECTED:
                    conn.close()
                    return False, result.error or "Inventario rechazado por el coordinador"
                if result.outcome != OUTCOME_APPLIED:
                    conn.close()
                    return False, unknown_writer_message(result.command_id, result.error or result.outcome)
            marker = command_motivo_marker(command_id)
            costo_total = cantidad * precio_unitario
            cursor.execute('''
                INSERT INTO movimientos (
                    tipo, producto_id, proveedor_id, usuario_id, cantidad,
                    precio_unitario, costo_total, motivo, num_factura,
                    en_cajas, num_cajas, observaciones
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                tipo, producto_id, proveedor_id,
                self.auth.usuario_actual.id if self.auth.usuario_actual else None,
                cantidad, precio_unitario, costo_total, marker, num_factura,
                1 if en_cajas else 0, num_cajas, observaciones,
            ))
            from repositories._outbox import encolar
            encolar(conn, "inventory_movement", cursor.lastrowid, "create", "movimientos")
            if tipo == 'ENTRADA_COMPRA' and precio_unitario > 0:
                cursor.execute(
                    "UPDATE productos SET precio_compra = ?, proveedor_id = ? WHERE id = ?",
                    (precio_unitario, proveedor_id, producto_id),
                )
            conn.commit()
            conn.close()
            return True, f"{tipo.replace('_', ' ').title()} registrada exitosamente"
        except (MissingProductLocalIdError, QuantityScaleError, UnknownProductError) as exc:
            try:
                conn.close()
            except Exception:
                pass
            return False, str(exc)
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
            return False, unknown_writer_message(command_id, str(e))
    
    def obtener_historial(self, producto_id: Optional[int] = None,
                         proveedor_id: Optional[int] = None,
                         tipo: Optional[str] = None,
                         fecha_inicio: Optional[str] = None,
                         fecha_fin: Optional[str] = None,
                         limite: int = 100) -> List[dict]:
        """
        Obtiene el historial de movimientos con filtros opcionales
        """
        _reconciliar_movimientos_inventario_huerfanos(self.db)

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

    def obtener_egresos(self, fecha_inicio: Optional[str] = None,
                        fecha_fin: Optional[str] = None,
                        limite: int = 500) -> List[dict]:
        """
        Obtiene los egresos de caja (gastos operativos) para mostrarlos en la
        vista de Movimientos. Son salidas de dinero, no de inventario, por eso
        viven en su propia tabla; aquí se leen para unificar la vista.
        """
        _reconciliar_pagos_proveedor()

        conn = self.db.conectar()
        cursor = conn.cursor()

        query = '''
            SELECT id, monto, categoria, descripcion, metodo_pago,
                   fecha_egreso, usuario
            FROM egresos_caja
            WHERE 1=1
        '''
        params = []
        if fecha_inicio:
            query += " AND DATE(fecha_egreso) >= DATE(?)"
            params.append(fecha_inicio)
        if fecha_fin:
            query += " AND DATE(fecha_egreso) <= DATE(?)"
            params.append(fecha_fin)
        query += " ORDER BY fecha_egreso DESC LIMIT ?"
        params.append(limite)

        try:
            cursor.execute(query, params)
            egresos = [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"[MOVIMIENTOS] No se pudieron leer egresos_caja: {e}")
            egresos = []
        conn.close()
        return egresos

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
    
    def anular_movimiento(self, movimiento_id: int, motivo: str,
                         inventory_mode: Optional[str] = None,
                         inventory_command_id: Optional[str] = None,
                         inventory_gateway=None,
                         inventory_transport=None,
                         inventory_connection_factory=None) -> Tuple[bool, str]:
        """
        Anula un movimiento y revierte el cambio en el stock
        NOTA: Usar con precaución
        """
        from inventory_writer_support import WRITER_MODE_AUTHORITATIVE, resolve_writer_mode_or_frozen

        mode, frozen = resolve_writer_mode_or_frozen(
            inventory_mode, db=self.db,
            connection_factory=inventory_connection_factory,
        )
        if frozen:
            return False, frozen
        if mode == WRITER_MODE_AUTHORITATIVE:
            return self._anular_movimiento_authoritative(
                movimiento_id, motivo,
                inventory_command_id=inventory_command_id,
                inventory_gateway=inventory_gateway,
                inventory_transport=inventory_transport,
                inventory_connection_factory=inventory_connection_factory,
            )

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
                nuevo_stock = producto['stock'] - movimiento['cantidad']
            else:  # SALIDA
                nuevo_stock = producto['stock'] + movimiento['cantidad']
            
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

            from repositories._outbox import encolar
            encolar(conn, "product", movimiento['producto_id'], "update", "productos")
            encolar(conn, "inventory_movement", movimiento_id, "update", "movimientos")

            from inventory_cutover import commit_legacy_inventory

            commit_legacy_inventory(
                conn, connection_factory=inventory_connection_factory
            )
            
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

    def _anular_movimiento_authoritative(
        self, movimiento_id: int, motivo: str, *,
        inventory_command_id, inventory_gateway, inventory_transport,
        inventory_connection_factory,
    ) -> Tuple[bool, str]:
        from inventory_cutover import get_or_create_act_command_id
        from inventory_gateway import OUTCOME_APPLIED, OUTCOME_REJECTED
        from inventory_ledger import QuantityScaleError, UnknownProductError
        from inventory_writer_support import (
            DOCUMENTO_TIPO_MOVIMIENTO, MissingProductLocalIdError,
            bind_inventory_gateway, build_signed_operations, command_already_applied,
            command_motivo_marker, movement_tipo_to_ledger, unknown_writer_message,
        )
        if not self.auth.tiene_permiso('gestionar_movimientos'):
            return False, "No tiene permisos para anular movimientos"
        movimiento = self.obtener_movimiento_por_id(movimiento_id)
        if not movimiento:
            return False, "Movimiento no encontrado"
        obs = str(movimiento.get("observaciones") or "")
        conn = self.db.conectar()
        cursor = conn.cursor()
        try:
            command_id = get_or_create_act_command_id(
                conn,
                "anular_movimiento",
                str(movimiento_id),
                command_id=inventory_command_id,
            )
        except Exception as exc:
            conn.close()
            return False, str(exc)
        self.last_inventory_command_id = command_id
        if "[ANULADO]" in obs:
            conn.close()
            return True, "Movimiento anulado"
        try:
            _tipo, sign = movement_tipo_to_ledger(movimiento["tipo"])
        except QuantityScaleError as exc:
            conn.close()
            return False, str(exc)
        inverse = -sign * movimiento["cantidad"]
        try:
            already = command_already_applied(conn, command_id)
            if already is None:
                operations = build_signed_operations(
                    conn, [{"producto_id": movimiento["producto_id"], "delta": inverse}],
                    command_id=command_id,
                )
                gw = bind_inventory_gateway(
                    conn, gateway=inventory_gateway, transport=inventory_transport,
                    connection_factory=inventory_connection_factory, cutover_enabled=True,
                )
                try:
                    result = gw.submit(
                        tipo="AJUSTE", operations=operations, command_id=command_id,
                        documento_tipo=DOCUMENTO_TIPO_MOVIMIENTO, device_id=None,
                        usuario_id=self.auth.usuario_actual.id if self.auth.usuario_actual else None,
                    )
                except Exception as exc:
                    conn.close()
                    return False, unknown_writer_message(command_id, str(exc))
                self.last_gateway_result = result
                if result.outcome == OUTCOME_REJECTED:
                    conn.close()
                    return False, result.error or "Inventario rechazado por el coordinador"
                if result.outcome != OUTCOME_APPLIED:
                    conn.close()
                    return False, unknown_writer_message(result.command_id, result.error or result.outcome)
            observacion_anulacion = f"[ANULADO] {motivo} {command_motivo_marker(command_id)}"
            if movimiento.get("observaciones"):
                observacion_anulacion = f"{movimiento['observaciones']} | {observacion_anulacion}"
            cursor.execute(
                "UPDATE movimientos SET observaciones = ? WHERE id = ?",
                (observacion_anulacion, movimiento_id),
            )
            from repositories._outbox import encolar
            encolar(conn, "inventory_movement", movimiento_id, "update", "movimientos")
            conn.commit()
            conn.close()
            return True, "Movimiento anulado"
        except (MissingProductLocalIdError, QuantityScaleError, UnknownProductError) as exc:
            try:
                conn.close()
            except Exception:
                pass
            return False, str(exc)
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
            return False, unknown_writer_message(command_id, str(e))
    
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
        stock_actual = producto['stock'] if producto else 0
        
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
