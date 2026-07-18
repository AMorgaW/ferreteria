---
name: ferrepro-ui-design
description: Skill potente para mejorar interfaces visuales UI/UX de FERREPRO en PySide/PyQt, manteniendo identidad visual, consistencia profesional, moneda COP y evitando tocar lógica de negocio.
---

# FERREPRO UI Design

Usar esta skill exclusivamente para mejoras visuales UI/UX en FERREPRO, especialmente en diálogos de detalle, pantallas de movimientos, ventanas modales, tablas, cards, formularios, dashboards, reportes visuales, interfaces PySide/PyQt, organización visual de información, jerarquía visual, espaciado y diseño profesional.

No usar esta skill para cambios de lógica de negocio, base de datos, sincronización, Supabase, UUID/local_id, SKU, autenticación, permisos, cálculos del sistema ni empaquetado, salvo que el usuario lo pida explícitamente.

## Identidad Visual

Mantener la identidad visual existente de FERREPRO:

- Usar azul navy / azul oscuro como color principal.
- Usar naranja/dorado como color de acento.
- Usar fondo blanco o gris muy claro para contenido.
- Usar tarjetas blancas compactas.
- Usar bordes suaves y sombras sutiles.
- Mantener un diseño empresarial, limpio y profesional.
- Evitar estilos futuristas que no combinen con el sistema actual.
- Evitar interfaces recargadas.
- Evitar cambios que hagan parecer la app como un producto completamente diferente.

## Principios UI/UX Obligatorios

- Priorizar claridad.
- Priorizar lectura rápida.
- Reducir espacios muertos.
- Evitar encabezados gigantes.
- Evitar tarjetas enormes con poco contenido.
- Mantener jerarquía visual clara.
- Agrupar información relacionada.
- Usar colores con intención.
- Hacer visible lo importante primero.
- Usar tablas limpias y compactas.
- Usar scroll interno cuando la información sea larga.
- Mantener botones principales visibles.
- No saturar la pantalla.
- Mantener consistencia entre módulos.

## Layout

- Usar encabezados compactos.
- Usar cards superiores pequeñas para metadata.
- Diseñar secciones financieras compactas.
- Dar buen espacio horizontal a las tablas.
- Alinear columnas de forma consistente.
- Usar etiquetas claras.
- Destacar valores monetarios sin sobredimensionarlos.
- Usar historiales tipo timeline cuando existan abonos o pagos.
- Usar secciones colapsadas o detalles bajo doble click cuando haya demasiada información.
- Evitar que los diálogos ocupen espacio innecesario.

## Moneda

FERREPRO usa pesos colombianos.

- Usar siempre COP.
- Nunca usar MXN.
- Nunca usar USD salvo que el usuario lo pida.
- Usar formato recomendado: `$60.000 COP`, `$700.000 COP`, `$1.000.000 COP`.
- Reutilizar cualquier función existente de formato monetario del proyecto antes de crear otra.

## Colores Semánticos

- Azul navy: estructura, encabezados y botones principales.
- Naranja/dorado: acentos, parciales, advertencias suaves y compras.
- Verde: pagado, completado y positivo.
- Rojo/naranja fuerte: pendiente, deuda y alerta.
- Gris claro: fondos secundarios.
- Blanco: cards y zonas de lectura.

## Diálogos de Detalle

Para diálogos abiertos desde Movimientos, seguir una estructura visual compacta y consistente. Mostrar solo datos reales disponibles.

### Detalle de entrada / compra

Incluir, si los datos existen:

- Encabezado compacto.
- Título: `Entrada de inventario #<factura>`.
- Factura.
- Fecha.
- Proveedor.
- Usuario.
- Total compra.
- Pagado acumulado.
- Saldo pendiente.
- Estado de pago.
- Tabla de productos con Producto, Marca, Cantidad, Precio unit. y Subtotal.
- Historial de abonos con fecha, valor, método, comprobante, usuario y saldo si se puede calcular.
- Observaciones si existen.
- Botón Cerrar.

### Detalle de salida / venta

Incluir, si los datos existen:

