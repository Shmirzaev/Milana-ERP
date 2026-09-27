from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.models import AuditLog, Model, SalesOrder, SalesOrderItem


def _model() -> int:
    with SessionLocal() as db:
        suffix = uuid4().hex[:8]
        model = Model(
            code=f"SOURCE-{suffix}",
            name="Sales source validation",
            status="approved",
            selling_price=12,
        )
        db.add(model)
        db.commit()
        return int(model.id)


def _payload(model_id: int, *, source_type: str | None = None) -> dict:
    line = {
        "model_id": model_id,
        "color": "black",
        "size": "M",
        "quantity": 2,
    }
    if source_type is not None:
        line["source_type"] = source_type
    return {"order_type": "client_order", "items": [line]}


@pytest.mark.parametrize("source_type", ["produce_new", "from_stock"])
def test_create_sales_order_accepts_every_item_source_type(client, auth_headers, source_type):
    model_id = _model()

    response = client.post(
        "/api/sales-orders",
        json=_payload(model_id, source_type=source_type),
        headers=auth_headers,
    )

    assert response.status_code == 201, response.text
    assert response.json()["items"][0]["source_type"] == source_type
    with SessionLocal() as db:
        row = db.query(SalesOrderItem).filter_by(sales_order_id=response.json()["id"]).one()
        assert row.source_type == source_type


def test_create_sales_order_keeps_omitted_source_type_compatibility(client, auth_headers):
    response = client.post(
        "/api/sales-orders",
        json=_payload(_model()),
        headers=auth_headers,
    )

    assert response.status_code == 201, response.text
    assert response.json()["items"][0]["source_type"] == "produce_new"


def test_invalid_item_source_type_rolls_back_order_line_and_audit(client, auth_headers):
    model_id = _model()
    with SessionLocal() as db:
        before = (
            db.query(SalesOrder).count(),
            db.query(SalesOrderItem).count(),
            db.query(AuditLog).count(),
        )

    response = client.post(
        "/api/sales-orders",
        json=_payload(model_id, source_type="external_stock"),
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid sales order item source_type"}
    with SessionLocal() as db:
        assert (
            db.query(SalesOrder).count(),
            db.query(SalesOrderItem).count(),
            db.query(AuditLog).count(),
        ) == before


def test_missing_model_precedes_item_source_validation(client, auth_headers):
    response = client.post(
        "/api/sales-orders",
        json=_payload(2_147_483_647, source_type="external_stock"),
        headers=auth_headers,
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Model 2147483647 not found"}


def test_authentication_precedes_item_source_validation(client):
    response = client.post(
        "/api/sales-orders",
        json=_payload(2_147_483_647, source_type="external_stock"),
    )

    assert response.status_code == 401
