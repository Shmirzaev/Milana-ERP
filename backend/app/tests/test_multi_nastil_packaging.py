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


def unbatched_work_order(order_id):
    with SessionLocal() as db:
        return db.query(WorkOrder.id).filter_by(production_order_id=order_id, operation="packaging", production_batch_id=None).scalar()


@pytest.mark.parametrize("factory", ["MIL", "BST", "ECO"])
def test_two_nastils_full_partial_retry_and_warehouse_provenance(client, factory):
    order_id, model_id, (first, second, unselected) = seed_nastils(factory)
    work_order_id = unbatched_work_order(order_id)
    source_path = f"/api/packages/sources/{work_order_id}"
    # Record entry/progress deliberately excludes Nastils owned by dedicated WOs.
    progress = client.get(f"/api/work-orders/{work_order_id}/packaging-batch-progress", headers=headers(factory))
    assert progress.status_code == 200, progress.text
    assert progress.json()["items"] == []
    # Package creation has a separate same-factory source read spanning siblings.
    source = client.get(source_path, headers=headers(factory))
    assert source.status_code == 200, source.text
    assert [(row["id"], row["available_to_package"]) for row in source.json()["items"]] == [(first, 35), (second, 40), (unselected, 90)]
    assert [row["name"] for row in source.json()["items"]] == ["Nastil 1", "Nastil 2", "Nastil 3"]
    body = {"request_key": str(uuid4()), "packages": [
        package(order_id, model_id, [(first, 35), (second, 25)]),
        package(order_id, model_id, [(second, 15)]),
    ]}
    response = client.post(RUN_PATH, headers=headers(factory), json=body)
    assert response.status_code == 201, response.text
    saved = response.json()
    assert client.post(RUN_PATH, headers=headers(factory), json=body).json() == saved
    remaining = client.get(source_path, headers=headers(factory))
    assert [(row["id"], row["available_to_package"]) for row in remaining.json()["items"]] == [(first, 0), (second, 0), (unselected, 90)]
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


def test_package_sources_filters_sibling_factory_and_enforces_anchor_access(client):
    order_id, _, (first, other_factory, third) = seed_nastils(split_factory=True)
    work_order_id = unbatched_work_order(order_id)
    path = f"/api/packages/sources/{work_order_id}"
    assert client.get(path).status_code == 401
    response = client.get(path, headers=headers("MIL"))
    assert response.status_code == 200, response.text
    assert {row["id"] for row in response.json()["items"]} == {first, third}
    assert other_factory not in {row["id"] for row in response.json()["items"]}
    assert client.get(path, headers=headers("ECO")).status_code == 403
    with SessionLocal() as db:
        foreign_work = db.query(WorkOrder.id).filter_by(production_order_id=order_id, operation="packaging", production_batch_id=other_factory).scalar()
    assert client.get(f"/api/packages/sources/{foreign_work}", headers=headers("MIL")).status_code == 403
    matching = client.get(f"/api/packages/sources/{foreign_work}", headers=headers("ECO"))
    assert matching.status_code == 200, matching.text
    assert [(row["id"], row["available_to_package"]) for row in matching.json()["items"]] == [(other_factory, 40)]


def test_package_sources_is_read_only_and_rejects_unsupported_anchor(client, auth_headers):
    from app.models.packaging.package_sources_service import package_sources
    from app.schemas import User
    order_id, _, batch_ids = seed_nastils()
    with SessionLocal() as db:
        current = db.get(User, 1)
        result = package_sources(db, current, unbatched_work_order(order_id))
        assert {row.id for row in result.items} == set(batch_ids)
        assert not db.new and not db.dirty and not db.deleted
        sew_id = db.query(WorkOrder.id).filter_by(production_order_id=order_id, operation="sewing").first()[0]
    assert client.get(f"/api/packages/sources/{sew_id}", headers=auth_headers).status_code == 400
    assert client.get("/api/packages/sources/2147483647", headers=auth_headers).status_code == 404
    with SessionLocal.begin() as db:
        db.get(ProductionOrder, order_id).source_type = "usluga"
    assert client.get(f"/api/packages/sources/{unbatched_work_order(order_id)}", headers=auth_headers).status_code == 409


def test_package_sources_requires_package_permission(client):
    from app.core.deps import get_current_user
    from app.main import app
    from app.schemas import Role, User
    order_id, _, _ = seed_nastils()
    with SessionLocal.begin() as db:
        role = Role(name="Sources denied", permissions=["modeling.models"])
        db.add(role)
        db.flush()
        actor = User(name="Sources denied", email="sources-denied@example.com", password_hash="unused", role_id=role.id, is_active=True)
        db.add(actor)
        db.flush()
        actor.role
        app.dependency_overrides[get_current_user] = lambda: actor
        try:
            assert client.get(f"/api/packages/sources/{unbatched_work_order(order_id)}").status_code == 403
        finally:
            app.dependency_overrides.pop(get_current_user, None)
