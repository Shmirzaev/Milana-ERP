import pytest

from app.db.session import SessionLocal
from app.models import AuditLog, WorkOrder
from app.tests.test_sewing_assignment_return import make_assignment


@pytest.mark.parametrize("status", ["completed", "cancelled", "not_a_status", None])
def test_generic_work_order_patch_rejects_status_changes_without_writes(
    client, auth_headers, status,
):
    _, _, work_order_id = make_assignment()
    with SessionLocal() as db:
        before_status = db.get(WorkOrder, work_order_id).status
        before_audits = db.query(AuditLog).count()

    response = client.patch(
        f"/api/work-orders/{work_order_id}",
        headers=auth_headers,
        json={"status": status, "notes": "Must not persist"},
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "Use a work-order action to change status"
    with SessionLocal() as db:
        work_order = db.get(WorkOrder, work_order_id)
        assert work_order.status == before_status
        assert work_order.notes is None
        assert db.query(AuditLog).count() == before_audits


def test_generic_work_order_patch_ignores_unchanged_status_on_metadata_edit(client, auth_headers):
    _, _, work_order_id = make_assignment()

    response = client.patch(
        f"/api/work-orders/{work_order_id}",
        headers=auth_headers,
        json={"status": "in_progress", "notes": "Updated note"},
    )

    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        work_order = db.get(WorkOrder, work_order_id)
        assert work_order.status == "in_progress"
        assert work_order.notes == "Updated note"
        audit = db.query(AuditLog).filter_by(entity_type="WorkOrder", entity_id=work_order_id, action="update").one()
        assert audit.new_value_json == {"notes": "Updated note"}


def test_generic_work_order_status_only_noop_does_not_append_audit(client, auth_headers):
    _, _, work_order_id = make_assignment()
    with SessionLocal() as db:
        before_audits = db.query(AuditLog).count()

    response = client.patch(
        f"/api/work-orders/{work_order_id}", headers=auth_headers,
        json={"status": "in_progress"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "in_progress"
    with SessionLocal() as db:
        assert db.query(AuditLog).count() == before_audits


def test_unauthenticated_bad_status_keeps_auth_precedence(client):
    response = client.patch("/api/work-orders/2147483647", json={"status": "not_a_status"})
    assert response.status_code == 401, response.text
