from datetime import date
from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.models import Department, ProductionOrder, SewingAssignment, SewingDailyReport, SewingFlow, WorkOrder


def make_assignment(*, factory="MIL", completed=0, report=False):
    with SessionLocal() as db:
        department = db.query(Department).filter(Department.code == ("SEW" if factory == "MIL" else "BST")).one()
        po = ProductionOrder(production_no=f"PO-RETURN-{uuid4().hex[:8]}", production_type="branded_stock", model_id=1, planned_quantity=100)
        flow = SewingFlow(factory_code=factory, name="Return source", code="RETURN-SOURCE", is_active=True)
        db.add_all([po, flow]); db.flush()
        wo = WorkOrder(production_order_id=po.id, department_id=department.id, operation="sewing",
                       status="in_progress", planned_input_qty=100, planned_output_qty=100, sewing_flow_id=flow.id)
        db.add(wo); db.flush()
        assignment = SewingAssignment(work_order_id=wo.id, sewing_flow_id=flow.id, quantity=100,
                                      completed_qty=completed, status="planned")
        db.add(assignment); db.flush()
        if report:
            db.add(SewingDailyReport(report_date=date.today(), sewing_flow_id=flow.id,
                                    work_order_id=wo.id, sewing_assignment_id=assignment.id,
                                    line_code=flow.code, line_name=flow.name, sewn_qty=0, defective_qty=0))
        db.commit()
        return assignment.id, flow.id, wo.id


def test_return_releases_assignment_without_deleting_history_and_allows_reassignment(client, auth_headers):
    aid, fid, wid = make_assignment()
    for _ in range(2):
        response = client.post(f"/api/sewing-assignments/{aid}/return", json={"sewing_flow_id": fid}, headers=auth_headers)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "cancelled"
    with SessionLocal() as db:
        assert db.get(SewingAssignment, aid).quantity == 100
        assert db.get(WorkOrder, wid).sewing_flow_id is None
    rows = client.get(f"/api/sewing-flows/{fid}/work-orders?only_active=true", headers=auth_headers).json()
    assert not any(row.get("sewing_assignment_id") == aid or row["id"] == wid for row in rows)
    response = client.post(f"/api/work-orders/{wid}/assignments", headers=auth_headers,
                           json={"work_order_id": wid, "sewing_flow_id": fid, "quantity": 100})
    assert response.status_code == 201, response.text


@pytest.mark.parametrize("completed,report", [(1, False), (0, True)])
def test_return_preserves_output_and_report_assignments(client, auth_headers, completed, report):
    aid, fid, wid = make_assignment(completed=completed, report=report)
    response = client.post(f"/api/sewing-assignments/{aid}/return", json={"sewing_flow_id": fid}, headers=auth_headers)
    assert response.status_code == 409 and response.json()["detail"] == "SEWING_RETURN_HAS_OUTPUT"
    with SessionLocal() as db:
        assert db.get(SewingAssignment, aid).status == "planned"
        assert db.get(WorkOrder, wid).sewing_flow_id == fid


def test_return_rejects_cross_factory_and_stale_line(client, auth_headers):
    aid, fid, _ = make_assignment(factory="BST")
    response = client.post(f"/api/sewing-assignments/{aid}/return", json={"sewing_flow_id": fid}, headers=auth_headers)
    assert response.status_code == 403, response.text
    aid, fid, _ = make_assignment()
    response = client.post(f"/api/sewing-assignments/{aid}/return", json={"sewing_flow_id": fid + 1}, headers=auth_headers)
    assert response.status_code == 409 and response.json()["detail"] == "SEWING_RETURN_MOVED"
