from uuid import uuid4

from sqlalchemy import event

from app.models import Item, StockBatch, Warehouse
from app.services.inventory_reports import material_inventory_report_rows
from app.tests.conftest import TestSessionLocal


def test_material_report_restricts_offsite_roll_aggregation_to_report_batches():
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        warehouse = Warehouse(name=f"Report query {marker}", type="materials")
        item = Item(
            sku=f"REPORT-{marker}", name=f"Report query {marker}",
            category="fabric", unit="kg", default_cost=0, reorder_level=0,
        )
        db.add_all([warehouse, item])
        db.flush()
        batch = StockBatch(
            item_id=item.id, warehouse_id=warehouse.id, batch_no=f"REPORT-{marker}",
            quantity=5, piece_count=2, unit="kg", qc_status="passed",
        )
        db.add(batch)
        db.commit()
        item_id = int(item.id)

    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT") and "eco_fabric_rolls" in statement.lower():
            statements.append(" ".join(statement.lower().split()))

    event.listen(TestSessionLocal.kw["bind"], "before_cursor_execute", capture)
    try:
        with TestSessionLocal() as db:
            rows = material_inventory_report_rows(db)
    finally:
        event.remove(TestSessionLocal.kw["bind"], "before_cursor_execute", capture)

    assert any(row["item_id"] == item_id and row["batch_count"] == 1 for row in rows)
    assert len(statements) == 1
    assert "join stock_batches" in statements[0]
    assert "stock_batches.item_id in" in statements[0]
    assert "stock_batches.quantity >" in statements[0]
