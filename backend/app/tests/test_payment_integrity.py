"""Payment status/allocation regressions; real row-lock tests opt in to local PostgreSQL."""

import os
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from queue import Queue
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import partners
from app.db.base import Base
from app.db.session import SessionLocal
from app.models import AuditLog, Customer, IdempotencyRecord, Invoice, Payment, SalesOrder
from app.services.payments import create_invoice_payment, invoice_paid_total


def _create_invoice(session_factory, amount=100):
    with session_factory() as db:
        customer = Customer(name=f"Payment integrity {uuid4().hex}")
        db.add(customer)
        db.flush()
        order = SalesOrder(order_no=f"PAY-{uuid4().hex}", customer_id=customer.id, total_amount=amount)
        db.add(order)
        db.flush()
        invoice = Invoice(
            sales_order_id=order.id, invoice_no=f"PAY-{uuid4().hex}", amount=amount, status="unpaid"
        )
        db.add(invoice)
        db.commit()
        return customer.id, order.id, invoice.id


@pytest.mark.parametrize(
    ("amounts", "expected_status"),
    [([Decimal("0.01")], "partially_paid"), ([40], "partially_paid"), ([100], "paid"), ([60, 40], "paid"), ([60, 60], "paid")],
)
def test_invoice_payment_status_matches_committed_sum(amounts, expected_status):
    customer_id, _, invoice_id = _create_invoice(SessionLocal)
    for amount in amounts:
        with SessionLocal() as db:
            payment = create_invoice_payment(db, db.get(Invoice, invoice_id), amount=amount, payment_method="cash")
            assert payment.customer_id == customer_id
            db.commit()
    with SessionLocal() as db:
        assert invoice_paid_total(db, invoice_id) == sum(amounts)
        assert db.get(Invoice, invoice_id).status == expected_status
        assert db.query(Payment).filter_by(invoice_id=invoice_id).count() == len(amounts)


def test_invoice_one_cent_short_remains_partially_paid():
    _, _, invoice_id = _create_invoice(SessionLocal, amount=100)
    with SessionLocal() as db:
        create_invoice_payment(db, db.get(Invoice, invoice_id), amount=Decimal("99.99"))
        db.commit()

    with SessionLocal() as db:
        invoice = db.get(Invoice, invoice_id)
        assert invoice_paid_total(db, invoice_id) == Decimal("99.99")
        assert invoice.status == "partially_paid"


def test_invoice_exact_cent_total_is_paid():
    _, _, invoice_id = _create_invoice(SessionLocal, amount=100)
    with SessionLocal() as db:
        create_invoice_payment(db, db.get(Invoice, invoice_id), amount=Decimal("99.99"))
        create_invoice_payment(db, db.get(Invoice, invoice_id), amount=Decimal("0.01"))
        db.commit()

    with SessionLocal() as db:
        assert invoice_paid_total(db, invoice_id) == Decimal("100.00")
        assert db.get(Invoice, invoice_id).status == "paid"


def test_invoice_payment_refreshes_cached_amount_before_status_calculation():
    _, _, invoice_id = _create_invoice(SessionLocal)
    with SessionLocal() as db:
        cached = db.get(Invoice, invoice_id)
        with SessionLocal() as other:
            other.get(Invoice, invoice_id).amount = 150
            other.commit()
        assert float(cached.amount) == 100

        create_invoice_payment(db, cached, amount=100)
        db.commit()

        assert float(cached.amount) == 150
        assert cached.status == "partially_paid"
        assert invoice_paid_total(db, invoice_id) == 100


def test_invoice_payment_lock_refresh_projects_only_status_fields():
    customer_id, _, invoice_id = _create_invoice(SessionLocal)
    statements = []
    with SessionLocal() as db:
        invoice = db.get(Invoice, invoice_id)
        legacy_sql = str(db.query(Invoice).statement.compile(dialect=db.bind.dialect)).lower()
        bind = db.get_bind()

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(bind, "before_cursor_execute", capture)
        try:
            payment = create_invoice_payment(db, invoice, amount=40, payment_method="cash")
            assert payment.customer_id == customer_id
            assert invoice.invoice_no.startswith("PAY-")
            assert invoice.status == "partially_paid"
        finally:
            event.remove(bind, "before_cursor_execute", capture)
        db.commit()

    invoice_reads = [statement for statement in statements if " from invoices " in statement]
    assert len(invoice_reads) == 1
    assert all(f"invoices.{column}" in invoice_reads[0] for column in (
        "id", "sales_order_id", "invoice_no", "amount", "status",
    ))
    assert "invoices.external_source" not in invoice_reads[0]
    assert "invoices.external_id" not in invoice_reads[0]
    assert "invoices.due_date" not in invoice_reads[0]
    assert "invoices.external_source" in legacy_sql
    assert "invoices.due_date" in legacy_sql


