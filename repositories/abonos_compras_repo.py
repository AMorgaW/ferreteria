# -*- coding: utf-8 -*-
"""
Repositorio para gestión de abonos en compras
Maneja la persistencia de pagos parciales a facturas de proveedores
"""
import pg_compat
from typing import List, Dict, Optional
from datetime import datetime
from models import Abono


def _row_value(row, key, index, default=None):
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        try:
            return row[index]
        except (TypeError, IndexError):
            return default


def _obtener_caja_abierta_id(cursor):
    cursor.execute('''
        SELECT id
        FROM cierres_caja
        WHERE fecha_cierre IS NULL
        ORDER BY fecha_apertura DESC
        LIMIT 1
    ''')
    caja = cursor.fetchone()
    return _row_value(caja, 'id', 0) if caja else None


def _actualizar_estado_compra_en_cursor(cursor, id_compra: int):
    cursor.execute('''
        SELECT COALESCE(SUM(monto_abono), 0) FROM abonos_compras
        WHERE id_compra = ?
    ''', (id_compra,))
    total_abonado = cursor.fetchone()[0]

    cursor.execute('''
        SELECT total FROM compras WHERE id = ?
    ''', (id_compra,))
    resultado = cursor.fetchone()

    if not resultado:
        return

    monto_total = resultado[0]

    if total_abonado >= monto_total:
        estado = 'PAGADO'
    elif total_abonado > 0:
        estado = 'PARCIAL'
    else:
        estado = 'PENDIENTE'

    saldo = max(0, monto_total - total_abonado)

    cursor.execute('''
        UPDATE compras
        SET estado_pago = ?, monto_pagado = ?, saldo_pendiente = ?
        WHERE id = ?
    ''', (estado, total_abonado, saldo, id_compra))


def _normalizar_fecha_egreso(fecha):
    if not fecha:
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    fecha_txt = str(fecha)
    if len(fecha_txt) <= 10:
        hoy = datetime.now().strftime('%Y-%m-%d')
        hora = datetime.now().strftime('%H:%M:%S') if fecha_txt == hoy else '00:00:00'
        return f"{fecha_txt} {hora}"
    return fecha_txt[:19]


def _crear_egreso_pago_proveedor(cursor, conn, abono_id: int, id_compra: int,
                                 monto: float, tipo_pago: str, usuario: str,
                                 numero_comprobante: Optional[str],
                                 observaciones: Optional[str],
                                 fecha_egreso=None) -> int:
    cursor.execute('''
        SELECT c.numero_factura, p.nombre as proveedor
        FROM compras c
        LEFT JOIN proveedores p ON c.proveedor_id = p.id
        WHERE c.id = ?
    ''', (id_compra,))
    compra = cursor.fetchone()

    numero_factura = _row_value(compra, 'numero_factura', 0, '-') if compra else '-'
    proveedor = _row_value(compra, 'proveedor', 1, 'Proveedor') if compra else 'Proveedor'
    descripcion = (
        f"Pago a proveedor {proveedor} - Compra #{id_compra} "
        f"- Factura {numero_factura} - Abono #{abono_id}"
    )
    if numero_comprobante:
        descripcion += f" - Comprobante {numero_comprobante}"
    if observaciones:
        descripcion += f" - {observaciones}"

    cursor.execute('''
        INSERT INTO egresos_caja
        (monto, categoria, descripcion, metodo_pago, fecha_egreso, usuario, id_caja)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        monto,
        'Pago a proveedor',
        descripcion,
        tipo_pago,
        _normalizar_fecha_egreso(fecha_egreso),
        usuario or 'Sistema',
        _obtener_caja_abierta_id(cursor)
    ))
    egreso_id = cursor.lastrowid

    from repositories._outbox import encolar
    encolar(conn, "cash_expense", egreso_id, "create", "egresos_caja")
    return egreso_id


def registrar_abono_compra_en_transaccion(conn, cursor, abono: Abono) -> int:
    cursor.execute('''
        INSERT INTO abonos_compras
        (id_compra, monto_abono, fecha_abono, tipo_pago,
         numero_comprobante, usuario, observaciones)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        abono.id_compra,
        abono.monto_abono,
        abono.fecha_abono,
        abono.tipo_pago,
        abono.numero_comprobante,
        abono.usuario,
        abono.observaciones
    ))

    abono_id = cursor.lastrowid

    _crear_egreso_pago_proveedor(
        cursor,
        conn,
        abono_id,
        abono.id_compra,
        abono.monto_abono,
        abono.tipo_pago,
        abono.usuario,
        abono.numero_comprobante,
        abono.observaciones,
        abono.fecha_abono
    )

    from services.caja_service import attach_supplier_payment_cash_effect

    cash_ok, cash_message, _cash_id = attach_supplier_payment_cash_effect(
        conn,
        abono_id=abono_id,
        tipo_pago=abono.tipo_pago,
        monto=abono.monto_abono,
        usuario=abono.usuario,
        descripcion=f"Pago proveedor compra #{abono.id_compra} abono #{abono_id}",
    )
    if not cash_ok:
        raise RuntimeError(cash_message)

    _actualizar_estado_compra_en_cursor(cursor, abono.id_compra)

    from repositories._outbox import encolar
    encolar(conn, "purchase_payment", abono_id, "create", "abonos_compras")
    encolar(conn, "purchase", abono.id_compra, "update", "compras")

    return abono_id


