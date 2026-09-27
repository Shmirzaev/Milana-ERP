from decimal import Decimal
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.api.routes import inventory as inventory_routes
from app.db import session as session_module
from app.models import (
    AuditLog, ForecastRecommendation, IdempotencyRecord, Item, MaterialReservation, Model, ProductionOrder,
    StockBatch, StockMovement, User, Warehouse, WasteRecord,
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


def test_direct_receipt_rejects_item_unit_mismatch_without_writes(client, auth_headers, movement_stock):
    with session_module.SessionLocal() as db:
        before = (
            db.query(StockBatch).count(), db.query(StockMovement).count(),
            db.query(AuditLog).count(), db.query(IdempotencyRecord).count(),
        )

    response = client.post(
        "/api/inventory/receive",
        headers={**auth_headers, "Idempotency-Key": "direct-unit-mismatch"},
        json={
            "item_id": movement_stock["item_id"], "batch_no": "DIRECT-UNIT-MISMATCH",
            "quantity": 3, "unit": "kg", "warehouse_id": movement_stock["source_id"],
            "qc_status": "passed",
        },
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "Batch unit must match the material unit"
    with session_module.SessionLocal() as db:
        assert (
            db.query(StockBatch).count(), db.query(StockMovement).count(),
            db.query(AuditLog).count(), db.query(IdempotencyRecord).count(),
        ) == before
        assert db.query(StockBatch).filter_by(batch_no="DIRECT-UNIT-MISMATCH").first() is None


def test_direct_receipt_checks_warehouse_before_item_unit(client, auth_headers, movement_stock):
    with session_module.SessionLocal() as db:
        wrong_warehouse = Warehouse(name="Wrong receipt warehouse", type="fabric_storage")
        db.add(wrong_warehouse)
        db.commit()
        wrong_warehouse_id = wrong_warehouse.id

    response = client.post(
        "/api/inventory/receive",
        headers=auth_headers,
        json={
            "item_id": movement_stock["item_id"], "batch_no": "WRONG-WAREHOUSE-UNIT",
            "quantity": 3, "unit": "kg", "warehouse_id": wrong_warehouse_id,
            "qc_status": "passed",
        },
    )

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "Movement test must be received into Accessory Storage"
    with session_module.SessionLocal() as db:
        assert db.query(StockBatch).filter_by(batch_no="WRONG-WAREHOUSE-UNIT").first() is None


def test_batch_reassignment_rejects_linked_unit_mismatch_without_writes(
    client, auth_headers, movement_stock,
):
    with session_module.SessionLocal() as db:
        target = Item(
            sku="MOVEMENT-OTHER-UNIT",
            name="Other unit item",
            category="accessory",
            unit="kg",
        )
        db.add(target)
        db.commit()
        target_item_id = target.id
        # Model a legacy batch already corrected to the target catalog unit,
        # while its receipt movement still carries the original unit.
        db.get(StockBatch, movement_stock["batch_id"]).unit = "kg"
        db.commit()
        before_audits = db.query(AuditLog).count()
        before_movements = [
            (row.id, row.item_id, row.batch_id, row.quantity, row.unit)
            for row in db.query(StockMovement).filter_by(batch_id=movement_stock["batch_id"]).all()
        ]

    response = client.patch(
        f"/api/inventory/batches/{movement_stock['batch_id']}",
        headers=auth_headers,
        json={"item_id": target_item_id},
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "Cannot change batch material when linked quantity units differ"
    with session_module.SessionLocal() as db:
        batch = db.get(StockBatch, movement_stock["batch_id"])
        assert (batch.item_id, batch.unit, batch.quantity) == (
            movement_stock["item_id"], "kg", Decimal("10.0000"),
        )
        assert [
            (row.id, row.item_id, row.batch_id, row.quantity, row.unit)
            for row in db.query(StockMovement).filter_by(batch_id=movement_stock["batch_id"]).all()
        ] == before_movements
        assert db.query(AuditLog).count() == before_audits


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


def test_batchless_transfer_requires_source_ledger_stock(
    client, auth_headers, movement_stock,
):
    before = stock_state(movement_stock)
    with session_module.SessionLocal() as db:
        source_before = current_stock_for_item(db, movement_stock["item_id"], movement_stock["source_id"])
        destination_before = current_stock_for_item(db, movement_stock["item_id"], movement_stock["destination_id"])

    response = client.post(
        "/api/inventory/transfer",
        headers={**auth_headers, "Idempotency-Key": "batchless-transfer"},
        json=movement_payload(movement_stock, "transfer", batch_id=None, quantity=10),
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "Transfer quantity exceeds available batchless stock"
    assert stock_state(movement_stock) == before
    with session_module.SessionLocal() as db:
        assert current_stock_for_item(db, movement_stock["item_id"], movement_stock["source_id"]) == source_before
        assert current_stock_for_item(db, movement_stock["item_id"], movement_stock["destination_id"]) == destination_before


@pytest.mark.parametrize("movement_type", ["issue", "consume", "return", "adjustment"])
@pytest.mark.parametrize("batchless", [False, True])
def test_direct_movement_rejects_opposite_direction_warehouse_without_writes(
    client, auth_headers, movement_stock, movement_type, batchless,
):
    opposite_field = "to_warehouse_id" if movement_type in {"issue", "consume"} else "from_warehouse_id"
    before = stock_state(movement_stock)
    response = client.post(
        "/api/inventory/transfer",
        headers={**auth_headers, "Idempotency-Key": f"opposite-{movement_type}-{batchless}"},
        json=movement_payload(
            movement_stock, movement_type,
            batch_id=None if batchless else movement_stock["batch_id"],
            **{opposite_field: movement_stock["destination_id"]},
        ),
    )
    assert response.status_code == 400, response.text
    assert "movement cannot have" in response.json()["detail"]
    assert stock_state(movement_stock) == before


def test_batchless_transfer_moves_only_ledger_stock_between_warehouses(
    client, auth_headers, movement_stock,
):
    deposited = client.post(
        "/api/inventory/transfer", headers=auth_headers,
        json=movement_payload(movement_stock, "adjustment", batch_id=None, quantity=5),
    )
    assert deposited.status_code == 201, deposited.text
    headers = {**auth_headers, "Idempotency-Key": "backed-batchless-transfer"}
    payload = movement_payload(movement_stock, "transfer", batch_id=None, quantity=3)

    response = client.post("/api/inventory/transfer", headers=headers, json=payload)

    assert response.status_code == 201, response.text
    assert response.json()["batch_id"] is None
    assert response.json()["from_warehouse_id"] == movement_stock["source_id"]
    assert response.json()["to_warehouse_id"] == movement_stock["destination_id"]
    with session_module.SessionLocal() as db:
        transfer_rows = db.query(StockMovement).filter_by(
            item_id=movement_stock["item_id"], batch_id=None, movement_type="transfer",
        ).all()
        assert len(transfer_rows) == 1
        assert (transfer_rows[0].from_warehouse_id, transfer_rows[0].to_warehouse_id) == (
            movement_stock["source_id"], movement_stock["destination_id"],
        )
        assert db.get(StockBatch, movement_stock["batch_id"]).quantity == 10
        assert current_stock_for_item(db, movement_stock["item_id"]) == 15
        assert current_stock_for_item(db, movement_stock["item_id"], movement_stock["source_id"]) == 12
        assert current_stock_for_item(db, movement_stock["item_id"], movement_stock["destination_id"]) == 3
    before_replay = stock_state(movement_stock)
    replay = client.post("/api/inventory/transfer", headers=headers, json=payload)
    assert replay.status_code == 201, replay.text
    assert replay.json() == response.json()
    assert stock_state(movement_stock) == before_replay


@pytest.mark.parametrize("overrides", [
    {"from_warehouse_id": None},
    {"to_warehouse_id": None},
    {"to_warehouse_id": "same"},
])
def test_batchless_transfer_requires_two_distinct_warehouses_without_writes(
    client, auth_headers, movement_stock, overrides,
):
    if overrides.get("to_warehouse_id") == "same":
        overrides = {"to_warehouse_id": movement_stock["source_id"]}
    before = stock_state(movement_stock)
    response = client.post(
        "/api/inventory/transfer", headers=auth_headers,
        json=movement_payload(movement_stock, "transfer", batch_id=None, **overrides),
    )
    assert response.status_code == 400, response.text
    assert stock_state(movement_stock) == before


def test_batchless_transfer_rejects_wrong_destination_category_without_writes(
    client, auth_headers, movement_stock,
):
    with session_module.SessionLocal() as db:
        wrong_destination = Warehouse(name="Batchless fabric destination", type="fabric_storage")
        db.add(wrong_destination)
        db.commit()
        wrong_destination_id = wrong_destination.id
    before = stock_state(movement_stock)

    response = client.post(
        "/api/inventory/transfer", headers=auth_headers,
        json=movement_payload(
            movement_stock, "transfer", batch_id=None, to_warehouse_id=wrong_destination_id,
        ),
    )

    assert response.status_code == 400, response.text
    assert "Accessory Storage" in response.text
    assert stock_state(movement_stock) == before


@pytest.mark.parametrize("movement_type", ["issue", "consume", "return", "adjustment"])
def test_batchless_movement_rejects_wrong_category_warehouse_without_writes(
    client, auth_headers, movement_stock, movement_type,
):
    with session_module.SessionLocal() as db:
        wrong_warehouse = Warehouse(name="Batchless wrong category warehouse", type="fabric_storage")
        db.add(wrong_warehouse)
        db.commit()
        wrong_warehouse_id = wrong_warehouse.id
    location_field = "to_warehouse_id" if movement_type in {"return", "adjustment"} else "from_warehouse_id"
    before = stock_state(movement_stock)

    response = client.post(
        "/api/inventory/transfer", headers={**auth_headers, "Idempotency-Key": f"wrong-{movement_type}"},
        json=movement_payload(movement_stock, movement_type, batch_id=None, **{location_field: wrong_warehouse_id}),
    )

    assert response.status_code == 400, response.text
    assert "Accessory Storage" in response.text
    assert stock_state(movement_stock) == before


def test_batchless_transfer_cannot_move_reserved_item_stock(
    client, auth_headers, movement_stock,
):
    deposited = client.post(
        "/api/inventory/transfer", headers=auth_headers,
        json=movement_payload(movement_stock, "adjustment", batch_id=None, quantity=5),
    )
    assert deposited.status_code == 201, deposited.text
    with session_module.SessionLocal() as db:
        order = ProductionOrder(
            production_no="BATCHLESS-TRANSFER-RESERVATION", production_type="branded_stock",
            model_id=db.query(Model.id).first()[0], planned_quantity=1,
        )
        db.add(order)
        db.flush()
        db.add(MaterialReservation(
            reservation_no="BATCHLESS-TRANSFER-RESERVATION", production_order_id=order.id,
            item_id=movement_stock["item_id"], warehouse_id=movement_stock["source_id"],
            reserved_quantity=4, unit="pcs",
        ))
        db.commit()
    before = stock_state(movement_stock)

    response = client.post(
        "/api/inventory/transfer", headers=auth_headers,
        json=movement_payload(movement_stock, "transfer", batch_id=None, quantity=2),
    )

    assert response.status_code == 409, response.text
    assert stock_state(movement_stock) == before


def test_batchless_transfer_uses_decimal_ledger_boundary(
    client, auth_headers, movement_stock,
):
    for quantity in (0.1, 0.2):
        deposited = client.post(
            "/api/inventory/transfer", headers=auth_headers,
            json=movement_payload(movement_stock, "adjustment", batch_id=None, quantity=quantity),
        )
        assert deposited.status_code == 201, deposited.text

    response = client.post(
        "/api/inventory/transfer", headers=auth_headers,
        json=movement_payload(movement_stock, "transfer", batch_id=None, quantity=0.3),
    )

    assert response.status_code == 201, response.text
    with session_module.SessionLocal() as db:
        assert current_stock_for_item(db, movement_stock["item_id"], movement_stock["source_id"]) == 10
        assert current_stock_for_item(db, movement_stock["item_id"], movement_stock["destination_id"]) == 0.3


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


@pytest.mark.parametrize("edit_kind", ["quantity", "warehouse"])
def test_batch_edit_rejects_legacy_unit_drift_before_ledger_write(
    client, auth_headers, movement_stock, edit_kind,
):
    with session_module.SessionLocal() as db:
        db.get(StockBatch, movement_stock["batch_id"]).unit = "kg"
        db.commit()
    before = stock_state(movement_stock)
    payload = (
        {"quantity": 11}
        if edit_kind == "quantity"
        else {"warehouse_id": movement_stock["destination_id"]}
    )

    response = client.patch(
        f"/api/inventory/batches/{movement_stock['batch_id']}",
        headers=auth_headers,
        json=payload,
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "Batch unit must match the material unit"
    assert stock_state(movement_stock) == before
    with session_module.SessionLocal() as db:
        assert db.get(StockBatch, movement_stock["batch_id"]).unit == "kg"


def test_batch_edit_allows_metadata_only_change_on_legacy_unit_drift(
    client, auth_headers, movement_stock,
):
    with session_module.SessionLocal() as db:
        db.get(StockBatch, movement_stock["batch_id"]).unit = "kg"
        db.commit()
    with session_module.SessionLocal() as db:
        before_movements = db.query(StockMovement).count()

    response = client.patch(
        f"/api/inventory/batches/{movement_stock['batch_id']}",
        headers=auth_headers,
        json={"color": "navy"},
    )

    assert response.status_code == 200, response.text
    with session_module.SessionLocal() as db:
        batch = db.get(StockBatch, movement_stock["batch_id"])
        assert batch.color == "navy"
        assert batch.unit == "kg"
        assert db.query(StockMovement).count() == before_movements


@pytest.mark.parametrize(
    "payload",
    [{"unit": "pcs"}, {"unit": "pcs", "quantity": 0}],
)
def test_batch_edit_cannot_relabel_quantity_or_ledger_history(
    client, auth_headers, movement_stock, payload,
):
    with session_module.SessionLocal() as db:
        batch = db.get(StockBatch, movement_stock["batch_id"])
        batch.unit = "kg"
        db.commit()
        before_movements = [
            (row.id, row.movement_type, row.quantity, row.unit)
            for row in db.query(StockMovement).filter_by(batch_id=batch.id).all()
        ]
        before_audits = db.query(AuditLog).count()
    before_stock = stock_state(movement_stock)

    response = client.patch(
        f"/api/inventory/batches/{movement_stock['batch_id']}",
        headers=auth_headers,
        json=payload,
    )

    assert response.status_code == 409, response.text
    assert "Cannot change batch unit" in response.json()["detail"]
    assert stock_state(movement_stock) == before_stock
    with session_module.SessionLocal() as db:
        batch = db.get(StockBatch, movement_stock["batch_id"])
        assert batch.unit == "kg"
        assert [
            (row.id, row.movement_type, row.quantity, row.unit)
            for row in db.query(StockMovement).filter_by(batch_id=batch.id).all()
        ] == before_movements
        assert db.query(AuditLog).count() == before_audits


def test_zero_balance_batch_relabel_rejects_mismatched_linked_movement_without_writes(
    client, auth_headers, movement_stock,
):
    with session_module.SessionLocal() as db:
        batch = db.get(StockBatch, movement_stock["batch_id"])
        batch.quantity = 0
        batch.unit = "kg"
        movement = db.query(StockMovement).filter_by(batch_id=batch.id).one()
        movement.unit = "kg"
        db.commit()
        before_movements = [
            (row.id, row.movement_type, row.quantity, row.unit)
            for row in db.query(StockMovement).filter_by(batch_id=batch.id).all()
        ]
        before_audits = db.query(AuditLog).count()
    before_stock = stock_state(movement_stock)

    response = client.patch(
        f"/api/inventory/batches/{movement_stock['batch_id']}",
        headers=auth_headers,
        json={"unit": "pcs"},
    )

    assert response.status_code == 409, response.text
    assert "linked quantity units differ" in response.json()["detail"]
    assert stock_state(movement_stock) == before_stock
    with session_module.SessionLocal() as db:
        batch = db.get(StockBatch, movement_stock["batch_id"])
        assert batch.unit == "kg"
        assert [
            (row.id, row.movement_type, row.quantity, row.unit)
            for row in db.query(StockMovement).filter_by(batch_id=batch.id).all()
        ] == before_movements
        assert db.query(AuditLog).count() == before_audits


def test_zero_balance_batch_relabel_rejects_linked_waste_record_without_writes(
    client, auth_headers, movement_stock,
):
    with session_module.SessionLocal() as db:
        batch = db.get(StockBatch, movement_stock["batch_id"])
        batch.quantity = 0
        batch.unit = "kg"
        db.add(WasteRecord(
            item_id=movement_stock["item_id"],
            batch_id=batch.id,
            waste_type="Synthetic unit-label review",
            quantity=1,
            unit="pcs",
            sellable=False,
            estimated_value=0,
        ))
        db.commit()
        before_waste = db.query(WasteRecord).filter_by(batch_id=batch.id).count()
        before_audits = db.query(AuditLog).count()
    before_stock = stock_state(movement_stock)

    response = client.patch(
        f"/api/inventory/batches/{movement_stock['batch_id']}",
        headers=auth_headers,
        json={"unit": "pcs"},
    )

    assert response.status_code == 409, response.text
    assert "linked waste records exist" in response.json()["detail"]
    assert stock_state(movement_stock) == before_stock
    with session_module.SessionLocal() as db:
        batch = db.get(StockBatch, movement_stock["batch_id"])
        assert batch.unit == "kg"
        assert db.query(WasteRecord).filter_by(batch_id=batch.id).count() == before_waste
        assert db.query(AuditLog).count() == before_audits


def test_zero_balance_unreferenced_batch_can_be_relabelled(client, auth_headers, movement_stock):
    with session_module.SessionLocal() as db:
        batch = db.get(StockBatch, movement_stock["batch_id"])
        batch.quantity = 0
        batch.unit = "kg"
        for movement in db.query(StockMovement).filter_by(batch_id=batch.id).all():
            db.delete(movement)
        db.commit()
        before_movement_count = db.query(StockMovement).count()

    response = client.patch(
        f"/api/inventory/batches/{movement_stock['batch_id']}",
        headers=auth_headers,
        json={"unit": "pcs"},
    )

    assert response.status_code == 200, response.text
    with session_module.SessionLocal() as db:
        batch = db.get(StockBatch, movement_stock["batch_id"])
        assert batch.unit == "pcs"
        assert batch.quantity == Decimal("0")
        assert db.query(StockMovement).count() == before_movement_count


def test_batch_archive_rejects_legacy_unit_drift_before_issue_or_reservation_release(
    client, auth_headers, movement_stock,
):
    used = client.post(
        "/api/inventory/transfer",
        headers=auth_headers,
        json=movement_payload(movement_stock, "issue", quantity=1),
    )
    assert used.status_code == 201, used.text
    with session_module.SessionLocal() as db:
        db.get(StockBatch, movement_stock["batch_id"]).unit = "kg"
        db.commit()
    before = stock_state(movement_stock)

    response = client.delete(
        f"/api/inventory/batches/{movement_stock['batch_id']}",
        headers=auth_headers,
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "Batch unit must match the material unit"
    assert stock_state(movement_stock) == before
    with session_module.SessionLocal() as db:
        assert db.get(StockBatch, movement_stock["batch_id"]).unit == "kg"


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


@pytest.mark.parametrize("movement_type", ["issue", "consume"])
def test_batchless_outgoing_cannot_borrow_tracked_batch_stock_without_writes(
    client, auth_headers, movement_stock, movement_type,
):
    before = stock_state(movement_stock)
    response = client.post(
        "/api/inventory/transfer",
        headers={**auth_headers, "Idempotency-Key": f"unbacked-{movement_type}"},
        json=movement_payload(movement_stock, movement_type, batch_id=None),
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "Movement quantity exceeds available batchless stock"
    assert stock_state(movement_stock) == before


@pytest.mark.parametrize("movement_type", ["issue", "consume"])
def test_batchless_outgoing_respects_item_only_reservation_and_source_ledger(
    client, auth_headers, movement_stock, movement_type,
):
    deposited = client.post(
        "/api/inventory/transfer", headers=auth_headers,
        json=movement_payload(movement_stock, "adjustment", batch_id=None, quantity=5),
    )
    assert deposited.status_code == 201, deposited.text
    with session_module.SessionLocal() as db:
        order = ProductionOrder(
            production_no=f"BATCHLESS-{movement_type.upper()}-RESERVATION",
            production_type="branded_stock", model_id=db.query(Model.id).first()[0], planned_quantity=1,
        )
        db.add(order)
        db.flush()
        db.add(MaterialReservation(
            reservation_no=f"BATCHLESS-{movement_type.upper()}-RESERVATION",
            production_order_id=order.id, item_id=movement_stock["item_id"],
            warehouse_id=movement_stock["source_id"], reserved_quantity=3, unit="pcs",
        ))
        db.commit()

    allowed = client.post(
        "/api/inventory/transfer", headers=auth_headers,
        json=movement_payload(movement_stock, movement_type, batch_id=None, quantity=2),
    )
    assert allowed.status_code == 201, allowed.text
    before_rejected = stock_state(movement_stock)
    rejected = client.post(
        "/api/inventory/transfer", headers=auth_headers,
        json=movement_payload(movement_stock, movement_type, batch_id=None, quantity=0.0001),
    )
    assert rejected.status_code == 409, rejected.text
    assert stock_state(movement_stock) == before_rejected
    with session_module.SessionLocal() as db:
        assert db.get(StockBatch, movement_stock["batch_id"]).quantity == 10
        assert current_stock_for_item(db, movement_stock["item_id"], movement_stock["source_id"]) == 13


@pytest.mark.parametrize("movement_type", ["issue", "consume", "transfer"])
def test_batch_outgoing_preserves_item_only_reservation_without_writes(
    client, auth_headers, movement_stock, movement_type,
):
    with session_module.SessionLocal() as db:
        order = ProductionOrder(
            production_no=f"BATCH-{movement_type.upper()}-ITEM-CLAIM",
            production_type="branded_stock", model_id=db.query(Model.id).first()[0], planned_quantity=1,
        )
        db.add(order)
        db.flush()
        reservation = MaterialReservation(
            reservation_no=f"BATCH-{movement_type.upper()}-ITEM-CLAIM",
            production_order_id=order.id, item_id=movement_stock["item_id"],
            warehouse_id=movement_stock["source_id"], reserved_quantity=8, unit="pcs",
        )
        db.add(reservation)
        db.commit()
        reservation_id = reservation.id

    before = stock_state(movement_stock)
    response = client.post(
        "/api/inventory/transfer", headers=auth_headers,
        json=movement_payload(movement_stock, movement_type),
    )
    assert response.status_code == 409, response.text
    assert stock_state(movement_stock) == before
    with session_module.SessionLocal() as db:
        claim = db.get(MaterialReservation, reservation_id)
        assert claim.reserved_quantity == 8
        assert claim.consumed_quantity == 0
        assert claim.released_quantity == 0


@pytest.mark.parametrize(("movement_type", "expected"), [("return", 14), ("adjustment", 14)])
def test_batchless_incoming_keeps_existing_ledger_behavior(client, auth_headers, movement_stock, movement_type, expected):
    response = client.post("/api/inventory/transfer", headers=auth_headers,
                           json=movement_payload(movement_stock, movement_type, batch_id=None))
    assert response.status_code == 201, response.text
    with session_module.SessionLocal() as db:
        assert db.get(StockBatch, movement_stock["batch_id"]).quantity == 10
        assert current_stock_for_item(db, movement_stock["item_id"]) == expected
