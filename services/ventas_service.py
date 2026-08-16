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
                       observaciones: str = None,
                       inventory_mode: Optional[str] = None,
                       inventory_command_id: Optional[str] = None,
                       inventory_gateway=None,
                       inventory_transport=None,
                       inventory_connection_factory=None) -> Tuple[bool, str, Optional[Venta]]:
        """
        Registra una venta con una sola conexion y una sola transaccion.

        Default (cutover OFF): camino LEGACY — productos.stock sigue siendo
        la ruta efectiva. No persiste un InventoryCommand autoritativo.
        Camino autoritativo: un solo command por venta, inyectable en tests.
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

        from inventory_writer_support import WRITER_MODE_AUTHORITATIVE, resolve_writer_mode_or_frozen

        mode, frozen = resolve_writer_mode_or_frozen(
            inventory_mode, db=self.db,
            connection_factory=inventory_connection_factory,
        )
        if frozen:
            return False, frozen, None
        if mode == WRITER_MODE_AUTHORITATIVE:
            from contextlib import nullcontext
            from inventory_cutover import serialize_implicit_pos_act

            guard = (
                serialize_implicit_pos_act()
                if inventory_command_id is None
                else nullcontext()
            )
            with guard:
                return self._registrar_venta_authoritative(
                    items,
                    cliente_id=cliente_id,
                    metodo_pago=metodo_pago,
                    descuento_general=descuento_general,
                    observaciones=observaciones,
                    inventory_command_id=inventory_command_id,
                    inventory_gateway=inventory_gateway,
                    inventory_transport=inventory_transport,
                    inventory_connection_factory=inventory_connection_factory,
                )

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

            from inventory_cutover import commit_legacy_inventory

            commit_legacy_inventory(
                conn, connection_factory=inventory_connection_factory
            )
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

    def _registrar_venta_authoritative(
        self,
        items: List[dict],
        *,
        cliente_id,
        metodo_pago,
        descuento_general,
        observaciones,
        inventory_command_id,
        inventory_gateway,
        inventory_transport,
        inventory_connection_factory,
    ) -> Tuple[bool, str, Optional[Venta]]:
        """Camino futuro: un InventoryCommand por venta. Sin UPDATE productos.stock."""
        from inventory_gateway import (
            OUTCOME_APPLIED,
            OUTCOME_REJECTED,
            OUTCOME_UNKNOWN,
        )
        from inventory_writer_support import (
            DOCUMENTO_TIPO_VENTA,
            MissingProductLocalIdError,
            bind_inventory_gateway,
            build_negative_operations,
            unknown_writer_message,
        )
        from inventory_ledger import QuantityScaleError, UnknownProductError

        usuario_id = self.auth.usuario_actual.id if self.auth.usuario_actual else None
        conn = self.db.conectar()
        cursor = conn.cursor()
        used_open_act = inventory_command_id is None
        command_id = None

        def _finish_open_act(sqlite_conn):
            if not used_open_act:
                return
            from inventory_cutover import ACT_KIND_POS_CHECKOUT, complete_open_act

            complete_open_act(sqlite_conn, ACT_KIND_POS_CHECKOUT)

        try:
            if used_open_act:
                from inventory_cutover import (
                    ACT_KIND_POS_CHECKOUT,
                    begin_or_resume_open_act,
                )

                command_id = begin_or_resume_open_act(conn, ACT_KIND_POS_CHECKOUT)
            else:
                command_id = inventory_command_id
            self.last_inventory_command_id = command_id
            producto_ids = sorted({item['producto_id'] for item in items})
            placeholders = ",".join("?" for _ in producto_ids)
            cursor.execute(
                f"SELECT id, nombre, stock, local_id FROM productos "
                f"WHERE id IN ({placeholders})",
                producto_ids,
            )
            productos = {row['id']: dict(row) for row in cursor.fetchall()}

            for item in items:
                producto = productos.get(item['producto_id'])
                if not producto:
                    conn.close()
                    return False, f"Producto ID {item['producto_id']} no encontrado", None

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

            iva_monto = 0.0
            iva_cfg = self._config_iva()
            if iva_cfg['activo'] and iva_cfg['tasa'] > 0:
                if iva_cfg['incluido']:
                    iva_monto = round(total - total / (1 + iva_cfg['tasa']), 2)
                else:
                    iva_monto = round(total * iva_cfg['tasa'], 2)
                    total = round(total + iva_monto, 2)

            try:
                operations = build_negative_operations(
                    conn, items, command_id=command_id
                )
            except MissingProductLocalIdError as exc:
                conn.close()
                return False, str(exc), None
            except (QuantityScaleError, UnknownProductError) as exc:
                conn.close()
                return False, str(exc), None

            gw = bind_inventory_gateway(
                conn,
                gateway=inventory_gateway,
                transport=inventory_transport,
                connection_factory=inventory_connection_factory,
                cutover_enabled=True,
            )
            try:
                result = gw.submit(
                    tipo="VENTA",
                    operations=operations,
                    command_id=command_id,
                    documento_tipo=DOCUMENTO_TIPO_VENTA,
                    device_id=None,
                    usuario_id=usuario_id,
                )
            except Exception as exc:
                conn.close()
                return False, unknown_writer_message(command_id, str(exc)), None

            self.last_gateway_result = result
            if result.outcome == OUTCOME_REJECTED:
                _finish_open_act(conn)
                conn.close()
                return False, (
                    result.error or "Inventario rechazado por el coordinador"
                ), None
            if result.outcome != OUTCOME_APPLIED:
                conn.close()
                return False, unknown_writer_message(
                    result.command_id, result.error or result.outcome
                ), None
            if result.command_id != command_id:
                conn.close()
                return False, unknown_writer_message(
                    command_id, "command_id divergente"
                ), None

            bound_id = (
                result.record.documento_local_id if result.record else None
            )
            if bound_id:
                row = cursor.execute(
                    "SELECT * FROM ventas WHERE local_id = ?",
                    (bound_id,),
                ).fetchone()
                if row:
                    _finish_open_act(conn)
                    conn.close()
                    venta = Venta(
                        id=row["id"],
                        numero_factura=row["numero_factura"],
                        fecha=row["fecha"] if "fecha" in row.keys() else obtener_fecha_actual(),
                        cliente_id=row["cliente_id"],
                        usuario_id=row["usuario_id"],
                        subtotal=row["subtotal"],
                        descuento=row["descuento"],
                        iva=row["iva"],
                        total=row["total"],
                        metodo_pago=row["metodo_pago"],
                        estado=row["estado"] if "estado" in row.keys() else "COMPLETADA",
                        observaciones=row["observaciones"],
                    )
                    return True, (
                        f"Venta {row['numero_factura']} registrada exitosamente"
                    ), venta

            estado_pago = 'PENDIENTE' if metodo_pago == 'CREDITO' else 'PAGADO'
            monto_pagado = 0 if metodo_pago == 'CREDITO' else total
            fecha = datetime.now().strftime("%Y%m%d")
            num_factura = self._siguiente_numero_factura(cursor, fecha)

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
            venta_local = cursor.execute(
                "SELECT local_id FROM ventas WHERE id = ?",
                (venta_id,),
            ).fetchone()["local_id"]
            from inventory_ledger import bind_inventory_command_documento

            bind_inventory_command_documento(conn, command_id, venta_local)

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
            _finish_open_act(conn)
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
            try:
                conn.rollback()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
            return False, unknown_writer_message(command_id, str(e)), None

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
    
    def cancelar_venta(self, venta_id: int, motivo: str,
                       inventory_mode: Optional[str] = None,
                       inventory_command_id: Optional[str] = None,
                       inventory_gateway=None,
                       inventory_transport=None,
                       inventory_connection_factory=None) -> Tuple[bool, str]:
        """Cancela una venta persistida y revierte el inventario.

        No confundir con ui/ventas_ui_modern.cancelar_venta, que solo vacía
        el carrito y no llama este método. W04 permanece preparado; no se borra.
        """
        from inventory_writer_support import WRITER_MODE_AUTHORITATIVE, resolve_writer_mode_or_frozen

        mode, frozen = resolve_writer_mode_or_frozen(
            inventory_mode, db=self.db,
            connection_factory=inventory_connection_factory,
        )
        if frozen:
            return False, frozen
        if mode == WRITER_MODE_AUTHORITATIVE:
            return self._cancelar_venta_authoritative(
                venta_id,
                motivo,
                inventory_command_id=inventory_command_id,
                inventory_gateway=inventory_gateway,
                inventory_transport=inventory_transport,
                inventory_connection_factory=inventory_connection_factory,
            )

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

            from inventory_cutover import commit_legacy_inventory

            commit_legacy_inventory(
                conn, connection_factory=inventory_connection_factory
            )
            
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

    def _cancelar_venta_authoritative(
        self,
        venta_id: int,
        motivo: str,
        *,
        inventory_command_id,
        inventory_gateway,
        inventory_transport,
        inventory_connection_factory,
    ) -> Tuple[bool, str]:
        import uuid as _uuid

        from inventory_gateway import OUTCOME_APPLIED, OUTCOME_REJECTED
        from inventory_ledger import QuantityScaleError, UnknownProductError
        from inventory_writer_support import (
            DOCUMENTO_TIPO_VENTA,
            MissingProductLocalIdError,
            bind_inventory_gateway,
            build_positive_operations,
            command_already_applied,
            command_motivo_marker,
            find_rows_marked_for_command,
            unknown_writer_message,
        )

        venta = self.obtener_venta(venta_id)
        if not venta:
            return False, "Venta no encontrada"
        from inventory_cutover import ACT_KIND_SALE_CANCEL
        from inventory_writer_support import durable_act_command_id
        conn = self.db.conectar()
        cursor = conn.cursor()
        try:
            command_id = durable_act_command_id(
                conn,
                ACT_KIND_SALE_CANCEL,
                act_key=str(venta_id),
                explicit_command_id=inventory_command_id,
            )
            self.last_inventory_command_id = command_id
            already = command_already_applied(conn, command_id)
            if venta['estado'] == 'CANCELADA':
                conn.close()
                if already is not None:
                    return True, "Venta cancelada exitosamente"
                return False, "La venta ya está cancelada"

            if already is None:
                try:
                    operations = build_positive_operations(
                        conn, venta['detalles'], command_id=command_id
                    )
                except MissingProductLocalIdError as exc:
                    conn.close()
                    return False, str(exc)
                except (QuantityScaleError, UnknownProductError) as exc:
                    conn.close()
                    return False, str(exc)
                gw = bind_inventory_gateway(
                    conn,
                    gateway=inventory_gateway,
                    transport=inventory_transport,
                    connection_factory=inventory_connection_factory,
                    cutover_enabled=True,
                )
                try:
                    result = gw.submit(
                        tipo="DEVOLUCION",
                        operations=operations,
                        command_id=command_id,
                        documento_tipo=DOCUMENTO_TIPO_VENTA,
                        documento_local_id=venta.get("local_id"),
                        device_id=None,
                        usuario_id=(
                            self.auth.usuario_actual.id if self.auth.usuario_actual else None
                        ),
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
                    return False, unknown_writer_message(
                        result.command_id, result.error or result.outcome
                    )
            elif find_rows_marked_for_command(conn, command_id, table="movimientos"):
                conn.close()
                return True, "Venta cancelada exitosamente"

            marker = command_motivo_marker(command_id)
            cursor.execute('''
                UPDATE ventas
                SET estado = 'CANCELADA',
                    observaciones = observaciones || ' | CANCELADA: ' || ?
                WHERE id = ?
            ''', (motivo, venta_id))
            usuario_id = self.auth.usuario_actual.id if self.auth.usuario_actual else None
            for detalle in venta['detalles']:
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
                    f'Cancelación de venta {venta["numero_factura"]}: {motivo} {marker}',
                    venta['numero_factura'],
                    obtener_fecha_actual()
                ))
                ensure_local_id(conn, "movimientos", cursor.lastrowid)
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
            venta_row = cursor.execute(
                "SELECT * FROM ventas WHERE id = ?", (venta_id,)
            ).fetchone()
            if venta_row:
                enqueue_sync(conn, "sale", venta_id, "update", dict(venta_row), "ventas")
            conn.commit()
            conn.close()
            return True, "Venta cancelada exitosamente"
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
                             motivo: str = "",
                             inventory_mode: Optional[str] = None,
                             inventory_command_id: Optional[str] = None,
                             inventory_gateway=None,
                             inventory_transport=None,
                             inventory_connection_factory=None) -> Tuple[bool, str, Optional[int]]:
        """Registra una devolución total o parcial de una venta.

        items: lista de {producto_id, cantidad}. Si es None/vacío se devuelve
        TODO lo pendiente (devolución total). Revierte stock atómicamente,
        registra kardex (ENTRADA_DEVOLUCION), auditoría y sincronización.
        Valida: no devolver más de lo vendido ni duplicar devoluciones.
        """
        from inventory_writer_support import WRITER_MODE_AUTHORITATIVE, resolve_writer_mode_or_frozen

        mode, frozen = resolve_writer_mode_or_frozen(
            inventory_mode, db=self.db,
            connection_factory=inventory_connection_factory,
        )
        if frozen:
            return False, frozen, None
        if mode == WRITER_MODE_AUTHORITATIVE:
            return self._registrar_devolucion_authoritative(
                venta_id,
                items,
                motivo,
                inventory_command_id=inventory_command_id,
                inventory_gateway=inventory_gateway,
                inventory_transport=inventory_transport,
                inventory_connection_factory=inventory_connection_factory,
            )

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

            from inventory_cutover import commit_legacy_inventory

            commit_legacy_inventory(
                conn, connection_factory=inventory_connection_factory
            )
            conn.close()

            if hasattr(self.productos_repo, 'invalidar_cache'):
                self.productos_repo.invalidar_cache()

            return True, f"Devolución {tipo} registrada por ${total_dev:,.0f}", dev_id

        except Exception as e:
            conn.rollback()
            conn.close()
            return False, f"Error al registrar devolución: {str(e)}", None

    def _registrar_devolucion_authoritative(
        self,
        venta_id: int,
        items: Optional[List[dict]],
        motivo: str,
        *,
        inventory_command_id,
        inventory_gateway,
        inventory_transport,
        inventory_connection_factory,
    ) -> Tuple[bool, str, Optional[int]]:
        import uuid as _uuid

        from inventory_gateway import OUTCOME_APPLIED, OUTCOME_REJECTED
        from inventory_ledger import QuantityScaleError, UnknownProductError
        from inventory_writer_support import (
            DOCUMENTO_TIPO_DEVOLUCION,
            MissingProductLocalIdError,
            bind_inventory_gateway,
            build_positive_operations,
            command_already_applied,
            command_motivo_marker,
            find_rows_marked_for_command,
            operations_from_command_record,
            unknown_writer_message,
        )
        from inventory_ledger import get_inventory_command_or_none

        venta = self.obtener_venta(venta_id)
        if not venta:
            return False, "Venta no encontrada", None
        if venta.get('estado') == 'CANCELADA':
            return False, "La venta está cancelada; no admite devoluciones", None
        usuario_id = self.auth.usuario_actual.id if (self.auth and self.auth.usuario_actual) else None
        if not usuario_id:
            return False, "Error: Usuario no autenticado", None

        vendido, precio, nombre = {}, {}, {}
        for d in venta['detalles']:
            pid = d['producto_id']
            vendido[pid] = vendido.get(pid, 0) + d['cantidad']
            precio[pid] = d['precio_unitario']
            nombre[pid] = d.get('producto_nombre', f'producto {pid}')

        conn = self.db.conectar()
        cursor = conn.cursor()
        try:
            from inventory_cutover import ACT_KIND_RETURN
            from inventory_writer_support import durable_act_command_id
            command_id = durable_act_command_id(
                conn,
                ACT_KIND_RETURN,
                fingerprint=f"{venta_id}:{repr(sorted((i.get('producto_id'), str(i.get('cantidad'))) for i in (items or [])))}",
                explicit_command_id=inventory_command_id,
                open_act=True,
            )
            self.last_inventory_command_id = command_id
            already = command_already_applied(conn, command_id)
            marked = find_rows_marked_for_command(conn, command_id, table="movimientos")
            if already is not None and marked:
                row = cursor.execute(
                    "SELECT id FROM devoluciones WHERE venta_id = ? ORDER BY id DESC LIMIT 1",
                    (venta_id,),
                ).fetchone()
                conn.close()
                return True, "Devolución registrada", row["id"] if row else None

            ya = {}
            for row in cursor.execute(
                "SELECT producto_id, COALESCE(SUM(cantidad),0) AS c "
                "FROM devolucion_detalle WHERE venta_id = ? GROUP BY producto_id",
                (venta_id,),
            ).fetchall():
                ya[row['producto_id']] = row['c']

            work_items = list(items) if items else None
            if not work_items:
                work_items = []
                for pid, qty in vendido.items():
                    restante = qty - ya.get(pid, 0)
                    if restante > 0:
                        work_items.append({'producto_id': pid, 'cantidad': restante})
                if not work_items:
                    conn.close()
                    return False, "No hay unidades pendientes por devolver", None

            for it in work_items:
                pid = it.get('producto_id')
                cant = it.get('cantidad', 0)
                if cant is None or cant <= 0:
                    conn.close()
                    return False, "La cantidad a devolver debe ser mayor a 0", None
                if pid not in vendido:
                    conn.close()
                    return False, f"El producto {pid} no pertenece a esta venta", None
                disponible = vendido[pid] - ya.get(pid, 0)
                if already is None and cant > disponible + 1e-9:
                    conn.close()
                    return False, (
                        f"No se pueden devolver {cant} de '{nombre[pid]}': "
                        f"vendidas {vendido[pid]}, ya devueltas {ya.get(pid, 0)}, "
                        f"disponibles {disponible}"
                    ), None

            total_dev = sum(it['cantidad'] * precio.get(it['producto_id'], 0) for it in work_items)
            total_vendido_unid = sum(vendido.values())
            total_dev_unid = sum(ya.values()) + sum(it['cantidad'] for it in work_items)
            tipo = 'TOTAL' if abs(total_dev_unid - total_vendido_unid) < 1e-9 else 'PARCIAL'

            if already is None:
                existing = get_inventory_command_or_none(conn, command_id)
                try:
                    if existing is not None:
                        operations = operations_from_command_record(existing)
                    else:
                        operations = build_positive_operations(
                            conn, work_items, command_id=command_id
                        )
                except MissingProductLocalIdError as exc:
                    conn.close()
                    return False, str(exc), None
                except (QuantityScaleError, UnknownProductError) as exc:
                    conn.close()
                    return False, str(exc), None
                gw = bind_inventory_gateway(
                    conn,
                    gateway=inventory_gateway,
                    transport=inventory_transport,
                    connection_factory=inventory_connection_factory,
                    cutover_enabled=True,
                )
                try:
                    result = gw.submit(
                        tipo="DEVOLUCION",
                        operations=operations,
                        command_id=command_id,
                        documento_tipo=DOCUMENTO_TIPO_DEVOLUCION,
                        device_id=None,
                        usuario_id=usuario_id,
                    )
                except Exception as exc:
                    conn.close()
                    return False, unknown_writer_message(command_id, str(exc)), None
                self.last_gateway_result = result
                if result.outcome == OUTCOME_REJECTED:
                    conn.close()
                    return False, result.error or "Inventario rechazado por el coordinador", None
                if result.outcome != OUTCOME_APPLIED:
                    conn.close()
                    return False, unknown_writer_message(
                        result.command_id, result.error or result.outcome
                    ), None

            marker = command_motivo_marker(command_id)
            cursor.execute('''
                INSERT INTO devoluciones (venta_id, fecha, usuario_id, motivo, tipo, total_devuelto)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (venta_id, obtener_fecha_actual(), usuario_id, f"{motivo} {marker}", tipo, total_dev))
            dev_id = cursor.lastrowid
            for it in work_items:
                pid = it['producto_id']
                cant = it['cantidad']
                pu = precio.get(pid, 0)
                sub = cant * pu
                cursor.execute('''
                    INSERT INTO devolucion_detalle
                        (devolucion_id, venta_id, producto_id, cantidad, precio_unitario, subtotal)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (dev_id, venta_id, pid, cant, pu, sub))
                cursor.execute('''
                    INSERT INTO movimientos (tipo, producto_id, usuario_id, cantidad,
                        precio_unitario, costo_total, motivo, num_factura, fecha)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', ('ENTRADA_DEVOLUCION', pid, usuario_id, cant, pu, sub,
                      f"Devolución venta {venta['numero_factura']}: {motivo} {marker}",
                      venta['numero_factura'], obtener_fecha_actual()))
                ensure_local_id(conn, "movimientos", cursor.lastrowid)
            if tipo == 'TOTAL':
                cursor.execute("UPDATE ventas SET estado = 'DEVUELTA' WHERE id = ?", (venta_id,))
                vrow = cursor.execute("SELECT * FROM ventas WHERE id = ?", (venta_id,)).fetchone()
                if vrow:
                    enqueue_sync(conn, "sale", venta_id, "update", dict(vrow), "ventas")
            conn.commit()
            conn.close()
            if hasattr(self.productos_repo, 'invalidar_cache'):
                self.productos_repo.invalidar_cache()
            return True, f"Devolución {tipo} registrada por ${total_dev:,.0f}", dev_id
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
            return False, unknown_writer_message(command_id, str(e)), None

    def agregar_productos_a_factura(self, venta_id: int, nuevos_items: List[dict],
                                    inventory_mode: Optional[str] = None,
                                    inventory_command_id: Optional[str] = None,
                                    inventory_gateway=None,
                                    inventory_transport=None,
                                    inventory_connection_factory=None) -> Tuple[bool, str]:
        """
        Agrega productos a una factura de crédito existente
        Args:
            venta_id: ID de la venta existente
            nuevos_items: Lista de dicts con {producto_id, cantidad, precio_unitario, descuento}
        Returns: (éxito, mensaje)

        Legacy: check de stock previo no atómico; UPDATE sin stock>= (puede ir
        negativo). No se "arregla" en 1E.1.
        Autoritativo: el coordinador decide insuficiencia; sin dual-write.
        """
        if not nuevos_items:
            return False, "No hay productos para agregar"

        from inventory_writer_support import WRITER_MODE_AUTHORITATIVE, resolve_writer_mode_or_frozen

        mode, frozen = resolve_writer_mode_or_frozen(
            inventory_mode, db=self.db,
            connection_factory=inventory_connection_factory,
        )
        if frozen:
            return False, frozen
        if mode == WRITER_MODE_AUTHORITATIVE:
            return self._agregar_productos_a_factura_authoritative(
                venta_id,
                nuevos_items,
                inventory_command_id=inventory_command_id,
                inventory_gateway=inventory_gateway,
                inventory_transport=inventory_transport,
                inventory_connection_factory=inventory_connection_factory,
            )
        
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

            from inventory_cutover import commit_legacy_inventory

            commit_legacy_inventory(
                conn, connection_factory=inventory_connection_factory
            )

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

    def _agregar_productos_a_factura_authoritative(
        self,
        venta_id: int,
        nuevos_items: List[dict],
        *,
        inventory_command_id,
        inventory_gateway,
        inventory_transport,
        inventory_connection_factory,
    ) -> Tuple[bool, str]:
        import uuid as _uuid

        from inventory_gateway import OUTCOME_APPLIED, OUTCOME_REJECTED
        from inventory_cutover import ACT_KIND_INVOICE_LINE_ADD
        from inventory_ledger import IdempotencyConflictError, QuantityScaleError, UnknownProductError
        from inventory_writer_support import (
            DOCUMENTO_TIPO_VENTA,
            MissingProductLocalIdError,
            bind_inventory_gateway,
            build_negative_operations,
            command_already_applied,
            command_motivo_marker,
            durable_act_command_id,
            find_rows_marked_for_command,
            unknown_writer_message,
        )

        conn = self.db.conectar()
        cursor = conn.cursor()
        try:
            command_id = durable_act_command_id(
                conn,
                ACT_KIND_INVOICE_LINE_ADD,
                fingerprint=f"{venta_id}:{repr(sorted((i.get('producto_id'), str(i.get('cantidad')), str(i.get('precio_unitario'))) for i in nuevos_items))}",
                explicit_command_id=inventory_command_id,
                open_act=True,
            )
            self.last_inventory_command_id = command_id

            cursor.execute('''
                SELECT id, numero_factura, metodo_pago, total, estado_pago, cliente_id, local_id
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

            nuevos_detalles = []
            total_nuevo = 0
            for item in nuevos_items:
                producto_dict = self.productos_repo.obtener_por_id(item['producto_id'])
                if not producto_dict:
                    conn.close()
                    return False, f"Producto ID {item['producto_id']} no encontrado"
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

            try:
                operations = build_negative_operations(
                    conn, nuevos_items, command_id=command_id
                )
                already = command_already_applied(
                    conn,
                    command_id,
                    tipo="VENTA",
                    operations=operations,
                    documento_tipo=DOCUMENTO_TIPO_VENTA,
                    documento_local_id=venta["local_id"],
                )
            except IdempotencyConflictError as exc:
                conn.close()
                return False, str(exc)
            except MissingProductLocalIdError as exc:
                conn.close()
                return False, str(exc)
            except (QuantityScaleError, UnknownProductError) as exc:
                conn.close()
                return False, str(exc)

            if already is not None:
                marked = find_rows_marked_for_command(
                    conn, command_id, table="movimientos"
                )
                if marked:
                    conn.close()
                    return True, "Productos agregados exitosamente (comando ya APPLIED)"

            if already is None:
                gw = bind_inventory_gateway(
                    conn,
                    gateway=inventory_gateway,
                    transport=inventory_transport,
                    connection_factory=inventory_connection_factory,
                    cutover_enabled=True,
                )
                try:
                    result = gw.submit(
                        tipo="VENTA",
                        operations=operations,
                        command_id=command_id,
                        documento_tipo=DOCUMENTO_TIPO_VENTA,
                        documento_local_id=venta["local_id"],
                        device_id=None,
                        usuario_id=(
                            self.auth.usuario_actual.id if self.auth.usuario_actual else None
                        ),
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
                    return False, unknown_writer_message(
                        result.command_id, result.error or result.outcome
                    )

            marker = command_motivo_marker(command_id)
            _nuevos_detalle_ids = []
            _nuevos_mov_ids = []
            usuario_id = self.auth.usuario_actual.id if self.auth.usuario_actual else None
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
                    f'Adición a factura {venta["numero_factura"]} {marker}',
                    venta['numero_factura'],
                    obtener_fecha_actual()
                ))
                _mid = cursor.lastrowid
                ensure_local_id(conn, "movimientos", _mid)
                _nuevos_mov_ids.append(_mid)

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

            conn.commit()
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
            try:
                conn.rollback()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
            return False, unknown_writer_message(command_id, str(e))

    def editar_linea_factura(
        self,
        venta_id: int,
        detalle_id: int,
        nueva_cantidad,
        nuevo_precio,
        inventory_mode: Optional[str] = None,
        inventory_command_id: Optional[str] = None,
        inventory_gateway=None,
        inventory_transport=None,
        inventory_connection_factory=None,
    ) -> Tuple[bool, str]:
        """W17: editar cantidad/precio de una línea de factura. MIXTO."""
        from inventory_writer_support import WRITER_MODE_AUTHORITATIVE, resolve_writer_mode_or_frozen

        mode, frozen = resolve_writer_mode_or_frozen(
            inventory_mode, db=self.db,
            connection_factory=inventory_connection_factory,
        )
        if frozen:
            return False, frozen
        if mode == WRITER_MODE_AUTHORITATIVE:
            return self._editar_linea_factura_authoritative(
                venta_id, detalle_id, nueva_cantidad, nuevo_precio,
                inventory_command_id=inventory_command_id,
                inventory_gateway=inventory_gateway,
                inventory_transport=inventory_transport,
                inventory_connection_factory=inventory_connection_factory,
            )
        conn = self.db.conectar()
        cursor = conn.cursor()
        try:
            detalle = cursor.execute(
                "SELECT * FROM detalle_ventas WHERE id = ? AND venta_id = ?",
                (detalle_id, venta_id),
            ).fetchone()
            if not detalle:
                conn.close()
                return False, "Detalle no encontrado"
            cant_anterior = detalle["cantidad"]
            subtotal_anterior = detalle["subtotal"]
            nuevo_subtotal = nueva_cantidad * nuevo_precio
            dif_cant = nueva_cantidad - cant_anterior
            cursor.execute(
                "UPDATE detalle_ventas SET cantidad = ?, precio_unitario = ?, subtotal = ? WHERE id = ?",
                (nueva_cantidad, nuevo_precio, nuevo_subtotal, detalle_id),
            )
            if dif_cant != 0:
                cursor.execute(
                    "UPDATE productos SET stock = stock - ? WHERE id = ?",
                    (dif_cant, detalle["producto_id"]),
                )
            dif_subtotal = nuevo_subtotal - subtotal_anterior
            cursor.execute(
                "UPDATE ventas SET total = total + ?, subtotal = subtotal + ? WHERE id = ?",
                (dif_subtotal, dif_subtotal, venta_id),
            )
            if dif_cant != 0:
                from inventory_cutover import commit_legacy_inventory

                commit_legacy_inventory(
                    conn, connection_factory=inventory_connection_factory
                )
            else:
                conn.commit()
            conn.close()
            return True, "Producto actualizado"
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            conn.close()
            return False, f"Error al editar: {e}"

    def _editar_linea_factura_authoritative(
        self, venta_id, detalle_id, nueva_cantidad, nuevo_precio, *,
        inventory_command_id, inventory_gateway, inventory_transport,
        inventory_connection_factory,
    ) -> Tuple[bool, str]:
        from inventory_cutover import ACT_KIND_INVOICE_LINE_EDIT
        from inventory_gateway import OUTCOME_APPLIED, OUTCOME_REJECTED
        from inventory_ledger import IdempotencyConflictError, QuantityScaleError, UnknownProductError
        from inventory_writer_support import (
            DOCUMENTO_TIPO_VENTA, NO_INVENTORY_CHANGE, MissingProductLocalIdError,
            bind_inventory_gateway, build_signed_operations, command_already_applied,
            durable_act_command_id, unknown_writer_message,
        )
        conn = self.db.conectar()
        cursor = conn.cursor()
        try:
            command_id = durable_act_command_id(
                conn,
                ACT_KIND_INVOICE_LINE_EDIT,
                fingerprint=f"{venta_id}:{detalle_id}:{nueva_cantidad}:{nuevo_precio}",
                explicit_command_id=inventory_command_id,
                open_act=True,
            )
            self.last_inventory_command_id = command_id
            detalle = cursor.execute(
                "SELECT * FROM detalle_ventas WHERE id = ? AND venta_id = ?",
                (detalle_id, venta_id),
            ).fetchone()
            if not detalle:
                conn.close()
                return False, "Detalle no encontrado"
            venta = cursor.execute("SELECT * FROM ventas WHERE id = ?", (venta_id,)).fetchone()
            if not venta:
                conn.close()
                return False, "Venta no encontrada"
            cant_anterior = detalle["cantidad"]
            subtotal_anterior = detalle["subtotal"]
            nuevo_subtotal = nueva_cantidad * nuevo_precio
            dif_cant = nueva_cantidad - cant_anterior
            operations = []
            try:
                if dif_cant != 0:
                    operations = build_signed_operations(
                        conn,
                        [{"producto_id": detalle["producto_id"], "delta": -dif_cant}],
                        command_id=command_id,
                    )
                already = None
                if operations:
                    already = command_already_applied(
                        conn,
                        command_id,
                        tipo="AJUSTE",
                        operations=operations,
                        documento_tipo=DOCUMENTO_TIPO_VENTA,
                        documento_local_id=(
                            venta["local_id"] if "local_id" in venta.keys() else None
                        ),
                    )
            except IdempotencyConflictError as exc:
                conn.close()
                return False, str(exc)
            except (MissingProductLocalIdError, QuantityScaleError, UnknownProductError) as exc:
                conn.close()
                return False, str(exc)
            if already is None and operations:
                gw = bind_inventory_gateway(
                    conn, gateway=inventory_gateway, transport=inventory_transport,
                    connection_factory=inventory_connection_factory, cutover_enabled=True,
                )
                try:
                    result = gw.submit(
                        tipo="AJUSTE", operations=operations, command_id=command_id,
                        documento_tipo=DOCUMENTO_TIPO_VENTA,
                        documento_local_id=venta["local_id"] if "local_id" in venta.keys() else None,
                        device_id=None,
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
            elif already is None:
                self.last_gateway_result = NO_INVENTORY_CHANGE
            elif already is not None and operations:
                stored_delta = int(already.operations[0].delta_scaled) if already.operations else None
                new_delta = int(operations[0]["delta_scaled"])
                if stored_delta is not None and stored_delta != new_delta:
                    conn.close()
                    return False, (
                        f"command_id {command_id} ya APPLIED con payload distinto"
                    )
            cursor.execute(
                "UPDATE detalle_ventas SET cantidad = ?, precio_unitario = ?, subtotal = ? WHERE id = ?",
                (nueva_cantidad, nuevo_precio, nuevo_subtotal, detalle_id),
            )
            dif_subtotal = nuevo_subtotal - subtotal_anterior
            cursor.execute(
                "UPDATE ventas SET total = total + ?, subtotal = subtotal + ? WHERE id = ?",
                (dif_subtotal, dif_subtotal, venta_id),
            )
            conn.commit()
            conn.close()
            return True, "Producto actualizado"
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

    def eliminar_linea_factura(
        self, venta_id: int, detalle_id: int,
        inventory_mode: Optional[str] = None,
        inventory_command_id: Optional[str] = None,
        inventory_gateway=None, inventory_transport=None,
        inventory_connection_factory=None,
    ) -> Tuple[bool, str]:
        """W18: quitar una línea de factura y restituir stock. POSITIVO."""
        from inventory_writer_support import WRITER_MODE_AUTHORITATIVE, resolve_writer_mode_or_frozen

        mode, frozen = resolve_writer_mode_or_frozen(
            inventory_mode, db=self.db,
            connection_factory=inventory_connection_factory,
        )
        if frozen:
            return False, frozen
        if mode == WRITER_MODE_AUTHORITATIVE:
            return self._eliminar_linea_factura_authoritative(
                venta_id, detalle_id,
                inventory_command_id=inventory_command_id,
                inventory_gateway=inventory_gateway,
                inventory_transport=inventory_transport,
                inventory_connection_factory=inventory_connection_factory,
            )
        conn = self.db.conectar()
        cursor = conn.cursor()
        try:
            detalle = cursor.execute(
                "SELECT * FROM detalle_ventas WHERE id = ? AND venta_id = ?",
                (detalle_id, venta_id),
            ).fetchone()
            if not detalle:
                conn.close()
                return False, "Detalle no encontrado"
            venta = cursor.execute("SELECT * FROM ventas WHERE id = ?", (venta_id,)).fetchone()
            if not venta:
                conn.close()
                return False, "Venta no encontrada"
            numero_factura = venta["numero_factura"]
            cursor.execute(
                "UPDATE productos SET stock = stock + ? WHERE id = ?",
                (detalle["cantidad"], detalle["producto_id"]),
            )
            cursor.execute(
                """
                DELETE FROM movimientos WHERE id = (
                    SELECT id FROM movimientos
                    WHERE tipo = 'SALIDA_VENTA' AND num_factura = ?
                    AND producto_id = ? AND cantidad = ?
                    AND COALESCE(precio_unitario, 0) = COALESCE(?, 0)
                    AND COALESCE(costo_total, 0) = COALESCE(?, 0)
                    ORDER BY fecha DESC, id DESC LIMIT 1
                )
                """,
                (
                    numero_factura, detalle["producto_id"], detalle["cantidad"],
                    detalle["precio_unitario"] if "precio_unitario" in detalle.keys() else 0,
                    detalle["subtotal"] if "subtotal" in detalle.keys() else 0,
                ),
            )
            cursor.execute("DELETE FROM detalle_ventas WHERE id = ?", (detalle_id,))
            sub = detalle["subtotal"] if "subtotal" in detalle.keys() else 0
            cursor.execute(
                "UPDATE ventas SET total = total - ?, subtotal = subtotal - ? WHERE id = ?",
                (sub, sub, venta_id),
            )
            from inventory_cutover import commit_legacy_inventory

            commit_legacy_inventory(
                conn, connection_factory=inventory_connection_factory
            )
            conn.close()
            return True, "Producto eliminado"
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            conn.close()
            return False, f"Error al eliminar: {e}"

    def _eliminar_linea_factura_authoritative(
        self, venta_id, detalle_id, *, inventory_command_id, inventory_gateway,
        inventory_transport, inventory_connection_factory,
    ) -> Tuple[bool, str]:
        from inventory_cutover import ACT_KIND_INVOICE_LINE_DELETE
        from inventory_gateway import OUTCOME_APPLIED, OUTCOME_REJECTED
        from inventory_ledger import QuantityScaleError, UnknownProductError
        from inventory_writer_support import (
            DOCUMENTO_TIPO_VENTA, MissingProductLocalIdError,
            bind_inventory_gateway, build_positive_operations, command_already_applied,
            durable_act_command_id, unknown_writer_message,
        )
        conn = self.db.conectar()
        cursor = conn.cursor()
        try:
            command_id = durable_act_command_id(
                conn,
                ACT_KIND_INVOICE_LINE_DELETE,
                act_key=f"{venta_id}:{detalle_id}",
                explicit_command_id=inventory_command_id,
            )
            self.last_inventory_command_id = command_id
            detalle = cursor.execute(
                "SELECT * FROM detalle_ventas WHERE id = ? AND venta_id = ?",
                (detalle_id, venta_id),
            ).fetchone()
            already = command_already_applied(conn, command_id)
            if detalle is None:
                conn.close()
                if already is not None:
                    return True, "Producto eliminado"
                return False, "Detalle no encontrado"
            venta = cursor.execute("SELECT * FROM ventas WHERE id = ?", (venta_id,)).fetchone()
            if not venta:
                conn.close()
                return False, "Venta no encontrada"
            if already is None:
                try:
                    operations = build_positive_operations(
                        conn,
                        [{"producto_id": detalle["producto_id"], "cantidad": detalle["cantidad"]}],
                        command_id=command_id,
                    )
                except (MissingProductLocalIdError, QuantityScaleError, UnknownProductError) as exc:
                    conn.close()
                    return False, str(exc)
                gw = bind_inventory_gateway(
                    conn, gateway=inventory_gateway, transport=inventory_transport,
                    connection_factory=inventory_connection_factory, cutover_enabled=True,
                )
                try:
                    result = gw.submit(
                        tipo="DEVOLUCION", operations=operations, command_id=command_id,
                        documento_tipo=DOCUMENTO_TIPO_VENTA,
                        documento_local_id=venta["local_id"] if "local_id" in venta.keys() else None,
                        device_id=None,
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
            numero_factura = venta["numero_factura"]
            cursor.execute(
                """
                DELETE FROM movimientos WHERE id = (
                    SELECT id FROM movimientos
                    WHERE tipo = 'SALIDA_VENTA' AND num_factura = ?
                    AND producto_id = ? AND cantidad = ?
                    AND COALESCE(precio_unitario, 0) = COALESCE(?, 0)
                    AND COALESCE(costo_total, 0) = COALESCE(?, 0)
                    ORDER BY fecha DESC, id DESC LIMIT 1
                )
                """,
                (
                    numero_factura, detalle["producto_id"], detalle["cantidad"],
                    detalle["precio_unitario"] if "precio_unitario" in detalle.keys() else 0,
                    detalle["subtotal"] if "subtotal" in detalle.keys() else 0,
                ),
            )
            cursor.execute("DELETE FROM detalle_ventas WHERE id = ?", (detalle_id,))
            sub = detalle["subtotal"] if "subtotal" in detalle.keys() else 0
            cursor.execute(
                "UPDATE ventas SET total = total - ?, subtotal = subtotal - ? WHERE id = ?",
                (sub, sub, venta_id),
            )
            conn.commit()
            conn.close()
            return True, "Producto eliminado"
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
