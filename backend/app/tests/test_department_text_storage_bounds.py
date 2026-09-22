import pytest

from app.models import AuditLog, Department
from app.tests.conftest import TestSessionLocal


def _counts() -> tuple[int, int]:
    with TestSessionLocal() as db:
        return db.query(Department).count(), db.query(AuditLog).filter_by(entity_type="Department").count()


def test_department_text_accepts_existing_column_boundaries(client, auth_headers):
    response = client.post(
        "/api/departments",
        headers=auth_headers,
        json={"name": "N" * 128, "code": "C" * 32},
    )
    assert response.status_code == 201, response.text
    assert response.json()["name"] == "N" * 128
    assert response.json()["code"] == "C" * 32


@pytest.mark.parametrize(
    ("field", "value"),
    [("name", "N" * 129), ("code", "C" * 33)],
)
def test_department_create_rejects_unstorable_text_without_writes(client, auth_headers, field, value):
    before = _counts()
    response = client.post(
        "/api/departments",
        headers=auth_headers,
        json={"name": "Valid department", "code": "VALID", field: value},
    )
    assert response.status_code == 422, response.text
    assert _counts() == before


def test_department_update_rejects_unstorable_text_without_mutation(client, auth_headers):
    created = client.post(
        "/api/departments",
        headers=auth_headers,
        json={"name": "Department before invalid update", "code": "DBIU"},
    )
    assert created.status_code == 201, created.text
    department_id = created.json()["id"]
    before = _counts()

    response = client.patch(
        f"/api/departments/{department_id}",
        headers=auth_headers,
        json={"name": "N" * 129, "code": "DBIU"},
    )
    assert response.status_code == 422, response.text
    assert _counts() == before
    with TestSessionLocal() as db:
        saved = db.get(Department, department_id)
        assert saved.name == "Department before invalid update"
        assert saved.code == "DBIU"


def test_department_text_bounds_preserve_auth_and_missing_row_precedence(client, auth_headers):
    unauthenticated = client.post(
        "/api/departments",
        json={"name": "N" * 129, "code": "VALID"},
    )
    assert unauthenticated.status_code == 401, unauthenticated.text

    missing = client.patch(
        "/api/departments/2147483647",
        headers=auth_headers,
        json={"name": "N" * 129, "code": "VALID"},
    )
    assert missing.status_code == 404, missing.text
