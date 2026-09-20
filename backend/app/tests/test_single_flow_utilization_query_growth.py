from datetime import datetime, timedelta, timezone

import pytest

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
