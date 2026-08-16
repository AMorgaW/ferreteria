# -*- coding: utf-8 -*-
"""
Repositorio para gestión de abonos en ventas
Maneja la persistencia de cobros parciales a facturas de clientes
"""
from typing import List, Dict, Optional
from models import AbonoVenta
from services.operational_balance import connect_local


class AbonosVentasRepository:
    """Repositorio para gestión de abonos a facturas de venta"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
    
    def crear_abono(self, abono: AbonoVenta) -> int:
        """
        Registra un abono (cobro) a una factura de venta.
        Identidad durable: local_id UUID. Retry same identity → mismo efecto.
        """
        from local_first_db import ensure_local_id
        from repositories._outbox import encolar
        from services.caja_service import attach_customer_payment_cash_effect
        from services.financial_writer_fence import assert_can_finalize_payment
        from services.operational_balance import (
            PaymentError,
            assert_payment_allowed,
            begin_immediate,
            compute_receivable,
            connect_local,
            durable_payment_id,
            find_payment_by_local_id,
            project_receivable,
        )

        conn = connect_local(self.db_path)
        cursor = conn.cursor()
        try:
            assert_can_finalize_payment()
            begin_immediate(conn)
            local_id = durable_payment_id(getattr(abono, "local_id", None))
            existing = find_payment_by_local_id(conn, "abonos_ventas", local_id)
            if existing:
                cash_ok, cash_message, _cash_id = attach_customer_payment_cash_effect(
                    conn,
                    abono_id=existing["id"],
                    tipo_pago=existing.get("tipo_pago") or abono.tipo_pago,
                    monto=existing.get("monto_abono") or abono.monto_abono,
                    usuario=abono.usuario,
                    source_identity=local_id,
                )
                if not cash_ok:
                    raise RuntimeError(cash_message)
                project_receivable(conn, abono.id_venta)
                conn.commit()
                return existing["id"]

            snap = compute_receivable(conn, abono.id_venta)
            if not snap:
                raise PaymentError("NOT_FOUND", "Venta no encontrada")
            monto = assert_payment_allowed(snap, abono.monto_abono)
            monto_txt = format(monto, "f")

            try:
                cursor.execute(
                    '''
                    INSERT INTO abonos_ventas
                    (id_venta, monto_abono, fecha_abono, tipo_pago,
                     numero_comprobante, usuario, observaciones, local_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        abono.id_venta,
                        monto_txt,
                        abono.fecha_abono,
                        abono.tipo_pago,
                        abono.numero_comprobante,
                        abono.usuario,
                        abono.observaciones,
                        local_id,
                    ),
                )
            except Exception as exc:
                if "UNIQUE" in str(exc).upper() or "local_id" in str(exc).lower():
                    row = find_payment_by_local_id(conn, "abonos_ventas", local_id)
                    if row:
                        conn.commit()
                        return row["id"]
                raise

            abono_id = cursor.lastrowid
            ensure_local_id(conn, "abonos_ventas", abono_id)
            project_receivable(conn, abono.id_venta)
            encolar(conn, "sale_payment", abono_id, "create", "abonos_ventas")
            encolar(conn, "sale", abono.id_venta, "update", "ventas")

            cash_ok, cash_message, _cash_id = attach_customer_payment_cash_effect(
                conn,
                abono_id=abono_id,
                tipo_pago=abono.tipo_pago,
                monto=monto_txt,
                usuario=abono.usuario,
                source_identity=local_id,
            )
            if not cash_ok:
                raise RuntimeError(cash_message)

            conn.commit()
            return abono_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def obtener_abonos_factura(self, id_venta: int) -> List[Dict]:
        """Obtiene todos los abonos de una factura"""
        conn = connect_local(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                id, id_venta, monto_abono, fecha_abono, tipo_pago,
                numero_comprobante, usuario, observaciones, created_at
            FROM abonos_ventas 
            WHERE id_venta = ?
            ORDER BY fecha_abono DESC
        ''', (id_venta,))
        
        abonos = cursor.fetchall()
        conn.close()
        
        return [
            {
                'id': a[0],
                'id_venta': a[1],
                'monto_abono': a[2],
                'fecha_abono': a[3],
                'tipo_pago': a[4],
                'numero_comprobante': a[5],
                'usuario': a[6],
                'observaciones': a[7],
                'created_at': a[8]
            }
            for a in abonos
        ]
    
    def obtener_total_abonado(self, id_venta: int):
        """Obtiene el total abonado a una factura (Decimal canónico)."""
        from services.operational_balance import compute_receivable, connect_local

        conn = connect_local(self.db_path)
        try:
            snap = compute_receivable(conn, id_venta)
            return snap.payments if snap else 0
        finally:
            conn.close()
    
    def eliminar_abono(self, id_abono: int) -> bool:
        """Elimina un abono (solo si se necesita corregir)"""
        conn = connect_local(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Obtener id_venta antes de eliminar
            cursor.execute('SELECT id_venta FROM abonos_ventas WHERE id = ?', (id_abono,))
            resultado = cursor.fetchone()
            
            if not resultado:
                return False
            
            id_venta = resultado[0]

            # Local-first: encolar borrado del abono ANTES de eliminarlo.
            from repositories._outbox import encolar, encolar_borrado
            encolar_borrado(conn, "sale_payment", id_abono, "abonos_ventas")

            # Eliminar abono
            cursor.execute('DELETE FROM abonos_ventas WHERE id = ?', (id_abono,))

            # Actualizar estado de la venta
            self._actualizar_estado_venta(cursor, id_venta)
            encolar(conn, "sale", id_venta, "update", "ventas")

            conn.commit()
            return True
            
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def _actualizar_estado_venta(self, cursor, id_venta: int):
        """Proyección idempotente desde el saldo canónico (reversos + abonos)."""
        from services.operational_balance import project_receivable

        project_receivable(cursor.connection, id_venta)
    
    def obtener_abonos_por_usuario(self, usuario: str, 
                                  fecha_inicio: str = None, 
                                  fecha_fin: str = None) -> List[Dict]:
        """
        Obtiene los abonos registrados por un usuario en un rango de fechas
        Útil para auditoría
        """
        conn = connect_local(self.db_path)
        cursor = conn.cursor()
        
        query = '''
            SELECT 
                a.id, a.id_venta, a.monto_abono, a.fecha_abono, a.tipo_pago,
                a.numero_comprobante, a.usuario, a.observaciones, a.created_at,
                v.numero_factura, v.total
            FROM abonos_ventas a
            INNER JOIN ventas v ON a.id_venta = v.id
            WHERE a.usuario = ?
        '''
        
        params = [usuario]
        
        if fecha_inicio:
            query += ' AND a.fecha_abono >= ?'
            params.append(fecha_inicio)
        
        if fecha_fin:
            query += ' AND a.fecha_abono <= ?'
            params.append(fecha_fin)
        
        query += ' ORDER BY a.fecha_abono DESC'
        
        cursor.execute(query, params)
        abonos = cursor.fetchall()
        conn.close()
        
        return [
            {
                'id': a[0],
                'id_venta': a[1],
                'monto_abono': a[2],
                'fecha_abono': a[3],
                'tipo_pago': a[4],
                'numero_comprobante': a[5],
                'usuario': a[6],
                'observaciones': a[7],
                'created_at': a[8],
                'numero_factura': a[9],
                'total_factura': a[10]
            }
            for a in abonos
        ]
