"""Selected Nastils retain independent budgets, provenance and factory access."""
from uuid import uuid4

import pytest

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.schemas import (
    Department, FinishedGoodsStock, Model, Package, PackageBatchAllocation,
    PackagePrintRun, PackagingRecord, ProductionBatch, ProductionOrder,
    SewingRecord, WorkOrder,
)

RUN_PATH = "/api/packages/print-runs/create-packages"


def seed_nastils(factory="MIL", *, split_factory=False, sessions=SessionLocal):
    marker = uuid4().hex[:10]
    with sessions.begin() as db:
        model = db.query(Model).filter_by(code="T-SHIRT-001").one()
        order = ProductionOrder(production_no=f"MULTI-{marker}", production_type="branded_stock",
                                model_id=model.id, planned_quantity=165)
        db.add(order)
        db.flush()
        package_code = {"MIL": "PKG", "BST": "BPK", "ECO": "ECP"}[factory]
        # A different order-level fallback must never mask exact Nastil ownership.
        fallback = WorkOrder(production_order_id=order.id, operation="packaging",
                             department_id=db.query(Department.id).filter_by(code=package_code).scalar())
        db.add(fallback)
        batch_ids = []
        for index, quantity in enumerate([35, 40, 90], 1):
            batch = ProductionBatch(production_order_id=order.id, batch_no=f"N-{marker}-{index}",
                                    name=f"Nastil {index}", batch_index=index, planned_quantity=quantity)
            db.add(batch)
            db.flush()
            batch_ids.append(batch.id)
            owner = "ECP" if split_factory and index == 2 else package_code
            package = WorkOrder(production_order_id=order.id, production_batch_id=batch.id,
                                operation="packaging", department_id=db.query(Department.id).filter_by(code=owner).scalar(),
                                passed_qty=quantity, actual_output_qty=quantity)
            sewing = WorkOrder(production_order_id=order.id, production_batch_id=batch.id,
                               operation="sewing", department_id=db.query(Department.id).filter_by(
                                   code="SEW" if factory == "MIL" else factory).scalar(), passed_qty=quantity)
            db.add_all([package, sewing])
            db.flush()
            db.add(PackagingRecord(work_order_id=package.id, production_batch_id=batch.id,
                                   input_qty=quantity, packed_qty=quantity))
            db.add(SewingRecord(work_order_id=sewing.id, production_batch_id=batch.id,
                               input_qty=quantity, sewn_qty=quantity, passed_qty=quantity,
                               size_quantities=[{"size": "M", "quantity": quantity}]))
        return order.id, model.id, batch_ids


def headers(factory):
    return {"Authorization": "Bearer " + create_access_token(1, extra={"factory_code": factory})}


def package(order_id, model_id, allocations):
    quantity = sum(value for _, value in allocations)
    return {"production_order_id": order_id, "production_batch_id": None,
            "model_id": model_id, "color": "White", "capacity": 60,
            "items": [{"model_id": model_id, "color": "White", "size": "M", "quantity": quantity}],
            "batch_allocations": [{"production_batch_id": bid, "quantity": qty} for bid, qty in allocations]}


def assert_no_packages(order_id):
    with SessionLocal() as db:
        assert db.query(Package).filter_by(production_order_id=order_id).count() == 0
        assert db.query(FinishedGoodsStock).filter_by(production_order_id=order_id).count() == 0
        assert db.query(PackagePrintRun).count() == 0


@pytest.mark.parametrize("factory", ["MIL", "BST", "ECO"])
def test_two_nastils_full_partial_retry_and_warehouse_provenance(client, factory):
    order_id, model_id, (first, second, unselected) = seed_nastils(factory)
    body = {"request_key": str(uuid4()), "packages": [
        package(order_id, model_id, [(first, 35), (second, 25)]),
        package(order_id, model_id, [(second, 15)]),
    ]}
    response = client.post(RUN_PATH, headers=headers(factory), json=body)
    assert response.status_code == 201, response.text
    saved = response.json()
    assert client.post(RUN_PATH, headers=headers(factory), json=body).json() == saved
    with SessionLocal() as db:
        allocations = db.query(PackageBatchAllocation).join(Package).filter(Package.production_order_id == order_id).all()
        assert sum(row.quantity for row in allocations if row.production_batch_id == first) == 35
        assert sum(row.quantity for row in allocations if row.production_batch_id == second) == 40
        assert not any(row.production_batch_id == unselected for row in allocations)
        assert sum(row.quantity for row in db.query(FinishedGoodsStock).filter_by(production_order_id=order_id)) == 75
    # Even with 90 unselected pieces, neither selected source may be spent again.
    extra = client.post(RUN_PATH, headers=headers(factory), json={"request_key": str(uuid4()),
                        "packages": [package(order_id, model_id, [(second, 1)])]})
    assert extra.status_code == 400, extra.text
    label = client.get(f"/api/packages/print-runs/{saved['id']}/label", headers=headers(factory))
    assert label.status_code == 200, label.text
    assert "Nastil 1" in label.text and "Nastil 2" in label.text
    received = client.post("/api/packages/print-runs/receive", headers=headers(factory), json={"code": saved["code"]})
    assert received.status_code == 200, received.text
    with SessionLocal() as db:
        packages = db.query(Package).filter_by(production_order_id=order_id).all()
        assert len(packages) == 2
        assert all(row.status == "received_in_storage" for row in packages)
        assert sum(row.total_quantity for row in packages) == 75


@pytest.mark.parametrize("path", [RUN_PATH, "/api/packages", "/api/packages/bulk"])
def test_all_creation_paths_authorize_each_source_nastil(client, path):
    order_id, model_id, (first, second, _) = seed_nastils(split_factory=True)
    row = package(order_id, model_id, [(first, 1), (second, 1)])
    body = {"request_key": str(uuid4()), "packages": [row]} if path == RUN_PATH else row
    response = client.post(path, headers=headers("MIL"), json=body)
    assert response.status_code == 403, response.text
    assert_no_packages(order_id)


def test_later_source_overrun_rolls_back_entire_print_run(client):
    order_id, model_id, (first, second, _) = seed_nastils()
    body = {"request_key": str(uuid4()), "packages": [
        package(order_id, model_id, [(first, 35), (second, 25)]),
        package(order_id, model_id, [(second, 16)]),
    ]}
    response = client.post(RUN_PATH, headers=headers("MIL"), json=body)
    assert response.status_code == 400, response.text
    assert_no_packages(order_id)
    # Correct the rejected request with the same key; no partial receipt survived.
    body["packages"][1] = package(order_id, model_id, [(second, 15)])
    response = client.post(RUN_PATH, headers=headers("MIL"), json=body)
    assert response.status_code == 201, response.text
