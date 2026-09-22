from decimal import Decimal
from uuid import uuid4

import pytest

from app.models import AuditLog, PayrollAdjustment
from app.tests.conftest import TestSessionLocal


def _counts() -> tuple[int, int]:
    with TestSessionLocal() as db:
        return db.query(PayrollAdjustment).count(), db.query(AuditLog).count()


def test_payroll_adjustment_accepts_numeric_storage_maximum(client, auth_headers):
    employee = client.post(
        "/api/employees",
        json={"full_name": f"Adjustment Worker {uuid4().hex[:8]}", "position": "Operator", "status": "active"},
        headers=auth_headers,
    )
    assert employee.status_code == 201, employee.text

    response = client.post(
        "/api/payroll/adjustments",
        json={"employee_id": employee.json()["id"], "amount": "999999999999.99", "reason": "Boundary"},
        headers=auth_headers,
    )

    assert response.status_code == 201, response.text
    assert Decimal(str(response.json()["amount"])) == Decimal("999999999999.99")


@pytest.mark.parametrize("amount", ["1000000000000", "-1000000000000"])
def test_payroll_adjustment_rejects_amount_outside_numeric_storage_without_writes(
    client, auth_headers, amount
):
    employee = client.post(
        "/api/employees",
        json={"full_name": f"Adjustment Worker {uuid4().hex[:8]}", "position": "Operator", "status": "active"},
        headers=auth_headers,
    )
    assert employee.status_code == 201, employee.text
    before = _counts()

    response = client.post(
        "/api/payroll/adjustments",
        json={"employee_id": employee.json()["id"], "amount": amount, "reason": "Boundary"},
        headers=auth_headers,
    )

    assert response.status_code == 400, response.text
    assert _counts() == before


def test_unrepresentable_adjustment_amount_preserves_auth_precedence(client):
    before = _counts()
    response = client.post(
        "/api/payroll/adjustments",
        json={"employee_id": 1, "amount": "1000000000000", "reason": "Boundary"},
    )
    assert response.status_code == 401, response.text
    assert _counts() == before
