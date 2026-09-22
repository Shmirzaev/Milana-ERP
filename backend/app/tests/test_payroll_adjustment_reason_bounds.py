from uuid import uuid4

from app.models import AuditLog, PayrollAdjustment
from app.tests.conftest import TestSessionLocal


def _counts() -> tuple[int, int]:
    with TestSessionLocal() as db:
        return db.query(PayrollAdjustment).count(), db.query(AuditLog).count()


def test_payroll_adjustment_reason_enforces_storage_limit(client, auth_headers):
    employee = client.post(
        "/api/employees",
        json={"full_name": f"Adjustment Worker {uuid4().hex[:8]}", "position": "Operator", "status": "active"},
        headers=auth_headers,
    )
    assert employee.status_code == 201, employee.text

    accepted = client.post(
        "/api/payroll/adjustments",
        json={"employee_id": employee.json()["id"], "amount": 1, "reason": "x" * 255},
        headers=auth_headers,
    )
    assert accepted.status_code == 201, accepted.text
    assert len(accepted.json()["reason"]) == 255

    before = _counts()
    rejected = client.post(
        "/api/payroll/adjustments",
        json={"employee_id": employee.json()["id"], "amount": 1, "reason": "x" * 256},
        headers=auth_headers,
    )
    assert rejected.status_code == 422, rejected.text
    assert _counts() == before


def test_oversized_payroll_adjustment_reason_preserves_auth_precedence(client):
    before = _counts()
    response = client.post(
        "/api/payroll/adjustments",
        json={"employee_id": 1, "amount": 1, "reason": "x" * 256},
    )
    assert response.status_code == 401, response.text
    assert _counts() == before
