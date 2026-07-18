# -*- coding: utf-8 -*-
import argparse
import hashlib
import json
import os
import platform
import secrets
import socket
import sys

# Logs Unicode-safe (consolas Windows cp1252).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from local_first_db import (
    DEFAULT_DB_PATH,
    connect,
    enqueue_sync,
    ensure_local_first_schema,
    ensure_local_id,
    get_sync_status,
    now_iso,
    row_to_dict,
)
from local_sync import get_service
from security import (hash_password as secure_hash, verify_password, needs_rehash,
                      verificar_bloqueo, registrar_fallo, registrar_exito)


ADMIN_ROLES = {"ADMIN", "GERENTE"}
WORKER_ROLES = {"ADMIN", "GERENTE", "VENDEDOR", "BODEGUERO"}
SALES_ROLES = {"ADMIN", "GERENTE", "VENDEDOR"}
CUSTOMER_WRITE_ROLES = {"ADMIN", "GERENTE", "VENDEDOR"}
VERSION = "2.0-local-first"

ROLE_PERMISSIONS = {
    "ADMIN": ["products:read", "customers:read", "customers:create", "sales:create", "sync:admin"],
    "GERENTE": ["products:read", "customers:read", "customers:create", "sales:create", "sync:admin"],
    "VENDEDOR": ["products:read", "customers:read", "customers:create", "sales:create"],
    "BODEGUERO": ["products:read"],
    "CONTADOR": [],
}


def json_response(handler, status, payload):
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_json(handler):
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length == 0:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8"))


