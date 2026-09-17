import pytest
from app.tests.test_sewing_assignment_return import make_assignment
from app.tests.conftest import TestSessionLocal
from app.models import (SewingRecord, SewingAssignment, WorkOrder, AuditLog, Department,
                        PackagingReceipt, SewingReplacementRequest, Role, User)
from app.main import app
from app.core.deps import get_current_user


def setup_record(factory="MIL"):
    aid, fid, wid = make_assignment(factory=factory, completed=80)
    with TestSessionLocal() as db:
        wo = db.get(WorkOrder, wid)
        wo.actual_input_qty = 100
        wo.actual_output_qty = wo.passed_qty = 80
        row = SewingRecord(work_order_id=wid, input_qty=100, sewn_qty=80, passed_qty=80,
            line_name="Return source", sewing_assignment_id=aid, assignment_applied_qty=80)
        db.add(row); db.commit()
        return row.id, wid, aid


def update(client, headers, rid, **values):
    return client.patch(f"/api/sewing/records/{rid}", headers=headers,
        json={"expected_version": 0, "input_qty": 90, "sewn_qty": 60, "passed_qty": 60, **values})


def test_edit_delete_updates_totals_audit_and_rejects_stale(client, auth_headers):
    rid, wid, aid = setup_record()
    result = update(client, auth_headers, rid)
    assert result.status_code == 200, result.text
    assert result.json()["correction_version"] == 1
    assert update(client, auth_headers, rid).status_code == 409
    with TestSessionLocal() as db:
        wo = db.get(WorkOrder, wid)
        assert (wo.actual_input_qty, wo.actual_output_qty, wo.passed_qty) == (90, 60, 60)
        assert db.get(SewingAssignment, aid).completed_qty == 60
        log = db.query(AuditLog).filter_by(entity_type="SewingRecord", entity_id=rid, action="update").one()
        assert log.old_value_json["input_qty"] == 100 and log.new_value_json["input_qty"] == 90
    response = client.request("DELETE", f"/api/sewing/records/{rid}", headers=auth_headers, json={"expected_version": 1})
    assert response.status_code == 200, response.text
    with TestSessionLocal() as db:
        wo = db.get(WorkOrder, wid)
        assert (wo.actual_input_qty, wo.actual_output_qty, wo.passed_qty) == (0, 0, 0)
        assert db.get(SewingRecord, rid) is None
        assert db.get(SewingAssignment, aid).completed_qty == 0
        assert db.query(AuditLog).filter_by(entity_type="SewingRecord", entity_id=rid, action="delete").count() == 1


@pytest.mark.parametrize("values,status", [({"input_qty": -1}, 422), ({"passed_qty": 70, "sewn_qty": 60}, 422),
    ({"input_qty": 30}, 409), ({"input_qty": 110}, 409), ({"unexpected": 1}, 422)])
def test_bad_changes_rollback(client, auth_headers, values, status):
    rid, wid, aid = setup_record()
    assert update(client, auth_headers, rid, **values).status_code == status
    with TestSessionLocal() as db:
        assert db.get(SewingRecord, rid).passed_qty == 80
        assert db.get(WorkOrder, wid).passed_qty == 80
        assert db.get(SewingAssignment, aid).completed_qty == 80


@pytest.mark.parametrize("linked", ["packaging", "replacement"])
def test_linked_output_cannot_change(client, auth_headers, linked):
    rid, wid, _ = setup_record()
    with TestSessionLocal() as db:
        wo = db.get(WorkOrder, wid)
        if linked == "replacement":
            db.add(SewingReplacementRequest(production_order_id=wo.production_order_id,
                sewing_work_order_id=wid, sewing_record_id=rid, requested_qty=1))
        else:
            department = db.query(Department).filter_by(code="PKG").one()
            pkg = WorkOrder(production_order_id=wo.production_order_id, department_id=department.id,
                operation="packaging", status="collected")
            db.add(pkg); db.flush()
            db.add(PackagingReceipt(work_order_id=pkg.id, source_work_order_id=wid,
                production_order_id=wo.production_order_id, quantity=10, receive_method="manual"))
        db.commit()
    assert update(client, auth_headers, rid).status_code == 409
    assert client.request("DELETE", f"/api/sewing/records/{rid}", headers=auth_headers,
        json={"expected_version": 0}).status_code == 409
    rows = client.get(f"/api/work-orders/{wid}/sewing-records", headers=auth_headers).json()
    assert rows[0]["locked_reason"]


def test_factory_and_permission_enforced(client, auth_headers):
    rid, wid, _ = setup_record("BST")
    assert update(client, auth_headers, rid).status_code == 403
    assert client.get(f"/api/work-orders/{wid}/sewing-records", headers=auth_headers).status_code == 403
    with TestSessionLocal() as db:
        role = Role(name="Read only sewing", permissions=["sewing.daily_reports.view"])
        user = User(name="Reader", email="reader-test@example.com", password_hash="unused", role=role, factory_code="BST")
        db.add(user); db.commit()
        app.dependency_overrides[get_current_user] = lambda: user
        try:
            assert update(client, {}, rid).status_code == 403
            assert client.get(f"/api/work-orders/{wid}/sewing-records").status_code == 403
        finally: app.dependency_overrides.pop(get_current_user)


def test_legacy_assignment_safe_inference(client, auth_headers):
    rid, wid, aid = setup_record()
    with TestSessionLocal() as db:
        row = db.get(SewingRecord, rid)
        row.sewing_assignment_id = None
        row.assignment_applied_qty = None
        db.commit()
    assert update(client, auth_headers, rid).status_code == 200
    with TestSessionLocal() as db:
        assert db.get(SewingAssignment, aid).completed_qty == 60
        assert db.get(SewingRecord, rid).sewing_assignment_id == aid


@pytest.mark.parametrize("batched", [False, True])
def test_input_increase_uses_actual_upstream_not_plan(client, auth_headers, batched):
    from app.models import ProductionBatch, CuttingRecord
    rid, wid, aid = setup_record()
    with TestSessionLocal() as db:
        wo = db.get(WorkOrder, wid)
        wo.planned_input_qty = 500
        cut = WorkOrder(production_order_id=wo.production_order_id, department_id=wo.department_id,
            operation="cutting", status="in_progress", planned_output_qty=500, passed_qty=110)
        db.add(cut); db.flush()
        if batched:
            batch = ProductionBatch(production_order_id=wo.production_order_id, batch_no="UPSTREAM-1", planned_quantity=500)
            db.add(batch); db.flush()
            db.get(SewingRecord, rid).production_batch_id = batch.id
            db.get(SewingAssignment, aid).production_batch_id = batch.id
            db.add(CuttingRecord(work_order_id=cut.id, production_batch_id=batch.id, cut_pieces=110, passed_pieces=110))
        db.commit()
    blocked = update(client, auth_headers, rid, input_qty=120)
    assert blocked.status_code == 409 and blocked.json()["detail"] == "sewingEdit.upstreamLimit"
    allowed = update(client, auth_headers, rid, input_qty=110)
    assert allowed.status_code == 200, allowed.text
