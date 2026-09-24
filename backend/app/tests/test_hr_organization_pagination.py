from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event, func

from app.api.routes.hr_workspace import list_organization
from app.models import Employee, HrOrgUnit, HrPosition
from app.tests.conftest import TestSessionLocal, test_engine


def _factory_user(factory="MIL"):
    return SimpleNamespace(
        role=SimpleNamespace(name="", permissions=[]),
        factory_code=factory,
        session_factory_code=factory,
    )


def _seed_directory(count):
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        active_before = db.query(func.count(Employee.id)).filter(
            Employee.factory_code == "MIL", Employee.status == "active",
        ).scalar() or 0
        vacant_before = db.query(func.count(Employee.id)).filter(
            Employee.factory_code == "MIL", Employee.status == "active", Employee.hr_position_id.is_(None),
        ).scalar() or 0
        managers_before = db.query(func.count(HrOrgUnit.id)).filter(
            HrOrgUnit.factory_code == "MIL", HrOrgUnit.manager_employee_id.is_not(None),
        ).scalar() or 0
        position = HrPosition(
            factory_code="MIL",
            name=f"Org position {marker}",
            required_skills_json=[],
            approved_count=1,
            is_active=True,
        )
        db.add(position)
        db.flush()
        employees = [
            Employee(
                factory_code="MIL",
                employee_no=f"ORG-{marker}-{index:04d}",
                full_name=f"Org employee {marker} {index:04d}",
                status="active" if index % 2 == 0 else "fired",
                hr_position_id=None if index % 4 == 0 else position.id,
            )
            for index in range(count)
        ]
        units = [
            HrOrgUnit(
                factory_code="MIL",
                parent_id=None if index == 0 else None,
                manager_employee_id=None,
                unit_type="section",
                name=f"Org unit {marker} {index:04d}",
                code=f"{marker}-{index:04d}",
                sort_order=index,
            )
            for index in range(count)
        ]
        db.add_all(employees)
        db.add_all(units)
        db.flush()
        units[0].manager_employee_id = employees[-1].id
        if count > 1:
            units[1].parent_id = units[0].id
        db.add(Employee(
            factory_code="ECO",
            employee_no=f"ORG-{marker}-FOREIGN",
            full_name=f"Foreign employee {marker}",
            status="active",
        ))
        db.add(HrOrgUnit(
            factory_code="ECO",
            unit_type="section",
            name=f"Org unit {marker} foreign",
        ))
        db.commit()
        expected = {
            "active_employee_total": int(active_before) + (count + 1) // 2,
            "vacant_employee_total": int(vacant_before) + (count + 3) // 4,
            "manager_unit_total": int(managers_before) + 1,
        }
        return marker, [int(row.id) for row in units], [int(row.id) for row in employees], expected


def _read(**kwargs):
    with TestSessionLocal() as db:
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(test_engine, "before_cursor_execute", capture)
        try:
            result = list_organization(db, _factory_user(), **kwargs)
        finally:
            event.remove(test_engine, "before_cursor_execute", capture)
        return result, statements


@pytest.mark.parametrize("count", [1, 50, 401])
def test_organization_page_has_exact_factory_scoped_totals_and_bounded_rows(count):
    marker, unit_ids, employee_ids, expected = _seed_directory(count)

    result, statements = _read(page=1, page_size=50, search=marker)

    assert result["unit_total"] == count
    assert result["employee_total"] == count
    assert len(result["units"]) == min(50, count)
    assert len(result["employees"]) == min(50, count)
    assert result["units_have_more"] is (count > 50)
    assert result["employees_have_more"] is (count > 50)
    assert result["active_employee_total"] == expected["active_employee_total"]
    assert result["vacant_employee_total"] == expected["vacant_employee_total"]
    assert result["manager_unit_total"] == expected["manager_unit_total"]
    assert {row["id"] for row in result["units"]} == set(unit_ids[:50])
    assert {row["id"] for row in result["employees"]} == set(employee_ids[:50])
    assert all("factory_code" not in row for row in result["units"])
    assert all("factory_code" not in row for row in result["employees"])
    assert len(statements) <= 8, statements
    bounded_directory_reads = [
        statement for statement in statements
        if " from hr_org_units " in statement or " from employees " in statement
    ]
    assert len(bounded_directory_reads) >= 2
    assert all(" limit " in statement for statement in bounded_directory_reads if " order by " in statement and " count(" not in statement), statements

    first_unit = next(row for row in result["units"] if row["id"] == unit_ids[0])
    assert first_unit["manager_employee_id"] == employee_ids[-1]
    assert first_unit["manager_name"] == f"Org employee {marker} {count - 1:04d}"
    if count > 1:
        child = next(row for row in result["units"] if row["id"] == unit_ids[1])
        assert child["parent_id"] == unit_ids[0]
        assert child["parent_name"] == result["units"][0]["name"]


def test_organization_pagination_and_search_cover_later_rows_and_escape_wildcards():
    marker, unit_ids, employee_ids, _expected = _seed_directory(401)
    first, _ = _read(page=1, page_size=50, search=marker)
    second, _ = _read(page=2, page_size=50, search=marker)
    employee_search, _ = _read(page=1, page_size=50, search=f"Org employee {marker} 0400")
    wildcard_search, _ = _read(page=1, page_size=50, search="%")

    assert first["units_have_more"] and first["employees_have_more"]
    assert second["unit_total"] == second["employee_total"] == 401
    assert {row["id"] for row in second["units"]}.isdisjoint({row["id"] for row in first["units"]})
    assert {row["id"] for row in second["employees"]}.isdisjoint({row["id"] for row in first["employees"]})
    assert second["units"][0]["id"] == unit_ids[50]
    assert second["employees"][0]["id"] == employee_ids[50]
    assert employee_search["employee_total"] == 1
    assert employee_search["employees"][0]["id"] == employee_ids[-1]
    assert employee_search["unit_total"] == 0
    assert wildcard_search["unit_total"] == wildcard_search["employee_total"] == 0


def test_organization_page_http_keeps_authentication_and_page_size_bound(client, auth_headers):
    assert client.get("/api/hr/organization?page=1&page_size=50").status_code == 401
    response = client.get("/api/hr/organization?page=1&page_size=50", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["page_size"] == 50
    assert client.get("/api/hr/organization?page_size=101", headers=auth_headers).status_code == 422
