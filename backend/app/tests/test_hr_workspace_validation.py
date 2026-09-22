from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.core.config import settings
from app.models import Department, HrOrgUnit, HrPosition


def _department_id(code: str) -> int:
    with SessionLocal() as db:
        return db.query(Department.id).filter(Department.code == code).scalar()


def _cross_factory_refs() -> tuple[int, int]:
    with SessionLocal() as db:
        department_id = db.query(Department.id).filter(Department.code == "ECT").scalar()
        unit = HrOrgUnit(
            factory_code="ECO",
            unit_type="section",
            name=f"Cross-factory HR unit {uuid4().hex}",
        )
        db.add(unit)
        db.commit()
        return department_id, unit.id


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/hr/organization", {"unit_type": "section", "name": "Scoped unit"}),
        ("/api/hr/positions", {"name": "Scoped position", "approved_count": 1}),
        ("/api/hr/recruitment", {"full_name": "Scoped candidate"}),
    ],
)
def test_hr_workspace_rejects_cross_factory_department(client, auth_headers, path, payload):
    department_id, _ = _cross_factory_refs()

    response = client.post(path, headers=auth_headers, json={**payload, "department_id": department_id})

    assert response.status_code == 409, response.text


def test_position_rejects_cross_factory_org_unit(client, auth_headers):
    _, org_unit_id = _cross_factory_refs()

    response = client.post(
        "/api/hr/positions",
        headers=auth_headers,
        json={"org_unit_id": org_unit_id, "name": "Wrong factory position"},
    )

    assert response.status_code == 404, response.text


def test_position_update_rejects_inverted_salary_range_without_mutation(client, auth_headers):
    created = client.post(
        "/api/hr/positions",
        headers=auth_headers,
        json={"name": "Salary range position", "salary_min": 100, "salary_max": 200},
    )
    assert created.status_code == 201, created.text
    position_id = created.json()["id"]

    response = client.patch(
        f"/api/hr/positions/{position_id}",
        headers=auth_headers,
        json={"name": "Salary range position", "salary_min": 300, "salary_max": 200},
    )

    assert response.status_code == 422, response.text
    with SessionLocal() as db:
        position = db.get(HrPosition, position_id)
        assert float(position.salary_min) == 100
        assert float(position.salary_max) == 200


def test_candidate_rejects_passport_expiry_before_issue(client, auth_headers):
    response = client.post(
        "/api/hr/recruitment",
        headers=auth_headers,
        json={
            "full_name": "Invalid passport range",
            "passport_issue_date": "2026-09-20",
            "passport_expiry_date": "2026-09-19",
        },
    )

    assert response.status_code == 422, response.text


def test_calendar_rejects_end_before_start(client, auth_headers):
    starts_at = datetime.now(timezone.utc)

    response = client.post(
        "/api/hr/calendar",
        headers=auth_headers,
        json={
            "event_type": "training",
            "title": "Invalid calendar range",
            "starts_at": starts_at.isoformat(),
            "ends_at": (starts_at - timedelta(minutes=1)).isoformat(),
        },
    )

    assert response.status_code == 422, response.text


def test_calendar_rejects_mixed_timezone_formats(client, auth_headers):
    response = client.post(
        "/api/hr/calendar",
        headers=auth_headers,
        json={
            "event_type": "training",
            "title": "Mixed timezone range",
            "starts_at": "2026-09-20T09:00:00Z",
            "ends_at": "2026-09-20T10:00:00",
        },
    )

    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/hr/organization", {"parent_id": 0, "unit_type": "section", "name": "Missing parent"}),
        ("/api/hr/organization", {"department_id": 0, "unit_type": "section", "name": "Missing department"}),
        ("/api/hr/organization", {"manager_employee_id": 0, "unit_type": "section", "name": "Missing manager"}),
        ("/api/hr/positions", {"org_unit_id": 0, "name": "Missing organization"}),
        ("/api/hr/positions", {"department_id": 0, "name": "Missing department"}),
        ("/api/hr/recruitment", {"position_id": 0, "full_name": "Missing position"}),
        ("/api/hr/recruitment", {"department_id": 0, "full_name": "Missing department"}),
        (
            "/api/hr/calendar",
            {"employee_id": 0, "event_type": "training", "title": "Missing employee", "starts_at": "2026-09-20T09:00:00Z"},
        ),
    ],
)
def test_hr_workspace_rejects_zero_references(client, auth_headers, path, payload):
    response = client.post(path, headers=auth_headers, json=payload)

    assert response.status_code == 422, response.text


@pytest.mark.parametrize("reference_id", [2_147_483_648, 10**100])
def test_hr_workspace_rejects_references_outside_postgres_int4(client, auth_headers, reference_id):
    response = client.post(
        "/api/hr/recruitment",
        headers=auth_headers,
        json={"position_id": reference_id, "full_name": "Invalid reference bound"},
    )

    assert response.status_code == 422, response.text


def test_hr_workspace_keeps_positive_missing_reference_as_not_found(client, auth_headers):
    response = client.post(
        "/api/hr/recruitment",
        headers=auth_headers,
        json={"position_id": 2_147_483_647, "full_name": "Missing position"},
    )

    assert response.status_code == 404, response.text


@pytest.mark.parametrize(
    "salary",
    ["Infinity", "NaN", "1e309", "1000000000000", "999999999999.9999"],
)
def test_position_rejects_nonfinite_or_unstorable_salary_json(client, auth_headers, salary):
    response = client.post(
        "/api/hr/positions",
        headers={**auth_headers, "Content-Type": "application/json"},
        content=f'{{"name":"Invalid salary","salary_min":{salary}}}',
    )

    assert response.status_code == 422, response.text


