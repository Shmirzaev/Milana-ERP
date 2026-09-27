from uuid import uuid4

from sqlalchemy import event

from app.services.inventory import stock_summary
from app.models import Item
from app.tests.conftest import TestSessionLocal, test_engine


def test_stock_summary_projects_item_fields_and_preserves_output():
    marker = uuid4().hex[:10]
    category = f"projection-{marker}"
    with TestSessionLocal() as db:
        item = Item(
            sku=f"STOCK-PROJECTION-{marker}",
            name=f"Projected stock item {marker}",
            category=category,
            unit="kg",
            image_url="/storage/item.webp",
            composition_json=[{"unused_payload": "x" * 10_000}],
        )
        db.add(item)
        db.commit()
        item_id = item.id

    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        with TestSessionLocal() as db:
            rows, total = stock_summary(
                db,
                category=category,
                page=1,
                page_size=20,
                include_total=True,
            )
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert total == 1
    assert rows == [{
        "item_id": item_id,
        "sku": f"STOCK-PROJECTION-{marker}",
        "name": f"Projected stock item {marker}",
        "image_url": "/storage/item.webp",
        "category": category,
        "unit": "kg",
        "quantity": 0.0,
        "reserved_quantity": 0.0,
        "available_quantity": 0.0,
    }]
    item_reads = [statement for statement in statements if " from items " in statement]
    assert len(item_reads) == 1, statements
    selected_columns = item_reads[0].split(" from ", 1)[0]
    for field in ("id", "sku", "name", "image_url", "category", "unit"):
        assert f"items.{field}" in selected_columns
    for field in ("composition_json", "default_cost", "reorder_level", "created_at"):
        assert f"items.{field}" not in selected_columns
