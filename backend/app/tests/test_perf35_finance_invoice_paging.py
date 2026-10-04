"""PERF35-FINANCE: the invoice list must not silently stop at fifty rows.

The row's original defect was silent truncation, not slow hydration: the
route accepted no offset, so anything past the first 50 invoices was simply
unreachable from the UI. These tests pin reachability and an EXACT total.

Note on style for this repo: assert on what the caller can observe (rows
returned, `total`), not on statement counts. A statement budget is a green
lie on this codebase.
"""
from decimal import Decimal

import pytest

from app.models import Customer, Invoice, SalesOrder
from app.tests.conftest import TestSessionLocal
from app.services.finance import list_recent_invoices


@pytest.fixture
def many_invoices():
    """Seed 60 invoices, which is past the old hard stop of 50."""
    with TestSessionLocal() as db:
        customer = Customer(name="PERF35 paging customer")
        db.add(customer)
        db.flush()
        order = SalesOrder(
            order_no="PERF35-PAGE-ORDER",
            customer_id=customer.id,
            total_amount=Decimal("600"),
            status="confirmed",
        )
        db.add(order)
        db.flush()
        for i in range(60):
            db.add(Invoice(
                sales_order_id=order.id,
                invoice_no=f"PERF35-{i:04d}",
                amount=Decimal("10"),
                status="unpaid",
            ))
        db.commit()
    yield


def test_rows_past_fifty_are_reachable(client, auth_headers, many_invoices):
    """The core regression: the old route made row 50+ unreachable."""
    first = client.get("/api/finance/invoices?limit=50&offset=0", headers=auth_headers)
    assert first.status_code == 200, first.text
    body = first.json()
    assert len(body["items"]) == 50
    assert body["total"] == 60

    # The 51st row must actually be fetchable, not swallowed.
    second = client.get("/api/finance/invoices?limit=50&offset=50", headers=auth_headers)
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert len(second_body["items"]) == 10
    assert second_body["total"] == 60
    # No overlap between the two pages, and together they cover everything.
    first_ids = {row["id"] for row in body["items"]}
    second_ids = {row["id"] for row in second_body["items"]}
    assert not (first_ids & second_ids)
    assert len(first_ids | second_ids) == 60


def test_total_is_exact_not_page_length(client, auth_headers, many_invoices):
    """`total` must describe the whole filtered set, never the page."""
    response = client.get("/api/finance/invoices?limit=5", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["items"]) == 5
    assert body["total"] == 60
    assert body["limit"] == 5
    assert body["offset"] == 0


def test_offset_past_the_end_is_empty_not_an_error(client, auth_headers, many_invoices):
    response = client.get("/api/finance/invoices?limit=10&offset=500", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 60


def test_hostile_limit_is_clamped_not_a_server_error(client, auth_headers, many_invoices):
    for bad in ("0", "-5", "999999999"):
        response = client.get(f"/api/finance/invoices?limit={bad}", headers=auth_headers)
        assert response.status_code == 200, f"limit={bad}: {response.text}"
        assert 1 <= len(response.json()["items"]) <= 200


def test_negative_offset_is_clamped(client, auth_headers, many_invoices):
    response = client.get("/api/finance/invoices?limit=5&offset=-10", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["offset"] == 0


def test_search_narrows_the_page_and_the_total_together(client, auth_headers, many_invoices):
    response = client.get(
        "/api/finance/invoices?limit=50&search=PERF35-0007", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1, body
    assert [row["invoice_no"] for row in body["items"]] == ["PERF35-0007"]


def test_search_matching_nothing_returns_empty_and_zero_total(client, auth_headers, many_invoices):
    response = client.get(
        "/api/finance/invoices?limit=50&search=NO-SUCH-INVOICE-XYZ", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_ordering_is_newest_first_and_stable_across_pages(client, auth_headers, many_invoices):
    with TestSessionLocal() as db:
        expected = [row.id for row in db.query(Invoice.id).order_by(Invoice.id.desc()).all()]

    # Page through the whole set; two pages of 25 would only cover 50 of 60.
    seen: list[int] = []
    offset = 0
    while True:
        body = client.get(
            f"/api/finance/invoices?limit=25&offset={offset}", headers=auth_headers
        ).json()
        rows = body["items"]
        seen.extend(row["id"] for row in rows)
        offset += len(rows)
        if not rows or offset >= body["total"]:
            break

    assert seen == expected
    assert len(seen) == len(set(seen)), "an invoice appeared on two pages"


def test_service_still_returns_a_plain_list_for_existing_callers():
    """`test_finance_received_revenue` imports the service directly and
    iterates it, so the service return type must not become an envelope."""
    with TestSessionLocal() as db:
        rows = list_recent_invoices(db, limit=3)
    assert isinstance(rows, list)
    assert len(rows) <= 3
    assert all(isinstance(row, dict) for row in rows)


def test_count_invoices_matches_the_page_filter():
    # Imported lazily so this module still collects (and the other tests still
    # fail meaningfully) against the unfixed service, which has no count.
    from app.services.finance import count_invoices

    with TestSessionLocal() as db:
        unfiltered = count_invoices(db)
        filtered = count_invoices(db, search="PERF35-")
    assert filtered <= unfiltered
