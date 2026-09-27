"""Invoice creation/replay regressions and opt-in PostgreSQL concurrency coverage."""

import os
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from queue import Queue
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import finance, sales
from app.db.base import Base
from app.db.session import SessionLocal
from app.models import AuditLog, Invoice, SalesOrder
from app.schemas.sales import InvoiceIn


def _create_order(session_factory, amount=100):
    with session_factory() as db:
        order = SalesOrder(order_no=f"INV-RACE-{uuid4().hex}", total_amount=amount)
        db.add(order)
        db.commit()
        return order.id


@pytest.mark.parametrize(("requested_amount", "expected_amount"), [(None, 100), (0, 0), (75.5, 75.5)])
def test_invoice_creation_and_retry_preserve_original_amount(client, auth_headers, requested_amount, expected_amount):
    order_id = _create_order(SessionLocal)
    payload = {"sales_order_id": order_id, "amount": requested_amount}

    first = client.post("/api/finance/invoices", json=payload, headers=auth_headers)
    retry = client.post("/api/finance/invoices", json={**payload, "amount": 999}, headers=auth_headers)

    assert first.status_code == retry.status_code == 201
    assert retry.json() == first.json()
    assert first.json()["amount"] == expected_amount
    assert first.json()["status"] == "unpaid"
    with SessionLocal() as db:
        assert db.query(Invoice).filter_by(sales_order_id=order_id).count() == 1
        assert db.query(AuditLog).filter_by(entity_type="Invoice", entity_id=first.json()["id"]).count() == 1


def test_invoice_creation_refreshes_cached_order_amount():
    order_id = _create_order(SessionLocal)
    with SessionLocal() as db:
        cached = db.get(SalesOrder, order_id)
        with SessionLocal() as other:
            other.get(SalesOrder, order_id).total_amount = 150
            other.commit()
        assert float(cached.total_amount) == 100

        invoice = finance.create_invoice(InvoiceIn(sales_order_id=order_id), db, current=None)

        assert float(invoice.amount) == 150
        assert float(cached.total_amount) == 150


