from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.encoders import jsonable_encoder
from sqlalchemy import event

from app.api.routes.partners import get_customer_payments
from app.core.security import create_access_token
from app.models import AuditLog, Customer, Payment, Role, User
from app.tests.conftest import TestSessionLocal


def _seed_customer_payments(row_count: int) -> tuple[int, list[int]]:
    marker = uuid4().hex
    with TestSessionLocal() as db:
        customer = Customer(name=f"Paged payment customer {marker}")
        db.add(customer)
        db.flush()
        payments = [
            Payment(
                customer_id=customer.id,
                amount=index + 1,
                payment_method="cash",
                paid_at=datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index),
                notes=f"Payment {index:04d}",
            )
            for index in range(row_count)
        ]
        db.add_all(payments)
        db.commit()
        return int(customer.id), [int(payment.id) for payment in payments]


def _read(customer_id: int, **kwargs):
    with TestSessionLocal() as db:
        statements: list[str] = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select"):
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = get_customer_payments(customer_id, db, object(), **kwargs)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


@pytest.mark.parametrize("row_count", [1, 50, 401])
def test_customer_payment_page_bounds_sql_and_preserves_legacy_prefix(row_count):
    customer_id, payment_ids = _seed_customer_payments(row_count)

    legacy, legacy_statements = _read(customer_id, limit=500)
    page, page_statements = _read(customer_id, limit=500, page=1, page_size=50)

    expected_rows = min(row_count, 50)
    assert page["total"] == row_count
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is (row_count > 50)
    assert len(page["rows"]) == expected_rows
    assert jsonable_encoder(page["rows"]) == jsonable_encoder(legacy[:expected_rows])
    assert [row["id"] for row in page["rows"]] == list(reversed(payment_ids))[:expected_rows]
    assert len(legacy_statements) == 2, legacy_statements
    assert len(page_statements) == 3, page_statements
    assert " limit ? offset ?" in page_statements[-1]


def test_customer_payment_page_preserves_auth_404_validation_and_no_writes(client, auth_headers):
    customer_id, payment_ids = _seed_customer_payments(3)
    with TestSessionLocal() as db:
        role = Role(name=f"No customer access {uuid4().hex}", permissions=[])
        db.add(role)
        db.flush()
        denied_user = User(
            name="Denied customer payment reader",
            email=f"denied-customer-payments-{uuid4().hex}@example.com",
            password_hash="unused-pagination-hash",
            role_id=role.id,
            factory_code="MIL",
            extra_permissions=[],
            is_active=True,
        )
        db.add(denied_user)
        db.commit()
        denied_headers = {"Authorization": f"Bearer {create_access_token(denied_user.id)}"}
        before = (
            db.query(Payment).filter(Payment.id.in_(payment_ids)).count(),
            db.query(AuditLog).count(),
        )

    legacy = client.get(
        f"/api/customers/{customer_id}/payments?limit=1",
        headers=auth_headers,
    )
    paged = client.get(
        f"/api/customers/{customer_id}/payments?page=1&page_size=1",
        headers=auth_headers,
    )
    assert legacy.status_code == 200, legacy.text
    assert paged.status_code == 200, paged.text
    assert isinstance(legacy.json(), list)
    assert paged.json()["rows"] == legacy.json()
    assert paged.json()["total"] == 3
    assert paged.json()["has_more"] is True

    assert client.get(
        f"/api/customers/{customer_id}/payments?page=1&page_size=501",
        headers=auth_headers,
    ).status_code == 422
    assert client.get(
        f"/api/customers/{customer_id}/payments?page=1&page_size=1",
        headers=denied_headers,
    ).status_code == 403
    assert client.get(
        f"/api/customers/{customer_id}/payments?page=1&page_size=1",
    ).status_code == 401
    missing = client.get(
        "/api/customers/2147483647/payments?page=1&page_size=1",
        headers=auth_headers,
    )
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Customer not found"}

    with TestSessionLocal() as db:
        after = (
            db.query(Payment).filter(Payment.id.in_(payment_ids)).count(),
            db.query(AuditLog).count(),
        )
    assert after == before
