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
from app.schemas.inventory import StockBatchIn, StockBatchUpdate
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
            db.query(PurchaseOrderLine.id, PurchaseOrderLine.unit_cost).order_by(PurchaseOrderLine.id).all(),
            db.query(StockBatch.id, StockBatch.cost_per_unit).order_by(StockBatch.id).all(),
        )


def _batch(cost):
    return StockBatchIn.model_validate({
        "item_id": 1, "batch_no": "COST-BOUND", "quantity": 1,
        "unit": "pcs", "warehouse_id": 1, "cost_per_unit": cost,
    })


def test_purchase_and_stock_costs_preserve_float_contract_and_storage_boundary():
    order_ordinary = _order_line("12.3456")
    order_maximum = _order_line("99999999.9999")
    receipt_ordinary = _receipt_line("12.3456")
    receipt_maximum = _receipt_line("99999999.9999")

    assert isinstance(order_ordinary.unit_cost, float)
    assert order_ordinary.unit_cost == 12.3456
    assert order_maximum.unit_cost == 99999999.9999
    assert _order_line("-1").unit_cost == -1
    assert _receipt_line(None).cost_per_unit is None
    assert receipt_ordinary.cost_per_unit == 12.3456
    assert receipt_maximum.cost_per_unit == 99999999.9999
    assert _batch("12.345600").cost_per_unit == 12.3456
    assert StockBatchUpdate(cost_per_unit="99999999.9999").cost_per_unit == 99999999.9999
    assert "cost_per_unit" not in StockBatchUpdate(batch_no="UNCHANGED").model_dump(exclude_unset=True)


@pytest.mark.parametrize("builder", [_order_line, _receipt_line, _batch, lambda cost: StockBatchUpdate(cost_per_unit=cost)])
@pytest.mark.parametrize("cost", ["12.34567", "0.00001", "99999998.99991"])
def test_purchase_and_stock_costs_reject_extra_fractional_places(builder, cost):
    with pytest.raises(ValidationError, match="4 decimal places"):
        builder(cost)


def test_purchase_order_rejects_negative_extra_fractional_place():
    with pytest.raises(ValidationError, match="4 decimal places"):
        _order_line("-0.00001")


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


def test_fractional_cost_api_rejections_do_not_write(client, auth_headers):
    before = _write_counts()
    order_payload = {"lines": [{
        "item_id": 1, "ordered_quantity": 1, "unit": "pcs", "unit_cost": "12.34567",
    }]}
    receipt_payload = {"lines": [{
        "purchase_order_line_id": 1, "received_quantity": 1,
        "batch_no": "COST-PRECISION", "cost_per_unit": "12.34567",
    }]}
    stock_payload = {
        "item_id": 1, "batch_no": "COST-PRECISION", "quantity": 1,
        "unit": "pcs", "warehouse_id": 1, "cost_per_unit": "12.34567",
    }
    responses = [
        client.post("/api/purchasing/orders", json=order_payload, headers=auth_headers),
        client.post("/api/purchasing/orders/1/receive", json=receipt_payload, headers=auth_headers),
        client.post("/api/inventory/receive", json=stock_payload, headers=auth_headers),
        client.patch("/api/inventory/batches/1", json={"cost_per_unit": "12.34567"}, headers=auth_headers),
    ]
    assert [response.status_code for response in responses] == [422] * 4
    assert _write_counts() == before


def test_negative_order_cost_requires_nonnegative_receipt_override(client, auth_headers):
    with SessionLocal() as db:
        item = db.query(Item).filter(Item.category == "fabric").order_by(Item.id).first()
        warehouse = db.query(Warehouse).filter(Warehouse.type == "fabric_storage").order_by(Warehouse.id).first()
        assert item is not None and warehouse is not None
        item_id, item_unit, warehouse_id = item.id, item.unit, warehouse.id

    order = client.post("/api/purchasing/orders", headers=auth_headers, json={"lines": [{
        "item_id": item_id, "ordered_quantity": 1, "unit": item_unit,
        "unit_cost": -1, "warehouse_id": warehouse_id,
    }]})
    assert order.status_code == 201, order.text
    order_id = order.json()["id"]
    line_id = order.json()["lines"][0]["id"]
    with SessionLocal() as db:
        db.get(PurchaseOrder, order_id).status = "sent"
        db.commit()
    before = _write_counts()

    receipt = {"lines": [{
        "purchase_order_line_id": line_id, "received_quantity": 1,
        "batch_no": f"NEG-COST-{line_id}", "warehouse_id": warehouse_id,
    }]}
    rejected = client.post(f"/api/purchasing/orders/{order_id}/receive", headers=auth_headers, json=receipt)
    assert rejected.status_code == 422, rejected.text
    assert "nonnegative" in rejected.json()["detail"]
    assert _write_counts() == before
    with SessionLocal() as db:
        assert db.get(PurchaseOrderLine, line_id).received_quantity == 0

    receipt["lines"][0]["cost_per_unit"] = "2.1234"
    accepted = client.post(f"/api/purchasing/orders/{order_id}/receive", headers=auth_headers, json=receipt)
    assert accepted.status_code == 200, accepted.text
    with SessionLocal() as db:
        assert db.get(PurchaseOrderLine, line_id).unit_cost == Decimal("2.1234")
        assert db.query(StockBatch).filter_by(batch_no=f"NEG-COST-{line_id}").one().cost_per_unit == Decimal("2.1234")
