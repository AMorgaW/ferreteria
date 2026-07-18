# -*- coding: utf-8 -*-
"""
Servicio de Caja
Gestiona apertura y cierre de caja, incluyendo egresos operativos
"""
import sqlite3
from typing import Optional, Tuple
from datetime import datetime


def _reconciliar_pagos_proveedor():
    try:
        from repositories.abonos_compras_repo import reconciliar_pagos_proveedor_huerfanos
        reconciliar_pagos_proveedor_huerfanos()
    except Exception as e:
        print(f"[CAJA] No se pudieron reconciliar pagos a proveedor: {e}")


class CajaService:
    """Servicio para gestión de caja"""
    
    def __init__(self, db_manager, auth_manager):
        self.db = db_manager
        self.auth = auth_manager
    
    def obtener_caja_abierta(self) -> Optional[dict]:
        """Obtiene la caja abierta actual (compartida entre todos los usuarios)"""
        if not self.auth.usuario_actual:
            return None
        
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM cierres_caja
            WHERE fecha_cierre IS NULL
            ORDER BY fecha_apertura DESC
            LIMIT 1
        ''')
        
        caja = cursor.fetchone()
        conn.close()
        
        if caja:
            return dict(caja)
        return None
    
    def abrir_caja(self, monto_inicial: float) -> Tuple[bool, str]:
        """Abre una nueva caja"""
        if not self.auth.usuario_actual or self.auth.usuario_actual.rol not in ('ADMIN', 'GERENTE'):
            return False, "Solo administradores o gerentes pueden abrir la caja"
        
        # Verificar que no haya una caja abierta
        caja_abierta = self.obtener_caja_abierta()
        if caja_abierta:
            return False, "Ya tiene una caja abierta. Debe cerrarla primero."
        
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO cierres_caja (
                    usuario_id, monto_inicial, fecha_apertura
                ) VALUES (?, ?, CURRENT_TIMESTAMP)
            ''', (self.auth.usuario_actual.id, monto_inicial))
            _caja_id = cursor.lastrowid

            from repositories._outbox import encolar
            encolar(conn, "cash_session", _caja_id, "create", "cierres_caja")

            conn.commit()
            
            # Registrar en auditoría
            self.auth.registrar_auditoria(
                self.auth.usuario_actual.id,
                "ABRIR_CAJA",
                "Caja",
                f"Caja abierta con monto inicial: ${monto_inicial:,.2f}"
            )
            
            conn.close()
            return True, "Caja abierta exitosamente"
            
        except Exception as e:
            conn.close()
            return False, f"Error al abrir caja: {str(e)}"
    
    def cerrar_caja(self, monto_real: float, observaciones: str = None) -> Tuple[bool, str]:
        """Cierra la caja actual"""
        if not self.auth.usuario_actual or self.auth.usuario_actual.rol not in ('ADMIN', 'GERENTE'):
            return False, "Solo administradores o gerentes pueden cerrar la caja"

        caja_abierta = self.obtener_caja_abierta()
        
        if not caja_abierta:
            return False, "No hay una caja abierta"
        
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        try:
            # Obtener resumen de ventas de TODOS los usuarios desde la apertura
            cursor.execute('''
                SELECT 
                    COALESCE(SUM(CASE WHEN metodo_pago = 'EFECTIVO' THEN total ELSE 0 END), 0) as efectivo,
                    COALESCE(SUM(CASE WHEN metodo_pago IN ('TARJETA_DEBITO', 'TARJETA_CREDITO') THEN total ELSE 0 END), 0) as tarjeta,
                    COALESCE(SUM(CASE WHEN metodo_pago = 'TRANSFERENCIA' THEN total ELSE 0 END), 0) as transferencia,
                    COALESCE(SUM(CASE WHEN metodo_pago NOT IN ('EFECTIVO', 'TARJETA_DEBITO', 'TARJETA_CREDITO', 'TRANSFERENCIA', 'CREDITO') THEN total ELSE 0 END), 0) as otros,
                    COALESCE(SUM(total), 0) as total_ventas
                FROM ventas
                WHERE fecha >= ?
                AND estado = 'COMPLETADA'
            ''', (caja_abierta['fecha_apertura'],))
            
            ventas = dict(cursor.fetchone())
            resumen_cierre = self.obtener_resumen_cierre()
            ventas = {
                'efectivo': resumen_cierre['efectivo'],
                'tarjeta': resumen_cierre['tarjeta'],
                'transferencia': resumen_cierre['transferencia'],
                'otros': resumen_cierre['otros'],
                'total_ventas': resumen_cierre['total'],
            }
            
            # Calcular totales
            monto_inicial = caja_abierta['monto_inicial']
            monto_esperado = resumen_cierre['esperado']
            diferencia = monto_real - monto_esperado
            
            # Actualizar el cierre de caja
            cursor.execute('''
                UPDATE cierres_caja SET
                    fecha_cierre = CURRENT_TIMESTAMP,
                    ventas_efectivo = ?,
                    ventas_tarjeta = ?,
                    ventas_transferencia = ?,
                    ventas_otros = ?,
                    total_ventas = ?,
                    monto_esperado = ?,
                    monto_real = ?,
                    diferencia = ?,
                    observaciones = ?
                WHERE id = ?
            ''', (
                ventas['efectivo'],
                ventas['tarjeta'],
                ventas['transferencia'],
                ventas['otros'],
                ventas['total_ventas'],
                monto_esperado,
                monto_real,
                diferencia,
                observaciones,
                caja_abierta['id']
            ))

            from repositories._outbox import encolar
            encolar(conn, "cash_session", caja_abierta['id'], "update", "cierres_caja")

            conn.commit()

            # Registrar en auditoría
            self.auth.registrar_auditoria(
                self.auth.usuario_actual.id,
                "CERRAR_CAJA",
                "Caja",
                f"Caja cerrada. Esperado: ${monto_esperado:,.2f}, Real: ${monto_real:,.2f}, Diferencia: ${diferencia:,.2f}"
            )
            
            conn.close()
            
            mensaje = f"Caja cerrada. Diferencia: ${abs(diferencia):,.2f}"
            if diferencia > 0:
                mensaje += " (Sobrante)"
            elif diferencia < 0:
                mensaje += " (Faltante)"
            
            return True, mensaje
            
        except Exception as e:
            conn.rollback()
            conn.close()
            return False, f"Error al cerrar caja: {str(e)}"
    
    def obtener_resumen_dia(self) -> dict:
        """Obtiene resumen de ventas desde la apertura de caja actual"""
        if not self.auth.usuario_actual:
            return {
                'cantidad_ventas': 0,
                'efectivo': 0,
                'tarjeta': 0,
                'transferencia': 0,
                'otros': 0,
                'total': 0,
                'egresos_efectivo': 0,
                'egresos_tarjeta': 0,
                'egresos_transferencia': 0,
                'egresos_otros': 0,
                'egresos_total': 0
            }
        
        _reconciliar_pagos_proveedor()

        fecha_hoy = datetime.now().strftime('%Y-%m-%d')
        
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        # Ventas del día de TODOS los usuarios (excluye CREDITO — los abonos se suman aparte)
        cursor.execute('''
            SELECT 
                COUNT(*) as cantidad_ventas,
                COALESCE(SUM(CASE WHEN metodo_pago = 'EFECTIVO' THEN total ELSE 0 END), 0) as efectivo,
                COALESCE(SUM(CASE WHEN metodo_pago IN ('TARJETA_DEBITO', 'TARJETA_CREDITO') THEN total ELSE 0 END), 0) as tarjeta,
                COALESCE(SUM(CASE WHEN metodo_pago = 'TRANSFERENCIA' THEN total ELSE 0 END), 0) as transferencia,
                COALESCE(SUM(CASE WHEN metodo_pago NOT IN ('EFECTIVO', 'TARJETA_DEBITO', 'TARJETA_CREDITO', 'TRANSFERENCIA', 'CREDITO') THEN total ELSE 0 END), 0) as otros,
                COALESCE(SUM(CASE WHEN metodo_pago != 'CREDITO' THEN total ELSE 0 END), 0) as total
            FROM ventas
            WHERE DATE(datetime(fecha, 'localtime')) = ?
            AND estado = 'COMPLETADA'
        ''', (fecha_hoy,))
        
        ventas = dict(cursor.fetchone())
        
        # Abonos registrados hoy (todos los usuarios)
        cursor.execute('''
            SELECT 
                COALESCE(SUM(CASE WHEN UPPER(tipo_pago) = 'EFECTIVO' THEN monto_abono ELSE 0 END), 0) as efectivo_abonos,
                COALESCE(SUM(CASE WHEN UPPER(tipo_pago) IN ('TARJETA_DEBITO', 'TARJETA_CREDITO', 'TARJETA') THEN monto_abono ELSE 0 END), 0) as tarjeta_abonos,
                COALESCE(SUM(CASE WHEN UPPER(tipo_pago) = 'TRANSFERENCIA' THEN monto_abono ELSE 0 END), 0) as transferencia_abonos,
                COALESCE(SUM(CASE WHEN UPPER(tipo_pago) NOT IN ('EFECTIVO', 'TARJETA_DEBITO', 'TARJETA_CREDITO', 'TARJETA', 'TRANSFERENCIA') THEN monto_abono ELSE 0 END), 0) as otros_abonos,
                COALESCE(SUM(monto_abono), 0) as total_abonos
            FROM abonos_ventas
            WHERE DATE(fecha_abono) = ?
        ''', (fecha_hoy,))
        
        abonos = dict(cursor.fetchone())
        
        # Egresos registrados hoy (todos los usuarios)
        cursor.execute('''
            SELECT 
                COALESCE(SUM(CASE WHEN UPPER(metodo_pago) = 'EFECTIVO' THEN monto ELSE 0 END), 0) as efectivo_egresos,
                COALESCE(SUM(CASE WHEN UPPER(metodo_pago) IN ('TARJETA_DEBITO', 'TARJETA_CREDITO', 'TARJETA') THEN monto ELSE 0 END), 0) as tarjeta_egresos,
                COALESCE(SUM(CASE WHEN UPPER(metodo_pago) = 'TRANSFERENCIA' THEN monto ELSE 0 END), 0) as transferencia_egresos,
                COALESCE(SUM(CASE WHEN UPPER(metodo_pago) NOT IN ('EFECTIVO', 'TARJETA_DEBITO', 'TARJETA_CREDITO', 'TARJETA', 'TRANSFERENCIA') THEN monto ELSE 0 END), 0) as otros_egresos,
                COALESCE(SUM(monto), 0) as total_egresos
            FROM egresos_caja
            WHERE DATE(fecha_egreso) = ?
        ''', (fecha_hoy,))
        
        egresos = dict(cursor.fetchone())
        conn.close()
        
        # Combinar ventas + abonos - egresos
        resumen = {
            'cantidad_ventas': ventas['cantidad_ventas'],
            'efectivo': ventas['efectivo'] + abonos['efectivo_abonos'],
            'tarjeta': ventas['tarjeta'] + abonos['tarjeta_abonos'],
            'transferencia': ventas['transferencia'] + abonos['transferencia_abonos'],
            'otros': ventas['otros'] + abonos['otros_abonos'],
            'total': ventas['total'] + abonos['total_abonos'],
            'egresos_efectivo': egresos['efectivo_egresos'],
            'egresos_tarjeta': egresos['tarjeta_egresos'],
            'egresos_transferencia': egresos['transferencia_egresos'],
            'egresos_otros': egresos['otros_egresos'],
            'egresos_total': egresos['total_egresos']
        }
        
        return resumen
    
    def obtener_resumen_cierre(self) -> dict:
        """Obtiene resumen para el cierre de caja"""
        caja_abierta = self.obtener_caja_abierta()
        
        if not caja_abierta:
            return {
                'monto_inicial': 0,
                'efectivo': 0,
                'tarjeta': 0,
                'transferencia': 0,
                'otros': 0,
                'total': 0,
                'esperado': 0,
                'egresos_efectivo': 0,
                'egresos_tarjeta': 0,
                'egresos_transferencia': 0,
                'egresos_otros': 0,
                'egresos_total': 0
            }
        
        _reconciliar_pagos_proveedor()

        conn = self.db.conectar()
        cursor = conn.cursor()
        
        # Ventas desde apertura de caja (excluyendo crédito)
        cursor.execute('''
            SELECT 
                COALESCE(SUM(CASE WHEN metodo_pago = 'EFECTIVO' THEN total ELSE 0 END), 0) as efectivo,
                COALESCE(SUM(CASE WHEN metodo_pago IN ('TARJETA_DEBITO', 'TARJETA_CREDITO') THEN total ELSE 0 END), 0) as tarjeta,
                COALESCE(SUM(CASE WHEN metodo_pago = 'TRANSFERENCIA' THEN total ELSE 0 END), 0) as transferencia,
                COALESCE(SUM(CASE WHEN metodo_pago NOT IN ('EFECTIVO', 'TARJETA_DEBITO', 'TARJETA_CREDITO', 'TRANSFERENCIA', 'CREDITO') THEN total ELSE 0 END), 0) as otros,
                COALESCE(SUM(CASE WHEN metodo_pago != 'CREDITO' THEN total ELSE 0 END), 0) as total
            FROM ventas
            WHERE DATE(datetime(fecha, 'localtime')) = DATE('now', 'localtime')
            AND estado = 'COMPLETADA'
        ''')
        
        ventas = dict(cursor.fetchone())
        
        # Abonos desde apertura de caja (todos los usuarios)
        cursor.execute('''
            SELECT 
                COALESCE(SUM(CASE WHEN UPPER(tipo_pago) = 'EFECTIVO' THEN monto_abono ELSE 0 END), 0) as efectivo_abonos,
                COALESCE(SUM(CASE WHEN UPPER(tipo_pago) IN ('TARJETA_DEBITO', 'TARJETA_CREDITO', 'TARJETA') THEN monto_abono ELSE 0 END), 0) as tarjeta_abonos,
                COALESCE(SUM(CASE WHEN UPPER(tipo_pago) = 'TRANSFERENCIA' THEN monto_abono ELSE 0 END), 0) as transferencia_abonos,
                COALESCE(SUM(CASE WHEN UPPER(tipo_pago) NOT IN ('EFECTIVO', 'TARJETA_DEBITO', 'TARJETA_CREDITO', 'TARJETA', 'TRANSFERENCIA') THEN monto_abono ELSE 0 END), 0) as otros_abonos,
                COALESCE(SUM(monto_abono), 0) as total_abonos
            FROM abonos_ventas
            WHERE DATE(fecha_abono) = DATE('now', 'localtime')
        ''')
        
        abonos = dict(cursor.fetchone())
        
        # Egresos desde apertura de caja (todos los usuarios)
        cursor.execute('''
            SELECT 
                COALESCE(SUM(CASE WHEN UPPER(metodo_pago) = 'EFECTIVO' THEN monto ELSE 0 END), 0) as efectivo_egresos,
                COALESCE(SUM(CASE WHEN UPPER(metodo_pago) IN ('TARJETA_DEBITO', 'TARJETA_CREDITO', 'TARJETA') THEN monto ELSE 0 END), 0) as tarjeta_egresos,
                COALESCE(SUM(CASE WHEN UPPER(metodo_pago) = 'TRANSFERENCIA' THEN monto ELSE 0 END), 0) as transferencia_egresos,
                COALESCE(SUM(CASE WHEN UPPER(metodo_pago) NOT IN ('EFECTIVO', 'TARJETA_DEBITO', 'TARJETA_CREDITO', 'TARJETA', 'TRANSFERENCIA') THEN monto ELSE 0 END), 0) as otros_egresos,
                COALESCE(SUM(monto), 0) as total_egresos
            FROM egresos_caja
            WHERE DATE(fecha_egreso) = DATE('now', 'localtime')
        ''')
        
        egresos = dict(cursor.fetchone())
        conn.close()
        
        monto_inicial = caja_abierta['monto_inicial']
        
        # Combinar ventas + abonos - egresos
        efectivo_total = ventas['efectivo'] + abonos['efectivo_abonos']
        tarjeta_total = ventas['tarjeta'] + abonos['tarjeta_abonos']
        transferencia_total = ventas['transferencia'] + abonos['transferencia_abonos']
        otros_total = ventas['otros'] + abonos['otros_abonos']
        total_ingresado = ventas['total'] + abonos['total_abonos']
        
        esperado = monto_inicial + efectivo_total - egresos['efectivo_egresos']
        
        return {
            'monto_inicial': monto_inicial,
            'efectivo': efectivo_total,
            'tarjeta': tarjeta_total,
            'transferencia': transferencia_total,
            'otros': otros_total,
            'total': total_ingresado,
            'esperado': esperado,
            'egresos_efectivo': egresos['efectivo_egresos'],
            'egresos_tarjeta': egresos['tarjeta_egresos'],
            'egresos_transferencia': egresos['transferencia_egresos'],
            'egresos_otros': egresos['otros_egresos'],
            'egresos_total': egresos['total_egresos']
        }
    
    def obtener_historial_cierres(self, limite: int = 30) -> list:
        """Obtiene historial de cierres de caja"""
        if not self.auth.usuario_actual:
            return []
        
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                c.*,
                u.nombre_completo as usuario_nombre
            FROM cierres_caja c
            JOIN usuarios u ON c.usuario_id = u.id
            WHERE c.fecha_cierre IS NOT NULL
            ORDER BY c.fecha_cierre DESC
            LIMIT ?
        ''', (limite,))
        
        cierres = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return cierres

    def obtener_ultimo_cierre_usuario(self) -> Optional[dict]:
        """Obtiene el último cierre de caja del usuario actual"""
        if not self.auth.usuario_actual:
            return None

        conn = self.db.conectar()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT *
            FROM cierres_caja
            WHERE usuario_id = ?
            AND fecha_cierre IS NOT NULL
            ORDER BY fecha_cierre DESC
            LIMIT 1
        ''', (self.auth.usuario_actual.id,))

        cierre = cursor.fetchone()
        conn.close()

        if cierre:
            return dict(cierre)
        return None
