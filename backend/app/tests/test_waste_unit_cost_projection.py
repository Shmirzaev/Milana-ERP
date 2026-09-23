from decimal import Decimal
from uuid import uuid4

from sqlalchemy import event

from app.models import Item, StockBatch, Warehouse
from app.api.routes import waste
from app.tests.conftest import TestSessionLocal


def test_waste_batch_cost_reads_project_only_cost_columns():
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        item = Item(
            sku=f"PERF35-WASTE-{marker}",
            name="Waste valuation fabric",
            category="fabric",
            unit="kg",
            default_cost=Decimal("1.25"),
            reorder_level=0,
            composition_json=[{"name": "cotton", "percentage": 100}],
        )
        warehouse = Warehouse(name=f"PERF35 waste {marker}", type="fabric_storage")
        db.add_all([item, warehouse])
        db.flush()
        batch = StockBatch(
            item_id=item.id,
            batch_no=f"PERF35-WASTE-BATCH-{marker}",
            quantity=10,
            piece_count=2,
            roll_weights_kg=[5, 5],
            roll_lengths_m=[10, 12],
            unit="kg",
            cost_per_unit=Decimal("2.75"),
            warehouse_id=warehouse.id,
            qc_status="passed",
        )
        db.add(batch)
        db.commit()

        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select") and " from stock_batches " in normalized:
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            cost = waste._unit_cost_for_waste(db, int(item.id), int(batch.id))
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert cost == Decimal("2.7500")
    assert len(statements) == 1
    selected_columns = statements[0].split(" from stock_batches", 1)[0]
    assert "stock_batches.id" in selected_columns
    assert "stock_batches.cost_per_unit" in selected_columns
    assert "stock_batches.roll_weights_kg" not in selected_columns
    assert "stock_batches.roll_lengths_m" not in selected_columns


def test_waste_item_default_cost_fallback_is_preserved():
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        item = Item(
            sku=f"PERF35-WASTE-DEFAULT-{marker}",
            name="Waste default-cost item",
            category="fabric",
            unit="kg",
            default_cost=Decimal("3.1250"),
            reorder_level=0,
            composition_json=[{"name": "linen", "percentage": 100}],
        )
        db.add(item)
        db.commit()

        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select") and (
                " from stock_batches " in normalized or " from items " in normalized
            ):
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            cost = waste._unit_cost_for_waste(db, int(item.id), None)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert cost == Decimal("3.1250")
    item_reads = [statement for statement in statements if " from items " in statement]
    assert len(item_reads) == 1
    selected_columns = item_reads[0].split(" from items", 1)[0]
    assert "items.id" in selected_columns
    assert "items.default_cost" in selected_columns
    assert "items.composition_json" not in selected_columns
