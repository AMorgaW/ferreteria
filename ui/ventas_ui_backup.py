"""
Interfaz de Punto de Venta (POS)
"""
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from ui_config import COLORS, FONTS

class VentasUI:
    """Interfaz de Punto de Venta"""
    
    def __init__(self, parent, ventas_service, productos_repo, clientes_repo, auth):
        self.parent = parent
        self.ventas_service = ventas_service
        self.productos_repo = productos_repo
        self.clientes_repo = clientes_repo
        self.auth = auth
        
        # Carrito de compras
        self.carrito = []
        self.cliente_seleccionado = None
        
        self.crear_ui()
        self.cargar_productos()
    
    def crear_ui(self):
        """Crea la interfaz del POS"""
        # Header
        header = tk.Frame(self.parent, bg=COLORS['primary'], height=70)
        header.pack(fill='x')
        header.pack_propagate(False)
        
        tk.Label(header, text="💰 Punto de Venta",
                font=FONTS['xlarge'],
                bg=COLORS['primary'], fg='white').pack(side='left', padx=20)
        
        # Fecha y hora
        self.hora_label = tk.Label(header, text="",
                                   font=FONTS['body'],
                                   bg=COLORS['primary'], fg='white')
        self.hora_label.pack(side='right', padx=20)
        self.actualizar_hora()
        
        # Contenedor principal (2 columnas)
        main_container = tk.Frame(self.parent, bg=COLORS['bg_secondary'])
        main_container.pack(fill='both', expand=True, padx=10, pady=10)
        
        # COLUMNA IZQUIERDA - Búsqueda y productos
        left_frame = tk.Frame(main_container, bg=COLORS['bg_secondary'])
        left_frame.pack(side='left', fill='both', expand=True, padx=(0, 5))
        
        self.crear_seccion_busqueda(left_frame)
        self.crear_seccion_productos(left_frame)
        
        # COLUMNA DERECHA - Carrito y totales
        right_frame = tk.Frame(main_container, bg='white', width=450)
        right_frame.pack(side='right', fill='both', padx=(5, 0))
        right_frame.pack_propagate(False)
        
        self.crear_seccion_carrito(right_frame)
    
    def crear_seccion_busqueda(self, parent):
        """Crea la sección de búsqueda de productos"""
        search_frame = tk.Frame(parent, bg='white', relief='solid', borderwidth=1)
        search_frame.pack(fill='x', pady=(0, 10))
        
        # Título
        tk.Label(search_frame, text="🔍 Buscar Producto",
                font=FONTS['heading'],
                bg='white').pack(anchor='w', padx=15, pady=(10, 5))
        
        # Búsqueda por código o nombre
        search_container = tk.Frame(search_frame, bg='white')
        search_container.pack(fill='x', padx=15, pady=10)
        
        tk.Label(search_container, text="Código o Nombre:",
                font=FONTS['body'],
                bg='white').pack(anchor='w')
        
        self.search_var = tk.StringVar()
        self.search_var.trace('w', lambda *args: self.buscar_productos())
        
        search_entry = ttk.Entry(search_container, textvariable=self.search_var,
                                font=FONTS['large'])
        search_entry.pack(fill='x', pady=5)
        search_entry.focus()
        
        # Bind Enter para agregar rápido
        search_entry.bind('<Return>', self.agregar_por_codigo_rapido)
        
        # Filtro por categoría
        filter_frame = tk.Frame(search_frame, bg='white')
        filter_frame.pack(fill='x', padx=15, pady=(0, 10))
        
        tk.Label(filter_frame, text="Categoría:",
                font=FONTS['body'],
                bg='white').pack(side='left', padx=(0, 5))
        
        self.categoria_var = tk.StringVar(value="Todas")
        self.combo_categoria = ttk.Combobox(filter_frame,
                                           textvariable=self.categoria_var,
                                           width=20, state='readonly')
        self.combo_categoria.pack(side='left', padx=5)
        self.combo_categoria.bind('<<ComboboxSelected>>', lambda e: self.buscar_productos())
    
    def crear_seccion_productos(self, parent):
        """Crea la sección de lista de productos"""
        productos_frame = tk.Frame(parent, bg='white', relief='solid', borderwidth=1)
        productos_frame.pack(fill='both', expand=True)
        
        # Título
        tk.Label(productos_frame, text="📦 Productos Disponibles",
                font=FONTS['heading'],
                bg='white').pack(anchor='w', padx=15, pady=(10, 5))
        
        # Tabla de productos
        table_container = tk.Frame(productos_frame, bg='white')
        table_container.pack(fill='both', expand=True, padx=15, pady=(0, 10))
        
        # Scrollbars
        scroll_y = ttk.Scrollbar(table_container, orient='vertical')
        scroll_y.pack(side='right', fill='y')
        
        # Treeview
        columnas = ('Código', 'Nombre', 'Precio', 'Stock')
        
        self.tree_productos = ttk.Treeview(table_container, columns=columnas,
                                          show='headings', height=15,
                                          yscrollcommand=scroll_y.set)
        
        scroll_y.config(command=self.tree_productos.yview)
        
        # Configurar columnas
        anchos = {'Código': 120, 'Nombre': 300, 'Precio': 100, 'Stock': 80}
        
        for col in columnas:
            self.tree_productos.heading(col, text=col)
            self.tree_productos.column(col, width=anchos.get(col, 100))
        
        self.tree_productos.pack(fill='both', expand=True)
        
        # Doble clic para agregar
        self.tree_productos.bind('<Double-1>', lambda e: self.agregar_producto_seleccionado())
        
        # Botón agregar
        tk.Button(productos_frame, text="➕ Agregar al Carrito",
                 font=FONTS['body_bold'],
                 bg=COLORS['primary'], fg='white',
                 cursor='hand2', relief='flat',
                 command=self.agregar_producto_seleccionado).pack(pady=10, ipadx=20, ipady=8)
    
    def crear_seccion_carrito(self, parent):
        """Crea la sección del carrito de compras"""
        # Título y cliente
        header = tk.Frame(parent, bg=COLORS['info'])
        header.pack(fill='x')
        
        tk.Label(header, text="🛒 Carrito de Compras",
                font=FONTS['heading'],
                bg=COLORS['info'], fg='white').pack(pady=10)
        
        # Selección de cliente
        cliente_frame = tk.Frame(parent, bg='white')
        cliente_frame.pack(fill='x', padx=15, pady=10)
        
        tk.Label(cliente_frame, text="Cliente:",
                font=FONTS['body_bold'],
                bg='white').pack(anchor='w')
        
        cliente_container = tk.Frame(cliente_frame, bg='white')
        cliente_container.pack(fill='x', pady=5)
        
        self.cliente_label = tk.Label(cliente_container, 
                                      text="Cliente General",
                                      font=FONTS['body'],
                                      bg='white',
                                      fg=COLORS['text_secondary'],
                                      anchor='w')
        self.cliente_label.pack(side='left', fill='x', expand=True)
        
        tk.Button(cliente_container, text="👤 Seleccionar",
                 font=FONTS['body'],
                 bg=COLORS['secondary'], fg='white',
                 cursor='hand2', relief='flat',
                 command=self.seleccionar_cliente).pack(side='right')
        
        # Lista de productos en el carrito
        ttk.Separator(parent, orient='horizontal').pack(fill='x', padx=15, pady=10)
        
        carrito_container = tk.Frame(parent, bg='white')
        carrito_container.pack(fill='both', expand=True, padx=15)
        
        # Scrollbar
        scroll_y = ttk.Scrollbar(carrito_container, orient='vertical')
        scroll_y.pack(side='right', fill='y')
        
        # Treeview del carrito
        columnas = ('Producto', 'Cant.', 'Precio', 'Total')
        
        self.tree_carrito = ttk.Treeview(carrito_container, columns=columnas,
                                        show='headings', height=8,
                                        yscrollcommand=scroll_y.set)
        
        scroll_y.config(command=self.tree_carrito.yview)
        
        # Configurar columnas
        self.tree_carrito.heading('Producto', text='Producto')
        self.tree_carrito.heading('Cant.', text='Cant.')
        self.tree_carrito.heading('Precio', text='Precio')
        self.tree_carrito.heading('Total', text='Total')
        
        self.tree_carrito.column('Producto', width=180)
        self.tree_carrito.column('Cant.', width=60)
        self.tree_carrito.column('Precio', width=80)
        self.tree_carrito.column('Total', width=80)
        
        self.tree_carrito.pack(fill='both', expand=True)
        
        # Botones de carrito
        btn_carrito_frame = tk.Frame(parent, bg='white')
        btn_carrito_frame.pack(fill='x', padx=15, pady=10)
        
        tk.Button(btn_carrito_frame, text="✏️ Editar",
                 font=FONTS['body'],
                 bg=COLORS['secondary'], fg='white',
                 cursor='hand2', relief='flat',
                 command=self.editar_item_carrito).pack(side='left', padx=5)
        
        tk.Button(btn_carrito_frame, text="🗑️ Quitar",
                 font=FONTS['body'],
                 bg=COLORS['danger'], fg='white',
                 cursor='hand2', relief='flat',
                 command=self.quitar_del_carrito).pack(side='left', padx=5)
        
        tk.Button(btn_carrito_frame, text="🗑️ Limpiar Todo",
                 font=FONTS['body'],
                 bg=COLORS['danger'], fg='white',
                 cursor='hand2', relief='flat',
                 command=self.limpiar_carrito).pack(side='right', padx=5)
        
        # Totales
        ttk.Separator(parent, orient='horizontal').pack(fill='x', padx=15, pady=10)
        
        totales_frame = tk.Frame(parent, bg='white')
        totales_frame.pack(fill='x', padx=15, pady=10)
        
        # Subtotal
        row = tk.Frame(totales_frame, bg='white')
        row.pack(fill='x', pady=3)
        tk.Label(row, text="Subtotal:", font=FONTS['body'],
                bg='white').pack(side='left')
        self.subtotal_label = tk.Label(row, text="$0",
                                       font=FONTS['body_bold'],
                                       bg='white')
        self.subtotal_label.pack(side='right')
        
        # Descuento
        row = tk.Frame(totales_frame, bg='white')
        row.pack(fill='x', pady=3)
        tk.Label(row, text="Descuento:", font=FONTS['body'],
                bg='white').pack(side='left')
        
        desc_container = tk.Frame(row, bg='white')
        desc_container.pack(side='right')
        
        self.descuento_var = tk.StringVar(value="0")
        self.descuento_entry = ttk.Entry(desc_container, textvariable=self.descuento_var,
                                        width=8, font=FONTS['body'])
        self.descuento_entry.pack(side='left')
        self.descuento_var.trace('w', lambda *args: self.calcular_totales())
        
        tk.Label(desc_container, text="%", font=FONTS['body'],
                bg='white').pack(side='left', padx=5)
        
        # IVA
        row = tk.Frame(totales_frame, bg='white')
        row.pack(fill='x', pady=3)
        tk.Label(row, text="IVA:", font=FONTS['body'],
                bg='white').pack(side='left')
        self.iva_label = tk.Label(row, text="$0",
                                  font=FONTS['body'],
                                  bg='white')
        self.iva_label.pack(side='right')
        
        # Total
        ttk.Separator(totales_frame, orient='horizontal').pack(fill='x', pady=5)
        
        row = tk.Frame(totales_frame, bg='white')
        row.pack(fill='x', pady=5)
        tk.Label(row, text="TOTAL:", font=FONTS['large'],
                bg='white', fg=COLORS['primary']).pack(side='left')
        self.total_label = tk.Label(row, text="$0",
                                    font=FONTS['xlarge'],
                                    bg='white', fg=COLORS['primary'])
        self.total_label.pack(side='right')
        
        # Método de pago
        ttk.Separator(parent, orient='horizontal').pack(fill='x', padx=15, pady=10)
        
        pago_frame = tk.Frame(parent, bg='white')
        pago_frame.pack(fill='x', padx=15, pady=10)
        
        tk.Label(pago_frame, text="Método de Pago:",
                font=FONTS['body_bold'],
                bg='white').pack(anchor='w')
        
        self.metodo_pago_var = tk.StringVar(value="EFECTIVO")
        metodos = ['EFECTIVO', 'TARJETA_DEBITO', 'TARJETA_CREDITO', 
                  'TRANSFERENCIA', 'NEQUI', 'CREDITO']
        
        for metodo in metodos:
            nombre = metodo.replace('_', ' ').title()
            tk.Radiobutton(pago_frame, text=nombre,
                          variable=self.metodo_pago_var,
                          value=metodo,
                          font=FONTS['body'],
                          bg='white').pack(anchor='w')
        
        # Botones finales
        btn_final_frame = tk.Frame(parent, bg='white')
        btn_final_frame.pack(fill='x', padx=15, pady=15)
        
        tk.Button(btn_final_frame, text="[GUARDAR] Procesar Venta",
                 font=FONTS['body_bold'],
                 bg=COLORS['success'], fg='white',
                 cursor='hand2', relief='flat',
                 command=self.procesar_venta).pack(fill='x', ipady=15)
        
        tk.Button(btn_final_frame, text="[ERROR] Cancelar",
                 font=FONTS['body'],
                 bg=COLORS['danger'], fg='white',
                 cursor='hand2', relief='flat',
                 command=self.cancelar_venta).pack(fill='x', pady=(10, 0), ipady=10)
    
    def actualizar_hora(self):
        """Actualiza la hora en el header"""
        ahora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        self.hora_label.config(text=ahora)
        self.parent.after(1000, self.actualizar_hora)
    
    def cargar_productos(self):
        """Carga la lista de productos"""
        try:
            # [OK] CORREGIDO: Método correcto es listar_productos()
            productos = self.productos_repo.listar_productos(solo_activos=True)
            self.productos_data = productos
            
            # Cargar categorías
            categorias = ['Todas'] + self.productos_repo.obtener_categorias()
            self.combo_categoria['values'] = categorias
            
            self.mostrar_productos(productos)
            
        except Exception as e:
            messagebox.showerror("Error", f"Error al cargar productos: {str(e)}")
    
    def mostrar_productos(self, productos):
        """Muestra productos en la tabla"""
        # Limpiar
        for item in self.tree_productos.get_children():
            self.tree_productos.delete(item)

        # [OK] CORREGIDO: productos son diccionarios, no objetos
        for prod in productos:
            if prod.get('activo', True) and prod.get('stock', 0) > 0:
                self.tree_productos.insert('', 'end', values=(
                    prod.get('codigo_barras') or prod.get('id'),
                    prod.get('nombre', ''),
                    f"${prod.get('precio_venta', 0):,.0f}",
                    prod.get('stock', 0)
                ), tags=(str(prod.get('id')),))
    
    def buscar_productos(self):
        """Busca y filtra productos"""
        busqueda = self.search_var.get().lower()
        categoria = self.categoria_var.get()

        if not hasattr(self, 'productos_data'):
            return

        productos_filtrados = []

        # [OK] CORREGIDO: productos son diccionarios
        for prod in self.productos_data:
            if not prod.get('activo', True) or prod.get('stock', 0) <= 0:
                continue

            # Filtro de búsqueda
            nombre = prod.get('nombre', '').lower()
            codigo = (prod.get('codigo_barras') or '').lower()

            if busqueda and not (busqueda in nombre or busqueda in codigo):
                continue

            # Filtro de categoría
            if categoria != "Todas" and prod.get('categoria') != categoria:
                continue

            productos_filtrados.append(prod)

        self.mostrar_productos(productos_filtrados)
    
    def agregar_por_codigo_rapido(self, event):
        """Agrega producto por código al presionar Enter"""
        codigo = self.search_var.get().strip()

        if not codigo:
            return

        # [OK] CORREGIDO: Método correcto es obtener_por_codigo()
        producto = self.productos_repo.obtener_por_codigo(codigo)

        if not producto:
            # Intentar buscar por ID
            try:
                # [OK] CORREGIDO: Método correcto es obtener_por_id()
                producto = self.productos_repo.obtener_por_id(int(codigo))
            except:
                pass

        if producto:
            self.agregar_al_carrito(producto)
            self.search_var.set("")
        else:
            messagebox.showwarning("No encontrado",
                                 f"No se encontró producto con código: {codigo}")
    
    def agregar_producto_seleccionado(self):
        """Agrega el producto seleccionado al carrito"""
        seleccion = self.tree_productos.selection()

        if not seleccion:
            messagebox.showwarning("Advertencia", "Seleccione un producto")
            return

        # Obtener ID del producto desde tags
        item = self.tree_productos.item(seleccion[0])
        producto_id = int(item['tags'][0])

        # [OK] CORREGIDO: Método correcto es obtener_por_id()
        producto = self.productos_repo.obtener_por_id(producto_id)

        if producto:
            self.agregar_al_carrito(producto)
    
    def agregar_al_carrito(self, producto, cantidad=1):
        """Agrega un producto al carrito"""
        # [OK] CORREGIDO: producto es un diccionario
        stock_disponible = producto.get('stock', 0)
        producto_id = producto.get('id')

        # Verificar stock
        if stock_disponible < cantidad:
            messagebox.showwarning("Stock insuficiente",
                                f"Solo hay {stock_disponible} unidades disponibles")
            return

        # Verificar si ya está en el carrito
        for item in self.carrito:
            if item['producto']['id'] == producto_id:
                # Actualizar cantidad
                nueva_cantidad = item['cantidad'] + cantidad

                if stock_disponible < nueva_cantidad:
                    messagebox.showwarning("Stock insuficiente",
                                        f"Solo hay {stock_disponible} unidades disponibles")
                    return

                item['cantidad'] = nueva_cantidad
                self.actualizar_carrito_ui()
                return

        # Agregar nuevo item
        self.carrito.append({
            'producto': producto,
            'cantidad': cantidad,
            'precio_unitario': producto.get('precio_venta', 0),
            'descuento': 0
        })

        self.actualizar_carrito_ui()
    def actualizar_carrito_ui(self):
        """Actualiza la visualización del carrito"""
        # Limpiar
        for item in self.tree_carrito.get_children():
            self.tree_carrito.delete(item)

        # [OK] CORREGIDO: producto es un diccionario
        for idx, item in enumerate(self.carrito):
            producto = item['producto']
            cantidad = item['cantidad']
            precio = item['precio_unitario']
            total = cantidad * precio

            self.tree_carrito.insert('', 'end', values=(
                producto.get('nombre', '')[:25],
                cantidad,
                f"${precio:,.0f}",
                f"${total:,.0f}"
            ), tags=(str(idx),))

        self.calcular_totales()
    
    def calcular_totales(self):
        """Calcula y muestra los totales"""
        subtotal = sum(item['cantidad'] * item['precio_unitario'] for item in self.carrito)

        # Descuento
        try:
            descuento_porcentaje = float(self.descuento_var.get() or 0)
            descuento_monto = subtotal * (descuento_porcentaje / 100)
        except:
            descuento_monto = 0
            self.descuento_var.set("0")

        # Subtotal después de descuento
        subtotal_con_desc = subtotal - descuento_monto

        # [OK] CORREGIDO: producto es un diccionario
        iva_monto = 0
        for item in self.carrito:
            producto = item['producto']
            subtotal_item = item['cantidad'] * item['precio_unitario']
            iva_monto += subtotal_item * producto.get('iva', 0.19)

        # Ajustar IVA por descuento
        if subtotal > 0:
            iva_monto = iva_monto * (subtotal_con_desc / subtotal)

        # Total
        total = subtotal_con_desc + iva_monto

        # Actualizar labels
        self.subtotal_label.config(text=f"${subtotal:,.0f}")
        self.iva_label.config(text=f"${iva_monto:,.0f}")
        self.total_label.config(text=f"${total:,.0f}")
    
    def editar_item_carrito(self):
        """Edita la cantidad de un item del carrito"""
        seleccion = self.tree_carrito.selection()
        
        if not seleccion:
            messagebox.showwarning("Advertencia", "Seleccione un producto del carrito")
            return
        
        # Obtener índice
        item = self.tree_carrito.item(seleccion[0])
        idx = int(item['tags'][0])
        
        item_carrito = self.carrito[idx]
        
        # Ventana para editar cantidad
        VentanaEditarCantidad(self.parent, item_carrito, 
                             callback=self.actualizar_carrito_ui)
    
    def quitar_del_carrito(self):
        """Quita un item del carrito"""
        seleccion = self.tree_carrito.selection()
        
        if not seleccion:
            messagebox.showwarning("Advertencia", "Seleccione un producto del carrito")
            return
        
        # Obtener índice
        item = self.tree_carrito.item(seleccion[0])
        idx = int(item['tags'][0])
        
        # Confirmar
        producto_nombre = self.carrito[idx]['producto'].nombre
        
        respuesta = messagebox.askyesno("Confirmar",
                                        f"¿Quitar {producto_nombre} del carrito?")
        
        if respuesta:
            del self.carrito[idx]
            self.actualizar_carrito_ui()
    
    def limpiar_carrito(self):
        """Limpia todo el carrito"""
        if not self.carrito:
            return
        
        respuesta = messagebox.askyesno("Confirmar",
                                        "¿Limpiar todo el carrito?")
        
        if respuesta:
            self.carrito = []
            self.actualizar_carrito_ui()
    
    def seleccionar_cliente(self):
        """Abre ventana para seleccionar cliente"""
        VentanaSeleccionarCliente(self.parent, self.clientes_repo,
                                 callback=self.asignar_cliente)
    
    def asignar_cliente(self, cliente):
        """Asigna un cliente a la venta"""
        self.cliente_seleccionado = cliente
        self.cliente_label.config(text=f"👤 {cliente.nombre}",
                                 fg=COLORS['primary'])
        
        # Aplicar descuento del cliente si tiene
        if cliente.descuento_default > 0:
            self.descuento_var.set(str(cliente.descuento_default))
    
    def procesar_venta(self):
        """Procesa la venta"""
        if not self.carrito:
            messagebox.showwarning("Carrito vacío", "Agregue productos al carrito")
            return
        
        try:
            # Preparar datos
            cliente_id = self.cliente_seleccionado.id if self.cliente_seleccionado else None
            metodo_pago = self.metodo_pago_var.get()
            
            try:
                descuento = float(self.descuento_var.get() or 0)
            except:
                descuento = 0
            
            # [OK] CORREGIDO: producto es un diccionario
            items = []
            for item in self.carrito:
                items.append({
                    'producto_id': item['producto']['id'],
                    'cantidad': item['cantidad'],
                    'precio_unitario': item['precio_unitario'],
                    'descuento': item.get('descuento', 0)
                })
            
            # Procesar venta
            exito, mensaje, venta = self.ventas_service.registrar_venta(
                items=items,
                cliente_id=cliente_id,
                metodo_pago=metodo_pago,
                descuento_general=descuento
            )
            
            if exito:
                # Mostrar resumen
                mensaje_resumen = f"""
Venta procesada exitosamente

Factura: {venta.numero_factura}
Total: ${venta.total:,.0f}
Método: {metodo_pago.replace('_', ' ')}

¿Desea imprimir el recibo?
"""
                
                respuesta = messagebox.askyesno("Venta Exitosa", mensaje_resumen)
                
                if respuesta:
                    self.imprimir_recibo(venta)
                
                # Limpiar para nueva venta
                self.nueva_venta()
            else:
                messagebox.showerror("Error", mensaje)
                
        except Exception as e:
            messagebox.showerror("Error", f"Error al procesar venta: {str(e)}")
    
    def imprimir_recibo(self, venta):
        """Muestra el recibo de la venta"""
        VentanaRecibo(self.parent, venta, self.cliente_seleccionado)
    
    def cancelar_venta(self):
        """Cancela la venta actual"""
        if self.carrito:
            respuesta = messagebox.askyesno("Confirmar",
                                           "¿Cancelar la venta actual?")
            if respuesta:
                self.nueva_venta()
        else:
            self.nueva_venta()
    
    def nueva_venta(self):
        """Prepara el sistema para una nueva venta"""
        self.carrito = []
        self.cliente_seleccionado = None
        self.cliente_label.config(text="Cliente General",
                                 fg=COLORS['text_secondary'])
        self.descuento_var.set("0")
        self.metodo_pago_var.set("EFECTIVO")
        self.search_var.set("")
        self.actualizar_carrito_ui()
        self.cargar_productos()


