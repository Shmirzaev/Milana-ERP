"""An archived material must not prevent corrections to its existing batch."""

from uuid import uuid4

import pytest

from app.db import session as session_module
from app.schemas import AuditLog, Item, StockBatch, StockMovement


@pytest.fixture
def inactive_material_batch(client, auth_headers):
    created = client.post(
        "/api/inventory/items",
        headers=auth_headers,
        json={
            "sku": f"INACTIVE-EDIT-{uuid4().hex[:12]}",
            "name": "Archived batch material",
            "category": "fabric",
            "unit": "kg",
            "track_batch": True,
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    item = created.json()
    warehouses = client.get("/api/inventory/warehouses", headers=auth_headers)
    assert warehouses.status_code == 200, warehouses.text
    received = client.post(
        "/api/inventory/receive",
        headers=auth_headers,
        json={
            "item_id": item["id"],
            "batch_no": "7148",
            "quantity": 320.4,
            "unit": "kg",
            "cost_per_unit": 0,
            "warehouse_id": warehouses.json()[0]["id"],
            "qc_status": "passed",
        },
    )
    assert received.status_code == 201, received.text
    archived = client.patch(
        f"/api/inventory/items/{item['id']}",
        headers=auth_headers,
        json={**item, "is_active": False},
    )
    assert archived.status_code == 200, archived.text
    return received.json()


def _movements(batch_id):
    with session_module.SessionLocal() as db:
        return db.query(
            StockMovement.id, StockMovement.item_id, StockMovement.quantity,
            StockMovement.movement_type, StockMovement.reference_id,
        ).filter(StockMovement.batch_id == batch_id).order_by(StockMovement.id).all()


@pytest.mark.parametrize("force", [False, True])
def test_batch_editor_keeps_inactive_current_material(client, auth_headers, inactive_material_batch, force):
    batch = inactive_material_batch
    movements_before = _movements(batch["id"])
    payload = {
        key: batch[key]
        for key in (
            "item_id", "batch_no", "quantity", "unit", "cost_per_unit",
            "warehouse_id", "qc_status", "received_date",
        )
    }
    payload.update(piece_count=24, color="KIRMIZI", color_code="DG-50126.1")
    # Repeat a full editor save and reopen, retaining the original item each time.
    for _ in range(3):
        response = client.patch(
            f"/api/inventory/batches/{batch['id']}?force={str(force).lower()}",
            headers=auth_headers,
            json=payload,
        )
        assert response.status_code == 200, response.text
        assert response.json()["item_id"] == batch["item_id"]
        reopened = client.get(
            f"/api/inventory/batches?item_id={batch['item_id']}", headers=auth_headers,
        )
        assert reopened.status_code == 200, reopened.text
        saved = next(row for row in reopened.json() if row["id"] == batch["id"])
        assert saved["piece_count"] == 24
        assert saved["color_code"] == "DG-50126.1"
        assert saved["item_id"] == batch["item_id"]
        assert saved["quantity"] == 320.4
    with session_module.SessionLocal() as db:
        assert db.get(Item, batch["item_id"]).is_active is False
        persisted = db.get(StockBatch, batch["id"])
        assert persisted.item_id == batch["item_id"]
        assert persisted.piece_count == 24
        assert persisted.color == "KIRMIZI"
    assert _movements(batch["id"]) == movements_before


@pytest.mark.parametrize("force", [False, True])
def test_batch_editor_still_refuses_another_inactive_material(client, auth_headers, inactive_material_batch, force):
    batch = inactive_material_batch
    with session_module.SessionLocal() as db:
        target = Item(
            sku=f"INACTIVE-TARGET-{uuid4().hex[:12]}", name="Other archived material",
            category="fabric", unit="kg", is_active=False,
        )
        db.add(target)
        db.commit()
        target_id = target.id
        audit_count = db.query(AuditLog).count()
    movements_before = _movements(batch["id"])
    refused = client.patch(
        f"/api/inventory/batches/{batch['id']}?force={str(force).lower()}",
        headers=auth_headers,
        json={"item_id": target_id, "piece_count": 24},
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == "Selected material is inactive"
    with session_module.SessionLocal() as db:
        persisted = db.get(StockBatch, batch["id"])
        assert persisted.item_id == batch["item_id"]
        assert persisted.piece_count == batch["piece_count"]
        assert db.query(AuditLog).count() == audit_count
    assert _movements(batch["id"]) == movements_before
