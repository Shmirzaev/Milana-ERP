"""Existing department deletion and linked-evidence guard precedence."""

from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.schemas import AuditLog, Department, Employee, Model, ProductionOrder, User, WorkOrder
from app.tests.test_department_create_characterization import department_case  # noqa: F401
from app.tests.test_peo01_create_employee_characterization import (
    employee_database, h, headers,  # noqa: F401 - shared database and HTTP fixtures
)


def department(case):
    marker = uuid4().hex[:12]
    with case[0]() as db:
        row = Department(name=f"Delete {marker}", code=marker.upper())
        db.add(row)
        db.commit()
        return row.id


def test_delete_audits_and_repeat_is_missing(department_case):
    factory, users, client = case = department_case
    row_id = department(case)
    response = client.delete(f"/api/departments/{row_id}", headers=headers(case))
    assert response.status_code == 204 and response.content == b""
    with factory() as db:
        assert db.get(Department, row_id) is None
        audit = db.query(AuditLog).filter_by(entity_type="Department", entity_id=row_id).one()
        assert (audit.action, audit.user_id, audit.old_value_json, audit.new_value_json) == (
            "delete", users["hr"], None, None,
        )
    again = client.delete(f"/api/departments/{row_id}", headers=headers(case))
    assert (again.status_code, again.json()) == (404, {"detail": "Department not found"})


@pytest.mark.parametrize("links,detail", [
    (("user", "employee", "work"), "Department is assigned to users. Reassign users before delete."),
    (("employee", "work"), "Department is assigned to employees. Reassign employees before delete."),
    (("work",), "Department is used by work orders. Delete is blocked."),
])
def test_delete_keeps_links_and_refusal_order(department_case, links, detail):
    factory, users, client = case = department_case
    row_id = department(case)
    marker = uuid4().hex
    with factory() as db:
        if "user" in links:
            db.get(User, users["hr"]).department_id = row_id
        if "employee" in links:
            db.add(Employee(full_name=f"Linked employee {marker}", factory_code="MIL", department_id=row_id))
        if "work" in links:
            model = Model(code=f"DEL-{marker}", name="Department guard model")
            db.add(model)
            db.flush()
            production = ProductionOrder(production_no=f"DEL-{marker}", production_type="branded_stock", model_id=model.id)
            db.add(production)
            db.flush()
            db.add(WorkOrder(production_order_id=production.id, department_id=row_id, operation="cutting"))
        db.commit()
        before = db.query(AuditLog).count()
        counts = db.query(User).count(), db.query(Employee).count(), db.query(WorkOrder).count()
    response = client.delete(f"/api/departments/{row_id}", headers=headers(case))
    assert (response.status_code, response.json()) == (409, {"detail": detail})
    with factory() as db:
        assert db.get(Department, row_id) is not None
        assert db.query(AuditLog).count() == before
        assert (db.query(User).count(), db.query(Employee).count(), db.query(WorkOrder).count()) == counts


def test_delete_permissions_and_commit_failure_preserve_row(department_case):
    factory, _, client = case = department_case
    row_id = department(case)
    with factory() as db:
        before = db.query(AuditLog).count()
    assert client.delete(f"/api/departments/{row_id}", headers=headers(case, "denied")).status_code == 403
    assert client.delete(f"/api/departments/{row_id}").status_code == 401

    def fail_commit(session):
        raise RuntimeError("Synthetic department delete failure")

    event.listen(Session, "before_commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="Synthetic department delete failure"):
            client.delete(f"/api/departments/{row_id}", headers=headers(case))
    finally:
        event.remove(Session, "before_commit", fail_commit)
    with factory() as db:
        assert db.get(Department, row_id) is not None
        assert db.query(AuditLog).count() == before
