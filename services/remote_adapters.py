# -*- coding: utf-8 -*-
"""
Adaptadores para el cliente remoto.

Exponen EXACTAMENTE la misma interfaz que los repositorios/servicios locales
(productos_repo, clientes_repo, ventas_service, auth, db) pero por debajo
hablan con el servidor LAN a través de la API (LocalAPIClient). Así el cliente
remoto reutiliza la MISMA interfaz moderna `VentasUIModern` (sin duplicar UI).
"""
import sqlite3
from types import SimpleNamespace

from services.local_api_client import LocalAPIError


class RemoteDB:
    """db_manager mínimo: solo provee conectar() para componentes como
    UnidadesVentaManager. Devuelve una BD en memoria con la tabla esperada
    vacía, de modo que se usen las unidades por defecto."""

    db_name = ":memory:"

    def conectar(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE IF NOT EXISTS categorias_config "
            "(id INTEGER PRIMARY KEY, nombre TEXT, unidad_base TEXT, "
            "unidades_venta TEXT, activo INTEGER DEFAULT 1)"
        )
        return conn


class RemoteAuth:
    """auth mínimo con el usuario autenticado en el servidor."""

    def __init__(self, user: dict):
        self.usuario_actual = SimpleNamespace(
            id=user.get("id"),
            username=user.get("username"),
            nombre_completo=user.get("nombre_completo") or user.get("username") or "Usuario",
            rol=user.get("rol") or "VENDEDOR",
        )

    def tiene_permiso(self, accion):
        # La autorización real la valida el servidor con el token; aquí se
        # permite operar el POS (el servidor rechazará lo no permitido).
        return True


class RemoteProductosRepo:
    def __init__(self, api):
        self.api = api

    # La caché local no aplica en remoto -> se usa la ruta directa a la API.
    def cache_disponible(self):
        return False

    def buscar_productos_cache(self, *a, **k):
        return []

    def invalidar_cache(self):
        pass

    def precargar_cache(self):
        return []

    def listar_productos(self, solo_activos=True, limite=None):
        try:
            return self.api.get_products(limit=limite or 200)
        except LocalAPIError:
            return []

    def buscar_productos(self, termino="", solo_activos=True, limite=None):
        try:
            return self.api.get_products(search=termino or "", limit=limite or 150)
        except LocalAPIError:
            return []

    def obtener_por_id(self, producto_id):
        try:
            return self.api.get_product(producto_id)
        except LocalAPIError:
            return None

    def obtener_por_codigo(self, codigo):
        try:
            return self.api.get_product_by_code(codigo)
        except LocalAPIError:
            return None

    def obtener_categorias(self):
        # La API no expone categorías -> derivarlas de los productos.
        try:
            prods = self.api.get_products(limit=300)
            return sorted({p.get("categoria") for p in prods if p.get("categoria")})
        except LocalAPIError:
            return []


class RemoteClientesRepo:
    def __init__(self, api):
        self.api = api

    def cache_disponible(self):
        return False

    def buscar_clientes_cache(self, *a, **k):
        return []

    def invalidar_cache(self):
        pass

    def buscar_clientes(self, termino="", limite=None):
        try:
            return self.api.get_customers(search=termino or "", limit=limite or 100)
        except LocalAPIError:
            return []

    def listar_clientes(self, *a, **k):
        try:
            return self.api.get_customers(limit=200)
        except LocalAPIError:
            return []

    def crear_cliente(self, cliente):
        payload = {
            "tipo_documento": getattr(cliente, "tipo_documento", "CC"),
            "numero_documento": getattr(cliente, "numero_documento", ""),
            "nombre": getattr(cliente, "nombre", ""),
            "telefono": getattr(cliente, "telefono", None),
            "email": getattr(cliente, "email", None),
            "direccion": getattr(cliente, "direccion", None),
            "ciudad": getattr(cliente, "ciudad", None),
        }
        try:
            nuevo = self.api.create_customer(payload)
            return True, "Cliente creado", nuevo.get("id")
        except LocalAPIError as exc:
            return False, str(exc), None


class RemoteVentasService:
    def __init__(self, api, db):
        self.api = api
        self.db = db

    def registrar_venta(self, items, cliente_id=None, metodo_pago="EFECTIVO",
                        descuento_general=0, observaciones=None):
        payload = {
            "items": [
                {"producto_id": it["producto_id"],
                 "cantidad": it["cantidad"],
                 "descuento": it.get("descuento", 0)}
                for it in items
            ],
            "metodo_pago": metodo_pago,
            "descuento": descuento_general or 0,
        }
        if cliente_id:
            payload["cliente_id"] = cliente_id
        if observaciones:
            payload["observaciones"] = observaciones
        try:
            res = self.api.create_sale(payload)
        except LocalAPIError as exc:
            return False, str(exc), None

        v = res.get("venta", res) or {}
        venta = SimpleNamespace(
            id=v.get("id"),
            numero_factura=v.get("numero_factura"),
            fecha=v.get("fecha"),
            cliente_id=v.get("cliente_id"),
            subtotal=v.get("subtotal", 0) or 0,
            descuento=v.get("descuento", 0) or 0,
            iva=v.get("iva", 0) or 0,
            total=v.get("total", 0) or 0,
            metodo_pago=v.get("metodo_pago", metodo_pago),
            estado=v.get("estado", "COMPLETADA"),
        )
        return True, f"Venta {venta.numero_factura} registrada", venta

    def agregar_productos_a_factura(self, *a, **k):
        return False, "Agregar a factura de crédito no está disponible en modo remoto"


class RemoteCuentasService:
    """Cuentas por cobrar: la API no las expone -> se degrada (sin crédito previo)."""

    def __init__(self, api):
        self.api = api

    def obtener_ventas_credito_pendientes(self, *a, **k):
        return []
