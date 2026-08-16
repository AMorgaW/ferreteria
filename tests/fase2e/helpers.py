from __future__ import annotations

import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from inventory_gateway import OUTCOME_APPLIED, OUTCOME_REJECTED, OUTCOME_UNKNOWN
from migration_runner import default_runner
from repositories.inventory_import_repository import InventoryImportRepository
from repositories.productos_repo import PRODUCT_CREATION_STAGING, ProductosRepository
from services.inventory_apply_service import InventoryImportApplyService
from services.inventory_import_service import InventoryImportService
from tests.fase0.harness import official_temp_db
from tests.fase2d.helpers import valid_row, write_workbook


class FakeAuthorityGateway:
    def __init__(self, balances=None):
        self.balances = balances if balances is not None else {}
        self.commands = {}
        self.calls = []
        self.payloads = []
        self.unknown_once = set()
        self.reject_call = None
        self.wrong_readback = False

    def submit(self, **payload):
        command_id = payload["command_id"]
        operation = dict(payload["operations"][0])
        self.calls.append((command_id, operation))
        self.payloads.append(dict(payload))
        if command_id in self.commands:
            return SimpleNamespace(
                outcome=OUTCOME_APPLIED, command_id=command_id, error=None
            )
        if self.reject_call and len(self.calls) == self.reject_call:
            return SimpleNamespace(
                outcome=OUTCOME_REJECTED, command_id=command_id,
                error="LAB_FAILURE",
            )
        local_id = operation["producto_local_id"]
        current = int(self.balances.get(local_id, 0))
        expected = int(operation["expected_base_scaled"])
        if current != expected:
            return SimpleNamespace(
                outcome=OUTCOME_REJECTED, command_id=command_id,
                error=f"STALE_BALANCE expected={expected} actual={current}",
            )
        if not self.wrong_readback:
            self.balances[local_id] = current + int(operation["delta_scaled"])
        self.commands[command_id] = operation
        if command_id in self.unknown_once:
            self.unknown_once.remove(command_id)
            return SimpleNamespace(
                outcome=OUTCOME_UNKNOWN, command_id=command_id,
                error="timeout after remote commit",
            )
        return SimpleNamespace(
            outcome=OUTCOME_APPLIED, command_id=command_id, error=None
        )


@contextmanager
def phase2e_env(*, rows=None, create_existing=True, base_scaled=80000):
    with official_temp_db() as env, tempfile.TemporaryDirectory(prefix="fase2e-xlsx-") as tmp:
        conn = env.connect()
        try:
            default_runner().run(conn, dry_run=False)
        finally:
            conn.close()
        source_rows = list(rows or [valid_row()])
        product_repo = ProductosRepository(env.db)
        local_id = None
        if create_existing:
            # Producto base estable; las diferencias del workbook deben quedar
            # visibles como candidate/metadata, no contaminar el setup.
            mapped = InventoryImportApplyService._mapped_product(valid_row())
            product = InventoryImportApplyService._producto_from_values(mapped, stock=0)
            ok, message, product_id = product_repo.crear_producto(
                product, creation_policy=PRODUCT_CREATION_STAGING
            )
            if not ok:
                raise AssertionError(message)
            local_id = product_repo.obtener_por_id(product_id)["local_id"]
        path = write_workbook(Path(tmp) / "inventario.xlsx", source_rows)
        repository = InventoryImportRepository(env.db)
        imported = InventoryImportService(repository).import_to_staging(path)
        balances = {} if local_id is None else {local_id: int(base_scaled)}
        gateway = FakeAuthorityGateway(balances)
        apply = InventoryImportApplyService(
            repository, product_repository=product_repo, gateway=gateway,
            authority_reader=lambda pid: gateway.balances.get(pid, 0),
        )
        yield SimpleNamespace(
            env=env, repository=repository, product_repo=product_repo,
            imported=imported, batch_id=imported.batch.batch_id,
            local_id=local_id, gateway=gateway, apply=apply, path=path,
        )


def approve_clean(context):
    review = context.apply.build_review_plan(context.batch_id)
    for blocker in tuple(review["blockers"]):
        if blocker["reason"] == "METADATA_APPROVAL_REQUIRED":
            context.repository.decide_metadata(
                blocker["row_id"], "KEEP_CURRENT", actor="tester"
            )
        elif blocker["reason"] in ("WARNING_NOT_APPROVED", "WORKBOOK_WARNING_NOT_APPROVED"):
            context.repository.acknowledge_batch_warnings(
                context.batch_id, actor="tester"
            )
    return context.apply.approve_batch(context.batch_id, actor="tester")
