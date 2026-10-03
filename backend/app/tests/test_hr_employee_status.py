from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.models import AuditLog, Employee


SUPPORTED_STATUSES = ["active", "inactive", "on_leave", "terminated"]


def _counts():
    with SessionLocal() as db:
        return db.query(Employee).count(), db.query(AuditLog).filter_by(entity_type="Employee").count()


@pytest.mark.parametrize("status", ["suspended", "", "ACTIVE", None])
def test_employee_create_rejects_unknown_status_without_write(client, auth_headers, status):
    before = _counts()
    response = client.post("/api/employees", headers=auth_headers,
                           json={"full_name": "Invalid status", "status": status})
    assert response.status_code == 422, response.text
    assert _counts() == before


@pytest.mark.parametrize("status", ["suspended", "", "ACTIVE", None])
def test_employee_patch_rejects_unknown_status_without_write(client, auth_headers, status):
    created = client.post("/api/employees", headers=auth_headers, json={"full_name": "Status before patch"})
    assert created.status_code == 201, created.text
    employee_id = created.json()["id"]
    before = _counts()
    response = client.patch(f"/api/employees/{employee_id}", headers=auth_headers,
                            json={"full_name": "Changed", "status": status})
    assert response.status_code == 422, response.text
    assert _counts() == before
    with SessionLocal() as db:
        saved = db.get(Employee, employee_id)
        assert saved.status == "active"
        assert saved.full_name == "Status before patch"


@pytest.mark.parametrize("status", SUPPORTED_STATUSES)
def test_employee_accepts_supported_statuses_on_create_and_patch(client, auth_headers, status):
    response = client.post("/api/employees", headers=auth_headers,
                           json={"full_name": f"Supported {uuid4().hex}", "status": status})
    assert response.status_code == 201, response.text
    assert response.json()["status"] == status
    employee_id = response.json()["id"]
    updated = client.patch(f"/api/employees/{employee_id}", headers=auth_headers, json={"status": status})
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] == status


def test_employee_patch_preserves_legacy_status_when_omitted(client, auth_headers):
    with SessionLocal.begin() as db:
        employee = Employee(factory_code="MIL", full_name="Legacy status", status="historical-status")
        db.add(employee)
        db.flush()
        employee_id = employee.id
    response = client.patch(f"/api/employees/{employee_id}", headers=auth_headers,
                            json={"position": "Updated position"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "historical-status"