class VentanaEditarCantidad:
    """Ventana para editar cantidad de un producto en el carrito"""
    
    def __init__(self, parent, item_carrito, callback=None):
        self.item = item_carrito
        self.callback = callback
        
        self.ventana = tk.Toplevel(parent)
        self.ventana.title("Editar Cantidad")
        self.ventana.geometry("400x250")
        self.ventana.configure(bg=COLORS['bg_primary'])
        self.ventana.transient(parent)
        self.ventana.grab_set()
        
        self.crear_ui()
    
    def crear_ui(self):
        """Crea la interfaz"""
        # Header
        header = tk.Frame(self.ventana, bg=COLORS['primary'], height=60)
        header.pack(fill='x')
        header.pack_propagate(False)
        
        tk.Label(header, text="✏️ Editar Cantidad",
                font=FONTS['large'],
                bg=COLORS['primary'], fg='white').pack(pady=15)
        
        # Contenido
        content = tk.Frame(self.ventana, bg=COLORS['bg_primary'])
        content.pack(fill='both', expand=True, padx=30, pady=20)
        
        # Producto
        tk.Label(content, text=f"Producto: {self.item['producto'].nombre}",
                font=FONTS['body_bold'],
                bg=COLORS['bg_primary']).pack(anchor='w', pady=5)
        
        tk.Label(content, text=f"Stock disponible: {self.item['producto'].stock}",
                font=FONTS['body'],
                bg=COLORS['bg_primary'],
                fg=COLORS['text_secondary']).pack(anchor='w', pady=5)
        
        # Cantidad
        tk.Label(content, text="Nueva Cantidad:",
                font=FONTS['body_bold'],
                bg=COLORS['bg_primary']).pack(anchor='w', pady=(20, 5))
        
        self.cantidad_var = tk.StringVar(value=str(self.item['cantidad']))
        entry = ttk.Entry(content, textvariable=self.cantidad_var,
                         font=FONTS['xlarge'], justify='center')
        entry.pack(fill='x', pady=5)
        entry.focus()
        entry.select_range(0, 'end')
        
        # Botones
        btn_frame = tk.Frame(content, bg=COLORS['bg_primary'])
        btn_frame.pack(fill='x', pady=20)
        
        tk.Button(btn_frame, text="[GUARDAR] Guardar",
                 font=FONTS['body_bold'],
                 bg=COLORS['success'], fg='white',
                 cursor='hand2', relief='flat',
                 command=self.guardar).pack(side='left', padx=5, ipadx=20, ipady=10)
        
        tk.Button(btn_frame, text="[ERROR] Cancelar",
                 font=FONTS['body'],
                 bg=COLORS['danger'], fg='white',
                 cursor='hand2', relief='flat',
                 command=self.ventana.destroy).pack(side='left', padx=5, ipadx=20, ipady=10)
        
        # Bind Enter
        entry.bind('<Return>', lambda e: self.guardar())
    
    def guardar(self):
        """Guarda la nueva cantidad"""
        try:
            cantidad = int(self.cantidad_var.get())
            
            if cantidad <= 0:
                messagebox.showwarning("Advertencia", "La cantidad debe ser mayor a 0")
                return
            
            if cantidad > self.item['producto'].stock:
                messagebox.showwarning("Stock insuficiente",
                                     f"Solo hay {self.item['producto'].stock} unidades disponibles")
                return
            
            self.item['cantidad'] = cantidad
            
            if self.callback:
                self.callback()
            
            self.ventana.destroy()
            
        except ValueError:
            messagebox.showerror("Error", "Ingrese una cantidad válida")


