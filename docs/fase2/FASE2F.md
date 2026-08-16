# Fase 2F — regularización operacional de barcodes

**Estado técnico:** completa. **Inventario comercial aplicado:** no.

Fase 2F agrega la pantalla **Productos sin código de barras**, cuya cola se
reconstruye desde SQLite y staging. Implementa filtros, búsqueda, doble scan,
read-back obligatorio, avance continuo, barcodes secundarios, PRIMARY
explícito, `package_role`, FRP confirmado y prueba HID sin persistencia.

## Gate

| Propiedad | Resultado |
|---|---|
| Cola/restart sin duplicados | PASS |
| Doble scan/mismatch sin escritura | PASS |
| Read-back y ceros iniciales | PASS |
| Modo continuo | PASS |
| Múltiples barcodes/PRIMARY | PASS |
| `package_role` SQLite/PostgreSQL | PASS |
| FRP explícito | PASS |
| Scanner test: 0 persistencia | PASS |
| DIG-X6266 físico | PENDING HUMAN TEST |

No se importó XLSX comercial, no se modificó stock, no se usó Supabase real y
no se aplicó inventario real.
