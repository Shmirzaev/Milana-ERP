"""Employee CREATE boundary and HTTP contract checks."""

from typing import get_type_hints
from uuid import uuid4

from fastapi import FastAPI, HTTPException
import pytest
from sqlalchemy import event

from app.api.routes.hr import router
from app.libs.dto.people.employee_input import EmployeeCreateIn
from app.libs.dto.people.employee_output import EmployeeCreateOut
from app.libs.enums.people import EmployeeStatus
from app.models.people import employees_service as service
from app.schemas import AuditLog, Employee, User
from app.schemas.people.employee_persistence import insert_employee
from app.tests.conftest import TestSessionLocal


def _seed_actor() -> int:
    with TestSessionLocal() as db:
        actor = User(
            name="Employee create contract actor",
            email=f"employee-create-{uuid4().hex}@example.invalid",
            password_hash="unused",
            factory_code="MIL",
            extra_permissions=["hr.employees"],
        )
        db.add(actor)
        db.commit()
        return int(actor.id)


def test_create_contract_has_enum_status_and_exact_api_result_fields():
    assert EmployeeCreateIn.model_fields["status"].annotation is EmployeeStatus
    assert EmployeeCreateIn.model_fields["status"].default is EmployeeStatus.ACTIVE
    assert EmployeeCreateIn(full_name="Default status").status is EmployeeStatus.ACTIVE
    assert EmployeeCreateIn(full_name="Archived", status="archived").status is EmployeeStatus.ARCHIVED
    with pytest.raises(ValueError):
        EmployeeCreateIn(full_name="Invalid", status="suspended")

    assert EmployeeCreateOut.model_fields["status"].annotation is EmployeeStatus
    assert Employee.__table__.c.status.default.arg == EmployeeStatus.ACTIVE.value
    assert Employee.__table__.c.status.server_default is None
    assert set(EmployeeCreateOut.model_fields) == {
        "id", "factory_code", "employee_no", "user_id", "full_name", "department_id",
        "position", "status", "joined_at", "manager_employee_id", "hr_position_id",
        "phone", "salary", "hr_profile_json",
    }
    assert get_type_hints(service.create_employee)["payload"] is EmployeeCreateIn
    assert get_type_hints(service.create_employee)["return"] is EmployeeCreateOut
    assert get_type_hints(insert_employee)["status"] is EmployeeStatus


