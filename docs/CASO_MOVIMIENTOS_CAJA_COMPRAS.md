# Caso técnico y funcional: Movimientos, Caja y Compras en FERREPRO

## 1. Resumen ejecutivo

FERREPRO es un sistema de inventario y gestión administrativa para ferreterías. Durante la revisión del flujo de compras, ventas, caja y movimientos se identificaron oportunidades para mejorar la trazabilidad de las operaciones y la claridad con que se presentan a los usuarios.

La situación afectaba principalmente la consulta de compras y ventas en **Movimientos**, el seguimiento de pagos o abonos a proveedores y la evidencia de estos pagos como egresos de caja. También se detectaron oportunidades de mejora en la lectura de tablas y detalles operativos.

La solución del caso se orientó a reforzar la relación visual y funcional entre operaciones de inventario, pagos y caja; compactar la información principal; y dejar los detalles completos disponibles bajo consulta. El resultado esperado es una operación más clara para el personal administrativo, con mejor trazabilidad de compras, ventas, saldos y salidas de dinero.

## 2. Contexto del sistema

FERREPRO es una aplicación de escritorio para la gestión integral de una ferretería. Sus módulos cubren, entre otros, los siguientes procesos:

- Productos e inventario.
- Proveedores.
- Compras.
- Ventas.
- Caja.
- Movimientos.
- Reportes.
- Usuarios.
- Sincronización local-first.

El sistema conserva su operación principal en una base de datos SQLite local y cuenta con integración con Supabase para la sincronización. Esta arquitectura permite continuar trabajando localmente y conservar el mecanismo de sincronización definido por el sistema.

El ejecutable oficial de escritorio se distribuye desde la siguiente ruta:

`dist/Ferreteria/Ferreteria.exe`

## 3. Problema inicial identificado

La revisión del caso evidenció necesidades de mejora en la trazabilidad y presentación de la información operativa:

- Las compras y ventas no siempre se visualizaban correctamente en el módulo de Movimientos.
- Los pagos o abonos a proveedores no siempre se reflejaban de forma clara como salidas de caja.
- En Caja no siempre era evidente el egreso asociado a un pago a proveedor.
- En Movimientos podía aparecer información incompleta, repetida o mezclada entre conceptos.
- Algunas columnas podían mostrar datos que no correspondían a la expectativa del encabezado; por ejemplo, un método de pago en una columna percibida como proveedor.
- La interfaz de detalle era funcional, pero ofrecía poca jerarquía visual y desaprovechaba espacio útil.

## 4. Impacto del problema

Estas situaciones podían afectar la operación administrativa y el control diario de la empresa:

- Dificultaban la auditoría de entradas y salidas de inventario y dinero.
- Reducían la claridad sobre los pagos realizados a proveedores.
- Podían generar confusión entre una compra, un abono y un egreso de caja.
- Hacían más difícil validar el comportamiento de caja durante una jornada o cierre.
- Incrementaban el riesgo de errores administrativos al interpretar registros incompletos o duplicados.
- Disminuían la confianza en los reportes operativos.
- Exigían más tiempo de revisión manual para relacionar facturas, pagos y movimientos.

## 5. Hallazgos técnicos y funcionales

### 5.1 Compras

- Las compras generan una entrada de inventario.
- Una compra puede registrar pago inicial, pagos parciales o permanecer pendiente de pago.
- Para su lectura administrativa es necesario distinguir total, valor pagado, saldo y estado de la compra.

### 5.2 Ventas

- Las ventas generan una salida de inventario.
- Las ventas pueden ser de contado o a crédito.
- Su consulta debe permitir identificar cliente, productos, total, valor pagado, saldo y estado.

### 5.3 Pagos a proveedor

- Los pagos a proveedor deben reflejarse como egresos reales de caja.
- Un abono a proveedor debe poder asociarse con la compra o factura correspondiente.
- Es importante conservar una referencia del pago para facilitar su consulta y auditoría.