def test_customer_allocation_refreshes_cached_invoice_before_checking_balance():
    _, order_id, invoice_id = _create_invoice(SessionLocal)
    with SessionLocal() as db:
        create_invoice_payment(db, db.get(Invoice, invoice_id), amount=100)
        db.commit()
        cached = db.get(Invoice, invoice_id)
        with SessionLocal() as other:
            other.get(Invoice, invoice_id).amount = 150
            other.commit()
        assert float(cached.amount) == 100

        payable = partners._find_payable_invoice(db, db.get(SalesOrder, order_id))

        assert payable is cached
        assert float(payable.amount) == 150


def test_invoice_payment_rollback_allows_retry_without_duplicate():
    _, _, invoice_id = _create_invoice(SessionLocal)
    with SessionLocal() as db:
        create_invoice_payment(db, db.get(Invoice, invoice_id), amount=60)
        db.rollback()
        assert invoice_paid_total(db, invoice_id) == 0
        assert db.get(Invoice, invoice_id).status == "unpaid"
        create_invoice_payment(db, db.get(Invoice, invoice_id), amount=60)
        db.commit()
    with SessionLocal() as db:
        assert invoice_paid_total(db, invoice_id) == 60
        assert db.query(Payment).filter_by(invoice_id=invoice_id).count() == 1
        assert db.get(Invoice, invoice_id).status == "partially_paid"


def test_fully_paid_invoice_retry_replays_original_payment(client, auth_headers):
    _, _, invoice_id = _create_invoice(SessionLocal)
    headers = {**auth_headers, "Idempotency-Key": f"payment-integrity-{uuid4().hex}"}
    payload = {"invoice_id": invoice_id, "amount": 100, "payment_method": "cash"}

    first = client.post("/api/finance/payments", json=payload, headers=headers)
    retry = client.post("/api/finance/payments", json=payload, headers=headers)
    changed = client.post("/api/finance/payments", json={**payload, "amount": 60}, headers=headers)

    assert first.status_code == retry.status_code == 201
    assert retry.json() == first.json()
    assert changed.status_code == 409
    with SessionLocal() as db:
        assert db.query(Payment).filter_by(invoice_id=invoice_id).count() == 1
        assert invoice_paid_total(db, invoice_id) == 100
        assert db.get(Invoice, invoice_id).status == "paid"


@pytest.mark.parametrize("status", ["void", "cancelled"])
def test_manual_payment_rejects_terminal_invoice_without_writes(client, auth_headers, status):
    _, _, invoice_id = _create_invoice(SessionLocal)
    with SessionLocal() as db:
        db.get(Invoice, invoice_id).status = status
        db.commit()
        before = (
            db.query(Payment).count(),
            db.query(AuditLog).count(),
            db.query(IdempotencyRecord).count(),
        )

    response = client.post(
        "/api/finance/payments",
        json={"invoice_id": invoice_id, "amount": "0.01", "payment_method": "cash"},
        headers={**auth_headers, "Idempotency-Key": f"terminal-payment-{uuid4().hex}"},
    )

    assert response.status_code == 409, response.text
    with SessionLocal() as db:
        assert db.get(Invoice, invoice_id).status == status
        assert (
            db.query(Payment).count(),
            db.query(AuditLog).count(),
            db.query(IdempotencyRecord).count(),
        ) == before


