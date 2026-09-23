from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.search import global_search
from app.db.session import SessionLocal
from app.models import Customer
from app.tests.test_task_assignment_authorization import _actor


def _seed_customers(count: int) -> tuple[str, list[int]]:
    marker = f"SEARCHPAGE{uuid4().hex[:12].upper()}"
    with SessionLocal() as db:
        rows = [Customer(name=f"{marker} {number:04d}") for number in range(count)]
        db.add_all(rows)
        db.commit()
        return marker, [int(row.id) for row in rows]


def _select_trace(db, callback):
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select"):
            statements.append(normalized)

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        return callback(), statements
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)


@pytest.mark.parametrize("row_count", [1, 50, 401])
def test_global_search_page_bounds_union_and_matches_legacy_prefix(row_count):
    marker, customer_ids = _seed_customers(row_count)

    with SessionLocal() as db:
        legacy, legacy_statements = _select_trace(
            db,
            lambda: global_search(marker, db, None, limit_per_type=200),
        )
    with SessionLocal() as db:
        page, page_statements = _select_trace(
            db,
            lambda: global_search(marker, db, None, page=1, page_size=50),
        )

    expected_ids = list(reversed(customer_ids))[:50]
    assert [row["id"] for row in legacy[:50]] == expected_ids
    assert [row["id"] for row in page["rows"]] == expected_ids
    assert page["rows"] == legacy[:50]
    assert all(row["type"] == "Customer" for row in page["rows"])
    assert page["total"] == row_count
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is (row_count > 50)
    assert len(page["rows"]) <= 50
    assert len(legacy_statements) == 1
    assert legacy_statements[0].count(" union all ") == 3
    assert "row_number() over (" in legacy_statements[0]
    assert "partition by" in legacy_statements[0]
    assert "type_row_number <= ?" in legacy_statements[0]
    assert len(page_statements) == 2
    assert all(statement.count(" union all ") == 3 for statement in page_statements)
    row_statement = next(statement for statement in page_statements if " order by anon_1.type_rank" in statement)
    assert " limit ? offset ?" in row_statement


def test_global_search_page_http_contract_preserves_legacy_and_auth(client):
    _, headers = _actor()
    marker, _ = _seed_customers(1)

    legacy = client.get(
        "/api/search",
        params={"q": marker, "limit_per_type": 1},
        headers=headers,
    )
    assert legacy.status_code == 200
    assert isinstance(legacy.json(), list)
    assert len(legacy.json()) == 1

    paged = client.get(
        "/api/search",
        params={"q": marker, "page": 1, "page_size": 1},
        headers=headers,
    )
    assert paged.status_code == 200
    body = paged.json()
    assert body["rows"] == legacy.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["page_size"] == 1

    empty = client.get(
        "/api/search",
        params={"q": "", "page": 1, "page_size": 1},
        headers=headers,
    )
    assert empty.status_code == 200
    assert empty.json() == {
        "rows": [],
        "total": 0,
        "page": 1,
        "page_size": 1,
        "has_more": False,
    }
    assert client.get(
        "/api/search",
        params={"q": marker, "page_size": 201},
        headers=headers,
    ).status_code == 422
    assert client.get("/api/search", params={"q": marker}).status_code == 401
