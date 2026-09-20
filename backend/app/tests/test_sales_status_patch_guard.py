"""Generic order edits cannot manufacture workflow progress."""

from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.models import AuditLog, SalesOrder


def _order(status="draft"):
    with SessionLocal() as db:
        row = SalesOrder(order_no=f"STATUS-{uuid4().hex}", status=status, notes="original", total_amount=100)
        db.add(row)
        db.commit()
        return row.id


@pytest.mark.parametrize("status", ["confirmed", "ready", "shipped", "delivered", "cancelled", "bogus", None])
def test_patch_cannot_skip_workflow_or_partially_apply(client, auth_headers, status):
    order_id = _order()
    with SessionLocal() as db:
        audit_count = db.query(AuditLog).count()
    response = client.patch(f"/api/sales-orders/{order_id}", headers=auth_headers,
                            json={"status": status, "notes": "must not save"})
    assert response.status_code == 409, response.text
    with SessionLocal() as db:
        row = db.get(SalesOrder, order_id)
        assert row.status == "draft"
        assert row.notes == "original"
        assert db.query(AuditLog).count() == audit_count


@pytest.mark.parametrize("status", ["draft", "shipped", "cancelled"])
def test_unchanged_status_and_normal_edits_remain_supported(client, auth_headers, status):
    order_id = _order(status)
    response = client.patch(f"/api/sales-orders/{order_id}", headers=auth_headers,
                            json={"status": status, "notes": "updated"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == status
    assert response.json()["notes"] == "updated"
    response = client.patch(f"/api/sales-orders/{order_id}", headers=auth_headers, json={"notes": "again"})
    assert response.status_code == 200
    assert response.json()["status"] == status


def test_confirm_command_still_advances_draft(client, auth_headers):
    order_id = _order()
    response = client.post(f"/api/sales-orders/{order_id}/confirm", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "confirmed"
