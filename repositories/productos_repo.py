# -*- coding: utf-8 -*-
"""
Repositorio para gestión de productos
Capa de acceso a datos para productos
"""
from typing import List, Optional, Tuple
from models import Producto

class ProductosRepository:
    """Repositorio de productos"""
    
    def __init__(self, db_manager):
        self.db = db_manager
    
    def crear_producto(self, producto: Producto) -> Tuple[bool, str, Optional[int]]:
        """
        Crea un nuevo producto en la base de datos
        Returns: (éxito, mensaje, id_producto)
        """
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO productos (
                    codigo_barras, nombre, categoria, marca, proveedor_id,
                    precio_compra, precio_venta, stock, stock_minimo,
                    ubicacion, descripcion, unidad_medida, viene_en_caja,
                    unidades_por_caja, unidades_por_media_caja, vende_por_empaque,
                    permite_decimales, iva, activo
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                producto.codigo_barras,
                producto.nombre,
                producto.categoria,
                producto.marca,
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
                1 if producto.activo else 0
            ))
            
            conn.commit()
            producto_id = cursor.lastrowid
            conn.close()
            
            return True, "Producto creado exitosamente", producto_id
            
        except Exception as e:
            conn.close()
            return False, f"Error al crear producto: {str(e)}", None
    
    def actualizar_producto(self, producto: Producto) -> Tuple[bool, str]:
        """Actualiza un producto existente"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE productos SET
                    codigo_barras = ?,
                    nombre = ?,
                    categoria = ?,
                    marca = ?,
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
            
            conn.commit()
            conn.close()
            
            return True, "Producto actualizado exitosamente"
            
        except Exception as e:
            conn.close()
            return False, f"Error al actualizar producto: {str(e)}"
    
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
    
    def listar_productos(self, solo_activos: bool = True) -> List[dict]:
        """Lista todos los productos"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        if solo_activos:
            cursor.execute('SELECT * FROM productos WHERE activo = 1 ORDER BY nombre')
        else:
            cursor.execute('SELECT * FROM productos ORDER BY nombre')
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def buscar_productos(self, termino: str = '', solo_activos: bool = True) -> List[dict]:
        """
        Busca productos por nombre, código o categoría
        Este es el método que faltaba y causaba el error
        """
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        termino_busqueda = f"%{termino}%"
        
        if solo_activos:
            cursor.execute('''
                SELECT * FROM productos 
                WHERE activo = 1 
                AND (
                    nombre LIKE ? OR 
                    codigo_barras LIKE ? OR 
                    categoria LIKE ? OR
                    marca LIKE ?
                )
                ORDER BY nombre
            ''', (termino_busqueda, termino_busqueda, termino_busqueda, termino_busqueda))
        else:
            cursor.execute('''
                SELECT * FROM productos 
                WHERE 
                    nombre LIKE ? OR 
                    codigo_barras LIKE ? OR 
                    categoria LIKE ? OR
                    marca LIKE ?
                ORDER BY nombre
            ''', (termino_busqueda, termino_busqueda, termino_busqueda, termino_busqueda))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def actualizar_stock(self, producto_id: int, cantidad: int, operacion: str = 'sumar') -> Tuple[bool, str]:
        """
        Actualiza el stock de un producto
        operacion: 'sumar' o 'restar'
        """
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
            conn.commit()
            conn.close()
            
            return True, f"Stock actualizado. Nuevo stock: {nuevo_stock}"
            
        except Exception as e:
            conn.close()
            return False, f"Error actualizando stock: {str(e)}"
    
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
                cursor.execute('DELETE FROM productos WHERE id = ?', (producto_id,))
                mensaje = "Producto eliminado permanentemente"
            else:
                cursor.execute('UPDATE productos SET activo = 0 WHERE id = ?', (producto_id,))
                mensaje = "Producto desactivado"
            
            conn.commit()
            conn.close()
            
            return True, mensaje
            
        except Exception as e:
            conn.close()
            return False, f"Error al eliminar producto: {str(e)}"
    
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
            cursor.execute('''
                UPDATE productos
                SET precio_compra = ?
                WHERE id = ?
            ''', (precio_compra, producto_id))

            conn.commit()
            conn.close()

            return True, "Precio de compra actualizado"
        except Exception as e:
            conn.close()
            return False, f"Error: {str(e)}"

    def actualizar_precio_venta(self, producto_id: int, precio_venta: float) -> Tuple[bool, str]:
        """Actualiza solo el precio de venta de un producto"""
        conn = self.db.conectar()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                UPDATE productos
                SET precio_venta = ?
                WHERE id = ?
            ''', (precio_venta, producto_id))

            conn.commit()
            conn.close()

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