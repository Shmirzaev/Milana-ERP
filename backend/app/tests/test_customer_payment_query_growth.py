"""PERF29: candidate-invoice paid sums must be batched, not summed per invoice.

Customer payment selection used to call ``invoice_paid_total`` once per candidate
invoice, so the query count grew linearly with the number of candidate invoices.
The sums are now fetched in grouped batches under the same invoice locks.

Three independent proofs live here:

* the query-count invariant, which fails on the retired per-invoice loop;
* exact money equality against a live per-invoice oracle, so a batched sum must
  equal ``invoice_paid_total`` for zero-receipt, partial, cent-boundary,
  overpaid and reversed invoices;
* the approved USD settlement display rule (<= $1.00 outstanding reads paid)
  staying a display rule while the real cent remains payable.

Query counting, ``FOR UPDATE`` locks and ``NUMERIC(14,2)`` arithmetic need real
PostgreSQL, so the first two proofs run against ``STABILIZATION_POSTGRES_URL``
and SKIP when it is unset. The settlement display proof runs on the shared
SQLite client suite.
"""

import os
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes.partners import _candidate_paid_totals, _find_payable_invoice
from app.db.base import Base
from app.models import Customer, Invoice, Payment, SalesOrder
from app.services.payments import (
    REVERSED_INVOICE_STATUSES,
    invoice_paid_total,
    invoice_payment_status,
    money_decimal,
)
from app.tests.conftest import TestSessionLocal

# A balanced-per-invoice ledger, then one payable candidate at the end.
_SETTLED_AMOUNT = Decimal("100.00")
_SETTLED_RECEIPTS = (Decimal("70.00"), Decimal("30.00"))


@pytest.fixture(scope="module")
def perf29_postgres_sessions():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL payment query growth")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("PERF29 coverage requires a loopback PostgreSQL URL without connection overrides")
    schema = f"perf29_query_growth_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema}"},
        pool_size=2,
        max_overflow=0,
    )
    assert engine.dialect.name == "postgresql"
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False), engine
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def _new_order(db, prefix, total_amount=100):
    order = SalesOrder(order_no=f"{prefix}-{uuid4().hex}", status="confirmed", total_amount=total_amount)
    db.add(order)
    db.flush()
    return order


def _add_invoice(db, order, amount, *, status="unpaid", receipts=()):
    invoice = Invoice(
        invoice_no=f"PERF29-{uuid4().hex}",
        sales_order_id=order.id,
        amount=amount,
        status=status,
    )
    db.add(invoice)
    db.flush()
    for receipt in receipts:
        db.add(Payment(invoice_id=invoice.id, amount=receipt))
    return invoice


def _growth_order(sessions, invoice_count):
    """Order whose only payable candidate is the last invoice.

    Every earlier invoice is settled to the cent, so a per-invoice loop must sum
    all of them before it can reach the payable candidate.
    """
    with sessions() as db:
        order = _new_order(db, "PERF29-GROW", total_amount=invoice_count * 100)
        for _ in range(invoice_count - 1):
            _add_invoice(db, order, _SETTLED_AMOUNT, receipts=_SETTLED_RECEIPTS)
        payable = _add_invoice(db, order, _SETTLED_AMOUNT)
        # An advance carries no invoice and must never enter a candidate sum.
        db.add(Payment(invoice_id=None, amount=Decimal("9999.00")))
        db.commit()
        return int(order.id), int(payable.id)


def _select_payable(sessions, engine, order_id):
    """Run the selection under a statement counter.

    The order is loaded before the listener is attached so the counter only
    measures ``_find_payable_invoice`` itself.
    """
    statements: list[str] = []

    def capture(_conn, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.split()))

    with sessions() as db:
        order = db.get(SalesOrder, order_id)
        event.listen(engine, "before_cursor_execute", capture)
        try:
            invoice = _find_payable_invoice(db, order)
            selected = None if invoice is None else (int(invoice.id), invoice.invoice_no, invoice.status)
        finally:
            event.remove(engine, "before_cursor_execute", capture)
    return statements, selected


def test_payable_selection_query_count_does_not_grow_with_invoice_count(perf29_postgres_sessions):
    """Query count must stay bounded, not linear, in candidate invoice count.

    10x the invoices must not cost 10x the queries. The bound is deliberately
    loose: a correct implementation issues one locking read plus one grouped
    sum batch, and may chunk the sums, so only linear growth is rejected here.
    """
    sessions, engine = perf29_postgres_sessions
    small_order, small_payable = _growth_order(sessions, 5)
    large_order, large_payable = _growth_order(sessions, 50)

    small_statements, small_selected = _select_payable(sessions, engine, small_order)
    large_statements, large_selected = _select_payable(sessions, engine, large_order)

    assert small_selected == (small_payable, small_selected[1], small_selected[2])
    assert large_selected[0] == large_payable

    small_count, large_count = len(small_statements), len(large_statements)
    assert large_count <= small_count * 2 + 4, (
        "candidate paid sums are still read per invoice: "
        f"{small_count} queries for 5 invoices but {large_count} for 50\n"
        + "\n".join(large_statements[:4])
    )
    # The payable candidate is still the same invoice; batching must not reorder.
    assert small_selected[0] == small_payable and large_selected[0] == large_payable


