# -*- coding: utf-8 -*-
"""
Repositorio para gestión de egresos de caja
Maneja gastos operativos como gasolina, mantenimiento, servicios, etc.
"""
import pg_compat
from typing import List, Dict, Optional
from datetime import datetime


class EgresosCajaRepository:
    """Repositorio para gestión de egresos/gastos de caja"""
    
    def __init__(self, db_path: str):
        pass  # db_path ignorado; se usa PostgreSQL
    
    def crear_egreso(self, monto: float, categoria: str, descripcion: str, 
                    metodo_pago: str, usuario: str, id_caja: Optional[int] = None) -> int:
        """
        Registra un egreso (gasto) de caja
        Returns: ID del egreso creado
        """
        conn = pg_compat.connect()
        cursor = conn.cursor()
        
        try:
            fecha_egreso = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            cursor.execute('''
                INSERT INTO egresos_caja 
                (monto, categoria, descripcion, metodo_pago, fecha_egreso, usuario, id_caja)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (monto, categoria, descripcion, metodo_pago, fecha_egreso, usuario, id_caja))
            
            egreso_id = cursor.lastrowid
            conn.commit()
            conn.close()
            return egreso_id
            
        except Exception as e:
            conn.close()
            raise e
    
    def obtener_egresos_por_fecha(self, fecha: str) -> List[Dict]:
        """
        Obtiene todos los egresos de una fecha específica
        Args:
            fecha: Fecha en formato 'YYYY-MM-DD' o 'YYYY-MM-DD HH:MM:SS'
        Returns: Lista de diccionarios con los egresos
        """
        conn = pg_compat.connect()
        # pg_compat usa DictCursor automaticamente
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT *
            FROM egresos_caja
            WHERE DATE(fecha_egreso) = DATE(?)
            ORDER BY fecha_egreso DESC
        ''', (fecha,))
        
        egresos = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return egresos
    
    def obtener_egresos_por_usuario_fecha(self, usuario: str, fecha: str) -> List[Dict]:
        """
        Obtiene los egresos de un usuario en una fecha específica
        Args:
            usuario: Nombre de usuario
            fecha: Fecha en formato 'YYYY-MM-DD' o 'YYYY-MM-DD HH:MM:SS'
        Returns: Lista de diccionarios con los egresos
        """
        conn = pg_compat.connect()
        # pg_compat usa DictCursor automaticamente
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT *
            FROM egresos_caja
            WHERE usuario = ?
            AND DATE(fecha_egreso) = DATE(?)
            ORDER BY fecha_egreso DESC
        ''', (usuario, fecha))
        
        egresos = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return egresos
    
    def obtener_resumen_egresos_dia(self, fecha: str) -> Dict:
        """
        Obtiene el resumen de egresos del día agrupados por método de pago
        Args:
            fecha: Fecha en formato 'YYYY-MM-DD' o 'YYYY-MM-DD HH:MM:SS'
        Returns: Diccionario con totales por método de pago
        """
        conn = pg_compat.connect()
        # pg_compat usa DictCursor automaticamente
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                COALESCE(SUM(CASE WHEN UPPER(metodo_pago) = 'EFECTIVO' THEN monto ELSE 0 END), 0) as efectivo,
                COALESCE(SUM(CASE WHEN UPPER(metodo_pago) IN ('TARJETA_DEBITO', 'TARJETA_CREDITO', 'TARJETA') THEN monto ELSE 0 END), 0) as tarjeta,
                COALESCE(SUM(CASE WHEN UPPER(metodo_pago) = 'TRANSFERENCIA' THEN monto ELSE 0 END), 0) as transferencia,
                COALESCE(SUM(CASE WHEN UPPER(metodo_pago) NOT IN ('EFECTIVO', 'TARJETA_DEBITO', 'TARJETA_CREDITO', 'TARJETA', 'TRANSFERENCIA') THEN monto ELSE 0 END), 0) as otros,
                COALESCE(SUM(monto), 0) as total
            FROM egresos_caja
            WHERE DATE(fecha_egreso) = DATE(?)
        ''', (fecha,))
        
        resumen = dict(cursor.fetchone())
        conn.close()
        
        return resumen
    
    def obtener_resumen_egresos_por_usuario(self, usuario: str, fecha: str) -> Dict:
        """
        Obtiene el resumen de egresos de un usuario en una fecha
        Args:
            usuario: Nombre de usuario
            fecha: Fecha en formato 'YYYY-MM-DD' o 'YYYY-MM-DD HH:MM:SS'
        Returns: Diccionario con totales por método de pago
        """
        conn = pg_compat.connect()
        # pg_compat usa DictCursor automaticamente
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                COALESCE(SUM(CASE WHEN UPPER(metodo_pago) = 'EFECTIVO' THEN monto ELSE 0 END), 0) as efectivo,
                COALESCE(SUM(CASE WHEN UPPER(metodo_pago) IN ('TARJETA_DEBITO', 'TARJETA_CREDITO', 'TARJETA') THEN monto ELSE 0 END), 0) as tarjeta,
                COALESCE(SUM(CASE WHEN UPPER(metodo_pago) = 'TRANSFERENCIA' THEN monto ELSE 0 END), 0) as transferencia,
                COALESCE(SUM(CASE WHEN UPPER(metodo_pago) NOT IN ('EFECTIVO', 'TARJETA_DEBITO', 'TARJETA_CREDITO', 'TARJETA', 'TRANSFERENCIA') THEN monto ELSE 0 END), 0) as otros,
                COALESCE(SUM(monto), 0) as total
            FROM egresos_caja
            WHERE usuario = ?
            AND DATE(fecha_egreso) = DATE(?)
        ''', (usuario, fecha))
        
        resumen = dict(cursor.fetchone())
        conn.close()
        
        return resumen
    
    def obtener_egresos_por_categoria(self, fecha_inicio: str, fecha_fin: str) -> List[Dict]:
        """
        Obtiene el total de egresos agrupados por categoría en un rango de fechas
        Args:
            fecha_inicio: Fecha inicial
            fecha_fin: Fecha final
        Returns: Lista de diccionarios con categoría y total
        """
        conn = pg_compat.connect()
        # pg_compat usa DictCursor automaticamente
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                categoria,
                COUNT(*) as cantidad,
                SUM(monto) as total
            FROM egresos_caja
            WHERE DATE(fecha_egreso) BETWEEN DATE(?) AND DATE(?)
            GROUP BY categoria
            ORDER BY total DESC
        ''', (fecha_inicio, fecha_fin))
        
        resumen = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return resumen
