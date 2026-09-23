"""Reject stock receipt quantities PostgreSQL NUMERIC(14, 4) cannot store."""

from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.models import AuditLog, IdempotencyRecord, Item, StockBatch, StockMovement, Warehouse


def _receipt_payload(quantity):
    with SessionLocal() as db:
        item_id = db.query(Item.id).filter(
            Item.category == "fabric", Item.is_active.is_(True),
        ).order_by(Item.id).first()[0]
        item_unit = db.query(Item.unit).filter(Item.id == item_id).scalar() or "kg"
        warehouse_id = db.query(Warehouse.id).filter(
            Warehouse.type == "fabric_storage",
        ).order_by(Warehouse.id).first()[0]
    return {
        "item_id": item_id,
        "batch_no": f"NUMERIC-BOUND-{uuid4().hex}",
        "quantity": quantity,
        "unit": item_unit,
        "cost_per_unit": 1,
        "warehouse_id": warehouse_id,
        "qc_status": "passed",
    }


def _write_counts():
    with SessionLocal() as db:
        return tuple(
            db.query(model).count()
            for model in (StockBatch, StockMovement, AuditLog, IdempotencyRecord)
        )


def test_stock_receipt_quantity_enforces_numeric_14_4_range(client, auth_headers):
    before = _write_counts()

    response = client.post(
        "/api/inventory/receive",
        headers=auth_headers,
        json=_receipt_payload(10_000_000_000),
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before


def test_stock_receipt_cost_accepts_numeric_12_4_maximum(client, auth_headers):
    response = client.post(
        "/api/inventory/receive",
        headers=auth_headers,
        json={**_receipt_payload(1), "cost_per_unit": "99999999.9999"},
    )

    assert response.status_code == 201, response.text
    with SessionLocal() as db:
        batch = db.get(StockBatch, response.json()["id"])
        assert batch is not None
        assert str(batch.cost_per_unit) == "99999999.9999"


@pytest.mark.parametrize("cost_per_unit", ["-0.0001", "NaN", "Infinity", "-Infinity", "100000000"])
def test_stock_receipt_rejects_unrepresentable_cost_without_writes(
    client, auth_headers, cost_per_unit
):
    before = _write_counts()

    response = client.post(
        "/api/inventory/receive",
        headers=auth_headers,
        json={**_receipt_payload(1), "cost_per_unit": cost_per_unit},
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before