def test_payable_selection_keeps_one_invoice_lock_and_batches_the_sums(perf29_postgres_sessions):
    sessions, engine = perf29_postgres_sessions
    order_id, payable_id = _growth_order(sessions, 50)
    statements, selected = _select_payable(sessions, engine, order_id)

    locking = [s for s in statements if "FOR UPDATE" in s]
    assert len(locking) == 1, f"the candidate invoice lock must be taken exactly once: {statements}"
    assert "FROM invoices" in locking[0]
    grouped = [s for s in statements if "GROUP BY" in s]
    assert len(grouped) == 1, (
        f"paid sums must be one grouped read, not 50 per-invoice reads: {len(statements)} statements"
    )
    assert "payments" in grouped[0]
    assert selected[0] == payable_id


def test_candidate_paid_sums_equal_the_per_invoice_loop_exactly(perf29_postgres_sessions):
    """Batched sums must be the same ``Decimal`` as ``invoice_paid_total``.

    Covers a receipt-less invoice (NULL vs zero), partial receipts, a sum that
    lands exactly on a cent, an overpaid invoice, a reversed invoice and the
    top of the ``NUMERIC(14,2)`` range. A stray advance must stay excluded.
    """
    sessions, engine = perf29_postgres_sessions
    shapes = {
        "no_receipts": (Decimal("100.00"), ()),
        "partial": (Decimal("100.00"), (Decimal("33.33"), Decimal("0.01"))),
        "cent_boundary": (Decimal("50.00"), (Decimal("24.99"), Decimal("24.01"))),
        "settlement_cent": (Decimal("50.00"), (Decimal("49.00"),)),
        "three_receipts": (Decimal("75.00"), (Decimal("25.00"), Decimal("25.00"), Decimal("25.00"))),
        "overpaid": (Decimal("20.00"), (Decimal("20.00"), Decimal("0.01"))),
        "max_numeric": (Decimal("999999999999.99"), (Decimal("999999999998.99"),)),
    }
    with sessions() as db:
        order = _new_order(db, "PERF29-MONEY", total_amount=1000)
        expected = {}
        for name, (amount, receipts) in shapes.items():
            invoice = _add_invoice(db, order, amount, receipts=receipts)
            expected[int(invoice.id)] = name
        reversed_invoice = _add_invoice(
            db, order, Decimal("100.00"), status="void", receipts=(Decimal("1.00"),)
        )
        db.add(Payment(invoice_id=None, amount=Decimal("9999.00")))
        db.commit()
        order_id, invoice_ids = int(order.id), list(expected)
        reversed_id = int(reversed_invoice.id)

    with sessions() as db:
        # Oracle: the retired per-invoice loop, still run here on purpose.
        oracle = {int(i): invoice_paid_total(db, int(i)) for i in invoice_ids + [reversed_id]}
        batched = _candidate_paid_totals(db, invoice_ids)
        assert sorted(batched) == sorted(invoice_ids)
        for invoice_id in invoice_ids:
            assert batched[invoice_id] == oracle[invoice_id]
            assert isinstance(batched[invoice_id], Decimal)
            assert batched[invoice_id].as_tuple() == oracle[invoice_id].as_tuple()
        # A receipt-less invoice is zero, never None, and never NULL.
        assert batched[next(i for i in invoice_ids if expected[i] == "no_receipts")] == Decimal("0")

        order = db.get(SalesOrder, order_id)
        invoices = {
            int(inv.id): inv
            for inv in db.query(Invoice).filter(Invoice.sales_order_id == order_id).order_by(Invoice.id).all()
        }
        active = [i for i in invoice_ids if invoices[i].status not in REVERSED_INVOICE_STATUSES]
        oracle_payable = next(
            i for i in active if money_decimal(invoices[i].amount) - oracle[i] > Decimal(0)
        )
        selected = _find_payable_invoice(db, order)
        assert int(selected.id) == oracle_payable == min(active)
        # The reversed invoice is never a candidate even though it has a receipt.
        assert int(reversed_id) not in active
        # A batched sum equals the loop for every displayed balance as well.
        for invoice_id in invoice_ids:
            assert money_decimal(invoices[invoice_id].amount) - batched[invoice_id] == (
                money_decimal(invoices[invoice_id].amount) - oracle[invoice_id]
            )


def test_batched_sums_keep_the_settlement_cent_payable_and_displayed_as_paid(perf29_postgres_sessions):
    """<= $1.00 outstanding reads paid, but the real cent stays payable."""
    sessions, _engine = perf29_postgres_sessions
    with sessions() as db:
        order = _new_order(db, "PERF29-SETTLE", total_amount=100)
        settled = _add_invoice(db, order, Decimal("100.00"), receipts=(Decimal("99.00"),))
        db.commit()
        order_id, invoice_id = int(order.id), int(settled.id)

    with sessions() as db:
        total = invoice_paid_total(db, invoice_id)
        assert total == Decimal("99.00")
        # Display rule: outstanding exactly $1.00 reads paid.
        assert invoice_payment_status(Decimal("100.00"), total, "unpaid") == "paid"
        # Selection rule: settlement is display only, so the cent stays payable.
        selected = _find_payable_invoice(db, db.get(SalesOrder, order_id))
        assert int(selected.id) == invoice_id
        assert money_decimal(Decimal("100.00")) - _candidate_paid_totals(db, [invoice_id])[invoice_id] == Decimal("1.00")
        assert 0 < money_decimal(Decimal("100.00")) - _candidate_paid_totals(db, [invoice_id])[invoice_id] <= Decimal("1.00")