def test_invoice_creation_unknown_order_keeps_404(client, auth_headers):
    response = client.post("/api/finance/invoices", json={"sales_order_id": 2_000_000_000}, headers=auth_headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "Sales order not found"


@pytest.mark.parametrize("amount", ["1.001", "0.009", "1.2301", "1.00000000000000001"])
def test_manual_invoice_rejects_subcent_amount_without_writes(client, auth_headers, amount):
    order_id = _create_order(SessionLocal)
    with SessionLocal() as db:
        audit_count = db.query(AuditLog).filter_by(entity_type="Invoice").count()

    response = client.post(
        "/api/finance/invoices",
        json={"sales_order_id": order_id, "amount": amount},
        headers=auth_headers,
    )

    assert response.status_code == 422
    with SessionLocal() as db:
        assert db.query(Invoice).filter_by(sales_order_id=order_id).count() == 0
        assert db.query(AuditLog).filter_by(entity_type="Invoice").count() == audit_count


def test_manual_invoice_subcent_check_preserves_auth_order_and_replay_precedence(client, auth_headers):
    order_id = _create_order(SessionLocal)
    rejected_without_auth = client.post(
        "/api/finance/invoices", json={"sales_order_id": order_id, "amount": "1.001"}
    )
    missing_order = client.post(
        "/api/finance/invoices",
        json={"sales_order_id": 2_000_000_000, "amount": "1.001"},
        headers=auth_headers,
    )
    assert rejected_without_auth.status_code == 401
    assert missing_order.status_code == 404

    first = client.post(
        "/api/finance/invoices", json={"sales_order_id": order_id, "amount": "4.25"}, headers=auth_headers
    )
    replay = client.post(
        "/api/finance/invoices", json={"sales_order_id": order_id, "amount": "1.001"}, headers=auth_headers
    )
    assert first.status_code == replay.status_code == 201
    assert replay.json() == first.json()


def test_manual_invoice_accepts_exact_decimal_cents_without_float_conversion(client, auth_headers):
    order_id = _create_order(SessionLocal)
    response = client.post(
        "/api/finance/invoices",
        json={"sales_order_id": order_id, "amount": "999999999999.99"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["amount"] == 999999999999.99
    with SessionLocal() as db:
        assert db.get(Invoice, response.json()["id"]).amount == Decimal("999999999999.99")


def test_sales_invoice_creation_replays_via_both_endpoints(client, auth_headers):
    order_id = _create_order(SessionLocal)
    with SessionLocal() as db:
        db.get(SalesOrder, order_id).status = "confirmed"
        db.commit()
    first = client.post(f"/api/sales-orders/{order_id}/generate-invoice", headers=auth_headers)
    repeated = client.post(f"/api/sales-orders/{order_id}/generate-invoice", headers=auth_headers)
    alternate = client.post("/api/finance/invoices", headers=auth_headers, json={"sales_order_id": order_id})
    assert first.status_code == repeated.status_code == 200
    assert alternate.status_code == 201
    assert first.json()["id"] == repeated.json()["id"] == alternate.json()["id"]
    assert first.json()["created_existing"] is False
    assert repeated.json()["created_existing"] is True


def test_sales_invoice_creation_refreshes_cached_amount_and_state():
    order_id = _create_order(SessionLocal)
    with SessionLocal() as db:
        cached = db.get(SalesOrder, order_id)
        with SessionLocal() as other:
            order = other.get(SalesOrder, order_id)
            order.status = "confirmed"
            order.total_amount = 150
            other.commit()
        assert cached.status == "draft"
        result = sales.generate_invoice_for_order(order_id, db, current=None)
        assert result["amount"] == 150
        assert cached.status == "confirmed"


def test_invoice_creation_rollback_can_retry(monkeypatch):
    order_id = _create_order(SessionLocal)
    original_log_action = finance.log_action

    def reject_audit(*args, **kwargs):
        raise RuntimeError("Synthetic failure after invoice insert")

    with SessionLocal() as db:
        monkeypatch.setattr(finance, "log_action", reject_audit)
        with pytest.raises(RuntimeError, match="Synthetic failure"):
            finance.create_invoice(InvoiceIn(sales_order_id=order_id), db, current=None)
        db.rollback()
        assert db.query(Invoice).filter_by(sales_order_id=order_id).count() == 0
        monkeypatch.setattr(finance, "log_action", original_log_action)

        invoice = finance.create_invoice(InvoiceIn(sales_order_id=order_id), db, current=None)

        assert db.query(Invoice).filter_by(sales_order_id=order_id).count() == 1
        assert db.query(AuditLog).filter_by(entity_type="Invoice", entity_id=invoice.id).count() == 1


@pytest.fixture(scope="module")
def invoice_postgres_engine():
    """Keep all synthetic records in a new schema on an explicitly local server."""
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL concurrency coverage")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Invoice concurrency tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"invoice_creation_{uuid4().hex}"
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
        tables = {Invoice.__table__, AuditLog.__table__}
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


@pytest.mark.parametrize("requested_amounts", [(None, None), (70, 90)])
@pytest.mark.parametrize("entrypoints", [("finance", "finance"), ("sales", "sales"), ("finance", "sales")])
def test_postgres_concurrent_invoice_creation_returns_one_invoice(invoice_postgres_engine, requested_amounts, entrypoints):
    """Old callers both pass existence checking before their numbering lock wait.

    Holding the order and numbering locks forces both old and new implementations
    to overlap. Old callers wait at numbering after reading no invoice; fixed
    callers wait at the order lock and check existence only after acquiring it.
    """
    session_factory = sessionmaker(bind=invoice_postgres_engine, autoflush=False, expire_on_commit=False)
    order_id = _create_order(session_factory)
    with session_factory() as db:
        db.get(SalesOrder, order_id).status = "confirmed"
        db.commit()
    ready = Queue()
    start = Event()

    def create(amount, entrypoint):
        with session_factory() as db:
            cached = db.get(SalesOrder, order_id)
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            assert start.wait(10), "Invoice workers were not started"
            if entrypoint == "sales":
                result = sales.generate_invoice_for_order(order_id, db, current=None)
                invoice = db.get(Invoice, result["id"])
            else:
                invoice = finance.create_invoice(InvoiceIn(sales_order_id=order_id, amount=amount), db, current=None)
            assert cached.id == order_id
            return invoice.id, invoice.invoice_no, float(invoice.amount)

    with session_factory() as holder, ThreadPoolExecutor(max_workers=2) as workers:
        holder.execute(text("SELECT id FROM sales_orders WHERE id = :id FOR UPDATE"), {"id": order_id})
        # Use the real numbering function to hold exactly the application's lock.
        finance.next_invoice_no(holder)
        futures = [workers.submit(create, amount, entrypoint) for amount, entrypoint in zip(requested_amounts, entrypoints)]
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
                pytest.fail("Both invoice transactions must reach an actual PostgreSQL lock wait")
        finally:
            start.set()
            holder.rollback()
        results = [future.result(timeout=10) for future in futures]

    assert results[0] == results[1]
    assert results[0][2] in {
        100 if amount is None or entrypoint == "sales" else amount
        for amount, entrypoint in zip(requested_amounts, entrypoints)
    }
    with session_factory() as db:
        assert db.query(Invoice).filter_by(sales_order_id=order_id).count() == 1
        assert db.query(AuditLog).filter_by(entity_type="Invoice", entity_id=results[0][0]).count() == 1
