# -*- coding: utf-8 -*-
"""
Repositorio para gestión de productos
Capa de acceso a datos para productos
"""
import secrets
import uuid
from datetime import datetime
from typing import List, Optional, Tuple
from models import Producto


def _ahora():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

class ProductosRepository:
    """Repositorio de productos"""
    
    def __init__(self, db_manager):
        self.db = db_manager
        self.auth = None  # se asigna desde main para registrar auditoría
        self._cache = []
        self._cache_activos = []
        self._cache_loaded = False

    def _usuario_id(self):
        if self.auth and getattr(self.auth, 'usuario_actual', None):
            return self.auth.usuario_actual.id
        return None

    def _encolar_sync(self, conn, entity_type, entity_id, operation, table_name):
        """Encola un cambio del admin en sync_queue para que el servicio
        local-first lo suba a Supabase (mismo outbox que usa el servidor LAN).
        Solo aplica en modo local (SQLite); nunca interrumpe la operación
        principal si algo falla."""
        try:
            import os
            if os.environ.get("DB_MODE", "local").strip().lower() not in (
                    "local", "sqlite", "server"):
                return
            from local_first_db import enqueue_entity
            enqueue_entity(conn, entity_type, entity_id, operation, table_name)
        except Exception as exc:
            print(f"[SYNC] No se pudo encolar {entity_type} {entity_id}: {exc}")

    def _encolar_borrado(self, conn, entity_type, entity_id, table_name):
        """Encola un borrado remoto (DELETE) para que Supabase elimine la fila.
        Debe llamarse ANTES de borrar la fila local. Solo en modo local."""
        try:
            import os
            if os.environ.get("DB_MODE", "local").strip().lower() not in (
                    "local", "sqlite", "server"):
                return
            from local_first_db import enqueue_sync
            enqueue_sync(conn, entity_type, entity_id, "delete",
                         {"id": entity_id}, table_name)
        except Exception as exc:
            print(f"[SYNC] No se pudo encolar borrado {entity_type} {entity_id}: {exc}")

    def _registrar_cambio_precio(self, cursor, producto_id, tipo, anterior, nuevo):
        """Inserta una fila en historial_precios si el precio realmente cambió."""
        try:
            a = float(anterior or 0)
            n = float(nuevo or 0)
            if abs(a - n) < 0.0001:
                return
            cursor.execute('''
                INSERT INTO historial_precios
                    (producto_id, tipo, precio_anterior, precio_nuevo, usuario_id, fecha)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (producto_id, tipo, a, n, self._usuario_id(), _ahora()))
            self._encolar_sync(cursor.connection, "price_history",
                               cursor.lastrowid, "create", "historial_precios")
        except Exception as exc:
            print(f"[PRECIOS] No se pudo registrar cambio de precio: {exc}")

    def obtener_historial_precios(self, producto_id: int, limite: int = 100) -> List[dict]:
        """Historial de cambios de precio de un producto (trazabilidad)."""
        conn = self.db.conectar()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT h.fecha, h.tipo, h.precio_anterior, h.precio_nuevo,
                       u.nombre_completo AS usuario
                FROM historial_precios h
                LEFT JOIN usuarios u ON h.usuario_id = u.id
                WHERE h.producto_id = ?
                ORDER BY h.fecha DESC, h.id DESC
                LIMIT ?
            ''', (producto_id, limite))
            return [dict(r) for r in cursor.fetchall()]
        finally:
            conn.close()

    def _auditar(self, accion: str, descripcion: str):
        """Registra la acción en auditoría si hay un usuario autenticado."""
        try:
            if self.auth and getattr(self.auth, 'usuario_actual', None):
                self.auth.registrar_auditoria(
                    self.auth.usuario_actual.id, accion, "Productos", descripcion)
        except Exception as exc:
            print(f"[AUDIT] No se pudo registrar auditoría de producto: {exc}")

    def invalidar_cache(self):
        self._cache = []
        self._cache_activos = []
        self._cache_loaded = False

    def precargar_cache(self):
        productos = self.listar_productos(solo_activos=False)
        self._cache = productos
        self._cache_activos = [p for p in productos if p.get('activo', 1)]
        self._cache_loaded = True
        return productos

    def cache_disponible(self) -> bool:
        return self._cache_loaded

    def buscar_productos_cache(self, termino: str = '', categoria: str = None,
                               solo_activos: bool = True, limite: Optional[int] = 120) -> List[dict]:
        if not self._cache_loaded:
            return []

        termino = (termino or '').strip().lower()
        base = self._cache_activos if solo_activos else self._cache
        resultados = []

        for producto in base:
            if categoria and categoria != "Todas" and producto.get('categoria') != categoria:
                continue

            if termino:
                nombre = (producto.get('nombre') or '').lower()
                codigo = (producto.get('codigo_barras') or '').lower()
                marca = (producto.get('marca') or '').lower()
                cat = (producto.get('categoria') or '').lower()
                if termino not in nombre and termino not in codigo and termino not in marca and termino not in cat:
                    continue

            resultados.append(producto)
            if limite and len(resultados) >= limite:
                break

        return resultados
    
    @staticmethod
    def _norm(valor) -> str:
        return (valor or '').strip().lower()

    @staticmethod
    def _prefijo_sku(producto: Producto) -> str:
        """Construye un prefijo legible para el SKU a partir de los atributos."""
        def parte(valor, n):
            limpio = ''.join(ch for ch in (valor or '').upper() if ch.isalnum())
            return limpio[:n]
        partes = [p for p in (parte(producto.categoria, 3),
                              parte(producto.marca, 3),
                              parte(producto.presentacion, 3)) if p]
        return '-'.join(partes) or 'PRD'

    def _generar_sku_unico(self, cursor, producto, producto_id) -> str:
        """SKU legible + sufijo aleatorio para que sea GLOBALMENTE único.

        Antes era f"{prefijo}-{id_local:05d}", pero el id_local es específico de
        cada equipo: dos computadores creando productos a la vez generaban el
        mismo SKU y chocaban con la restricción UNIQUE de codigo_barras. Se
        añade un sufijo aleatorio (4 hex) que garantiza unicidad entre equipos;
        además se verifica la unicidad LOCAL y se reintenta si hiciera falta."""
        base = f"{self._prefijo_sku(producto)}-{producto_id:05d}"
        for _ in range(30):
            sku = f"{base}-{secrets.token_hex(2).upper()}"  # 4 hex
            cursor.execute(
                "SELECT 1 FROM productos WHERE codigo_barras = ? LIMIT 1", (sku,))
            if not cursor.fetchone():
                return sku
        # Colisión extremadamente improbable: sufijo más largo como último recurso.
        return f"{base}-{secrets.token_hex(4).upper()}"

    def existe_duplicado(self, nombre, marca, presentacion, unidad_medida,
                         exclude_id=None) -> bool:
        """Detecta un duplicado REAL: mismo nombre + marca + presentación +
        unidad de medida (variantes como 25kg vs 50kg NO se consideran iguales)."""
        conn = self.db.conectar()
        cursor = conn.cursor()
        try:
            query = '''
                SELECT id FROM productos
                WHERE activo = 1
                  AND LOWER(TRIM(COALESCE(nombre, ''))) = ?
                  AND LOWER(TRIM(COALESCE(marca, ''))) = ?
                  AND LOWER(TRIM(COALESCE(presentacion, ''))) = ?
                  AND LOWER(TRIM(COALESCE(unidad_medida, ''))) = ?
            '''
            params = [self._norm(nombre), self._norm(marca),
                      self._norm(presentacion), self._norm(unidad_medida)]
            if exclude_id:
                query += " AND id <> ?"
                params.append(exclude_id)
            cursor.execute(query, params)
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def crear_producto(self, producto: Producto,
                       inventory_mode: Optional[str] = None,
                       inventory_command_id: Optional[str] = None,
                       inventory_gateway=None,
                       inventory_transport=None,
                       inventory_connection_factory=None,
                       producto_local_id: Optional[str] = None) -> Tuple[bool, str, Optional[int]]:
        """
        Crea un nuevo producto en la base de datos
        Returns: (éxito, mensaje, id_producto)
        """
        from inventory_writer_support import WRITER_MODE_AUTHORITATIVE, resolve_writer_mode

        if resolve_writer_mode(inventory_mode) == WRITER_MODE_AUTHORITATIVE:
            return self._crear_producto_authoritative(
                producto,
                inventory_command_id=inventory_command_id,
                inventory_gateway=inventory_gateway,
                inventory_transport=inventory_transport,
                inventory_connection_factory=inventory_connection_factory,
                producto_local_id=producto_local_id,
            )

        # 1) Validación en la capa de datos (no solo en el formulario)
        valido, msg_val = producto.validar()
        if not valido:
            return False, msg_val, None

        # 2) Anti-duplicado real (mismo nombre+marca+presentación+unidad)
        if self.existe_duplicado(producto.nombre, producto.marca,
                                 producto.presentacion, producto.unidad_medida):
            return False, ("Ya existe un producto con el mismo nombre, marca, "
                           "presentación y unidad de medida. Si es una variante "
                           "distinta, especifique el tamaño/medida en 'Presentación'."), None

        conn = self.db.conectar()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                INSERT INTO productos (
                    codigo_barras, nombre, categoria, marca, presentacion, proveedor_id,
                    precio_compra, precio_venta, stock, stock_minimo,
                    ubicacion, descripcion, unidad_medida, viene_en_caja,
                    unidades_por_caja, unidades_por_media_caja, vende_por_empaque,
                    permite_decimales, iva, activo, local_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                producto.codigo_barras,
                producto.nombre,
                producto.categoria,
                producto.marca,
                producto.presentacion,
                producto.proveedor_id,
                producto.precio_compra,
                producto.precio_venta,
                producto.stock,
                producto.stock_minimo,
                producto.ubicacion,
                producto.descripcion,
                producto.unidad_medida,
                1 if producto.viene_en_caja else 0,
                producto.unidades_por_caja,
                producto.unidades_por_media_caja,
                producto.vende_por_empaque,
                1 if producto.permite_decimales else 0,
                producto.iva,
                1 if producto.activo else 0,
                str(uuid.uuid4()),
            ))

            producto_id = cursor.lastrowid

            # 3) SKU/código único automático si el usuario no ingresó uno.
            #    Globalmente único (sufijo aleatorio) para permitir creación
            #    simultánea de productos desde varios equipos sin chocar con la
            #    restricción UNIQUE de codigo_barras.
            if not (producto.codigo_barras or '').strip():
                sku = self._generar_sku_unico(cursor, producto, producto_id)
                cursor.execute('UPDATE productos SET codigo_barras = ? WHERE id = ?',
                               (sku, producto_id))

            # 4) Trazabilidad (kardex): registrar el stock inicial como movimiento
            mov_id = None
            try:
                if (producto.stock or 0) > 0:
                    uid = (self.auth.usuario_actual.id
                           if (self.auth and getattr(self.auth, 'usuario_actual', None))
                           else None)
                    cursor.execute('''
                        INSERT INTO movimientos (tipo, producto_id, usuario_id, cantidad,
                            precio_unitario, costo_total, motivo, fecha)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', ('ENTRADA_AJUSTE', producto_id, uid, producto.stock,
                          producto.precio_compra or 0,
                          (producto.precio_compra or 0) * (producto.stock or 0),
                          'Stock inicial al crear producto', _ahora()))
                    mov_id = cursor.lastrowid
            except Exception as _mov_exc:
                print(f"[KARDEX] No se pudo registrar stock inicial: {_mov_exc}")

            # 5) Local-first: encolar para sincronizar a Supabase (patrón outbox).
            self._encolar_sync(conn, "product", producto_id, "create", "productos")
            if mov_id:
                self._encolar_sync(conn, "inventory_movement", mov_id,
                                   "create", "movimientos")

            conn.commit()
            conn.close()
            self.invalidar_cache()

            self._auditar("CREAR_PRODUCTO",
                          f"Creó producto '{producto.nombre}' (id {producto_id})")
            return True, "Producto creado exitosamente", producto_id

        except Exception as e:
            conn.close()
            return False, f"Error al crear producto: {str(e)}", None

    def _crear_producto_authoritative(
        self, producto: Producto, *, inventory_command_id, inventory_gateway,
        inventory_transport, inventory_connection_factory, producto_local_id,
    ) -> Tuple[bool, str, Optional[int]]:
        import uuid as _uuid
        from inventory_gateway import OUTCOME_APPLIED, OUTCOME_REJECTED
        from inventory_ledger import QuantityScaleError, UnknownProductError, get_inventory_command_or_none
        from inventory_writer_support import (
            DOCUMENTO_TIPO_PRODUCTO, NO_INVENTORY_CHANGE, MissingProductLocalIdError,
            bind_inventory_gateway, build_positive_operations, command_already_applied,
            command_motivo_marker, find_rows_marked_for_command,
            operations_from_command_record, unknown_writer_message,
        )
        valido, msg_val = producto.validar()
        if not valido:
            return False, msg_val, None
        command_id = inventory_command_id or str(_uuid.uuid4())
        self.last_inventory_command_id = command_id
        local_id = producto_local_id or str(_uuid.uuid4())
        try:
            local_id = str(_uuid.UUID(str(local_id)))
        except (ValueError, AttributeError, TypeError):
            return False, "producto_local_id inválido", None
        initial = producto.stock or 0
        conn = self.db.conectar()
        cursor = conn.cursor()
        try:
            existing_row = cursor.execute(
                "SELECT id FROM productos WHERE local_id = ?", (local_id,)
            ).fetchone()
            if existing_row is None and self.existe_duplicado(
                producto.nombre, producto.marca,
                producto.presentacion, producto.unidad_medida,
            ):
                conn.close()
                return False, ("Ya existe un producto con el mismo nombre, marca, "
                               "presentación y unidad de medida. Si es una variante "
                               "distinta, especifique el tamaño/medida en 'Presentación'."), None
            already = command_already_applied(conn, command_id)
            if existing_row and already is not None:
                producto_id = existing_row["id"]
                if initial > 0 and not find_rows_marked_for_command(
                    conn, command_id, table="movimientos"
                ):
                    uid = (self.auth.usuario_actual.id
                           if (self.auth and getattr(self.auth, 'usuario_actual', None))
                           else None)
                    marker = command_motivo_marker(command_id)
                    cursor.execute('''
                        INSERT INTO movimientos (tipo, producto_id, usuario_id, cantidad,
                            precio_unitario, costo_total, motivo, fecha)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', ('ENTRADA_AJUSTE', producto_id, uid, initial,
                          producto.precio_compra or 0,
                          (producto.precio_compra or 0) * initial,
                          f'Stock inicial al crear producto {marker}', _ahora()))
                    self._encolar_sync(conn, "inventory_movement", cursor.lastrowid, "create", "movimientos")
                    conn.commit()
                else:
                    conn.close()
                    return True, "Producto creado exitosamente", producto_id
                conn.close()
                self.invalidar_cache()
                return True, "Producto creado exitosamente", producto_id
            if existing_row and initial <= 0:
                conn.close()
                return True, "Producto creado exitosamente", existing_row["id"]

            if existing_row:
                producto_id = existing_row["id"]
            else:
                cursor.execute('''
                    INSERT INTO productos (
                        codigo_barras, nombre, categoria, marca, presentacion, proveedor_id,
                        precio_compra, precio_venta, stock, stock_minimo,
                        ubicacion, descripcion, unidad_medida, viene_en_caja,
                        unidades_por_caja, unidades_por_media_caja, vende_por_empaque,
                        permite_decimales, iva, activo, local_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    producto.codigo_barras, producto.nombre, producto.categoria,
                    producto.marca, producto.presentacion, producto.proveedor_id,
                    producto.precio_compra, producto.precio_venta,
                    0,
                    producto.stock_minimo, producto.ubicacion, producto.descripcion,
                    producto.unidad_medida, 1 if producto.viene_en_caja else 0,
                    producto.unidades_por_caja, producto.unidades_por_media_caja,
                    producto.vende_por_empaque, 1 if producto.permite_decimales else 0,
                    producto.iva, 1 if producto.activo else 0, local_id,
                ))
                producto_id = cursor.lastrowid
                if not (producto.codigo_barras or '').strip():
                    sku = self._generar_sku_unico(cursor, producto, producto_id)
                    cursor.execute('UPDATE productos SET codigo_barras = ? WHERE id = ?',
                                   (sku, producto_id))
                self._encolar_sync(conn, "product", producto_id, "create", "productos")

            if initial <= 0:
                conn.commit()
                conn.close()
                self.invalidar_cache()
                self.last_gateway_result = NO_INVENTORY_CHANGE
                return True, "Producto creado exitosamente", producto_id

            if already is None:
                try:
                    existing_cmd = get_inventory_command_or_none(conn, command_id)
                    if existing_cmd is not None:
                        operations = operations_from_command_record(existing_cmd)
                    else:
                        operations = build_positive_operations(
                            conn, [{"producto_id": producto_id, "cantidad": initial}],
                            command_id=command_id,
                        )
                except (MissingProductLocalIdError, QuantityScaleError, UnknownProductError) as exc:
                    conn.rollback()
                    conn.close()
                    return False, str(exc), None
                gw = bind_inventory_gateway(
                    conn, gateway=inventory_gateway, transport=inventory_transport,
                    connection_factory=inventory_connection_factory, cutover_enabled=True,
                )
                try:
                    result = gw.submit(
                        tipo="AJUSTE", operations=operations, command_id=command_id,
                        documento_tipo=DOCUMENTO_TIPO_PRODUCTO, documento_local_id=local_id,
                        device_id=None,
                        usuario_id=(self.auth.usuario_actual.id
                                    if (self.auth and getattr(self.auth, 'usuario_actual', None))
                                    else None),
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
                    return False, unknown_writer_message(result.command_id, result.error or result.outcome), None

            uid = (self.auth.usuario_actual.id
                   if (self.auth and getattr(self.auth, 'usuario_actual', None))
                   else None)
            marker = command_motivo_marker(command_id)
            cursor.execute('''
                INSERT INTO movimientos (tipo, producto_id, usuario_id, cantidad,
                    precio_unitario, costo_total, motivo, fecha)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', ('ENTRADA_AJUSTE', producto_id, uid, initial,
                  producto.precio_compra or 0,
                  (producto.precio_compra or 0) * initial,
                  f'Stock inicial al crear producto {marker}', _ahora()))
            self._encolar_sync(conn, "inventory_movement", cursor.lastrowid, "create", "movimientos")
            conn.commit()
            conn.close()
            self.invalidar_cache()
            return True, "Producto creado exitosamente", producto_id
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

    def actualizar_producto(self, producto: Producto,
                            inventory_mode: Optional[str] = None,
                            inventory_command_id: Optional[str] = None,
                            inventory_gateway=None,
                            inventory_transport=None,
                            inventory_connection_factory=None,
                            inventory_stock_base_scaled: Optional[int] = None) -> Tuple[bool, str]:
        """Actualiza un producto existente.

        Legacy: metadata y stock viajan juntos (SET stock = ?).
        Autoritativo: UPDATE de metadata no puede mutar stock; un cambio de
        stock requiere InventoryCommand AJUSTE.
        """
        from inventory_writer_support import WRITER_MODE_AUTHORITATIVE, resolve_writer_mode

        if resolve_writer_mode(inventory_mode) == WRITER_MODE_AUTHORITATIVE:
            return self._actualizar_producto_authoritative(
                producto,
                inventory_command_id=inventory_command_id,
                inventory_gateway=inventory_gateway,
                inventory_transport=inventory_transport,
                inventory_connection_factory=inventory_connection_factory,
                inventory_stock_base_scaled=inventory_stock_base_scaled,
            )

        valido, msg_val = producto.validar()
        if not valido:
            return False, msg_val

        if self.existe_duplicado(producto.nombre, producto.marca,
                                 producto.presentacion, producto.unidad_medida,
                                 exclude_id=producto.id):
            return False, ("Ya existe otro producto con el mismo nombre, marca, "
                           "presentación y unidad de medida.")

        conn = self.db.conectar()
        cursor = conn.cursor()

        try:
            # Capturar precios anteriores para el historial de precios
            cursor.execute('SELECT precio_venta, precio_compra FROM productos WHERE id = ?',
                           (producto.id,))
            _ant = cursor.fetchone()
            precio_venta_ant = _ant['precio_venta'] if _ant else None
            precio_compra_ant = _ant['precio_compra'] if _ant else None

            cursor.execute('''
                UPDATE productos SET
                    codigo_barras = ?,
                    nombre = ?,
                    categoria = ?,
                    marca = ?,
                    presentacion = ?,
                    proveedor_id = ?,
                    precio_compra = ?,
                    precio_venta = ?,
                    stock = ?,
                    stock_minimo = ?,
                    ubicacion = ?,
                    descripcion = ?,
                    unidad_medida = ?,
                    viene_en_caja = ?,
                    unidades_por_caja = ?,
                    unidades_por_media_caja = ?,
                    vende_por_empaque = ?,
                    permite_decimales = ?,
                    iva = ?,
                    activo = ?
                WHERE id = ?
            ''', (
                producto.codigo_barras,
                producto.nombre,
                producto.categoria,
                producto.marca,
                producto.presentacion,
                producto.proveedor_id,
                producto.precio_compra,
                producto.precio_venta,
                producto.stock,
                producto.stock_minimo,
                producto.ubicacion,
                producto.descripcion,
                producto.unidad_medida,
                1 if producto.viene_en_caja else 0,
                producto.unidades_por_caja,
                producto.unidades_por_media_caja,
                producto.vende_por_empaque,
                1 if producto.permite_decimales else 0,
                producto.iva,
                1 if producto.activo else 0,
                producto.id
            ))

            # Historial de precios (si cambiaron)
            self._registrar_cambio_precio(cursor, producto.id, 'venta',
                                          precio_venta_ant, producto.precio_venta)
            self._registrar_cambio_precio(cursor, producto.id, 'compra',
                                          precio_compra_ant, producto.precio_compra)

            # Local-first: encolar la edición para sincronizar a Supabase.
            self._encolar_sync(conn, "product", producto.id, "update", "productos")

            conn.commit()
            conn.close()
            self.invalidar_cache()

            self._auditar("EDITAR_PRODUCTO",
                          f"Editó producto '{producto.nombre}' (id {producto.id})")
            return True, "Producto actualizado exitosamente"

        except Exception as e:
            conn.close()
            return False, f"Error al actualizar producto: {str(e)}"

    def _actualizar_producto_authoritative(
        self, producto: Producto, *, inventory_command_id, inventory_gateway,
        inventory_transport, inventory_connection_factory, inventory_stock_base_scaled,
    ) -> Tuple[bool, str]:
        import uuid as _uuid
        from inventory_gateway import OUTCOME_APPLIED, OUTCOME_REJECTED, InventoryGatewayError
        from inventory_ledger import QuantityScaleError, UnknownProductError, get_inventory_command_or_none
        from inventory_writer_support import (
            DOCUMENTO_TIPO_PRODUCTO, NO_INVENTORY_CHANGE, MissingProductLocalIdError,
            bind_inventory_gateway, build_absolute_operations, command_already_applied,
            operations_from_command_record, require_producto_local_id,
            resolve_authoritative_base_scaled, unknown_writer_message,
        )
        valido, msg_val = producto.validar()
        if not valido:
            return False, msg_val
        if self.existe_duplicado(producto.nombre, producto.marca,
                                 producto.presentacion, producto.unidad_medida,
                                 exclude_id=producto.id):
            return False, ("Ya existe otro producto con el mismo nombre, marca, "
                           "presentación y unidad de medida.")
        command_id = inventory_command_id or str(_uuid.uuid4())
        self.last_inventory_command_id = command_id
        conn = self.db.conectar()
        cursor = conn.cursor()
        try:
            current = cursor.execute(
                "SELECT stock, local_id, precio_venta, precio_compra FROM productos WHERE id = ?",
                (producto.id,),
            ).fetchone()
            if not current:
                conn.close()
                return False, "Producto no encontrado"
            target_stock = producto.stock
            stock_changed = int(current["stock"]) != int(target_stock)
            already = command_already_applied(conn, command_id)
            if stock_changed and already is None:
                try:
                    existing_cmd = get_inventory_command_or_none(conn, command_id)
                    if existing_cmd is not None:
                        operations = operations_from_command_record(existing_cmd)
                    else:
                        local_id = require_producto_local_id(conn, producto.id)
                        base = resolve_authoritative_base_scaled(
                            local_id,
                            explicit_base_scaled=inventory_stock_base_scaled,
                            connection_factory=inventory_connection_factory,
                        )
                        operations = build_absolute_operations(
                            conn, command_id=command_id, producto_id=producto.id,
                            target_qty=target_stock, base_scaled=base,
                        )
                except (MissingProductLocalIdError, QuantityScaleError, UnknownProductError) as exc:
                    conn.close()
                    return False, str(exc)
                except InventoryGatewayError as exc:
                    conn.close()
                    return False, str(exc)
                if operations:
                    gw = bind_inventory_gateway(
                        conn, gateway=inventory_gateway, transport=inventory_transport,
                        connection_factory=inventory_connection_factory, cutover_enabled=True,
                    )
                    try:
                        result = gw.submit(
                            tipo="AJUSTE", operations=operations, command_id=command_id,
                            documento_tipo=DOCUMENTO_TIPO_PRODUCTO,
                            documento_local_id=current["local_id"],
                            device_id=None,
                            usuario_id=(self.auth.usuario_actual.id
                                        if (self.auth and getattr(self.auth, 'usuario_actual', None))
                                        else None),
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
                else:
                    self.last_gateway_result = NO_INVENTORY_CHANGE
            elif not stock_changed:
                self.last_gateway_result = NO_INVENTORY_CHANGE

            cursor.execute('''
                UPDATE productos SET
                    codigo_barras = ?, nombre = ?, categoria = ?, marca = ?,
                    presentacion = ?, proveedor_id = ?, precio_compra = ?,
                    precio_venta = ?, stock_minimo = ?, ubicacion = ?,
                    descripcion = ?, unidad_medida = ?, viene_en_caja = ?,
                    unidades_por_caja = ?, unidades_por_media_caja = ?,
                    vende_por_empaque = ?, permite_decimales = ?, iva = ?, activo = ?
                WHERE id = ?
            ''', (
                producto.codigo_barras, producto.nombre, producto.categoria,
                producto.marca, producto.presentacion, producto.proveedor_id,
                producto.precio_compra, producto.precio_venta,
                producto.stock_minimo, producto.ubicacion, producto.descripcion,
                producto.unidad_medida, 1 if producto.viene_en_caja else 0,
                producto.unidades_por_caja, producto.unidades_por_media_caja,
                producto.vende_por_empaque, 1 if producto.permite_decimales else 0,
                producto.iva, 1 if producto.activo else 0, producto.id
            ))
            self._registrar_cambio_precio(cursor, producto.id, 'venta',
                                          current["precio_venta"], producto.precio_venta)
            self._registrar_cambio_precio(cursor, producto.id, 'compra',
                                          current["precio_compra"], producto.precio_compra)
            self._encolar_sync(conn, "product", producto.id, "update", "productos")
            conn.commit()
            conn.close()
            self.invalidar_cache()
            return True, "Producto actualizado exitosamente"
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
    
    def obtener_por_id(self, producto_id: int) -> Optional[dict]:
        """Obtiene un producto por su ID"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM productos WHERE id = ?', (producto_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None
    
    def obtener_por_codigo(self, codigo_barras: str) -> Optional[dict]:
        """Obtiene un producto por código de barras"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM productos WHERE codigo_barras = ?', (codigo_barras,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None
    
    def listar_productos(self, solo_activos: bool = True, limite: Optional[int] = None) -> List[dict]:
        """Lista todos los productos"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        if solo_activos:
            query = 'SELECT * FROM productos WHERE activo = 1 ORDER BY nombre'
        else:
            query = 'SELECT * FROM productos ORDER BY nombre'

        params = []
        if limite:
            query += ' LIMIT ?'
            params.append(limite)

        cursor.execute(query, params)
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def buscar_productos(
        self,
        termino: str = '',
        solo_activos: bool = True,
        limite: Optional[int] = None
    ) -> List[dict]:
        """
        Busca productos por nombre, código o categoría
        Este es el método que faltaba y causaba el error
        """
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        termino_busqueda = f"%{termino.lower()}%"
        params = [
            termino_busqueda,
            termino_busqueda,
            termino_busqueda,
            termino_busqueda,
        ]
        
        if solo_activos:
            query = '''
                SELECT * FROM productos 
                WHERE activo = 1 
                AND (
                    LOWER(nombre) LIKE ? OR 
                    LOWER(codigo_barras) LIKE ? OR 
                    LOWER(categoria) LIKE ? OR
                    LOWER(marca) LIKE ?
                )
                ORDER BY nombre
            '''
        else:
            query = '''
                SELECT * FROM productos 
                WHERE 
                    LOWER(nombre) LIKE ? OR 
                    LOWER(codigo_barras) LIKE ? OR 
                    LOWER(categoria) LIKE ? OR
                    LOWER(marca) LIKE ?
                ORDER BY nombre
            '''

        if limite:
            query += ' LIMIT ?'
            params.append(limite)

        cursor.execute(query, params)
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def actualizar_stock(self, producto_id: int, cantidad: int, operacion: str = 'sumar',
                         inventory_mode: Optional[str] = None,
                         inventory_command_id: Optional[str] = None,
                         inventory_gateway=None,
                         inventory_transport=None,
                         inventory_connection_factory=None) -> Tuple[bool, str]:
        """
        Actualiza el stock de un producto
        operacion: 'sumar' o 'restar' (DELTA, no valor absoluto)
        """
        from inventory_writer_support import WRITER_MODE_AUTHORITATIVE, resolve_writer_mode

        if resolve_writer_mode(inventory_mode) == WRITER_MODE_AUTHORITATIVE:
            return self._actualizar_stock_authoritative(
                producto_id, cantidad, operacion,
                inventory_command_id=inventory_command_id,
                inventory_gateway=inventory_gateway,
                inventory_transport=inventory_transport,
                inventory_connection_factory=inventory_connection_factory,
            )

        conn = self.db.conectar()
        cursor = conn.cursor()
        
        try:
            # Obtener stock actual
            cursor.execute('SELECT stock FROM productos WHERE id = ?', (producto_id,))
            row = cursor.fetchone()
            
            if not row:
                conn.close()
                return False, "Producto no encontrado"
            
            stock_actual = row[0]
            
            # Calcular nuevo stock
            if operacion == 'sumar':
                nuevo_stock = stock_actual + cantidad
            elif operacion == 'restar':
                nuevo_stock = stock_actual - cantidad
                if nuevo_stock < 0:
                    conn.close()
                    return False, "Stock insuficiente"
            else:
                conn.close()
                return False, "Operación inválida"
            
            # Actualizar
            cursor.execute('UPDATE productos SET stock = ? WHERE id = ?',
                         (nuevo_stock, producto_id))
            # Local-first: encolar el cambio de stock para sincronizar a Supabase.
            self._encolar_sync(conn, "product", producto_id, "update", "productos")
            conn.commit()
            conn.close()
            self.invalidar_cache()

            return True, f"Stock actualizado. Nuevo stock: {nuevo_stock}"
            
        except Exception as e:
            conn.close()
            return False, f"Error actualizando stock: {str(e)}"

    def _actualizar_stock_authoritative(
        self, producto_id: int, cantidad: int, operacion: str, *,
        inventory_command_id, inventory_gateway, inventory_transport,
        inventory_connection_factory,
    ) -> Tuple[bool, str]:
        import uuid as _uuid
        from inventory_gateway import OUTCOME_APPLIED, OUTCOME_REJECTED
        from inventory_ledger import QuantityScaleError, UnknownProductError
        from inventory_writer_support import (
            DOCUMENTO_TIPO_AJUSTE, MissingProductLocalIdError,
            bind_inventory_gateway, build_signed_operations, command_already_applied,
            unknown_writer_message,
        )
        if operacion not in ('sumar', 'restar'):
            return False, "Operación inválida"
        if cantidad is None or cantidad <= 0:
            return False, "La cantidad debe ser mayor a 0"
        signed = cantidad if operacion == 'sumar' else -cantidad
        command_id = inventory_command_id or str(_uuid.uuid4())
        self.last_inventory_command_id = command_id
        conn = self.db.conectar()
        try:
            already = command_already_applied(conn, command_id)
            if already is None:
                try:
                    operations = build_signed_operations(
                        conn, [{"producto_id": producto_id, "delta": signed}],
                        command_id=command_id,
                    )
                except (MissingProductLocalIdError, QuantityScaleError, UnknownProductError) as exc:
                    conn.close()
                    return False, str(exc)
                if not operations:
                    conn.close()
                    return True, "Stock actualizado. Sin cambio de inventario"
                gw = bind_inventory_gateway(
                    conn, gateway=inventory_gateway, transport=inventory_transport,
                    connection_factory=inventory_connection_factory, cutover_enabled=True,
                )
                try:
                    result = gw.submit(
                        tipo="AJUSTE", operations=operations, command_id=command_id,
                        documento_tipo=DOCUMENTO_TIPO_AJUSTE, device_id=None, usuario_id=None,
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
            conn.close()
            self.invalidar_cache()
            return True, "Stock actualizado"
        except Exception as e:
            try:
                conn.close()
            except Exception:
                pass
            return False, unknown_writer_message(command_id, str(e))
    
    def obtener_productos_stock_bajo(self) -> List[dict]:
        """Obtiene productos con stock bajo o crítico"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM productos 
            WHERE stock <= stock_minimo AND activo = 1
            ORDER BY stock ASC
        ''')
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def eliminar_producto(self, producto_id: int, eliminar_permanente: bool = False) -> Tuple[bool, str]:
        """
        Elimina un producto (soft delete por defecto)
        Si eliminar_permanente=True, elimina de la BD
        """
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        try:
            if eliminar_permanente:
                # Encolar el borrado remoto ANTES de borrar la fila local.
                self._encolar_borrado(conn, "product", producto_id, "productos")
                cursor.execute('DELETE FROM productos WHERE id = ?', (producto_id,))
                mensaje = "Producto eliminado permanentemente"
            else:
                cursor.execute('UPDATE productos SET activo = 0 WHERE id = ?', (producto_id,))
                # Soft delete: la fila sigue existiendo; se sincroniza como update.
                self._encolar_sync(conn, "product", producto_id, "update", "productos")
                mensaje = "Producto desactivado"

            conn.commit()
            conn.close()
            self.invalidar_cache()

            self._auditar(
                "ELIMINAR_PRODUCTO" if eliminar_permanente else "DESACTIVAR_PRODUCTO",
                f"{'Eliminó permanentemente' if eliminar_permanente else 'Desactivó'} "
                f"el producto id {producto_id}")
            return True, mensaje

        except Exception as e:
            conn.close()
            return False, f"Error al eliminar producto: {str(e)}"
    
    def obtener_kardex_producto(self, producto_id: int, limite: int = 200) -> List[dict]:
        """Kardex básico: historial de movimientos de un producto (trazabilidad).
        Incluye entradas, salidas por venta, compras y ajustes."""
        conn = self.db.conectar()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT m.fecha, m.tipo, m.cantidad, m.precio_unitario, m.costo_total,
                       m.motivo, m.num_factura,
                       u.nombre_completo AS usuario
                FROM movimientos m
                LEFT JOIN usuarios u ON m.usuario_id = u.id
                WHERE m.producto_id = ?
                ORDER BY m.fecha DESC, m.id DESC
                LIMIT ?
            ''', (producto_id, limite))
            return [dict(r) for r in cursor.fetchall()]
        finally:
            conn.close()

    def obtener_categorias(self) -> List[str]:
        """Obtiene lista única de categorías"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        cursor.execute('SELECT DISTINCT categoria FROM productos WHERE categoria IS NOT NULL ORDER BY categoria')
        rows = cursor.fetchall()
        conn.close()
        
        return [row[0] for row in rows if row[0]]
    
    def obtener_marcas(self) -> List[str]:
        """Obtiene lista única de marcas"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        cursor.execute('SELECT DISTINCT marca FROM productos WHERE marca IS NOT NULL ORDER BY marca')
        rows = cursor.fetchall()
        conn.close()
        
        return [row[0] for row in rows if row[0]]
    
    def contar_productos(self, solo_activos: bool = True) -> int:
        """Cuenta el total de productos"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        if solo_activos:
            cursor.execute('SELECT COUNT(*) FROM productos WHERE activo = 1')
        else:
            cursor.execute('SELECT COUNT(*) FROM productos')
        
        count = cursor.fetchone()[0]
        conn.close()
        
        return count
    
    def valor_total_inventario(self) -> float:
        """Calcula el valor total del inventario"""
        conn = self.db.conectar()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT SUM(stock * precio_compra)
            FROM productos
            WHERE activo = 1
        ''')

        total = cursor.fetchone()[0] or 0.0
        conn.close()

        return total

    def obtener_productos_mas_vendidos(self, limite: int = 10) -> List[dict]:
        """Obtiene los productos más vendidos"""
        conn = self.db.conectar()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT
                p.id,
                p.nombre,
                p.categoria,
                p.precio_venta,
                p.stock,
                COALESCE(SUM(dv.cantidad), 0) as total_vendido,
                COALESCE(SUM(dv.subtotal), 0) as monto_total
            FROM productos p
            LEFT JOIN detalle_ventas dv ON p.id = dv.producto_id
            LEFT JOIN ventas v ON dv.venta_id = v.id
            WHERE p.activo = 1
            AND (v.estado = 'COMPLETADA' OR v.estado IS NULL)
            GROUP BY p.id, p.nombre, p.categoria, p.precio_venta, p.stock
            ORDER BY total_vendido DESC
            LIMIT ?
        ''', (limite,))

        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    def obtener_productos_sin_movimiento(self, dias: int = 30) -> List[dict]:
        """Obtiene productos sin movimiento en X días"""
        conn = self.db.conectar()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT
                p.*,
                MAX(m.fecha) as ultimo_movimiento
            FROM productos p
            LEFT JOIN movimientos m ON p.id = m.producto_id
            WHERE p.activo = 1
            GROUP BY p.id
            HAVING ultimo_movimiento IS NULL
                OR julianday('now') - julianday(ultimo_movimiento) > ?
            ORDER BY ultimo_movimiento ASC
        ''', (dias,))

        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    def actualizar_precio_compra(self, producto_id: int, precio_compra: float) -> Tuple[bool, str]:
        """Actualiza solo el precio de compra de un producto"""
        conn = self.db.conectar()
        cursor = conn.cursor()

        try:
            cursor.execute('SELECT precio_compra FROM productos WHERE id = ?', (producto_id,))
            _a = cursor.fetchone()
            anterior = _a['precio_compra'] if _a else None

            cursor.execute('''
                UPDATE productos
                SET precio_compra = ?
                WHERE id = ?
            ''', (precio_compra, producto_id))

            self._registrar_cambio_precio(cursor, producto_id, 'compra', anterior, precio_compra)

            self._encolar_sync(conn, "product", producto_id, "update", "productos")
            conn.commit()
            conn.close()
            self.invalidar_cache()

            return True, "Precio de compra actualizado"
        except Exception as e:
            conn.close()
            return False, f"Error: {str(e)}"

    def actualizar_precio_venta(self, producto_id: int, precio_venta: float) -> Tuple[bool, str]:
        """Actualiza solo el precio de venta de un producto"""
        conn = self.db.conectar()
        cursor = conn.cursor()

        try:
            cursor.execute('SELECT precio_venta FROM productos WHERE id = ?', (producto_id,))
            _a = cursor.fetchone()
            anterior = _a['precio_venta'] if _a else None

            cursor.execute('''
                UPDATE productos
                SET precio_venta = ?
                WHERE id = ?
            ''', (precio_venta, producto_id))

            self._registrar_cambio_precio(cursor, producto_id, 'venta', anterior, precio_venta)

            self._encolar_sync(conn, "product", producto_id, "update", "productos")
            conn.commit()
            conn.close()
            self.invalidar_cache()

            return True, "Precio de venta actualizado"
        except Exception as e:
            conn.close()
            return False, f"Error: {str(e)}"

    def obtener_resumen_inventario(self) -> dict:
        """Obtiene un resumen general del inventario"""
        conn = self.db.conectar()
        cursor = conn.cursor()

        # Total productos
        cursor.execute("SELECT COUNT(*) FROM productos WHERE activo = 1")
        total_productos = cursor.fetchone()[0]

        # Productos con stock
        cursor.execute("SELECT COUNT(*) FROM productos WHERE activo = 1 AND stock > 0")
        con_stock = cursor.fetchone()[0]

        # Productos sin stock
        sin_stock = total_productos - con_stock

        # Stock crítico
        cursor.execute("SELECT COUNT(*) FROM productos WHERE activo = 1 AND stock > 0 AND stock <= stock_minimo")
        stock_critico = cursor.fetchone()[0]

        # Valor total
        cursor.execute("SELECT COALESCE(SUM(stock * precio_compra), 0) FROM productos WHERE activo = 1")
        valor_compra = cursor.fetchone()[0]

        cursor.execute("SELECT COALESCE(SUM(stock * precio_venta), 0) FROM productos WHERE activo = 1")
        valor_venta = cursor.fetchone()[0]

        conn.close()

        return {
            'total_productos': total_productos,
            'con_stock': con_stock,
            'sin_stock': sin_stock,
            'stock_critico': stock_critico,
            'valor_compra': valor_compra,
            'valor_venta': valor_venta,
            'ganancia_potencial': valor_venta - valor_compra
        }

    def listar_productos_por_proveedor(self, proveedor_id: int, solo_activos: bool = True) -> List[Producto]:
        """
        Lista todos los productos de un proveedor específico

        Args:
            proveedor_id: ID del proveedor
            solo_activos: Si True, solo retorna productos activos

        Returns:
            Lista de objetos Producto
        """
        conn = self.db.conectar()
        cursor = conn.cursor()

        try:
            if solo_activos:
                cursor.execute('''
                    SELECT * FROM productos
                    WHERE proveedor_id = ? AND activo = 1
                    ORDER BY nombre
                ''', (proveedor_id,))
            else:
                cursor.execute('''
                    SELECT * FROM productos
                    WHERE proveedor_id = ?
                    ORDER BY nombre
                ''', (proveedor_id,))

            rows = cursor.fetchall()
            conn.close()

            productos = []
            for row in rows:
                producto = Producto(
                    id=row['id'],
                    codigo_barras=row['codigo_barras'],
                    nombre=row['nombre'],
                    categoria=row['categoria'],
                    marca=row['marca'],
                    proveedor_id=row['proveedor_id'],
                    precio_compra=row['precio_compra'] or 0,
                    precio_venta=row['precio_venta'],
                    stock=row['stock'] or 0,
                    stock_minimo=row['stock_minimo'] or 10,
                    ubicacion=row['ubicacion'],
                    descripcion=row['descripcion'],
                    unidad_medida=row['unidad_medida'] or 'UNIDAD',
                    viene_en_caja=bool(row['viene_en_caja']),
                    unidades_por_caja=row['unidades_por_caja'] or 1,
                    iva=0.0,  # IVA eliminado del sistema
                    activo=bool(row['activo'])
                )
                productos.append(producto)

            return productos

        except Exception as e:
            conn.close()
            print(f"Error listando productos por proveedor: {e}")
            return []
