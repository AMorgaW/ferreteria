# Checklist previo a inventario real

Cada gate pendiente debe completarse con el archivo y los servicios reales de
la operación controlada. Los PASS de fixtures no sustituyen esa verificación.

- [ ] Excel final disponible
- [ ] XLSX validator PASS
- [ ] staging PASS
- [ ] matching reviewed
- [ ] dry-run reviewed
- [x] apply engine certified
- [ ] authoritative inventory reachable
- [x] barcode queue works
- [x] double scan PASS
- [x] DIG-X6266 physical PASS
- [x] LOCAL-FIRST responsiveness physical PASS
- [x] startup y navegación offline PASS
- [x] reconnect/sync background sin freeze PASS
- [ ] backup operativo preparado
- [ ] usuario autoriza ejecución real

## Evidencia técnica ya certificada

- Cola DB-derived reconstruible tras restart; mismatch no persiste.
- Persistencia solo después de segundo scan y read-back exacto.
- Ceros iniciales y case preservados.
- Barcodes secundarios y `FULL_PACKAGE` resuelven el mismo producto/stock.
- Candidate Excel permanece como referencia y FRP exige acción explícita.
- SQLite y PostgreSQL de laboratorio validados; Supabase real no fue tocado.
- DIG-X6266, HID y doble escaneo validados físicamente: PASS.
- Startup online/offline, navegación local y reconexión validados físicamente:
  PASS; no se observó “Python no responde”.

**Ready para inventario real hoy:** NO. Fase 2 está completa a nivel
software/operacional, incluido DIG-X6266 y local-first responsiveness, pero
siguen pendientes los demás gates operacionales de este checklist. El
inventario comercial todavía NO ha sido ejecutado.