class VentanaSeleccionarCliente:
    """Ventana para seleccionar un cliente"""
    
    def __init__(self, parent, clientes_repo, callback=None):
        self.repo = clientes_repo
        self.callback = callback
        
        self.ventana = tk.Toplevel(parent)
        self.ventana.title("Seleccionar Cliente")
        self.ventana.geometry("700x500")
        self.ventana.configure(bg=COLORS['bg_primary'])
        self.ventana.transient(parent)
        self.ventana.grab_set()
        
        self.crear_ui()
        self.cargar_clientes()
    
    def crear_ui(self):
        """Crea la interfaz"""
        # Header
        header = tk.Frame(self.ventana, bg=COLORS['primary'], height=60)
        header.pack(fill='x')
        header.pack_propagate(False)
        
        tk.Label(header, text="👤 Seleccionar Cliente",
                font=FONTS['large'],
                bg=COLORS['primary'], fg='white').pack(pady=15)
        
        # Búsqueda
        search_frame = tk.Frame(self.ventana, bg=COLORS['bg_primary'])
        search_frame.pack(fill='x', padx=20, pady=10)
        
        tk.Label(search_frame, text="Buscar:",
                font=FONTS['body'],
                bg=COLORS['bg_primary']).pack(side='left', padx=5)
        
        self.search_var = tk.StringVar()
        self.search_var.trace('w', lambda *args: self.filtrar_clientes())
        
        ttk.Entry(search_frame, textvariable=self.search_var,
                 font=FONTS['body'], width=40).pack(side='left', padx=5)
        
        # Tabla
        table_frame = tk.Frame(self.ventana, bg='white')
        table_frame.pack(fill='both', expand=True, padx=20, pady=10)
        
        scroll_y = ttk.Scrollbar(table_frame, orient='vertical')
        scroll_y.pack(side='right', fill='y')
        
        columnas = ('ID', 'Documento', 'Nombre', 'Teléfono', 'Clasificación')
        
        self.tree = ttk.Treeview(table_frame, columns=columnas,
                                show='headings',
                                yscrollcommand=scroll_y.set)
        
        scroll_y.config(command=self.tree.yview)
        
        for col in columnas:
            self.tree.heading(col, text=col)
        
        self.tree.column('ID', width=50)
        self.tree.column('Documento', width=120)
        self.tree.column('Nombre', width=250)
        self.tree.column('Teléfono', width=120)
        self.tree.column('Clasificación', width=100)
        
        self.tree.pack(fill='both', expand=True)
        
        # Doble clic para seleccionar
        self.tree.bind('<Double-1>', lambda e: self.seleccionar())
        
        # Botones
        btn_frame = tk.Frame(self.ventana, bg=COLORS['bg_primary'])
        btn_frame.pack(fill='x', padx=20, pady=10)
        
        tk.Button(btn_frame, text="[OK] Seleccionar",
                 font=FONTS['body_bold'],
                 bg=COLORS['success'], fg='white',
                 cursor='hand2', relief='flat',
                 command=self.seleccionar).pack(side='left', padx=5, ipadx=20, ipady=10)
        
        tk.Button(btn_frame, text="[ERROR] Cancelar",
                 font=FONTS['body'],
                 bg=COLORS['danger'], fg='white',
                 cursor='hand2', relief='flat',
                 command=self.ventana.destroy).pack(side='left', padx=5, ipadx=20, ipady=10)
    
    def cargar_clientes(self):
        """Carga los clientes"""
        try:
            clientes = self.repo.listar_todos()
            self.clientes_data = clientes
            
            for cliente in clientes:
                self.tree.insert('', 'end', values=(
                    cliente.id,
                    cliente.numero_documento,
                    cliente.nombre,
                    cliente.telefono or 'N/A',
                    cliente.clasificacion
                ), tags=(str(cliente.id),))
                
        except Exception as e:
            messagebox.showerror("Error", f"Error al cargar clientes: {str(e)}")
    
    def filtrar_clientes(self):
        """Filtra clientes por búsqueda"""
        busqueda = self.search_var.get().lower()
        
        # Limpiar
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        if not hasattr(self, 'clientes_data'):
            return
        
        # Filtrar
        for cliente in self.clientes_data:
            if (busqueda in cliente.nombre.lower() or
                busqueda in cliente.numero_documento.lower()):
                
                self.tree.insert('', 'end', values=(
                    cliente.id,
                    cliente.numero_documento,
                    cliente.nombre,
                    cliente.telefono or 'N/A',
                    cliente.clasificacion
                ), tags=(str(cliente.id),))
    
    def seleccionar(self):
        """Selecciona el cliente"""
        seleccion = self.tree.selection()
        
        if not seleccion:
            messagebox.showwarning("Advertencia", "Seleccione un cliente")
            return
        
        # Obtener ID
        item = self.tree.item(seleccion[0])
        cliente_id = int(item['tags'][0])
        
        cliente = self.repo.buscar_por_id(cliente_id)
        
        if cliente and self.callback:
            self.callback(cliente)
        
        self.ventana.destroy()


