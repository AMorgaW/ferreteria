# -*- coding: utf-8 -*-
"""
Modelos de datos para el sistema de ferretería
Define las estructuras de datos y clases del dominio
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Tuple
from enum import Enum

class RolUsuario(Enum):
    """Roles de usuario en el sistema"""
    ADMIN = "Administrador"
    GERENTE = "Gerente"
    VENDEDOR = "Vendedor"
    BODEGUERO = "Bodeguero"
    CONTADOR = "Contador"

class TipoMovimiento(Enum):
    """Tipos de movimiento de inventario"""
    ENTRADA_COMPRA = "Entrada por Compra"
    ENTRADA_DEVOLUCION = "Entrada por Devolución"
    ENTRADA_AJUSTE = "Ajuste Positivo"
    SALIDA_VENTA = "Salida por Venta"
    SALIDA_DEVOLUCION = "Salida por Devolución a Proveedor"
    SALIDA_MERMA = "Merma"
    SALIDA_DAÑADO = "Producto Dañado"
    SALIDA_AJUSTE = "Ajuste Negativo"
    TRANSFERENCIA = "Transferencia"

class MetodoPago(Enum):
    """Métodos de pago disponibles"""
    EFECTIVO = "Efectivo"
    TARJETA_DEBITO = "Tarjeta Débito"
    TARJETA_CREDITO = "Tarjeta Crédito"
    TRANSFERENCIA = "Transferencia"
    NEQUI = "Nequi"
    DAVIPLATA = "Daviplata"
    CREDITO = "Crédito"

class EstadoVenta(Enum):
    """Estados de una venta"""
    COMPLETADA = "Completada"
    PENDIENTE = "Pendiente"
    CANCELADA = "Cancelada"

@dataclass
class Usuario:
    """Modelo de usuario del sistema"""
    id: Optional[int] = None
    username: str = ""
    password_hash: str = ""
    nombre_completo: str = ""
    rol: str = RolUsuario.VENDEDOR.name
    email: Optional[str] = None
    telefono: Optional[str] = None
    activo: bool = True
    fecha_creacion: Optional[datetime] = None
    ultimo_acceso: Optional[datetime] = None

@dataclass
@dataclass
class Producto:
    """Modelo de producto"""
    id: Optional[int] = None
    codigo_barras: Optional[str] = None
    nombre: str = ""
    categoria: Optional[str] = None
    marca: Optional[str] = None
    proveedor_id: Optional[int] = None
    precio_compra: float = 0.0
    precio_venta: float = 0.0
    stock: int = 0
    stock_minimo: int = 10
    ubicacion: Optional[str] = None
    descripcion: Optional[str] = None
    unidad_medida: str = "UNIDAD"
    viene_en_caja: bool = False
    unidades_por_caja: int = 1
    unidades_por_media_caja: int = 1
    vende_por_empaque: int = 0
    # Nuevos campos para unidades de venta flexibles
    usar_unidades_categoria: bool = True
    unidades_venta_custom: Optional[str] = None  # JSON
    unidad_base_producto: Optional[str] = None
    permite_decimales: bool = False  # True para productos que se venden por medida (metros, kilos, etc.)
    iva: float = 0.0  # IVA eliminado del sistema
    activo: bool = True
    fecha_registro: Optional[datetime] = None

    def calcular_margen(self) -> float:
        """Calcula el margen de ganancia en porcentaje"""
        if self.precio_compra == 0:
            return 0.0
        return ((self.precio_venta - self.precio_compra) / self.precio_compra) * 100

    def calcular_ganancia_neta(self) -> float:
        """Calcula la ganancia neta por unidad"""
        return self.precio_venta - self.precio_compra

    def tiene_stock_disponible(self, cantidad: int) -> bool:
        """Verifica si hay stock disponible para una cantidad dada"""
        return self.stock >= cantidad

    def es_stock_critico(self) -> bool:
        """Verifica si el stock está en nivel crítico"""
        return self.stock <= self.stock_minimo

    def validar(self) -> Tuple[bool, str]:
        """Valida los datos del producto"""
        if not self.nombre or self.nombre.strip() == "":
            return False, "El nombre del producto es obligatorio"

        if self.precio_venta < 0:
            return False, "El precio de venta no puede ser negativo"

        if self.precio_compra < 0:
            return False, "El precio de compra no puede ser negativo"

        if self.stock < 0:
            return False, "El stock no puede ser negativo"

        if self.stock_minimo < 0:
            return False, "El stock mínimo no puede ser negativo"

        if self.iva < 0 or self.iva > 1:
            return False, "El IVA debe estar entre 0 y 1 (0-100%)"

        if self.viene_en_caja and self.unidades_por_caja < 1:
            return False, "Las unidades por caja deben ser al menos 1"

        return True, "Validación exitosa"

@dataclass
class Cliente:
    """Modelo de cliente"""
    id: Optional[int] = None
    tipo_documento: str = "CC"  # CC, NIT, CE
    numero_documento: str = ""
    nombre: str = ""
    telefono: Optional[str] = None
    email: Optional[str] = None
    direccion: Optional[str] = None
    ciudad: Optional[str] = None
    limite_credito: float = 0.0
    saldo_pendiente: float = 0.0
    clasificacion: str = "C"  # A, B, C
    descuento_default: float = 0.0
    puntos_fidelidad: int = 0
    activo: bool = True
    fecha_registro: Optional[datetime] = None
    
    def tiene_credito_disponible(self, monto: float) -> bool:
        """Verifica si el cliente tiene crédito disponible"""
        return (self.saldo_pendiente + monto) <= self.limite_credito

@dataclass
class Proveedor:
    """Modelo de proveedor"""
    id: Optional[int] = None
    nit: Optional[str] = None
    nombre: str = ""
    telefono: Optional[str] = None
    correo: Optional[str] = None
    direccion: Optional[str] = None
    ciudad: Optional[str] = None
    contacto_nombre: Optional[str] = None
    contacto_telefono: Optional[str] = None
    productos_provee: Optional[str] = None
    calificacion: float = 0.0  # 1-5 estrellas
    dias_credito: int = 0
    activo: bool = True
    fecha_registro: Optional[datetime] = None

@dataclass
class Venta:
    """Modelo de venta"""
    id: Optional[int] = None
    numero_factura: Optional[str] = None
    fecha: Optional[datetime] = None
    cliente_id: Optional[int] = None
    usuario_id: Optional[int] = None
    subtotal: float = 0.0
    descuento: float = 0.0
    iva: float = 0.0
    total: float = 0.0
    metodo_pago: str = MetodoPago.EFECTIVO.name
    estado: str = EstadoVenta.COMPLETADA.name
    observaciones: Optional[str] = None
    detalles: List['DetalleVenta'] = None
    
    def __post_init__(self):
        if self.detalles is None:
            self.detalles = []

@dataclass
class DetalleVenta:
    """Detalle de productos en una venta"""
    id: Optional[int] = None
    venta_id: Optional[int] = None
    producto_id: int = 0
    cantidad: int = 0
    precio_unitario: float = 0.0
    descuento: float = 0.0
    subtotal: float = 0.0
    iva: float = 0.0

@dataclass
class Movimiento:
    """Modelo de movimiento de inventario"""
    id: Optional[int] = None
    tipo: str = TipoMovimiento.ENTRADA_COMPRA.name
    producto_id: int = 0
    proveedor_id: Optional[int] = None
    usuario_id: Optional[int] = None
    cantidad: int = 0
    precio_unitario: float = 0.0
    costo_total: float = 0.0
    motivo: Optional[str] = None
    num_factura: Optional[str] = None
    en_cajas: bool = False
    num_cajas: int = 0
    fecha: Optional[datetime] = None
    observaciones: Optional[str] = None

    def calcular_total(self) -> float:
        """Calcula el costo total del movimiento"""
        return self.cantidad * self.precio_unitario

    def es_entrada(self) -> bool:
        """Verifica si es un movimiento de entrada"""
        return self.tipo.startswith('ENTRADA')

    def es_salida(self) -> bool:
        """Verifica si es un movimiento de salida"""
        return self.tipo.startswith('SALIDA')

    def validar(self) -> Tuple[bool, str]:
        """Valida los datos del movimiento"""
        if self.producto_id <= 0:
            return False, "Debe especificar un producto válido"

        if self.cantidad <= 0:
            return False, "La cantidad debe ser mayor a 0"

        if self.precio_unitario < 0:
            return False, "El precio unitario no puede ser negativo"

        # Validar que tipo sea válido
        tipos_validos = [t.name for t in TipoMovimiento]
        if self.tipo not in tipos_validos:
            return False, f"Tipo de movimiento inválido: {self.tipo}"

        # Validar cajas
        if self.en_cajas:
            if self.num_cajas <= 0:
                return False, "El número de cajas debe ser mayor a 0"

        return True, "Validación exitosa"

@dataclass
class CierreCaja:
    """Modelo de cierre de caja"""
    id: Optional[int] = None
    usuario_id: int = 0
    fecha_apertura: Optional[datetime] = None
    fecha_cierre: Optional[datetime] = None
    monto_inicial: float = 0.0
    ventas_efectivo: float = 0.0
    ventas_tarjeta: float = 0.0
    ventas_transferencia: float = 0.0
    ventas_otros: float = 0.0
    total_ventas: float = 0.0
    gastos: float = 0.0
    monto_esperado: float = 0.0
    monto_real: float = 0.0
    diferencia: float = 0.0
    observaciones: Optional[str] = None

@dataclass
class CuentaPorCobrar:
    """Modelo de cuenta por cobrar"""
    id: Optional[int] = None
    venta_id: int = 0
    cliente_id: int = 0
    monto_total: float = 0.0
    monto_pagado: float = 0.0
    saldo_pendiente: float = 0.0
    fecha_vencimiento: Optional[datetime] = None
    estado: str = "PENDIENTE"  # PENDIENTE, PAGADO, VENCIDO
    observaciones: Optional[str] = None

@dataclass
class Alerta:
    """Modelo de alertas del sistema"""
    id: Optional[int] = None
    tipo: str = ""  # STOCK_BAJO, VENCIMIENTO, COBRO, etc.
    titulo: str = ""
    mensaje: str = ""
    prioridad: str = "MEDIA"  # BAJA, MEDIA, ALTA, CRITICA
    leida: bool = False
    fecha_creacion: Optional[datetime] = None
    relacionado_id: Optional[int] = None
    relacionado_tipo: Optional[str] = None

@dataclass
class MovimientoInventario:
    """Modelo para movimientos de inventario"""
    tipo_movimiento: str  # ENTRADA_COMPRA, SALIDA_VENTA, etc.
    producto_id: int
    cantidad: int
    precio_unitario: float
    usuario_id: int
    fecha: datetime
    proveedor_id: int = None
    cliente_id: int = None
    numero_factura: str = None  # [OK] NUEVO CAMPO
    observaciones: str = None
    id: int = None
    
    def to_dict(self):
        """Convierte el movimiento a diccionario"""
        return {
            'id': self.id,
            'tipo_movimiento': self.tipo_movimiento,
            'producto_id': self.producto_id,
            'proveedor_id': self.proveedor_id,
            'cliente_id': self.cliente_id,
            'cantidad': self.cantidad,
            'precio_unitario': self.precio_unitario,
            'numero_factura': self.numero_factura,  # [OK] NUEVO
            'observaciones': self.observaciones,
            'usuario_id': self.usuario_id,
            'fecha': self.fecha.isoformat() if isinstance(self.fecha, datetime) else self.fecha
        }

# [OK] NUEVOS: Modelos para gestión de deudas en compras

@dataclass
class Abono:
    """Modelo de abono a facturas de compra"""
    id: Optional[int] = None
    id_compra: int = None
    monto_abono: float = 0
    fecha_abono: str = None
    tipo_pago: str = None  # Efectivo, Cheque, Transferencia, Depósito, Otro
    numero_comprobante: Optional[str] = None
    usuario: Optional[str] = None
    observaciones: Optional[str] = None
    created_at: Optional[str] = None

@dataclass
class ResumenDeuda:
    """Modelo de resumen de deudas por proveedor"""
    id_proveedor: int = None
    nombre_proveedor: str = ""
    total_deuda: float = 0
    cantidad_facturas_pendientes: int = 0
    deuda_30_dias: float = 0
    deuda_60_dias: float = 0
    deuda_90_dias: float = 0
    fecha_factura_mas_antigua: Optional[str] = None
    estado_vencimiento: str = ""

# [OK] NUEVOS: Modelos para gestión de cuentas por cobrar (ventas a crédito)

@dataclass
class AbonoVenta:
    """Modelo de abono a facturas de venta"""
    id: Optional[int] = None
    id_venta: int = None
    monto_abono: float = 0
    fecha_abono: str = None
    tipo_pago: str = None  # Efectivo, Cheque, Transferencia, Depósito, Otro
    numero_comprobante: Optional[str] = None
    usuario: Optional[str] = None
    observaciones: Optional[str] = None
    created_at: Optional[str] = None

@dataclass
class ResumenCuentaPorCobrar:
    """Modelo de resumen de cuentas por cobrar por cliente"""
    id_cliente: int = None
    nombre_cliente: str = ""
    total_deuda: float = 0
    cantidad_facturas_pendientes: int = 0
    deuda_30_dias: float = 0
    deuda_60_dias: float = 0
    deuda_90_dias: float = 0
    fecha_factura_mas_antigua: Optional[str] = None
    estado_vencimiento: str = ""