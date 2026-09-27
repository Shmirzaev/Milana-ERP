from uuid import uuid4

from app.models import Item, MaterialReservation, Model, ProductionOrder, StockBatch, StockMovement, Warehouse
from app.tests.conftest import TestSessionLocal


def _seed_warehouse_reserved_accessory(*, free_unit: str = "pcs") -> tuple[int, int, int, int, int]:
    marker = uuid4().hex[:12]
    with TestSessionLocal() as db:
        item = Item(sku=f"ACC-SCOPED-{marker}", name="Scoped accessory", category="accessory", unit="pcs")
        model = Model(code=f"ACC-SCOPED-MODEL-{marker}", name="Scoped model")
        reserved_warehouse = Warehouse(name=f"Reserved warehouse {marker}", type="accessory_storage")
        free_warehouse = Warehouse(name=f"Free warehouse {marker}", type="accessory_storage")
        db.add_all([item, model, reserved_warehouse, free_warehouse])
        db.flush()
        issue_order = ProductionOrder(
            production_no=f"ACC-SCOPED-ISSUE-{marker}", production_type="branded_stock",
            model_id=model.id, planned_quantity=10,
        )
        other_order = ProductionOrder(
            production_no=f"ACC-SCOPED-OTHER-{marker}", production_type="branded_stock",
            model_id=model.id, planned_quantity=10,
        )
        reserved_batch = StockBatch(
            item_id=item.id, batch_no=f"ACC-SCOPED-RES-{marker}",
            warehouse_id=reserved_warehouse.id, quantity=5, unit="pcs", qc_status="passed",
        )
        free_batch = StockBatch(
            item_id=item.id, batch_no=f"ACC-SCOPED-FREE-{marker}",
            warehouse_id=free_warehouse.id, quantity=5, unit=free_unit, qc_status="passed",
        )
        db.add_all([issue_order, other_order, reserved_batch, free_batch])
        db.flush()
        reservation = MaterialReservation(
            reservation_no=f"ACC-SCOPED-RESERVATION-{marker}",
            production_order_id=other_order.id, item_id=item.id,
            stock_batch_id=None, warehouse_id=reserved_warehouse.id,
            reserved_quantity=5, consumed_quantity=0, released_quantity=0,
            unit="pcs", status="reserved", reservation_type="accessory", source="manual",
        )
        db.add(reservation)
        db.commit()
        return int(issue_order.id), int(item.id), int(reserved_batch.id), int(free_batch.id), int(reservation.id)


def test_accessory_issue_uses_free_warehouse_before_scoped_item_only_claim(client, auth_headers):
    order_id, item_id, reserved_batch_id, free_batch_id, reservation_id = _seed_warehouse_reserved_accessory()
    response = client.post(
        "/api/inventory/accessory-issues",
        json={"production_order_id": order_id, "lines": [{"item_id": item_id, "quantity": 5, "unit": "pcs"}]},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    with TestSessionLocal() as db:
        assert float(db.get(StockBatch, reserved_batch_id).quantity) == 5
        assert float(db.get(StockBatch, free_batch_id).quantity) == 0
        assert float(db.get(MaterialReservation, reservation_id).consumed_quantity) == 0
        movements = db.query(StockMovement).filter_by(movement_type="consume", item_id=item_id).all()
        assert [(movement.batch_id, float(movement.quantity)) for movement in movements] == [(free_batch_id, 5)]


def test_accessory_issue_rejects_unusable_free_batch_without_debiting_reserved_batch(client, auth_headers):
    order_id, item_id, reserved_batch_id, free_batch_id, reservation_id = _seed_warehouse_reserved_accessory(
        free_unit="kg",
    )
    response = client.post(
        "/api/inventory/accessory-issues",
        json={"production_order_id": order_id, "lines": [{"item_id": item_id, "quantity": 5, "unit": "pcs"}]},
        headers=auth_headers,
    )
    assert response.status_code == 409, response.text
    with TestSessionLocal() as db:
        assert float(db.get(StockBatch, reserved_batch_id).quantity) == 5
        assert float(db.get(StockBatch, free_batch_id).quantity) == 5
        assert float(db.get(MaterialReservation, reservation_id).consumed_quantity) == 0
        assert db.query(StockMovement).filter_by(movement_type="consume", item_id=item_id).count() == 0
