from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import AuditLog, Item, PurchaseOrder, PurchaseOrderLine, Role, User
from app.schemas.purchasing import PurchaseOrderLineIn, PurchaseRequestOrderLineIn


def _direct_line(quantity):
    return PurchaseOrderLineIn.model_validate({
        "item_id": 1,
        "ordered_quantity": quantity,
        "unit": "pcs",
        "unit_cost": 1,
    })


def _conversion_line(quantity):
    return PurchaseRequestOrderLineIn.model_validate({
        "purchase_request_line_id": 1,
        "ordered_quantity": quantity,
    })


def test_purchase_order_quantity_accepts_finite_values_and_exact_storage_boundary():
    direct = _direct_line("12.3456")
    converted = _conversion_line("9999999999.9999")

    assert direct.ordered_quantity == Decimal("12.3456")
    assert converted.ordered_quantity == Decimal("9999999999.9999")


@pytest.mark.parametrize("quantity", ["Infinity", "-Infinity", "NaN", "0", "10000000000", "1.00001"])
@pytest.mark.parametrize("builder", [_direct_line, _conversion_line])
def test_purchase_order_quantity_rejects_invalid_or_unrepresentable_values(builder, quantity):
    with pytest.raises(ValidationError):
        builder(quantity)


def test_purchase_order_quantity_api_rejects_before_writes_and_preserves_auth_precedence(client, auth_headers):
    with SessionLocal() as db:
        item_unit = db.query(Item.unit).filter(Item.id == 1).scalar()
        denied_role = Role(name=f"No purchase order {uuid4().hex}", permissions=[])
        db.add(denied_role)
        db.flush()
        denied_user = User(
            name="Denied purchase order writer",
            email=f"denied-purchase-order-{uuid4().hex}@example.com",
            password_hash="unused-purchase-bound-hash",
            role_id=denied_role.id,
            factory_code="MIL",
            extra_permissions=[],
            is_active=True,
        )
        db.add(denied_user)
        db.commit()
        denied_headers = {"Authorization": f"Bearer {create_access_token(denied_user.id)}"}
        before = (
            db.query(PurchaseOrder).count(),
            db.query(PurchaseOrderLine).count(),
            db.query(AuditLog).count(),
        )

    def payload(quantity):
        return {
            "notes": "Purchase quantity boundary regression",
            "lines": [{
                "item_id": 1,
                "ordered_quantity": quantity,
                "unit": item_unit,
                "unit_cost": 1,
            }],
        }

    valid = client.post(
        "/api/purchasing/orders",
        json=payload("12.3456"),
        headers=auth_headers,
    )
    assert valid.status_code == 201, valid.text
    assert valid.json()["lines"][0]["ordered_quantity"] == pytest.approx(12.3456)

    with SessionLocal() as db:
        after_valid = (
            db.query(PurchaseOrder).count(),
            db.query(PurchaseOrderLine).count(),
            db.query(AuditLog).count(),
        )
    assert after_valid == (before[0] + 1, before[1] + 1, before[2] + 1)

    for quantity in ("Infinity", "10000000000", "1.00001"):
        response = client.post(
            "/api/purchasing/orders",
            json=payload(quantity),
            headers=auth_headers,
        )
        assert response.status_code == 422, (quantity, response.text)

    assert client.post(
        "/api/purchasing/orders",
        json=payload("Infinity"),
        headers=denied_headers,
    ).status_code == 403
    assert client.post(
        "/api/purchasing/orders",
        json=payload("Infinity"),
    ).status_code == 401

    with SessionLocal() as db:
        after_invalid = (
            db.query(PurchaseOrder).count(),
            db.query(PurchaseOrderLine).count(),
            db.query(AuditLog).count(),
        )
    assert after_invalid == after_valid
