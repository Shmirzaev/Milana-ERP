from uuid import uuid4

import pytest

from app.models import AuditLog, Employee
from app.tests.conftest import TestSessionLocal


def _counts() -> tuple[int, int]:
    with TestSessionLocal() as db:
        return db.query(Employee).count(), db.query(AuditLog).filter_by(entity_type="Employee").count()


def test_employee_text_fields_accept_existing_column_boundaries(client, auth_headers):
    response = client.post(
        "/api/employees",
        headers=auth_headers,
        json={"full_name": "N" * 255, "position": "P" * 128, "phone": "1" * 64},
    )
    assert response.status_code == 201, response.text
    assert response.json()["full_name"] == "N" * 255
    assert response.json()["position"] == "P" * 128
    assert response.json()["phone"] == "1" * 64


@pytest.mark.parametrize(
    ("field", "value"),
    [("full_name", "N" * 256), ("position", "P" * 129), ("phone", "1" * 65)],
)
def test_employee_create_rejects_unstorable_text_without_writes(client, auth_headers, field, value):
    before = _counts()
    response = client.post(
        "/api/employees",
        headers=auth_headers,
        json={"full_name": "Valid name", field: value},
    )
    assert response.status_code == 422, response.text
    assert _counts() == before


def test_employee_patch_rejects_unstorable_text_without_mutation(client, auth_headers):
    created = client.post(
        "/api/employees",
        headers=auth_headers,
        json={"full_name": f"Text boundary {uuid4().hex[:8]}", "position": "Operator"},
    )
    assert created.status_code == 201, created.text
    employee_id = created.json()["id"]
    before = _counts()

    response = client.patch(
        f"/api/employees/{employee_id}",
        headers=auth_headers,
        json={"position": "P" * 129},
    )
    assert response.status_code == 422, response.text
    assert _counts() == before
    with TestSessionLocal() as db:
        assert db.get(Employee, employee_id).position == "Operator"


def test_employee_text_bounds_preserve_auth_and_not_found_precedence(client, auth_headers):
    unauthenticated = client.post(
        "/api/employees",
        json={"full_name": "N" * 256},
    )
    assert unauthenticated.status_code == 401, unauthenticated.text

    missing = client.patch(
        "/api/employees/2147483647",
        headers=auth_headers,
        json={"position": "P" * 129},
    )
    assert missing.status_code == 404, missing.text
