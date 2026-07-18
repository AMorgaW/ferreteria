# -*- coding: utf-8 -*-
"""
Repositorio para gestión de proveedores
Capa de acceso a datos para proveedores
"""
from typing import List, Optional, Tuple
from models import Proveedor

class ProveedoresRepository:
    """Repositorio de proveedores"""
    
    def __init__(self, db_manager):
        self.db = db_manager
        self._cache = []
        self._cache_loaded = False

    def invalidar_cache(self):
        self._cache = []
        self._cache_loaded = False

    def precargar_cache(self):
        proveedores = self.listar_proveedores(solo_activos=False)
        self._cache = proveedores
        self._cache_loaded = True
        return proveedores

    def cache_disponible(self) -> bool:
        return self._cache_loaded

    def buscar_proveedores_cache(
        self,
        termino: str = '',
        solo_activos: bool = True,
        limite: Optional[int] = 120
    ) -> List[Proveedor]:
        if not self._cache_loaded:
            return []

        termino = (termino or '').strip().lower()
        resultados = []

        for proveedor in self._cache:
            if solo_activos and not proveedor.activo:
                continue

            if termino:
                texto = " ".join([
                    proveedor.nombre or '',
                    proveedor.nit or '',
                    proveedor.ciudad or '',
                    proveedor.productos_provee or '',
                    proveedor.correo or '',
                ]).lower()
                if termino not in texto:
                    continue

            resultados.append(proveedor)
            if limite and len(resultados) >= limite:
                break

        return resultados
    
    def crear_proveedor(self, proveedor: Proveedor) -> Tuple[bool, str, Optional[int]]:
        """
        Crea un nuevo proveedor en la base de datos
        Returns: (éxito, mensaje, id_proveedor)
        """
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO proveedores (
                    nit, nombre, telefono, correo, direccion, ciudad,
                    contacto_nombre, contacto_telefono, productos_provee,
                    calificacion, dias_credito, activo
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                proveedor.nit,
                proveedor.nombre,
                proveedor.telefono,
                proveedor.correo,
                proveedor.direccion,
                proveedor.ciudad,
                proveedor.contacto_nombre,
                proveedor.contacto_telefono,
                proveedor.productos_provee,
                proveedor.calificacion,
                proveedor.dias_credito,
                1 if proveedor.activo else 0
            ))
            
            proveedor_id = cursor.lastrowid
            from repositories._outbox import encolar
            encolar(conn, "supplier", proveedor_id, "create", "proveedores")
            conn.commit()
            conn.close()
            self.invalidar_cache()

            return True, "Proveedor creado exitosamente", proveedor_id
            
        except Exception as e:
            conn.close()
            return False, f"Error al crear proveedor: {str(e)}", None
    
    def actualizar_proveedor(self, proveedor: Proveedor) -> Tuple[bool, str]:
        """Actualiza un proveedor existente"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE proveedores SET
                    nit = ?,
                    nombre = ?,
                    telefono = ?,
                    correo = ?,
                    direccion = ?,
                    ciudad = ?,
                    contacto_nombre = ?,
                    contacto_telefono = ?,
                    productos_provee = ?,
                    calificacion = ?,
                    dias_credito = ?,
                    activo = ?
                WHERE id = ?
            ''', (
                proveedor.nit,
                proveedor.nombre,
                proveedor.telefono,
                proveedor.correo,
                proveedor.direccion,
                proveedor.ciudad,
                proveedor.contacto_nombre,
                proveedor.contacto_telefono,
                proveedor.productos_provee,
                proveedor.calificacion,
                proveedor.dias_credito,
                1 if proveedor.activo else 0,
                proveedor.id
            ))

            from repositories._outbox import encolar
            encolar(conn, "supplier", proveedor.id, "update", "proveedores")
            conn.commit()
            conn.close()
            self.invalidar_cache()
            
            return True, "Proveedor actualizado exitosamente"
            
        except Exception as e:
            conn.close()
            return False, f"Error al actualizar proveedor: {str(e)}"
    
    def obtener_por_id(self, proveedor_id: int) -> Optional[Proveedor]:
        """Obtiene un proveedor por su ID"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM proveedores WHERE id = ?', (proveedor_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return Proveedor(
                id=row['id'],
                nit=row['nit'],
                nombre=row['nombre'],
                telefono=row['telefono'],
                correo=row['correo'],
                direccion=row['direccion'],
                ciudad=row['ciudad'],
                contacto_nombre=row['contacto_nombre'],
                contacto_telefono=row['contacto_telefono'],
                productos_provee=row['productos_provee'],
                calificacion=row['calificacion'],
                dias_credito=row['dias_credito'],
                activo=bool(row['activo']),
                fecha_registro=row['fecha_registro']
            )
        return None
    
    def obtener_por_nit(self, nit: str) -> Optional[Proveedor]:
        """Obtiene un proveedor por NIT"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM proveedores WHERE nit = ?', (nit,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return Proveedor(
                id=row['id'],
                nit=row['nit'],
                nombre=row['nombre'],
                telefono=row['telefono'],
                correo=row['correo'],
                direccion=row['direccion'],
                ciudad=row['ciudad'],
                contacto_nombre=row['contacto_nombre'],
                contacto_telefono=row['contacto_telefono'],
                productos_provee=row['productos_provee'],
                calificacion=row['calificacion'],
                dias_credito=row['dias_credito'],
                activo=bool(row['activo']),
                fecha_registro=row['fecha_registro']
            )
        return None
    
    def listar_proveedores(self, solo_activos: bool = True, limite: Optional[int] = None) -> List[Proveedor]:
        """
        Lista todos los proveedores
        [OK] CORREGIDO: Ahora devuelve objetos Proveedor en lugar de diccionarios
        """
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        if solo_activos:
            query = 'SELECT * FROM proveedores WHERE activo = 1 ORDER BY nombre'
        else:
            query = 'SELECT * FROM proveedores ORDER BY nombre'

        params = []
        if limite:
            query += ' LIMIT ?'
            params.append(limite)

        cursor.execute(query, params)
        
        rows = cursor.fetchall()
        conn.close()
        
        # [OK] CORREGIDO: Devolver objetos Proveedor
        proveedores = []
        for row in rows:
            proveedor = Proveedor(
                id=row['id'],
                nit=row['nit'],
                nombre=row['nombre'],
                telefono=row['telefono'],
                correo=row['correo'],
                direccion=row['direccion'],
                ciudad=row['ciudad'],
                contacto_nombre=row['contacto_nombre'],
                contacto_telefono=row['contacto_telefono'],
                productos_provee=row['productos_provee'],
                calificacion=row['calificacion'],
                dias_credito=row['dias_credito'],
                activo=bool(row['activo']),
                fecha_registro=row['fecha_registro']
            )
            proveedores.append(proveedor)
        
        return proveedores
    
    def buscar_proveedores(
        self,
        termino: str = '',
        solo_activos: bool = True,
        limite: Optional[int] = None
    ) -> List[Proveedor]:
        """Busca proveedores por nombre, NIT o ciudad"""
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
                SELECT * FROM proveedores 
                WHERE activo = 1 
                AND (
                    LOWER(nombre) LIKE ? OR 
                    LOWER(nit) LIKE ? OR 
                    LOWER(ciudad) LIKE ? OR
                    LOWER(productos_provee) LIKE ?
                )
                ORDER BY nombre
            '''
        else:
            query = '''
                SELECT * FROM proveedores 
                WHERE 
                    LOWER(nombre) LIKE ? OR 
                    LOWER(nit) LIKE ? OR 
                    LOWER(ciudad) LIKE ? OR
                    LOWER(productos_provee) LIKE ?
                ORDER BY nombre
            '''

        if limite:
            query += ' LIMIT ?'
            params.append(limite)

        cursor.execute(query, params)
        
        rows = cursor.fetchall()
        conn.close()
        
        proveedores = []
        for row in rows:
            proveedor = Proveedor(
                id=row['id'],
                nit=row['nit'],
                nombre=row['nombre'],
                telefono=row['telefono'],
                correo=row['correo'],
                direccion=row['direccion'],
                ciudad=row['ciudad'],
                contacto_nombre=row['contacto_nombre'],
                contacto_telefono=row['contacto_telefono'],
                productos_provee=row['productos_provee'],
                calificacion=row['calificacion'],
                dias_credito=row['dias_credito'],
                activo=bool(row['activo']),
                fecha_registro=row['fecha_registro']
            )
            proveedores.append(proveedor)
        
        return proveedores
    
    def eliminar_proveedor(self, proveedor_id: int, eliminar_permanente: bool = False) -> Tuple[bool, str]:
        """
        Elimina un proveedor (soft delete por defecto)
        Si eliminar_permanente=True, elimina de la BD
        """
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        try:
            if eliminar_permanente:
                # Verificar que no tenga productos asociados
                cursor.execute('SELECT COUNT(*) FROM productos WHERE proveedor_id = ?', (proveedor_id,))
                count = cursor.fetchone()[0]
                
                if count > 0:
                    conn.close()
                    return False, f"No se puede eliminar. Tiene {count} productos asociados"
                
                from repositories._outbox import encolar_borrado
                encolar_borrado(conn, "supplier", proveedor_id, "proveedores")
                cursor.execute('DELETE FROM proveedores WHERE id = ?', (proveedor_id,))
                mensaje = "Proveedor eliminado permanentemente"
            else:
                cursor.execute('UPDATE proveedores SET activo = 0 WHERE id = ?', (proveedor_id,))
                from repositories._outbox import encolar
                encolar(conn, "supplier", proveedor_id, "update", "proveedores")
                mensaje = "Proveedor desactivado"

            conn.commit()
            conn.close()
            self.invalidar_cache()
            
            return True, mensaje
            
        except Exception as e:
            conn.close()
            return False, f"Error al eliminar proveedor: {str(e)}"
    
    def actualizar_calificacion(self, proveedor_id: int, nueva_calificacion: float) -> Tuple[bool, str]:
        """Actualiza la calificación de un proveedor (1-5 estrellas)"""
        if nueva_calificacion < 0 or nueva_calificacion > 5:
            return False, "La calificación debe estar entre 0 y 5"
        
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        try:
            cursor.execute('UPDATE proveedores SET calificacion = ? WHERE id = ?',
                         (nueva_calificacion, proveedor_id))
            conn.commit()
            conn.close()
            
            return True, "Calificación actualizada"
            
        except Exception as e:
            conn.close()
            return False, f"Error actualizando calificación: {str(e)}"
    
    def obtener_ciudades(self) -> List[str]:
        """Obtiene lista única de ciudades"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        cursor.execute('SELECT DISTINCT ciudad FROM proveedores WHERE ciudad IS NOT NULL ORDER BY ciudad')
        rows = cursor.fetchall()
        conn.close()
        
        return [row[0] for row in rows if row[0]]
    
    def contar_proveedores(self, solo_activos: bool = True) -> int:
        """Cuenta el total de proveedores"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        if solo_activos:
            cursor.execute('SELECT COUNT(*) FROM proveedores WHERE activo = 1')
        else:
            cursor.execute('SELECT COUNT(*) FROM proveedores')
        
        count = cursor.fetchone()[0]
        conn.close()
        
        return count
    
    def obtener_proveedores_top(self, limite: int = 10) -> List[dict]:
        """Obtiene los proveedores con mejor calificación"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT p.*, COUNT(m.id) as total_compras
            FROM proveedores p
            LEFT JOIN movimientos m ON p.id = m.proveedor_id 
                AND m.tipo = 'ENTRADA_COMPRA'
            WHERE p.activo = 1
            GROUP BY p.id
            ORDER BY p.calificacion DESC, total_compras DESC
            LIMIT ?
        ''', (limite,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def obtener_estadisticas_proveedor(self, proveedor_id: int) -> dict:
        """Obtiene estadísticas de un proveedor"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        # Total de compras
        cursor.execute('''
            SELECT 
                COUNT(*) as total_compras,
                COALESCE(SUM(costo_total), 0) as monto_total
            FROM movimientos
            WHERE proveedor_id = ? AND tipo = 'ENTRADA_COMPRA'
        ''', (proveedor_id,))
        
        row = cursor.fetchone()
        
        # Productos del proveedor
        cursor.execute('''
            SELECT COUNT(*) 
            FROM productos 
            WHERE proveedor_id = ? AND activo = 1
        ''', (proveedor_id,))
        
        productos_count = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            'total_compras': row[0],
            'monto_total_comprado': row[1],
            'productos_activos': productos_count
        }
