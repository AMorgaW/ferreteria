# -*- coding: utf-8 -*-
"""
Servicio de Mezclas de Pinturas
Gestiona fórmulas, validación de stock y descuento de inventario
"""
from typing import Optional, List, Tuple
from database import obtener_fecha_actual


W15_DEPRECATED = True
W15_DEAD_REASON = (
    "Writer huérfano: la UI de mezclas descuenta componentes vía "
    "VentasService.registrar_venta (W03). No borrar; no usar como writer "
    "directo. Camino autoritativo exige InventoryGateway."
)


class MezclasService:
    """Servicio para gestionar mezclas de pinturas"""

    def __init__(self, db_manager, productos_repo, auth):
        self.db = db_manager
        self.productos_repo = productos_repo
        self.auth = auth

    def validar_stock_componentes(self, componentes: List[dict]) -> Tuple[bool, str]:
        """
        Valida que haya stock suficiente para todos los componentes.
        componentes: [{'producto_id': int, 'cantidad': float}, ...]
        Returns: (es_valido, mensaje_error)
        """
        for comp in componentes:
            producto = self.productos_repo.obtener_por_id(comp['producto_id'])
            if not producto:
                return False, f"Producto ID {comp['producto_id']} no encontrado"

            stock_actual = producto.get('stock', 0)
            cantidad_requerida = comp['cantidad']

            if stock_actual < cantidad_requerida:
                nombre = producto.get('nombre', 'Desconocido')
                return False, (
                    f"Stock insuficiente de '{nombre}'.\n"
                    f"Disponible: {stock_actual:.3f} | Requerido: {cantidad_requerida:.3f}"
                )

        return True, ""

    def guardar_formula(self, nombre: str, componentes: List[dict],
                        precio_venta: float = 0, descripcion: str = '',
                        cliente_referencia: str = '',
                        unidad_medida: str = 'L') -> Tuple[bool, str, Optional[int]]:
        """
        Guarda una fórmula de mezcla para reutilizar.
        componentes: [{'producto_id': int, 'cantidad': float, 'unidad': str}, ...]
        Returns: (exito, mensaje, formula_id)
        """
        conn = self.db.conectar()
        cursor = conn.cursor()

        try:
            usuario_id = self.auth.usuario_actual.id if self.auth.usuario_actual else None
            volumen_total = sum(c['cantidad'] for c in componentes)

            cursor.execute('''
                INSERT INTO formulas_mezcla
                (nombre, descripcion, precio_venta, volumen_total,
                 unidad_medida, cliente_referencia, usuario_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (nombre, descripcion, precio_venta, volumen_total,
                  unidad_medida, cliente_referencia, usuario_id))

            formula_id = cursor.lastrowid

            for comp in componentes:
                cursor.execute('''
                    INSERT INTO formula_detalle
                    (formula_id, producto_id, cantidad, unidad_medida)
                    VALUES (?, ?, ?, ?)
                ''', (formula_id, comp['producto_id'], comp['cantidad'],
                      comp.get('unidad', 'L')))

            conn.commit()
            return True, "Formula guardada exitosamente", formula_id

        except Exception as e:
            conn.rollback()
            return False, f"Error al guardar formula: {str(e)}", None
        finally:
            conn.close()

    def obtener_formulas(self, solo_activas: bool = True) -> List[dict]:
        """Obtiene todas las fórmulas guardadas"""
        query = '''
            SELECT fm.*, u.nombre_completo as creado_por
            FROM formulas_mezcla fm
            LEFT JOIN usuarios u ON fm.usuario_id = u.id
        '''
        if solo_activas:
            query += " WHERE fm.activo = 1"
        query += " ORDER BY fm.fecha_creacion DESC"

        return self.db.ejecutar_query(query)

    def obtener_formula_detalle(self, formula_id: int) -> dict:
        """Obtiene una fórmula con sus componentes"""
        formula = self.db.ejecutar_query(
            "SELECT * FROM formulas_mezcla WHERE id = ?", (formula_id,)
        )
        if not formula:
            return None

        formula = dict(formula[0])

        componentes = self.db.ejecutar_query('''
            SELECT fd.*, p.nombre as producto_nombre, p.stock as stock_actual,
                   p.precio_venta as precio_unitario
            FROM formula_detalle fd
            JOIN productos p ON fd.producto_id = p.id
            WHERE fd.formula_id = ?
        ''', (formula_id,))

        formula['componentes'] = [dict(c) for c in componentes]
        return formula

    def buscar_formulas(self, termino: str) -> List[dict]:
        """Busca fórmulas por nombre o cliente"""
        query = '''
            SELECT fm.*, u.nombre_completo as creado_por
            FROM formulas_mezcla fm
            LEFT JOIN usuarios u ON fm.usuario_id = u.id
            WHERE fm.activo = 1
              AND (fm.nombre LIKE ? OR fm.cliente_referencia LIKE ?)
            ORDER BY fm.fecha_creacion DESC
        '''
        param = f"%{termino}%"
        return self.db.ejecutar_query(query, (param, param))

    def descontar_stock_mezcla(self, componentes: List[dict],
                                num_factura: str = '',
                                inventory_mode: Optional[str] = None,
                                inventory_command_id: Optional[str] = None,
                                inventory_gateway=None,
                                inventory_transport=None,
                                inventory_connection_factory=None) -> Tuple[bool, str]:
        """
        DEPRECATED/DEAD. Descuenta stock de cada componente de la mezcla.

        No hay callers de producción. La venta de mezcla usa W03.
        No se borra. Legacy conserva SQL directo. Autoritativo usa gateway
        (tipo VENTA: solo consumo negativo; MEZCLA del ledger exige signos
        mixtos y no aplica a este writer).
        """
        from inventory_writer_support import WRITER_MODE_AUTHORITATIVE, resolve_writer_mode

        if resolve_writer_mode(inventory_mode) == WRITER_MODE_AUTHORITATIVE:
            return self._descontar_stock_mezcla_authoritative(
                componentes,
                num_factura=num_factura,
                inventory_command_id=inventory_command_id,
                inventory_gateway=inventory_gateway,
                inventory_transport=inventory_transport,
                inventory_connection_factory=inventory_connection_factory,
            )

        # Validar stock primero
        valido, msg = self.validar_stock_componentes(componentes)
        if not valido:
            return False, msg

        conn = self.db.conectar()
        cursor = conn.cursor()

        try:
            usuario_id = self.auth.usuario_actual.id if self.auth.usuario_actual else None

            for comp in componentes:
                # Descontar stock
                cursor.execute('''
                    UPDATE productos
                    SET stock = stock - ?
                    WHERE id = ?
                ''', (comp['cantidad'], comp['producto_id']))

                # Registrar movimiento de salida
                producto = self.productos_repo.obtener_por_id(comp['producto_id'])
                precio_unit = producto.get('precio_venta', 0) if producto else 0

                cursor.execute('''
                    INSERT INTO movimientos (
                        tipo, producto_id, usuario_id, cantidad,
                        precio_unitario, costo_total, motivo, num_factura, fecha
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    'SALIDA_VENTA',
                    comp['producto_id'],
                    usuario_id,
                    comp['cantidad'],
                    precio_unit,
                    comp['cantidad'] * precio_unit,
                    f'Mezcla pintura - {num_factura}' if num_factura else 'Mezcla pintura',
                    num_factura,
                    obtener_fecha_actual()
                ))
                _mz_mov_id = cursor.lastrowid

                # Local-first: encolar movimiento y producto (stock).
                from repositories._outbox import encolar
                encolar(conn, "inventory_movement", _mz_mov_id, "create", "movimientos")
                encolar(conn, "product", comp['producto_id'], "update", "productos")

            conn.commit()
            return True, "Stock descontado exitosamente"

        except Exception as e:
            conn.rollback()
            return False, f"Error al descontar stock: {str(e)}"
        finally:
            conn.close()

    def _descontar_stock_mezcla_authoritative(
        self,
        componentes: List[dict],
        *,
        num_factura: str,
        inventory_command_id,
        inventory_gateway,
        inventory_transport,
        inventory_connection_factory,
    ) -> Tuple[bool, str]:
        import uuid as _uuid

        from inventory_gateway import OUTCOME_APPLIED, OUTCOME_REJECTED
        from inventory_ledger import QuantityScaleError, UnknownProductError
        from inventory_writer_support import (
            DOCUMENTO_TIPO_MEZCLA,
            MissingProductLocalIdError,
            bind_inventory_gateway,
            build_negative_operations,
            command_already_applied,
            command_motivo_marker,
            find_rows_marked_for_command,
            unknown_writer_message,
        )
        from repositories._outbox import encolar

        command_id = inventory_command_id or str(_uuid.uuid4())
        self.last_inventory_command_id = command_id
        conn = self.db.conectar()
        cursor = conn.cursor()
        try:
            already = command_already_applied(conn, command_id)
            if already is not None:
                marked = find_rows_marked_for_command(
                    conn, command_id, table="movimientos"
                )
                if marked:
                    return True, "Stock descontado exitosamente"
            else:
                try:
                    operations = build_negative_operations(
                        conn, componentes, command_id=command_id
                    )
                except MissingProductLocalIdError as exc:
                    return False, str(exc)
                except (QuantityScaleError, UnknownProductError) as exc:
                    return False, str(exc)

                gw = bind_inventory_gateway(
                    conn,
                    gateway=inventory_gateway,
                    transport=inventory_transport,
                    connection_factory=inventory_connection_factory,
                    cutover_enabled=True,
                )
                usuario_id = self.auth.usuario_actual.id if self.auth.usuario_actual else None
                try:
                    result = gw.submit(
                        tipo="VENTA",
                        operations=operations,
                        command_id=command_id,
                        documento_tipo=DOCUMENTO_TIPO_MEZCLA,
                        device_id=None,
                        usuario_id=usuario_id,
                    )
                except Exception as exc:
                    return False, unknown_writer_message(command_id, str(exc))

                self.last_gateway_result = result
                if result.outcome == OUTCOME_REJECTED:
                    return False, result.error or "Inventario rechazado por el coordinador"
                if result.outcome != OUTCOME_APPLIED:
                    return False, unknown_writer_message(
                        result.command_id, result.error or result.outcome
                    )

            marker = command_motivo_marker(command_id)
            usuario_id = self.auth.usuario_actual.id if self.auth.usuario_actual else None
            for comp in componentes:
                producto = self.productos_repo.obtener_por_id(comp['producto_id'])
                precio_unit = producto.get('precio_venta', 0) if producto else 0
                cursor.execute('''
                    INSERT INTO movimientos (
                        tipo, producto_id, usuario_id, cantidad,
                        precio_unitario, costo_total, motivo, num_factura, fecha
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    'SALIDA_VENTA',
                    comp['producto_id'],
                    usuario_id,
                    comp['cantidad'],
                    precio_unit,
                    comp['cantidad'] * precio_unit,
                    (
                        f'Mezcla pintura - {num_factura} {marker}'
                        if num_factura
                        else f'Mezcla pintura {marker}'
                    ),
                    num_factura,
                    obtener_fecha_actual()
                ))
                _mz_mov_id = cursor.lastrowid
                encolar(conn, "inventory_movement", _mz_mov_id, "create", "movimientos")

            conn.commit()
            return True, "Stock descontado exitosamente"
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return False, unknown_writer_message(command_id, str(e))
        finally:
            conn.close()

    def eliminar_formula(self, formula_id: int) -> Tuple[bool, str]:
        """Desactiva una fórmula (borrado lógico)"""
        conn = self.db.conectar()
        cursor = conn.cursor()

        try:
            cursor.execute(
                "UPDATE formulas_mezcla SET activo = 0 WHERE id = ?",
                (formula_id,)
            )
            conn.commit()
            return True, "Formula eliminada"
        except Exception as e:
            conn.rollback()
            return False, f"Error: {str(e)}"
        finally:
            conn.close()

    def calcular_precio_mezcla(self, componentes: List[dict]) -> float:
        """
        Calcula el precio de la mezcla basado en el costo proporcional
        de cada componente.
        """
        precio_total = 0
        for comp in componentes:
            producto = self.productos_repo.obtener_por_id(comp['producto_id'])
            if producto:
                precio_total += producto.get('precio_venta', 0) * comp['cantidad']
        return precio_total
