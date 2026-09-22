from uuid import uuid4

import pytest

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import AuditLog, Employee, Role, User


PROFILE_FIELDS = {
    "photo_url": "/storage/profile.jpg",
    "date_of_birth": "1990-01-02",
    "gender": "female",
    "email": "employee@example.com",
    "address": "Tashkent",
    "emergency_contact": "+998900000000",
    "nationality": "Uzbekistan",
    "company": "Milana",
    "branch": "Main",
    "section": "Sewing",
    "grade_level": "Senior",
    "employment_type": "full_time",
    "probation_end": "2026-12-31",
    "work_schedule": "Mon-Fri",
    "shift": "day",
    "workplace": "Line 1",
    "scheduled_daily_hours": 8,
    "rate_type": "monthly",
    "bonus_scheme": "standard",
    "bank_details": "test account",
    "payroll_id": "PAY-123",
}


def _employee_counts() -> tuple[int, int]:
    with SessionLocal() as db:
        return (
            db.query(Employee).count(),
            db.query(AuditLog).filter(AuditLog.entity_type == "Employee").count(),
        )


def _unprivileged_headers() -> dict[str, str]:
    marker = uuid4().hex
    with SessionLocal.begin() as db:
        role = Role(name=f"No HR profile access {marker}", permissions=[])
        db.add(role)
        db.flush()
        user = User(
            name="No HR profile access",
            email=f"no-hr-profile-{marker}@example.invalid",
            password_hash="unused",
            role_id=role.id,
            factory_code="MIL",
        )
        db.add(user)
        db.flush()
        user_id = user.id
    return {"Authorization": f"Bearer {create_access_token(user_id, {'factory_code': 'MIL'})}"}


def test_employee_profile_accepts_complete_established_shape(client, auth_headers):
    response = client.post(
        "/api/employees",
        headers=auth_headers,
        json={
            "employee_no": "81234001",
            "full_name": "Structured HR Profile",
            "hr_profile_json": PROFILE_FIELDS,
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["hr_profile_json"] == PROFILE_FIELDS


@pytest.mark.parametrize(
    "profile",
    [
        {"unsupported_profile_key": "value"},
        {"nationality": {"nested": "value"}},
        {"scheduled_daily_hours": [8]},
    ],
)
def test_employee_profile_rejects_malformed_shape_without_side_effects(
    client, auth_headers, profile,
):
    before = _employee_counts()

    response = client.post(
        "/api/employees",
        headers=auth_headers,
        json={
            "employee_no": "81234002",
            "full_name": "Malformed HR Profile",
            "hr_profile_json": profile,
        },
    )

    assert response.status_code == 422, response.text
    assert _employee_counts() == before


def test_employee_profile_update_rejects_malformed_shape_without_mutation(
    client, auth_headers,
):
    created = client.post(
        "/api/employees",
        headers=auth_headers,
        json={
            "employee_no": "81234006",
            "full_name": "Profile Before Invalid Update",
            "hr_profile_json": {"nationality": "Uzbekistan"},
        },
    )
    assert created.status_code == 201, created.text
    before = _employee_counts()

    response = client.patch(
        f"/api/employees/{created.json()['id']}",
        headers=auth_headers,
        json={
            "full_name": "Profile After Invalid Update",
            "hr_profile_json": {"email": ["not", "a", "string"]},
        },
    )

    assert response.status_code == 422, response.text
    assert _employee_counts() == before
    with SessionLocal() as db:
        saved = db.get(Employee, created.json()["id"])
        assert saved.full_name == "Profile Before Invalid Update"
        assert saved.hr_profile_json == {"nationality": "Uzbekistan"}


def test_employee_profile_validation_preserves_auth_not_found_and_conflict_precedence(
    client, auth_headers,
):
    invalid_profile = {"nationality": {"nested": "value"}}

    denied = client.post(
        "/api/employees",
        headers=_unprivileged_headers(),
        json={"full_name": "Denied HR Profile", "hr_profile_json": invalid_profile},
    )
    assert denied.status_code == 403, denied.text

    missing = client.patch(
        "/api/employees/2147483647",
        headers=auth_headers,
        json={"hr_profile_json": invalid_profile},
    )
    assert missing.status_code == 404, missing.text

    first = client.post(
        "/api/employees",
        headers=auth_headers,
        json={"employee_no": "81234003", "full_name": "Profile Conflict First"},
    )
    second = client.post(
        "/api/employees",
        headers=auth_headers,
        json={"employee_no": "81234004", "full_name": "Profile Conflict Second"},
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    before = _employee_counts()

    conflict = client.patch(
        f"/api/employees/{second.json()['id']}",
        headers=auth_headers,
        json={"employee_no": "81234003", "hr_profile_json": invalid_profile},
    )

    assert conflict.status_code == 409, conflict.text
    assert _employee_counts() == before
    with SessionLocal() as db:
        saved = db.get(Employee, second.json()["id"])
        assert saved.employee_no == "81234004"
        assert saved.hr_profile_json == {}


def test_employee_profile_legacy_shape_remains_readable_and_unrelated_edits_preserve_it(
    client, auth_headers,
):
    legacy_profile = {"legacy_extension": {"nested": [1, 2, 3]}}
    with SessionLocal.begin() as db:
        employee = Employee(
            factory_code="MIL",
            employee_no="81234005",
            full_name="Legacy HR Profile",
            status="active",
            hr_profile_json=legacy_profile,
        )
        db.add(employee)
        db.flush()
        employee_id = employee.id

    loaded = client.get(f"/api/employees/{employee_id}", headers=auth_headers)
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["hr_profile_json"] == legacy_profile

    edited = client.patch(
        f"/api/employees/{employee_id}",
        headers=auth_headers,
        json={"full_name": "Legacy HR Profile Renamed"},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["hr_profile_json"] == legacy_profile
