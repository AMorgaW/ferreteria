# -*- coding: utf-8 -*-
"""Helpers de tests Fase 1E.0."""
from __future__ import annotations

import uuid
from io import BytesIO

from models import Usuario

DEVICE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


class AuthPermitido:
    def __init__(self, usuario_id=1, rol="ADMIN"):
        self.usuario_actual = Usuario(
            id=usuario_id,
            username="tester",
            nombre_completo="Tester 1E0",
            rol=rol,
        )

    def tiene_permiso(self, _nombre):
        return True

    def registrar_auditoria(self, *args, **kwargs):
        return None


class ClientesRepoDummy:
    def invalidar_cache(self):
        return None


def insert_usuario(conn, usuario_id=1, username="tester"):
    conn.execute(
        """
        INSERT INTO usuarios (id, username, password_hash, nombre_completo, rol)
        VALUES (?, ?, 'x', 'Tester 1E0', 'ADMIN')
        """,
        (usuario_id, username),
    )
    return usuario_id


def seed_producto(conn, env, *, stock=50, producto_id=1, local_id=None, codigo=None):
    env.insert_proveedor(conn)
    lid = local_id or str(uuid.uuid4())
    env.insert_producto(
        conn,
        producto_id=producto_id,
        stock=stock,
        local_id=lid,
        codigo=codigo or f"TEST-1E0-{producto_id:03d}",
    )
    conn.commit()
    return lid


def stock_of(conn, producto_id=1):
    return conn.execute(
        "SELECT stock FROM productos WHERE id = ?", (producto_id,)
    ).fetchone()[0]


def count_mov(conn, tipo, table="movimientos"):
    col = "tipo" if table == "movimientos" else "tipo_movimiento"
    return conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE {col} = ?", (tipo,)
    ).fetchone()[0]


def _op(producto_local_id, delta, line_no=1, operation_id=None):
    return {
        "operation_id": operation_id or str(uuid.uuid4()),
        "producto_local_id": producto_local_id,
        "line_no": line_no,
        "delta": delta,
    }


class FakeHTTPHandler:
    """Soporte mínimo para invocar LocalFerreteriaAPI.create_sale sin socket."""

    def __init__(self, db_path, body: bytes):
        self.db_path = str(db_path)
        self.headers = {"Content-Length": str(len(body))}
        self.rfile = BytesIO(body)
        self.wfile = BytesIO()
        self.status = None
        self._headers_out = []

    def send_response(self, status, _message=None):
        self.status = status

    def send_header(self, key, value):
        self._headers_out.append((key, value))

    def end_headers(self):
        return None
