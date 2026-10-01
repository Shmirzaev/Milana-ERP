import pytest

from app.models import ProductionOrder
from app.tests.conftest import TestSessionLocal


def make_order():
    with TestSessionLocal() as db:
        order = ProductionOrder(
            production_no="PATCH-ALLOWLIST", production_type="branded_stock",
            model_id=1, planned_quantity=100, status="planning",
        )
        db.add(order)
        db.commit()
        return order.id


@pytest.mark.parametrize("field,value", [
    ("id", 999999), ("created_by", 1), ("production_no", "INJECTED"),
    ("created_at", None), ("updated_at", None), ("start_date", None),
    ("collection_id", None), ("planning_order_id", None), ("brand_id", None),
    ("fabric_batch_id", None), ("destination_warehouse_id", None),
    ("printing_instructions", "injected"), ("printing_attachments", []),
    ("items", []), ("materials", []), ("batches", []), ("work_orders", []),
    ("source_type", "usluga"), ("unknown_field", "injected"),
])
def test_patch_rejects_blocked_fields_atomically(client, auth_headers, field, value):
    pid = make_order()
    response = client.patch(
        f"/api/production-orders/{pid}", headers=auth_headers,
        json={field: value, "planned_quantity": 200},
    )
    assert response.status_code == 422, response.text
    with TestSessionLocal() as db:
        order = db.get(ProductionOrder, pid)
        assert order is not None
        assert order.production_no == "PATCH-ALLOWLIST"
        assert order.created_by is None
        assert order.planned_quantity == 100


def test_patch_accepts_all_editable_fields_and_status(client, auth_headers):
    pid = make_order()
    payload = {
        "model_id": 1, "sales_order_id": None, "planned_quantity": 120,
        "deadline": None, "estimated_material_code": "FABRIC",
        "estimated_material_amount": 12.5, "estimated_material_unit": "kg",
        "status": "in_progress",
    }
    response = client.patch(
        f"/api/production-orders/{pid}", headers=auth_headers, json=payload,
    )
    assert response.status_code == 200, response.text
    with TestSessionLocal() as db:
        order = db.get(ProductionOrder, pid)
        for field, value in payload.items():
            assert getattr(order, field) == value
