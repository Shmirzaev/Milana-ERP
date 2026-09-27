from decimal import Decimal
from uuid import uuid4

from sqlalchemy import event

from app.models import Item, StockBatch, Warehouse, WasteRecord
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


def test_waste_page_values_batch_costs_without_per_row_queries():
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        stocked = Item(
            sku=f"PERF35-WASTE-STOCKED-{marker}", name="Stocked waste item",
            category="fabric", unit="kg", default_cost=Decimal("1"), reorder_level=0,
            composition_json=[],
        )
        defaulted = Item(
            sku=f"PERF35-WASTE-DEFAULTED-{marker}", name="Defaulted waste item",
            category="fabric", unit="kg", default_cost=Decimal("3"), reorder_level=0,
            composition_json=[],
        )
        warehouse = Warehouse(name=f"PERF35 waste page {marker}", type="fabric_storage")
        db.add_all([stocked, defaulted, warehouse])
        db.flush()
        old_batch = StockBatch(
            item_id=stocked.id, batch_no=f"PERF35-OLD-{marker}", quantity=10,
            unit="kg", cost_per_unit=Decimal("2"), warehouse_id=warehouse.id,
            qc_status="passed", roll_weights_kg=[], roll_lengths_m=[],
        )
        latest_batch = StockBatch(
            item_id=stocked.id, batch_no=f"PERF35-NEW-{marker}", quantity=10,
            unit="kg", cost_per_unit=Decimal("4"), warehouse_id=warehouse.id,
            qc_status="passed", roll_weights_kg=[], roll_lengths_m=[],
        )
        db.add_all([old_batch, latest_batch])
        db.flush()
        rows = [
            WasteRecord(id=n + 1, item_id=stocked.id, batch_id=old_batch.id, quantity=Decimal("1.5"))
            for n in range(20)
        ] + [
            WasteRecord(id=n + 21, item_id=stocked.id, quantity=Decimal("1.5"))
            for n in range(20)
        ] + [
            WasteRecord(id=n + 41, item_id=defaulted.id, quantity=Decimal("1.5"))
            for n in range(20)
        ]

        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            values = waste._estimated_values_for_waste_page(db, rows)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert len(statements) == 3, statements
    assert [values[n] for n in (1, 20)] == [3.0, 3.0]
    assert [values[n] for n in (21, 40)] == [6.0, 6.0]
    assert [values[n] for n in (41, 60)] == [4.5, 4.5]
    assert all("roll_weights_kg" not in statement for statement in statements)
    assert all("roll_lengths_m" not in statement for statement in statements)