def test_create_openapi_documents_enum_without_changing_serialized_values():
    app = FastAPI()
    app.include_router(router, prefix="/api")
    schema = app.openapi()
    models = schema["components"]["schemas"]

    assert models["EmployeeStatus"]["enum"] == [
        "active", "inactive", "on_leave", "terminated", "archived",
    ]
    assert models["EmployeeCreateIn"]["properties"]["status"]["default"] == "active"
    assert models["EmployeeCreateIn"]["properties"]["status"]["$ref"].endswith("/EmployeeStatus")
    post = schema["paths"]["/api/employees"]["post"]
    assert post["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("/EmployeeCreateIn")
    assert post["responses"]["201"]["content"]["application/json"]["schema"]["$ref"].endswith("/EmployeeCreateOut")


def test_service_passes_same_session_and_canonical_fields_to_schema_writer(monkeypatch):
    actor_id = _seed_actor()
    original = service.insert_employee
    observed = []

    with TestSessionLocal() as db:
        actor = db.get(User, actor_id)
        actor.session_factory_code = "MIL"
        supplied_session = db

        def checked_insert(actual_db, **values):
            assert actual_db is supplied_session
            assert values["status"] is EmployeeStatus.ON_LEAVE
            assert values["employee_no"] == "2048"
            row = original(actual_db, **values)
            assert row.status == "on_leave"
            observed.append(row.id)
            return row

        monkeypatch.setattr(service, "insert_employee", checked_insert)
        result = service.create_employee(
            actor,
            db,
            EmployeeCreateIn(employee_no=" 2048 ", full_name="Typed worker", status=EmployeeStatus.ON_LEAVE),
        )

        assert isinstance(result, EmployeeCreateOut)
        assert result.status is EmployeeStatus.ON_LEAVE
        assert result.model_dump(mode="json")["status"] == "on_leave"
        assert observed == [result.id]
        assert db.query(AuditLog).filter_by(
            entity_type="Employee", entity_id=result.id, action="create"
        ).count() == 1


def test_service_refuses_missing_permission_before_payload_validation():
    with TestSessionLocal() as db:
        actor = User(
            name="Employee CREATE denied actor",
            email=f"employee-create-denied-{uuid4().hex}@example.invalid",
            password_hash="unused",
            factory_code="MIL",
            extra_permissions=["payroll.view"],
        )
        db.add(actor)
        db.commit()
        actor.session_factory_code = "MIL"
        with pytest.raises(HTTPException) as denied:
            service.create_employee(
                actor,
                db,
                EmployeeCreateIn(full_name="Denied", salary="10000000000"),
            )
        assert denied.value.status_code == 403
        assert "Missing permission" in denied.value.detail


def test_service_refuses_unassigned_factory_before_reference_validation():
    actor_id = _seed_actor()
    with TestSessionLocal() as db:
        actor = db.get(User, actor_id)
        actor.session_factory_code = "ECO"
        with pytest.raises(HTTPException) as denied:
            service.create_employee(
                actor,
                db,
                EmployeeCreateIn(full_name="Wrong factory", department_id=2_147_483_647),
            )
        assert denied.value.status_code == 403
        assert denied.value.detail == "This account is not assigned to the selected factory"


def test_create_preserves_reference_duplicate_and_salary_refusal_order():
    actor_id = _seed_actor()
    duplicate_number = f"7{uuid4().int % 10**12:012d}"
    with TestSessionLocal() as db:
        actor = db.get(User, actor_id)
        actor.session_factory_code = "MIL"
        db.add(Employee(factory_code="MIL", employee_no=duplicate_number, full_name="Existing"))
        db.commit()

    with TestSessionLocal() as db:
        actor = db.get(User, actor_id)
        actor.session_factory_code = "MIL"
        with pytest.raises(HTTPException) as missing_department:
            service.create_employee(
                actor,
                db,
                EmployeeCreateIn(
                    employee_no=duplicate_number,
                    full_name="Reference should win",
                    department_id=2_147_483_647,
                    salary="-1",
                    hr_profile_json={"unsupported": "also invalid"},
                ),
            )
        assert missing_department.value.status_code == 404
        assert missing_department.value.detail == "Employee department not found"
        db.rollback()

        with pytest.raises(HTTPException) as duplicate:
            service.create_employee(
                actor,
                db,
                EmployeeCreateIn(employee_no=duplicate_number, full_name="Duplicate wins", salary="-1"),
            )
        assert duplicate.value.status_code == 409
        assert duplicate.value.detail == "Employee number already exists in this factory"
        db.rollback()

        with pytest.raises(HTTPException) as salary:
            service.create_employee(
                actor,
                db,
                EmployeeCreateIn(
                    employee_no=f"8{uuid4().int % 10**12:012d}",
                    full_name="Salary before profile",
                    salary="-1",
                    hr_profile_json={"unsupported": "invalid"},
                ),
            )
        assert salary.value.status_code == 422
        assert salary.value.detail == "Employee salary must be nonnegative"
        db.rollback()


def test_create_reference_refusals_keep_user_department_manager_position_order():
    actor_id = _seed_actor()
    missing_id = 2_147_483_647
    cases = [
        (
            EmployeeCreateIn(
                full_name="Missing user before all other references",
                user_id=missing_id,
                department_id=missing_id,
                manager_employee_id=missing_id,
                hr_position_id=missing_id,
            ),
            404,
            "Employee user not found",
        ),
        (
            EmployeeCreateIn(
                full_name="Missing department before later references",
                department_id=missing_id,
                manager_employee_id=missing_id,
                hr_position_id=missing_id,
            ),
            404,
            "Employee department not found",
        ),
        (
            EmployeeCreateIn(
                full_name="Missing manager before position",
                manager_employee_id=missing_id,
                hr_position_id=missing_id,
            ),
            404,
            "Employee manager not found in this factory",
        ),
        (
            EmployeeCreateIn(full_name="Missing HR position", hr_position_id=missing_id),
            404,
            "HR position not found in this factory",
        ),
    ]

    for payload, expected_status, expected_detail in cases:
        with TestSessionLocal() as db:
            actor = db.get(User, actor_id)
            actor.session_factory_code = "MIL"
            with pytest.raises(HTTPException) as refused:
                service.create_employee(actor, db, payload)
            assert refused.value.status_code == expected_status
            assert refused.value.detail == expected_detail


def test_create_refuses_foreign_factory_user_reference():
    actor_id = _seed_actor()
    with TestSessionLocal() as db:
        foreign = User(
            name="ECO employee user",
            email=f"employee-create-eco-{uuid4().hex}@example.invalid",
            password_hash="unused",
            factory_code="ECO",
        )
        db.add(foreign)
        db.commit()
        foreign_id = foreign.id

    with TestSessionLocal() as db:
        actor = db.get(User, actor_id)
        actor.session_factory_code = "MIL"
        with pytest.raises(HTTPException) as refused:
            service.create_employee(
                actor,
                db,
                EmployeeCreateIn(full_name="Wrong factory user", user_id=foreign_id),
            )
        assert refused.value.status_code == 409
        assert refused.value.detail == "Employee user belongs to another factory"


def test_create_keeps_existing_same_factory_archived_manager_eligible():
    actor_id = _seed_actor()
    with TestSessionLocal() as db:
        actor = db.get(User, actor_id)
        actor.session_factory_code = "MIL"
        manager = Employee(factory_code="MIL", full_name="Archived manager", status="archived")
        db.add(manager)
        db.flush()
        result = service.create_employee(
            actor,
            db,
            EmployeeCreateIn(
                employee_no=f"6{uuid4().int % 10**12:012d}",
                full_name="Worker with historical manager",
                manager_employee_id=manager.id,
            ),
        )
        assert result.manager_employee_id == manager.id


def test_schema_writer_flushes_on_supplied_session_without_committing():
    employee_id = None
    commits = []
    with TestSessionLocal() as db:
        event.listen(db, "after_commit", lambda _: commits.append(True))
        row = insert_employee(
            db,
            factory_code="MIL",
            user_id=None,
            employee_no=f"9{uuid4().int % 10**12:012d}",
            full_name="Rollback-only schema row",
            department_id=None,
            position=None,
            phone=None,
            salary=None,
            status=EmployeeStatus.ACTIVE,
            joined_at=None,
            manager_employee_id=None,
            hr_position_id=None,
            hr_profile_json={},
        )
        employee_id = row.id
        assert employee_id is not None
        assert db.get(Employee, employee_id) is row
        assert commits == []
        db.rollback()

    with TestSessionLocal() as db:
        assert db.get(Employee, employee_id) is None


def test_http_create_keeps_public_scalar_response_and_private_fields(client, auth_headers):
    response = client.post(
        "/api/employees",
        headers=auth_headers,
        json={"employee_no": " 2049 ", "full_name": "HTTP typed worker", "salary": "1250.25"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["employee_no"] == "2049"
    assert body["status"] == "active"
    assert body["salary"] == 1250.25
    assert body["hr_profile_json"] == {}
    assert set(body) == set(EmployeeCreateOut.model_fields)

    with TestSessionLocal() as db:
        row = db.get(Employee, body["id"])
        assert row.factory_code == body["factory_code"] == "MIL"
        assert row.status == "active"
        assert row.salary == 1250.25
        assert db.query(AuditLog).filter_by(
            entity_type="Employee", entity_id=row.id, action="create"
        ).count() == 1
