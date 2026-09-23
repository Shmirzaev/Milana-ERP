from uuid import uuid4

from sqlalchemy import event

from app.tests.conftest import test_engine


def test_recruitment_list_projects_legacy_response_fields(client, auth_headers):
    marker = uuid4().hex[:8]
    created = client.post(
        "/api/hr/recruitment",
        headers=auth_headers,
        json={
            "full_name": f"PERF35 Candidate {marker}",
            "first_name": "Perf",
            "last_name": marker,
            "pinfl": str(uuid4().int % 10**14).zfill(14),
            "passport_number": f"PC{marker}",
            "stage": "screening",
            "notes": "Keep exact legacy notes field",
        },
    )
    assert created.status_code == 201, created.text

    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and " from hr_recruitment_candidates " in normalized:
            statements.append(normalized)

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        response = client.get(
            f"/api/hr/recruitment?q={marker}",
            headers=auth_headers,
        )
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    row = next(item for item in response.json() if item["id"] == created.json()["id"])
    assert set(row) == {
        "id", "position_id", "department_id", "full_name", "first_name", "last_name", "middle_name",
        "date_of_birth", "gender", "nationality", "country", "region", "district", "address",
        "passport_number", "passport_issued_by", "passport_issue_date", "passport_expiry_date", "pinfl",
        "phone", "email", "source", "stage", "applied_on", "interview_at", "notes",
    }
    assert row["notes"] == "Keep exact legacy notes field"
    assert len(statements) == 1
    selected_columns = statements[0].split(" from hr_recruitment_candidates", 1)[0]
    for omitted in (
        "hr_recruitment_candidates.factory_code",
        "hr_recruitment_candidates.created_at",
        "hr_recruitment_candidates.updated_at",
    ):
        assert omitted not in selected_columns
