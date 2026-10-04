from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import AuditLog, Employee, Role, User


MAX_EMPLOYEE_SALARY = Decimal("9999999999.99")


def _employee_counts() -> tuple[int, int]:
    with SessionLocal() as db:
        return (
            db.query(Employee).count(),
            db.query(AuditLog).filter(AuditLog.entity_type == "Employee").count(),
        )


def _unprivileged_headers() -> dict[str, str]:
    marker = uuid4().hex
    with SessionLocal.begin() as db:
        role = Role(name=f"No employee salary access {marker}", permissions=[])
        db.add(role)
        db.flush()
        user = User(
            name="No employee salary access",
            email=f"no-employee-salary-{marker}@example.invalid",
            password_hash="unused",
            role_id=role.id,
            factory_code="MIL",
        )
        db.add(user)
        db.flush()
        user_id = user.id
    token = create_access_token(user_id, {"factory_code": "MIL"})
    return {"Authorization": f"Bearer {token}"}


def test_employee_salary_accepts_exact_numeric_boundary(client, auth_headers):
    response = client.post(
        "/api/employees",
        headers=auth_headers,
        json={"full_name": "Maximum salary employee", "salary": str(MAX_EMPLOYEE_SALARY)},
    )

    assert response.status_code == 201, response.text
    assert Decimal(str(response.json()["salary"])) == MAX_EMPLOYEE_SALARY
    with SessionLocal() as db:
        saved = db.get(Employee, response.json()["id"])
        assert saved.salary == MAX_EMPLOYEE_SALARY


def test_employee_salary_accepts_trailing_zero_precision(client, auth_headers):
    response = client.post(
        "/api/employees",
        headers=auth_headers,
        json={"full_name": "Trailing zero salary", "salary": "1250.2500"},
    )

    assert response.status_code == 201, response.text
    with SessionLocal() as db:
        saved = db.get(Employee, response.json()["id"])
        assert saved.salary == Decimal("1250.25")


@pytest.mark.parametrize("salary", ["-0.01", "-0.000001", "NaN", "Infinity", "-Infinity", "10000000000"])
def test_employee_create_rejects_unstorable_salary_without_side_effects(
    client, auth_headers, salary,
):
    before = _employee_counts()

    response = client.post(
        "/api/employees",
        headers=auth_headers,
        json={"full_name": "Invalid salary employee", "salary": salary},
    )

    assert response.status_code == 422, response.text
    assert _employee_counts() == before


def test_employee_patch_rejects_unstorable_salary_without_mutation(client, auth_headers):
    created = client.post(
        "/api/employees",
        headers=auth_headers,
        json={"full_name": "Salary before invalid patch", "salary": "1250.25"},
    )
    assert created.status_code == 201, created.text
    employee_id = created.json()["id"]
    before = _employee_counts()

    response = client.patch(
        f"/api/employees/{employee_id}",
        headers=auth_headers,
        json={"full_name": "Salary after invalid patch", "salary": "10000000000"},
    )

    assert response.status_code == 422, response.text
    assert _employee_counts() == before
    with SessionLocal() as db:
        saved = db.get(Employee, employee_id)
        assert saved.full_name == "Salary before invalid patch"
        assert saved.salary == Decimal("1250.25")


@pytest.mark.parametrize("salary, expected", [
    ("1250.25555", "1250.2556"),
    ("1250.25554", "1250.2555"),
    ("0.00005", "0.0001"),
    ("0.00004", "0.0000"),
    ("9999999999.98994", "9999999999.9899"),
    ("9999999999.98996", "9999999999.9900"),
])
def test_employee_salary_rounds_to_four_decimals_on_create_and_patch(client, auth_headers, salary, expected):
    created = client.post("/api/employees", headers=auth_headers,
                          json={"full_name": "Rounded salary", "salary": salary})
    assert created.status_code == 201, created.text
    employee_id = created.json()["id"]
    with SessionLocal() as db:
        assert db.get(Employee, employee_id).salary == Decimal(expected)
    assert Decimal(str(created.json()["salary"])) == Decimal(expected)

    updated = client.patch(f"/api/employees/{employee_id}", headers=auth_headers,
                           json={"salary": salary})
    assert updated.status_code == 200, updated.text
    with SessionLocal() as db:
        assert db.get(Employee, employee_id).salary == Decimal(expected)
    assert Decimal(str(updated.json()["salary"])) == Decimal(expected)


def test_employee_salary_null_and_omitted_patch_remain_supported(client, auth_headers):
    created = client.post("/api/employees", headers=auth_headers,
                          json={"full_name": "Partial salary", "salary": "12.3456"})
    assert created.status_code == 201, created.text
    employee_id = created.json()["id"]
    updated = client.patch(f"/api/employees/{employee_id}", headers=auth_headers,
                           json={"position": "Unrelated edit"})
    assert updated.status_code == 200, updated.text
    with SessionLocal() as db:
        assert db.get(Employee, employee_id).salary == Decimal("12.3456")
    cleared = client.patch(f"/api/employees/{employee_id}", headers=auth_headers, json={"salary": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["salary"] is None
    with SessionLocal() as db:
        assert db.get(Employee, employee_id).salary is None


def test_employee_salary_validation_preserves_auth_and_not_found_precedence(
    client, auth_headers,
):
    denied = client.post(
        "/api/employees",
        headers=_unprivileged_headers(),
        json={"full_name": "Denied salary", "salary": "10000000000"},
    )
    assert denied.status_code == 403, denied.text

    missing = client.patch(
        "/api/employees/2147483647",
        headers=auth_headers,
        json={"salary": "10000000000"},
    )
    assert missing.status_code == 404, missing.text



@pytest.mark.parametrize("salary", ["Infinity", "-Infinity", "NaN"])
def test_employee_salary_rejects_nonfinite_raw_json(client, auth_headers, salary):
    before = _employee_counts()
    response = client.post("/api/employees", headers={**auth_headers, "Content-Type": "application/json"},
                           content=f'{{"full_name":"Nonfinite salary","salary":{salary}}}')
    assert response.status_code == 422, response.text
    assert _employee_counts() == before