### 5.4 Caja

- Caja debe reflejar los egresos generados por pagos a proveedor.
- El cierre de caja debe considerar ventas, ingresos y egresos registrados.
- Es esencial evitar doble descuento o registros duplicados al relacionar una operación con caja.

### 5.5 Movimientos

- Movimientos debe funcionar como una vista de trazabilidad general de entradas, salidas, pagos y egresos.
- La tabla principal debe conservar una lectura compacta y ordenada.
- La información completa debe estar disponible mediante doble click sobre el registro correspondiente.
- No es conveniente mostrar demasiadas columnas en la tabla principal, porque se pierde legibilidad y se mezclan conceptos.

### 5.6 Interfaz

- Los diálogos anteriores mostraban la información requerida, pero tenían poco aprovechamiento del espacio disponible.
- Se necesitaba un diseño más profesional, compacto y consistente entre módulos.
- Se definió una identidad visual basada en azul navy, naranja o dorado de marca, tarjetas limpias y presentación monetaria en pesos colombianos (COP).

## 6. Solución implementada

### 6.1 Registro correcto de pagos a proveedor

- Los pagos a proveedor se reflejan como egresos de caja.
- Los abonos quedan relacionados con la compra correspondiente.
- La consulta de caja puede mostrar salidas reales asociadas a pagos de proveedor.

### 6.2 Mejora de Movimientos

- Movimientos presenta entradas, salidas, egresos y pagos relacionados de forma trazable.
- Se ajustó la presentación para evitar que la información se perciba mezclada entre tipos de operación.
- La tabla principal se compactó para priorizar los datos necesarios para una revisión rápida.
- La información completa se consulta desde el detalle mediante doble click.

### 6.3 Mejora de detalles

- El detalle de entrada permite consultar compra, proveedor, productos, marca, total, pagado, saldo e historial de abonos.
- El detalle de salida permite consultar venta, cliente, productos, marca, total, pagado, saldo y método de pago.
- El detalle de egreso permite consultar valor, categoría, método, comprobante y referencia de pago cuando aplique.

### 6.4 Mejora visual

- Encabezados más compactos y fáciles de recorrer.
- Tarjetas y contenedores más limpios.
- Menos espacios muertos en vistas de detalle.
- Tablas con columna de marca cuando corresponde al contexto del producto.
- Formato monetario en COP.
- Estilo visual consistente entre consultas, tablas y diálogos.

### 6.5 Manejo visual de créditos

- Los créditos pendientes se pueden identificar visualmente.
- Las compras y ventas con saldo pendiente se resaltan para facilitar el seguimiento.
- Los abonos recientes permiten evidenciar actividad sobre una factura.
- Cuando un crédito queda pagado, deja de mostrarse como pendiente.

## 7. Archivos o módulos involucrados

El caso se relaciona con los siguientes archivos y módulos del sistema:

- `ui/movimientos_ui.py`
- `services/movimientos_service.py`
- `repositories/compras_repo.py`
- `repositories/abonos_compras_repo.py`
- `services/caja_service.py`
- Módulos de ventas.
- Módulos de compras.
- Módulo de caja.
- Base local SQLite.
- Ejecutable `dist/Ferreteria/Ferreteria.exe`.

Esta lista describe el alcance funcional y técnico del caso completo. No implica que todos estos archivos o módulos hayan sido modificados en una misma intervención o en la última intervención realizada.

## 8. Validaciones realizadas

Para comprobar la consistencia del flujo y de su presentación, el caso contempla las siguientes validaciones:

