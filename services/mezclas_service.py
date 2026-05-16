# -*- coding: utf-8 -*-
"""
Servicio de Mezclas de Pinturas
Gestiona fórmulas, validación de stock y descuento de inventario
"""
from typing import Optional, List, Tuple
from database import obtener_fecha_actual


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
                                num_factura: str = '') -> Tuple[bool, str]:
        """
        Descuenta stock de cada componente de la mezcla.
        Se llama al procesar la venta.
        componentes: [{'producto_id': int, 'cantidad': float}, ...]
        """
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

            conn.commit()
            return True, "Stock descontado exitosamente"

        except Exception as e:
            conn.rollback()
            return False, f"Error al descontar stock: {str(e)}"
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
