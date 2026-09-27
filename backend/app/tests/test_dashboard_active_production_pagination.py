from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.dashboards import active_production
from app.db.session import SessionLocal
from app.models import AuditLog, SalesOrder, User


def _seed_active_orders(count: int) -> list[int]:
    marker = uuid4().hex[:10]
    with SessionLocal() as db:
        db.query(SalesOrder).filter(
            SalesOrder.status.in_(("planning", "confirmed", "in_production")),
        ).update({SalesOrder.status: "cancelled"}, synchronize_session=False)
        start = datetime(2027, 1, 1, tzinfo=timezone.utc)
        rows = [
            SalesOrder(
                order_no=f"PERF35-DASH-{marker}-{index:04d}",
                order_type="client_order",
                status="planning",
                deadline=start + timedelta(days=index),
                total_amount=index + 1,
            )
            for index in range(count)
        ]
        db.add_all(rows)
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
            payload = active_production(db, user, **kwargs)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


@pytest.mark.parametrize("count", [1, 50, 401])
def test_active_production_pages_bound_dependent_reads_and_preserve_legacy_payload(count):
    created_ids = _seed_active_orders(count)
    returned_count = min(count, 50)

    page, statements = _read(limit=500, page=1, page_size=50)
    legacy, legacy_statements = _read(limit=500, page=None, page_size=None)

    assert page["total"] == count
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is (count > 50)
    assert [row["id"] for row in page["rows"]] == created_ids[:returned_count]
    assert page["rows"] == legacy[:returned_count]
    assert len(statements) == 4, statements
    assert len(legacy_statements) == 3, legacy_statements
    count_queries = [statement for statement in statements if "count(" in statement]
    assert len(count_queries) == 1, statements
    assert "count(sales_orders.id)" in count_queries[0]
    assert " from (select sales_orders." not in count_queries[0]
    sales_order_reads = [
        statement.lower()
        for statement in statements
        if " limit ? offset ?" in statement.lower()
        and "sales_orders.order_no as sales_orders_order_no" in statement.lower()
    ]
    assert len(sales_order_reads) == 1
    assert "sales_orders.printing_attachments" not in sales_order_reads[0]
    assert "sales_orders.notes" not in sales_order_reads[0]


def test_active_production_page_contract_auth_and_no_writes(client, auth_headers):
    created_ids = _seed_active_orders(3)
    with SessionLocal() as db:
        before = (db.query(SalesOrder).count(), db.query(AuditLog).count())

    response = client.get(
        "/api/dashboard/active-production",
        params={"page": 2, "page_size": 2},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 3
    assert payload["page"] == 2
    assert payload["page_size"] == 2
    assert payload["has_more"] is False
    assert [row["id"] for row in payload["rows"]] == created_ids[2:]
    assert client.get(
        "/api/dashboard/active-production",
        params={"page": 1, "page_size": 501},
        headers=auth_headers,
    ).status_code == 422

    login = client.post(
        "/api/auth/token",
        data={"username": "hr@example.com", "password": "demo12345"},
    )
    assert login.status_code == 200, login.text
    denied = client.get(
        "/api/dashboard/active-production",
        params={"page": 1, "page_size": 2},
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert denied.status_code == 403, denied.text

    with SessionLocal() as db:
        after = (db.query(SalesOrder).count(), db.query(AuditLog).count())
    assert after == before


def test_active_production_value_requires_recorded_currency(client, auth_headers):
    known_id, unknown_id = _seed_active_orders(2)
    with SessionLocal() as db:
        db.get(SalesOrder, known_id).currency = "UZS"
        db.commit()

    response = client.get("/api/dashboard/active-production", headers=auth_headers)
    assert response.status_code == 200, response.text
    rows = {row["id"]: row for row in response.json()}
    assert rows[known_id]["value"] == 1
    assert rows[known_id]["currency"] == "UZS"
    assert rows[unknown_id]["value"] is None
    assert rows[unknown_id]["currency"] is None
