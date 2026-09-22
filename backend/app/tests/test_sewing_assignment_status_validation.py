from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.models import AuditLog, Department, ProductionOrder, SewingAssignment, SewingFlow, WorkOrder


VALID_STATUSES = ("planned", "in_progress", "completed", "cancelled", "transferred")


def _assignment_case() -> tuple[int, int]:
    marker = uuid4().hex[:12]
    with SessionLocal() as db:
        department_id = db.query(Department.id).filter(Department.code == "SEW").scalar()
        order = ProductionOrder(
            production_no=f"ASSIGNMENT-STATUS-{marker}",
            production_type="branded_stock",
            model_id=1,
            planned_quantity=100,
        )
        flow = SewingFlow(
            factory_code="MIL",
            name=f"Assignment status {marker}",
            code=f"AS-{marker}",
            is_active=True,
        )
        db.add_all([order, flow])
        db.flush()
        work_order = WorkOrder(
            production_order_id=order.id,
            department_id=department_id,
            operation="sewing",
            status="in_progress",
            planned_input_qty=100,
            planned_output_qty=100,
            sewing_flow_id=flow.id,
        )
        db.add(work_order)
        db.flush()
        assignment = SewingAssignment(
            work_order_id=work_order.id,
            sewing_flow_id=flow.id,
            quantity=100,
            completed_qty=0,
            status="planned",
            notes="original",
        )
        db.add(assignment)
        db.commit()
        return int(assignment.id), int(flow.id)


@pytest.mark.parametrize("status", VALID_STATUSES)
def test_sewing_assignment_patch_accepts_established_status_vocabulary(client, auth_headers, status):
    assignment_id, _ = _assignment_case()

    response = client.patch(
        f"/api/sewing-assignments/{assignment_id}",
        headers=auth_headers,
        json={"status": status},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == status
    with SessionLocal() as db:
        assert db.get(SewingAssignment, assignment_id).status == status


def test_sewing_assignment_patch_rejects_unknown_status_without_mutation(client, auth_headers):
    assignment_id, _ = _assignment_case()
    with SessionLocal() as db:
        before_audits = db.query(AuditLog).count()

    response = client.patch(
        f"/api/sewing-assignments/{assignment_id}",
        headers=auth_headers,
        json={"status": "paused", "quantity": 90, "notes": "changed"},
    )

    assert response.status_code == 400, response.text
    assert response.json() == {"detail": "Invalid sewing assignment status"}
    with SessionLocal() as db:
        assignment = db.get(SewingAssignment, assignment_id)
        assert assignment.status == "planned"
        assert assignment.quantity == 100
        assert assignment.notes == "original"
        assert assignment.actual_end is None
        assert db.query(AuditLog).count() == before_audits


def test_sewing_assignment_patch_preserves_missing_assignment_precedence(client, auth_headers):
    response = client.patch(
        "/api/sewing-assignments/2147483647",
        headers=auth_headers,
        json={"status": "paused"},
    )

    assert response.status_code == 404, response.text
    assert response.json() == {"detail": "Assignment not found"}


def test_sewing_assignment_patch_preserves_missing_flow_precedence(client, auth_headers):
    assignment_id, _ = _assignment_case()

    response = client.patch(
        f"/api/sewing-assignments/{assignment_id}",
        headers=auth_headers,
        json={"sewing_flow_id": 2_147_483_647, "status": "paused"},
    )

    assert response.status_code == 404, response.text
    assert response.json() == {"detail": "Sewing flow not found"}
    with SessionLocal() as db:
        assignment = db.get(SewingAssignment, assignment_id)
        assert assignment.status == "planned"
        assert assignment.sewing_flow_id != 2_147_483_647


def test_sewing_assignment_patch_preserves_authentication_precedence(client):
    assignment_id, _ = _assignment_case()

    response = client.patch(
        f"/api/sewing-assignments/{assignment_id}",
        json={"status": "paused"},
    )

    assert response.status_code == 401, response.text
    with SessionLocal() as db:
        assert db.get(SewingAssignment, assignment_id).status == "planned"
