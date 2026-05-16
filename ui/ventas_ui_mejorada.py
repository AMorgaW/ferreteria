"""
Interfaz de Punto de Venta (POS) - VERSIÓN MEJORADA
Rediseño completo con mejor UX y funcionalidad
"""
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from datetime import datetime
from ui_config import COLORS, FONTS


class DialogoCantidad(tk.Toplevel):
    """Diálogo para ingresar cantidad de producto"""

    def __init__(self, parent, producto_nombre, stock_disponible):
        super().__init__(parent)
        self.title("Cantidad")
        self.cantidad = None
        self.stock_disponible = stock_disponible

        # Configurar ventana
        self.geometry("400x250")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        # Centrar ventana
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (400 // 2)
        y = (self.winfo_screenheight() // 2) - (250 // 2)
        self.geometry(f"+{x}+{y}")

        self.crear_ui(producto_nombre)

        # Focus en entrada
        self.entry_cantidad.focus()
        self.entry_cantidad.select_range(0, tk.END)

    def crear_ui(self, producto_nombre):
        """Crea la interfaz del diálogo"""
        # Frame principal
        main_frame = tk.Frame(self, bg='white', padx=20, pady=20)
        main_frame.pack(fill='both', expand=True)

        # Título
        tk.Label(main_frame, text="📦 Ingresar Cantidad",
                font=FONTS['heading'],
                bg='white').pack(pady=(0, 10))

        # Producto
        tk.Label(main_frame, text=f"Producto: {producto_nombre}",
                font=FONTS['body'],
                bg='white',
                fg=COLORS['text_secondary']).pack(pady=5)

        # Stock disponible
        tk.Label(main_frame, text=f"Stock disponible: {self.stock_disponible} unidades",
                font=FONTS['body'],
                bg='white',
                fg=COLORS['success']).pack(pady=5)

        # Entrada de cantidad
        tk.Label(main_frame, text="Cantidad:",
                font=FONTS['body_bold'],
                bg='white').pack(anchor='w', pady=(15, 5))

        self.entry_cantidad = tk.Entry(main_frame, font=FONTS['xlarge'],
                                       justify='center', width=10)
        self.entry_cantidad.pack(pady=5)
        self.entry_cantidad.insert(0, "1")
        self.entry_cantidad.bind('<Return>', lambda e: self.aceptar())
        self.entry_cantidad.bind('<KP_Enter>', lambda e: self.aceptar())

        # Botones rápidos
        btn_frame = tk.Frame(main_frame, bg='white')
        btn_frame.pack(pady=10)

        for cant in [1, 5, 10, 20]:
            tk.Button(btn_frame, text=str(cant),
                     font=FONTS['body'],
                     bg=COLORS['bg_secondary'],
                     cursor='hand2',
                     width=4,
                     command=lambda c=cant: self.establecer_cantidad(c)).pack(side='left', padx=3)

        # Botones de acción
        action_frame = tk.Frame(main_frame, bg='white')
        action_frame.pack(pady=(15, 0))

        tk.Button(action_frame, text="[OK] Aceptar",
                 font=FONTS['body_bold'],
                 bg=COLORS['success'], fg='white',
                 cursor='hand2', relief='flat',
                 width=12,
                 command=self.aceptar).pack(side='left', padx=5)

        tk.Button(action_frame, text="✗ Cancelar",
                 font=FONTS['body'],
                 bg=COLORS['danger'], fg='white',
                 cursor='hand2', relief='flat',
                 width=12,
                 command=self.cancelar).pack(side='left', padx=5)

    def establecer_cantidad(self, cantidad):
        """Establece una cantidad rápida"""
        self.entry_cantidad.delete(0, tk.END)
        self.entry_cantidad.insert(0, str(cantidad))
        self.entry_cantidad.focus()

    def aceptar(self):
        """Valida y acepta la cantidad"""
        try:
            cantidad = int(self.entry_cantidad.get())

            if cantidad <= 0:
                messagebox.showwarning("Cantidad inválida",
                                     "La cantidad debe ser mayor a 0",
                                     parent=self)
                return

            if cantidad > self.stock_disponible:
                messagebox.showwarning("Stock insuficiente",
                                     f"Solo hay {self.stock_disponible} unidades disponibles",
                                     parent=self)
                return

            self.cantidad = cantidad
            self.destroy()

        except ValueError:
            messagebox.showerror("Error",
                               "Ingrese una cantidad válida",
                               parent=self)

    def cancelar(self):
        """Cancela el diálogo"""
        self.cantidad = None
        self.destroy()


class VentasUI:
    """Interfaz de Punto de Venta MEJORADA"""

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

        # Doble clic para agregar CON cantidad
        self.tree_productos.bind('<Double-1>', lambda e: self.agregar_producto_con_cantidad())

        # [OK] MEJORADO: Botón agregar con cantidad
        tk.Button(productos_frame, text="➕ Agregar al Carrito (especificar cantidad)",
                 font=FONTS['body_bold'],
                 bg=COLORS['primary'], fg='white',
                 cursor='hand2', relief='flat',
                 command=self.agregar_producto_con_cantidad).pack(pady=10, ipadx=20, ipady=8)

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

        # [OK] MEJORADO: Botones esenciales solamente
        btn_carrito_frame = tk.Frame(parent, bg='white')
        btn_carrito_frame.pack(fill='x', padx=15, pady=10)

        tk.Button(btn_carrito_frame, text="✏️ Editar Cantidad",
                 font=FONTS['body'],
                 bg=COLORS['secondary'], fg='white',
                 cursor='hand2', relief='flat',
                 command=self.editar_cantidad_item).pack(side='left', padx=5)

        tk.Button(btn_carrito_frame, text="🗑️ Quitar",
                 font=FONTS['body'],
                 bg=COLORS['danger'], fg='white',
                 cursor='hand2', relief='flat',
                 command=self.quitar_del_carrito).pack(side='left', padx=5)

        # Totales
        self.crear_seccion_totales(parent)

        # Botones de acción final
        self.crear_botones_accion(parent)

    def crear_seccion_totales(self, parent):
        """Crea la sección de totales"""
        ttk.Separator(parent, orient='horizontal').pack(fill='x', padx=15, pady=10)

        totales_frame = tk.Frame(parent, bg='white')
        totales_frame.pack(fill='x', padx=15, pady=10)

        # Subtotal
        row1 = tk.Frame(totales_frame, bg='white')
        row1.pack(fill='x', pady=3)

        tk.Label(row1, text="Subtotal:",
                font=FONTS['body'],
                bg='white').pack(side='left')

        self.subtotal_label = tk.Label(row1, text="$0",
                                       font=FONTS['body_bold'],
                                       bg='white', anchor='e')
        self.subtotal_label.pack(side='right')

        # IVA
        row2 = tk.Frame(totales_frame, bg='white')
        row2.pack(fill='x', pady=3)

        tk.Label(row2, text="IVA (19%):",
                font=FONTS['body'],
                bg='white').pack(side='left')

        self.iva_label = tk.Label(row2, text="$0",
                                  font=FONTS['body'],
                                  bg='white', anchor='e')
        self.iva_label.pack(side='right')

        # Descuento
        row3 = tk.Frame(totales_frame, bg='white')
        row3.pack(fill='x', pady=3)

        tk.Label(row3, text="Descuento %:",
                font=FONTS['body'],
                bg='white').pack(side='left')

        self.descuento_var = tk.StringVar(value="0")
        self.descuento_var.trace('w', lambda *args: self.calcular_totales())

        tk.Entry(row3, textvariable=self.descuento_var,
                font=FONTS['body'], width=8,
                justify='right').pack(side='right')

        # Total
        ttk.Separator(totales_frame, orient='horizontal').pack(fill='x', pady=10)

        row4 = tk.Frame(totales_frame, bg='white')
        row4.pack(fill='x', pady=3)

        tk.Label(row4, text="TOTAL:",
                font=FONTS['large_bold'],
                bg='white', fg=COLORS['primary']).pack(side='left')

        self.total_label = tk.Label(row4, text="$0",
                                    font=FONTS['xlarge'],
                                    bg='white', fg=COLORS['primary'],
                                    anchor='e')
        self.total_label.pack(side='right')

    def crear_botones_accion(self, parent):
        """Crea los botones de acción final"""
        ttk.Separator(parent, orient='horizontal').pack(fill='x', padx=15, pady=10)

        # Método de pago
        pago_frame = tk.Frame(parent, bg='white')
        pago_frame.pack(fill='x', padx=15, pady=10)

        tk.Label(pago_frame, text="Método de Pago:",
                font=FONTS['body_bold'],
                bg='white').pack(anchor='w', pady=(0, 5))

        self.metodo_pago_var = tk.StringVar(value="EFECTIVO")

        metodos = [
            ("💵 Efectivo", "EFECTIVO"),
            ("💳 Tarjeta", "TARJETA"),
            ("🏦 Transferencia", "TRANSFERENCIA"),
            ("📝 Crédito", "CREDITO")
        ]

        for texto, valor in metodos:
            ttk.Radiobutton(pago_frame, text=texto,
                           variable=self.metodo_pago_var,
                           value=valor).pack(anchor='w', pady=2)

        # Botones principales
        btn_frame = tk.Frame(parent, bg='white')
        btn_frame.pack(fill='x', padx=15, pady=15)

        tk.Button(btn_frame, text="💰 PROCESAR VENTA",
                 font=FONTS['heading'],
                 bg=COLORS['success'], fg='white',
                 cursor='hand2', relief='flat',
                 height=2,
                 command=self.procesar_venta).pack(fill='x', pady=(0, 10))

        btn_actions = tk.Frame(btn_frame, bg='white')
        btn_actions.pack(fill='x')

        tk.Button(btn_actions, text="🗑️ Limpiar",
                 font=FONTS['body'],
                 bg=COLORS['danger'], fg='white',
                 cursor='hand2', relief='flat',
                 command=self.limpiar_carrito).pack(side='left', fill='x', expand=True, padx=(0, 5))

        tk.Button(btn_actions, text="✗ Cancelar",
                 font=FONTS['body'],
                 bg=COLORS['secondary'], fg='white',
                 cursor='hand2', relief='flat',
                 command=self.cancelar_venta).pack(side='right', fill='x', expand=True, padx=(5, 0))

    # ============================================
    # MÉTODOS DE FUNCIONALIDAD
    # ============================================

    def actualizar_hora(self):
        """Actualiza la hora en el header"""
        ahora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        self.hora_label.config(text=ahora)
        self.parent.after(1000, self.actualizar_hora)

    def cargar_productos(self):
        """Carga la lista de productos"""
        try:
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

        # Mostrar productos
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

        producto = self.productos_repo.obtener_por_codigo(codigo)

        if not producto:
            try:
                producto = self.productos_repo.obtener_por_id(int(codigo))
            except:
                pass

        if producto:
            self.mostrar_dialogo_cantidad_y_agregar(producto)
            self.search_var.set("")
        else:
            messagebox.showwarning("No encontrado",
                                 f"No se encontró producto con código: {codigo}")

    def agregar_producto_con_cantidad(self):
        """[OK] MEJORADO: Agrega el producto seleccionado con diálogo de cantidad"""
        seleccion = self.tree_productos.selection()

        if not seleccion:
            messagebox.showwarning("Advertencia", "Seleccione un producto")
            return

        # Obtener ID del producto desde tags
        item = self.tree_productos.item(seleccion[0])
        producto_id = int(item['tags'][0])

        producto = self.productos_repo.obtener_por_id(producto_id)

        if producto:
            self.mostrar_dialogo_cantidad_y_agregar(producto)

    def mostrar_dialogo_cantidad_y_agregar(self, producto):
        """[OK] NUEVO: Muestra diálogo para ingresar cantidad"""
        dialogo = DialogoCantidad(
            self.parent,
            producto.get('nombre', ''),
            producto.get('stock', 0)
        )
        self.parent.wait_window(dialogo)

        if dialogo.cantidad:
            self.agregar_al_carrito(producto, dialogo.cantidad)

    def agregar_al_carrito(self, producto, cantidad=1):
        """Agrega un producto al carrito"""
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

        # Insertar items
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

        # IVA
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

    def editar_cantidad_item(self):
        """[OK] MEJORADO: Edita la cantidad de un item del carrito"""
        seleccion = self.tree_carrito.selection()

        if not seleccion:
            messagebox.showwarning("Advertencia", "Seleccione un producto del carrito")
            return

        # Obtener índice
        item = self.tree_carrito.item(seleccion[0])
        idx = int(item['tags'][0])

        carrito_item = self.carrito[idx]
        producto = carrito_item['producto']

        # Mostrar diálogo de cantidad
        dialogo = DialogoCantidad(
            self.parent,
            producto.get('nombre', ''),
            producto.get('stock', 0)
        )
        self.parent.wait_window(dialogo)

        if dialogo.cantidad:
            carrito_item['cantidad'] = dialogo.cantidad
            self.actualizar_carrito_ui()

    def quitar_del_carrito(self):
        """Quita un producto del carrito"""
        seleccion = self.tree_carrito.selection()

        if not seleccion:
            messagebox.showwarning("Advertencia", "Seleccione un producto del carrito")
            return

        item = self.tree_carrito.item(seleccion[0])
        idx = int(item['tags'][0])

        del self.carrito[idx]
        self.actualizar_carrito_ui()

    def limpiar_carrito(self):
        """Limpia todo el carrito"""
        if self.carrito:
            respuesta = messagebox.askyesno("Confirmar",
                                           "¿Limpiar todo el carrito?")
            if respuesta:
                self.carrito = []
                self.actualizar_carrito_ui()

    def seleccionar_cliente(self):
        """Abre diálogo para seleccionar cliente"""
        # TODO: Implementar ventana de selección de cliente
        messagebox.showinfo("En desarrollo", "Funcionalidad de selección de cliente")

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

            # Preparar items
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

La venta ha sido registrada en Movimientos.
"""

                messagebox.showinfo("Venta Exitosa", mensaje_resumen)

                # Limpiar para nueva venta
                self.nueva_venta()

                # Recargar productos (stock actualizado)
                self.cargar_productos()
            else:
                messagebox.showerror("Error", mensaje)

        except Exception as e:
            messagebox.showerror("Error", f"Error al procesar venta: {str(e)}")

    def cancelar_venta(self):
        """Cancela la venta actual"""
        if self.carrito:
            respuesta = messagebox.askyesno("Confirmar",
                                           "¿Cancelar la venta actual?")
            if respuesta:
                self.nueva_venta()

    def nueva_venta(self):
        """Prepara el sistema para una nueva venta"""
        self.carrito = []
        self.cliente_seleccionado = None
        self.cliente_label.config(text="Cliente General",
                                 fg=COLORS['text_secondary'])
        self.descuento_var.set("0")
        self.metodo_pago_var.set("EFECTIVO")
        self.actualizar_carrito_ui()
        self.search_var.set("")
