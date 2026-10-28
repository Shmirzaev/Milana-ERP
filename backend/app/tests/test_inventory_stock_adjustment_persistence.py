"""Focused regression coverage for INV-STOCK-ADJUSTMENT-01.

Runs only when explicitly selected by the application test suite; the agent
preparation step does not import the app, create a test database, or run tests.
"""

from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.libs.dto.inventory.stock_quantity_adjustment_output import StockQuantityAdjustmentOut
from app.libs.enums.inventory import StockMovementType
from app.models.inventory_service import current_stock_for_item
from app.schemas import AuditLog, Item, StockBatch, StockMovement


def _create_item(client, auth_headers, *, category="accessory", unit="pcs", track_batch=False):
    marker = uuid4().hex[:10].upper()
    response = client.post(
        "/api/inventory/items",
        headers=auth_headers,
        json={
            "sku": f"ADJ-{marker}",
            "name": f"Adjustment persistence {marker}",
            "category": category,
            "unit": unit,
            "default_cost": 2.125,
            "reorder_level": 0,
            "track_batch": track_batch,
            "is_active": True,
        },
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def _warehouse_id(client, auth_headers, warehouse_type="fabric_storage"):
    response = client.get("/api/inventory/warehouses", headers=auth_headers)
    assert response.status_code == 200, response.text
    for row in response.json():
        if row.get("type") == warehouse_type:
            return int(row["id"])
    raise AssertionError(f"seeded data has no {warehouse_type} warehouse")


def _receive(client, auth_headers, *, item_id, warehouse_id, quantity, unit="kg"):
    response = client.post(
        "/api/inventory/receive",
        headers=auth_headers,
        json={
            "item_id": item_id,
            "batch_no": f"ADJ-{uuid4().hex}",
            "quantity": quantity,
            "unit": unit,
            "cost_per_unit": 2.125,
            "warehouse_id": warehouse_id,
            "qc_status": "passed",
        },
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def test_adjustment_response_and_openapi_use_optional_movement_enum(client):
    assert StockQuantityAdjustmentOut.model_fields["movement_type"].annotation == StockMovementType | None
    assert StockQuantityAdjustmentOut(
        item_id=1,
        previous_quantity=0,
        quantity=3,
        delta=3,
        unit="pcs",
        movement_type=StockMovementType.ADJUSTMENT,
    ).model_dump(mode="json")["movement_type"] == "adjustment"
    assert StockQuantityAdjustmentOut(
        item_id=1,
        previous_quantity=3,
        quantity=3,
        delta=0,
        unit="pcs",
    ).model_dump(mode="json")["movement_type"] is None

    document = client.get("/openapi.json")
    assert document.status_code == 200, document.text
    schemas = document.json()["components"]["schemas"]
    movement_schema = schemas["StockQuantityAdjustmentOut"]["properties"]["movement_type"]

    def enum_values(node, seen_refs=frozenset()):
        if isinstance(node, list):
            return set().union(*(enum_values(value, seen_refs) for value in node)) if node else set()
        if not isinstance(node, dict):
            return set()
        values = set(node.get("enum", []))
        reference = node.get("$ref")
        if reference:
            ref_name = reference.rsplit("/", 1)[-1]
            if ref_name not in seen_refs:
                values |= enum_values(schemas[ref_name], seen_refs | {ref_name})
        for key, value in node.items():
            if key not in {"enum", "$ref"}:
                values |= enum_values(value, seen_refs)
        return values

    assert {"adjustment", "issue"} <= enum_values(movement_schema)


def test_non_batch_adjustment_persists_enum_values_and_noop_writes_nothing(client, auth_headers):
    item_id = _create_item(client, auth_headers)
    with SessionLocal() as db:
        audit_before = db.query(AuditLog).filter_by(entity_type="Item", entity_id=item_id).count()

    increase = client.patch(
        f"/api/inventory/stock/{item_id}",
        headers=auth_headers,
        json={"quantity": 3, "unit": "pcs"},
    )
    assert increase.status_code == 200, increase.text
    assert increase.json()["movement_type"] == "adjustment"
    assert increase.json()["movement_id"] is not None

    decrease = client.patch(
        f"/api/inventory/stock/{item_id}",
        headers=auth_headers,
        json={"quantity": 1, "unit": "pcs"},
    )
    assert decrease.status_code == 200, decrease.text
    assert decrease.json()["movement_type"] == "issue"
    assert decrease.json()["movement_id"] is not None

    with SessionLocal() as db:
        rows = db.query(StockMovement).filter_by(
            item_id=item_id, reference_type="StockAdjustment",
        ).order_by(StockMovement.id).all()
        audit_count = db.query(AuditLog).filter_by(entity_type="Item", entity_id=item_id).count()
        assert [(row.movement_type, float(row.quantity)) for row in rows] == [
            ("adjustment", 3.0), ("issue", 2.0),
        ]
        assert all(row.batch_id is None for row in rows)
        assert all(row.from_warehouse_id is None and row.to_warehouse_id is None for row in rows)
        assert audit_count == audit_before + 2

    no_op = client.patch(
        f"/api/inventory/stock/{item_id}",
        headers=auth_headers,
        json={"quantity": 1, "unit": "pcs"},
    )
    assert no_op.status_code == 200, no_op.text
    assert no_op.json()["movement_id"] is None
    assert no_op.json()["movement_type"] is None
    with SessionLocal() as db:
        assert db.query(StockMovement).filter_by(
            item_id=item_id, reference_type="StockAdjustment",
        ).count() == 2
        assert db.query(AuditLog).filter_by(entity_type="Item", entity_id=item_id).count() == audit_before + 2


def test_batch_adjustment_creates_fk_ready_batch_and_archives_depleted_material(client, auth_headers):
    item_id = _create_item(client, auth_headers, category="fabric", unit="kg", track_batch=True)

    increase = client.patch(
        f"/api/inventory/stock/{item_id}",
        headers=auth_headers,
        json={"quantity": 5, "unit": "kg"},
    )
    assert increase.status_code == 200, increase.text
    assert increase.json()["movement_type"] == "adjustment"

    with SessionLocal() as db:
        batch = db.query(StockBatch).filter_by(item_id=item_id, archived_at=None).one()
        movement = db.get(StockMovement, increase.json()["movement_id"])
        assert batch.id is not None
        assert float(batch.quantity) == 5
        assert batch.qc_status == "passed"
        assert float(batch.cost_per_unit) == 2.125
        assert movement.batch_id == batch.id
        assert movement.from_warehouse_id is None
        assert movement.to_warehouse_id == batch.warehouse_id
        assert movement.movement_type == "adjustment"
        assert movement.reference_type == "StockAdjustment"
        assert float(movement.quantity) == 5
        batch_id = batch.id
        warehouse_id = batch.warehouse_id

    decrease = client.patch(
        f"/api/inventory/stock/{item_id}",
        headers=auth_headers,
        json={"quantity": 0, "unit": "kg"},
    )
    assert decrease.status_code == 200, decrease.text
    assert decrease.json()["movement_type"] == "issue"
    with SessionLocal() as db:
        batch = db.get(StockBatch, batch_id)
        movement = db.get(StockMovement, decrease.json()["movement_id"])
        assert float(batch.quantity) == 0
        assert batch.archived_at is not None
        assert batch.archived_by is not None
        assert movement.from_warehouse_id == warehouse_id
        assert movement.to_warehouse_id is None
        assert movement.movement_type == "issue"
        assert movement.batch_id == batch_id


def test_forced_multibatch_decrease_keeps_first_movement_response_and_batch_order(client, auth_headers):
    item_id = _create_item(client, auth_headers, category="fabric", unit="kg", track_batch=True)
    warehouse_id = _warehouse_id(client, auth_headers)
    older_batch_id = _receive(
        client, auth_headers, item_id=item_id, warehouse_id=warehouse_id, quantity=2,
    )
    newer_batch_id = _receive(
        client, auth_headers, item_id=item_id, warehouse_id=warehouse_id, quantity=3,
    )

    response = client.patch(
        f"/api/inventory/stock/{item_id}?force=true",
        headers=auth_headers,
        json={"quantity": 1, "unit": "kg"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["movement_type"] == "issue"

    with SessionLocal() as db:
        adjustments = db.query(StockMovement).filter_by(
            item_id=item_id, reference_type="StockAdjustment",
        ).order_by(StockMovement.id).all()
        assert [row.batch_id for row in adjustments] == [newer_batch_id, older_batch_id]
        assert [float(row.quantity) for row in adjustments] == [3.0, 1.0]
        assert response.json()["movement_id"] == adjustments[0].id
        newer = db.get(StockBatch, newer_batch_id)
        older = db.get(StockBatch, older_batch_id)
        assert float(newer.quantity) == 0
        assert newer.archived_at is not None
        assert float(older.quantity) == 1
        assert older.archived_at is None
        assert current_stock_for_item(db, item_id) == 1


def test_audit_failure_rolls_back_the_adjustment_rows(client, auth_headers, monkeypatch):
    from app.models.inventory import stock_service

    item_id = _create_item(client, auth_headers)
    with SessionLocal() as db:
        audit_before = db.query(AuditLog).filter_by(entity_type="Item", entity_id=item_id).count()

    def fail_audit(*args, **kwargs):
        raise RuntimeError("injected adjustment audit failure")

    monkeypatch.setattr(stock_service, "log_action", fail_audit)
    with pytest.raises(RuntimeError, match="injected adjustment audit failure"):
        client.patch(
            f"/api/inventory/stock/{item_id}",
            headers=auth_headers,
            json={"quantity": 3, "unit": "pcs"},
        )

    with SessionLocal() as db:
        assert current_stock_for_item(db, item_id) == 0
        assert db.query(StockMovement).filter_by(
            item_id=item_id, reference_type="StockAdjustment",
        ).count() == 0
        assert db.query(AuditLog).filter_by(entity_type="Item", entity_id=item_id).count() == audit_before
