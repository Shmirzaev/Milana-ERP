"""Received quantities are ledger evidence, never a second stock balance."""
from decimal import Decimal

from sqlalchemy import event

from app.schemas import Item, StockBatch, StockMovement, Warehouse
from app.tests.conftest import TestSessionLocal, test_engine


def test_active_batch_receipts_exclude_returns_usage_and_adjustments(client, auth_headers):
    with TestSessionLocal() as db:
        item = db.query(Item).filter(Item.category == "fabric").first()
        warehouse = db.query(Warehouse).first()
        item_id, warehouse_id = item.id, warehouse.id
    received = client.post("/api/inventory/receive", headers=auth_headers, json={
        "item_id": item_id, "batch_no": "RECEIVED-EVIDENCE", "quantity": 10.25,
        "unit": "kg", "cost_per_unit": 2, "warehouse_id": warehouse_id, "qc_status": "passed",
    })
    assert received.status_code == 201, received.text
    bid = received.json()["id"]
    with TestSessionLocal() as db:
        for kind, qty in [("receive", "1.5"), ("return", "2"), ("issue", "3"), ("adjustment", "4"), ("transfer", "7")]:
            db.add(StockMovement(movement_type=kind, item_id=item_id, batch_id=bid,
                                quantity=Decimal(qty), unit="kg", to_warehouse_id=warehouse_id))
        db.get(StockBatch, bid).quantity = Decimal("14.75")
        missing = StockBatch(item_id=item_id, batch_no="NO-RECEIPT", quantity=9,
                             unit="kg", cost_per_unit=1, warehouse_id=warehouse_id)
        db.add(missing)
        db.commit()
        missing_id = missing.id

    def batches():
        result = client.get(f"/api/inventory/batches?item_id={item_id}", headers=auth_headers)
        assert result.status_code == 200, result.text
        return {row["id"]: row for row in result.json()}

    before = batches()
    assert before[bid]["received_quantity"] == 11.75
    assert float(before[bid]["quantity"]) == 14.75
    assert before[missing_id]["received_quantity"] is None
    for _ in range(12):
        assert batches() == before, "repeated reads must not write or recompute from stock balance"
    with TestSessionLocal() as db:
        db.get(StockBatch, bid).unit = "m"
        db.commit()
    assert batches()[bid]["received_quantity"] is None, "incompatible units cannot be summed"


def test_receipt_projection_is_one_batched_query(client, auth_headers):
    with TestSessionLocal() as db:
        item = db.query(Item).filter(Item.category == "fabric").first()
        warehouse = db.query(Warehouse).first()
        for i in range(24):
            batch = StockBatch(item_id=item.id, batch_no=f"BULK-RECEIPT-{i}", quantity=5,
                               unit="kg", cost_per_unit=1, warehouse_id=warehouse.id)
            db.add(batch)
            db.flush()
            db.add(StockMovement(movement_type="receive", item_id=item.id, batch_id=batch.id,
                                quantity=10, unit="kg", to_warehouse_id=warehouse.id))
        db.commit()
    queries = []

    def capture(_conn, _cursor, statement, *_args):
        if "sum(stock_movements.quantity)" in statement.lower():
            queries.append(statement)

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        result = client.get("/api/inventory/batches?q=BULK-RECEIPT-", headers=auth_headers)
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)
    assert result.status_code == 200, result.text
    assert len(result.json()) == 24
    assert all(row["received_quantity"] == 10 for row in result.json())
    assert len(queries) == 1
