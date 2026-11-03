"""Focused Option A packaging-write boundary and outer-transaction proof."""
from sqlalchemy import event

from app.schemas import Department, WorkOrder
from app.schemas.production.factory_routing import assign_packaging_department
from app.tests.conftest import TestSessionLocal
from app.tests.test_packaging_payroll_routing import routed_order


def test_packaging_department_helper_keeps_flow_and_never_flushes_or_commits():
    _, _, works, _, _ = routed_order()
    with TestSessionLocal.begin() as setup:
        row = setup.get(WorkOrder, works["packaging"])
        row.sewing_flow_id = setup.get(WorkOrder, works["sewing"]).sewing_flow_id
        flow = row.sewing_flow_id
        target = setup.query(Department.id).filter_by(code="BPK").scalar()
        old_department = row.department_id
    assert flow is not None and target != old_department
    with TestSessionLocal() as db:
        row = db.get(WorkOrder, works["packaging"])
        events = []
        event.listen(db, "after_flush", lambda *_: events.append("flush"))
        event.listen(db, "after_commit", lambda *_: events.append("commit"))
        assign_packaging_department(row, target)
        assert row.department_id == target and row.sewing_flow_id == flow
        assert events == []
        db.commit()
        assert events == ["flush", "commit"]
    with TestSessionLocal() as db:
        row = db.get(WorkOrder, works["packaging"])
        assert row.department_id == target and row.sewing_flow_id == flow
