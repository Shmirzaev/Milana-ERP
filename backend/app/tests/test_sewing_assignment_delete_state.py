"""Unused sewing assignments may be deleted; production evidence may not be erased."""

import pytest

from app.db.session import SessionLocal
from app.models import AuditLog, SewingAssignment, SewingRecord
from app.tests.test_sewing_assignment_return import make_assignment


@pytest.mark.parametrize(
    ("scenario", "error"),
    [
        ("completed_qty", "SEWING_DELETE_HAS_OUTPUT"),
        ("report", "SEWING_DELETE_HAS_OUTPUT"),
        ("record", "SEWING_DELETE_HAS_OUTPUT"),
        ("completed_status", "SEWING_DELETE_INACTIVE"),
        ("cancelled_status", "SEWING_DELETE_INACTIVE"),
    ],
)
def test_delete_rejects_used_or_historical_assignment_without_writes(client, auth_headers, scenario, error):
    aid, _flow_id, work_order_id = make_assignment(
        completed=1 if scenario == "completed_qty" else 0,
        report=scenario == "report",
    )
    with SessionLocal() as db:
        assignment = db.get(SewingAssignment, aid)
        if scenario == "record":
            db.add(SewingRecord(
                work_order_id=work_order_id,
                sewing_assignment_id=aid,
                line_name="Different line name",
            ))
        elif scenario == "completed_status":
            assignment.status = "completed"
        elif scenario == "cancelled_status":
            assignment.status = "cancelled"
        db.commit()
        prior_status = assignment.status
        prior_completed = assignment.completed_qty
        prior_audit_count = db.query(AuditLog).count()

    response = client.delete(f"/api/sewing-assignments/{aid}", headers=auth_headers)

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == error
    with SessionLocal() as db:
        assignment = db.get(SewingAssignment, aid)
        assert assignment is not None
        assert (assignment.status, assignment.completed_qty) == (prior_status, prior_completed)
        assert db.query(AuditLog).count() == prior_audit_count


def test_return_rejects_directly_linked_record_even_if_line_name_differs(client, auth_headers):
    aid, flow_id, work_order_id = make_assignment()
    with SessionLocal() as db:
        db.add(SewingRecord(
            work_order_id=work_order_id,
            sewing_assignment_id=aid,
            line_name="Different line name",
        ))
        db.commit()

    response = client.post(
        f"/api/sewing-assignments/{aid}/return",
        json={"sewing_flow_id": flow_id},
        headers=auth_headers,
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "SEWING_RETURN_HAS_OUTPUT"
    with SessionLocal() as db:
        assert db.get(SewingAssignment, aid).status == "planned"