class VentanaRecibo:
    """Ventana para mostrar el recibo de venta"""
    
    def __init__(self, parent, venta, cliente=None):
        self.venta = venta
        self.cliente = cliente
        
        self.ventana = tk.Toplevel(parent)
        self.ventana.title(f"Recibo - {venta.numero_factura}")
        self.ventana.geometry("600x700")
        self.ventana.configure(bg='white')
        self.ventana.transient(parent)
        
        self.crear_ui()
    
    def crear_ui(self):
        """Crea la interfaz del recibo"""
        # Contenido
        content = tk.Frame(self.ventana, bg='white')
        content.pack(fill='both', expand=True, padx=30, pady=30)
        
        # Header
        tk.Label(content, text="🏪 FERRETERÍA",
                font=FONTS['xlarge'],
                bg='white').pack(pady=10)
        
        tk.Label(content, text="RECIBO DE VENTA",
                font=FONTS['heading'],
                bg='white').pack(pady=5)
        
        ttk.Separator(content, orient='horizontal').pack(fill='x', pady=15)
        
        # Información de la venta
        info = [
            ("Factura:", self.venta.numero_factura),
            ("Fecha:", datetime.now().strftime("%d/%m/%Y %H:%M")),
            ("Cliente:", self.cliente.nombre if self.cliente else "Cliente General"),
            ("Método de Pago:", self.venta.metodo_pago.replace('_', ' ')),
        ]
        
        for label, valor in info:
            row = tk.Frame(content, bg='white')
            row.pack(fill='x', pady=3)
            
            tk.Label(row, text=label, font=FONTS['body'],
                    bg='white', anchor='w', width=15).pack(side='left')
            tk.Label(row, text=valor, font=FONTS['body_bold'],
                    bg='white', anchor='w').pack(side='left')
        
        ttk.Separator(content, orient='horizontal').pack(fill='x', pady=15)
        
        # Detalles de productos
        tk.Label(content, text="DETALLE DE PRODUCTOS",
                font=FONTS['body_bold'],
                bg='white').pack(anchor='w', pady=10)
        
        # Aquí normalmente cargarías los detalles desde la BD
        # Por ahora mostramos solo el resumen
        
        ttk.Separator(content, orient='horizontal').pack(fill='x', pady=15)
        
        # Totales
        totales = [
            ("Subtotal:", f"${self.venta.subtotal:,.0f}"),
            ("Descuento:", f"${self.venta.descuento:,.0f}"),
            ("IVA:", f"${self.venta.iva:,.0f}"),
        ]
        
        for label, valor in totales:
            row = tk.Frame(content, bg='white')
            row.pack(fill='x', pady=3)
            
            tk.Label(row, text=label, font=FONTS['body'],
                    bg='white').pack(side='left')
            tk.Label(row, text=valor, font=FONTS['body'],
                    bg='white').pack(side='right')
        
        ttk.Separator(content, orient='horizontal').pack(fill='x', pady=10)
        
        # Total
        total_frame = tk.Frame(content, bg='white')
        total_frame.pack(fill='x', pady=10)
        
        tk.Label(total_frame, text="TOTAL:", font=FONTS['large'],
                bg='white', fg=COLORS['primary']).pack(side='left')
        tk.Label(total_frame, text=f"${self.venta.total:,.0f}",
                font=FONTS['xlarge'],
                bg='white', fg=COLORS['primary']).pack(side='right')
        
        ttk.Separator(content, orient='horizontal').pack(fill='x', pady=15)
        
        # Mensaje
        tk.Label(content, text="¡Gracias por su compra!",
                font=FONTS['heading'],
                bg='white').pack(pady=20)
        
        # Botones
        btn_frame = tk.Frame(content, bg='white')
        btn_frame.pack(fill='x', pady=10)
        
        tk.Button(btn_frame, text="🖨️ Imprimir",
                 font=FONTS['body_bold'],
                 bg=COLORS['primary'], fg='white',
                 cursor='hand2', relief='flat',
                 command=self.imprimir).pack(side='left', padx=5, ipadx=20, ipady=10)
        
        tk.Button(btn_frame, text="[OK] Cerrar",
                 font=FONTS['body'],
                 bg=COLORS['success'], fg='white',
                 cursor='hand2', relief='flat',
                 command=self.ventana.destroy).pack(side='right', padx=5, ipadx=20, ipady=10)
    
    def imprimir(self):
        """Simula impresión del recibo"""
        messagebox.showinfo("Imprimir", "Función de impresión no implementada")