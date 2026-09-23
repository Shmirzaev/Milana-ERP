from uuid import uuid4

from sqlalchemy import event

from app.models import Item, Model, ModelBOM, ProductionOrder, StockBatch, Warehouse
from app.services.inventory import accessory_issue_plan, available_stock_for_item
from app.tests.conftest import TestSessionLocal


def test_accessory_issue_plan_batches_stock_totals_and_preserves_values():
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        warehouse = Warehouse(name=f"PERF02 plan {marker}", type="materials")
        model = Model(code=f"PERF02-PLAN-{marker}", name="Accessory plan", product_type="shirt")
        db.add_all([warehouse, model])
        db.flush()
        items = [
            Item(
                sku=f"PERF02-PLAN-{marker}-{index}",
                name=f"Accessory {index}",
                category="accessory",
                unit="pcs",
            )
            for index in range(50)
        ]
        db.add_all(items)
        db.flush()
        order = ProductionOrder(
            production_no=f"PERF02-PLAN-PO-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=2,
            status="new",
        )
        db.add(order)
        db.flush()
        for index, item in enumerate(items):
            db.add(ModelBOM(
                model_id=model.id,
                item_id=item.id,
                quantity_per_piece=index + 1,
                unit="pcs",
                waste_percent=0,
            ))
            db.add(StockBatch(
                item_id=item.id,
                batch_no=f"PERF02-PLAN-B-{marker}-{index}",
                quantity=index + 3,
                unit="pcs",
                warehouse_id=warehouse.id,
            ))
        db.commit()
        expected = {
            int(item.id): available_stock_for_item(db, int(item.id))
            for item in items
        }

        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select"):
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            plan = accessory_issue_plan(db, int(order.id))
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert len(plan["rows"]) == len(items)
    assert {
        int(row["item_id"]): row["available_quantity"]
        for row in plan["rows"]
    } == expected
    stock_batch_totals = [
        statement for statement in statements
        if "sum(stock_batches.quantity)" in statement
    ]
    movement_totals = [
        statement for statement in statements
        if "sum(case" in statement and "stock_movements" in statement
    ]
    reservation_totals = [
        statement for statement in statements
        if "material_reservations.reserved_quantity - material_reservations.consumed_quantity" in statement
    ]
    assert len(stock_batch_totals) == 1
    assert len(movement_totals) == 1
    assert len(reservation_totals) == 1, statements
