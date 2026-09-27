"""HR position reads fetch only fields serialized by the route."""
from uuid import uuid4

from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import HrPosition
from app.tests.conftest import test_engine


def test_hr_position_list_projects_serialized_columns(client, auth_headers):
    with SessionLocal() as db:
        position = HrPosition(
            factory_code="MIL",
            name=f"Projection test {uuid4().hex}",
            job_description="Detailed description",
            required_skills_json=["precision"],
            qualification_level="Senior",
            grade_level="G4",
            salary_min=1000,
            salary_max=2000,
            approved_count=3,
            is_active=True,
        )
        db.add(position)
        db.commit()
        position_id = position.id

    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and " from hr_positions " in normalized:
            statements.append(normalized)

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        response = client.get("/api/hr/positions", headers=auth_headers)
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    row = next(item for item in response.json() if item["id"] == position_id)
    assert row["required_skills"] == ["precision"]
    assert row["salary_min"] == 1000
    assert row["salary_max"] == 2000
    position_reads = [sql for sql in statements if " from hr_positions " in sql]
    assert len(position_reads) == 1
    selected_columns = position_reads[0].split(" from hr_positions ", maxsplit=1)[0]
    for omitted in ("factory_code", "created_at", "updated_at"):
        assert omitted not in selected_columns
