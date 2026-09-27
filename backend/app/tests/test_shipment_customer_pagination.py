from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.api.routes.shipments import manual_shipment_customers
from app.models import AuditLog, Customer
from app.tests.conftest import TestSessionLocal


@contextmanager
def _customer_database(count: int):
    engine = create_engine("sqlite://")
    Customer.__table__.create(engine)
    with Session(engine) as db:
        customers = [Customer(name=f"Customer {index:04d}") for index in range(count)]
        db.add_all(customers)
        db.commit()
        yield db, [int(customer.id) for customer in customers]
    engine.dispose()


def _read(db: Session, **kwargs):
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().lower().startswith("select"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        payload = manual_shipment_customers(db, object(), **kwargs)
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
    return payload, statements


@pytest.mark.parametrize("count", [1, 50, 401])
def test_shipment_customer_pages_bound_sql_and_preserve_legacy_payload(count):
    with _customer_database(count) as (db, customer_ids):
        page, statements = _read(db, page=1, page_size=50)
        legacy, legacy_statements = _read(db, page=None, page_size=None)
        expected_count = min(count, 50)
        expected = [
            {"id": customer_ids[index], "name": f"Customer {index:04d}"}
            for index in range(expected_count)
        ]

        assert page == {
            "rows": expected,
            "total": count,
            "page": 1,
            "page_size": 50,
            "has_more": count > 50,
        }
        assert page["rows"] == legacy[:expected_count]
        assert len(statements) == 2, statements
        assert " limit ? offset ?" in statements[1]
        assert len(legacy_statements) == 1, legacy_statements


def test_shipment_customer_page_contract_auth_bounds_and_no_writes(client, auth_headers):
    with TestSessionLocal() as db:
        db.add(Customer(name="!!! PERF35 shipment customer"))
        db.commit()
        before = (db.query(Customer).count(), db.query(AuditLog).count())

    legacy = client.get("/api/shipments/customers", headers=auth_headers)
    assert legacy.status_code == 200, legacy.text
    assert isinstance(legacy.json(), list)

    response = client.get(
        "/api/shipments/customers?page=1&page_size=50",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["rows"] == legacy.json()[:50]
    assert payload["total"] == len(legacy.json())
    assert payload["page"] == 1
    assert payload["page_size"] == 50
    assert payload["has_more"] is (payload["total"] > 50)

    assert client.get(
        "/api/shipments/customers?page_size=501",
        headers=auth_headers,
    ).status_code == 422
    assert client.get("/api/shipments/customers?page=1&page_size=1").status_code == 401

    login = client.post(
        "/api/auth/token",
        data={"username": "hr@example.com", "password": "demo12345"},
    )
    assert login.status_code == 200, login.text
    denied = client.get(
        "/api/shipments/customers?page=1&page_size=1",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert denied.status_code == 403, denied.text

    with TestSessionLocal() as db:
        after = (db.query(Customer).count(), db.query(AuditLog).count())
    assert after == before
