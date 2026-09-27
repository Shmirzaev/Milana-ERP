from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.inventory import list_batches
from app.models import Item, StockBatch, User, Warehouse
from app.schemas.inventory import StockBatchOut
from app.tests.conftest import TestSessionLocal


@pytest.mark.parametrize("batch_count", [1, 50, 401])
def test_batch_list_uses_explicit_item_join_without_implicit_duplicate(batch_count):
    suffix = uuid4().hex[:10].upper()
    with TestSessionLocal() as db:
        item = Item(
            sku=f"PERF-{suffix}",
            name=f"Projection test {suffix}",
            category="fabric",
            unit="kg",
            default_cost=1,
            reorder_level=0,
            track_batch=True,
            is_active=True,
            composition_json=[{"name": "cotton", "percentage": 100}],
        )
        warehouse = Warehouse(name=f"Projection {suffix}", type="raw_material")
        db.add_all([item, warehouse])
        db.flush()
        batches = [
            StockBatch(
                item_id=item.id,
                batch_no=f"{suffix}-{index:04d}",
                quantity=10,
                unit="kg",
                cost_per_unit=1,
                warehouse_id=warehouse.id,
                qc_status="passed",
            )
            for index in range(batch_count)
        ]
        db.add_all(batches)
        db.commit()

        user = db.query(User).filter(User.email == "admin@example.com").one()
        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select"):
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = list_batches(db, user, item_id=item.id, page_size=500)
            expected_batch = StockBatchOut.model_validate(batches[0]).model_dump()
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    batch_selects = [sql for sql in statements if " from stock_batches " in sql]
    assert len(payload) == batch_count
    assert len(batch_selects) == 1
    assert batch_selects[0].count("join items") == 1, batch_selects[0]
    assert "items_1" not in batch_selects[0]
    assert len(statements) == 3, statements
    assert len([sql for sql in statements if " from eco_fabric_rolls " in sql]) == 1
    assert len([sql for sql in statements if " from material_reservations " in sql]) == 1
    first_batch = next(row for row in payload if row["batch_no"] == f"{suffix}-0000")
    expected_batch.update(
        {
            "offsite_roll_numbers": [],
            "available_piece_count": None,
            "item_sku": f"PERF-{suffix}",
            "item_name": f"Projection test {suffix}",
            "item_category": "fabric",
            "supplier_name": None,
            "warehouse_name": f"Projection {suffix}",
            "reserved_quantity": 0.0,
            "available_quantity": 10.0,
            "active_reservations": [],
        }
    )
    assert first_batch == expected_batch
