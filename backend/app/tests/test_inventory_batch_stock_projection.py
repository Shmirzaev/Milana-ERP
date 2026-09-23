from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.models import Item, StockBatch, Warehouse
from app.services.inventory import current_stock_for_batch
from app.tests.conftest import TestSessionLocal, test_engine


def test_current_batch_stock_selects_only_quantity_and_preserves_not_found():
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        item = Item(
            sku=f"BATCH-PROJECTION-{marker}",
            name="Projection item",
            category="fabric",
            unit="kg",
            composition_json=[{"unused": "x" * 10_000}],
        )
        warehouse = Warehouse(name=f"Projection warehouse {marker}", type="raw_material")
        db.add_all([item, warehouse])
        db.flush()
        batch = StockBatch(
            item_id=item.id,
            warehouse_id=warehouse.id,
            batch_no=f"BATCH-PROJECTION-{marker}",
            quantity=12.5,
            unit="kg",
        )
        db.add(batch)
        db.commit()
        batch_id = batch.id

    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        with TestSessionLocal() as db:
            assert current_stock_for_batch(db, batch_id) == 12.5
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert len(statements) == 1, statements
    assert statements[0].startswith(
        "select stock_batches.quantity as stock_batches_quantity from stock_batches where stock_batches.id"
    )
    assert "items" not in statements[0]

    with TestSessionLocal() as db:
        with pytest.raises(HTTPException) as exc_info:
            current_stock_for_batch(db, batch_id + 1_000_000_000)
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Stock batch not found"
