"""Existing department-create contract, on SQLite and approved PostgreSQL."""

from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.schemas import AuditLog, Department, Role, User
from app.tests.test_peo01_create_employee_characterization import (
    employee_database, h, headers,  # noqa: F401 - shared database and HTTP fixtures
)


@pytest.fixture
def department_case(h):
    factory, users, client = h
    with factory() as db:
        role = db.get(Role, db.get(User, users["hr"]).role_id)
        role.permissions = ["*"]
        db.commit()
    return h


def test_create_keeps_raw_editable_values_and_audit(department_case):
    factory, users, client = case = department_case
    marker = uuid4().hex[:12]
    payload = {"name": f"  People {marker}  ", "code": f" raw-{marker} "}
    response = client.post("/api/departments", headers=headers(case), json=payload)
    assert response.status_code == 201, response.text
    assert response.json() == {"id": response.json()["id"], **payload}
    with factory() as db:
        row = db.get(Department, response.json()["id"])
        assert (row.name, row.code) == (payload["name"], payload["code"])
        audit = db.query(AuditLog).filter_by(entity_type="Department", entity_id=row.id).one()
        assert (audit.action, audit.user_id, audit.old_value_json, audit.new_value_json) == (
            "create", users["hr"], None, {"name": payload["name"]},
        )
    assert any(row["id"] == response.json()["id"] for row in client.get(
        "/api/departments", headers=headers(case),
    ).json())


def test_create_rejects_denied_and_unauthenticated_without_writes(department_case):
    factory, _, client = case = department_case
    payload = {"name": "Denied department", "code": uuid4().hex[:12]}
    with factory() as db:
        before = db.query(Department).count(), db.query(AuditLog).count()
    denied = client.post("/api/departments", headers=headers(case, "denied"), json=payload)
    assert denied.status_code == 403
    assert denied.json() == {"detail": "Missing permission. Need any of: ['*']"}
    assert client.post("/api/departments", json=payload).status_code == 401
    with factory() as db:
        assert (db.query(Department).count(), db.query(AuditLog).count()) == before


def test_create_commit_failure_rolls_back_department_and_audit(department_case):
    factory, _, client = case = department_case
    name = f"Rollback department {uuid4().hex}"
    with factory() as db:
        before = db.query(Department).count(), db.query(AuditLog).count()

    def fail_commit(session):
        raise RuntimeError("Synthetic department commit failure")

    event.listen(Session, "before_commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="Synthetic department commit failure"):
            client.post("/api/departments", headers=headers(case), json={"name": name, "code": uuid4().hex[:12]})
    finally:
        event.remove(Session, "before_commit", fail_commit)
    with factory() as db:
        assert db.query(Department).filter_by(name=name).first() is None
        assert (db.query(Department).count(), db.query(AuditLog).count()) == before
