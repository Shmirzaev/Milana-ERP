"""Legacy package creation preserves production-order model identity."""

from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.models import Department, FinishedGoodsStock, Model, Package, PackageItem, ProductionOrder, WorkOrder


def _packaging_order():
    marker = uuid4().hex
    with SessionLocal() as db:
        expected = Model(code=f"PKG-MATCH-{marker}", name="Expected package model", status="approved")
        wrong = Model(code=f"PKG-WRONG-{marker}", name="Wrong package model", status="approved")
        db.add_all([expected, wrong])
        db.flush()
        order = ProductionOrder(
            production_no=f"PO-PKG-{marker}",
            production_type="branded_stock",
            model_id=expected.id,
            planned_quantity=20,
            status="in_progress",
        )
        db.add(order)
        db.flush()
        department_id = db.query(Department.id).filter(Department.code == "PKG").scalar()
        db.add(WorkOrder(
            production_order_id=order.id,
            department_id=department_id,
            operation="packaging",
            planned_input_qty=20,
            planned_output_qty=20,
            status="in_progress",
        ))
        db.commit()
        return order.id, expected.id, wrong.id


def _payload(order_id, header_model_id, item_model_id):
    return {
        "production_order_id": order_id,
        "model_id": header_model_id,
        "color": "navy",
        "capacity": 20,
        "items": [{
            "model_id": item_model_id,
            "color": "navy",
            "size": "M",
            "quantity": 5,
        }],
    }


def _assert_no_package_graph(order_id):
    with SessionLocal() as db:
        packages = db.query(Package).filter(Package.production_order_id == order_id).all()
        assert packages == []
        assert db.query(PackageItem).join(Package).filter(Package.production_order_id == order_id).count() == 0
        assert db.query(FinishedGoodsStock).filter(FinishedGoodsStock.production_order_id == order_id).count() == 0


@pytest.mark.parametrize(
    ("path", "count", "wrong_part"),
    [
        ("/api/packages", None, "header"),
        ("/api/packages/bulk", 2, "item"),
    ],
)
def test_legacy_package_endpoints_reject_models_outside_order(
    client,
    auth_headers,
    path,
    count,
    wrong_part,
):
    order_id, expected_model_id, wrong_model_id = _packaging_order()
    header_model_id = wrong_model_id if wrong_part == "header" else expected_model_id
    item_model_id = wrong_model_id if wrong_part == "item" else expected_model_id
    payload = _payload(order_id, header_model_id, item_model_id)
    if count is not None:
        payload["count"] = count

    response = client.post(path, json=payload, headers=auth_headers)

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "Package model must match the production order"
    _assert_no_package_graph(order_id)


def test_legacy_bulk_package_creation_keeps_matching_model(client, auth_headers):
    order_id, expected_model_id, _ = _packaging_order()
    payload = _payload(order_id, expected_model_id, expected_model_id)
    payload["count"] = 2

    response = client.post("/api/packages/bulk", json=payload, headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.json()["count"] == 2
    with SessionLocal() as db:
        packages = db.query(Package).filter(Package.production_order_id == order_id).all()
        assert len(packages) == 2
        assert {package.model_id for package in packages} == {expected_model_id}
        assert {
            item.model_id
            for item in db.query(PackageItem).filter(PackageItem.package_id.in_([package.id for package in packages]))
        } == {expected_model_id}
        stocks = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.production_order_id == order_id).all()
        assert len(stocks) == 2
        assert {stock.model_id for stock in stocks} == {expected_model_id}


def test_admin_override_cannot_mix_models_outside_order(client, auth_headers):
    order_id, expected_model_id, wrong_model_id = _packaging_order()
    payload = _payload(order_id, expected_model_id, expected_model_id)
    payload["override_capacity"] = True
    payload["items"].append({
        "model_id": wrong_model_id,
        "color": "navy",
        "size": "L",
        "quantity": 5,
    })

    response = client.post("/api/packages", json=payload, headers=auth_headers)

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "Package model must match the production order"
    _assert_no_package_graph(order_id)
