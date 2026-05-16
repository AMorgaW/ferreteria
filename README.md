# Sistema de Inventario - Ferretería Profesional

Aplicación de escritorio para gestión integral de una ferretería. Desarrollada en **Python + PySide6** con base de datos local **SQLite** y sincronización en la nube con **Supabase (PostgreSQL)**.

---

## Tabla de Contenidos

- [Requisitos](#requisitos)
- [Instalación y Ejecución](#instalación-y-ejecución)
- [Estructura del Proyecto](#estructura-del-proyecto)
- [Módulos Principales](#módulos-principales)
- [Base de Datos](#base-de-datos)
- [Roles y Permisos](#roles-y-permisos)
- [Sincronización con Supabase](#sincronización-con-supabase)
- [Credenciales por Defecto](#credenciales-por-defecto)

---

## Requisitos

- Python 3.10+
- PySide6
- psycopg2 (para sync con Supabase)

Instalar dependencias:

```bash
pip install PySide6 psycopg2-binary
```

---

## Instalación y Ejecución

```bash
# Opción 1: ejecutable bat
run.bat

# Opción 2: directo con Python
python main.py
```

Al primer inicio se crea automáticamente el archivo `ferreteria.db` con toda la estructura de tablas y los usuarios por defecto.

---

## Estructura del Proyecto

```
ferreteria 3.0/
│
├── main.py                  # Punto de entrada, ventana principal y login
├── database.py              # Gestor de base de datos SQLite, crea todas las tablas
├── models.py                # Dataclasses y enums del dominio (Producto, Cliente, etc.)
├── auth.py                  # Autenticación, sesiones y auditoría
├── ui_config.py             # Paleta de colores, fuentes y estilos globales (QSS)
├── sync_supabase.py         # Hilo de sincronización SQLite → Supabase (cada 30 min)
├── pg_compat.py             # Capa de compatibilidad PostgreSQL/SQLite
├── unidades_venta_manager.py # Gestión de unidades de venta (cajas, medias cajas, unidades)
│
├── repositories/            # Capa de acceso a datos (patrón Repository)
│   ├── productos_repo.py
│   ├── clientes_repo.py
│   ├── proveedores_repo.py
│   ├── compras_repo.py
│   ├── inventario_repository.py
│   ├── abonos_compras_repo.py
│   └── abonos_ventas_repo.py
│
├── services/                # Lógica de negocio
│   ├── ventas_service.py
│   ├── caja_service.py
│   ├── alertas_service.py
│   ├── reportes_service.py
│   ├── reportes_compras_service.py
│   ├── movimientos_service.py
│   ├── deudas_service.py
│   ├── cuentas_por_cobrar_service.py
│   └── mezclas_service.py
│
├── ui/                      # Interfaces gráficas por módulo
│   ├── dashboard_ui.py
│   ├── productos_ui.py
│   ├── clientes_ui.py
│   ├── proveedores_ui.py
│   ├── compras_ui.py
│   ├── ventas_ui_modern.py
│   ├── movimientos_ui.py
│   ├── caja_ui.py
│   ├── reportes_ui.py
│   ├── alertas_ui.py
│   ├── usuarios_ui.py
│   ├── mezcla_ui.py
│   ├── buscar_producto_dialog.py
│   ├── buscar_proveedor_dialog.py
│   ├── entrada_inventario_ui.py
│   ├── imprimir_factura.py
│   └── widgets.py           # Componentes reutilizables (HoverButton, etc.)
│
├── respaldos/               # Backups automáticos de la base de datos
├── scripts/                 # Scripts utilitarios de mantenimiento
└── ferreteria.db            # Base de datos SQLite (se crea al primer inicio)
```

---

## Módulos Principales

### Dashboard
Vista general con métricas del negocio: ventas del día, productos con stock crítico, cuentas por cobrar pendientes y resumen de caja. Genera archivos `stock_critico_YYYYMMDD_HHmmss.txt` cuando detecta productos bajo el mínimo.

### Productos
CRUD completo de productos. Soporta:
- Categorías configurables
- Control de stock mínimo con alertas automáticas
- Unidades de venta: por unidad, media caja o caja completa
- Cantidades decimales (ej. metros, kilos)

### Clientes
Gestión de clientes con historial de compras a crédito y abonos. Incluye módulo de **Cuentas por Cobrar** con seguimiento de saldo pendiente.

### Proveedores
CRUD de proveedores. Vinculados a compras y al sistema de deudas.

### Compras
Registro de órdenes de compra con:
- Selección de método de pago (contado o crédito)
- Pago inicial parcial
- Sistema de deudas y abonos a proveedores
- Actualización automática de stock al registrar la compra

### Ventas
Módulo principal de punto de venta:
- Búsqueda rápida de productos por nombre o código
- Carrito de compras con cantidades decimales
- Venta por caja / media caja / unidad
- Métodos de pago: efectivo, tarjeta, transferencia, Nequi, Daviplata, crédito
- Emisión de factura imprimible
- Integración con **Mezclas** (productos compuestos)
- Signal `venta_completada` que actualiza la Caja en tiempo real

### Movimientos
Registro de todos los movimientos de inventario (entradas, salidas, ajustes, mermas). Vista agrupada por factura/compra con detalle expandible.

### Caja
Resumen del turno actual: ingresos por ventas, egresos, saldo inicial y cierre de caja. Se sincroniza automáticamente cuando se completa una venta.

### Reportes
Reportes de ventas y compras con filtros por fecha, proveedor o producto. Exportables.

### Alertas
Sistema automático de alertas:
- Stock por debajo del mínimo
- Cuentas por cobrar vencidas
- Verificaciones diarias al iniciar la aplicación
- Popup de alertas importantes al arrancar

### Usuarios
Gestión de cuentas de usuario: crear, editar, activar/desactivar. Solo visible para el rol Administrador.

### Mezclas
Gestión de fórmulas de productos mezclados o compuestos (ej. pinturas, morteros). Define ingredientes y proporciones.

---

## Base de Datos

SQLite local (`ferreteria.db`). Tablas principales:

| Tabla | Descripción |
|---|---|
| `usuarios` | Cuentas de acceso al sistema |
| `productos` | Catálogo de productos |
| `categorias_config` | Categorías de productos |
| `clientes` | Clientes registrados |
| `proveedores` | Proveedores |
| `ventas` | Cabecera de ventas |
| `detalle_ventas` | Líneas de cada venta |
| `compras` | Órdenes de compra |
| `detalle_compras` | Líneas de cada compra |
| `movimientos_inventario` | Historial de movimientos de stock |
| `cuentas_por_cobrar` | Deudas de clientes |
| `pagos_cuentas` | Abonos a cuentas por cobrar |
| `abonos_compras` | Abonos a deudas con proveedores |
| `abonos_ventas` | Abonos de ventas a crédito |
| `cierres_caja` | Cierres de turno de caja |
| `egresos_caja` | Salidas de efectivo de caja |
| `alertas` | Alertas del sistema |
| `auditoria` | Log de acciones de usuarios |
| `formulas_mezcla` | Fórmulas de productos compuestos |
| `formula_detalle` | Ingredientes de cada fórmula |
| `configuracion` | Parámetros del sistema |

La estructura completa se crea automáticamente al instanciar `DatabaseManager` si las tablas no existen.

---

## Roles y Permisos

| Rol | Permisos principales |
|---|---|
| **Administrador** | Acceso total: usuarios, configuración, todos los módulos |
| **Gerente** | Todos los módulos excepto gestión de usuarios |
| **Vendedor** | Ventas, clientes, caja, dashboard |
| **Bodeguero** | Productos, movimientos, inventario |
| **Contador** | Reportes, caja, cuentas por cobrar |

Los botones y módulos del menú lateral se ocultan automáticamente según el rol del usuario autenticado.

---

## Sincronización con Supabase

El sistema mantiene una copia en la nube usando Supabase (PostgreSQL). El módulo `sync_supabase.py` funciona así:

- Se ejecuta en un **hilo daemon** independiente al iniciar la app.
- Después de cada `commit()` en SQLite, programa un sync con debounce de **10 segundos** para agrupar cambios rápidos.
- Sync periódico forzado cada **30 minutos**.
- Las tablas se sincronizan en orden de dependencias de claves foráneas.
- Si Supabase no está disponible, el sistema sigue funcionando 100% en local.

Configuración de la conexión en `sync_supabase.py`:
```python
SUPABASE_URI = "postgresql://..."
INTERVALO_SEGUNDOS = 30 * 60
```

---

## Credenciales por Defecto

Se crean automáticamente al primer inicio:

| Usuario | Contraseña | Rol |
|---|---|---|
| `admin` | `admin123` | Administrador |
| `empleado` | `emp123` | Vendedor |

Se recomienda cambiar estas contraseñas desde el módulo **Usuarios** después del primer acceso.
