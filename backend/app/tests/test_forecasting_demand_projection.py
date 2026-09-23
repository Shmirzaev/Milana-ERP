from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import event

from app.models import Model, SalesOrder, SalesOrderItem
from app.services.forecasting import _branded_demand_groups
from app.tests.conftest import TestSessionLocal


def test_branded_demand_aggregation_projects_only_consumed_fields():
    suffix = uuid4().hex[:8]
    created_at = datetime(2026, 9, 20, tzinfo=timezone.utc)
    with TestSessionLocal() as db:
        model = Model(code=f"PERF-FORECAST-{suffix}", name="Projected forecast model")
        db.add(model)
        db.flush()
        order = SalesOrder(
            order_no=f"PERF-FORECAST-{suffix}",
            order_type="branded_stock_sale",
            status="ready",
            created_at=created_at,
            printing_attachments=[{"unused": "large attachment metadata"}],
            notes="not used for branded demand",
        )
        db.add(order)
        db.flush()
        db.add(SalesOrderItem(
            sales_order_id=order.id,
            model_id=model.id,
            color="navy",
            size="M",
            quantity=7,
            unit_price=10,
            notes="not used for demand grouping",
        ))
        db.commit()
        model_id = int(model.id)

    statements = []
    with TestSessionLocal() as db:
        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            groups = _branded_demand_groups(db)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    group = groups[(model_id, None, None, "navy", "M")]
    assert group["quantity"] == 7
    assert group["order_ids"]
    assert group["source"] == "sales_orders"
    sales_read = next(
        statement for statement in statements
        if "from sales_order_items" in statement and "join sales_orders" in statement
    )
    production_read = next(
        statement for statement in statements
        if "from production_order_items" in statement and "join production_orders" in statement
    )
    assert "sales_orders.created_at" in sales_read
    assert "sales_orders.printing_attachments" not in sales_read
    assert "sales_orders.notes" not in sales_read
    assert "sales_order_items.notes" not in sales_read
    assert "production_orders.created_at" in production_read
    assert "production_orders.notes" not in production_read
