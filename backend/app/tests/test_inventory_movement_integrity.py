from decimal import Decimal
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.api.routes import inventory as inventory_routes
from app.db import session as session_module
from app.models import (
    AuditLog, ForecastRecommendation, IdempotencyRecord, Item, MaterialReservation, Model, ProductionOrder,
    StockBatch, StockMovement, User, Warehouse,
)
from app.models.eco_transfer import EcoFabricDispatch, EcoFabricRoll
from app.services.inventory import current_stock_for_item


@pytest.fixture
def movement_stock(client, auth_headers):
    with session_module.SessionLocal() as db:
        item = Item(sku="MOVEMENT-TEST", name="Movement test", category="accessory", unit="pcs")
        other = Item(sku="MOVEMENT-OTHER", name="Other item", category="accessory", unit="pcs")
        source = Warehouse(name="Movement source", type="accessory_storage")
        destination = Warehouse(name="Movement destination", type="accessory_storage")
        db.add_all([item, other, source, destination])
        db.flush()
        ids = dict(item_id=item.id, other_item_id=other.id, source_id=source.id, destination_id=destination.id)
        db.commit()
    receipt = client.post("/api/inventory/receive", headers=auth_headers, json={
        "item_id": ids["item_id"], "batch_no": "MOVEMENT-TEST", "quantity": 10,
        "unit": "pcs", "warehouse_id": ids["source_id"], "qc_status": "passed",
    })
    assert receipt.status_code == 201, receipt.text
    ids["batch_id"] = receipt.json()["id"]
    return ids


def movement_payload(stock, movement_type="issue", **overrides):
    payload = {
        "movement_type": movement_type, "item_id": stock["item_id"], "batch_id": stock["batch_id"],
        "quantity": 4, "unit": "pcs",
    }
    if movement_type in {"issue", "consume", "transfer"}:
        payload["from_warehouse_id"] = stock["source_id"]
    if movement_type in {"adjustment", "return"}:
        payload["to_warehouse_id"] = stock["source_id"]
    if movement_type == "transfer":
        payload["to_warehouse_id"] = stock["destination_id"]
    return {**payload, **overrides}


def stock_state(stock):
    with session_module.SessionLocal() as db:
        batch = db.get(StockBatch, stock["batch_id"])
        return (
            batch.quantity, batch.warehouse_id, batch.archived_at,
            db.query(StockMovement).count(), db.query(AuditLog).count(), db.query(IdempotencyRecord).count(),
        )


def assert_batch_ledger(stock, expected):
    with session_module.SessionLocal() as db:
        batch = db.get(StockBatch, stock["batch_id"])
        movements = db.query(StockMovement).filter_by(batch_id=batch.id).all()
        ledger = sum(
            movement.quantity * (-1 if movement.movement_type in {"issue", "consume"} else 1)
            for movement in movements if movement.movement_type != "transfer"
        )
        assert batch.quantity == Decimal(str(expected))
        assert ledger == batch.quantity
        assert current_stock_for_item(db, stock["item_id"]) == float(batch.quantity)


@pytest.mark.parametrize(("movement_type", "expected"), [
    ("issue", 6), ("consume", 6), ("return", 14), ("adjustment", 14),
])
def test_batch_movements_update_balance_and_ledger(client, auth_headers, movement_stock, movement_type, expected):
    assert_batch_ledger(movement_stock, 10)
    response = client.post("/api/inventory/transfer", headers=auth_headers,
                           json=movement_payload(movement_stock, movement_type))
    assert response.status_code == 201, response.text
    assert response.json()["quantity"] == 4
    assert_batch_ledger(movement_stock, expected)


def test_mismatched_item_and_batch_rejected_without_writes(client, auth_headers, movement_stock):
    before = stock_state(movement_stock)
    response = client.post("/api/inventory/transfer", headers={**auth_headers, "Idempotency-Key": "mismatch"},
                           json=movement_payload(movement_stock, item_id=movement_stock["other_item_id"]))
    assert response.status_code == 409, response.text
    assert stock_state(movement_stock) == before


