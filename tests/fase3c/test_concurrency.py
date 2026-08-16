# -*- coding: utf-8 -*-
"""Concurrencia 3C: cupo retornable en ferrepro-pg-test."""
from __future__ import annotations

import sys
import threading
import unittest
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from returns_schema import (
    KIND_CUSTOMER_RETURN,
    KIND_SUPPLIER_RETURN,
    ORIGINAL_TIPO_COMPRA,
    ORIGINAL_TIPO_VENTA,
)
from tests.fase1d.pg_harness import insert_producto, postgres_available
from tests.fase1e.helpers import insert_usuario, seed_producto
from tests.fase1e1.helpers import ventas_service
from tests.fase1e3.helpers import app_factory, force_postgres_status, pin_env_db
from tests.fase1e4.helpers import prepare_pg
from tests.fase3c.helpers import assert_not_commercial_db, compras_service, phase3c_env, returns_service


@unittest.skipUnless(
    postgres_available(),
    "POSTGRES INTEGRATION opt-in: ferrepro-pg-test / FERREPRO_PG_TEST_DSN",
)
class ReturnsConcurrencyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_pg()
        from tests.fase1d.pg_harness import connect

        cls.admin = connect()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.admin.close()
        except Exception:
            pass

    def test_19_two_station_customer_return_race(self):
        from inventory_coordinator import InventoryCoordinatorClient
        from inventory_cutover import STATUS_AUTHORITATIVE, STATUS_CUTOVER_IN_PROGRESS

        lid = insert_producto(self.admin, stock=10)
        InventoryCoordinatorClient(self.admin).seed_balance(lid, 10000)
        force_postgres_status(self.admin, STATUS_CUTOVER_IN_PROGRESS)
        force_postgres_status(self.admin, STATUS_AUTHORITATIVE, epoch=1)

        with phase3c_env() as env_a:
            assert_not_commercial_db(env_a)
            pin_env_db(env_a)
            conn = env_a.connect()
            try:
                seed_producto(conn, env_a, stock=10, local_id=lid, codigo="RET-A")
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            vsvc = ventas_service(env_a)
            ok, msg, venta = vsvc.registrar_venta(
                items=[{"producto_id": 1, "cantidad": 1, "precio_unitario": 1000}],
                inventory_command_id=str(uuid.uuid4()),
                inventory_connection_factory=app_factory(),
            )
            self.assertTrue(ok, msg)
            sale_cmd = vsvc.last_inventory_command_id
            conn = env_a.connect()
            try:
                sale = dict(conn.execute("SELECT * FROM ventas WHERE id=?", (venta.id,)).fetchone())
                det = dict(
                    conn.execute(
                        "SELECT * FROM detalle_ventas WHERE venta_id=?", (venta.id,)
                    ).fetchone()
                )
            finally:
                conn.close()

        results = []
        barrier = threading.Barrier(2)

        def worker(env, label):
            pin_env_db(env)
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=10, local_id=lid, codigo=f"RET-{label}")
                insert_usuario(conn)
                conn.execute(
                    """
                    INSERT INTO ventas (
                        numero_factura, fecha, subtotal, descuento, iva, total,
                        metodo_pago, estado, local_id, inventory_command_id, usuario_id
                    ) VALUES (?, ?, ?, 0, 0, ?, 'EFECTIVO', 'COMPLETADA', ?, ?, 1)
                    """,
                    (
                        f"COPY-{label}",
                        sale["fecha"],
                        sale["total"],
                        sale["total"],
                        sale["local_id"],
                        sale_cmd,
                    ),
                )
                venta_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                conn.execute(
                    """
                    INSERT INTO detalle_ventas (
                        venta_id, producto_id, cantidad, precio_unitario, descuento, subtotal
                    ) VALUES (?, 1, ?, ?, 0, ?)
                    """,
                    (venta_id, det["cantidad"], det["precio_unitario"], det["subtotal"]),
                )
                conn.commit()
            finally:
                conn.close()
            svc = returns_service(env)
            ok_d, msg_d, rid = svc.guardar_borrador(
                kind=KIND_CUSTOMER_RETURN,
                original_tipo=ORIGINAL_TIPO_VENTA,
                original_id=venta_id,
                items=[{"producto_id": 1, "cantidad": 1}],
            )
            barrier.wait(timeout=15)
            if not ok_d:
                results.append((False, msg_d, label))
                return
            ok_c, msg_c, _ = svc.confirmar(
                rid,
                inventory_mode="authoritative",
                inventory_command_id=str(uuid.uuid4()),
                inventory_connection_factory=app_factory(),
            )
            results.append((ok_c, msg_c, label))

        with phase3c_env() as env1, phase3c_env() as env2:
            t1 = threading.Thread(target=worker, args=(env1, "W01"))
            t2 = threading.Thread(target=worker, args=(env2, "W02"))
            t1.start()
            t2.start()
            t1.join(timeout=30)
            t2.join(timeout=30)
        self.assertEqual(len(results), 2, msg=repr(results))
        applied = [r for r in results if r[0]]
        rejected = [r for r in results if not r[0]]
        self.assertEqual(len(applied), 1, msg=repr(results))
        self.assertEqual(len(rejected), 1, msg=repr(results))
        self.assertEqual(InventoryCoordinatorClient(self.admin).get_balance(lid), 10000)

    def test_20_two_station_supplier_return_race(self):
        from inventory_coordinator import InventoryCoordinatorClient
        from inventory_cutover import STATUS_AUTHORITATIVE, STATUS_CUTOVER_IN_PROGRESS

        lid = insert_producto(self.admin, stock=100)
        InventoryCoordinatorClient(self.admin).seed_balance(lid, 100000)
        force_postgres_status(self.admin, STATUS_CUTOVER_IN_PROGRESS)
        force_postgres_status(self.admin, STATUS_AUTHORITATIVE, epoch=1)

        with phase3c_env() as env_a:
            pin_env_db(env_a)
            conn = env_a.connect()
            try:
                seed_producto(conn, env_a, stock=100, local_id=lid, codigo="SUP-A")
                insert_usuario(conn)
                conn.commit()
            finally:
                conn.close()
            ok, msg, cid = compras_service(env_a).confirmar_recepcion(
                proveedor_id=1,
                productos=[{"producto_id": 1, "cantidad": 5, "precio_unitario": 10}],
                numero_factura="ORIG-5",
                inventory_mode="authoritative",
                inventory_command_id=str(uuid.uuid4()),
                inventory_connection_factory=app_factory(),
            )
            self.assertTrue(ok, msg)
            conn = env_a.connect()
            try:
                compra = dict(conn.execute("SELECT * FROM compras WHERE id=?", (cid,)).fetchone())
                det = dict(
                    conn.execute(
                        "SELECT * FROM detalle_compras WHERE compra_id=?", (cid,)
                    ).fetchone()
                )
            finally:
                conn.close()

        results = []
        barrier = threading.Barrier(2)

        def worker(env, label):
            pin_env_db(env)
            conn = env.connect()
            try:
                seed_producto(conn, env, stock=100, local_id=lid, codigo=f"SUP-{label}")
                insert_usuario(conn)
                conn.execute(
                    """
                    INSERT INTO compras (
                        proveedor_id, numero_factura, fecha, tipo_compra, total,
                        usuario_id, estado, local_id, inventory_command_id
                    ) VALUES (1, ?, ?, 'CONTADO', ?, 1, 'COMPLETADA', ?, ?)
                    """,
                    (
                        f"COPY-{label}",
                        compra["fecha"],
                        compra["total"],
                        compra["local_id"],
                        compra["inventory_command_id"],
                    ),
                )
                compra_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                conn.execute(
                    """
                    INSERT INTO detalle_compras (
                        compra_id, producto_id, cantidad, precio_unitario, subtotal
                    ) VALUES (?, 1, ?, ?, ?)
                    """,
                    (compra_id, det["cantidad"], det["precio_unitario"], det["subtotal"]),
                )
                conn.commit()
            finally:
                conn.close()
            svc = returns_service(env)
            ok_d, msg_d, rid = svc.guardar_borrador(
                kind=KIND_SUPPLIER_RETURN,
                original_tipo=ORIGINAL_TIPO_COMPRA,
                original_id=compra_id,
                items=[{"producto_id": 1, "cantidad": 3}],
            )
            barrier.wait(timeout=15)
            if not ok_d:
                results.append((False, msg_d, 0))
                return
            ok_c, msg_c, _ = svc.confirmar(
                rid,
                inventory_mode="authoritative",
                inventory_command_id=str(uuid.uuid4()),
                inventory_connection_factory=app_factory(),
            )
            results.append((ok_c, msg_c, 3 if ok_c else 0))

        with phase3c_env() as env1, phase3c_env() as env2:
            t1 = threading.Thread(target=worker, args=(env1, "W01"))
            t2 = threading.Thread(target=worker, args=(env2, "W02"))
            t1.start()
            t2.start()
            t1.join(timeout=30)
            t2.join(timeout=30)
        self.assertEqual(len(results), 2, msg=repr(results))
        net = sum(r[2] for r in results)
        self.assertLessEqual(net, 5, msg=repr(results))
        self.assertEqual(len([r for r in results if r[0]]), 1, msg=repr(results))
        self.assertEqual(InventoryCoordinatorClient(self.admin).get_balance(lid), 102000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
