from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.partners import list_suppliers
from app.db.session import SessionLocal
from app.models import AuditLog, Supplier
from app.schemas.catalog import PartyOut


def _seed_suppliers(count: int) -> tuple[list[int], int]:
    marker = uuid4().hex[:10]
    with SessionLocal() as db:
        db.query(Supplier).update({Supplier.is_active: False}, synchronize_session=False)
        rows = [
            Supplier(
                name=f"Bounded supplier {marker} {index:04d}",
                phone=f"+99890{index:07d}",
                notes=f"PERF35 supplier {index}",
                is_active=True,
            )
            for index in range(count)
        ]
        db.add_all(rows)
        db.flush()
        inactive = Supplier(name=f"Inactive supplier {marker}", is_active=False)
        db.add(inactive)
        db.commit()
        return [int(row.id) for row in rows], int(inactive.id)


def _read(**kwargs):
    with SessionLocal() as db:
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = list_suppliers(db, None, **kwargs)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


def _payload(rows: list[Supplier]) -> list[dict]:
    return [PartyOut.model_validate(row).model_dump(mode="json") for row in rows]


@pytest.mark.parametrize("count", [1, 50, 401])
def test_supplier_pages_bound_rows_and_preserve_legacy_payload(count):
    created_ids, inactive_id = _seed_suppliers(count)

    page, statements = _read(page=1, page_size=count)
    legacy, legacy_statements = _read(page=None, page_size=None)

    assert page["total"] == count
    assert page["page"] == 1
    assert page["page_size"] == count
    assert page["has_more"] is False
    assert [row.id for row in page["rows"]] == list(reversed(created_ids))
    assert inactive_id not in [row.id for row in page["rows"]]
    assert _payload(page["rows"]) == _payload(legacy)
    assert len(statements) == 2, statements
    assert len(legacy_statements) == 1, legacy_statements


def test_supplier_page_contract_bound_authorization_and_no_writes(client, auth_headers):
    created_ids, _ = _seed_suppliers(3)
    with SessionLocal() as db:
        before = (db.query(Supplier).count(), db.query(AuditLog).count())

    response = client.get(
        "/api/suppliers",
        params={"page": 1, "page_size": 2},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 3
    assert payload["page"] == 1
    assert payload["page_size"] == 2
    assert payload["has_more"] is True
    assert [row["id"] for row in payload["rows"]] == list(reversed(created_ids))[:2]
    assert client.get(
        "/api/suppliers",
        params={"page": 1, "page_size": 501},
        headers=auth_headers,
    ).status_code == 422

    login = client.post(
        "/api/auth/token",
        data={"username": "hr@example.com", "password": "demo12345"},
    )
    assert login.status_code == 200, login.text
    denied = client.get(
        "/api/suppliers",
        params={"page": 1, "page_size": 2},
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert denied.status_code == 403, denied.text

    with SessionLocal() as db:
        after = (db.query(Supplier).count(), db.query(AuditLog).count())
    assert after == before
