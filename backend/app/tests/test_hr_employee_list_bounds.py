from app.models import Employee
from app.tests.conftest import TestSessionLocal


def test_employee_list_has_bounded_default_and_explicit_limit(client, auth_headers):
    db = TestSessionLocal()
    try:
        rows = [
            Employee(factory_code="MIL", full_name=f"Bounded employee {idx}", status="active")
            for idx in range(501)
        ]
        db.add_all(rows)
        db.commit()
        newest_id = max(row.id for row in rows)
    finally:
        db.close()

    default = client.get("/api/employees", headers=auth_headers)
    assert default.status_code == 200, default.text
    assert len(default.json()) == 500
    assert default.json()[0]["id"] == newest_id

    explicit = client.get("/api/employees?limit=1", headers=auth_headers)
    assert explicit.status_code == 200, explicit.text
    assert len(explicit.json()) == 1
    assert explicit.json()[0]["id"] == newest_id

    rejected = client.get("/api/employees?limit=501", headers=auth_headers)
    assert rejected.status_code == 422, rejected.text
