# Script para detectar compras con estado PENDIENTE pero saldo_pendiente <= 0
import sqlite3

db_path = 'ferreteria.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute('''
SELECT id, numero_factura, total, estado_pago, monto_pagado, saldo_pendiente
FROM compras
WHERE estado_pago = 'PENDIENTE' AND (saldo_pendiente IS NULL OR saldo_pendiente <= 0)
''')
rows = cursor.fetchall()

print(f"Compras inconsistentes encontradas: {len(rows)}")
for r in rows:
    comp_id, num_fact, total, estado, monto_pagado, saldo = r
    print('-'*60)
    print(f"ID: {comp_id} | Factura: {num_fact} | Total: {total} | estado: {estado}")
    print(f"monto_pagado: {monto_pagado} | saldo_pendiente: {saldo}")
    # obtener abonos
    cursor.execute('SELECT id, monto_abono, fecha_abono FROM abonos_compras WHERE id_compra = ?', (comp_id,))
    abonos = cursor.fetchall()
    if abonos:
        print(' Abonos:')
        for a in abonos:
            print('  ', a)
    else:
        print(' No hay abonos registrados')

conn.close()
