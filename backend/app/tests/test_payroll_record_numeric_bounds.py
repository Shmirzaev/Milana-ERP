from decimal import Decimal
from uuid import uuid4

import pytest

from app.models import AuditLog, PayrollRecord
from app.tests.conftest import TestSessionLocal


MAX_COMPONENT = "9999999999.9999"
MAX_TOTAL = Decimal("999999999999.99")


def _create_employee(client, auth_headers) -> int:
    response = client.post(
        "/api/employees",
        headers=auth_headers,
        json={"full_name": f"Payroll Bound {uuid4().hex[:8]}", "position": "Operator", "status": "active"},
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def _write_counts() -> tuple[int, int]:
    with TestSessionLocal() as db:
        return db.query(PayrollRecord).count(), db.query(AuditLog).count()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("quantity", "10000000000"),
        ("rate_per_piece", "10000000000"),
        ("quantity", "NaN"),
        ("rate_per_piece", "Infinity"),
    ],
)
def test_payroll_record_component_bounds_reject_unrepresentable_values_without_writes(
    client, auth_headers, field, value
):
    employee_id = _create_employee(client, auth_headers)
    before = _write_counts()
    payload = {"employee_id": employee_id, "quantity": "1", "rate_per_piece": "1"}
    payload[field] = value

    response = client.post("/api/payroll/records", headers=auth_headers, json=payload)

    assert response.status_code == 400, response.text
    assert _write_counts() == before


def test_payroll_record_derived_total_bound_rejects_overflow_without_writes(client, auth_headers):
    employee_id = _create_employee(client, auth_headers)
    before = _write_counts()

    response = client.post(
        "/api/payroll/records",
        headers=auth_headers,
        json={"employee_id": employee_id, "quantity": MAX_COMPONENT, "rate_per_piece": "100.0001"},
    )

    assert response.status_code == 400, response.text
    assert _write_counts() == before


def test_payroll_record_exact_component_and_total_maxima_remain_accepted(client, auth_headers):
    employee_id = _create_employee(client, auth_headers)

    response = client.post(
        "/api/payroll/records",
        headers=auth_headers,
        json={"employee_id": employee_id, "quantity": MAX_COMPONENT, "rate_per_piece": "100"},
    )

    assert response.status_code == 201, response.text
    assert Decimal(str(response.json()["quantity"])) == Decimal(MAX_COMPONENT)
    assert Decimal(str(response.json()["total_amount"])) == MAX_TOTAL


def test_unrepresentable_payroll_record_preserves_auth_precedence(client):
    before = _write_counts()

    response = client.post(
        "/api/payroll/records",
        json={"employee_id": 1, "quantity": MAX_COMPONENT, "rate_per_piece": "100.0001"},
    )

    assert response.status_code == 401, response.text
    assert _write_counts() == before
