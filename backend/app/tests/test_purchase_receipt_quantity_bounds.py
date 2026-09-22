from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import (
    AuditLog,
    IdempotencyRecord,
    Item,
    PurchaseOrder,
    PurchaseOrderLine,
    Role,
    StockBatch,
    StockMovement,
    User,
    Warehouse,
)
from app.schemas.purchasing import PurchaseOrderReceiveLineIn


def _receive_line(quantity):
    return PurchaseOrderReceiveLineIn.model_validate({
        "purchase_order_line_id": 1,
        "received_quantity": quantity,
        "batch_no": "BOUNDARY-BATCH",
    })


def _seed_order(*, received_quantity: Decimal = Decimal("0")) -> dict[str, int | str]:
    marker = uuid4().hex[:10].upper()
    with SessionLocal() as db:
        item = Item(
            sku=f"RECEIPT-BOUND-{marker}",
            name=f"Receipt quantity {marker}",
            category="accessory",
            unit="pcs",
            default_cost=1,
            reorder_level=0,
            track_batch=True,
            is_active=True,
        )
        warehouse = Warehouse(name=f"Receipt quantity {marker}", type="accessory_storage")
        order = PurchaseOrder(po_no=f"PUR-BOUND-{marker}", status="sent")
        db.add_all([item, warehouse, order])
        db.flush()
        line = PurchaseOrderLine(
            purchase_order_id=order.id,
            item_id=item.id,
            ordered_quantity=Decimal("9999999999.9999"),
            received_quantity=received_quantity,
            unit="pcs",
            unit_cost=1,
            warehouse_id=warehouse.id,
        )
        db.add(line)
        db.commit()
        return {
            "order_id": int(order.id),
            "line_id": int(line.id),
            "warehouse_id": int(warehouse.id),
            "batch_no": f"BOUND-{marker}",
        }


def _payload(order: dict[str, int | str], quantity) -> dict:
    return {"lines": [{
        "purchase_order_line_id": order["line_id"],
        "received_quantity": quantity,
        "batch_no": order["batch_no"],
        "warehouse_id": order["warehouse_id"],
    }]}


def _state(order: dict[str, int | str]):
    with SessionLocal() as db:
        return (
            db.get(PurchaseOrderLine, order["line_id"]).received_quantity,
            db.query(StockBatch).filter(StockBatch.batch_no == order["batch_no"]).count(),
            db.query(StockMovement).filter(
                StockMovement.reference_type == "PurchaseOrderLine",
                StockMovement.reference_id == order["line_id"],
            ).count(),
            db.query(AuditLog).count(),
            db.query(IdempotencyRecord).count(),
        )


def test_purchase_receipt_quantity_preserves_float_contract_and_storage_boundary():
    ordinary = _receive_line("12.34567")
    maximum = _receive_line("9999999999.9999")

    assert isinstance(ordinary.received_quantity, float)
    assert ordinary.received_quantity == 12.34567
    assert maximum.received_quantity == 9999999999.9999


@pytest.mark.parametrize("quantity", ["Infinity", "-Infinity", "NaN", "0", "10000000000"])
def test_purchase_receipt_quantity_rejects_invalid_or_unrepresentable_values(quantity):
    with pytest.raises(ValidationError):
        _receive_line(quantity)


def test_purchase_receipt_quantity_keeps_idempotent_valid_receipts(client, auth_headers):
    order = _seed_order()
    headers = {**auth_headers, "Idempotency-Key": f"receipt-bound-{uuid4()}"}
    payload = _payload(order, "12.34567")

    first = client.post(
        f"/api/purchasing/orders/{order['order_id']}/receive",
        json=payload,
        headers=headers,
    )
    assert first.status_code == 200, first.text
    assert first.json()["lines"][0]["received_quantity"] == pytest.approx(12.34567)
    after_first = _state(order)

    replay = client.post(
        f"/api/purchasing/orders/{order['order_id']}/receive",
        json=payload,
        headers=headers,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()
    assert _state(order) == after_first
    assert after_first[1:3] == (1, 1)


def test_purchase_receipt_quantity_rejects_before_side_effects_and_preserves_auth(client, auth_headers):
    order = _seed_order(received_quantity=Decimal("9999999999.5000"))
    with SessionLocal() as db:
        denied_role = Role(name=f"No purchasing receive {uuid4().hex}", permissions=[])
        db.add(denied_role)
        db.flush()
        denied_user = User(
            name="Denied purchase receiver",
            email=f"denied-purchase-receive-{uuid4().hex}@example.com",
            password_hash="unused-purchase-receive-bound-hash",
            role_id=denied_role.id,
            factory_code="MIL",
            extra_permissions=[],
            is_active=True,
        )
        db.add(denied_user)
        db.commit()
        denied_headers = {"Authorization": f"Bearer {create_access_token(denied_user.id)}"}
    before = _state(order)

    for quantity in ("Infinity", "10000000000"):
        response = client.post(
            f"/api/purchasing/orders/{order['order_id']}/receive",
            json=_payload(order, quantity),
            headers=auth_headers,
        )
        assert response.status_code == 422, (quantity, response.text)

    cumulative = client.post(
        f"/api/purchasing/orders/{order['order_id']}/receive",
        json=_payload(order, 1),
        headers=auth_headers,
    )
    assert cumulative.status_code == 400, cumulative.text
    assert "supported maximum" in cumulative.text

    assert client.post(
        f"/api/purchasing/orders/{order['order_id']}/receive",
        json=_payload(order, "Infinity"),
        headers=denied_headers,
    ).status_code == 403
    assert client.post(
        f"/api/purchasing/orders/{order['order_id']}/receive",
        json=_payload(order, "Infinity"),
    ).status_code == 401
    assert _state(order) == before
