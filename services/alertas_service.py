# -*- coding: utf-8 -*-
"""
Servicio de Alertas del Sistema
Gestiona notificaciones y alertas automáticas
"""
from datetime import datetime, timedelta
from typing import List, Dict
from models import Alerta


class AlertasService:
    """Servicio para gestionar alertas del sistema"""
    
    def __init__(self, db_manager, productos_repo, clientes_repo):
        self.db = db_manager
        self.productos_repo = productos_repo
        self.clientes_repo = clientes_repo
    
    def crear_alerta(self, tipo: str, titulo: str, mensaje: str,
                    prioridad: str = 'MEDIA', relacionado_id: int = None,
                    relacionado_tipo: str = None) -> bool:
        """Crea una nueva alerta"""
        
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO alertas 
                (tipo, titulo, mensaje, prioridad, relacionado_id, relacionado_tipo)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (tipo, titulo, mensaje, prioridad, relacionado_id, relacionado_tipo))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            conn.close()
            print(f"Error creando alerta: {e}")
            return False
    
    def obtener_alertas(self, solo_no_leidas: bool = False, 
                       tipo: str = None, limite: int = 100) -> List[Alerta]:
        """Obtiene alertas del sistema"""
        
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        query = "SELECT * FROM alertas WHERE 1=1"
        params = []
        
        if solo_no_leidas:
            query += " AND leida = 0"
        
        if tipo:
            query += " AND tipo = ?"
            params.append(tipo)
        
        query += " ORDER BY fecha_creacion DESC LIMIT ?"
        params.append(limite)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        alertas = []
        for row in rows:
            alerta = Alerta(
                id=row['id'],
                tipo=row['tipo'],
                titulo=row['titulo'],
                mensaje=row['mensaje'],
                prioridad=row['prioridad'],
                leida=bool(row['leida']),
                fecha_creacion=row['fecha_creacion'],
                relacionado_id=row['relacionado_id'],
                relacionado_tipo=row['relacionado_tipo']
            )
            alertas.append(alerta)
        
        conn.close()
        return alertas

    def contar_no_leidas(self) -> int:
        conn = self.db.conectar()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM alertas WHERE leida = 0")
        count = cursor.fetchone()['count']
        conn.close()
        return count
    
    def marcar_como_leida(self, alerta_id: int) -> bool:
        """Marca una alerta como leída"""
        
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE alertas 
                SET leida = 1
                WHERE id = ?
            ''', (alerta_id,))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            conn.close()
            print(f"Error marcando alerta: {e}")
            return False
    
    def marcar_todas_leidas(self) -> bool:
        """Marca todas las alertas como leídas"""
        
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        try:
            cursor.execute("UPDATE alertas SET leida = 1")
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            conn.close()
            print(f"Error marcando alertas: {e}")
            return False
    
    def eliminar_alerta(self, alerta_id: int) -> bool:
        """Elimina una alerta"""
        
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        try:
            cursor.execute("DELETE FROM alertas WHERE id = ?", (alerta_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            conn.close()
            print(f"Error eliminando alerta: {e}")
            return False
    
    def obtener_productos_stock_critico(self) -> List[Dict]:
        """Lista de stock crítico. Misma fuente que dashboard y reporte inventario."""
        from services.reportes_service import ReportesService

        return ReportesService(self.db).productos_stock_critico()
    
    def verificar_cuentas_vencidas(self) -> int:
        """Verifica cuentas por cobrar vencidas"""
        
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        # Buscar cuentas vencidas
        cursor.execute('''
            SELECT cpc.*, c.nombre as cliente_nombre, v.numero_factura
            FROM cuentas_por_cobrar cpc
            JOIN clientes c ON cpc.cliente_id = c.id
            JOIN ventas v ON cpc.venta_id = v.id
            WHERE cpc.estado = 'PENDIENTE'
            AND DATE(cpc.fecha_vencimiento) < DATE('now')
        ''')
        
        cuentas_vencidas = cursor.fetchall()
        alertas_creadas = 0
        
        for cuenta in cuentas_vencidas:
            # Verificar si ya existe alerta NO LEÍDA
            cursor.execute('''
                SELECT COUNT(*) as count FROM alertas
                WHERE tipo = 'CUENTA_VENCIDA'
                AND relacionado_id = ?
                AND relacionado_tipo = 'CUENTA'
                AND leida = 0
            ''', (cuenta['id'],))
            
            existe = cursor.fetchone()['count'] > 0
            
            if not existe:
                dias_vencido = (datetime.now() - datetime.strptime(
                    cuenta['fecha_vencimiento'], '%Y-%m-%d %H:%M:%S')).days
                
                titulo = f"Cuenta Vencida - {cuenta['cliente_nombre']}"
                mensaje = f"Factura {cuenta['numero_factura']}: ${cuenta['saldo_pendiente']:,.0f} - {dias_vencido} días vencida"
                
                if self.crear_alerta('CUENTA_VENCIDA', titulo, mensaje, 'ALTA',
                                   cuenta['id'], 'CUENTA'):
                    alertas_creadas += 1
        
        conn.close()
        return alertas_creadas
    
    def verificar_clientes_limite_credito(self) -> int:
        """Verifica clientes cerca del límite de crédito"""
        
        clientes = self.clientes_repo.listar_clientes(solo_activos=False)
        alertas_creadas = 0
        
        for cliente in clientes:
            if not cliente.activo or cliente.limite_credito == 0:
                continue
            
            # Si ha usado más del 90% del límite
            porcentaje_usado = (cliente.saldo_pendiente / cliente.limite_credito) * 100
            
            if porcentaje_usado >= 90:
                conn = self.db.conectar()
                cursor = conn.cursor()
                
                cursor.execute('''
                    SELECT COUNT(*) as count FROM alertas
                    WHERE tipo = 'LIMITE_CREDITO'
                    AND relacionado_id = ?
                    AND relacionado_tipo = 'CLIENTE'
                    AND leida = 0
                ''', (cliente.id,))
                
                existe = cursor.fetchone()['count'] > 0
                conn.close()
                
                if not existe:
                    prioridad = 'CRITICA' if porcentaje_usado >= 100 else 'ALTA'
                    
                    titulo = f"Límite de Crédito - {cliente.nombre}"
                    mensaje = f"Cliente ha usado {porcentaje_usado:.1f}% de su límite (${cliente.saldo_pendiente:,.0f} de ${cliente.limite_credito:,.0f})"
                    
                    if self.crear_alerta('LIMITE_CREDITO', titulo, mensaje, prioridad,
                                       cliente.id, 'CLIENTE'):
                        alertas_creadas += 1
        
        return alertas_creadas
    
    def verificar_stock_bajo(self) -> int:
        """Crea alertas desde la misma cantidad canónica usada por reporting."""
        alertas_creadas = 0
        for producto in self.obtener_productos_stock_critico():
            conn = self.db.conectar()
            try:
                existe = conn.execute(
                    """
                    SELECT 1 FROM alertas
                     WHERE tipo = 'STOCK_BAJO'
                       AND relacionado_id = ?
                       AND relacionado_tipo = 'PRODUCTO'
                       AND leida = 0
                     LIMIT 1
                    """,
                    (producto["id"],),
                ).fetchone()
            finally:
                conn.close()
            if existe:
                continue

            cantidad = producto["stock_actual"]
            minimo = producto["stock_minimo"]
            agotado = cantidad <= 0
            titulo = "Stock Crítico" if agotado else "Stock Bajo - Reorden Recomendado"
            mensaje = (
                f"El producto '{producto['nombre']}' tiene stock {cantidad} "
                f"(mínimo: {minimo})"
            )
            if producto.get("proveedor_nombre"):
                mensaje += f"\nProveedor recomendado: {producto['proveedor_nombre']}"
            if self.crear_alerta(
                "STOCK_BAJO",
                titulo,
                mensaje,
                "CRITICA" if agotado else "ALTA",
                producto["id"],
                "PRODUCTO",
            ):
                alertas_creadas += 1
        return alertas_creadas

    def verificar_cuentas_vencidas(self) -> int:
        """Verifica cuentas por cobrar vencidas en una sola consulta."""
        conn = self.db.conectar()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                INSERT INTO alertas (tipo, titulo, mensaje, prioridad, relacionado_id, relacionado_tipo)
                SELECT
                    'CUENTA_VENCIDA',
                    'Cuenta Vencida - ' || c.nombre,
                    'Factura ' || v.numero_factura || ': $' || cpc.saldo_pendiente ||
                        ' - ' || (CURRENT_DATE - DATE(cpc.fecha_vencimiento)) || ' dias vencida',
                    'ALTA',
                    cpc.id,
                    'CUENTA'
                FROM cuentas_por_cobrar cpc
                JOIN clientes c ON cpc.cliente_id = c.id
                JOIN ventas v ON cpc.venta_id = v.id
                WHERE cpc.estado = 'PENDIENTE'
                  AND DATE(cpc.fecha_vencimiento) < CURRENT_DATE
                  AND NOT EXISTS (
                    SELECT 1 FROM alertas a
                    WHERE a.tipo = 'CUENTA_VENCIDA'
                      AND a.relacionado_id = cpc.id
                      AND a.relacionado_tipo = 'CUENTA'
                      AND a.leida = 0
                  )
            ''')
            count = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
            conn.commit()
            conn.close()
            return count
        except Exception as e:
            conn.rollback()
            conn.close()
            print(f"Error verificando cuentas vencidas: {e}")
            return 0

    def verificar_clientes_limite_credito(self) -> int:
        """Verifica clientes cerca del limite de credito en una sola consulta."""
        conn = self.db.conectar()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                INSERT INTO alertas (tipo, titulo, mensaje, prioridad, relacionado_id, relacionado_tipo)
                SELECT
                    'LIMITE_CREDITO',
                    'Limite de Credito - ' || c.nombre,
                    'Cliente ha usado ' || ROUND(((c.saldo_pendiente / c.limite_credito) * 100)::numeric, 1) ||
                        '% de su limite ($' || c.saldo_pendiente || ' de $' || c.limite_credito || ')',
                    CASE WHEN ((c.saldo_pendiente / c.limite_credito) * 100) >= 100 THEN 'CRITICA' ELSE 'ALTA' END,
                    c.id,
                    'CLIENTE'
                FROM clientes c
                WHERE c.activo = 1
                  AND c.limite_credito > 0
                  AND ((c.saldo_pendiente / c.limite_credito) * 100) >= 90
                  AND NOT EXISTS (
                    SELECT 1 FROM alertas a
                    WHERE a.tipo = 'LIMITE_CREDITO'
                      AND a.relacionado_id = c.id
                      AND a.relacionado_tipo = 'CLIENTE'
                      AND a.leida = 0
                  )
            ''')
            count = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
            conn.commit()
            conn.close()
            return count
        except Exception as e:
            conn.rollback()
            conn.close()
            print(f"Error verificando limite de credito: {e}")
            return 0

    def ejecutar_verificaciones_diarias(self) -> Dict[str, int]:
        """Ejecuta todas las verificaciones diarias y retorna resumen"""
        
        resultados = {
            'stock_bajo': self.verificar_stock_bajo(),
            'cuentas_vencidas': self.verificar_cuentas_vencidas(),
            'limite_credito': self.verificar_clientes_limite_credito()
        }
        
        return resultados
    
    def obtener_resumen_alertas(self) -> Dict:
        """Obtiene un resumen de alertas"""
        
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        resumen = {}
        
        # Total de alertas no leídas
        cursor.execute("SELECT COUNT(*) as count FROM alertas WHERE leida = 0")
        resumen['no_leidas'] = cursor.fetchone()['count']
        
        # Por prioridad
        cursor.execute('''
            SELECT prioridad, COUNT(*) as count 
            FROM alertas 
            WHERE leida = 0
            GROUP BY prioridad
        ''')
        
        resumen['por_prioridad'] = {}
        for row in cursor.fetchall():
            resumen['por_prioridad'][row['prioridad']] = row['count']
        
        # Por tipo
        cursor.execute('''
            SELECT tipo, COUNT(*) as count 
            FROM alertas 
            WHERE leida = 0
            GROUP BY tipo
        ''')
        
        resumen['por_tipo'] = {}
        for row in cursor.fetchall():
            resumen['por_tipo'][row['tipo']] = row['count']
        
        conn.close()
        return resumen
