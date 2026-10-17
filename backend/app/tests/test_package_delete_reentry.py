"""An unused QR deletion reopens only its output, never its Sewing receipt."""
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import (
    AuditLog, Department, FinishedGoodsStock, Model, Package, PackagePrintRun,
    PackagePrintRunMember, PackagingReceipt, PackagingRecord, ProductionBatch,
    ProductionOrder, SewingRecord, StockMovement, WorkOrder,
)
from app.tests.test_package_workflows import create_run


def setup_output(client, *, factory="BST", batched=True, receipts=True, quantity=120, packed=None, damaged=0):
    headers = {"Authorization": f"Bearer {create_access_token(1, extra={'factory_code': factory})}"}
    department = {"MIL": "PKG", "BST": "BPK", "ECO": "ECP"}[factory]
    with SessionLocal() as db:
        model = Model(code=f"RESET-{uuid4().hex}", name="Reset regression", status="approved")
        db.add(model)
        db.flush()
        order = ProductionOrder(production_no=f"RESET-{uuid4().hex}", production_type="branded_stock",
                                model_id=model.id, planned_quantity=quantity, status="packaging")
        db.add(order)
        db.flush()
        batch = ProductionBatch(production_order_id=order.id, batch_no=f"RESET-{order.id}-01",
                                batch_index=1, planned_quantity=quantity) if batched else None
        if batch:
            db.add(batch)
            db.flush()
        batch_id = batch.id if batch else None
        sewing = WorkOrder(production_order_id=order.id, operation="sewing", status="completed",
                           department_id=db.query(Department.id).filter_by(code="SEW" if factory == "MIL" else factory).scalar(),
                           planned_input_qty=quantity, planned_output_qty=quantity,
                           actual_input_qty=quantity, actual_output_qty=quantity, passed_qty=quantity)
        packaging = WorkOrder(production_order_id=order.id, operation="packaging", status="in_progress",
                              department_id=db.query(Department.id).filter_by(code=department).scalar(),
                              planned_input_qty=quantity, planned_output_qty=quantity,
                              actual_input_qty=quantity if receipts else 0)
        storage = WorkOrder(production_order_id=order.id, operation="storage_transfer", status="waiting",
                            department_id=db.query(Department.id).filter_by(code="FGS").scalar(),
                            planned_input_qty=quantity, planned_output_qty=quantity)
        db.add_all([sewing, packaging, storage])
        db.flush()
        db.add(SewingRecord(work_order_id=sewing.id, production_batch_id=batch_id,
                            input_qty=quantity, sewn_qty=quantity, passed_qty=quantity))
        if receipts:
            db.add(PackagingReceipt(work_order_id=packaging.id, source_work_order_id=sewing.id,
                                   production_order_id=order.id, production_batch_id=batch_id,
                                   packaging_department_code=department, quantity=quantity, receive_method="manual"))
        db.commit()
        ids = dict(order=order.id, packaging=packaging.id, storage=storage.id, batch=batch_id)
        template = dict(production_order_id=order.id, production_batch_id=batch_id, model_id=model.id,
                        color="white", capacity=quantity, weight_kg=1.5,
                        items=[dict(model_id=model.id, color="white", size="M", quantity=quantity // 2)])
    payload = dict(work_order_id=ids["packaging"], production_batch_id=batch_id, input_qty=quantity,
                   packed_qty=quantity if packed is None else packed, damaged_qty=damaged)
    response = client.post("/api/packaging/records", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    ids["record"] = response.json()["id"]
    return headers, ids, template, payload


def upstream_snapshot():
    with SessionLocal() as db:
        return [db.execute(select(model.__table__).order_by(model.id)).all()
                for model in (SewingRecord, PackagingReceipt)]


def delete(client, headers, pid):
    return client.post(f"/api/packages/{pid}/change-requests", headers=headers, json={"request_type": "delete"})


@pytest.mark.parametrize("factory", ["MIL", "BST", "ECO"])
@pytest.mark.parametrize("batched,receipts", [(True, True), (True, False), (False, True), (False, False)])
def test_partial_full_delete_reenter_and_reprint(client, auth_headers, factory, batched, receipts):
    headers, ids, template, payload = setup_output(client, factory=factory, batched=batched, receipts=receipts)
    run = create_run(client, headers, template, 2)
    upstream = upstream_snapshot()
    old_numbers = []
    for index, pid in enumerate(run["package_ids"]):
        with SessionLocal() as db:
            old_numbers.append(db.get(Package, pid).package_no)
        response = delete(client, headers, pid)
        assert response.status_code == 201, response.text
        remaining = 60 if index == 0 else 0
        with SessionLocal() as db:
            record = db.get(PackagingRecord, ids["record"])
            assert (record.input_qty, record.packed_qty, record.damaged_qty) == (remaining, remaining, 0)
            wo = db.get(WorkOrder, ids["packaging"])
            assert (wo.passed_qty, wo.actual_output_qty, wo.status, wo.end_time) == (remaining, remaining, "in_progress", None)
            assert wo.actual_input_qty == (120 if receipts else remaining)
            assert db.get(ProductionOrder, ids["order"]).status == "packaging"
            assert db.get(WorkOrder, ids["storage"]).status == "waiting"
            assert db.query(FinishedGoodsStock).filter_by(production_order_id=ids["order"]).count() == (1 if remaining else 0)
        assert upstream_snapshot() == upstream
        progress = client.get(f"/api/work-orders/{ids['packaging']}/packaging-batch-progress", headers=headers).json()
        balance = progress["items"][0] if batched else progress
        assert balance["packed_qty"] == balance["packaged_qty"] == remaining
        assert balance["available_to_package"] == 0
        assert balance["available_input_qty"] == 120 - remaining
    # Old labels cannot be reused, and replacements require re-entered output.
    duplicate = delete(client, headers, run["package_ids"][0])
    assert duplicate.status_code == 404
    blocked = client.post("/api/packages/print-runs/create-packages", headers=headers,
                          json={"request_key": str(uuid4()), "packages": [template]})
    assert blocked.status_code in {400, 409}, blocked.text
    reenter = client.post("/api/packaging/records", headers=headers, json=payload)
    assert reenter.status_code == 201, reenter.text
    replacement = create_run(client, headers, template, 2)
    with SessionLocal() as db:
        assert db.get(WorkOrder, ids["packaging"]).actual_input_qty == 120
        assert db.get(WorkOrder, ids["packaging"]).passed_qty == 120
        assert db.get(PackagePrintRun, run["id"]).deleted_at is not None
        assert db.query(PackagePrintRunMember).filter_by(run_id=run["id"]).count() == 2
        assert all(db.get(Package, pid).package_no not in old_numbers for pid in replacement["package_ids"])
        assert db.query(AuditLog).filter_by(action="undo_package_output").count() == 2
    assert upstream_snapshot() == upstream


@pytest.mark.parametrize("input_qty,packed,damaged,remaining", [(318, 240, 0, 0), (120, 110, 10, 10)])
def test_last_label_releases_unused_input_but_preserves_defects(client, auth_headers, input_qty, packed, damaged, remaining):
    headers, ids, template, _ = setup_output(client, quantity=input_qty, packed=packed, damaged=damaged)
    template["items"][0]["quantity"] = packed
    run = create_run(client, headers, template, 1)
    assert delete(client, headers, run["package_ids"][0]).status_code == 201
    with SessionLocal() as db:
        record = db.get(PackagingRecord, ids["record"])
        assert (record.input_qty, record.packed_qty, record.damaged_qty) == (remaining, 0, damaged)
        wo = db.get(WorkOrder, ids["packaging"])
        assert wo.actual_input_qty == input_qty and wo.failed_qty == damaged
    progress = client.get(f"/api/work-orders/{ids['packaging']}/packaging-batch-progress", headers=headers).json()["items"][0]
    assert progress["available_input_qty"] == input_qty - remaining


@pytest.mark.parametrize("blocker", ["reserved", "materials", "wrong_factory"])
def test_rejected_delete_does_not_release_quantity_or_retire_label(client, auth_headers, blocker):
    headers, ids, template, _ = setup_output(client)
    run = create_run(client, headers, template, 2)
    pid = run["package_ids"][0]
    with SessionLocal() as db:
        if blocker == "reserved":
            stock = db.query(FinishedGoodsStock).filter_by(package_id=pid).one()
            stock.reserved_qty, stock.available_qty = 1, stock.quantity - 1
        elif blocker == "materials":
            db.add(StockMovement(movement_type="consume", item_id=1, quantity=1, unit="pcs",
                                 reference_type="PackagingRecord", reference_id=ids["record"]))
        db.commit()
    response = delete(client, auth_headers if blocker == "wrong_factory" else headers, pid)
    assert response.status_code == (403 if blocker == "wrong_factory" else 409), response.text
    with SessionLocal() as db:
        assert db.get(Package, pid)
        assert db.get(PackagingRecord, ids["record"]).packed_qty == 120
        assert not db.get(PackagePrintRun, run["id"]).deleted_package_ids
        assert db.query(AuditLog).filter_by(action="undo_package_output").count() == 0


@pytest.mark.parametrize("warehouse_delete", [False, True])
def test_mixed_batch_delete_releases_exact_allocations_and_keeps_siblings(client, auth_headers, warehouse_delete):
    headers, ids, template, _ = setup_output(client)
    with SessionLocal() as db:
        sewing = db.query(WorkOrder).filter_by(production_order_id=ids["order"], operation="sewing").one()
        second = ProductionBatch(production_order_id=ids["order"], batch_no="RESET-SECOND", batch_index=2, planned_quantity=80)
        db.add(second)
        db.flush()
        second_id = second.id
        db.add(SewingRecord(work_order_id=sewing.id, production_batch_id=second_id, input_qty=80, sewn_qty=80, passed_qty=80))
        db.add(PackagingReceipt(work_order_id=ids["packaging"], source_work_order_id=sewing.id,
                               production_order_id=ids["order"], production_batch_id=second_id,
                               packaging_department_code="BPK", quantity=80, receive_method="manual"))
        target = db.get(WorkOrder, ids["packaging"])
        target.status, target.actual_input_qty = "in_progress", 200
        target.planned_input_qty = target.planned_output_qty = 200
        db.commit()
    response = client.post("/api/packaging/records", headers=headers, json={
        "work_order_id": ids["packaging"], "production_batch_id": second_id, "input_qty": 80, "packed_qty": 80,
    })
    assert response.status_code == 201, response.text
    mixed = {**template, "production_batch_id": None,
             "items": [{**template["items"][0], "quantity": 100}],
             "batch_allocations": [{"production_batch_id": ids["batch"], "quantity": 60},
                                   {"production_batch_id": second_id, "quantity": 40}]}
    other = {**template, "production_batch_id": second_id, "items": [{**template["items"][0], "quantity": 40}]}
    response = client.post("/api/packages/print-runs/create-packages", headers=headers,
                           json={"request_key": str(uuid4()), "packages": [mixed, template, other]})
    assert response.status_code == 201, response.text
    run = response.json()
    upstream = upstream_snapshot()
    if warehouse_delete:
        receipt = client.post("/api/packages/print-runs/receive", headers=headers, json={"code": run["code"]})
        assert receipt.status_code == 200, receipt.text
        pid = run["package_ids"][0]
        result = client.delete(f"/api/packages/warehouse/{pid}", headers=headers)
    else:
        result = delete(client, headers, run["package_ids"][0])
    assert result.status_code == (200 if warehouse_delete else 201), result.text
    with SessionLocal() as db:
        assert {r.production_batch_id: r.packed_qty for r in db.query(PackagingRecord).filter_by(work_order_id=ids["packaging"])} == {ids["batch"]: 60, second_id: 40}
        assert [db.get(Package, pid).total_quantity for pid in run["package_ids"][1:]] == [60, 40]
        assert db.get(WorkOrder, ids["packaging"]).passed_qty == 100
        assert db.get(WorkOrder, ids["packaging"]).actual_input_qty == 200
    assert upstream_snapshot() == upstream


def test_received_sibling_remains_in_storage_when_pending_label_is_deleted(client, auth_headers):
    headers, ids, template, _ = setup_output(client, factory="MIL")
    first = create_run(client, headers, template, 1)
    second = create_run(client, headers, template, 1)
    received = client.post("/api/packages/print-runs/receive", headers=headers, json={"code": first["code"]})
    assert received.status_code == 200, received.text
    assert delete(client, headers, second["package_ids"][0]).status_code == 201
    with SessionLocal() as db:
        assert db.get(Package, first["package_ids"][0]).status == "received_in_storage"
        storage = db.get(WorkOrder, ids["storage"])
        assert storage.passed_qty == 60 and storage.status == "in_progress"
        assert db.get(PackagingRecord, ids["record"]).packed_qty == 60
