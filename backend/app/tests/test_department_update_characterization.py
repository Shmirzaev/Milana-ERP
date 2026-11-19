"""Existing department-update normalization, refusal order and atomic audit."""

from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.schemas import AuditLog, Department
from app.tests.test_department_create_characterization import department_case  # noqa: F401
from app.tests.test_peo01_create_employee_characterization import (
    employee_database, h, headers,  # noqa: F401 - shared database and HTTP fixtures
)


def seed_departments(case):
    marker = uuid4().hex[:10]
    with case[0]() as db:
        row = Department(name=f"Original {marker}", code=f"O{marker}".upper())
        other = Department(name=f"Other {marker}", code=f"T{marker}".upper())
        db.add_all([row, other])
        db.commit()
        return row.id, other.id, row.name, row.code, other.name, other.code


def test_update_normalizes_and_audits_only_target(department_case):
    factory, users, client = case = department_case
    row_id, other_id, old_name, old_code, other_name, other_code = seed_departments(case)
    response = client.patch(f"/api/departments/{row_id}", headers=headers(case),
                            json={"name": "  Editable department  ", "code": "  people-custom  "})
    assert response.status_code == 200, response.text
    assert response.json() == {"id": row_id, "name": "Editable department", "code": "PEOPLE-CUSTOM"}
    with factory() as db:
        row = db.get(Department, row_id)
        assert (row.name, row.code) == ("Editable department", "PEOPLE-CUSTOM")
        other = db.get(Department, other_id)
        assert (other.name, other.code) == (other_name, other_code)
        audit = db.query(AuditLog).filter_by(entity_type="Department", entity_id=row_id).one()
        assert (audit.action, audit.user_id) == ("update", users["hr"])
        assert audit.old_value_json == {"name": old_name, "code": old_code}
        assert audit.new_value_json == {"name": "Editable department", "code": "PEOPLE-CUSTOM"}


@pytest.mark.parametrize("case_name,status,detail", [
    ("missing", 404, "Department not found"),
    ("blank", 400, "name and code are required"),
    ("duplicate_name", 400, "Department name already exists"),
    ("duplicate_code", 400, "Department code already exists"),
])
def test_update_refusals_preserve_values_and_audit(department_case, case_name, status, detail):
    factory, _, client = case = department_case
    row_id, _, old_name, old_code, other_name, other_code = seed_departments(case)
    values = {
        "missing": (99999999, {"name": " ", "code": " "}),
        "blank": (row_id, {"name": " ", "code": other_code}),
        "duplicate_name": (row_id, {"name": other_name, "code": other_code}),
        "duplicate_code": (row_id, {"name": old_name, "code": other_code}),
    }
    target, payload = values[case_name]
    with factory() as db:
        before = db.query(AuditLog).count()
    response = client.patch(f"/api/departments/{target}", headers=headers(case), json=payload)
    assert (response.status_code, response.json()) == (status, {"detail": detail})
    with factory() as db:
        row = db.get(Department, row_id)
        assert (row.name, row.code) == (old_name, old_code)
        assert db.query(AuditLog).count() == before


def test_update_permissions_and_commit_failure_are_atomic(department_case):
    factory, _, client = case = department_case
    row_id, _, old_name, old_code, _, _ = seed_departments(case)
    payload = {"name": "Should not persist", "code": "ROLLBACK"}
    with factory() as db:
        before = db.query(AuditLog).count()
    assert client.patch(f"/api/departments/{row_id}", headers=headers(case, "denied"), json=payload).status_code == 403
    assert client.patch(f"/api/departments/{row_id}", json=payload).status_code == 401

    def fail_commit(session):
        raise RuntimeError("Synthetic department update failure")

    event.listen(Session, "before_commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="Synthetic department update failure"):
            client.patch(f"/api/departments/{row_id}", headers=headers(case), json=payload)
    finally:
        event.remove(Session, "before_commit", fail_commit)
    with factory() as db:
        row = db.get(Department, row_id)
        assert (row.name, row.code) == (old_name, old_code)
        assert db.query(AuditLog).count() == before
