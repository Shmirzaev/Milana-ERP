from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.hr_workspace import list_positions
from app.models import Department, Employee, HrPosition
from app.tests.conftest import TestSessionLocal, test_engine


def _factory_user(factory="MIL"):
    return SimpleNamespace(
        role=SimpleNamespace(name="", permissions=[]),
        factory_code=factory,
        session_factory_code=factory,
    )


def _seed_positions(count):
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        department = db.query(Department).filter(Department.code == "HR").first()
        assert department is not None
        positions = [
            HrPosition(
                factory_code="MIL",
                department_id=department.id,
                name=f"Bounded position {marker} {index:04d}",
                required_skills_json=[],
                approved_count=2,
                is_active=True,
            )
            for index in range(count)
        ]
        db.add_all(positions)
        db.flush()
        db.add_all([
            Employee(
                factory_code="MIL",
                employee_no=f"HP-{marker}-{index:04d}",
                full_name=f"Position employee {index}",
                department_id=department.id,
                hr_position_id=position.id,
                status="active",
            )
            for index, position in enumerate(positions)
        ])
        db.add(HrPosition(
            factory_code="ECO",
            name=f"Foreign position {marker}",
            required_skills_json=[],
            approved_count=99,
            is_active=True,
        ))
        db.commit()
        return [int(position.id) for position in positions]


def _read(**kwargs):
    with TestSessionLocal() as db:
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(test_engine, "before_cursor_execute", capture)
        try:
            payload = list_positions(db, _factory_user(), **kwargs)
        finally:
            event.remove(test_engine, "before_cursor_execute", capture)
        return payload, statements


@pytest.mark.parametrize("count", [1, 50, 401])
def test_position_pages_preserve_legacy_and_bound_enrichment(count):
    position_ids = _seed_positions(count)
    returned_count = min(count, 50)

    page, statements = _read(page=1, page_size=50)
    second_page, _ = _read(page=2, page_size=50)
    legacy, _ = _read()
    legacy_summary = {
        "plan": sum(row["approved_count"] for row in legacy),
        "actual": sum(row["occupied_count"] for row in legacy),
        "vacant": sum(row["vacant_count"] for row in legacy),
    }

    assert page["total"] == count
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is (count > 50)
    assert [row["id"] for row in page["rows"]] == position_ids[:returned_count]
    assert page["rows"] == legacy[:returned_count]
    assert page["summary"] == legacy_summary
    assert second_page["total"] == count
    assert second_page["rows"] == legacy[50:100]
    assert {row["id"] for row in page["rows"]}.isdisjoint({row["id"] for row in second_page["rows"]})
    assert all(row["occupied_count"] == 1 and row["vacant_count"] == 1 for row in page["rows"])
    assert len(statements) == 5, statements
    occupied_reads = [statement for statement in statements if "employees.hr_position_id in (" in statement]
    summary_reads = [statement for statement in statements if "left outer join (select employees.hr_position_id" in statement]
    department_reads = [statement for statement in statements if " from departments " in statement]
    assert len(occupied_reads) == len(department_reads) == 1
    assert len(summary_reads) == 1
    assert occupied_reads[0].count("?") == returned_count + 2
    assert department_reads[0].count("?") == 1


def test_position_page_http_contract_and_bound(client, auth_headers):
    [position_id] = _seed_positions(1)

    response = client.get("/api/hr/positions?page=1&page_size=500", headers=auth_headers)

    assert response.status_code == 200, response.text
    page = response.json()
    assert page["total"] == 1
    assert any(row["id"] == position_id for row in page["rows"])
    assert page["page"] == 1
    assert page["page_size"] == 500
    assert page["has_more"] is False
    assert set(page["summary"]) == {"plan", "actual", "vacant"}
    assert client.get("/api/hr/positions?page_size=501", headers=auth_headers).status_code == 422
