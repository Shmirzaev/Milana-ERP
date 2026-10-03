"""FN07-PURCHASE-QUANTITY: purchase and receipt quantity inputs must be finite and storage-bounded."""

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import Item, PurchaseOrder, PurchaseOrderLine, Role, StockBatch, User, Warehouse
from app.schemas.purchasing import (
    PurchaseOrderLineIn,
    PurchaseOrderReceiveLineIn,
    PurchaseRequestOrderLineIn,
)

# The storage bound this task requires. Declared here rather than imported so the
# test exercises the unfixed base instead of failing at import.
MAX_PURCHASE_QUANTITY = Decimal("9999999999.9999")


def _order_line(quantity):
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


def _receive_line(quantity):
    return PurchaseOrderReceiveLineIn.model_validate({
        "purchase_order_line_id": 1,
        "received_quantity": quantity,
        "batch_no": "B-1",
    })


# ---------------------------------------------------------------- schema bounds

def test_purchase_order_quantity_accepts_finite_values_and_storage_boundary():
    assert _order_line(12.3456).ordered_quantity == Decimal("12.3456")
    assert _conversion_line(12.3456).ordered_quantity == Decimal("12.3456")
    assert float(_order_line(MAX_PURCHASE_QUANTITY).ordered_quantity) == float(MAX_PURCHASE_QUANTITY)
    assert _receive_line(12.3456).received_quantity == 12.3456


@pytest.mark.parametrize("quantity", ["Infinity", "-Infinity", "NaN", "0", "-1", "10000000000"])
@pytest.mark.parametrize("builder", [_order_line, _conversion_line, _receive_line])
def test_purchase_quantity_rejects_nonfinite_zero_negative_and_overflow(builder, quantity):
    with pytest.raises(ValidationError):
        builder(quantity)


def test_purchase_receipt_quantity_rejects_overflow_but_accepts_exact_boundary():
    with pytest.raises(ValidationError):
        _receive_line(10_000_000_000)
    assert _receive_line(9_999_999_999.9999).received_quantity == pytest.approx(9_999_999_999.9999)


# --------------------------------------------------- cumulative receipt overflow

def _receiving_order(*, received_quantity, ordered_quantity=100):
    marker = uuid4().hex[:10]
    with SessionLocal() as db:
        role = Role(name=f"FN07 quantity {marker}", permissions=["*"])
        user = User(
            name=f"FN07 quantity user {marker}",
            email=f"fn07-quantity-{marker}@example.com",
            password_hash="unused-fn07-quantity-hash",
            role=role,
            factory_code="MIL",
            is_active=True,
        )
        item = Item(
            sku=f"FN07-{marker}", name=f"FN07 quantity item {marker}",
            category="material", unit="pcs", is_active=True,
        )
        warehouse = Warehouse(name=f"FN07 warehouse {marker}", type="material_storage")
        db.add_all([role, user, item, warehouse])
        db.flush()
        order = PurchaseOrder(po_no=f"FN07-{marker}", status="sent", supplier_id=None)
        db.add(order)
        db.flush()
        line = PurchaseOrderLine(
            purchase_order_id=order.id, item_id=item.id, ordered_quantity=ordered_quantity,
            received_quantity=received_quantity, unit="pcs", warehouse_id=warehouse.id,
        )
        db.add(line)
        db.commit()
        return {
            "order_id": order.id, "line_id": line.id, "item_id": item.id,
            "headers": {"Authorization": f"Bearer {create_access_token(user.id)}"},
        }


def test_accumulated_receipts_cannot_overflow_storage_column(client):
    """A per-request quantity in range must not let repeated receipts overflow the column."""
    near_limit = float(MAX_PURCHASE_QUANTITY) - 1
    account = _receiving_order(received_quantity=near_limit, ordered_quantity=near_limit)
    response = client.post(
        f"/api/purchasing/orders/{account['order_id']}/receive",
        headers=account["headers"],
        json={"lines": [{
            "purchase_order_line_id": account["line_id"],
            "received_quantity": 5,
            "batch_no": "FN07-OVERFLOW",
        }]},
    )
    assert response.status_code == 400, response.text
    assert "maximum" in response.text.lower()
    # A rejected overflow must leave quantity, batch and ledger untouched.
    with SessionLocal() as db:
        line = db.query(PurchaseOrderLine).filter(PurchaseOrderLine.id == account["line_id"]).one()
        assert float(line.received_quantity) == pytest.approx(near_limit)
        assert (
            db.query(StockBatch)
            .filter(StockBatch.batch_no == "FN07-OVERFLOW")
            .count()
            == 0
        )


def test_receipt_within_bounds_still_works_after_the_guard(client):
    account = _receiving_order(received_quantity=0, ordered_quantity=100)
    response = client.post(
        f"/api/purchasing/orders/{account['order_id']}/receive",
        headers=account["headers"],
        json={"lines": [{
            "purchase_order_line_id": account["line_id"],
            "received_quantity": 7,
            "batch_no": "FN07-OK",
        }]},
    )
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        line = db.query(PurchaseOrderLine).filter(PurchaseOrderLine.id == account["line_id"]).one()
        assert float(line.received_quantity) == pytest.approx(7)
        assert db.query(StockBatch).filter(StockBatch.batch_no == "FN07-OK").count() == 1
