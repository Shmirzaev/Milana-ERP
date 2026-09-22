from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import (
    AuditLog,
    IdempotencyRecord,
    PurchaseOrder,
    PurchaseOrderLine,
    Role,
    StockBatch,
    StockMovement,
    User,
)
from app.schemas.purchasing import PurchaseOrderLineIn, PurchaseOrderReceiveLineIn


def _order_line(cost):
    return PurchaseOrderLineIn.model_validate({
        "item_id": 1,
        "ordered_quantity": 1,
        "unit": "pcs",
        "unit_cost": cost,
    })


def _receipt_line(cost):
    return PurchaseOrderReceiveLineIn.model_validate({
        "purchase_order_line_id": 1,
        "received_quantity": 1,
        "batch_no": "COST-BOUND",
        "cost_per_unit": cost,
    })


def _write_counts():
    with SessionLocal() as db:
        return (
            db.query(PurchaseOrder).count(),
            db.query(PurchaseOrderLine).count(),
            db.query(StockBatch).count(),
            db.query(StockMovement).count(),
            db.query(AuditLog).count(),
            db.query(IdempotencyRecord).count(),
        )


def test_purchase_costs_preserve_float_contract_and_storage_boundary():
    order_ordinary = _order_line("12.34567")
    order_maximum = _order_line("99999999.9999")
    receipt_ordinary = _receipt_line("12.34567")
    receipt_maximum = _receipt_line("99999999.9999")

    assert isinstance(order_ordinary.unit_cost, float)
    assert order_ordinary.unit_cost == 12.34567
    assert order_maximum.unit_cost == 99999999.9999
    assert _order_line("-1").unit_cost == -1
    assert _receipt_line(None).cost_per_unit is None
    assert receipt_ordinary.cost_per_unit == 12.34567
    assert receipt_maximum.cost_per_unit == 99999999.9999


@pytest.mark.parametrize(
    "cost",
    ["Infinity", "-Infinity", "NaN", "-100000000", "100000000"],
)
def test_purchase_order_cost_rejects_nonfinite_or_unrepresentable_values(cost):
    with pytest.raises(ValidationError):
        _order_line(cost)


@pytest.mark.parametrize(
    "cost",
    ["Infinity", "-Infinity", "NaN", "-0.0001", "100000000"],
)
def test_purchase_receipt_cost_rejects_invalid_or_unrepresentable_values(cost):
    with pytest.raises(ValidationError):
        _receipt_line(cost)


def test_purchase_cost_api_rejects_before_writes_and_preserves_auth_precedence(
    client,
    auth_headers,
):
    with SessionLocal() as db:
        denied_role = Role(name=f"No purchase cost write {uuid4().hex}", permissions=[])
        db.add(denied_role)
        db.flush()
        denied_user = User(
            name="Denied purchase cost writer",
            email=f"denied-purchase-cost-{uuid4().hex}@example.com",
            password_hash="unused-purchase-cost-bound-hash",
            role_id=denied_role.id,
            factory_code="MIL",
            extra_permissions=[],
            is_active=True,
        )
        db.add(denied_user)
        db.commit()
        denied_headers = {"Authorization": f"Bearer {create_access_token(denied_user.id)}"}

    order_payload = {
        "notes": "Purchase cost boundary regression",
        "lines": [{
            "item_id": 1,
            "ordered_quantity": 1,
            "unit": "pcs",
            "unit_cost": "100000000",
        }],
    }
    receipt_payload = {"lines": [{
        "purchase_order_line_id": 1,
        "received_quantity": 1,
        "batch_no": "COST-BOUND",
        "cost_per_unit": "Infinity",
    }]}
    before = _write_counts()

    order = client.post("/api/purchasing/orders", json=order_payload, headers=auth_headers)
    receipt = client.post(
        "/api/purchasing/orders/1/receive",
        json=receipt_payload,
        headers=auth_headers,
    )
    assert order.status_code == 422, order.text
    assert receipt.status_code == 422, receipt.text

    assert client.post(
        "/api/purchasing/orders",
        json=order_payload,
        headers=denied_headers,
    ).status_code == 403
    assert client.post(
        "/api/purchasing/orders/1/receive",
        json=receipt_payload,
        headers=denied_headers,
    ).status_code == 403
    assert client.post("/api/purchasing/orders", json=order_payload).status_code == 401
    assert client.post(
        "/api/purchasing/orders/1/receive",
        json=receipt_payload,
    ).status_code == 401
    assert _write_counts() == before
