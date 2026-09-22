from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.finance import list_invoices
from app.db.session import SessionLocal
from app.models import Customer, Invoice, SalesOrder
from app.services.finance import count_invoices


def _seed_invoices(db, count: int) -> list[int]:
    suffix = uuid4().hex
    customer = Customer(name=f"Invoice pagination {suffix}")
    db.add(customer)
    db.flush()
    orders = [
        SalesOrder(
            order_no=f"FIN-PAGE-{suffix}-{number:04d}",
            customer_id=customer.id,
            total_amount=number + 1,
        )
        for number in range(count)
    ]
    db.add_all(orders)
    db.flush()
    invoices = [
        Invoice(
            sales_order_id=order.id,
            invoice_no=f"FIN-PAGE-INV-{suffix}-{number:04d}",
            amount=number + 1,
            status="unpaid",
            issued_at=datetime(2097, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=number),
        )
        for number, order in enumerate(orders)
    ]
    db.add_all(invoices)
    db.commit()
    return [int(invoice.id) for invoice in invoices]


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
def test_invoice_page_bounds_joined_enrichment_and_matches_legacy_prefix(row_count):
    with SessionLocal() as db:
        baseline = count_invoices(db)
        invoice_ids = _seed_invoices(db, row_count)

    with SessionLocal() as db:
        legacy, legacy_statements = _select_trace(
            db,
            lambda: list_invoices(db, None, limit=500),
        )
    with SessionLocal() as db:
        page, page_statements = _select_trace(
            db,
            lambda: list_invoices(db, None, page=1, page_size=50),
        )

    expected_ids = list(reversed(invoice_ids))[:50]
    assert [row["id"] for row in legacy[: len(expected_ids)]] == expected_ids
    assert [row["id"] for row in page["rows"]] == expected_ids
    assert page["rows"] == legacy[:50]
    assert page["total"] == baseline + row_count
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is ((baseline + row_count) > 50)
    assert len(page["rows"]) <= 50
    assert len(legacy_statements) == 1
    assert len(page_statements) == 2
    row_statement = next(statement for statement in page_statements if " from invoices " in statement)
    assert " join sales_orders " in row_statement
    assert " left outer join customers " in row_statement
    assert " limit ? offset ?" in row_statement


def test_invoice_page_http_contract_preserves_legacy_list_and_auth(client, auth_headers):
    with SessionLocal() as db:
        _seed_invoices(db, 1)

    legacy = client.get("/api/finance/invoices?limit=1", headers=auth_headers)
    assert legacy.status_code == 200
    assert isinstance(legacy.json(), list)
    assert len(legacy.json()) == 1

    paged = client.get("/api/finance/invoices?page=1&page_size=1", headers=auth_headers)
    assert paged.status_code == 200
    body = paged.json()
    assert body["rows"] == legacy.json()
    assert body["page"] == 1
    assert body["page_size"] == 1
    assert body["total"] >= 1

    assert client.get("/api/finance/invoices?page_size=501", headers=auth_headers).status_code == 422
    assert client.get("/api/finance/invoices?page=1&page_size=1").status_code == 401
