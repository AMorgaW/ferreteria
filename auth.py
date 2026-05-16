# -*- coding: utf-8 -*-
"""
Sistema de autenticación y gestión de usuarios
"""
import hashlib
import sqlite3
from typing import Optional, Tuple
from datetime import datetime
from models import Usuario, RolUsuario

class AuthManager:
    """Gestor de autenticación y usuarios"""
    
    def __init__(self, db_manager):
        self.db = db_manager
        self.usuario_actual: Optional[Usuario] = None
    
    def hash_password(self, password: str) -> str:
        """Genera hash SHA-256 de la contraseña"""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def login(self, username: str, password: str) -> Tuple[bool, str, Optional[Usuario]]:
        """
        Intenta iniciar sesión con las credenciales proporcionadas
        Returns: (éxito, mensaje, usuario)
        """
        conn = self.db.conectar()
        cursor = conn.cursor()
        
        password_hash = self.hash_password(password)
        
        cursor.execute('''
            SELECT * FROM usuarios 
            WHERE username = ? AND password_hash = ? AND activo = 1
        ''', (username, password_hash))
        
        row = cursor.fetchone()
        
        if row:
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
            # Credenciales inválidas
            self.registrar_auditoria(None, "LOGIN_FALLIDO", "Autenticación",
                                   f"Intento fallido de inicio de sesión: {username}")
            conn.close()
            return False, "Usuario o contraseña incorrectos", None
    
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