- Encabezado compacto.
- Título: `Salida de inventario #<factura>`.
- Factura.
- Fecha.
- Cliente.
- Usuario/cajero.
- Total venta.
- Monto pagado.
- Saldo pendiente.
- Estado de pago.
- Método de pago.
- Tabla de productos con Producto, Marca, Cantidad, Precio unit. y Subtotal.
- Observaciones si existen.
- Botón Cerrar.
- Botón imprimir solo si ya existe función real.

### Detalle de egreso de caja

Seguir el mismo estilo visual de entrada y salida. Incluir, si los datos existen:

- Encabezado compacto.
- Título: `Egreso de caja #<id>` o `Salida de caja #<id>`.
- Fecha.
- Categoría.
- Valor.
- Método de pago.
- Usuario.
- Comprobante.
- Descripción.
- Si es pago a proveedor: proveedor, compra asociada, factura, abono relacionado, valor pagado, fecha del abono y método de pago.
- Botón Cerrar.

## Tablas

- Usar tablas compactas.
- Usar encabezado de tabla azul navy.
- Usar filas alternadas suaves si ya se usa ese estilo.
- Alinear números a la derecha.
- Alinear texto a la izquierda.
- Mostrar moneda en COP.
- Si falta marca, mostrar `-` o `Sin marca`.
- No inventar productos ni marcas.
- No usar datos falsos.

## Cards

- Usar cards pequeñas para metadata.
- Usar cards financieras más destacadas, pero compactas.
- Evitar cards gigantes.
- Usar iconos simples si ya existe un patrón de iconos.
- No agregar iconos que rompan el estilo.
- Mantener espaciado uniforme.

## Botones

- Usar botón principal azul navy.
- Usar botón secundario claro.
- Usar botones con texto claro.
- No crear botones sin funcionalidad.
- Mantener Cerrar visible.
- No agregar acciones nuevas si no están implementadas.

## Seguridad Funcional

Cuando la tarea sea visual:

- Preferir modificar solo archivos `ui/*`.
- Usar `services/*` solo si hace falta traer datos para mostrar.
- No modificar repositories salvo autorización explícita.
- No modificar base de datos.
- No modificar lógica de caja.
- No modificar lógica de compras.
- No modificar lógica de ventas.
- No modificar inventario.
- No modificar sincronización.
- No modificar Supabase.
- No modificar UUID/local_id.
- No modificar SKU.
- No modificar autenticación.
- No modificar permisos.
- No modificar PyInstaller salvo que la tarea sea de empaquetado.
- No cambiar cálculos existentes.
- No cambiar flujos ya validados.

## Datos

- No inventar información.
- Si falta un dato, mostrar `-`, `No registrado` o `Sin marca`.
- No hardcodear valores de prueba.
- No dejar MXN.
- No dejar textos falsos.
- No dejar logs de debug.
- No dejar código muerto.

## Validación Después de Cambios UI

Después de cualquier cambio visual, validar:

- Ejecutar `python -m py_compile` sobre archivos modificados.
- Confirmar que la ventana o diálogo abre.
- Confirmar que no aparece MXN.
- Confirmar que se usa COP.
- Confirmar que no se rompió doble click.
- Confirmar que los filtros siguen funcionando si se tocó Movimientos.
- Confirmar que ventas siguen visibles.
- Confirmar que compras siguen visibles.
- Confirmar que egresos siguen visibles.
- Confirmar que caja no fue afectada.
- Confirmar que no se modificó lógica de negocio.
- Si se modifica UI del ejecutable, reconstruir `dist/Ferreteria/Ferreteria.exe`.

## Informe Final Estándar

Al finalizar una tarea que use esta skill, entregar siempre:

- Archivos modificados.
- Cambios visuales realizados.
- Confirmación de que solo se tocó UI o explicación si se tocó `services/*`.
- Confirmación de que no se tocó lógica de negocio.
- Confirmación de que se usa COP.
- Confirmación de que no aparece MXN.
- Confirmación de que no se rompieron ventas, compras, egresos, caja ni filtros.
- Confirmación de que el ejecutable quedó en `dist/Ferreteria/Ferreteria.exe`, si aplica.
