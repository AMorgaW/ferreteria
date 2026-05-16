# Script para recalcular y reparar saldos en la tabla compras
import sqlite3

db_path = 'ferreteria.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    # Asegurarse de que monto_pagado no sea NULL
    cursor.execute("UPDATE compras SET monto_pagado = 0 WHERE monto_pagado IS NULL")
    conn.commit()

    # Recalcular monto_pagado sumando abonos
    cursor.execute('''
        SELECT c.id, c.total, COALESCE(SUM(a.monto_abono), 0) as total_abonos
        FROM compras c
        LEFT JOIN abonos_compras a ON a.id_compra = c.id
        GROUP BY c.id
    ''')
    rows = cursor.fetchall()

    for comp_id, total, total_abonos in rows:
        nuevo_pagado = total_abonos or 0
        nuevo_saldo = total - nuevo_pagado
        if nuevo_saldo < 0:
            nuevo_saldo = 0
        # Actualizar
        cursor.execute('''
            UPDATE compras
            SET monto_pagado = ?, saldo_pendiente = ?, estado_pago = ?
            WHERE id = ?
        ''', (nuevo_pagado, nuevo_saldo, 'PAGADO' if nuevo_pagado >= total else ('PARCIAL' if nuevo_pagado > 0 else 'PENDIENTE'), comp_id))

    conn.commit()
    print('Reparacion completada')

finally:
    conn.close()
