from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.models import AuditLog, StockBatch, StockMovement, Warehouse
from app.schemas.inventory import StockQuantityAdjustmentIn


MAX_STOCK_QUANTITY = Decimal("9999999999.9999")


def _create_item(client, auth_headers) -> int:
    suffix = uuid4().hex[:10].upper()
    response = client.post(
        "/api/inventory/items",
        headers=auth_headers,
        json={
            "sku": f"ADJ-BOUND-{suffix}",
            "name": f"Adjustment bound {suffix}",
            "category": "accessory",
            "unit": "pcs",
            "default_cost": 1,
            "reorder_level": 0,
            "track_batch": False,
        },
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def _write_counts(item_id: int) -> tuple[int, int]:
    with SessionLocal() as db:
        return (
            db.query(StockMovement).filter(StockMovement.item_id == item_id).count(),
            db.query(AuditLog).count(),
        )


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "10000000000"])
def test_stock_adjustment_rejects_non_finite_and_storage_overflow(value):
    with pytest.raises(ValidationError):
        StockQuantityAdjustmentIn(quantity=value)


def test_stock_adjustment_preserves_zero_ordinary_and_exact_storage_maximum():
    assert StockQuantityAdjustmentIn(quantity=0).quantity == 0
    assert StockQuantityAdjustmentIn(quantity="12.34567").quantity == pytest.approx(12.34567)
    maximum = StockQuantityAdjustmentIn(quantity=str(MAX_STOCK_QUANTITY))
    assert maximum.quantity == pytest.approx(float(MAX_STOCK_QUANTITY))


@pytest.mark.parametrize("value", ["Infinity", "10000000000"])
def test_invalid_stock_adjustment_has_no_movement_or_audit_side_effects(
    client,
    auth_headers,
    value,
):
    item_id = _create_item(client, auth_headers)
    before = _write_counts(item_id)

    response = client.patch(
        f"/api/inventory/stock/{item_id}",
        headers=auth_headers,
        json={"quantity": value, "unit": "pcs"},
    )

    assert response.status_code == 422, response.text
    assert _write_counts(item_id) == before


def test_stock_adjustment_storage_maximum_persists_exactly(client, auth_headers):
    item_id = _create_item(client, auth_headers)

    response = client.patch(
        f"/api/inventory/stock/{item_id}",
        headers=auth_headers,
        json={"quantity": str(MAX_STOCK_QUANTITY), "unit": "pcs"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["quantity"] == pytest.approx(float(MAX_STOCK_QUANTITY))
    with SessionLocal() as db:
        movement = (
            db.query(StockMovement)
            .filter(
                StockMovement.item_id == item_id,
                StockMovement.reference_type == "StockAdjustment",
            )
            .one()
        )
        assert movement.quantity == MAX_STOCK_QUANTITY


def test_batch_tracked_adjustment_uses_matching_category_storage(client, auth_headers):
    suffix = uuid4().hex[:10].upper()
    item_response = client.post("/api/inventory/items", headers=auth_headers, json={
        "sku": f"ADJ-BATCH-{suffix}", "name": f"Adjustment batch {suffix}",
        "category": "accessory", "unit": "pcs", "default_cost": 1,
        "reorder_level": 0, "track_batch": True,
    })
    assert item_response.status_code == 201, item_response.text
    item_id = int(item_response.json()["id"])

    adjusted = client.patch(
        f"/api/inventory/stock/{item_id}", headers=auth_headers,
        json={"quantity": 3, "unit": "pcs"},
    )

    assert adjusted.status_code == 200, adjusted.text
    with SessionLocal() as db:
        batch = db.query(StockBatch).filter_by(item_id=item_id).one()
        warehouse = db.get(Warehouse, batch.warehouse_id)
        movement = db.query(StockMovement).filter_by(batch_id=batch.id).one()
        assert warehouse.type == "accessory_storage"
        assert movement.item_id == batch.item_id == item_id
        assert movement.to_warehouse_id == batch.warehouse_id
        assert movement.quantity == batch.quantity == Decimal("3")


@pytest.mark.parametrize(
    ("archived", "target_quantity"),
    [(False, 6), (False, 5), (True, 6), (True, 5)],
)
def test_batch_tracked_adjustment_rejects_legacy_unit_drift_without_writes(
    client, auth_headers, archived, target_quantity,
):
    suffix = uuid4().hex[:10].upper()
    item_response = client.post("/api/inventory/items", headers=auth_headers, json={
        "sku": f"ADJ-DRIFT-{suffix}", "name": f"Adjustment drift {suffix}",
        "category": "accessory", "unit": "pcs", "default_cost": 1,
        "reorder_level": 0, "track_batch": True,
    })
    assert item_response.status_code == 201, item_response.text
    item_id = int(item_response.json()["id"])

    with SessionLocal() as db:
        warehouse = db.query(Warehouse).filter_by(type="accessory_storage").first()
        assert warehouse is not None
        batch = StockBatch(
            item_id=item_id,
            batch_no=f"LEGACY-DRIFT-{suffix}",
            quantity=5,
            unit="kg",
            cost_per_unit=1,
            warehouse_id=warehouse.id,
            qc_status="passed",
            archived_at=datetime.utcnow() if archived else None,
        )
        db.add(batch)
        db.commit()
        batch_id = int(batch.id)
    with SessionLocal() as db:
        before = (
            db.query(StockBatch).filter_by(item_id=item_id).count(),
            db.query(StockMovement).filter_by(item_id=item_id).count(),
            db.query(AuditLog).count(),
        )

    response = client.patch(
        f"/api/inventory/stock/{item_id}",
        headers=auth_headers,
        json={"quantity": target_quantity, "unit": "pcs"},
    )

    assert response.status_code == 409, response.text
    assert "unit differs from the item" in response.text
    with SessionLocal() as db:
        after = (
            db.query(StockBatch).filter_by(item_id=item_id).count(),
            db.query(StockMovement).filter_by(item_id=item_id).count(),
            db.query(AuditLog).count(),
        )
        assert db.get(StockBatch, batch_id).quantity == Decimal("5")
        assert (db.get(StockBatch, batch_id).archived_at is not None) is archived
    assert after == before


def test_stock_adjustment_rejects_derived_delta_overflow_without_writes(client, auth_headers):
    item_id = _create_item(client, auth_headers)
    with SessionLocal() as db:
        db.add(StockMovement(
            movement_type="issue",
            item_id=item_id,
            quantity=Decimal("0.0001"),
            unit="pcs",
            reference_type="SyntheticBoundSetup",
        ))
        db.commit()
    before = _write_counts(item_id)

    response = client.patch(
        f"/api/inventory/stock/{item_id}",
        headers=auth_headers,
        json={"quantity": str(MAX_STOCK_QUANTITY), "unit": "pcs"},
    )

    assert response.status_code == 422, response.text
    assert "delta exceeds" in response.text
    assert _write_counts(item_id) == before


def test_invalid_stock_adjustment_preserves_authentication_precedence(client, auth_headers):
    item_id = _create_item(client, auth_headers)
    before = _write_counts(item_id)

    response = client.patch(
        f"/api/inventory/stock/{item_id}",
        json={"quantity": "Infinity", "unit": "pcs"},
    )

    assert response.status_code == 401, response.text
    assert _write_counts(item_id) == before
