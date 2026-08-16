# Prueba manual DigitalPOS DIG-X6266

**Software HID:** CERTIFIED por tests automatizados.
**Equipo físico DIG-X6266:** PENDING HUMAN TEST.

Usar exclusivamente una base y un producto de prueba. No seleccionar productos
comerciales; esta prueba no debe cambiar stock.

## Checklist interactivo

- [ ] **A.** Conectar el DIG-X6266 por USB en modo HID Keyboard Wedge, con
  terminador ENTER.
- [ ] **B.** Abrir **Regularizar barcodes → Prueba de scanner** y enfocar el
  campo de captura.
- [ ] **C.** Escanear un producto. Verificar el barcode exacto, el terminador
  detectado y los ceros iniciales si aplica. Confirmar que el primer scan queda
  en `WAITING_CONFIRMATION` y no persiste.
- [ ] **D.** Escanear el mismo barcode otra vez. Verificar `MATCH`.
- [ ] **E.** Reiniciar la prueba y escanear dos códigos diferentes. Verificar
  `MISMATCH` y 0 persistencia en `product_barcodes`.
- [ ] **F.** En **Regularización continua**, seleccionar un PRODUCTO DE PRUEBA
  seguro. Escanear el mismo código dos veces y verificar
  `PERSISTENCE_VERIFIED` después del segundo scan.
- [ ] **G.** Reabrir o recargar la pantalla. Verificar que el barcode permanece
  asociado al producto de prueba y que el producto ya no aparece en pending.

Registrar además que el modo de prueba produjo 0 INSERT/UPDATE y que un
mismatch o barcode duplicado no avanza al siguiente producto.

No declarar el hardware certificado hasta completar y registrar esta prueba
con el DIG-X6266 físico.