def reconciliar_pagos_proveedor_huerfanos() -> dict:
    conn = pg_compat.connect()
    cursor = conn.cursor()
    creados = {'abonos': 0, 'egresos': 0}

    try:
        cursor.execute('''
            SELECT id, id_compra, monto_abono, fecha_abono, tipo_pago,
                   numero_comprobante, usuario, observaciones
            FROM abonos_compras
            ORDER BY id
        ''')
        abonos = cursor.fetchall()

        for row in abonos:
            abono_id = _row_value(row, 'id', 0)
            cursor.execute(
                "SELECT COUNT(*) FROM egresos_caja WHERE descripcion LIKE ?",
                (f"%Abono #{abono_id}%",)
            )
            if cursor.fetchone()[0] > 0:
                continue

            _crear_egreso_pago_proveedor(
                cursor,
                conn,
                abono_id,
                _row_value(row, 'id_compra', 1),
                _row_value(row, 'monto_abono', 2),
                _row_value(row, 'tipo_pago', 4) or 'Efectivo',
                _row_value(row, 'usuario', 6) or 'Sistema',
                _row_value(row, 'numero_comprobante', 5),
                _row_value(row, 'observaciones', 7),
                _row_value(row, 'fecha_abono', 3)
            )
            creados['egresos'] += 1

        cursor.execute('''
            SELECT c.id, c.monto_pagado, c.fecha, c.usuario_id,
                   COALESCE(SUM(a.monto_abono), 0) AS total_abonos
            FROM compras c
            LEFT JOIN abonos_compras a ON a.id_compra = c.id
            WHERE COALESCE(c.monto_pagado, 0) > 0
            GROUP BY c.id, c.monto_pagado, c.fecha, c.usuario_id
            HAVING COALESCE(c.monto_pagado, 0) > COALESCE(SUM(a.monto_abono), 0)
        ''')
        compras = cursor.fetchall()

        for row in compras:
            id_compra = _row_value(row, 'id', 0)
            monto_pagado = float(_row_value(row, 'monto_pagado', 1) or 0)
            total_abonos = float(_row_value(row, 'total_abonos', 4) or 0)
            diferencia = monto_pagado - total_abonos
            if diferencia <= 0:
                continue

            usuario = 'Sistema'
            usuario_id = _row_value(row, 'usuario_id', 3)
            if usuario_id:
                cursor.execute("SELECT username FROM usuarios WHERE id = ?", (usuario_id,))
                usuario_row = cursor.fetchone()
                if usuario_row:
                    usuario = _row_value(usuario_row, 'username', 0, 'Sistema')

            abono = Abono(
                id_compra=id_compra,
                monto_abono=diferencia,
                fecha_abono=_normalizar_fecha_egreso(_row_value(row, 'fecha', 2)),
                tipo_pago='Efectivo',
                numero_comprobante=None,
                usuario=usuario,
                observaciones='Pago histórico registrado en compra'
            )
            registrar_abono_compra_en_transaccion(conn, cursor, abono)
            creados['abonos'] += 1
            creados['egresos'] += 1

        conn.commit()
        return creados
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class AbonosaComprasRepository:
    """Repositorio para gestión de abonos a facturas de compra"""
    
    def __init__(self, db_path: str):
        pass  # db_path ignorado; se usa PostgreSQL
    
    def crear_abono(self, abono: Abono) -> int:
        """
        Registra un abono a una factura
        Returns: ID del abono creado
        """
        conn = pg_compat.connect()
        cursor = conn.cursor()
        
        try:
            abono_id = registrar_abono_compra_en_transaccion(conn, cursor, abono)
            conn.commit()
            return abono_id

        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def obtener_abonos_factura(self, id_compra: int) -> List[Dict]:
        """Obtiene todos los abonos de una factura"""
        conn = pg_compat.connect()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                id, id_compra, monto_abono, fecha_abono, tipo_pago,
                numero_comprobante, usuario, observaciones, created_at
            FROM abonos_compras 
            WHERE id_compra = ?
            ORDER BY fecha_abono DESC
        ''', (id_compra,))
        
        abonos = cursor.fetchall()
        conn.close()
        
        return [
            {
                'id': a[0],
                'id_compra': a[1],
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
    
    def obtener_total_abonado(self, id_compra: int) -> float:
        """Obtiene el total abonado a una factura"""
        conn = pg_compat.connect()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT COALESCE(SUM(monto_abono), 0) FROM abonos_compras 
            WHERE id_compra = ?
        ''', (id_compra,))
        
        total = cursor.fetchone()[0]
        conn.close()
        
        return total
    
    def eliminar_abono(self, id_abono: int) -> bool:
        """Elimina un abono (solo si se necesita corregir)"""
        conn = pg_compat.connect()
        cursor = conn.cursor()
        
        try:
            # Obtener id_compra antes de eliminar
            cursor.execute('SELECT id_compra FROM abonos_compras WHERE id = ?', (id_abono,))
            resultado = cursor.fetchone()
            
            if not resultado:
                return False
            
            id_compra = resultado[0]
            
            # Eliminar abono
            cursor.execute('DELETE FROM abonos_compras WHERE id = ?', (id_abono,))
            
            _actualizar_estado_compra_en_cursor(cursor, id_compra)
            
            conn.commit()
            return True
            
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def obtener_abonos_por_usuario(self, usuario: str, 
                                  fecha_inicio: str = None, 
                                  fecha_fin: str = None) -> List[Dict]:
        """Obtiene abonos registrados por un usuario en un rango de fechas"""
        conn = pg_compat.connect()
        cursor = conn.cursor()
        
        query = '''
            SELECT 
                a.id, a.id_compra, a.monto_abono, a.fecha_abono, a.tipo_pago,
                a.numero_comprobante, a.usuario, a.observaciones,
                c.numero_factura, p.nombre as proveedor
            FROM abonos_compras a
            JOIN compras c ON a.id_compra = c.id
            JOIN proveedores p ON c.proveedor_id = p.id
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
                'id_compra': a[1],
                'monto_abono': a[2],
                'fecha_abono': a[3],
                'tipo_pago': a[4],
                'numero_comprobante': a[5],
                'usuario': a[6],
                'observaciones': a[7],
                'numero_factura': a[8],
                'proveedor': a[9]
            }
            for a in abonos
        ]
    
    def listar_abonos_por_periodo(self, dias: int = 30) -> List[Dict]:
        """
        Obtiene todos los abonos de los últimos N días
        
        Args:
            dias: Número de días hacia atrás
            
        Returns:
            Lista de abonos con información de compra y proveedor
        """
        conn = pg_compat.connect()
        # pg_compat usa DictCursor automaticamente
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT 
                    a.id,
                    a.id_compra,
                    a.monto_abono,
                    a.fecha_abono,
                    a.tipo_pago,
                    a.numero_comprobante,
                    a.usuario as usuario_nombre,
                    a.observaciones,
                    c.numero_factura,
                    c.total as total_factura,
                    c.saldo_pendiente,
                    c.estado_pago,
                    p.nombre as proveedor
                FROM abonos_compras a
                JOIN compras c ON a.id_compra = c.id
                LEFT JOIN proveedores p ON c.proveedor_id = p.id
                WHERE DATE(a.fecha_abono) >= DATE('now', '-' || ? || ' days')
                ORDER BY a.fecha_abono DESC
            ''', (dias,))
            
            abonos = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return abonos
            
        except Exception as e:
            conn.close()
            print(f"Error listando abonos: {e}")
            return []
    
    def listar_compras_con_pagos_periodo(self, dias: int = 30) -> List[Dict]:
        """
        Obtiene todas las compras del período con información de sus pagos
        Incluye compras sin abonos (pendientes)
        
        Args:
            dias: Número de días hacia atrás
            
        Returns:
            Lista de compras con sus abonos más recientes
        """
        conn = pg_compat.connect()
        # pg_compat usa DictCursor automaticamente
        cursor = conn.cursor()
        
        try:
            # Obtener todas las compras del período
            cursor.execute('''
                SELECT 
                    c.id as id_compra,
                    c.fecha as fecha_compra,
                    c.numero_factura,
                    c.total as total_factura,
                    c.monto_pagado,
                    c.saldo_pendiente,
                    c.estado_pago,
                    c.tipo_compra,
                    p.nombre as proveedor,
                    u.nombre_completo as usuario_compra
                FROM compras c
                LEFT JOIN proveedores p ON c.proveedor_id = p.id
                LEFT JOIN usuarios u ON c.usuario_id = u.id
                WHERE DATE(c.fecha) >= DATE('now', '-' || ? || ' days')
                ORDER BY c.fecha DESC
            ''', (dias,))
            
            compras = []
            
            for compra in cursor.fetchall():
                compra_dict = dict(compra)
                
                # Obtener el abono más reciente de esta compra (si existe)
                cursor.execute('''
                    SELECT 
                        id, fecha_abono, monto_abono, tipo_pago, 
                        numero_comprobante, usuario
                    FROM abonos_compras
                    WHERE id_compra = ?
                    ORDER BY fecha_abono DESC
                    LIMIT 1
                ''', (compra_dict['id_compra'],))
                
                ultimo_abono = cursor.fetchone()
                
                if ultimo_abono:
                    # Si tiene abonos, agregar info del último abono
                    compra_dict['ultimo_abono_id'] = ultimo_abono['id']
                    compra_dict['fecha_ultimo_abono'] = ultimo_abono['fecha_abono']
                    compra_dict['monto_ultimo_abono'] = ultimo_abono['monto_abono']
                    compra_dict['tipo_pago_ultimo'] = ultimo_abono['tipo_pago']
                    compra_dict['comprobante_ultimo'] = ultimo_abono['numero_comprobante']
                    compra_dict['usuario_ultimo_abono'] = ultimo_abono['usuario']
                else:
                    # Si no tiene abonos, valores nulos
                    compra_dict['ultimo_abono_id'] = None
                    compra_dict['fecha_ultimo_abono'] = None
                    compra_dict['monto_ultimo_abono'] = 0
                    compra_dict['tipo_pago_ultimo'] = '-'
                    compra_dict['comprobante_ultimo'] = '-'
                    compra_dict['usuario_ultimo_abono'] = compra_dict['usuario_compra']
                
                compras.append(compra_dict)
            
            conn.close()
            return compras
            
        except Exception as e:
            conn.close()
            print(f"Error listando compras con pagos: {e}")
            return []
