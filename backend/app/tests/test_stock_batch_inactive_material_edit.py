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


def test_batch_edit_movement_failure_rolls_back_batch(client, auth_headers, inactive_material_batch, monkeypatch):
    """An error after applying the correction must not persist the changed quantity."""
    from app.schemas.inventory import stock_batch_edit_persistence

    batch = inactive_material_batch
    before = _movements(batch["id"])

    def fail_movement(*args, **kwargs):
        raise RuntimeError("injected movement failure")

    monkeypatch.setattr(stock_batch_edit_persistence, "add_movement", fail_movement)
    with pytest.raises(RuntimeError, match="injected movement failure"):
        client.patch(
            f"/api/inventory/batches/{batch['id']}",
            headers=auth_headers,
            json={"quantity": batch["quantity"] + 1},
        )
    with session_module.SessionLocal() as db:
        assert float(db.get(StockBatch, batch["id"]).quantity) == batch["quantity"]
    assert _movements(batch["id"]) == before


def test_forced_relink_flush_failure_rolls_back_all_tables(client, auth_headers, inactive_material_batch, monkeypatch):
    """Flushed relinks and batch edits roll back together when the audit step fails."""
    from app.models.inventory import stock_service
    from app.schemas import MaterialReservation, Model, ModelBOM, ProductionOrder, WasteRecord

    batch = inactive_material_batch
    suffix = uuid4().hex[:12]
    with session_module.SessionLocal() as db:
        target = Item(sku=f"RELINK-TARGET-{suffix}", name=f"Target {suffix}",
                      category="fabric", unit="kg", is_active=True)
        model = Model(code=f"RELINK-{suffix}", name=f"Relink {suffix}", status="approved")
        db.add_all([target, model])
        db.flush()
        order = ProductionOrder(production_no=f"RELINK-{suffix}", production_type="branded_stock",
                                model_id=model.id, planned_quantity=1)
        db.add(order)
        db.flush()
        reservation = MaterialReservation(reservation_no=f"RELINK-{suffix}", production_order_id=order.id,
            item_id=batch["item_id"], stock_batch_id=batch["id"], warehouse_id=batch["warehouse_id"],
            reserved_quantity=1, consumed_quantity=0, released_quantity=0, unit="kg",
            status="reserved", reservation_type="material", source="manual")
        bom = ModelBOM(model_id=model.id, item_id=batch["item_id"], stock_batch_id=batch["id"],
                       quantity_per_piece=1, unit="kg")
        waste = WasteRecord(item_id=batch["item_id"], batch_id=batch["id"], waste_type="fabric",
                            quantity=1, unit="kg")
        control_bom = ModelBOM(model_id=model.id, item_id=batch["item_id"], quantity_per_piece=1, unit="kg")
        control_waste = WasteRecord(item_id=batch["item_id"], waste_type="fabric", quantity=1, unit="kg")
        control_reservation = MaterialReservation(reservation_no=f"CONTROL-{suffix}", production_order_id=order.id,
            item_id=batch["item_id"], warehouse_id=batch["warehouse_id"], reserved_quantity=1,
            consumed_quantity=0, released_quantity=0, unit="kg", status="reserved",
            reservation_type="material", source="manual")
        db.add_all([reservation, bom, waste, control_bom, control_waste, control_reservation])
        db.commit()
        ids = (target.id, reservation.id, bom.id, waste.id, control_bom.id, control_waste.id, control_reservation.id)
    target_id, reservation_id, bom_id, waste_id, control_bom_id, control_waste_id, control_reservation_id = ids
    before_movements = _movements(batch["id"])
    with session_module.SessionLocal() as db:
        before_audits = db.query(AuditLog.id).filter_by(entity_type="StockBatch", entity_id=batch["id"]).count()

    def fail_after_flush(db, *args, **kwargs):
        db.flush()
        assert db.get(StockBatch, batch["id"]).item_id == target_id
        assert db.query(MaterialReservation.item_id).filter_by(id=reservation_id).scalar() == target_id
        assert db.query(ModelBOM.item_id).filter_by(id=bom_id).scalar() == target_id
        assert db.query(WasteRecord.item_id).filter_by(id=waste_id).scalar() == target_id
        assert all(row.item_id == target_id for row in db.query(StockMovement).filter_by(batch_id=batch["id"]))
        raise RuntimeError("injected audit failure after relink")

    monkeypatch.setattr(stock_service, "log_action", fail_after_flush)
    with pytest.raises(RuntimeError, match="injected audit failure after relink"):
        client.patch(f"/api/inventory/batches/{batch['id']}?force=true", headers=auth_headers,
                     json={"item_id": target_id})
    with session_module.SessionLocal() as db:
        assert db.get(StockBatch, batch["id"]).item_id == batch["item_id"]
        assert db.get(MaterialReservation, reservation_id).item_id == batch["item_id"]
        assert db.get(ModelBOM, bom_id).item_id == batch["item_id"]
        assert db.get(WasteRecord, waste_id).item_id == batch["item_id"]
        assert db.get(MaterialReservation, control_reservation_id).item_id == batch["item_id"]
        assert db.get(ModelBOM, control_bom_id).item_id == batch["item_id"]
        assert db.get(WasteRecord, control_waste_id).item_id == batch["item_id"]
        assert db.query(AuditLog.id).filter_by(entity_type="StockBatch", entity_id=batch["id"]).count() == before_audits
    assert _movements(batch["id"]) == before_movements
