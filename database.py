# -*- coding: utf-8 -*-
"""
Capa de base de datos – PostgreSQL (Supabase)
"""
import pg_compat
import hashlib
from typing import Optional, List, Tuple
from datetime import datetime
import os
from local_first_db import ensure_local_first_schema
import schema_bootstrap

def obtener_fecha_actual():
    """Obtiene la fecha/hora actual en formato local (no UTC)"""
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')




class DatabaseManager:
    """Gestor principal de la base de datos (PostgreSQL / Supabase)"""
    _schema_initialized = False

    def __init__(self, db_name="ferreteria.db"):
        # db_name se mantiene por compatibilidad con código existente pero no se usa
        self.db_name = db_name
        if not DatabaseManager._schema_initialized:
            self.crear_estructura_completa()
            self.crear_usuario_admin_default()
            self.crear_usuario_empleado_default()
            # Usar la MISMA base que pg_compat (LOCAL_DB_PATH), no una ruta
            # relativa: si difieren, las migraciones/columnas de sync se
            # aplicarían sobre el archivo equivocado.
            from local_first_db import DEFAULT_DB_PATH as _LF_DB
            ensure_local_first_schema(_LF_DB)
            DatabaseManager._schema_initialized = True

    def conectar(self):
        """Abre conexión a PostgreSQL (Supabase)."""
        return pg_compat.connect()
    
    def ejecutar_script(self, script: str):
        """Ejecuta un script SQL (sentencias separadas por ';')"""
        conn = self.conectar()
        cursor = conn.cursor()
        for stmt in script.split(";"):
            stmt = stmt.strip()
            if stmt:
                try:
                    cursor.execute(stmt)
                except Exception:
                    pass
        conn.commit()
        conn.close()
    
    # [OK] AGREGADO: Método ejecutar_query que faltaba
    def ejecutar_query(self, query: str, params: tuple = None):
        """
        Ejecuta una query SQL y retorna los resultados
        Returns: Lista de diccionarios con los resultados
        """
        conn = self.conectar()
        cursor = conn.cursor()
        
        try:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            
            # Si es un SELECT, retornar resultados
            if query.strip().upper().startswith('SELECT'):
                rows = cursor.fetchall()
                resultado = [dict(row) for row in rows]
            else:
                # Si es INSERT, UPDATE, DELETE
                conn.commit()
                resultado = []
            
            conn.close()
            return resultado
            
        except Exception as e:
            conn.close()
            raise e
    
    def crear_estructura_completa(self):
        """Crea toda la estructura de la base de datos"""
        conn = self.conectar()
        cursor = conn.cursor()
        pk = schema_bootstrap.pk_sql(conn)
        sqlite = schema_bootstrap.is_sqlite_connection(conn)

        def _create(sql: str):
            # SQLite: SERIAL no es alias de ROWID. Sustitución por motor, no
            # un reemplazo ciego del SQL remoto ni del DDL PostgreSQL.
            if sqlite:
                sql = sql.replace("SERIAL PRIMARY KEY", pk)
            cursor.execute(sql)

        # Tabla de usuarios
        _create('''
            CREATE TABLE IF NOT EXISTS usuarios (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                nombre_completo TEXT NOT NULL,
                rol TEXT NOT NULL,
                email TEXT,
                telefono TEXT,
                activo INTEGER DEFAULT 1,
                fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ultimo_acceso TIMESTAMP
            )
        ''')
        
        # Tabla de proveedores (DEBE CREARSE ANTES DE PRODUCTOS)
        _create('''
            CREATE TABLE IF NOT EXISTS proveedores (
                id SERIAL PRIMARY KEY,
                nit TEXT UNIQUE,
                nombre TEXT NOT NULL,
                telefono TEXT,
                correo TEXT,
                direccion TEXT,
                ciudad TEXT,
                contacto_nombre TEXT,
                contacto_telefono TEXT,
                productos_provee TEXT,
                calificacion REAL DEFAULT 0,
                dias_credito INTEGER DEFAULT 0,
                activo INTEGER DEFAULT 1,
                fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Tabla de productos (MEJORADA CON PROVEEDOR_ID)
        _create('''
            CREATE TABLE IF NOT EXISTS productos (
                id SERIAL PRIMARY KEY,
                codigo_barras TEXT UNIQUE,
                nombre TEXT NOT NULL,
                categoria TEXT,
                marca TEXT,
                presentacion TEXT,
                proveedor_id INTEGER,
                precio_compra REAL DEFAULT 0,
                precio_venta REAL NOT NULL,
                stock INTEGER DEFAULT 0,
                stock_minimo INTEGER DEFAULT 10,
                ubicacion TEXT,
                descripcion TEXT,
                unidad_medida TEXT DEFAULT 'UNIDAD',
                viene_en_caja INTEGER DEFAULT 0,
                unidades_por_caja INTEGER DEFAULT 1,
                unidades_por_media_caja INTEGER DEFAULT 1,
                vende_por_empaque INTEGER DEFAULT 0,
                usar_unidades_categoria INTEGER DEFAULT 1,
                unidades_venta_custom TEXT,
                unidad_base_producto TEXT,
                permite_decimales INTEGER DEFAULT 0,
                iva REAL DEFAULT 0,
                activo INTEGER DEFAULT 1,
                fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (proveedor_id) REFERENCES proveedores(id)
            )
        ''')
        
        # Tabla de clientes
        _create('''
            CREATE TABLE IF NOT EXISTS clientes (
                id SERIAL PRIMARY KEY,
                tipo_documento TEXT DEFAULT 'CC',
                numero_documento TEXT UNIQUE NOT NULL,
                nombre TEXT NOT NULL,
                telefono TEXT,
                email TEXT,
                direccion TEXT,
                ciudad TEXT,
                limite_credito REAL DEFAULT 0,
                saldo_pendiente REAL DEFAULT 0,
                clasificacion TEXT DEFAULT 'C',
                descuento_default REAL DEFAULT 0,
                puntos_fidelidad INTEGER DEFAULT 0,
                activo INTEGER DEFAULT 1,
                fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Tabla de ventas (mejorada)
        _create('''
            CREATE TABLE IF NOT EXISTS ventas (
                id SERIAL PRIMARY KEY,
                numero_factura TEXT UNIQUE,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                cliente_id INTEGER,
                usuario_id INTEGER,
                subtotal REAL NOT NULL,
                descuento REAL DEFAULT 0,
                iva REAL DEFAULT 0,
                total REAL NOT NULL,
                metodo_pago TEXT DEFAULT 'EFECTIVO',
                estado TEXT DEFAULT 'COMPLETADA',
                estado_pago TEXT DEFAULT 'PENDIENTE',
                monto_pagado REAL DEFAULT 0,
                observaciones TEXT,
                FOREIGN KEY (cliente_id) REFERENCES clientes(id),
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
            )
        ''')
        
        # Tabla de detalle de ventas
        _create('''
            CREATE TABLE IF NOT EXISTS detalle_ventas (
                id SERIAL PRIMARY KEY,
                venta_id INTEGER NOT NULL,
                producto_id INTEGER NOT NULL,
                cantidad INTEGER NOT NULL,
                precio_unitario REAL NOT NULL,
                descuento REAL DEFAULT 0,
                subtotal REAL NOT NULL,
                iva REAL DEFAULT 0,
                tipo_unidad TEXT DEFAULT 'Unidad',
                FOREIGN KEY (venta_id) REFERENCES ventas(id),
                FOREIGN KEY (producto_id) REFERENCES productos(id)
            )
        ''')
        
        # [OK] CORREGIDO: Tabla de movimientos con numero_factura
        _create('''
            CREATE TABLE IF NOT EXISTS movimientos (
                id SERIAL PRIMARY KEY,
                tipo TEXT NOT NULL,
                producto_id INTEGER NOT NULL,
                proveedor_id INTEGER,
                usuario_id INTEGER,
                cantidad INTEGER NOT NULL,
                precio_unitario REAL DEFAULT 0,
                costo_total REAL DEFAULT 0,
                motivo TEXT,
                num_factura TEXT,
                en_cajas INTEGER DEFAULT 0,
                num_cajas INTEGER DEFAULT 0,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                observaciones TEXT,
                FOREIGN KEY (producto_id) REFERENCES productos(id),
                FOREIGN KEY (proveedor_id) REFERENCES proveedores(id),
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
            )
        ''')
        
        # [OK] AGREGADO: Tabla de movimientos_inventario (para compatibilidad)
        _create('''
            CREATE TABLE IF NOT EXISTS movimientos_inventario (
                id SERIAL PRIMARY KEY,
                tipo_movimiento TEXT NOT NULL,
                producto_id INTEGER NOT NULL,
                proveedor_id INTEGER,
                cliente_id INTEGER,
                cantidad INTEGER NOT NULL,
                precio_unitario REAL DEFAULT 0,
                numero_factura TEXT,
                observaciones TEXT,
                usuario_id INTEGER,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (producto_id) REFERENCES productos(id),
                FOREIGN KEY (proveedor_id) REFERENCES proveedores(id),
                FOREIGN KEY (cliente_id) REFERENCES clientes(id),
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
            )
        ''')

        # [OK] NUEVO: Tabla de compras (encabezado)
        _create('''
            CREATE TABLE IF NOT EXISTS compras (
                id SERIAL PRIMARY KEY,
                proveedor_id INTEGER NOT NULL,
                numero_factura TEXT,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                tipo_compra TEXT DEFAULT 'CONTADO',
                subtotal REAL DEFAULT 0,
                total REAL NOT NULL,
                observaciones TEXT,
                usuario_id INTEGER,
                estado TEXT DEFAULT 'COMPLETADA',
                estado_pago TEXT DEFAULT 'PENDIENTE',
                monto_pagado REAL DEFAULT 0,
                saldo_pendiente REAL DEFAULT 0,
                fecha_vencimiento DATE,
                FOREIGN KEY (proveedor_id) REFERENCES proveedores(id),
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
            )
        ''')

        # [OK] NUEVO: Tabla de detalle de compras
        _create('''
            CREATE TABLE IF NOT EXISTS detalle_compras (
                id SERIAL PRIMARY KEY,
                compra_id INTEGER NOT NULL,
                producto_id INTEGER NOT NULL,
                cantidad INTEGER NOT NULL,
                precio_unitario REAL NOT NULL,
                subtotal REAL NOT NULL,
                FOREIGN KEY (compra_id) REFERENCES compras(id),
                FOREIGN KEY (producto_id) REFERENCES productos(id)
            )
        ''')
        
        # Tabla de cierre de caja
        _create('''
            CREATE TABLE IF NOT EXISTS cierres_caja (
                id SERIAL PRIMARY KEY,
                usuario_id INTEGER NOT NULL,
                fecha_apertura TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                fecha_cierre TIMESTAMP,
                monto_inicial REAL DEFAULT 0,
                ventas_efectivo REAL DEFAULT 0,
                ventas_tarjeta REAL DEFAULT 0,
                ventas_transferencia REAL DEFAULT 0,
                ventas_otros REAL DEFAULT 0,
                total_ventas REAL DEFAULT 0,
                gastos REAL DEFAULT 0,
                monto_esperado REAL DEFAULT 0,
                monto_real REAL DEFAULT 0,
                diferencia REAL DEFAULT 0,
                observaciones TEXT,
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
            )
        ''')
        
        # Tabla de cuentas por cobrar
        _create('''
            CREATE TABLE IF NOT EXISTS cuentas_por_cobrar (
                id SERIAL PRIMARY KEY,
                venta_id INTEGER NOT NULL,
                cliente_id INTEGER NOT NULL,
                monto_total REAL NOT NULL,
                monto_pagado REAL DEFAULT 0,
                saldo_pendiente REAL NOT NULL,
                fecha_vencimiento TIMESTAMP,
                estado TEXT DEFAULT 'PENDIENTE',
                observaciones TEXT,
                FOREIGN KEY (venta_id) REFERENCES ventas(id),
                FOREIGN KEY (cliente_id) REFERENCES clientes(id)
            )
        ''')
        
        # Tabla de pagos de cuentas por cobrar
        _create('''
            CREATE TABLE IF NOT EXISTS pagos_cuentas (
                id SERIAL PRIMARY KEY,
                cuenta_id INTEGER NOT NULL,
                monto REAL NOT NULL,
                metodo_pago TEXT NOT NULL,
                fecha_pago TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                observaciones TEXT,
                FOREIGN KEY (cuenta_id) REFERENCES cuentas_por_cobrar(id)
            )
        ''')
        
        # Tabla de alertas
        _create('''
            CREATE TABLE IF NOT EXISTS alertas (
                id SERIAL PRIMARY KEY,
                tipo TEXT NOT NULL,
                titulo TEXT NOT NULL,
                mensaje TEXT NOT NULL,
                prioridad TEXT DEFAULT 'MEDIA',
                leida INTEGER DEFAULT 0,
                fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                relacionado_id INTEGER,
                relacionado_tipo TEXT
            )
        ''')
        
        # [OK] NUEVO: Tabla de abonos a compras
        _create('''
            CREATE TABLE IF NOT EXISTS abonos_compras (
                id SERIAL PRIMARY KEY,
                id_compra INTEGER NOT NULL,
                monto_abono REAL NOT NULL,
                fecha_abono DATE NOT NULL,
                tipo_pago VARCHAR NOT NULL,
                numero_comprobante VARCHAR,
                usuario VARCHAR,
                observaciones TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (id_compra) REFERENCES compras(id)
            )
        ''')
        
        # [OK] NUEVO: Tabla de resumen de deudas (desnormalizado para queries rápidas)
        _create('''
            CREATE TABLE IF NOT EXISTS resumen_deudas (
                id SERIAL PRIMARY KEY,
                id_proveedor INTEGER NOT NULL,
                total_deuda REAL DEFAULT 0,
                ultima_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (id_proveedor) REFERENCES proveedores(id)
            )
        ''')
        
        # [OK] NUEVO: Tabla de abonos a ventas (cuentas por cobrar)
        _create('''
            CREATE TABLE IF NOT EXISTS abonos_ventas (
                id SERIAL PRIMARY KEY,
                id_venta INTEGER NOT NULL,
                monto_abono REAL NOT NULL,
                fecha_abono DATE NOT NULL,
                tipo_pago VARCHAR NOT NULL,
                numero_comprobante VARCHAR,
                usuario VARCHAR,
                observaciones TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (id_venta) REFERENCES ventas(id)
            )
        ''')
        
        # [OK] NUEVO: Tabla de egresos de caja (gastos operativos)
        _create('''
            CREATE TABLE IF NOT EXISTS egresos_caja (
                id SERIAL PRIMARY KEY,
                monto REAL NOT NULL,
                categoria VARCHAR NOT NULL,
                descripcion TEXT NOT NULL,
                metodo_pago VARCHAR NOT NULL,
                fecha_egreso TIMESTAMP NOT NULL,
                usuario VARCHAR NOT NULL,
                id_caja INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (id_caja) REFERENCES cierres_caja(id)
            )
        ''')
        
        # [OK] NUEVO: Tabla de fórmulas de mezcla de pinturas
        _create('''
            CREATE TABLE IF NOT EXISTS formulas_mezcla (
                id SERIAL PRIMARY KEY,
                nombre TEXT NOT NULL,
                descripcion TEXT,
                precio_venta REAL DEFAULT 0,
                volumen_total REAL DEFAULT 0,
                unidad_medida TEXT DEFAULT 'L',
                cliente_referencia TEXT,
                usuario_id INTEGER,
                activo INTEGER DEFAULT 1,
                fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
            )
        ''')

        # [OK] NUEVO: Detalle de componentes de una fórmula de mezcla
        _create('''
            CREATE TABLE IF NOT EXISTS formula_detalle (
                id SERIAL PRIMARY KEY,
                formula_id INTEGER NOT NULL,
                producto_id INTEGER NOT NULL,
                cantidad REAL NOT NULL,
                unidad_medida TEXT DEFAULT 'L',
                FOREIGN KEY (formula_id) REFERENCES formulas_mezcla(id),
                FOREIGN KEY (producto_id) REFERENCES productos(id)
            )
        ''')

        # Tabla de auditoría
        _create('''
            CREATE TABLE IF NOT EXISTS auditoria (
                id SERIAL PRIMARY KEY,
                usuario_id INTEGER,
                accion TEXT NOT NULL,
                modulo TEXT NOT NULL,
                descripcion TEXT,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ip_address TEXT,
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
            )
        ''')
        
        # Tabla de configuración
        _create('''
            CREATE TABLE IF NOT EXISTS configuracion (
                clave TEXT PRIMARY KEY,
                valor TEXT NOT NULL,
                descripcion TEXT,
                fecha_modificacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Crear tabla de configuración de categorías (nueva)
        _create('''
            CREATE TABLE IF NOT EXISTS categorias_config (
                id SERIAL PRIMARY KEY,
                nombre TEXT UNIQUE NOT NULL,
                unidad_base TEXT NOT NULL,
                unidades_venta_json TEXT NOT NULL,
                activo INTEGER DEFAULT 1,
                fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        try:
            schema_bootstrap.apply_engine_schema_fixes(conn)
            self.insertar_categorias_predefinidas(cursor)
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            conn.close()
            raise
        conn.close()
        print("[OK] Base de datos inicializada correctamente")
    
    def agregar_columnas_productos(self, cursor=None):
        """Idempotente: añade columnas de negocio faltantes. No traga errores."""
        conn = self.conectar()
        try:
            schema_bootstrap.apply_required_columns(conn)
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            conn.close()
    
    def insertar_categorias_predefinidas(self, cursor):
        """Inserta las categorías predefinidas con sus unidades de venta"""
        import json
        
        categorias = [
            {
                'nombre': 'Elementos de Fijación',
                'unidad_base': 'unidad',
                'unidades_venta': [
                    {'nombre': 'Cajas', 'factor': None, 'requiere_config': True},
                    {'nombre': 'Unidades', 'factor': 1.0}
                ]
            },
            {
                'nombre': 'Herrajes',
                'unidad_base': 'unidad',
                'unidades_venta': [
                    {'nombre': 'Cajas', 'factor': None, 'requiere_config': True},
                    {'nombre': 'Unidades', 'factor': 1.0}
                ]
            },
            {
                'nombre': 'Pinturas',
                'unidad_base': 'galón',
                'unidades_venta': [
                    {'nombre': 'Galón', 'factor': 1.0},
                    {'nombre': '3/4 Galón', 'factor': 0.75},
                    {'nombre': '1/2 Galón', 'factor': 0.5},
                    {'nombre': '1/4 Galón', 'factor': 0.25}
                ]
            },
            {
                'nombre': 'Varillas/Tubos/Alambres',
                'unidad_base': 'metro',
                'unidades_venta': [
                    {'nombre': 'Metros', 'factor': 1.0},
                    {'nombre': 'Centímetros', 'factor': 0.01},
                    {'nombre': 'Unidades', 'factor': None, 'requiere_config': True}
                ]
            },
            {
                'nombre': 'Líquidos',
                'unidad_base': 'litro',
                'unidades_venta': [
                    {'nombre': 'Galones', 'factor': 3.785},
                    {'nombre': 'Litros', 'factor': 1.0},
                    {'nombre': 'Mililitros', 'factor': 0.001}
                ]
            },
            {
                'nombre': 'Productos en Polvo',
                'unidad_base': 'kilogramo',
                'unidades_venta': [
                    {'nombre': 'Bultos', 'factor': 50.0},
                    {'nombre': 'Kilogramos', 'factor': 1.0}
                ]
            },
            {
                'nombre': 'Herramientas Manuales',
                'unidad_base': 'unidad',
                'unidades_venta': [
                    {'nombre': 'Unidades', 'factor': 1.0}
                ]
            },
            {
                'nombre': 'Electrodomésticos y Equipos',
                'unidad_base': 'unidad',
                'unidades_venta': [
                    {'nombre': 'Unidades', 'factor': 1.0}
                ]
            },
            {
                'nombre': 'Materiales de Construcción',
                'unidad_base': 'unidad',
                'unidades_venta': [
                    {'nombre': 'Unidades', 'factor': 1.0},
                    {'nombre': 'Metros', 'factor': None, 'requiere_config': True},
                    {'nombre': 'Metro²', 'factor': None, 'requiere_config': True},
                    {'nombre': 'Kilogramos', 'factor': None, 'requiere_config': True}
                ]
            },
            {
                'nombre': 'Electricidad',
                'unidad_base': 'unidad',
                'unidades_venta': [
                    {'nombre': 'Metros', 'factor': None, 'requiere_config': True},
                    {'nombre': 'Unidades', 'factor': 1.0}
                ]
            },
            {
                'nombre': 'Plomería',
                'unidad_base': 'unidad',
                'unidades_venta': [
                    {'nombre': 'Metros', 'factor': None, 'requiere_config': True},
                    {'nombre': 'Unidades', 'factor': 1.0}
                ]
            }
        ]
        
        for cat in categorias:
            try:
                cursor.execute('''
                    INSERT OR IGNORE INTO categorias_config (nombre, unidad_base, unidades_venta_json)
                    VALUES (?, ?, ?)
                ''', (cat['nombre'], cat['unidad_base'], json.dumps(cat['unidades_venta'], ensure_ascii=False)))
            except Exception as e:
                print(f"[WARN] Error al insertar categoría {cat['nombre']}: {e}")
    
    def crear_usuario_admin_default(self):
        """Crea el administrador inicial únicamente con una clave local configurada."""
        conn = self.conectar()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM usuarios WHERE username = 'admin'")
        if cursor.fetchone()[0] == 0:
            bootstrap_password = os.environ.get("FERREPRO_BOOTSTRAP_ADMIN_PASSWORD", "").strip()
            if not bootstrap_password:
                print("[INFO] No se creó el administrador inicial: configure "
                      "FERREPRO_BOOTSTRAP_ADMIN_PASSWORD en el .env local.")
                conn.close()
                return
            password_hash = hashlib.sha256(bootstrap_password.encode()).hexdigest()
            cursor.execute('''
                INSERT INTO usuarios (username, password_hash, nombre_completo, rol)
                VALUES (?, ?, ?, ?)
            ''', ('admin', password_hash, 'Administrador', 'ADMIN'))
            conn.commit()
            print("[OK] Usuario administrador inicial creado.")
        
        conn.close()
    
    def crear_usuario_empleado_default(self):
        """Crea el vendedor inicial únicamente con una clave local configurada."""
        conn = self.conectar()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM usuarios WHERE username = 'empleado'")
        if cursor.fetchone()[0] == 0:
            bootstrap_password = os.environ.get("FERREPRO_BOOTSTRAP_SELLER_PASSWORD", "").strip()
            if not bootstrap_password:
                print("[INFO] No se creó el vendedor inicial: configure "
                      "FERREPRO_BOOTSTRAP_SELLER_PASSWORD en el .env local.")
                conn.close()
                return
            password_hash = hashlib.sha256(bootstrap_password.encode()).hexdigest()
            cursor.execute('''
                INSERT INTO usuarios (username, password_hash, nombre_completo, rol)
                VALUES (?, ?, ?, ?)
            ''', ('empleado', password_hash, 'Empleado', 'VENDEDOR'))
            conn.commit()
            print("[OK] Usuario vendedor inicial creado.")

        conn.close()

    def realizar_respaldo(self, ruta_destino: str = None) -> str:
        """Respaldo no disponible en modo PostgreSQL/Supabase."""
        return "Respaldo gestionado por Supabase (ver panel de Supabase)"
    
    # [OK] AGREGADO: Método para verificar y agregar columnas faltantes
    def verificar_y_actualizar_esquema(self):
        """
        Verifica el esquema y agrega columnas faltantes si es necesario.
        """
        conn = self.conectar()
        try:
            schema_bootstrap.apply_engine_schema_fixes(conn)
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            conn.close()
    
    def obtener_estadisticas(self) -> dict:
        """Obtiene estadísticas generales del sistema"""
        conn = self.conectar()
        cursor = conn.cursor()
        
        stats = {}
        
        # Total de productos
        cursor.execute("SELECT COUNT(*) FROM productos WHERE activo = 1")
        stats['total_productos'] = cursor.fetchone()[0]
        
        # Productos con stock bajo
        cursor.execute("SELECT COUNT(*) FROM productos WHERE stock <= stock_minimo AND activo = 1")
        stats['productos_stock_bajo'] = cursor.fetchone()[0]
        
        # Total de clientes
        cursor.execute("SELECT COUNT(*) FROM clientes WHERE activo = 1")
        stats['total_clientes'] = cursor.fetchone()[0]
        
        # Ventas del día
        cursor.execute("""
            SELECT COUNT(*), COALESCE(SUM(total), 0) 
            FROM ventas 
            WHERE DATE(fecha) = DATE('now')
        """)
        ventas_hoy = cursor.fetchone()
        stats['ventas_hoy'] = ventas_hoy[0]
        stats['monto_ventas_hoy'] = ventas_hoy[1]
        
        # Cuentas por cobrar pendientes
        cursor.execute("SELECT COALESCE(SUM(saldo_pendiente), 0) FROM cuentas_por_cobrar WHERE estado = 'PENDIENTE'")
        stats['cuentas_por_cobrar'] = cursor.fetchone()[0]
        
        # Alertas sin leer
        cursor.execute("SELECT COUNT(*) FROM alertas WHERE leida = 0")
        stats['alertas_pendientes'] = cursor.fetchone()[0]
        
        conn.close()
        return stats
    
    # [OK] AGREGADO: Método helper para limpiar base de datos (útil para testing)
    def limpiar_base_datos(self):
        """
        ADVERTENCIA: Elimina TODOS los datos de todas las tablas
        Solo usar para testing o reset completo
        """
        conn = self.conectar()
        cursor = conn.cursor()

        tablas = [
            'detalle_ventas', 'ventas', 'movimientos_inventario', 'movimientos',
            'pagos_cuentas', 'cuentas_por_cobrar', 'productos', 'clientes',
            'proveedores', 'cierres_caja', 'alertas', 'auditoria', 'configuracion'
        ]

        for tabla in tablas:
            try:
                cursor.execute(f"DELETE FROM {tabla}")
            except Exception:
                pass

        conn.commit()
        conn.close()
        print("[AVISO] Base de datos limpiada (usuarios mantenidos)")

    def ejecutar_transaccion(self, operaciones: List[Tuple[str, Tuple]]) -> Tuple[bool, str]:
        """
        Ejecuta múltiples operaciones SQL en una transacción
        Args:
            operaciones: Lista de tuplas (query, params)
        Returns:
            (exito, mensaje)
        """
        conn = self.conectar()
        cursor = conn.cursor()

        try:
            for query, params in operaciones:
                cursor.execute(query, params)

            conn.commit()
            conn.close()
            return True, "Transacción completada exitosamente"
        except Exception as e:
            conn.rollback()
            conn.close()
            return False, f"Error en transacción: {str(e)}"

    def obtener_configuracion(self, clave: str, valor_default: str = None) -> Optional[str]:
        """Obtiene un valor de configuración"""
        conn = self.conectar()
        cursor = conn.cursor()

        cursor.execute("SELECT valor FROM configuracion WHERE clave = ?", (clave,))
        row = cursor.fetchone()
        conn.close()

        return row['valor'] if row else valor_default

    def guardar_configuracion(self, clave: str, valor: str, descripcion: str = None) -> Tuple[bool, str]:
        """Guarda o actualiza un valor de configuración"""
        conn = self.conectar()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO configuracion (clave, valor, descripcion)
                VALUES (?, ?, ?)
                ON CONFLICT(clave) DO UPDATE SET
                    valor = excluded.valor,
                    descripcion = excluded.descripcion,
                    fecha_modificacion = CURRENT_TIMESTAMP
            """, (clave, valor, descripcion))

            conn.commit()
            conn.close()
            return True, "Configuración guardada"
        except Exception as e:
            conn.close()
            return False, f"Error: {str(e)}"

    def verificar_integridad(self) -> Tuple[bool, List[str]]:
        """
        Verifica la integridad de la base de datos
        Returns: (exito, lista_de_problemas)
        """
        problemas = []
        conn = self.conectar()
        cursor = conn.cursor()

        try:
            # Verificar productos sin stock negativo
            cursor.execute("SELECT COUNT(*) FROM productos WHERE stock < 0")
            if cursor.fetchone()[0] > 0:
                problemas.append("Existen productos con stock negativo")

            # Verificar ventas sin detalles
            cursor.execute("""
                SELECT COUNT(*) FROM ventas v
                WHERE NOT EXISTS (
                    SELECT 1 FROM detalle_ventas dv WHERE dv.venta_id = v.id
                )
            """)
            if cursor.fetchone()[0] > 0:
                problemas.append("Existen ventas sin detalles")

            # Verificar clientes con saldo negativo
            cursor.execute("SELECT COUNT(*) FROM clientes WHERE saldo_pendiente < 0")
            if cursor.fetchone()[0] > 0:
                problemas.append("Existen clientes con saldo negativo")

            conn.close()

            if problemas:
                return False, problemas
            else:
                return True, ["Base de datos íntegra"]

        except Exception as e:
            conn.close()
            return False, [f"Error verificando integridad: {str(e)}"]
