from copy import deepcopy
from uuid import uuid4

import pytest

from app.models import AuditLog, HrPosition
from app.tests.conftest import TestSessionLocal


def _position_payload(required_skills, *, name=None, approved_count=2):
    return {
        "org_unit_id": None,
        "department_id": None,
        "name": name or f"Skill Bounds {uuid4().hex[:10]}",
        "job_description": "Position for required-skill bounds tests",
        "required_skills": required_skills,
        "qualification_level": None,
        "grade_level": None,
        "salary_min": None,
        "salary_max": None,
        "approved_count": approved_count,
        "is_active": True,
    }


def _write_counts():
    with TestSessionLocal() as db:
        return {
            "positions": db.query(HrPosition).count(),
            "audit_rows": db.query(AuditLog).count(),
        }


@pytest.mark.parametrize(
    "skills",
    [
        [f"skill-{index}" for index in range(51)],
        ["x" * 161],
    ],
)
def test_create_rejects_oversized_required_skills_without_writes(client, auth_headers, skills):
    before = _write_counts()

    response = client.post(
        "/api/hr/positions",
        headers=auth_headers,
        json=_position_payload(skills),
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before


def test_create_and_patch_accept_required_skill_limits_at_boundary(client, auth_headers):
    boundary_skills = ["s" * 160 for _ in range(50)]

    created = client.post(
        "/api/hr/positions",
        headers=auth_headers,
        json=_position_payload(boundary_skills),
    )
    assert created.status_code == 201, created.text
    position_id = created.json()["id"]
    assert created.json()["required_skills"] == boundary_skills

    patched_skills = [f"{index:03d}" + "p" * 157 for index in range(50)]
    patched = client.patch(
        f"/api/hr/positions/{position_id}",
        headers=auth_headers,
        json=_position_payload(patched_skills, name=created.json()["name"]),
    )

    assert patched.status_code == 200, patched.text
    assert patched.json()["required_skills"] == patched_skills
    with TestSessionLocal() as db:
        assert db.get(HrPosition, position_id).required_skills_json == patched_skills


def test_patch_rejects_oversized_changed_required_skills_without_writes(client, auth_headers):
    created = client.post(
        "/api/hr/positions",
        headers=auth_headers,
        json=_position_payload(["machine safety"]),
    )
    assert created.status_code == 201, created.text
    position_id = created.json()["id"]
    before = _write_counts()
    with TestSessionLocal() as db:
        before_json = deepcopy(db.get(HrPosition, position_id).required_skills_json)

    response = client.patch(
        f"/api/hr/positions/{position_id}",
        headers=auth_headers,
        json=_position_payload(["changed"] * 51, name=created.json()["name"], approved_count=9),
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before
    with TestSessionLocal() as db:
        row = db.get(HrPosition, position_id)
        assert row.required_skills_json == before_json
        assert row.approved_count == 2


def test_patch_and_read_preserve_unchanged_oversized_legacy_skills(client, auth_headers):
    created = client.post(
        "/api/hr/positions",
        headers=auth_headers,
        json=_position_payload(["machine safety"]),
    )
    assert created.status_code == 201, created.text
    position_id = created.json()["id"]
    legacy_skills = [f"legacy-{index}" for index in range(50)] + ["L" * 161]
    with TestSessionLocal() as db:
        db.get(HrPosition, position_id).required_skills_json = deepcopy(legacy_skills)
        db.commit()

    patched = client.patch(
        f"/api/hr/positions/{position_id}",
        headers=auth_headers,
        json=_position_payload(legacy_skills, name=created.json()["name"] + " updated", approved_count=3),
    )

    assert patched.status_code == 200, patched.text
    assert patched.json()["required_skills"] == legacy_skills
    with TestSessionLocal() as db:
        assert db.get(HrPosition, position_id).required_skills_json == legacy_skills

    listed = client.get("/api/hr/positions", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert next(row for row in listed.json() if row["id"] == position_id)["required_skills"] == legacy_skills