def test_item_unit_change_with_stock_history_rejected_but_metadata_edit_remains_allowed(
    client, auth_headers, movement_stock,
):
    before = stock_state(movement_stock)
    common_payload = {
        "sku": "MOVEMENT-TEST",
        "category": "accessory",
        "default_cost": 0,
        "reorder_level": 0,
        "track_batch": False,
        "is_active": True,
        "composition": [],
    }

    rejected = client.patch(
        f"/api/inventory/items/{movement_stock['item_id']}",
        headers=auth_headers,
        json={**common_payload, "name": "Should not persist", "unit": "box"},
    )

    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["detail"] == "Cannot change material unit while quantity records exist"
    assert stock_state(movement_stock) == before
    with session_module.SessionLocal() as db:
        item = db.get(Item, movement_stock["item_id"])
        batch = db.get(StockBatch, movement_stock["batch_id"])
        movements = db.query(StockMovement).filter_by(batch_id=batch.id).all()
        assert item.name == "Movement test"
        assert item.unit == "pcs"
        assert batch.unit == "pcs"
        assert all(row.unit == "pcs" for row in movements)

    metadata = client.patch(
        f"/api/inventory/items/{movement_stock['item_id']}",
        headers=auth_headers,
        json={**common_payload, "name": "Metadata edit allowed", "unit": "pcs"},
    )
    assert metadata.status_code == 200, metadata.text
    assert metadata.json()["name"] == "Metadata edit allowed"
    assert metadata.json()["unit"] == "pcs"


def test_item_unit_change_with_forecast_quantity_reference_rejected_without_writes(
    client, auth_headers,
):
    created = client.post("/api/inventory/items", headers=auth_headers, json={
        "sku": "FORECAST-UNIT-GUARD",
        "name": "Forecast unit guard",
        "category": "accessory",
        "unit": "pcs",
        "default_cost": 1,
        "reorder_level": 0,
        "track_batch": False,
        "is_active": True,
    })
    assert created.status_code == 201, created.text
    item_id = created.json()["id"]
    with session_module.SessionLocal() as db:
        db.add(ForecastRecommendation(
            recommendation_type="purchase",
            item_id=item_id,
            suggested_quantity=8,
            unit="pcs",
            status="open",
        ))
        db.commit()
        before_audits = db.query(AuditLog).count()

    rejected = client.patch(f"/api/inventory/items/{item_id}", headers=auth_headers, json={
        "sku": "FORECAST-UNIT-GUARD",
        "name": "Must not rename",
        "category": "accessory",
        "unit": "box",
        "default_cost": 1,
        "reorder_level": 0,
        "track_batch": False,
        "is_active": True,
        "composition": [],
    })

    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["detail"] == "Cannot change material unit while quantity records exist"
    with session_module.SessionLocal() as db:
        item = db.get(Item, item_id)
        recommendation = db.query(ForecastRecommendation).filter_by(item_id=item_id).one()
        assert (item.name, item.unit) == ("Forecast unit guard", "pcs")
        assert (recommendation.suggested_quantity, recommendation.unit) == (8, "pcs")
        assert db.query(AuditLog).count() == before_audits


@pytest.mark.parametrize("quantity", [0, -1, "NaN", "Infinity", "-Infinity", 0.00001, 10000000000])
def test_invalid_movement_quantity_rejected_without_writes(client, auth_headers, movement_stock, quantity):
    before = stock_state(movement_stock)
    response = client.post("/api/inventory/transfer", headers=auth_headers,
                           json=movement_payload(movement_stock, quantity=quantity))
    assert response.status_code == 400, response.text
    assert stock_state(movement_stock) == before


@pytest.mark.parametrize(("overrides", "expected_status"), [
    ({"unit": "kg"}, 409), ({"from_warehouse_id": -1}, 404),
    ({"batch_id": -1}, 404), ({"item_id": -1}, 404),
    ({"quantity": 11}, 409), ({"movement_type": "invalid"}, 400),
    ({"reference_type": "ProductionOrder"}, 400), ({"reference_id": -1}, 400),
])
def test_invalid_batch_movement_rejected_without_writes(client, auth_headers, movement_stock, overrides, expected_status):
    before = stock_state(movement_stock)
    response = client.post("/api/inventory/transfer", headers=auth_headers,
                           json=movement_payload(movement_stock, **overrides))
    assert response.status_code == expected_status, response.text
    assert stock_state(movement_stock) == before


@pytest.mark.parametrize("movement_type", ["issue", "consume", "return", "adjustment", "transfer"])
def test_wrong_batch_warehouse_rejected_without_writes(client, auth_headers, movement_stock, movement_type):
    location = "to_warehouse_id" if movement_type in {"return", "adjustment"} else "from_warehouse_id"
    before = stock_state(movement_stock)
    response = client.post("/api/inventory/transfer", headers=auth_headers, json=movement_payload(
        movement_stock, movement_type, **{location: movement_stock["destination_id"]},
    ))
    assert response.status_code == 409, response.text
    assert stock_state(movement_stock) == before


