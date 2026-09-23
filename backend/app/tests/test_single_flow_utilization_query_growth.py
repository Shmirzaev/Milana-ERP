from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event

from app.api.routes.production_extra import flow_utilization
from app.db.session import SessionLocal
from app.models import SewingAssignment, WorkOrder
from app.tests.test_sewing_flow_utilization_query_growth import _factory_user, _flow_set, _select_count


@pytest.mark.parametrize("count", [1, 50, 401])
def test_single_flow_direct_work_orders_do_not_query_assignments_per_row(count):
    with SessionLocal() as db:
        flow_ids = _flow_set(db, count)
        db.query(WorkOrder).filter(WorkOrder.sewing_flow_id.in_(flow_ids)).update(
            {"sewing_flow_id": flow_ids[0]}, synchronize_session=False)
        db.commit()
    with SessionLocal() as db:
        result, queries = _select_count(db, lambda: flow_utilization(flow_ids[0], db, _factory_user()))
    assert result["committed_today"] == count * 8
    assert queries == 3


def test_single_flow_preserves_split_exclusion_and_cancelled_assignment_fallback():
    with SessionLocal() as db:
        flow_ids = _flow_set(db, 3)
        work_orders = db.query(WorkOrder).filter(WorkOrder.sewing_flow_id.in_(flow_ids)).order_by(WorkOrder.id).all()
        for row in work_orders:
            row.sewing_flow_id = flow_ids[0]
        now = datetime.now(timezone.utc)
        db.add_all([
            SewingAssignment(work_order_id=work_orders[0].id, sewing_flow_id=flow_ids[0],
                             quantity=10, completed_qty=10, status="completed"),
            SewingAssignment(work_order_id=work_orders[1].id, sewing_flow_id=flow_ids[0],
                             quantity=10, completed_qty=0, status="cancelled"),
            SewingAssignment(work_order_id=work_orders[2].id, sewing_flow_id=flow_ids[0],
                             quantity=10, completed_qty=3, status="in_progress",
                             planned_start=now - timedelta(days=1), planned_end=now + timedelta(days=1)),
        ])
        db.commit()
    with SessionLocal() as db:
        result, queries = _select_count(db, lambda: flow_utilization(flow_ids[0], db, _factory_user()))
    assert result["committed_today"] == 12  # Cancelled ->8 direct; active split round(7/2) ->4.
    assert result["utilization_pct"] == 120.0
    assert queries == 3


def test_single_flow_utilization_projects_capacity_inputs_only():
    with SessionLocal() as db:
        flow_id = _flow_set(db, 1)[0]
        work_order = db.query(WorkOrder).filter_by(sewing_flow_id=flow_id).one()
        now = datetime.now(timezone.utc)
        db.add(SewingAssignment(
            work_order_id=work_order.id,
            sewing_flow_id=flow_id,
            quantity=10,
            completed_qty=2,
            status="in_progress",
            planned_start=now - timedelta(days=1),
            planned_end=now + timedelta(days=1),
        ))
        db.commit()

    with SessionLocal() as db:
        statements = []

        def capture(_conn, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            result = flow_utilization(flow_id, db, _factory_user())
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert result["committed_today"] == 4
    assert result["utilization_pct"] == 40.0
    assert len(statements) == 3
    flow_query = next(sql for sql in statements if "from sewing_flows" in sql)
    assignment_query = next(
        sql for sql in statements if "from sewing_assignments" in sql and "join work_orders" in sql
    )
    direct_work_order_query = next(
        sql for sql in statements if "from work_orders" in sql and "work_orders.sewing_flow_id" in sql
    )
    assert "sewing_flows.description" not in flow_query
    assert "sewing_flows.supervisor_id" not in flow_query
    assert "sewing_assignments.planned_start" in assignment_query
    assert "sewing_assignments.notes" not in assignment_query
    assert "work_orders.planned_output_qty" in direct_work_order_query
    assert "work_orders.notes" not in direct_work_order_query
