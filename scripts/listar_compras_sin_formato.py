# Script para listar compras mostrando valores crudos
import sqlite3

db_path = 'ferreteria.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute('''
SELECT id, numero_factura, total, estado_pago, monto_pagado, saldo_pendiente
FROM compras
ORDER BY fecha DESC
LIMIT 10
''')
rows = cursor.fetchall()
for r in rows:
    print(r)

conn.close()
