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
MAX_PROFILE_JSON_BYTES = 16 * 1024
MAX_PROFILE_JSON_DEPTH = 16
ADDRESS_JSON_OVERHEAD = len('{"address":""}'.encode("utf-8"))


def _nested_profile(depth: int) -> dict:
    value: object = "leaf"
    for _ in range(depth):
        value = {"legacy_extension": value}
    return value


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
        {"scheduled_daily_hours": "not-a-number"},
        {"scheduled_daily_hours": True},
        {"scheduled_daily_hours": 0},
        {"scheduled_daily_hours": 24.25},
        {"scheduled_daily_hours": float("inf")},
        {"scheduled_daily_hours": 10**400},
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


@pytest.mark.parametrize(
    "profile",
    [
        {"address": "x" * MAX_PROFILE_JSON_BYTES},
        _nested_profile(MAX_PROFILE_JSON_DEPTH + 1),
    ],
)
def test_employee_profile_rejects_oversized_or_deep_json_without_side_effects(
    client, auth_headers, profile,
):
    before = _employee_counts()

    response = client.post(
        "/api/employees",
        headers=auth_headers,
        json={
            "employee_no": "81234020",
            "full_name": "Bounded HR Profile",
            "hr_profile_json": profile,
        },
    )

    assert response.status_code == 422, response.text
    assert _employee_counts() == before


def test_employee_profile_accepts_exact_json_byte_limit(client, auth_headers):
    address = "x" * (MAX_PROFILE_JSON_BYTES - ADDRESS_JSON_OVERHEAD)
    response = client.post(
        "/api/employees",
        headers=auth_headers,
        json={"employee_no": "81234022", "full_name": "HR Profile Byte Boundary", "hr_profile_json": {"address": address}},
    )

    assert response.status_code == 201, response.text
    assert response.json()["hr_profile_json"]["address"] == address


def test_employee_profile_preserves_unchanged_oversized_legacy_json_on_patch(
    client, auth_headers,
):
    legacy_profile = {
        "legacy_extension": _nested_profile(MAX_PROFILE_JSON_DEPTH + 1),
        "padding": "x" * MAX_PROFILE_JSON_BYTES,
    }
    with SessionLocal.begin() as db:
        employee = Employee(
            factory_code="MIL",
            employee_no="81234021",
            full_name="Oversized Legacy Profile",
            status="active",
            hr_profile_json=legacy_profile,
        )
        db.add(employee)
        db.flush()
        employee_id = employee.id

    before = _employee_counts()
    rejected = client.patch(
        f"/api/employees/{employee_id}",
        headers=auth_headers,
        json={
            "hr_profile_json": {
                "legacy_extension": _nested_profile(MAX_PROFILE_JSON_DEPTH + 1),
                "padding": "x" * (MAX_PROFILE_JSON_BYTES + 1),
            },
        },
    )
    assert rejected.status_code == 422, rejected.text
    assert _employee_counts() == before

    preserved = client.patch(
        f"/api/employees/{employee_id}",
        headers=auth_headers,
        json={"full_name": "Oversized Legacy Profile Renamed", "hr_profile_json": legacy_profile},
    )
    assert preserved.status_code == 200, preserved.text
    assert preserved.json()["hr_profile_json"] == legacy_profile


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


def test_employee_profile_accepts_numeric_string_daily_hours(client, auth_headers):
    response = client.post(
        "/api/employees",
        headers=auth_headers,
        json={
            "employee_no": "81234007",
            "full_name": "Numeric Hours String",
            "hr_profile_json": {"scheduled_daily_hours": "7.5"},
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["hr_profile_json"]["scheduled_daily_hours"] == "7.5"


def test_employee_profile_update_rejects_changed_invalid_daily_hours_without_mutation(
    client,
    auth_headers,
):
    created = client.post(
        "/api/employees",
        headers=auth_headers,
        json={
            "employee_no": "81234008",
            "full_name": "Valid Hours Before Update",
            "hr_profile_json": {"scheduled_daily_hours": 8},
        },
    )
    assert created.status_code == 201, created.text
    before = _employee_counts()

    response = client.patch(
        f"/api/employees/{created.json()['id']}",
        headers=auth_headers,
        json={
            "full_name": "Must Not Persist",
            "hr_profile_json": {"scheduled_daily_hours": 25},
        },
    )

    assert response.status_code == 422, response.text
    assert _employee_counts() == before
    with SessionLocal() as db:
        saved = db.get(Employee, created.json()["id"])
        assert saved.full_name == "Valid Hours Before Update"
        assert saved.hr_profile_json == {"scheduled_daily_hours": 8}


def test_employee_profile_round_trip_preserves_unchanged_legacy_numeric_and_extension(
    client,
    auth_headers,
):
    legacy_profile = {
        "scheduled_daily_hours": "legacy-hours",
        "legacy_extension": {"nested": [1, "two"]},
    }
    with SessionLocal.begin() as db:
        employee = Employee(
            factory_code="MIL",
            employee_no="81234009",
            full_name="Legacy Numeric Profile",
            status="active",
            hr_profile_json=legacy_profile,
        )
        db.add(employee)
        db.flush()
        employee_id = employee.id

    loaded = client.get(f"/api/employees/{employee_id}", headers=auth_headers)
    assert loaded.status_code == 200, loaded.text
    profile = loaded.json()["hr_profile_json"]

    edited = client.patch(
        f"/api/employees/{employee_id}",
        headers=auth_headers,
        json={"full_name": "Legacy Numeric Profile Renamed", "hr_profile_json": profile},
    )

    assert edited.status_code == 200, edited.text
    assert edited.json()["hr_profile_json"] == legacy_profile
    with SessionLocal() as db:
        assert db.get(Employee, employee_id).hr_profile_json == legacy_profile

