"""PEO-01 baseline for the existing employee-create HTTP operation."""

from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.schemas import AuditLog, Employee, Role, User
from app.tests.conftest import TestSessionLocal
from app.tests.pg_approved_instance import (
    ApprovedInstanceUnavailable, create_target_database, finalize_target,
    load_approved_instance, require_or_skip, target_engine,
)


@pytest.fixture(scope="module", params=["sqlite", "postgres"])
def employee_database(request):
    if request.param == "sqlite":
        yield TestSessionLocal
        return
    try:
        instance = load_approved_instance()
    except ApprovedInstanceUnavailable as exc:
        require_or_skip(exc)
    target = create_target_database(instance)
    engine = None
    try:
        engine = target_engine(target, options="-ctimezone=UTC")
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        finalize_target(target, engine)


@pytest.fixture
def h(employee_database):
    factory = employee_database
    marker = uuid4().hex
    with factory() as db:
        roles = {}
        users = {}
        for name, factory_code, permissions in (
            ("hr", "MIL", ["hr.employees"]),
            ("denied", "MIL", ["finance.view"]),
            ("eco", "ECO", ["hr.employees"]),
        ):
            role = Role(name=f"PEO01 {name} {marker}", permissions=permissions)
            db.add(role)
            db.flush()
            user = User(name=name, email=f"peo01-{name}-{marker}@example.invalid",
                        password_hash="test-only", role_id=role.id,
                        factory_code=factory_code, is_active=True)
            db.add(user)
            db.flush()
            roles[name] = role.id
            users[name] = user.id
        db.commit()

    def sessions():
        with factory() as db:
            yield db

    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = sessions
    try:
        yield factory, users, TestClient(app)
    finally:
        app.dependency_overrides[get_db] = previous


def headers(h, actor="hr"):
    _, users, _ = h
    factory = "ECO" if actor == "eco" else "MIL"
    return {"Authorization": f"Bearer {create_access_token(users[actor], {'factory_code': factory})}"}


def counts(h):
    factory, _, _ = h
    with factory() as db:
        return db.query(Employee).count(), db.query(AuditLog).filter_by(entity_type="Employee").count()


def test_create_employee_persists_factory_number_salary_profile_and_audit(h):
    factory, users, client = h
    before = counts(h)
    response = client.post("/api/employees", headers=headers(h), json={
        "full_name": "PEO01 Alice", "employee_no": "  74001  ",
        "salary": "1250.25555", "hr_profile_json": {"scheduled_daily_hours": "8"},
    })
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["factory_code"] == "MIL"
    assert body["employee_no"] == "74001"
    assert body["salary"] == 1250.2556
    assert body["hr_profile_json"] == {"scheduled_daily_hours": "8"}
    assert counts(h) == (before[0] + 1, before[1] + 1)
    with factory() as db:
        employee = db.get(Employee, body["id"])
        assert (employee.full_name, employee.factory_code, employee.employee_no) == ("PEO01 Alice", "MIL", "74001")
        assert employee.salary == Decimal("1250.2556")
        assert employee.hr_profile_json == {"scheduled_daily_hours": "8"}
        audit = db.query(AuditLog).filter_by(action="create", entity_type="Employee", entity_id=employee.id).one()
        assert audit.user_id == users["hr"]
        assert audit.new_value_json == {"employee_no": "74001", "full_name": "PEO01 Alice"}
    assert client.get(f"/api/employees/{body['id']}", headers=headers(h)).status_code == 200
    assert client.get(f"/api/employees/{body['id']}", headers=headers(h, "eco")).status_code == 404


@pytest.mark.parametrize("payload,status,detail", [
    ({"user_id": 99999999, "employee_no": "1", "salary": "-1"}, 404, "Employee user not found"),
    ({"department_id": 99999999, "manager_employee_id": 99999999}, 404, "Employee department not found"),
    ({"manager_employee_id": 99999999, "hr_position_id": 99999999}, 404, "Employee manager not found in this factory"),
    ({"hr_position_id": 99999999, "salary": "-1"}, 404, "HR position not found in this factory"),
    ({"salary": "-1", "hr_profile_json": {"scheduled_daily_hours": 25}}, 422, "Employee salary must be nonnegative"),
    ({"hr_profile_json": {"scheduled_daily_hours": 25}}, 422, "scheduled_daily_hours must be finite and greater than 0 and no more than 24"),
])
def test_create_refusal_order_and_no_writes(h, payload, status, detail):
    before = counts(h)
    result = h[2].post("/api/employees", headers=headers(h), json={"full_name": "Refused", **payload})
    assert (result.status_code, result.json()) == (status, {"detail": detail})
    assert counts(h) == before


def test_duplicate_number_and_permission_refusals(h):
    _, _, client = h
    number = str(uuid4().int)[:12]
    created = client.post("/api/employees", headers=headers(h), json={"full_name": "First", "employee_no": number})
    assert created.status_code == 201, created.text
    before = counts(h)
    duplicate = client.post("/api/employees", headers=headers(h), json={"full_name": "Second", "employee_no": number})
    assert (duplicate.status_code, duplicate.json()) == (409, {"detail": "Employee number already exists in this factory"})
    denied = client.post("/api/employees", headers=headers(h, "denied"), json={"full_name": "Denied"})
    assert (denied.status_code, denied.json()) == (403, {"detail": "Missing permission. Need any of: ['hr.employees', 'payroll.manage', '*']"})
    assert counts(h) == before


def test_cross_factory_user_refused_before_salary_validation(h):
    before = counts(h)
    result = h[2].post("/api/employees", headers=headers(h), json={
        "full_name": "Wrong factory", "user_id": h[1]["eco"], "salary": "-1",
    })
    assert (result.status_code, result.json()) == (409, {"detail": "Employee user belongs to another factory"})
    assert counts(h) == before
