from uuid import uuid4

from app.models import Item, Model, ProductionOrder, StockBatch, StockMovement, Warehouse
from app.tests.conftest import TestSessionLocal


def _seed_stock_backed_accessory() -> tuple[int, int, int]:
    marker = uuid4().hex[:12]
    with TestSessionLocal() as db:
        item = Item(
            sku=f"ACC-UNIT-{marker}",
            name="Unit-bound accessory",
            category="accessory",
            unit="pcs",
        )
        model = Model(code=f"ACC-UNIT-MODEL-{marker}", name="Unit-bound model")
        warehouse = Warehouse(name=f"Accessory unit warehouse {marker}", type="accessory_storage")
        db.add_all([item, model, warehouse])
        db.flush()
        order = ProductionOrder(
            production_no=f"ACC-UNIT-PO-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=10,
        )
        batch = StockBatch(
            item_id=item.id,
            batch_no=f"ACC-UNIT-BATCH-{marker}",
            quantity=10,
            unit="pcs",
            warehouse_id=warehouse.id,
            qc_status="passed",
        )
        db.add_all([order, batch])
        db.flush()
        db.add(StockMovement(
            movement_type="receive",
            item_id=item.id,
            batch_id=batch.id,
            to_warehouse_id=warehouse.id,
            quantity=10,
            unit="pcs",
        ))
        db.commit()
        return int(order.id), int(item.id), int(batch.id)


def test_stock_backed_accessory_issue_rejects_mismatched_unit_without_writes(client, auth_headers):
    order_id, item_id, batch_id = _seed_stock_backed_accessory()
    request = {
        "production_order_id": order_id,
        "lines": [{"item_id": item_id, "quantity": 2, "unit": "kg"}],
    }
    assert client.post("/api/inventory/accessory-issues", json=request).status_code == 401

    response = client.post("/api/inventory/accessory-issues", json=request, headers=auth_headers)
    assert response.status_code == 409, response.text
    assert "unit" in response.json()["detail"].lower()
    with TestSessionLocal() as db:
        assert float(db.get(StockBatch, batch_id).quantity) == 10
        assert db.query(StockMovement).filter_by(item_id=item_id).count() == 1


def test_mismatched_second_line_rolls_back_first_stock_issue(client, auth_headers):
    order_id, item_id, batch_id = _seed_stock_backed_accessory()
    response = client.post(
        "/api/inventory/accessory-issues",
        json={
            "production_order_id": order_id,
            "lines": [
                {"item_id": item_id, "quantity": 2, "unit": "pcs"},
                {"item_id": item_id, "quantity": 1, "unit": "kg"},
            ],
        },
        headers=auth_headers,
    )
    assert response.status_code == 409, response.text
    with TestSessionLocal() as db:
        assert float(db.get(StockBatch, batch_id).quantity) == 10
        assert db.query(StockMovement).filter_by(item_id=item_id).count() == 1


def test_stock_backed_accessory_issue_accepts_item_unit_and_records_matching_movement(client, auth_headers):
    order_id, item_id, batch_id = _seed_stock_backed_accessory()
    response = client.post(
        "/api/inventory/accessory-issues",
        json={
            "production_order_id": order_id,
            "lines": [{"item_id": item_id, "quantity": 2, "unit": " pcs "}],
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["issued"][0]["unit"] == "pcs"
    with TestSessionLocal() as db:
        assert float(db.get(StockBatch, batch_id).quantity) == 8
        movements = db.query(StockMovement).filter_by(item_id=item_id).order_by(StockMovement.id).all()
        assert [movement.movement_type for movement in movements] == ["receive", "consume"]
        assert movements[-1].unit == "pcs"
        assert float(movements[-1].quantity) == 2

