from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.admin import list_roles
from app.db.session import SessionLocal
from app.models import Role
from app.schemas.catalog import RoleOut


def _seed_roles(count: int) -> int:
    marker = uuid4().hex[:8].upper()
    with SessionLocal() as db:
        baseline = db.query(Role).count()
        db.add_all([
            Role(name=f"PERF35 role {marker} {number:04d}", permissions=[])
            for number in range(count)
        ])
        db.commit()
        return baseline


def _serialize_rows(rows):
    return [RoleOut.model_validate(row).model_dump(mode="json") for row in rows]


def _read(**kwargs):
    with SessionLocal() as db:
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = list_roles(db, SimpleNamespace(), **kwargs)
            if isinstance(payload, dict):
                payload = {**payload, "rows": _serialize_rows(payload["rows"])}
            else:
                payload = _serialize_rows(payload)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


@pytest.mark.parametrize("role_count", [1, 50, 401])
def test_role_page_bounds_rows_and_preserves_legacy_order(role_count):
    baseline = _seed_roles(role_count)

    page, statements = _read(page=1, page_size=50)
    legacy, legacy_statements = _read()

    selects = [statement for statement in statements if statement.startswith("select")]
    writes = [
        statement for statement in statements
        if statement.startswith(("insert", "update", "delete"))
    ]
    assert page["total"] == baseline + role_count
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is (page["total"] > 50)
    assert page["rows"] == legacy[:50]
    assert len(page["rows"]) == min(page["total"], 50)
    assert len(selects) == 2, selects
    assert len([statement for statement in legacy_statements if statement.startswith("select")]) == 1
    assert writes == []


def test_role_page_http_contract_and_authenticated_access(client, auth_headers):
    legacy = client.get("/api/roles", headers=auth_headers)
    paged = client.get(
        "/api/roles",
        params={"page": 1, "page_size": 50},
        headers=auth_headers,
    )

    assert legacy.status_code == paged.status_code == 200
    payload = paged.json()
    assert payload["rows"] == legacy.json()[:50]
    assert payload["total"] == len(legacy.json())
    assert payload["has_more"] is (payload["total"] > 50)
    assert client.get("/api/roles?page=1&page_size=1").status_code == 401

    storage_login = client.post(
        "/api/auth/token",
        data={"username": "storage@example.com", "password": "demo12345"},
    )
    assert storage_login.status_code == 200, storage_login.text
    storage_response = client.get(
        "/api/roles?page=1&page_size=1",
        headers={"Authorization": f"Bearer {storage_login.json()['access_token']}"},
    )
    assert storage_response.status_code == 200, storage_response.text
    assert len(storage_response.json()["rows"]) == 1


def test_role_page_size_is_bounded(client, auth_headers):
    response = client.get(
        "/api/roles",
        params={"page": 1, "page_size": 501},
        headers=auth_headers,
    )

    assert response.status_code == 422, response.text