def test_reversed_only_order_selects_nothing_and_reads_no_sums(perf29_postgres_sessions):
    sessions, engine = perf29_postgres_sessions
    with sessions() as db:
        order = _new_order(db, "PERF29-REVERSED", total_amount=100)
        _add_invoice(db, order, Decimal("100.00"), status="void", receipts=(Decimal("1.00"),))
        db.commit()
        order_id = int(order.id)

    statements, selected = _select_payable(sessions, engine, order_id)
    assert selected is None
    assert not [s for s in statements if "GROUP BY" in s], (
        f"a fully reversed order has no payable candidate to sum: {len(statements)} statements"
    )


# --------------------------------------------------------------------------
# Approved USD settlement display rule, pinned on the shared SQLite client.
# --------------------------------------------------------------------------

@pytest.fixture
def settlement_order():
    with TestSessionLocal() as db:
        customer = Customer(name="PERF29 settlement")
        db.add(customer)
        db.flush()
        order = SalesOrder(order_no=f"PERF29-{uuid4().hex}", customer_id=customer.id, total_amount=100)
        db.add(order)
        db.flush()
        invoice = Invoice(invoice_no=f"PERF29-{uuid4().hex}", sales_order_id=order.id, amount=100, status="unpaid")
        db.add(invoice)
        db.commit()
        return customer.id, order.id, invoice.id, invoice.invoice_no


def test_exactly_one_dollar_outstanding_displays_paid_but_is_still_payable(client, auth_headers, settlement_order):
    cid, oid, iid, invoice_no = settlement_order
    with TestSessionLocal() as db:
        db.add(Payment(invoice_id=iid, customer_id=cid, amount=Decimal("99.00")))
        db.commit()

    history = client.get(f"/api/customers/{cid}/orders", headers=auth_headers)
    assert history.status_code == 200, history.text
    row = next(row for row in history.json() if row["id"] == oid)
    assert row["invoices"][0]["status"] == "paid"
    assert row["payment_status"] == "paid"
    assert row["paid_total"] == 99.0 and row["balance_due"] == 1.0
    assert row["invoices"][0]["raw_paid_amount"] == 99.0

    # The displayed settlement must not stop the real cent from being allocated.
    response = client.post(
        f"/api/customers/{cid}/payments",
        headers={**auth_headers, "Idempotency-Key": f"perf29-{uuid4().hex}"},
        json={"sales_order_id": oid, "amount": 1.0},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["amount"] == 1.0
    assert payload["invoice_id"] == iid
    assert payload["invoice_no"] == invoice_no
    assert payload["invoice_amount"] == 100.0
    assert payload["order_id"] == oid
    assert payload["order_no"] == row["order_no"]
    assert payload["is_advance"] is False
    assert payload["payment_method"] is None

    with TestSessionLocal() as db:
        assert invoice_paid_total(db, iid) == Decimal("100.00")
        assert db.query(Payment).filter_by(customer_id=cid, invoice_id=None).count() == 0
    after = client.get(f"/api/customers/{cid}/orders", headers=auth_headers)
    settled = next(row for row in after.json() if row["id"] == oid)
    assert settled["paid_total"] == 100.0 and settled["balance_due"] == 0.0


@pytest.mark.parametrize(("outstanding", "invoice_status", "payment_status"), [
    ("0.99", "paid", "paid"),
    ("1.00", "paid", "paid"),
    ("1.01", "partially_paid", "partial"),
])
def test_settlement_boundary_display_never_alters_the_ledger(
    client, auth_headers, settlement_order, outstanding, invoice_status, payment_status,
):
    cid, oid, iid, _invoice_no = settlement_order
    outstanding_decimal = Decimal(outstanding)
    paid = Decimal("100.00") - outstanding_decimal
    with TestSessionLocal() as db:
        db.add(Payment(invoice_id=iid, customer_id=cid, amount=paid))
        db.commit()

    history = client.get(f"/api/customers/{cid}/orders", headers=auth_headers)
    assert history.status_code == 200, history.text
    row = next(row for row in history.json() if row["id"] == oid)
    assert row["invoices"][0]["status"] == invoice_status
    assert row["payment_status"] == payment_status
    assert row["paid_total"] == float(paid)
    assert row["balance_due"] == float(outstanding_decimal)
    assert row["invoices"][0]["raw_paid_amount"] == float(paid)

    with TestSessionLocal() as db:
        assert invoice_paid_total(db, iid) == paid
        assert db.get(Invoice, iid).amount == Decimal("100.00")
        assert db.query(Payment).filter_by(customer_id=cid).count() == 1
