# -*- coding: utf-8 -*-
"""
Repositorio de Clientes
Gestión de datos de clientes
"""
import sqlite3
from typing import List, Optional, Tuple
from models import Cliente


class ClientesRepository:
    """Repositorio para gestión de clientes"""
    
    def __init__(self, db_manager):
        self.db = db_manager
        self._cache = []
        self._cache_loaded = False

    def invalidar_cache(self):
        self._cache = []
        self._cache_loaded = False

    def precargar_cache(self):
        clientes = self.listar_clientes(solo_activos=False)
        self._cache = clientes
        self._cache_loaded = True
        return clientes

    def cache_disponible(self) -> bool:
        return self._cache_loaded

    def buscar_clientes_cache(
        self,
        criterio: str = None,
        solo_activos: bool = True,
        limite: Optional[int] = 120
    ) -> List[Cliente]:
        if not self._cache_loaded:
            return []

        criterio = (criterio or '').strip().lower()
        resultados = []

        for cliente in self._cache:
            if solo_activos and not cliente.activo:
                continue

            if criterio:
                texto = " ".join([
                    cliente.nombre or '',
                    cliente.numero_documento or '',
                    cliente.telefono or '',
                    cliente.ciudad or '',
                ]).lower()
                if criterio not in texto:
                    continue

            resultados.append(cliente)
            if limite and len(resultados) >= limite:
                break

        return resultados
    
    def crear_cliente(self, cliente: Cliente) -> Tuple[bool, str, Optional[int]]:
        """Crea un nuevo cliente"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO clientes (
                    tipo_documento, numero_documento, nombre, telefono,
                    email, direccion, ciudad, limite_credito,
                    saldo_pendiente, clasificacion, descuento_default,
                    puntos_fidelidad, activo
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                cliente.tipo_documento, cliente.numero_documento, cliente.nombre,
                cliente.telefono, cliente.email, cliente.direccion, cliente.ciudad,
                cliente.limite_credito, cliente.saldo_pendiente, cliente.clasificacion,
                cliente.descuento_default, cliente.puntos_fidelidad,
                1 if cliente.activo else 0
            ))
            
            cliente_id = cursor.lastrowid
            from repositories._outbox import encolar
            encolar(conn, "customer", cliente_id, "create", "clientes")
            conn.commit()
            conn.close()
            self.invalidar_cache()
            return True, "Cliente creado exitosamente", cliente_id
            
        except sqlite3.IntegrityError:
            conn.close()
            return False, "El número de documento ya existe", None
        except Exception as e:
            conn.close()
            return False, f"Error al crear cliente: {str(e)}", None
    
    def obtener_cliente(self, cliente_id: int) -> Optional[Cliente]:
        """Obtiene un cliente por ID"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM clientes WHERE id = ?', (cliente_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return self._row_to_cliente(row)
        return None
    
    def buscar_clientes(
        self,
        criterio: str = None,
        solo_activos: bool = True,
        limite: Optional[int] = None
    ) -> List[Cliente]:
        """Busca clientes por nombre o documento"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        if criterio:
            query = 'SELECT * FROM clientes WHERE (LOWER(nombre) LIKE ? OR LOWER(numero_documento) LIKE ?)'
            criterio_busqueda = f'%{criterio.lower()}%'
            params = [criterio_busqueda, criterio_busqueda]
            if solo_activos:
                query += ' AND activo = 1'
            query += ' ORDER BY nombre'
            if limite:
                query += ' LIMIT ?'
                params.append(limite)
            cursor.execute(query, params)
        else:
            query = 'SELECT * FROM clientes'
            params = []
            if solo_activos:
                query += ' WHERE activo = 1'
            query += ' ORDER BY nombre'
            if limite:
                query += ' LIMIT ?'
                params.append(limite)
            cursor.execute(query, params)
        
        rows = cursor.fetchall()
        conn.close()
        return [self._row_to_cliente(row) for row in rows]
    
    def listar_clientes(self, solo_activos: bool = True, limite: Optional[int] = None) -> List[Cliente]:
        """Lista todos los clientes"""
        return self.buscar_clientes(criterio=None, solo_activos=solo_activos, limite=limite)
    
    def actualizar_cliente(self, cliente: Cliente) -> Tuple[bool, str]:
        """Actualiza los datos de un cliente"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE clientes SET
                    tipo_documento = ?, numero_documento = ?, nombre = ?,
                    telefono = ?, email = ?, direccion = ?, ciudad = ?,
                    limite_credito = ?, saldo_pendiente = ?, clasificacion = ?,
                    descuento_default = ?, puntos_fidelidad = ?, activo = ?
                WHERE id = ?
            ''', (
                cliente.tipo_documento, cliente.numero_documento, cliente.nombre,
                cliente.telefono, cliente.email, cliente.direccion, cliente.ciudad,
                cliente.limite_credito, cliente.saldo_pendiente, cliente.clasificacion,
                cliente.descuento_default, cliente.puntos_fidelidad,
                1 if cliente.activo else 0, cliente.id
            ))

            from repositories._outbox import encolar
            encolar(conn, "customer", cliente.id, "update", "clientes")
            conn.commit()
            conn.close()
            self.invalidar_cache()
            return True, "Cliente actualizado exitosamente"
            
        except sqlite3.IntegrityError:
            conn.close()
            return False, "El número de documento ya existe para otro cliente"
        except Exception as e:
            conn.close()
            return False, f"Error al actualizar cliente: {str(e)}"
    
    def eliminar_cliente(self, cliente_id: int) -> Tuple[bool, str]:
        """Elimina un cliente (solo si no tiene ventas)"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM ventas WHERE cliente_id = ?', (cliente_id,))
        if cursor.fetchone()[0] > 0:
            conn.close()
            return False, "No se puede eliminar: el cliente tiene ventas registradas"
        
        try:
            from repositories._outbox import encolar_borrado
            encolar_borrado(conn, "customer", cliente_id, "clientes")
            cursor.execute('DELETE FROM clientes WHERE id = ?', (cliente_id,))
            conn.commit()
            conn.close()
            self.invalidar_cache()
            return True, "Cliente eliminado exitosamente"
        except Exception as e:
            conn.close()
            return False, f"Error al eliminar cliente: {str(e)}"
    
    def buscar_por_documento(self, numero_documento: str) -> Optional[Cliente]:
        """Busca un cliente por número de documento"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM clientes WHERE numero_documento = ?', (numero_documento,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return self._row_to_cliente(row)
        return None
    
    def actualizar_saldo(self, cliente_id: int, nuevo_saldo: float) -> Tuple[bool, str]:
        """Actualiza el saldo pendiente de un cliente"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        cursor.execute('UPDATE clientes SET saldo_pendiente = ? WHERE id = ?', (nuevo_saldo, cliente_id))
        conn.commit()
        conn.close()
        self.invalidar_cache()
        return True, "Saldo actualizado exitosamente"
    
    def _row_to_cliente(self, row) -> Cliente:
        """Convierte una fila de la BD a objeto Cliente"""
        return Cliente(
            id=row['id'],
            tipo_documento=row['tipo_documento'],
            numero_documento=row['numero_documento'],
            nombre=row['nombre'],
            telefono=row['telefono'],
            email=row['email'],
            direccion=row['direccion'],
            ciudad=row['ciudad'],
            limite_credito=row['limite_credito'],
            saldo_pendiente=row['saldo_pendiente'],
            clasificacion=row['clasificacion'],
            descuento_default=row['descuento_default'],
            puntos_fidelidad=row['puntos_fidelidad'],
            activo=bool(row['activo']),
            fecha_registro=row['fecha_registro']
        )
