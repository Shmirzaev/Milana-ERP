from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import event

from app.api.routes import dashboards
from app.models import SalesOrder
from app.tests.conftest import TestSessionLocal


def test_management_dashboard_counts_active_and_late_orders_in_one_query(monkeypatch):
    suffix = uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    orders = [
        ("confirmed", now - timedelta(days=1)),
        ("draft", now - timedelta(days=1)),
        ("delivered", now - timedelta(days=1)),
        ("cancelled", now - timedelta(days=1)),
        ("planning", now + timedelta(days=1)),
    ]
    with TestSessionLocal() as db:
        active_statuses = (
            "confirmed", "planning", "planning_approved", "in_production",
            "production", "cutting", "sewing", "packaging", "storage",
        )
        prior_active_count = db.query(SalesOrder.id).filter(
            SalesOrder.status.in_(active_statuses),
        ).count()
        prior_late_count = db.query(SalesOrder.id).filter(
            SalesOrder.deadline < now,
            SalesOrder.status.not_in(("delivered", "closed", "cancelled")),
        ).count()
        db.add_all([
            SalesOrder(
                order_no=f"PERF-DASH-MGMT-{suffix}-{index}",
                order_type="client_order",
                status=status,
                deadline=deadline,
            )
            for index, (status, deadline) in enumerate(orders)
        ])
        db.commit()

    monkeypatch.setattr(dashboards, "branded_stock_value", lambda _db: 17.5)
    statements = []
    with TestSessionLocal() as db:
        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = dashboards.management(db, object())
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert payload["active_orders"] == prior_active_count + 2
    assert payload["late_orders"] == prior_late_count + 2
    assert payload["branded_stock_value"] == 17.5
    order_aggregate_reads = [
        statement for statement in statements
        if "from sales_orders" in statement and "sum(case" in statement
    ]
    assert len(order_aggregate_reads) == 1
    assert "sales_orders.status in" in order_aggregate_reads[0]
    assert "sales_orders.deadline <" in order_aggregate_reads[0]
