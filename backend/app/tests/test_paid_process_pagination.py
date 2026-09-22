from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.paid_processes import list_processes
from app.db.session import SessionLocal
from app.models import AuditLog, User
from app.models.paid_process import PaidProcess
from app.services.paid_process_catalog import normalized_key, normalized_name


def _process(*, marker: str, index: int, factory_code: str = "MIL", prefix: str = "Bounded"):
    name = f"{prefix} process {marker} {index:04d}"
    return PaidProcess(
        factory_code=factory_code,
        code=f"P35-{marker}-{factory_code}-{index:04d}",
        name=name,
        normalized_name=normalized_name(name),
        normalized_key=normalized_key(name),
        section="sewing",
    )


def _seed_processes(count: int) -> list[int]:
    marker = uuid4().hex[:8]
    with SessionLocal() as db:
        db.query(PaidProcess).delete(synchronize_session=False)
        rows = [_process(marker=marker, index=index) for index in range(count)]
        db.add_all(rows)
        db.add(_process(marker=marker, index=count, factory_code="ECO"))
        db.commit()
        return [int(row.id) for row in rows]


def _read(**kwargs):
    with SessionLocal() as db:
        user = db.get(User, 1)
        assert user is not None
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = list_processes(db, current=user, **kwargs)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


@pytest.mark.parametrize("count", [1, 50, 401])
def test_paid_process_pages_bound_rows_and_preserve_legacy_prefix(count):
    created_ids = _seed_processes(count)

    page, statements = _read(search="", page=1, page_size=count)
    legacy, legacy_statements = _read(search="", page=None, page_size=None)

    assert page["total"] == count
    assert page["page"] == 1
    assert page["page_size"] == count
    assert page["has_more"] is False
    assert [row["id"] for row in page["items"]] == created_ids
    assert page["items"][:50] == legacy["items"]
    assert legacy["has_more"] is (count > 50)
    assert len(statements) == 2, statements
    assert len(legacy_statements) == 1, legacy_statements


def test_paid_process_page_filters_before_count_and_has_no_write_side_effects(client, auth_headers):
    marker = uuid4().hex[:8]
    with SessionLocal() as db:
        db.query(PaidProcess).delete(synchronize_session=False)
        matching = [
            _process(marker=marker, index=index, prefix="Needle")
            for index in range(3)
        ]
        db.add_all([
            *matching,
            _process(marker=marker, index=3, prefix="Other"),
            _process(marker=marker, index=4, factory_code="ECO", prefix="Needle"),
        ])
        db.commit()
        matching_ids = [int(row.id) for row in matching]
        before = (db.query(PaidProcess).count(), db.query(AuditLog).count())

    response = client.get(
        "/api/paid-processes",
        params={"search": f"needle process {marker}", "page": 1, "page_size": 2},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 3
    assert payload["page"] == 1
    assert payload["page_size"] == 2
    assert payload["has_more"] is True
    assert [row["id"] for row in payload["items"]] == matching_ids[:2]
    assert client.get(
        "/api/paid-processes",
        params={"page": 1, "page_size": 501},
        headers=auth_headers,
    ).status_code == 422

    login = client.post(
        "/api/auth/token",
        data={"username": "hr@example.com", "password": "demo12345"},
    )
    assert login.status_code == 200, login.text
    denied = client.get(
        "/api/paid-processes",
        params={"page": 1, "page_size": 2},
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert denied.status_code == 403, denied.text

    with SessionLocal() as db:
        after = (db.query(PaidProcess).count(), db.query(AuditLog).count())
    assert after == before
