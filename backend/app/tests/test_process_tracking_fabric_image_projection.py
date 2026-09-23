from uuid import uuid4

from sqlalchemy import event

from app.api.routes.process_tracking import _fabric_batch_images
from app.models import Item, StockBatch, Warehouse
from app.tests.conftest import TestSessionLocal


def test_process_tracking_fabric_batch_lookup_selects_only_image_fields():
    marker = uuid4().hex
    image_url = f"/storage/fabrics/{marker}.webp"
    with TestSessionLocal() as db:
        item = Item(
            sku=f"PT-FAB-{marker}",
            name=f"Tracking fabric {marker}",
            category="fabric",
            unit="kg",
        )
        warehouse = Warehouse(name=f"PT Warehouse {marker}", type="materials")
        db.add_all([item, warehouse])
        db.flush()
        batch = StockBatch(
            item_id=item.id,
            warehouse_id=warehouse.id,
            batch_no=f"PT-BATCH-{marker}",
            quantity=10,
            unit="kg",
            cost_per_unit=2,
            image_url=image_url,
        )
        db.add(batch)
        db.commit()

        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select") and " from stock_batches " in normalized:
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            result = _fabric_batch_images(db, {batch.id})
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert result == {batch.id: image_url}
    assert len(statements) == 1, statements
    assert "stock_batches.id" in statements[0]
    assert "stock_batches.image_url" in statements[0]
    assert "stock_batches.batch_no" not in statements[0]
    assert "stock_batches.quantity" not in statements[0]
