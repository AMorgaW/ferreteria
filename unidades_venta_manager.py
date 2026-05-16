# -*- coding: utf-8 -*-
"""
Módulo para gestión de unidades de venta flexibles
Maneja la configuración de categorías y unidades alternativas
"""
import json
from typing import List, Dict, Optional, Tuple

class UnidadesVentaManager:
    """Gestor de unidades de venta por categoría"""
    
    def __init__(self, db_manager):
        self.db = db_manager
    
    def obtener_categorias(self) -> List[Dict]:
        """Obtiene todas las categorías configuradas"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM categorias_config WHERE activo = 1 ORDER BY nombre")
        categorias = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        # Parsear JSON
        for cat in categorias:
            cat['unidades_venta'] = json.loads(cat['unidades_venta_json'])
        
        return categorias
    
    def obtener_categoria(self, nombre_categoria: str) -> Optional[Dict]:
        """Obtiene una categoría específica por nombre"""
        conn = self.db.conectar()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM categorias_config WHERE nombre = ?", (nombre_categoria,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            cat = dict(row)
            cat['unidades_venta'] = json.loads(cat['unidades_venta_json'])
            return cat
        return None
    
    def obtener_unidades_venta_producto(self, producto: Dict) -> List[Dict]:
        """
        Obtiene las unidades de venta aplicables a un producto
        Incluye opciones de Caja y Media Caja si están configuradas
        """
        unidades_disponibles = []
        
        # Siempre incluir venta por unidad
        unidades_disponibles.append({'nombre': 'Unidad', 'factor': 1.0})
        
        # Si el producto tiene configuración de empaques
        if producto.get('vende_por_empaque') == 1:
            # Media Caja (si está configurado)
            unidades_media_caja = producto.get('unidades_por_media_caja', 0)
            if unidades_media_caja and unidades_media_caja > 1:
                unidades_disponibles.append({
                    'nombre': f'1/2 Caja ({unidades_media_caja}u)',
                    'factor': float(unidades_media_caja)
                })
            
            # Caja completa (si está configurado)
            unidades_caja = producto.get('unidades_por_caja', 0)
            if unidades_caja and unidades_caja > 1:
                unidades_disponibles.append({
                    'nombre': f'Caja ({unidades_caja}u)',
                    'factor': float(unidades_caja)
                })
        
        # Si no tiene configuración de empaques, intentar usar categoría
        if len(unidades_disponibles) == 1:
            # Si el producto usa configuración personalizada
            if not producto.get('usar_unidades_categoria', True):
                if producto.get('unidades_venta_custom'):
                    return json.loads(producto['unidades_venta_custom'])
                return unidades_disponibles
            
            # Usar configuración de la categoría
            categoria = self.obtener_categoria(producto.get('categoria', ''))
            if categoria:
                unidades = categoria['unidades_venta'].copy()
                
                # Procesar unidades que requieren configuración
                unidades_procesadas = []
                for unidad in unidades:
                    if unidad.get('requiere_config'):
                        # Casos especiales que requieren info del producto
                        if unidad['nombre'] == 'Cajas' and producto.get('viene_en_caja'):
                            unidades_procesadas.append({
                                'nombre': 'Cajas',
                                'factor': producto.get('unidades_por_caja', 1)
                            })
                        # No incluir opciones no configuradas
                    else:
                        unidades_procesadas.append(unidad)
                
                if unidades_procesadas:
                    return unidades_procesadas
        
        return unidades_disponibles
    
    def convertir_a_unidad_base(self, producto: Dict, cantidad: float, 
                                 unidad_seleccionada: str) -> Tuple[float, str]:
        """
        Convierte una cantidad de una unidad específica a la unidad base
        Returns: (cantidad_en_unidad_base, unidad_base)
        """
        unidades = self.obtener_unidades_venta_producto(producto)
        
        # Buscar el factor de conversión
        for unidad in unidades:
            if unidad['nombre'] == unidad_seleccionada:
                cantidad_base = cantidad * unidad['factor']
                
                # Determinar unidad base
                if producto.get('usar_unidades_categoria', True):
                    categoria = self.obtener_categoria(producto.get('categoria', ''))
                    unidad_base = categoria['unidad_base'] if categoria else 'unidad'
                else:
                    unidad_base = producto.get('unidad_base_producto', 'unidad')
                
                return cantidad_base, unidad_base
        
        # Si no se encuentra, asumir que ya está en unidad base
        return cantidad, producto.get('unidad_base_producto', 'unidad')
    
    def formatear_stock_display(self, producto: Dict) -> str:
        """
        Formatea el stock para mostrar de forma simple
        Solo muestra la cantidad en unidades base
        """
        stock = producto.get('stock', 0)
        
        # Obtener unidad base
        if producto.get('usar_unidades_categoria', True):
            categoria = self.obtener_categoria(producto.get('categoria', ''))
            unidad_base = categoria['unidad_base'] if categoria else 'unidades'
        else:
            unidad_base = producto.get('unidad_base_producto', 'unidades')
        
        # Formato simple: solo stock y unidad base
        return f"{stock} {unidad_base}"
    
    def validar_stock_disponible(self, producto: Dict, cantidad: float, 
                                  unidad_seleccionada: str) -> Tuple[bool, str]:
        """
        Valida si hay suficiente stock para una venta
        Returns: (es_valido, mensaje)
        """
        cantidad_base, _ = self.convertir_a_unidad_base(producto, cantidad, unidad_seleccionada)
        stock_disponible = producto.get('stock', 0)
        
        if cantidad_base > stock_disponible:
            # Calcular cuánto hay disponible en la unidad seleccionada
            unidades = self.obtener_unidades_venta_producto(producto)
            for unidad in unidades:
                if unidad['nombre'] == unidad_seleccionada:
                    disponible_en_unidad = stock_disponible / unidad['factor']
                    return False, f"Solo hay {disponible_en_unidad:.2f} {unidad_seleccionada.lower()} disponibles"
            
            return False, f"Stock insuficiente"
        
        return True, "Stock disponible"
    
    def obtener_nombres_categorias(self) -> List[str]:
        """Obtiene solo los nombres de las categorías para listas desplegables"""
        categorias = self.obtener_categorias()
        return [cat['nombre'] for cat in categorias]
