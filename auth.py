# -*- coding: utf-8 -*-
"""
Sistema de autenticación y gestión de usuarios
"""
import hashlib
import logging
import sqlite3
from typing import Optional, Tuple
from datetime import datetime
from models import Usuario, RolUsuario
from security import (hash_password as _secure_hash, verify_password, needs_rehash,
                      verificar_bloqueo, registrar_fallo, registrar_exito, MAX_INTENTOS)

logger = logging.getLogger(__name__)

class AuthManager:
    """Gestor de autenticación y usuarios"""
    
    def __init__(self, db_manager):
        self.db = db_manager
        self.usuario_actual: Optional[Usuario] = None
    
    def hash_password(self, password: str) -> str:
        """Genera un hash seguro (PBKDF2 con sal) de la contraseña."""
        return _secure_hash(password)

    def login(self, username: str, password: str) -> Tuple[bool, str, Optional[Usuario]]:
        """
        Intenta iniciar sesión con las credenciales proporcionadas
        Returns: (éxito, mensaje, usuario)
        """
        conn = self.db.conectar()
        cursor = conn.cursor()

        # Rate-limiting: rechazar si la cuenta está bloqueada por intentos fallidos
        bloqueado, segundos = verificar_bloqueo(cursor, username)
        if bloqueado:
            conn.close()
            mins = segundos // 60
            return False, (f"Cuenta bloqueada por demasiados intentos fallidos. "
                           f"Intente de nuevo en {mins} min {segundos % 60} s."), None

        # Se busca por usuario y la contraseña se verifica con sal (PBKDF2),
        # con retrocompatibilidad para hashes antiguos SHA-256.
        cursor.execute('''
            SELECT * FROM usuarios
            WHERE username = ? AND activo = 1
        ''', (username,))

        row = cursor.fetchone()

        if row and verify_password(row['password_hash'], password):
            # Migrar hashes legacy a PBKDF2 de forma transparente
            if needs_rehash(row['password_hash']):
                try:
                    cursor.execute('UPDATE usuarios SET password_hash = ? WHERE id = ?',
                                   (_secure_hash(password), row['id']))
                    conn.commit()
                except Exception:
                    logger.warning(
                        "Fallo al actualizar hash de credenciales (rehash PBKDF2) "
                        "para usuario_id=%s; el inicio de sesión continúa",
                        row["id"],
                    )
                    try:
                        conn.rollback()
                    except Exception:
                        pass

            # Usuario encontrado y activo
            usuario = Usuario(
                id=row['id'],
                username=row['username'],
                password_hash=row['password_hash'],
                nombre_completo=row['nombre_completo'],
                rol=row['rol'],
                email=row['email'],
                telefono=row['telefono'],
                activo=bool(row['activo']),
                fecha_creacion=row['fecha_creacion'],
                ultimo_acceso=row['ultimo_acceso']
            )
            
            # Login correcto: limpiar contador de intentos fallidos
            registrar_exito(cursor, username)

            # Actualizar último acceso
            cursor.execute('''
                UPDATE usuarios
                SET ultimo_acceso = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (usuario.id,))
            conn.commit()
            
            # Registrar en auditoría
            self.registrar_auditoria(usuario.id, "LOGIN", "Autenticación", 
                                   f"Usuario {username} inició sesión")
            
            self.usuario_actual = usuario
            conn.close()
            return True, "Inicio de sesión exitoso", usuario
        else:
            # Credenciales inválidas: contar el fallo (puede bloquear la cuenta)
            intentos, quedo_bloqueado = registrar_fallo(cursor, username)
            conn.commit()
            self.registrar_auditoria(None, "LOGIN_FALLIDO", "Autenticación",
                                   f"Intento fallido de inicio de sesión: {username} "
                                   f"(intento {intentos})")
            conn.close()
            if quedo_bloqueado:
                return False, ("Demasiados intentos fallidos. La cuenta quedó bloqueada "
                               f"temporalmente ({MAX_INTENTOS} intentos)."), None
            restantes = max(0, MAX_INTENTOS - intentos)
            return False, (f"Usuario o contraseña incorrectos. "
                           f"Le quedan {restantes} intento(s)."), None
    
    def logout(self):
        """Cierra la sesión actual"""
        if self.usuario_actual:
            self.registrar_auditoria(
                self.usuario_actual.id, 
                "LOGOUT", 
                "Autenticación",
                f"Usuario {self.usuario_actual.username} cerró sesión"
            )
            self.usuario_actual = None
    
    def crear_usuario(self, username: str, password: str, nombre_completo: str,
                     rol: str, email: str = None, telefono: str = None) -> Tuple[bool, str]:
        """
        Crea un nuevo usuario
        Returns: (éxito, mensaje)
        """
        # Verificar permisos
        if not self.tiene_permiso('crear_usuario'):
            return False, "No tiene permisos para crear usuarios"
        
        # Validar rol
        try:
            RolUsuario[rol]
        except KeyError:
            return False, f"Rol inválido: {rol}"
        
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        try:
            password_hash = self.hash_password(password)
            
            cursor.execute('''
                INSERT INTO usuarios (username, password_hash, nombre_completo, rol, email, telefono)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (username, password_hash, nombre_completo, rol, email, telefono))
            _nuevo_uid = cursor.lastrowid

            # Local-first: encolar el usuario para sincronizar a Supabase.
            from repositories._outbox import encolar
            encolar(conn, "user", _nuevo_uid, "create", "usuarios")

            conn.commit()

            self.registrar_auditoria(
                self.usuario_actual.id if self.usuario_actual else None,
                "CREAR_USUARIO",
                "Usuarios",
                f"Usuario {username} creado con rol {rol}"
            )
            
            conn.close()
            return True, "Usuario creado exitosamente"
            
        except sqlite3.IntegrityError:
            conn.close()
            return False, "El nombre de usuario ya existe"
        except Exception as e:
            conn.close()
            return False, f"Error al crear usuario: {str(e)}"
    
    def cambiar_password(self, usuario_id: int, password_nueva: str) -> Tuple[bool, str]:
        """Cambia la contraseña de un usuario"""
        # Solo admin o el mismo usuario pueden cambiar contraseña
        if self.usuario_actual.rol != 'ADMIN' and self.usuario_actual.id != usuario_id:
            return False, "No tiene permisos para cambiar esta contraseña"
        
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        password_hash = self.hash_password(password_nueva)
        
        cursor.execute('''
            UPDATE usuarios
            SET password_hash = ?
            WHERE id = ?
        ''', (password_hash, usuario_id))

        from repositories._outbox import encolar
        encolar(conn, "user", usuario_id, "update", "usuarios")
        conn.commit()

        self.registrar_auditoria(
            self.usuario_actual.id,
            "CAMBIAR_PASSWORD",
            "Usuarios",
            f"Contraseña cambiada para usuario ID {usuario_id}"
        )
        
        conn.close()
        return True, "Contraseña actualizada exitosamente"
    
    def listar_usuarios(self) -> list:
        """Lista todos los usuarios del sistema"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM usuarios ORDER BY nombre_completo')
        rows = cursor.fetchall()
        
        usuarios = []
        for row in rows:
            usuario = Usuario(
                id=row['id'],
                username=row['username'],
                password_hash='***',  # No exponer hash
                nombre_completo=row['nombre_completo'],
                rol=row['rol'],
                email=row['email'],
                telefono=row['telefono'],
                activo=bool(row['activo']),
                fecha_creacion=row['fecha_creacion'],
                ultimo_acceso=row['ultimo_acceso']
            )
            usuarios.append(usuario)
        
        conn.close()
        return usuarios
    
    def activar_desactivar_usuario(self, usuario_id: int, activo: bool) -> Tuple[bool, str]:
        """Activa o desactiva un usuario"""
        if not self.tiene_permiso('gestionar_usuarios'):
            return False, "No tiene permisos para esta acción"
        
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE usuarios
            SET activo = ?
            WHERE id = ?
        ''', (1 if activo else 0, usuario_id))

        from repositories._outbox import encolar
        encolar(conn, "user", usuario_id, "update", "usuarios")
        conn.commit()

        accion = "activado" if activo else "desactivado"
        self.registrar_auditoria(
            self.usuario_actual.id,
            "CAMBIAR_ESTADO_USUARIO",
            "Usuarios",
            f"Usuario ID {usuario_id} {accion}"
        )
        
        conn.close()
        return True, f"Usuario {accion} exitosamente"
    
    def tiene_permiso(self, accion: str) -> bool:
        """Verifica si el usuario actual tiene permiso para una acción"""
        if not self.usuario_actual:
            return False
        
        # Definir permisos por rol
        permisos = {
            'ADMIN': [
                'crear_usuario', 'gestionar_usuarios', 'ver_reportes',
                'gestionar_productos', 'realizar_ventas', 'gestionar_proveedores',
                'gestionar_movimientos', 'ver_precios_compra', 'modificar_precios',
                'eliminar_registros', 'ver_auditoria', 'configurar_sistema', 'ver_dashboard'
            ],
            'GERENTE': [
                'ver_reportes', 'gestionar_productos', 'gestionar_proveedores',
                'gestionar_movimientos', 'ver_precios_compra', 'modificar_precios',
                'realizar_ventas', 'ver_dashboard'
            ],
            'VENDEDOR': [
                'realizar_ventas', 'ver_productos', 'gestionar_clientes',
                'gestionar_movimientos'
            ],
            'EMPLEADO': [
                'realizar_ventas', 'ver_productos', 'gestionar_clientes',
                'gestionar_movimientos'
            ],
            'BODEGUERO': [
                'gestionar_movimientos', 'ver_productos', 'gestionar_productos', 'ver_dashboard'
            ],
            'CONTADOR': [
                'ver_reportes', 'ver_precios_compra', 'ver_dashboard'
            ]
        }
        
        rol_permisos = permisos.get(self.usuario_actual.rol, [])
        return accion in rol_permisos
    
    def registrar_auditoria(self, usuario_id: Optional[int], accion: str, 
                          modulo: str, descripcion: str, ip_address: str = None):
        """Registra una acción en el log de auditoría"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO auditoria (usuario_id, accion, modulo, descripcion, ip_address)
            VALUES (?, ?, ?, ?, ?)
        ''', (usuario_id, accion, modulo, descripcion, ip_address))

        from repositories._outbox import encolar
        encolar(conn, "audit_log", cursor.lastrowid, "create", "auditoria")

        conn.commit()
        conn.close()

    def obtener_auditoria(self, limite: int = 100, usuario_id: int = None) -> list:
        """Obtiene registros de auditoría"""
        if not self.tiene_permiso('ver_auditoria'):
            return []
        
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        if usuario_id:
            cursor.execute('''
                SELECT a.*, u.username, u.nombre_completo
                FROM auditoria a
                LEFT JOIN usuarios u ON a.usuario_id = u.id
                WHERE a.usuario_id = ?
                ORDER BY a.fecha DESC
                LIMIT ?
            ''', (usuario_id, limite))
        else:
            cursor.execute('''
                SELECT a.*, u.username, u.nombre_completo
                FROM auditoria a
                LEFT JOIN usuarios u ON a.usuario_id = u.id
                ORDER BY a.fecha DESC
                LIMIT ?
            ''', (limite,))
        
        registros = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in registros]