- Compra con pago inicial.
- Compra pendiente de pago.
- Compra con pago parcial.
- Abono posterior a proveedor.
- Egreso manual.
- Venta de contado.
- Venta a crédito.
- Visualización de entradas, salidas y egresos en Movimientos.
- Apertura de detalle mediante doble click.
- Caja reflejando egresos por pagos a proveedor.
- Presentación de valores en COP.
- Ausencia de referencias monetarias en MXN.
- Comprobación de sintaxis mediante `py_compile` dentro del proceso técnico de validación.
- Construcción y verificación del ejecutable oficial en modo `onedir` como validación de entrega cuando corresponde al ciclo de publicación.

Las validaciones deben realizarse sin crear datos reales no autorizados y sin alterar la configuración de sincronización, persistencia ni servicios externos.

## 9. Beneficios para la empresa

### 9.1 Control operativo

- Mayor control sobre el inventario.
- Registro más claro de entradas y salidas.
- Mejor trazabilidad de compras y ventas.

### 9.2 Control financiero

- Caja más confiable para la consulta operativa.
- Egresos identificables y relacionados con su origen.
- Pagos a proveedor visibles.
- Mejor control de créditos y saldos pendientes.

### 9.3 Auditoría y trazabilidad

- Cada movimiento puede quedar registrado y consultable.
- El detalle completo por factura facilita relacionar la operación con sus pagos.
- Se reducen errores de lectura y consolidación manual.
- Se facilita la revisión administrativa de compras, ventas, caja y saldos.

### 9.4 Toma de decisiones

- Información más clara para administrar compras.
- Mejor visibilidad de deudas con proveedores.
- Mejor visibilidad de ventas pendientes de cobro.
- Mejor lectura del flujo de caja para apoyar decisiones operativas.

### 9.5 Productividad

- Menos tiempo buscando información en registros extensos.
- Menor dependencia de cálculos y cruces manuales.
- Interfaz más clara para usuarios administrativos.
- Menor probabilidad de confusión entre operaciones relacionadas.

### 9.6 Profesionalización del negocio

- Sistema más ordenado y consistente.
- Mejor presentación visual de la información administrativa.
- Procesos más formales y fáciles de seguir.
- Base más sólida para escalar a más sedes o usuarios cuando el negocio lo requiera.

## 10. Estado final del caso

- Movimientos quedó funcional y con una lectura más clara.
- Caja refleja los egresos asociados a pagos de proveedor.
- Compras y ventas se visualizan con mejor trazabilidad.
- Los detalles por doble click permiten consultar la información completa de cada operación.
- La interfaz fue compactada y mejorada para priorizar la lectura administrativa.
- Se mantiene la moneda COP en la presentación de valores.
- El ejecutable oficial permanece identificado como:

`dist/Ferreteria/Ferreteria.exe`

## 11. Recomendaciones futuras

- Mantener esta documentación actualizada ante cambios de proceso.
- Crear listas de pruebas manuales por módulo y por tipo de operación.
- Documentar de forma explícita las reglas de crédito, abonos y cierre de saldos.
- Continuar fortaleciendo los reportes financieros según las necesidades de administración.
- Evaluar exportación a Excel o PDF si el proceso administrativo lo requiere.
- Mantener respaldos de versiones estables antes de publicar cambios.
- No modificar lógica sensible sin validaciones previas, especialmente en caja, inventario, créditos y sincronización.
- Continuar utilizando la skill `ferrepro-ui-design` para futuras mejoras estrictamente visuales, preservando el comportamiento del sistema.

## 12. Conclusión

El caso de Movimientos, Caja y Compras fortalece el control operativo de FERREPRO al hacer más comprensible la relación entre inventario, compras, ventas, pagos a proveedor y egresos. La mejora de trazabilidad, la consulta detallada por operación y una interfaz más compacta ayudan a reducir ambigüedades en la gestión diaria.

Con ello, la empresa dispone de una base más confiable para revisar caja, controlar saldos, auditar operaciones y tomar decisiones administrativas con mejor contexto. El enfoque preserva la operación local-first, la persistencia existente y la integración con Supabase, mientras mejora la calidad de uso y presentación del sistema.
