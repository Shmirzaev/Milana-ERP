"""Production-backed package creation requires saved Packaging output."""

from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.models import (
    Department,
    FinishedGoodsStock,
    Model,
    Package,
    PackageItem,
    PackagingRecord,
    ProductionOrder,
    WorkOrder,
)


def _packaging_order(*, packed_quantity=None):
    marker = uuid4().hex
    with SessionLocal() as db:
        model = Model(code=f"PKG-EVID-{marker}", name="Package evidence", status="approved")
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no=f"PO-EVID-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=20,
            status="in_progress",
        )
        db.add(order)
        db.flush()
        work_order = WorkOrder(
            production_order_id=order.id,
            department_id=db.query(Department.id).filter(Department.code == "PKG").scalar(),
            operation="packaging",
            planned_input_qty=20,
            planned_output_qty=20,
            status="in_progress",
        )
        db.add(work_order)
        db.flush()
        if packed_quantity is not None:
            db.add(PackagingRecord(
                work_order_id=work_order.id,
                input_qty=packed_quantity,
                packed_qty=packed_quantity,
                damaged_qty=0,
            ))
        db.commit()
        return order.id, model.id


def _payload(order_id, model_id, *, count=None):
    payload = {
        "production_order_id": order_id,
        "model_id": model_id,
        "color": "navy",
        "capacity": 20,
        "items": [{
            "model_id": model_id,
            "color": "navy",
            "size": "M",
            "quantity": 5,
        }],
    }
    if count is not None:
        payload["count"] = count
    return payload


def _assert_no_package_graph(order_id):
    with SessionLocal() as db:
        packages = db.query(Package).filter(Package.production_order_id == order_id).all()
        assert packages == []
        assert db.query(PackageItem).join(Package).filter(Package.production_order_id == order_id).count() == 0
        assert db.query(FinishedGoodsStock).filter(FinishedGoodsStock.production_order_id == order_id).count() == 0


@pytest.mark.parametrize(
    ("path", "count"),
    [("/api/packages", None), ("/api/packages/bulk", 2)],
)
def test_legacy_package_creation_requires_packaging_output(client, auth_headers, path, count):
    order_id, model_id = _packaging_order()

    response = client.post(path, json=_payload(order_id, model_id, count=count), headers=auth_headers)

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "Save Packaging output before creating packages"
    _assert_no_package_graph(order_id)


def test_legacy_bulk_creation_uses_saved_packaging_output(client, auth_headers):
    order_id, model_id = _packaging_order(packed_quantity=10)

    response = client.post(
        "/api/packages/bulk",
        json=_payload(order_id, model_id, count=2),
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["count"] == 2
    with SessionLocal() as db:
        packages = db.query(Package).filter(Package.production_order_id == order_id).all()
        assert len(packages) == 2
        assert sum(package.total_quantity for package in packages) == 10
        stocks = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.production_order_id == order_id).all()
        assert len(stocks) == 2
        assert sum(stock.quantity for stock in stocks) == 10


def test_zero_packaging_output_cannot_create_stock(client, auth_headers):
    order_id, model_id = _packaging_order(packed_quantity=0)

    response = client.post("/api/packages", json=_payload(order_id, model_id), headers=auth_headers)

    assert response.status_code == 400, response.text
    assert "available packed quantity 0" in response.json()["detail"]
    _assert_no_package_graph(order_id)


def test_bulk_creation_rolls_back_when_total_exceeds_packaging_output(client, auth_headers):
    order_id, model_id = _packaging_order(packed_quantity=7)

    response = client.post(
        "/api/packages/bulk",
        json=_payload(order_id, model_id, count=2),
        headers=auth_headers,
    )

    assert response.status_code == 400, response.text
    assert "available packed quantity 2" in response.json()["detail"]
    _assert_no_package_graph(order_id)
