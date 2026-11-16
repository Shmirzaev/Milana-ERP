"""Recovery must preserve attribution written by the newer Packaging release."""
from copy import deepcopy

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.packaging.recovery_guard_service import RECOVERY_REFUSAL
from app.models.packages_service import _apply_package_delete_request, _apply_package_edit_request
from app.schemas import (
    AuditLog, FinishedGoodsStock, Package, PackageBatchAllocation, PackageChangeRequest,
    PackageItem, PackagePrintRunMember, ProductionBatch, ProductionOrder,
)
from app.tests.test_package_workflows import (
    create_run, package_qr, packaging_order, warehouse,  # noqa: F401 - shared pytest fixtures
)
from app.tests.test_shipment_review import correct, dispatch  # noqa: F401 - shared pytest fixture


def add_exact_allocation(package_id):
    with SessionLocal() as db:
        package = db.get(Package, package_id)
        if package.production_order_id is None:
            order = ProductionOrder(production_no="RECOVERY-PO", production_type="branded_stock",
                                    model_id=package.model_id, planned_quantity=package.total_quantity)
            db.add(order)
            db.flush()
            package.production_order_id = order.id
        batch = ProductionBatch(production_order_id=package.production_order_id,
                                batch_no="RECOVERY-BATCH", planned_quantity=package.total_quantity)
        db.add(batch)
        db.flush()
        breakdown = [{"model_id": item.model_id, "color": item.color, "size": item.size,
                      "quantity": item.quantity} for item in package.items]
        allocation = {"production_batch_id": batch.id, "quantity": package.total_quantity,
                      "item_breakdown": breakdown}
        db.add(PackageBatchAllocation(package_id=package.id, **allocation))
        for member in db.query(PackagePrintRunMember).filter_by(package_id=package.id):
            # Literal final-release contract, independent of recovery's snapshot serializer.
            snapshot = deepcopy(member.snapshot)
            snapshot["batch_allocations"] = [allocation]
            member.snapshot = snapshot
        db.commit()
        return allocation


def protected_facts():
    with SessionLocal() as db:
        return {
            model.__tablename__: [dict(row) for row in db.execute(
                select(model.__table__).order_by(model.id)).mappings()]
            for model in (Package, PackageItem, PackageBatchAllocation, FinishedGoodsStock, AuditLog)
        }


@pytest.mark.parametrize("receipt", ["print-run", "order"])
def test_recovery_receives_exact_run_once_and_blocks_warehouse_delete(
    client, auth_headers, warehouse, packaging_order, receipt,
):
    run = create_run(client, auth_headers, packaging_order, 1)
    pid = run["package_ids"][0]
    expected = add_exact_allocation(pid)
    if receipt == "print-run":
        path = "/api/packages/print-runs/receive"
        body = {"code": package_qr(pid), "storage_cell": "A-01", "storage_shelf": "S1"}
    else:
        path = f'/api/packages/receive-order/{packaging_order["production_order_id"]}'
        body = {"package_ids": [pid]}
    first = client.post(path, headers=warehouse, json=body)
    assert first.status_code == 200, first.text
    before = protected_facts()
    assert client.post(path, headers=warehouse, json=body).status_code == 200
    assert protected_facts() == before
    refusal = client.delete(f"/api/packages/warehouse/{pid}", headers=warehouse)
    assert refusal.status_code == 409, refusal.text
    assert refusal.json()["detail"] == RECOVERY_REFUSAL
    assert protected_facts() == before
    with SessionLocal() as db:
        package = db.get(Package, pid)
        assert package.status == "received_in_storage"
        assert package.batch_allocations[0].item_breakdown == expected["item_breakdown"]


@pytest.mark.parametrize("operation", ["edit", "delete"])
def test_recovery_change_application_refuses_exact_package_without_writes(
    client, auth_headers, packaging_order, operation,
):
    pid = create_run(client, auth_headers, packaging_order, 1)["package_ids"][0]
    add_exact_allocation(pid)
    before = protected_facts()
    with SessionLocal() as db:
        package = db.get(Package, pid)
        request = PackageChangeRequest(package_id=pid, package_no=package.package_no,
                                       request_type=operation, payload_json={"weight_kg": 2})
        with pytest.raises(HTTPException) as refusal:
            if operation == "edit":
                _apply_package_edit_request(db, request, None, allow_printed=True)
            else:
                _apply_package_delete_request(db, request, allow_printed=True)
        assert refusal.value.status_code == 409
        assert refusal.value.detail == RECOVERY_REFUSAL
        db.commit()
    assert protected_facts() == before


def test_recovery_shipment_correction_refuses_exact_package_without_writes(client, auth_headers, dispatch):
    add_exact_allocation(dispatch["package"])
    before = protected_facts()
    response = correct(client, auth_headers, dispatch)
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == RECOVERY_REFUSAL
    assert protected_facts() == before
