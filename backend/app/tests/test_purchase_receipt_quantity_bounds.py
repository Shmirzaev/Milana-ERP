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


def _receive_line(quantity, **overrides):
    return PurchaseOrderReceiveLineIn.model_validate({
        "purchase_order_line_id": 1,
        "received_quantity": quantity,
        "batch_no": "BOUNDARY-BATCH",
        **overrides,
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


def _payload(order: dict[str, int | str], quantity, **overrides) -> dict:
    return {"lines": [{
        "purchase_order_line_id": order["line_id"],
        "received_quantity": quantity,
        "batch_no": order["batch_no"],
        "warehouse_id": order["warehouse_id"],
        **overrides,
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
    ordinary = _receive_line("12.3456")
    maximum = _receive_line("9999999999.9999")

    assert isinstance(ordinary.received_quantity, float)
    assert ordinary.received_quantity == 12.3456
    assert maximum.received_quantity == 9999999999.9999


def test_purchase_receipt_dimensions_accept_numeric_column_boundaries():
    maximum_width = _receive_line(1, width="99999999.99")
    minimum_width = _receive_line(1, width="-99999999.99")
    maximum_gsm = _receive_line(1, gsm="99999999.999999")
    minimum_gsm = _receive_line(1, gsm="-99999999.999999")

    assert maximum_width.width == 99_999_999.99
    assert minimum_width.width == -99_999_999.99
    assert maximum_gsm.gsm == 99_999_999.999999
    assert minimum_gsm.gsm == -99_999_999.999999


@pytest.mark.parametrize("quantity", ["Infinity", "-Infinity", "NaN", "0", "10000000000", "1.00001"])
def test_purchase_receipt_quantity_rejects_invalid_or_unrepresentable_values(quantity):
    with pytest.raises(ValidationError):
        _receive_line(quantity)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("width", "100000000"),
        ("width", "-100000000"),
        ("width", "NaN"),
        ("width", "Infinity"),
        ("gsm", "100000000"),
        ("gsm", "-100000000"),
        ("gsm", "NaN"),
        ("gsm", "-Infinity"),
    ],
)
def test_purchase_receipt_dimensions_reject_nonfinite_or_unrepresentable_values(field, value):
    with pytest.raises(ValidationError):
        _receive_line(1, **{field: value})


def test_purchase_receipt_quantity_keeps_idempotent_valid_receipts(client, auth_headers):
    order = _seed_order()
    headers = {**auth_headers, "Idempotency-Key": f"receipt-bound-{uuid4()}"}
    payload = _payload(order, "12.3456")

    first = client.post(
        f"/api/purchasing/orders/{order['order_id']}/receive",
        json=payload,
        headers=headers,
    )
    assert first.status_code == 200, first.text
    assert first.json()["lines"][0]["received_quantity"] == pytest.approx(12.3456)
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

    for quantity in ("Infinity", "10000000000", "1.00001"):
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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("width", "100000000"),
        ("width", "NaN"),
        ("gsm", "100000000"),
        ("gsm", "Infinity"),
    ],
)
def test_purchase_receipt_dimensions_reject_before_side_effects(
    client, auth_headers, field, value
):
    order = _seed_order()
    before = _state(order)

    response = client.post(
        f"/api/purchasing/orders/{order['order_id']}/receive",
        json=_payload(order, 1, **{field: value}),
        headers=auth_headers,
    )

    assert response.status_code == 422, response.text
    assert _state(order) == before
