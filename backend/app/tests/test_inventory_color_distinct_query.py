from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import event, func
import pytest

from app.api.routes.inventory import list_received_stock_colors
from app.db.session import SessionLocal
from app.models import Item, StockBatch, Warehouse


@pytest.mark.parametrize("batch_count", [1, 50, 401])
def test_received_stock_colors_deduplicates_trimmed_values_in_sql(batch_count):
    suffix = uuid4().hex[:8].upper()
    color = f"PERF35-{suffix}"
    with SessionLocal() as db:
        item = Item(sku=f"PERF35-{suffix}", name="Color query fixture", category="fabric", unit="kg")
        warehouse = Warehouse(name=f"PERF35 color warehouse {suffix}", type="materials")
        db.add_all([item, warehouse])
        db.flush()
        batches = [
            StockBatch(
                item_id=item.id,
                batch_no=f"PERF35-{suffix}-{index:04d}",
                color=f"  {color}  " if index % 2 else color,
                quantity=1,
                unit="kg",
                cost_per_unit=1,
                warehouse_id=warehouse.id,
            )
            for index in range(batch_count)
        ]
        db.add_all(batches)
        db.commit()

    with SessionLocal() as db:
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            result = list_received_stock_colors(
                db,
                SimpleNamespace(factory_code="MIL", role=None, extra_permissions=[]),
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        fixture_rows = db.query(StockBatch).filter(StockBatch.item_id == item.id).count()
        distinct_fixture_colors = (
            db.query(func.trim(StockBatch.color))
            .filter(StockBatch.item_id == item.id, func.length(func.trim(StockBatch.color)) > 0)
            .distinct()
            .count()
        )

    assert fixture_rows == batch_count
    assert distinct_fixture_colors == 1
    assert color in result
    color_query = next(statement for statement in statements if " from stock_batches " in statement)
    assert "select distinct trim(stock_batches.color)" in color_query
