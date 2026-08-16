# Scanner HID — DigitalPOS DIG-X6266

## Contrato

Configuración inicial: USB HID Keyboard Wedge. No se instala SDK propietario ni
se abre puerto serial/COM. Solo una prueba física que demuestre que HID no
funciona justificaría revisar esa decisión.

`HidBarcodeScanner` recibe caracteres, acumula el buffer y emite únicamente al
detectar CR, LF, `ENTER` o `RETURN`. CRLF se interpreta como un solo terminador.
Los dígitos no se ejecutan como atajos ni comandos. Un ENTER sin contenido se
rechaza y `reset()` vacía el buffer de forma segura.

## Doble escaneo

```text
WAITING_FIRST_SCAN
  -> scan A -> WAITING_CONFIRMATION
  -> scan A -> VERIFIED
  -> persist -> reread DB -> PERSISTENCE_VERIFIED
```

Si el segundo valor es distinto, el resultado visible es `MISMATCH` /
`CÓDIGOS NO COINCIDEN`, no se llama al repository y ambos intentos se borran.
El tercer scan se convierte en el nuevo primer scan.

La UI distingue:

- primer scan capturado;
- verificado en memoria;
- persistido;
- `GUARDADO Y VERIFICADO`, único éxito completo.

## Plan manual DIG-X6266

Esta prueba no modifica stock y debe hacerse sobre una base temporal o producto
de laboratorio:

1. Conectar el DIG-X6266 por USB.
2. Abrir Productos y enfocar el campo del scanner.
3. Escanear un barcode y comprobar `Primer scan capturado`.
4. Verificar que solicita `Escanee nuevamente para verificar`.
5. Escanear el mismo barcode por segunda vez.
6. Comprobar `VERIFICADO`, aún pendiente de DB.
7. Guardar y confirmar `GUARDADO Y VERIFICADO`; reabrir el producto y verificar
   que aparece en códigos activos.
8. Reiniciar y hacer mismatch deliberado con dos códigos diferentes; comprobar
   que no existe fila nueva.
9. Probar una muestra con cero inicial y verificar el valor exacto tras reabrir.
10. Intentar un barcode ya asignado a otro producto; comprobar el mensaje con
    el nombre del propietario y ausencia de reasignación.

Para CI, `tests/fase2c/test_double_scan.py` simula el teclado carácter por
carácter; no requiere hardware.

