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
- [ ] DIG-X6266 physical PASS
- [ ] backup operativo preparado
- [ ] usuario autoriza ejecución real

## Evidencia técnica ya certificada

- Cola DB-derived reconstruible tras restart; mismatch no persiste.
- Persistencia solo después de segundo scan y read-back exacto.
- Ceros iniciales y case preservados.
- Barcodes secundarios y `FULL_PACKAGE` resuelven el mismo producto/stock.
- Candidate Excel permanece como referencia y FRP exige acción explícita.
- SQLite y PostgreSQL de laboratorio validados; Supabase real no fue tocado.

**Ready para inventario real hoy:** NO. Fase 2 está completa a nivel software,
pero falta la prueba física DIG-X6266 y los gates operacionales de este
checklist. El inventario comercial todavía NO ha sido ejecutado.