class LocalFerreteriaAPI(BaseHTTPRequestHandler):
    db_path = DEFAULT_DB_PATH
    sync_service = None

    def log_message(self, fmt, *args):
        print(f"[LOCAL_API] {self.address_string()} - {fmt % args}")

    def server_info_payload(self):
        status = get_sync_status(self.db_path)
        host, port = self.server.server_address[:2]
        return {
            "ok": True,
            "app": "ferreteria-local-first",
            "version": VERSION,
            "mode": "local-first",
            "time": now_iso(),
            "computer_name": platform.node(),
            "host": host,
            "port": port,
            "database": os.path.basename(self.db_path),
            "sync": status,
        }

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        try:
            if path == "/health":
                return json_response(self, 200, self.server_info_payload())
            if path == "/server/info":
                return json_response(self, 200, self.server_info_payload())
            if path == "/products":
                user = self.require_auth(WORKER_ROLES)
                if not user:
                    return
                return self.list_products(query)
            if path.startswith("/products/code/"):
                user = self.require_auth(WORKER_ROLES)
                if not user:
                    return
                return self.get_product_by_code(unquote(path.split("/products/code/", 1)[1]))
            if path.startswith("/products/"):
                user = self.require_auth(WORKER_ROLES)
                if not user:
                    return
                return self.get_product(path.rsplit("/", 1)[1])
            if path == "/customers":
                user = self.require_auth(WORKER_ROLES)
                if not user:
                    return
                return self.list_customers(query)
            if path.startswith("/sales/"):
                user = self.require_auth(SALES_ROLES)
                if not user:
                    return
                return self.get_sale(path.rsplit("/", 1)[1])
            if path == "/sync/status":
                user = self.require_auth(ADMIN_ROLES)
                if not user:
                    return
                return json_response(self, 200, get_sync_status(self.db_path))
            if path == "/sync/queue":
                user = self.require_auth(ADMIN_ROLES)
                if not user:
                    return
                return self.list_queue(query)
            if path == "/sync/conflicts":
                user = self.require_auth(ADMIN_ROLES)
                if not user:
                    return
                return self.list_conflicts(query)
            return json_response(self, 404, {"error": "Ruta no encontrada"})
        except Exception as exc:
            return json_response(self, 500, {"error": str(exc)})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            if path == "/auth/login":
                return self.login()
            if path == "/sales":
                user = self.require_auth(SALES_ROLES)
                if not user:
                    return
                return self.create_sale(user)
            if path == "/customers":
                user = self.require_auth(CUSTOMER_WRITE_ROLES)
                if not user:
                    return
                return self.create_customer(user)
            if path == "/sync/run":
                user = self.require_auth(ADMIN_ROLES)
                if not user:
                    return
                result = self.sync_service.sync_once()
                return json_response(self, 200, result)
            if path == "/sync/retry":
                user = self.require_auth(ADMIN_ROLES)
                if not user:
                    return
                return json_response(self, 200, self.sync_service.retry_failed())
            if path == "/sync/test":
                user = self.require_auth(ADMIN_ROLES)
                if not user:
                    return
                return json_response(self, 200, self.sync_service.test_connection())
            if path == "/sync/cleanup":
                user = self.require_auth(ADMIN_ROLES)
                if not user:
                    return
                return json_response(self, 200, self.sync_service.cleanup_synced())
            return json_response(self, 404, {"error": "Ruta no encontrada"})
        except Exception as exc:
            return json_response(self, 500, {"error": str(exc)})

    def require_auth(self, allowed_roles):
        auth = self.headers.get("Authorization", "")
        token = auth.replace("Bearer ", "").strip()
        if not token:
            json_response(self, 401, {"error": "Token requerido"})
            return None

        conn = connect(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT s.token, s.usuario_id, s.rol, s.expires_at,
                       u.username, u.nombre_completo, u.activo
                FROM local_sessions s
                JOIN usuarios u ON u.id = s.usuario_id
                WHERE s.token = ?
                """,
                (token,),
            ).fetchone()
            if not row or not row["activo"]:
                json_response(self, 401, {"error": "Sesion invalida"})
                return None
            if row["expires_at"] and row["expires_at"] < now_iso():
                conn.execute("DELETE FROM local_sessions WHERE token = ?", (token,))
                conn.commit()
                json_response(self, 401, {"error": "La sesion expiro. Inicia sesion nuevamente."})
                return None
            if row["rol"] not in allowed_roles:
                json_response(self, 403, {"error": "Permiso insuficiente"})
                return None
            conn.execute(
                "UPDATE local_sessions SET last_activity_at = ? WHERE token = ?",
                (now_iso(), token),
            )
            conn.commit()
            return row_to_dict(row)
        finally:
            conn.close()

    def login(self):
        data = read_json(self)
        username = (data.get("username") or "").strip()
        password = data.get("password") or ""

        conn = connect(self.db_path)
        try:
            # Rate-limiting compartido con la app de escritorio
            bloqueado, segundos = verificar_bloqueo(conn, username)
            if bloqueado:
                return json_response(self, 429, {
                    "error": f"Cuenta bloqueada por intentos fallidos. "
                             f"Reintente en {segundos // 60} min {segundos % 60} s."})

            user = conn.execute(
                "SELECT * FROM usuarios WHERE username = ? AND activo = 1",
                (username,),
            ).fetchone()
            # Verificación con sal (PBKDF2) y retrocompatibilidad SHA-256 legacy.
            if not user or not verify_password(user["password_hash"], password):
                registrar_fallo(conn, username)
                conn.commit()
                return json_response(self, 401, {"error": "Usuario o contraseña incorrectos"})

            registrar_exito(conn, username)

            # Migrar hash legacy a PBKDF2 de forma transparente.
            if needs_rehash(user["password_hash"]):
                try:
                    conn.execute("UPDATE usuarios SET password_hash = ? WHERE id = ?",
                                 (secure_hash(password), user["id"]))
                except Exception:
                    pass

            token = secrets.token_urlsafe(32)
            expires = (datetime.now() + timedelta(hours=12)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                """
                INSERT INTO local_sessions
                    (token, usuario_id, rol, created_at, expires_at, last_activity_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (token, user["id"], user["rol"], now_iso(), expires, now_iso()),
            )
            conn.execute("UPDATE usuarios SET ultimo_acceso = ? WHERE id = ?", (now_iso(), user["id"]))
            conn.commit()
            return json_response(
                self,
                200,
                {
                    "token": token,
                    "user": {
                        "id": user["id"],
                        "username": user["username"],
                        "nombre_completo": user["nombre_completo"],
                        "rol": user["rol"],
                        "permissions": ROLE_PERMISSIONS.get(user["rol"], []),
                    },
                },
            )
        finally:
            conn.close()

    def list_products(self, query):
        search = (query.get("search", [""])[0] or "").strip().lower()
        limit = min(int(query.get("limit", ["100"])[0] or "100"), 500)
        offset = max(int(query.get("offset", ["0"])[0] or "0"), 0)
        params = []
        sql = """
            SELECT id, codigo_barras, nombre, categoria, marca, precio_venta, stock,
                   stock_minimo, unidad_medida, activo, viene_en_caja, unidades_por_caja,
                   unidades_por_media_caja, vende_por_empaque, permite_decimales
            FROM productos
            WHERE activo = 1 AND COALESCE(is_deleted, 0) = 0
        """
        if search:
            sql += """
                AND (
                    LOWER(nombre) LIKE ?
                    OR LOWER(COALESCE(codigo_barras, '')) LIKE ?
                    OR LOWER(COALESCE(categoria, '')) LIKE ?
                    OR LOWER(COALESCE(marca, '')) LIKE ?
                )
            """
            term = f"%{search}%"
            params.extend([term, term, term, term])
        sql += " ORDER BY nombre LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        conn = connect(self.db_path)
        try:
            products = [row_to_dict(row) for row in conn.execute(sql, params).fetchall()]
            return json_response(self, 200, {"products": products})
        finally:
            conn.close()

    def get_product(self, raw_id):
        try:
            product_id = int(raw_id)
        except ValueError:
            return json_response(self, 400, {"error": "ID de producto invalido"})
        conn = connect(self.db_path)
        try:
            product = conn.execute(
                "SELECT * FROM productos WHERE id = ? AND activo = 1 AND COALESCE(is_deleted, 0) = 0",
                (product_id,),
            ).fetchone()
            if not product:
                return json_response(self, 404, {"error": "Producto no encontrado"})
            return json_response(self, 200, {"product": row_to_dict(product)})
        finally:
            conn.close()

    def get_product_by_code(self, code):
        conn = connect(self.db_path)
        try:
            product = conn.execute(
                """
                SELECT * FROM productos
                WHERE codigo_barras = ? AND activo = 1 AND COALESCE(is_deleted, 0) = 0
                LIMIT 1
                """,
                (code,),
            ).fetchone()
            if not product:
                return json_response(self, 404, {"error": "Producto no encontrado"})
            return json_response(self, 200, {"product": row_to_dict(product)})
        finally:
            conn.close()

    def list_customers(self, query):
        search = (query.get("search", [""])[0] or "").strip().lower()
        limit = min(int(query.get("limit", ["100"])[0] or "100"), 500)
        offset = max(int(query.get("offset", ["0"])[0] or "0"), 0)
        params = []
        sql = """
            SELECT id, tipo_documento, numero_documento, nombre, telefono, email,
                   ciudad, limite_credito, saldo_pendiente, activo
            FROM clientes
            WHERE activo = 1 AND COALESCE(is_deleted, 0) = 0
        """
        if search:
            sql += """
                AND (
                    LOWER(nombre) LIKE ?
                    OR LOWER(numero_documento) LIKE ?
                    OR LOWER(COALESCE(telefono, '')) LIKE ?
                )
            """
            term = f"%{search}%"
            params.extend([term, term, term])
        sql += " ORDER BY nombre LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        conn = connect(self.db_path)
        try:
            customers = [row_to_dict(row) for row in conn.execute(sql, params).fetchall()]
            return json_response(self, 200, {"customers": customers})
        finally:
            conn.close()

    def create_customer(self, user):
        data = read_json(self)
        nombre = (data.get("nombre") or "").strip()
        documento = (data.get("numero_documento") or "").strip()
        if not nombre or not documento:
            return json_response(self, 400, {"error": "Nombre y documento son obligatorios"})
        conn = connect(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                """
                INSERT INTO clientes (
                    tipo_documento, numero_documento, nombre, telefono, email,
                    direccion, ciudad, activo, sync_status, updated_at, created_by, updated_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'pending', ?, ?, ?)
                """,
                (
                    data.get("tipo_documento") or "CC",
                    documento,
                    nombre,
                    data.get("telefono"),
                    data.get("email"),
                    data.get("direccion"),
                    data.get("ciudad"),
                    now_iso(),
                    user["usuario_id"],
                    user["usuario_id"],
                ),
            )
            customer_id = cursor.lastrowid
            ensure_local_id(conn, "clientes", customer_id)
            customer = row_to_dict(conn.execute("SELECT * FROM clientes WHERE id=?", (customer_id,)).fetchone())
            enqueue_sync(conn, "customer", customer_id, "create", customer, "clientes")
            conn.commit()
            return json_response(self, 201, {"customer": customer})
        except Exception as exc:
            conn.rollback()
            return json_response(self, 400, {"error": str(exc)})
        finally:
            conn.close()

    def create_sale(self, user):
        data = read_json(self)
        items = data.get("items") or []
        if not items:
            return json_response(self, 400, {"error": "La venta no tiene productos"})

        metodo_pago = data.get("metodo_pago") or "EFECTIVO"
        cliente_id = data.get("cliente_id")
        descuento = float(data.get("descuento") or 0)
        observaciones = data.get("observaciones")
        if descuento < 0:
            return json_response(self, 400, {"error": "El descuento no puede ser negativo"})

        conn = connect(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            product_ids = sorted({int(item["producto_id"]) for item in items})
            placeholders = ",".join("?" for _ in product_ids)
            products = {
                row["id"]: row_to_dict(row)
                for row in conn.execute(
                    f"""
                    SELECT id, nombre, stock, precio_venta
                    FROM productos
                    WHERE id IN ({placeholders})
                      AND activo = 1
                      AND COALESCE(is_deleted, 0) = 0
                    """,
                    product_ids,
                ).fetchall()
            }

            requested_quantities = {}
            for item in items:
                pid = int(item["producto_id"])
                qty = float(item["cantidad"])
                product = products.get(pid)
                if qty <= 0:
                    conn.rollback()
                    return json_response(self, 400, {"error": "La cantidad debe ser mayor a cero"})
                if not product:
                    conn.rollback()
                    return json_response(self, 400, {"error": f"Producto {pid} no existe"})
                item_discount = float(item.get("descuento") or 0)
                if item_discount < 0 or item_discount > float(product["precio_venta"]) * qty:
                    conn.rollback()
                    return json_response(self, 400, {"error": f"Descuento invalido para {product['nombre']}"})
                requested_quantities[pid] = requested_quantities.get(pid, 0) + qty

            for pid, qty in requested_quantities.items():
                product = products[pid]
                if float(product["stock"]) < qty:
                    conn.rollback()
                    return json_response(self, 409, {"error": f"Stock insuficiente para {product['nombre']}"})

            # Consecutivo de factura ATÓMICO (igual que la app de escritorio):
            # evita colisiones cuando varias cajas venden por la API a la vez.
            fecha_key = datetime.now().strftime("%Y%m%d")
            prefijo = fecha_key + "-"
            base_row = conn.execute(
                "SELECT MAX(CAST(SUBSTR(numero_factura, 10) AS INTEGER)) AS ultimo FROM ventas WHERE numero_factura LIKE ?",
                (prefijo + "%",),
            ).fetchone()
            base = (base_row["ultimo"] or 0)
            conn.execute(
                "INSERT INTO consecutivos (clave, valor) VALUES (?, ?) "
                "ON CONFLICT(clave) DO UPDATE SET valor = CASE WHEN valor < ? THEN ? ELSE valor + 1 END",
                (fecha_key, base + 1, base, base + 1),
            )
            consec = conn.execute(
                "SELECT valor FROM consecutivos WHERE clave = ?", (fecha_key,)
            ).fetchone()["valor"]
            numero_factura = f"{prefijo}{consec:04d}"

            subtotal = sum(
                float(products[int(i["producto_id"])]["precio_venta"]) * float(i["cantidad"])
                - float(i.get("descuento") or 0)
                for i in items
            )
            total = subtotal - descuento
            if total < 0:
                conn.rollback()
                return json_response(self, 400, {"error": "El descuento supera el total de la venta"})
            venta_cur = conn.execute(
                """
                INSERT INTO ventas
                    (numero_factura, cliente_id, usuario_id, subtotal, descuento, iva, total,
                     metodo_pago, estado, observaciones, fecha, sync_status, updated_at, created_by, updated_by)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?, 'COMPLETADA', ?, ?, 'pending', ?, ?, ?)
                """,
                (
                    numero_factura,
                    cliente_id,
                    user["usuario_id"],
                    subtotal,
                    descuento,
                    total,
                    metodo_pago,
                    observaciones,
                    now_iso(),
                    now_iso(),
                    user["usuario_id"],
                    user["usuario_id"],
                ),
            )
            venta_id = venta_cur.lastrowid
            ensure_local_id(conn, "ventas", venta_id)
            venta_payload = row_to_dict(conn.execute("SELECT * FROM ventas WHERE id=?", (venta_id,)).fetchone())
            enqueue_sync(conn, "sale", venta_id, "create", venta_payload, "ventas")

            details = []
            movements = []
            for item in items:
                pid = int(item["producto_id"])
                qty = float(item["cantidad"])
                price = float(products[pid]["precio_venta"])
                item_discount = float(item.get("descuento") or 0)
                item_subtotal = price * qty - item_discount
                detail_cur = conn.execute(
                    """
                    INSERT INTO detalle_ventas
                        (venta_id, producto_id, cantidad, precio_unitario, descuento, subtotal, iva,
                         sync_status, updated_at, created_by, updated_by)
                    VALUES (?, ?, ?, ?, ?, ?, 0, 'pending', ?, ?, ?)
                    """,
                    (venta_id, pid, qty, price, item_discount, item_subtotal, now_iso(), user["usuario_id"], user["usuario_id"]),
                )
                detail_id = detail_cur.lastrowid
                ensure_local_id(conn, "detalle_ventas", detail_id)
                detail_payload = row_to_dict(conn.execute("SELECT * FROM detalle_ventas WHERE id=?", (detail_id,)).fetchone())
                enqueue_sync(conn, "sale_detail", detail_id, "create", detail_payload, "detalle_ventas")
                details.append(detail_payload)

                conn.execute("UPDATE productos SET stock = stock - ?, sync_status='pending', updated_at=?, updated_by=? WHERE id=?", (qty, now_iso(), user["usuario_id"], pid))
                product_payload = row_to_dict(conn.execute("SELECT * FROM productos WHERE id=?", (pid,)).fetchone())
                enqueue_sync(conn, "product", pid, "update", product_payload, "productos")

                mov_cur = conn.execute(
                    """
                    INSERT INTO movimientos
                        (tipo, producto_id, usuario_id, cantidad, precio_unitario, costo_total,
                         motivo, num_factura, fecha, sync_status, updated_at, created_by, updated_by)
                    VALUES ('SALIDA_VENTA', ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                    """,
                    (pid, user["usuario_id"], qty, price, item_subtotal, f"Venta {numero_factura}", numero_factura, now_iso(), now_iso(), user["usuario_id"], user["usuario_id"]),
                )
                mov_id = mov_cur.lastrowid
                ensure_local_id(conn, "movimientos", mov_id)
                mov_payload = row_to_dict(conn.execute("SELECT * FROM movimientos WHERE id=?", (mov_id,)).fetchone())
                enqueue_sync(conn, "inventory_movement", mov_id, "create", mov_payload, "movimientos")
                movements.append(mov_payload)

            conn.commit()
            return json_response(
                self,
                201,
                {
                    "venta": venta_payload,
                    "detalles": details,
                    "movimientos": movements,
                    "sync_status": "pending",
                },
            )
        except Exception as exc:
            conn.rollback()
            return json_response(self, 500, {"error": str(exc)})
        finally:
            conn.close()

    def get_sale(self, raw_id):
        try:
            sale_id = int(raw_id)
        except ValueError:
            return json_response(self, 400, {"error": "ID de venta invalido"})
        conn = connect(self.db_path)
        try:
            sale = conn.execute(
                """
                SELECT v.*, c.nombre AS cliente_nombre, u.nombre_completo AS vendedor
                FROM ventas v
                LEFT JOIN clientes c ON c.id = v.cliente_id
                LEFT JOIN usuarios u ON u.id = v.usuario_id
                WHERE v.id = ?
                """,
                (sale_id,),
            ).fetchone()
            if not sale:
                return json_response(self, 404, {"error": "Venta no encontrada"})
            details = [
                row_to_dict(row)
                for row in conn.execute(
                    """
                    SELECT dv.*, p.nombre AS producto_nombre
                    FROM detalle_ventas dv
                    JOIN productos p ON p.id = dv.producto_id
                    WHERE dv.venta_id = ?
                    """,
                    (sale_id,),
                ).fetchall()
            ]
            return json_response(self, 200, {"sale": row_to_dict(sale), "details": details})
        finally:
            conn.close()

    def list_queue(self, query):
        limit = min(int(query.get("limit", ["100"])[0] or "100"), 500)
        conn = connect(self.db_path)
        try:
            rows = [
                row_to_dict(row)
                for row in conn.execute(
                    "SELECT * FROM sync_queue ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            ]
            return json_response(self, 200, {"queue": rows})
        finally:
            conn.close()

    def list_conflicts(self, query):
        limit = min(int(query.get("limit", ["100"])[0] or "100"), 500)
        conn = connect(self.db_path)
        try:
            rows = [
                row_to_dict(row)
                for row in conn.execute(
                    "SELECT * FROM sync_conflicts ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            ]
            return json_response(self, 200, {"conflicts": rows})
        finally:
            conn.close()


def run_server(host="0.0.0.0", port=8000, db_path=DEFAULT_DB_PATH, start_sync=True,
               usar_https=False):
    try:
        from app_logging import setup_logging
        setup_logging(componente="server")
    except Exception:
        pass
    ensure_local_first_schema(db_path)
    LocalFerreteriaAPI.db_path = db_path
    LocalFerreteriaAPI.sync_service = get_service(db_path)
    if start_sync:
        # Verificación de Supabase no bloqueante: solo informa, nunca detiene el arranque.
        try:
            chequeo = LocalFerreteriaAPI.sync_service.test_connection()
            if chequeo.get("ok"):
                print(f"[SYNC] Supabase conectado. Sincronizacion automatica activa "
                      f"(cada {LocalFerreteriaAPI.sync_service.interval}s).")
            else:
                print(f"[SYNC] Supabase no disponible ({chequeo.get('message')}). "
                      f"La cola sync_queue se procesara cuando vuelva la conexion.")
        except Exception as exc:
            print(f"[SYNC] No se pudo verificar Supabase: {exc}. "
                  f"El sistema sigue operando en modo local.")
        LocalFerreteriaAPI.sync_service.start_background()
    else:
        print("[SYNC] Sincronizacion deshabilitada (--no-sync).")
    server = ThreadingHTTPServer((host, port), LocalFerreteriaAPI)
    esquema = "http"
    if usar_https:
        try:
            import ssl
            import cert_manager
            cert, key = cert_manager.crear_cert_si_falta()
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(cert, key)
            server.socket = ctx.wrap_socket(server.socket, server_side=True)
            esquema = "https"
            print("[HTTPS] TLS activo (certificado autofirmado).")
        except Exception as exc:
            print(f"[HTTPS] No se pudo activar TLS ({exc}); el servidor sigue en HTTP.")
    print(f"Servidor local iniciado en {esquema}://{host}:{port}")
    print(f"Base local: {db_path}")
    server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Servidor local-first para Ferreteria")
    parser.add_argument("--host", default=os.environ.get("LOCAL_SERVER_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("LOCAL_SERVER_PORT", "8000")))
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--no-sync", action="store_true")
    parser.add_argument("--https", action="store_true")
    args = parser.parse_args()
    run_server(args.host, args.port, args.db, start_sync=not args.no_sync,
               usar_https=args.https)
