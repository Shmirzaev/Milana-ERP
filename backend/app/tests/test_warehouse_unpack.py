"""Warehouse delete -> exact output reversal -> repacking -> warehouse receipt."""
from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.schemas import AuditLog, FinishedGoodsStock, Package, PackagePrintRun, PackagingRecord, ProductionOrder, WorkOrder
from app.tests.test_package_delete_reentry import setup_output, upstream_snapshot
from app.tests.test_package_workflows import create_run


@pytest.mark.parametrize("factory", ["MIL", "BST", "ECO"])
@pytest.mark.parametrize("batched,receipts", [(True, True), (True, False), (False, True), (False, False)])
def test_warehouse_delete_repack_receive(client, auth_headers, factory, batched, receipts):
    headers, ids, template, payload = setup_output(client, factory=factory, batched=batched, receipts=receipts)
    run = create_run(client, headers, template, 2)
    response = client.post("/api/packages/print-runs/receive", headers=headers, json={"code": run["code"]})
    assert response.status_code == 200, response.text
    upstream = upstream_snapshot()
    with SessionLocal() as db:
        assert db.get(WorkOrder, ids["storage"]).status == "completed"
        numbers = [db.get(Package, pid).package_no for pid in run["package_ids"]]
    for index, pid in enumerate(run["package_ids"]):
        result = client.delete(f"/api/packages/warehouse/{pid}", headers=headers)
        assert result.status_code == 200, result.text
        remaining = 60 if index == 0 else 0
        with SessionLocal() as db:
            assert db.get(Package, pid) is None
            assert db.query(FinishedGoodsStock).filter_by(package_id=pid).count() == 0
            record = db.get(PackagingRecord, ids["record"])
            assert (record.input_qty, record.packed_qty, record.damaged_qty) == (remaining, remaining, 0)
            work = db.get(WorkOrder, ids["packaging"])
            assert (work.passed_qty, work.status, work.end_time) == (remaining, "in_progress", None)
            assert work.actual_input_qty == (120 if receipts else remaining)
            storage = db.get(WorkOrder, ids["storage"])
            assert storage.passed_qty == remaining
            assert storage.status == ("in_progress" if remaining else "waiting")
            assert storage.end_time is None
            assert db.get(ProductionOrder, ids["order"]).status == ("storage_transfer" if remaining else "packaging")
            assert db.get(PackagePrintRun, run["id"]).deleted_package_ids == run["package_ids"][:index + 1]
        assert upstream_snapshot() == upstream
        progress = client.get(f"/api/work-orders/{ids['packaging']}/packaging-batch-progress", headers=headers)
        assert progress.status_code == 200
        balance = progress.json()["items"][0] if batched else progress.json()
        assert balance["packed_qty"] == balance["packaged_qty"] == remaining
        assert balance["available_input_qty"] == 120 - remaining
        assert client.delete(f"/api/packages/warehouse/{pid}", headers=headers).status_code == 404
    blocked = client.post("/api/packages/print-runs/create-packages", headers=headers,
                          json={"request_key": str(uuid4()), "packages": [template]})
    assert blocked.status_code in {400, 409}
    entered = client.post("/api/packaging/records", headers=headers, json=payload)
    assert entered.status_code == 201, entered.text
    replacement = create_run(client, headers, template, 2)
    received = client.post("/api/packages/print-runs/receive", headers=headers, json={"code": replacement["code"]})
    assert received.status_code == 200, received.text
    with SessionLocal() as db:
        assert db.get(WorkOrder, ids["storage"]).passed_qty == 120
        assert db.get(WorkOrder, ids["storage"]).status == "completed"
        assert all(db.get(Package, pid).package_no not in numbers for pid in replacement["package_ids"])
        assert db.query(AuditLog).filter_by(action="undo_package_output", entity_type="Package").count() == 2
    assert upstream_snapshot() == upstream


@pytest.mark.parametrize("blocker", ["materials", "reserved", "wrong_factory"])
def test_warehouse_failed_delete_preserves_output(client, auth_headers, blocker):
    from app.schemas import StockMovement
    headers, ids, template, _ = setup_output(client, factory="BST")
    run = create_run(client, headers, template, 2)
    assert client.post("/api/packages/print-runs/receive", headers=headers, json={"code": run["code"]}).status_code == 200
    pid = run["package_ids"][0]
    with SessionLocal() as db:
        if blocker == "materials":
            db.add(StockMovement(movement_type="consume", item_id=1, quantity=1, unit="pcs",
                                 reference_type="PackagingRecord", reference_id=ids["record"]))
        elif blocker == "reserved":
            stock = db.query(FinishedGoodsStock).filter_by(package_id=pid).one()
            stock.reserved_qty, stock.available_qty = 1, stock.quantity - 1
        db.commit()
    result = client.delete(f"/api/packages/warehouse/{pid}", headers=auth_headers if blocker == "wrong_factory" else headers)
    assert result.status_code == (403 if blocker == "wrong_factory" else 409), result.text
    with SessionLocal() as db:
        assert db.get(Package, pid)
        assert db.get(PackagingRecord, ids["record"]).packed_qty == 120
        assert not db.get(PackagePrintRun, run["id"]).deleted_package_ids
        assert db.query(AuditLog).filter_by(action="undo_package_output").count() == 0
