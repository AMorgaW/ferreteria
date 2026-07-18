# -*- coding: utf-8 -*-
"""
Servicio de Ventas
Gestiona el proceso de ventas y facturación
"""
from datetime import datetime, timedelta
from typing import Tuple, List, Optional
from models import Venta, DetalleVenta, MetodoPago, EstadoVenta
from database import obtener_fecha_actual
from local_first_db import enqueue_sync, ensure_local_id


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

    def _config_iva(self):
        """Lee la configuración de IVA (apagado por defecto)."""
        try:
            from local_first_config import load_config
            c = load_config()
            return {
                'activo': bool(c.get('iva_activo', False)),
                'tasa': float(c.get('iva_tasa', 0.19) or 0),
                'incluido': bool(c.get('iva_incluido', True)),
            }
        except Exception:
            return {'activo': False, 'tasa': 0.0, 'incluido': True}

    def _siguiente_numero_factura(self, cursor, fecha):
        """Consecutivo de factura ATÓMICO por día (tabla `consecutivos`).
        Un único UPSERT serializado por el writer de SQLite garantiza números
        únicos aunque varias cajas vendan simultáneamente. Si la transacción
        hace rollback, el incremento se revierte (no deja huecos)."""
        prefijo = f"{fecha}-"
        # Respaldo: mayor consecutivo ya usado hoy (alinea el contador con datos previos)
        cursor.execute('''
            SELECT MAX(CAST(SUBSTR(numero_factura, 10) AS INTEGER)) AS ultimo
            FROM ventas WHERE numero_factura LIKE ? || '%'
        ''', (prefijo,))
        row = cursor.fetchone()
        base = (row['ultimo'] if row and row['ultimo'] is not None else 0) or 0
        cursor.execute('''
            INSERT INTO consecutivos (clave, valor) VALUES (?, ?)
            ON CONFLICT(clave) DO UPDATE SET
                valor = CASE WHEN valor < ? THEN ? ELSE valor + 1 END
        ''', (fecha, base + 1, base, base + 1))
        r = cursor.execute("SELECT valor FROM consecutivos WHERE clave = ?", (fecha,)).fetchone()
        consec = r['valor'] if hasattr(r, 'keys') else r[0]
        return f"{prefijo}{consec:04d}"

    # NOTA: el antiguo crear_venta() (decremento de stock NO atomico) y el
    # primer registrar_venta() duplicado fueron eliminados. La unica ruta de
    # venta es registrar_venta() (mas abajo), con guardia atomica WHERE stock>=?.

    def registrar_venta(self, items: List[dict], cliente_id: Optional[int] = None,
                       metodo_pago: str = 'EFECTIVO', descuento_general: float = 0,
                       observaciones: str = None) -> Tuple[bool, str, Optional[Venta]]:
        """
        Registra una venta con una sola conexion y una sola transaccion.
        """
        if not items:
            return False, "No hay productos en la venta", None

        # Validación de líneas: cantidades y precios deben ser positivos
        for item in items:
            cant = item.get('cantidad', 0)
            precio = item.get('precio_unitario', 0)
            desc = item.get('descuento', 0) or 0
            if cant is None or cant <= 0:
                return False, "La cantidad de cada producto debe ser mayor a 0", None
            if precio is None or precio < 0:
                return False, "El precio unitario no puede ser negativo", None
            if desc < 0:
                return False, "El descuento no puede ser negativo", None
            if desc > precio * cant:
                return False, "El descuento de un producto no puede superar su subtotal", None

        if descuento_general is None or descuento_general < 0:
            return False, "El descuento general no puede ser negativo", None

        usuario_id = self.auth.usuario_actual.id if self.auth.usuario_actual else None
        if not usuario_id:
            return False, "Error: Usuario no autenticado. No se puede registrar venta", None

        conn = self.db.conectar()
        cursor = conn.cursor()

        try:
            producto_ids = sorted({item['producto_id'] for item in items})
            placeholders = ",".join("?" for _ in producto_ids)
            cursor.execute(
                f"SELECT id, nombre, stock FROM productos WHERE id IN ({placeholders})",
                producto_ids,
            )
            productos = {row['id']: dict(row) for row in cursor.fetchall()}

            for item in items:
                producto = productos.get(item['producto_id'])
                if not producto:
                    conn.close()
                    return False, f"Producto ID {item['producto_id']} no encontrado", None
                if producto['stock'] < item['cantidad']:
                    conn.close()
                    return False, (
                        f"Stock insuficiente para {producto['nombre']}. "
                        f"Disponible: {producto['stock']}"
                    ), None

            fecha = datetime.now().strftime("%Y%m%d")
            num_factura = self._siguiente_numero_factura(cursor, fecha)

            detalles = []
            for item in items:
                cantidad = item['cantidad']
                precio_unitario = item['precio_unitario']
                descuento_item = item.get('descuento', 0)
                subtotal_item = (precio_unitario * cantidad) - descuento_item
                detalles.append({
                    'producto_id': item['producto_id'],
                    'cantidad': cantidad,
                    'precio_unitario': precio_unitario,
                    'descuento': descuento_item,
                    'subtotal': subtotal_item,
                })

            subtotal = sum(d['subtotal'] for d in detalles)
            if descuento_general > subtotal:
                conn.close()
                return False, "El descuento general no puede superar el subtotal de la venta", None
            total = subtotal - descuento_general

            # IVA (configurable, por defecto desactivado). Modelo "incluido":
            # el precio ya lo incluye y solo se desglosa (no cambia el total).
            iva_monto = 0.0
            iva_cfg = self._config_iva()
            if iva_cfg['activo'] and iva_cfg['tasa'] > 0:
                if iva_cfg['incluido']:
                    iva_monto = round(total - total / (1 + iva_cfg['tasa']), 2)
                else:
                    iva_monto = round(total * iva_cfg['tasa'], 2)
                    total = round(total + iva_monto, 2)

            estado_pago = 'PENDIENTE' if metodo_pago == 'CREDITO' else 'PAGADO'
            monto_pagado = 0 if metodo_pago == 'CREDITO' else total

            cursor.execute('''
                INSERT INTO ventas
                (numero_factura, cliente_id, usuario_id, subtotal, descuento,
                 iva, total, metodo_pago, estado_pago, monto_pagado,
                 observaciones, fecha, estado)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 'COMPLETADA')
            ''', (num_factura, cliente_id, usuario_id, subtotal, descuento_general,
                  iva_monto, total, metodo_pago, estado_pago, monto_pagado,
                  observaciones))
            venta_id = cursor.lastrowid
            ensure_local_id(conn, "ventas", venta_id)

            for detalle in detalles:
                cursor.execute('''
                    INSERT INTO detalle_ventas
                    (venta_id, producto_id, cantidad, precio_unitario, descuento, subtotal, iva)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (venta_id, detalle['producto_id'], detalle['cantidad'],
                      detalle['precio_unitario'], detalle['descuento'],
                      detalle['subtotal'], 0))
                detalle_id = cursor.lastrowid
                ensure_local_id(conn, "detalle_ventas", detalle_id)

                cursor.execute('''
                    UPDATE productos
                    SET stock = stock - ?
                    WHERE id = ? AND stock >= ?
                ''', (detalle['cantidad'], detalle['producto_id'], detalle['cantidad']))

                if cursor.rowcount == 0:
                    conn.rollback()
                    conn.close()
                    return False, "Stock insuficiente; la venta fue cancelada", None

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
                    detalle['subtotal'],
                    f'Venta {num_factura}',
                    num_factura,
                    obtener_fecha_actual()
                ))
                movimiento_id = cursor.lastrowid
                ensure_local_id(conn, "movimientos", movimiento_id)

            cuenta_id = None
            if metodo_pago == 'CREDITO' and cliente_id:
                fecha_vencimiento = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
                cursor.execute('''
                    INSERT INTO cuentas_por_cobrar
                    (venta_id, cliente_id, monto_total, saldo_pendiente, fecha_vencimiento)
                    VALUES (?, ?, ?, ?, ?)
                ''', (venta_id, cliente_id, total, total, fecha_vencimiento))
                cuenta_id = cursor.lastrowid
                ensure_local_id(conn, "cuentas_por_cobrar", cuenta_id)

                cursor.execute('''
                    UPDATE clientes
                    SET saldo_pendiente = saldo_pendiente + ?
                    WHERE id = ?
                ''', (total, cliente_id))

            cursor.execute('''
                INSERT INTO auditoria (usuario_id, accion, modulo, descripcion, ip_address)
                VALUES (?, ?, ?, ?, ?)
            ''', (usuario_id, "VENTA", "Ventas", f"Venta {num_factura} por ${total:,.0f}", None))
            from local_first_db import enqueue_entity as _eq
            _eq(conn, "audit_log", cursor.lastrowid, "create", "auditoria")

            venta_payload = dict(cursor.execute("SELECT * FROM ventas WHERE id = ?", (venta_id,)).fetchone())
            enqueue_sync(conn, "sale", venta_id, "create", venta_payload, "ventas")

            for row in cursor.execute("SELECT * FROM detalle_ventas WHERE venta_id = ?", (venta_id,)).fetchall():
                enqueue_sync(conn, "sale_detail", row['id'], "create", dict(row), "detalle_ventas")

            for row in cursor.execute("SELECT * FROM movimientos WHERE num_factura = ?", (num_factura,)).fetchall():
                enqueue_sync(conn, "inventory_movement", row['id'], "create", dict(row), "movimientos")

            for detalle in detalles:
                product_payload = dict(cursor.execute(
                    "SELECT * FROM productos WHERE id = ?",
                    (detalle['producto_id'],),
                ).fetchone())
                enqueue_sync(conn, "product", detalle['producto_id'], "update", product_payload, "productos")

            # Crédito: sincronizar también la cuenta por cobrar y el saldo del cliente.
            if cuenta_id is not None:
                cuenta_payload = dict(cursor.execute(
                    "SELECT * FROM cuentas_por_cobrar WHERE id = ?", (cuenta_id,)).fetchone())
                enqueue_sync(conn, "receivable", cuenta_id, "create",
                             cuenta_payload, "cuentas_por_cobrar")
                ensure_local_id(conn, "clientes", cliente_id)
                cliente_payload = dict(cursor.execute(
                    "SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone())
                enqueue_sync(conn, "customer", cliente_id, "update",
                             cliente_payload, "clientes")

            conn.commit()
            conn.close()

            if hasattr(self.productos_repo, 'invalidar_cache'):
                self.productos_repo.invalidar_cache()
            if cliente_id and hasattr(self.clientes_repo, 'invalidar_cache'):
                self.clientes_repo.invalidar_cache()

            venta = Venta(
                id=venta_id,
                numero_factura=num_factura,
                fecha=obtener_fecha_actual(),
                cliente_id=cliente_id,
                usuario_id=usuario_id,
                subtotal=subtotal,
                descuento=descuento_general,
                iva=iva_monto,
                total=total,
                metodo_pago=metodo_pago,
                estado='COMPLETADA',
                observaciones=observaciones
            )
            return True, f"Venta {num_factura} registrada exitosamente", venta

        except Exception as e:
            conn.rollback()
            conn.close()
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

            # Encolar la cancelación para sincronizar con Supabase (estado de la
            # venta + stock revertido + movimientos de devolución). Sin esto el
            # respaldo remoto quedaba desincronizado tras una cancelación.
            try:
                venta_row = cursor.execute(
                    "SELECT * FROM ventas WHERE id = ?", (venta_id,)).fetchone()
                if venta_row:
                    enqueue_sync(conn, "sale", venta_id, "update", dict(venta_row), "ventas")
                for det in venta['detalles']:
                    prod_row = cursor.execute(
                        "SELECT * FROM productos WHERE id = ?", (det['producto_id'],)).fetchone()
                    if prod_row:
                        enqueue_sync(conn, "product", det['producto_id'], "update",
                                     dict(prod_row), "productos")
                for mov in cursor.execute(
                    "SELECT * FROM movimientos WHERE num_factura = ? AND tipo = 'ENTRADA_DEVOLUCION'",
                    (venta['numero_factura'],)).fetchall():
                    enqueue_sync(conn, "inventory_movement", mov['id'], "create",
                                 dict(mov), "movimientos")
            except Exception as _sync_exc:
                print(f"[SYNC] No se pudo encolar la cancelacion: {_sync_exc}")

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

    def cantidad_devuelta(self, venta_id: int, producto_id: int) -> float:
        """Unidades ya devueltas de un producto en una venta."""
        conn = self.db.conectar()
        cursor = conn.cursor()
        try:
            row = cursor.execute(
                "SELECT COALESCE(SUM(cantidad), 0) AS c FROM devolucion_detalle "
                "WHERE venta_id = ? AND producto_id = ?",
                (venta_id, producto_id)).fetchone()
            return float(row['c'] if row else 0)
        finally:
            conn.close()

    def obtener_devoluciones(self, venta_id: int) -> List[dict]:
        """Lista las devoluciones registradas de una venta."""
        conn = self.db.conectar()
        cursor = conn.cursor()
        try:
            return [dict(r) for r in cursor.execute(
                "SELECT * FROM devoluciones WHERE venta_id = ? ORDER BY fecha DESC",
                (venta_id,)).fetchall()]
        finally:
            conn.close()

    def registrar_devolucion(self, venta_id: int, items: Optional[List[dict]] = None,
                             motivo: str = "") -> Tuple[bool, str, Optional[int]]:
        """Registra una devolución total o parcial de una venta.

        items: lista de {producto_id, cantidad}. Si es None/vacío se devuelve
        TODO lo pendiente (devolución total). Revierte stock atómicamente,
        registra kardex (ENTRADA_DEVOLUCION), auditoría y sincronización.
        Valida: no devolver más de lo vendido ni duplicar devoluciones.
        """
        venta = self.obtener_venta(venta_id)
        if not venta:
            return False, "Venta no encontrada", None
        if venta.get('estado') == 'CANCELADA':
            return False, "La venta está cancelada; no admite devoluciones", None

        usuario_id = self.auth.usuario_actual.id if (self.auth and self.auth.usuario_actual) else None
        if not usuario_id:
            return False, "Error: Usuario no autenticado", None

        # Vendido y precio por producto (puede haber varias líneas del mismo)
        vendido, precio, nombre = {}, {}, {}
        for d in venta['detalles']:
            pid = d['producto_id']
            vendido[pid] = vendido.get(pid, 0) + d['cantidad']
            precio[pid] = d['precio_unitario']
            nombre[pid] = d.get('producto_nombre', f'producto {pid}')

        conn = self.db.conectar()
        cursor = conn.cursor()
        try:
            # Ya devuelto por producto
            ya = {}
            for row in cursor.execute(
                "SELECT producto_id, COALESCE(SUM(cantidad),0) AS c "
                "FROM devolucion_detalle WHERE venta_id = ? GROUP BY producto_id",
                (venta_id,)).fetchall():
                ya[row['producto_id']] = row['c']

            # Devolución total: completar lo pendiente
            if not items:
                items = []
                for pid, qty in vendido.items():
                    restante = qty - ya.get(pid, 0)
                    if restante > 0:
                        items.append({'producto_id': pid, 'cantidad': restante})
                if not items:
                    conn.close()
                    return False, "No hay unidades pendientes por devolver", None

            # Validaciones
            for it in items:
                pid = it.get('producto_id')
                cant = it.get('cantidad', 0)
                if cant is None or cant <= 0:
                    conn.close()
                    return False, "La cantidad a devolver debe ser mayor a 0", None
                if pid not in vendido:
                    conn.close()
                    return False, f"El producto {pid} no pertenece a esta venta", None
                disponible = vendido[pid] - ya.get(pid, 0)
                if cant > disponible + 1e-9:
                    conn.close()
                    return False, (f"No se pueden devolver {cant} de '{nombre[pid]}': "
                                   f"vendidas {vendido[pid]}, ya devueltas {ya.get(pid, 0)}, "
                                   f"disponibles {disponible}"), None

            total_dev = sum(it['cantidad'] * precio.get(it['producto_id'], 0) for it in items)
            total_vendido_unid = sum(vendido.values())
            total_dev_unid = sum(ya.values()) + sum(it['cantidad'] for it in items)
            tipo = 'TOTAL' if abs(total_dev_unid - total_vendido_unid) < 1e-9 else 'PARCIAL'

            cursor.execute('''
                INSERT INTO devoluciones (venta_id, fecha, usuario_id, motivo, tipo, total_devuelto)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (venta_id, obtener_fecha_actual(), usuario_id, motivo, tipo, total_dev))
            dev_id = cursor.lastrowid

            for it in items:
                pid = it['producto_id']
                cant = it['cantidad']
                pu = precio.get(pid, 0)
                sub = cant * pu

                cursor.execute('''
                    INSERT INTO devolucion_detalle
                        (devolucion_id, venta_id, producto_id, cantidad, precio_unitario, subtotal)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (dev_id, venta_id, pid, cant, pu, sub))

                cursor.execute("UPDATE productos SET stock = stock + ? WHERE id = ?", (cant, pid))

                cursor.execute('''
                    INSERT INTO movimientos (tipo, producto_id, usuario_id, cantidad,
                        precio_unitario, costo_total, motivo, num_factura, fecha)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', ('ENTRADA_DEVOLUCION', pid, usuario_id, cant, pu, sub,
                      f"Devolución venta {venta['numero_factura']}: {motivo}",
                      venta['numero_factura'], obtener_fecha_actual()))
                mov_id = cursor.lastrowid
                ensure_local_id(conn, "movimientos", mov_id)

                prow = cursor.execute("SELECT * FROM productos WHERE id = ?", (pid,)).fetchone()
                if prow:
                    enqueue_sync(conn, "product", pid, "update", dict(prow), "productos")
                mrow = cursor.execute("SELECT * FROM movimientos WHERE id = ?", (mov_id,)).fetchone()
                if mrow:
                    enqueue_sync(conn, "inventory_movement", mov_id, "create", dict(mrow), "movimientos")

            # Si quedó totalmente devuelta, marcar la venta
            if tipo == 'TOTAL':
                cursor.execute("UPDATE ventas SET estado = 'DEVUELTA' WHERE id = ?", (venta_id,))
                vrow = cursor.execute("SELECT * FROM ventas WHERE id = ?", (venta_id,)).fetchone()
                if vrow:
                    enqueue_sync(conn, "sale", venta_id, "update", dict(vrow), "ventas")

            cursor.execute('''
                INSERT INTO auditoria (usuario_id, accion, modulo, descripcion, ip_address)
                VALUES (?, ?, ?, ?, ?)
            ''', (usuario_id, "DEVOLUCION", "Ventas",
                  f"Devolución {tipo} de venta {venta['numero_factura']} por ${total_dev:,.0f}. "
                  f"Motivo: {motivo}", None))
            from local_first_db import enqueue_entity as _eq
            _eq(conn, "audit_log", cursor.lastrowid, "create", "auditoria")

            conn.commit()
            conn.close()

            if hasattr(self.productos_repo, 'invalidar_cache'):
                self.productos_repo.invalidar_cache()

            return True, f"Devolución {tipo} registrada por ${total_dev:,.0f}", dev_id

        except Exception as e:
            conn.rollback()
            conn.close()
            return False, f"Error al registrar devolución: {str(e)}", None

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
            _nuevos_detalle_ids = []
            _nuevos_mov_ids = []
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
                _did = cursor.lastrowid
                ensure_local_id(conn, "detalle_ventas", _did)
                _nuevos_detalle_ids.append(_did)

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
                _mid = cursor.lastrowid
                ensure_local_id(conn, "movimientos", _mid)
                _nuevos_mov_ids.append(_mid)
            
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

            # Local-first: encolar venta (total actualizado), nuevos detalles,
            # movimientos y productos afectados para sincronizar a Supabase.
            _vrow = cursor.execute("SELECT * FROM ventas WHERE id = ?", (venta_id,)).fetchone()
            if _vrow:
                enqueue_sync(conn, "sale", venta_id, "update", dict(_vrow), "ventas")
            for _did in _nuevos_detalle_ids:
                _dr = cursor.execute("SELECT * FROM detalle_ventas WHERE id = ?", (_did,)).fetchone()
                if _dr:
                    enqueue_sync(conn, "sale_detail", _did, "create", dict(_dr), "detalle_ventas")
            for _mid in _nuevos_mov_ids:
                _mr = cursor.execute("SELECT * FROM movimientos WHERE id = ?", (_mid,)).fetchone()
                if _mr:
                    enqueue_sync(conn, "inventory_movement", _mid, "create", dict(_mr), "movimientos")
            for detalle in nuevos_detalles:
                _pr = cursor.execute("SELECT * FROM productos WHERE id = ?", (detalle['producto_id'],)).fetchone()
                if _pr:
                    enqueue_sync(conn, "product", detalle['producto_id'], "update", dict(_pr), "productos")

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
