from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import event

from app.models import Employee
from app.tests.conftest import TestSessionLocal, test_engine


def _seed_analytics_employees() -> None:
    marker = uuid4().hex[:12]
    today = date.today()
    with TestSessionLocal() as db:
        db.add_all(
            [
                Employee(
                    factory_code="MIL",
                    employee_no=f"AN-{marker}-1",
                    full_name=f"Analytics active {marker}",
                    status="active",
                    salary=1250.50,
                    joined_at=datetime.combine(today - timedelta(days=730), datetime.min.time(), tzinfo=timezone.utc),
                    hr_profile_json={"gender": "female", "date_of_birth": "1990-01-01"},
                ),
                Employee(
                    factory_code="MIL",
                    employee_no=f"AN-{marker}-2",
                    full_name=f"Analytics malformed profile {marker}",
                    status="active",
                    salary=None,
                    joined_at=None,
                    hr_profile_json={"gender": "male", "date_of_birth": "not-a-date"},
                ),
                Employee(
                    factory_code="MIL",
                    employee_no=f"AN-{marker}-3",
                    full_name=f"Analytics inactive {marker}",
                    status="inactive",
                    salary=9999,
                    joined_at=datetime.combine(today - timedelta(days=365), datetime.min.time(), tzinfo=timezone.utc),
                    hr_profile_json={"gender": "other", "date_of_birth": "2000-01-01"},
                ),
            ]
        )
        db.commit()


def _reference_analytics(rows: list[Employee]) -> dict:
    active = [row for row in rows if row.status == "active"]
    salaries = [float(row.salary) for row in active if row.salary is not None]
    today = date.today()
    tenures = [max(0, (today - row.joined_at.date()).days) for row in active if row.joined_at]
    gender: dict[str, int] = {}
    ages = {"under_25": 0, "25_34": 0, "35_44": 0, "45_plus": 0}
    for row in active:
        profile = row.hr_profile_json or {}
        label = str(profile.get("gender") or "not_specified")
        gender[label] = gender.get(label, 0) + 1
        dob = profile.get("date_of_birth")
        if dob:
            try:
                age = (today - date.fromisoformat(str(dob))).days // 365
                bucket = "under_25" if age < 25 else "25_34" if age < 35 else "35_44" if age < 45 else "45_plus"
                ages[bucket] += 1
            except ValueError:
                pass
    return {
        "total_headcount": len(active),
        "inactive_headcount": len(rows) - len(active),
        "retention_rate": round(len(active) / len(rows) * 100, 1) if rows else 0,
        "average_tenure_years": round(sum(tenures) / len(tenures) / 365, 1) if tenures else 0,
        "average_salary": round(sum(salaries) / len(salaries), 2) if salaries else 0,
        "gender_distribution": gender,
        "age_distribution": ages,
    }


def test_hr_analytics_projects_consumed_columns_without_deferred_selects(client, auth_headers):
    _seed_analytics_employees()
    with TestSessionLocal() as db:
        expected = _reference_analytics(
            db.query(Employee).filter(Employee.factory_code == "MIL").all()
        )

    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        response = client.get("/api/hr/analytics", headers=auth_headers)
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    assert response.json() == expected
    employee_reads = [statement for statement in statements if " from employees " in statement]
    assert len(employee_reads) == 1, statements
    selected_columns = employee_reads[0].split(" from employees", 1)[0]
    for needed in ("employees.status", "employees.salary", "employees.joined_at", "employees.hr_profile_json"):
        assert needed in selected_columns
    for unrelated in (
        "employees.email",
        "employees.phone",
        "employees.full_name",
        "employees.employee_no",
        "employees.user_id",
        "employees.position",
    ):
        assert unrelated not in selected_columns