def test_position_accepts_numeric_database_salary_boundary(client, auth_headers):
    response = client.post(
        "/api/hr/positions",
        headers=auth_headers,
        json={
            "name": "Maximum salary boundary",
            "salary_min": 999_999_999_999.99,
            "salary_max": 999_999_999_999.99,
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["salary_min"] == 999_999_999_999.99
    assert response.json()["salary_max"] == 999_999_999_999.99


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/hr/organization", {"unit_type": "section", "name": "   "}),
        ("/api/hr/positions", {"name": "   "}),
        ("/api/hr/recruitment", {"full_name": "   "}),
        (
            "/api/hr/calendar",
            {"event_type": "training", "title": "   ", "starts_at": "2026-09-20T09:00:00Z"},
        ),
    ],
)
def test_hr_workspace_rejects_whitespace_only_required_values(client, auth_headers, path, payload):
    response = client.post(path, headers=auth_headers, json=payload)

    assert response.status_code == 422, response.text


def test_document_rejects_whitespace_title_before_file_write(client, auth_headers, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "HR_DOCUMENTS_DIR", str(tmp_path))
    employee = client.post(
        "/api/employees",
        headers=auth_headers,
        json={"employee_no": "880001", "full_name": "Document validation employee"},
    )
    assert employee.status_code == 201, employee.text

    response = client.post(
        "/api/hr/documents",
        headers=auth_headers,
        data={"employee_id": employee.json()["id"], "category": "other", "title": "   "},
        files={"file": ("document.txt", b"synthetic", "text/plain")},
    )

    assert response.status_code == 422, response.text
    assert list(tmp_path.iterdir()) == []


def test_document_rejects_oversized_title_before_file_write(client, auth_headers, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "HR_DOCUMENTS_DIR", str(tmp_path))
    employee = client.post(
        "/api/employees",
        headers=auth_headers,
        json={"employee_no": "880002", "full_name": "Document title bound employee"},
    )
    assert employee.status_code == 201, employee.text

    response = client.post(
        "/api/hr/documents",
        headers=auth_headers,
        data={"employee_id": employee.json()["id"], "category": "other", "title": "x" * 256},
        files={"file": ("document.txt", b"synthetic", "text/plain")},
    )

    assert response.status_code == 422, response.text
    assert list(tmp_path.iterdir()) == []


def test_same_factory_cross_department_tree_remains_allowed(client, auth_headers):
    cutting_id = _department_id("CUT")
    sewing_id = _department_id("MIL")
    parent = client.post(
        "/api/hr/organization",
        headers=auth_headers,
        json={"department_id": cutting_id, "unit_type": "department", "name": "Cross-department parent"},
    )
    assert parent.status_code == 201, parent.text

    child = client.post(
        "/api/hr/organization",
        headers=auth_headers,
        json={
            "parent_id": parent.json()["id"],
            "department_id": sewing_id,
            "unit_type": "section",
            "name": "Cross-department child",
        },
    )
    position = client.post(
        "/api/hr/positions",
        headers=auth_headers,
        json={
            "org_unit_id": parent.json()["id"],
            "department_id": sewing_id,
            "name": "Cross-department position",
        },
    )

    assert child.status_code == 201, child.text
    assert position.status_code == 201, position.text


def test_valid_scoped_hr_workflow_remains_supported(client, auth_headers):
    department_id = _department_id("MIL")
    marker = uuid4().hex
    organization = client.post(
        "/api/hr/organization",
        headers=auth_headers,
        json={
            "department_id": department_id,
            "unit_type": "section",
            "name": f"Valid HR unit {marker}",
        },
    )
    assert organization.status_code == 201, organization.text

    position = client.post(
        "/api/hr/positions",
        headers=auth_headers,
        json={
            "org_unit_id": organization.json()["id"],
            "department_id": department_id,
            "name": f"Valid HR position {marker}",
            "salary_min": 100,
            "salary_max": 200,
        },
    )
    assert position.status_code == 201, position.text

    listed = client.get("/api/hr/positions", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    listed_position = next(row for row in listed.json() if row["id"] == position.json()["id"])
    assert listed_position["department_name"] == "Milana Sewing Factory"

    cleared = client.patch(
        f"/api/hr/positions/{position.json()['id']}",
        headers=auth_headers,
        json={
            "org_unit_id": None,
            "department_id": None,
            "name": f"Valid HR position {marker}",
            "salary_min": 100,
            "salary_max": 200,
        },
    )
    assert cleared.status_code == 200, cleared.text

    candidate = client.post(
        "/api/hr/recruitment",
        headers=auth_headers,
        json={
            "position_id": position.json()["id"],
            "department_id": department_id,
            "full_name": "  Valid Candidate  ",
            "passport_issue_date": "2026-09-19",
            "passport_expiry_date": "2027-09-19",
        },
    )
    assert candidate.status_code == 201, candidate.text

    cleared_candidate = client.patch(
        f"/api/hr/recruitment/{candidate.json()['id']}",
        headers=auth_headers,
        json={
            "position_id": None,
            "department_id": None,
            "full_name": "Valid Candidate",
            "passport_issue_date": "2026-09-19",
            "passport_expiry_date": "2027-09-19",
        },
    )
    assert cleared_candidate.status_code == 200, cleared_candidate.text

    event = client.post(
        "/api/hr/calendar",
        headers=auth_headers,
        json={
            "event_type": "interview",
            "title": "  Valid interview  ",
            "starts_at": "2026-09-20T09:00:00Z",
            "ends_at": "2026-09-20T10:00:00Z",
        },
    )
    assert event.status_code == 201, event.text
