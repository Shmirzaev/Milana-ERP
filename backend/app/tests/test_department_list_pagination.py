from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.admin import list_departments
from app.db.session import SessionLocal
from app.models import AuditLog, Department
from app.schemas.catalog import DepartmentOut


def _seed_departments(count: int) -> tuple[list[int], int]:
    marker = uuid4().hex[:8]
    with SessionLocal() as db:
        baseline = db.query(Department).count()
        rows = [
            Department(
                name=f"Bounded department {marker} {index:04d}",
                code=f"P35{marker[:6]}{index:04d}",
            )
            for index in range(count)
        ]
        db.add_all(rows)
        db.commit()
        return [int(row.id) for row in rows], baseline


def _read(**kwargs):
    with SessionLocal() as db:
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = list_departments(db, None, **kwargs)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


def _payload(rows: list[Department]) -> list[dict]:
    return [DepartmentOut.model_validate(row).model_dump(mode="json") for row in rows]


def _assert_department_projection(statements):
    reads = [sql for sql in statements if " from departments " in sql and "count(" not in sql]
    assert len(reads) == 1
    selected_columns = reads[0].split(" from departments ", maxsplit=1)[0]
    assert "departments.id" in selected_columns
    assert "departments.name" in selected_columns
    assert "departments.code" in selected_columns
    assert "created_at" not in selected_columns
    assert "updated_at" not in selected_columns


@pytest.mark.parametrize("count", [1, 50, 401])
def test_department_pages_bound_rows_and_preserve_legacy_payload(count):
    created_ids, baseline = _seed_departments(count)

    page, statements = _read(page=1, page_size=count)
    legacy, legacy_statements = _read(page=None, page_size=None)

    assert page["total"] == baseline + count
    assert page["page"] == 1
    assert page["page_size"] == count
    assert page["has_more"] is (baseline > 0)
    assert [row.id for row in page["rows"]] == [row.id for row in legacy[:count]]
    assert created_ids == [row.id for row in legacy[-count:]]
    assert _payload(page["rows"]) == _payload(legacy[:count])
    assert len(statements) == 2, statements
    assert len(legacy_statements) == 1, legacy_statements
    _assert_department_projection(statements)
    _assert_department_projection(legacy_statements)


def test_department_page_contract_auth_and_no_writes(client, auth_headers):
    created_ids, baseline = _seed_departments(3)
    with SessionLocal() as db:
        before = (db.query(Department).count(), db.query(AuditLog).count())

    response = client.get(
        "/api/departments",
        params={"page": 2, "page_size": baseline + 1},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == baseline + 3
    assert payload["page"] == 2
    assert payload["page_size"] == baseline + 1
    assert payload["has_more"] is False
    assert [row["id"] for row in payload["rows"]] == created_ids[1:]
    assert client.get(
        "/api/departments",
        params={"page": 1, "page_size": 501},
        headers=auth_headers,
    ).status_code == 422
    assert client.get(
        "/api/departments",
        params={"page": 1, "page_size": 2},
    ).status_code == 401

    with SessionLocal() as db:
        after = (db.query(Department).count(), db.query(AuditLog).count())
    assert after == before