@pytest.mark.parametrize("movement_type", ["issue", "consume", "return", "adjustment"])
def test_batch_movement_infers_omitted_location(client, auth_headers, movement_stock, movement_type):
    location = "to_warehouse_id" if movement_type in {"return", "adjustment"} else "from_warehouse_id"
    payload = movement_payload(movement_stock, movement_type)
    payload.pop(location)
    response = client.post("/api/inventory/transfer", headers=auth_headers, json=payload)
    assert response.status_code == 201, response.text
    assert response.json()[location] == movement_stock["source_id"]
    assert_batch_ledger(movement_stock, 14 if movement_type in {"return", "adjustment"} else 6)


def test_entire_batch_transfer_moves_location_once(client, auth_headers, movement_stock):
    payload = movement_payload(movement_stock, "transfer", quantity=10)
    headers = {**auth_headers, "Idempotency-Key": "batch-transfer"}
    response = client.post("/api/inventory/transfer", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    assert_batch_ledger(movement_stock, 10)
    with session_module.SessionLocal() as db:
        assert db.get(StockBatch, movement_stock["batch_id"]).warehouse_id == movement_stock["destination_id"]
        assert current_stock_for_item(db, movement_stock["item_id"], movement_stock["source_id"]) == 0
        assert current_stock_for_item(db, movement_stock["item_id"], movement_stock["destination_id"]) == 10
    before_replay = stock_state(movement_stock)
    replay = client.post("/api/inventory/transfer", headers=headers, json=payload)
    assert replay.status_code == 201, replay.text
    assert replay.json() == response.json()
    assert stock_state(movement_stock) == before_replay


@pytest.mark.parametrize(("overrides", "expected_status"), [
    ({"quantity": 4}, 409), ({"quantity": 10, "to_warehouse_id": None}, 400),
])
def test_partial_or_incomplete_transfer_rejected(client, auth_headers, movement_stock, overrides, expected_status):
    before = stock_state(movement_stock)
    response = client.post("/api/inventory/transfer", headers=auth_headers,
                           json=movement_payload(movement_stock, "transfer", **overrides))
    assert response.status_code == expected_status, response.text
    assert stock_state(movement_stock) == before


def test_same_warehouse_transfer_rejected(client, auth_headers, movement_stock):
    before = stock_state(movement_stock)
    response = client.post("/api/inventory/transfer", headers=auth_headers, json=movement_payload(
        movement_stock, "transfer", quantity=10, to_warehouse_id=movement_stock["source_id"],
    ))
    assert response.status_code == 400, response.text
    assert stock_state(movement_stock) == before


def test_transfer_rejects_destination_for_wrong_item_category_without_writes(
    client, auth_headers, movement_stock,
):
    with session_module.SessionLocal() as db:
        wrong_destination = Warehouse(name="Movement fabric destination", type="fabric_storage")
        db.add(wrong_destination)
        db.commit()
        wrong_destination_id = wrong_destination.id
    before = stock_state(movement_stock)

    response = client.post("/api/inventory/transfer", headers=auth_headers, json=movement_payload(
        movement_stock, "transfer", quantity=10, to_warehouse_id=wrong_destination_id,
    ))

    assert response.status_code == 400, response.text
    assert "Accessory Storage" in response.text
    assert stock_state(movement_stock) == before


def test_batch_edit_rejects_wrong_category_warehouse_without_writes(
    client, auth_headers, movement_stock,
):
    with session_module.SessionLocal() as db:
        wrong_destination = Warehouse(name="Batch edit fabric destination", type="fabric_storage")
        db.add(wrong_destination)
        db.commit()
        wrong_destination_id = wrong_destination.id
    before = stock_state(movement_stock)

    response = client.patch(
        f"/api/inventory/batches/{movement_stock['batch_id']}",
        headers=auth_headers,
        json={"warehouse_id": wrong_destination_id},
    )

    assert response.status_code == 400, response.text
    assert "Accessory Storage" in response.text
    assert stock_state(movement_stock) == before


@pytest.mark.parametrize("movement_type", ["issue", "consume", "transfer"])
def test_movement_cannot_spend_or_move_reserved_stock(client, auth_headers, movement_stock, movement_type):
    with session_module.SessionLocal() as db:
        order = ProductionOrder(production_no="MOVEMENT-RESERVATION", production_type="branded_stock",
                                model_id=db.query(Model.id).first()[0], planned_quantity=1)
        db.add(order)
        db.flush()
        db.add(MaterialReservation(
            reservation_no="MOVEMENT-RESERVATION", production_order_id=order.id,
            item_id=movement_stock["item_id"], stock_batch_id=movement_stock["batch_id"],
            warehouse_id=movement_stock["source_id"], reserved_quantity=7, unit="pcs",
        ))
        db.commit()
    before = stock_state(movement_stock)
    response = client.post("/api/inventory/transfer", headers=auth_headers, json=movement_payload(
        movement_stock, movement_type, quantity=10 if movement_type == "transfer" else 4,
    ))
    assert response.status_code == 409, response.text
    assert stock_state(movement_stock) == before
    if movement_type != "transfer":
        allowed = client.post("/api/inventory/transfer", headers=auth_headers,
                              json=movement_payload(movement_stock, movement_type, quantity=3))
        assert allowed.status_code == 201, allowed.text
        assert_batch_ledger(movement_stock, 7)


@pytest.mark.parametrize("movement_type", ["issue", "consume", "return", "adjustment", "transfer"])
def test_batch_with_outstanding_eco_custody_cannot_be_changed(client, auth_headers, movement_stock, movement_type):
    with session_module.SessionLocal() as db:
        user = db.query(User).filter_by(email="admin@example.com").one()
        dispatch = EcoFabricDispatch(request_key="movement-custody", created_by=user.id, operator_name=user.name)
        db.add(dispatch)
        db.flush()
        db.add(EcoFabricRoll(
            dispatch_id=dispatch.id, batch_id=movement_stock["batch_id"], roll_number=1,
            fabric_name="Movement test", batch_no="MOVEMENT-TEST", quantity=1, unit="pcs",
        ))
        db.commit()
    before = stock_state(movement_stock)
    response = client.post("/api/inventory/transfer", headers=auth_headers,
                           json=movement_payload(movement_stock, movement_type, quantity=10))
    assert response.status_code == 409, response.text
    assert stock_state(movement_stock) == before


def test_archived_batch_cannot_be_changed(client, auth_headers, movement_stock):
    with session_module.SessionLocal() as db:
        db.get(StockBatch, movement_stock["batch_id"]).archived_at = datetime.now(timezone.utc)
        db.commit()
    before = stock_state(movement_stock)
    response = client.post("/api/inventory/transfer", headers=auth_headers,
                           json=movement_payload(movement_stock, "return"))
    assert response.status_code == 404, response.text
    assert stock_state(movement_stock) == before


def test_issue_retry_does_not_decrement_twice(client, auth_headers, movement_stock):
    headers = {**auth_headers, "Idempotency-Key": "batch-issue"}
    payload = movement_payload(movement_stock)
    first = client.post("/api/inventory/transfer", headers=headers, json=payload)
    assert first.status_code == 201, first.text
    before_replay = stock_state(movement_stock)
    second = client.post("/api/inventory/transfer", headers=headers, json=payload)
    assert second.status_code == 201, second.text
    assert first.json() == second.json()
    assert stock_state(movement_stock) == before_replay
    assert_batch_ledger(movement_stock, 6)


def test_late_failure_rolls_back_balance_and_ledger(client, auth_headers, movement_stock, monkeypatch):
    def fail_audit(*args, **kwargs):
        raise HTTPException(503, "Synthetic audit failure")

    monkeypatch.setattr(inventory_routes, "log_action", fail_audit)
    before = stock_state(movement_stock)
    response = client.post("/api/inventory/transfer", headers=auth_headers,
                           json=movement_payload(movement_stock))
    assert response.status_code == 503, response.text
    assert stock_state(movement_stock) == before


def test_fractional_batch_ledger_stays_exact(client, auth_headers, movement_stock):
    for quantity in (0.1001, 0.2002):
        response = client.post("/api/inventory/transfer", headers=auth_headers,
                               json=movement_payload(movement_stock, quantity=quantity))
        assert response.status_code == 201, response.text
    assert_batch_ledger(movement_stock, "9.6997")


@pytest.mark.parametrize(("movement_type", "expected"), [("issue", 6), ("consume", 6), ("return", 14), ("adjustment", 14)])
def test_batchless_movement_keeps_existing_ledger_behavior(client, auth_headers, movement_stock, movement_type, expected):
    response = client.post("/api/inventory/transfer", headers=auth_headers,
                           json=movement_payload(movement_stock, movement_type, batch_id=None))
    assert response.status_code == 201, response.text
    with session_module.SessionLocal() as db:
        assert db.get(StockBatch, movement_stock["batch_id"]).quantity == 10
        assert current_stock_for_item(db, movement_stock["item_id"]) == expected