@pytest.fixture(scope="module")
def payment_postgres_engine():
    """Create only payment tables/dependencies in a unique, disposable local schema.

    Set PAYMENT_INTEGRITY_POSTGRES_URL to a disposable loopback PostgreSQL URL.
    The shared conftest still owns SQLite; this separate engine tests real locks.
    """
    raw_url = os.environ.get("PAYMENT_INTEGRITY_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set PAYMENT_INTEGRITY_POSTGRES_URL for real PostgreSQL concurrency coverage")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Payment concurrency tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"payment_integrity_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"},
        pool_size=4,
        max_overflow=0,
        isolation_level="READ COMMITTED",
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        tables = {Invoice.__table__, Payment.__table__, AuditLog.__table__}
        pending = list(tables)
        while pending:
            for foreign_key in pending.pop().foreign_keys:
                target = foreign_key.column.table
                if target not in tables:
                    tables.add(target)
                    pending.append(target)
        Base.metadata.create_all(engine, tables=list(tables))
        yield engine
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def _concurrent_payments(engine, ids, amounts, *, customer_route):
    """Hold a compatible lock until both real transactions demonstrably wait.

    FOR NO KEY UPDATE allows the old service's payment FK inserts, but blocks
    its final invoice updates. Both old transactions therefore calculate stale
    status before either commits. The fixed code instead waits at FOR UPDATE
    before inserting/calculating, so each sees the preceding committed payment.
    """
    customer_id, order_id, invoice_id = ids
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    ready = Queue()
    start = Event()

    def pay(amount):
        with session_factory() as db:
            invoice = db.get(Invoice, invoice_id)
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            assert start.wait(10), "Payment workers were not started"
            if customer_route:
                return partners.create_customer_payment(
                    customer_id,
                    partners.CustomerPaymentIn(sales_order_id=order_id, amount=amount, payment_method="cash"),
                    db,
                    current=None,
                    idempotency_key=None,
                )
            payment = create_invoice_payment(db, invoice, amount=amount)
            db.commit()
            return payment.id

    with engine.connect() as holder, ThreadPoolExecutor(max_workers=2) as workers:
        holder.execute(
            text("SELECT id FROM invoices WHERE id = :id FOR NO KEY UPDATE"), {"id": invoice_id}
        )
        futures = [workers.submit(pay, amount) for amount in amounts]
        try:
            worker_pids = [ready.get(timeout=10) for _ in futures]
            start.set()
            deadline = monotonic() + 10
            while monotonic() < deadline:
                blocked = [
                    bool(holder.execute(text("SELECT pg_blocking_pids(:pid)"), {"pid": pid}).scalar_one())
                    for pid in worker_pids
                ]
                if all(blocked):
                    break
                sleep(0.02)
            else:
                pytest.fail("Both payment transactions must reach an actual PostgreSQL lock wait")
        finally:
            start.set()
            holder.rollback()
        return [future.result(timeout=10) for future in futures]


@pytest.mark.parametrize(
    ("amounts", "expected_status"),
    [((60, 60), "paid"), ((40, 60), "paid"), ((25, 35), "partially_paid")],
)
def test_postgres_concurrent_invoice_payments_keep_status_consistent(payment_postgres_engine, amounts, expected_status):
    session_factory = sessionmaker(bind=payment_postgres_engine, autoflush=False, expire_on_commit=False)
    ids = _create_invoice(session_factory)

    results = _concurrent_payments(payment_postgres_engine, ids, amounts, customer_route=False)

    assert len(set(results)) == 2
    with session_factory() as db:
        assert invoice_paid_total(db, ids[2]) == sum(amounts)
        assert db.query(Payment).filter_by(invoice_id=ids[2]).count() == 2
        assert db.get(Invoice, ids[2]).status == expected_status


@pytest.mark.parametrize("amounts", [(60, 60), (100, 100), (25, 35)])
def test_postgres_concurrent_customer_payments_preserve_advance_split(payment_postgres_engine, amounts):
    session_factory = sessionmaker(bind=payment_postgres_engine, autoflush=False, expire_on_commit=False)
    ids = _create_invoice(session_factory)

    _concurrent_payments(payment_postgres_engine, ids, amounts, customer_route=True)

    with session_factory() as db:
        total = sum(amounts)
        assert invoice_paid_total(db, ids[2]) == min(total, 100)
        advance = db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
            Payment.customer_id == ids[0], Payment.invoice_id.is_(None)
        ).scalar()
        assert float(advance) == max(total - 100, 0)
        assert db.get(Invoice, ids[2]).status == ("paid" if total >= 100 else "partially_paid")
