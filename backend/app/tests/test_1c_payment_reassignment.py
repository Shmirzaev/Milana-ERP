import os
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import Customer, Invoice, Payment, SalesOrder
from app.schemas.integrations import OneCSyncIn
from app.services import finance_1c
from app.services.finance_1c import sync_from_1c
from app.services.payments import create_invoice_payment, invoice_paid_total
from app.tests.conftest import TestSessionLocal


def _invoices(session_factory, count=3):
    marker = uuid4().hex[:12]
    with session_factory() as db:
        customer = Customer(name=f"1C reassignment {marker}")
        db.add(customer)
        db.flush()
        order = SalesOrder(order_no=f"REASSIGN-{marker}", customer_id=customer.id, total_amount=300)
        db.add(order)
        db.flush()
        invoices = [Invoice(
            invoice_no=f"REASSIGN-{marker}-{index}", sales_order_id=order.id, amount=100,
            status="paid" if index == 0 else "unpaid", external_source="1c", external_id=f"invoice-{marker}-{index}",
        ) for index in range(count)]
        db.add_all(invoices)
        db.flush()
        payment = Payment(invoice_id=invoices[0].id, external_source="1c", external_id=f"payment-{marker}", amount=100)
        db.add(payment)
        db.commit()
        return {
            "invoices": [invoice.id for invoice in invoices], "payment_id": payment.id,
            "external_id": payment.external_id, "customer_id": customer.id, "order_id": order.id,
            "invoice_nos": [invoice.invoice_no for invoice in invoices],
            "invoice_external_ids": [invoice.external_id for invoice in invoices],
        }


def _payment_row(ids, target=1, amount=100, **overrides):
    return {"external_id": ids["external_id"], "invoice_id": ids["invoices"][target], "amount": amount, **overrides}


def _assert_invoices(session_factory, ids, totals, statuses):
    with session_factory() as db:
        assert [invoice_paid_total(db, invoice_id) for invoice_id in ids["invoices"]] == totals
        assert [db.get(Invoice, invoice_id).status for invoice_id in ids["invoices"]] == statuses
        payments = db.query(Payment).filter_by(external_source="1c", external_id=ids["external_id"]).all()
        assert len(payments) == 1
        assert payments[0].id == ids["payment_id"]


@pytest.mark.parametrize("reference", ["invoice_id", "invoice_no", "invoice_external_id"])
def test_1c_payment_move_refreshes_both_invoice_statuses(client, reference):
    ids = _invoices(TestSessionLocal)
    target = {
        "invoice_id": ids["invoices"][1], "invoice_no": ids["invoice_nos"][1],
        "invoice_external_id": ids["invoice_external_ids"][1],
    }[reference]
    response = client.post("/api/finance/integrations/1c/sync", headers={"X-1C-Token": "test-1c-token"}, json={
        "payments": [{"external_id": ids["external_id"], reference: target, "amount": 100}],
    })
    assert response.status_code == 200, response.text
    assert response.json()["payments_updated"] == 1
    assert response.json()["payments_created"] == 0
    assert response.json()["errors"] == []
    _assert_invoices(TestSessionLocal, ids, [0, 100, 0], ["unpaid", "paid", "unpaid"])
    with TestSessionLocal() as db:
        assert db.get(Payment, ids["payment_id"]).invoice_id == ids["invoices"][1]


@pytest.mark.parametrize(("amount", "new_status"), [(40, "partially_paid"), (120, "paid")])
def test_reassignment_with_amount_change_preserves_other_payments_and_advances(amount, new_status):
    ids = _invoices(TestSessionLocal)
    with TestSessionLocal() as db:
        db.add_all([
            Payment(invoice_id=ids["invoices"][0], amount=30),
            Payment(invoice_id=ids["invoices"][1], amount=20),
            Payment(customer_id=ids["customer_id"], invoice_id=None, amount=13),
        ])
        db.commit()
        summary = sync_from_1c(db, OneCSyncIn(payments=[_payment_row(ids, amount=amount)]))
        assert summary["errors"] == []
        db.commit()
        advance = db.query(Payment).filter_by(customer_id=ids["customer_id"], invoice_id=None).one()
        assert float(advance.amount) == 13
        assert db.query(Payment).count() >= 4
    _assert_invoices(TestSessionLocal, ids, [30, amount + 20, 0], ["partially_paid", new_status, "unpaid"])


def test_same_invoice_amount_update_and_move_back_keep_one_payment():
    ids = _invoices(TestSessionLocal)
    for target, amount, totals, statuses in [
        (0, 60, [60, 0, 0], ["partially_paid", "unpaid", "unpaid"]),
        (1, 40, [0, 40, 0], ["unpaid", "partially_paid", "unpaid"]),
        (0, 75, [75, 0, 0], ["partially_paid", "unpaid", "unpaid"]),
    ]:
        with TestSessionLocal() as db:
            summary = sync_from_1c(db, OneCSyncIn(payments=[_payment_row(ids, target, amount)]))
            assert summary["payments_updated"] == 1 and summary["errors"] == []
            db.commit()
        _assert_invoices(TestSessionLocal, ids, totals, statuses)


def test_invalid_new_invoice_reference_does_not_change_payment_or_old_status(client):
    ids = _invoices(TestSessionLocal)
    response = client.post("/api/finance/integrations/1c/sync", headers={"X-1C-Token": "test-1c-token"}, json={
        "payments": [_payment_row(ids, invoice_id=2**40, amount=40)],
    })
    assert response.status_code == 200, response.text
    assert response.json()["payments_updated"] == 0
    assert len(response.json()["errors"]) == 1
    assert "invoice not found" in response.json()["errors"][0]["error"]
    _assert_invoices(TestSessionLocal, ids, [100, 0, 0], ["paid", "unpaid", "unpaid"])


def test_reassignment_removes_old_foreign_key_without_deleting_payment():
    ids = _invoices(TestSessionLocal)
    with TestSessionLocal() as db:
        assert sync_from_1c(db, OneCSyncIn(payments=[_payment_row(ids)]))["errors"] == []
        db.commit()
        assert db.query(Payment).filter_by(invoice_id=ids["invoices"][0]).count() == 0
        db.delete(db.get(Invoice, ids["invoices"][0]))
        db.commit()
        payment = db.get(Payment, ids["payment_id"])
        assert payment.invoice_id == ids["invoices"][1]
        assert float(payment.amount) == 100


@pytest.mark.parametrize("reverse", [False, True])
def test_multi_payment_swap_is_independent_of_input_order(reverse):
    ids = _invoices(TestSessionLocal)
    second_key = f"second-{ids['external_id']}"
    with TestSessionLocal() as db:
        db.add(Payment(invoice_id=ids["invoices"][1], amount=50, external_source="1c", external_id=second_key))
        db.get(Invoice, ids["invoices"][1]).status = "partially_paid"
        db.commit()
        rows = [_payment_row(ids, target=1, amount=25), _payment_row(ids, target=0, amount=75, external_id=second_key)]
        summary = sync_from_1c(db, OneCSyncIn(payments=list(reversed(rows)) if reverse else rows))
        assert summary["payments_updated"] == 2 and summary["errors"] == []
        db.commit()
    _assert_invoices(TestSessionLocal, ids, [75, 25, 0], ["partially_paid", "partially_paid", "unpaid"])


@pytest.mark.parametrize("new_invoice", [False, True])
def test_invoice_import_in_same_batch_preserves_changed_amount_and_reference(new_invoice):
    ids = _invoices(TestSessionLocal)
    external_id = f"new-{ids['external_id']}" if new_invoice else ids["invoice_external_ids"][1]
    invoice_no = f"NEW-REFERENCE-{uuid4().hex[:12]}"
    with TestSessionLocal() as db:
        summary = sync_from_1c(db, OneCSyncIn(
            invoices=[{"external_id": external_id, "invoice_no": invoice_no,
                       "sales_order_id": ids["order_id"], "amount": 150}],
            payments=[{"external_id": ids["external_id"], "invoice_no": invoice_no, "amount": 100}],
        ))
        assert summary["errors"] == []
        db.commit()
        invoice = db.query(Invoice).filter_by(external_source="1c", external_id=external_id).one()
        assert float(invoice.amount) == 150 and invoice.status == "partially_paid"
        assert db.get(Payment, ids["payment_id"]).invoice_id == invoice.id
        assert db.get(Invoice, ids["invoices"][0]).status == "unpaid"


def test_reassignment_caller_rollback_restores_association_and_both_statuses():
    ids = _invoices(TestSessionLocal)
    with TestSessionLocal() as db:
        assert sync_from_1c(db, OneCSyncIn(payments=[_payment_row(ids)]))["errors"] == []
        db.rollback()
    _assert_invoices(TestSessionLocal, ids, [100, 0, 0], ["paid", "unpaid", "unpaid"])


def test_existing_unallocated_payment_can_be_assigned_without_other_advance_changes():
    ids = _invoices(TestSessionLocal)
    with TestSessionLocal() as db:
        payment = db.get(Payment, ids["payment_id"])
        payment.invoice_id = None
        payment.customer_id = ids["customer_id"]
        db.get(Invoice, ids["invoices"][0]).status = "unpaid"
        db.commit()
        assert sync_from_1c(db, OneCSyncIn(payments=[_payment_row(ids)]))["errors"] == []
        db.commit()
        assert payment.customer_id == ids["customer_id"]
    _assert_invoices(TestSessionLocal, ids, [0, 100, 0], ["unpaid", "paid", "unpaid"])


def test_repeated_payment_within_batch_clears_intermediate_invoice():
    ids = _invoices(TestSessionLocal)
    with TestSessionLocal() as db:
        summary = sync_from_1c(db, OneCSyncIn(payments=[_payment_row(ids, 1), _payment_row(ids, 2)]))
        assert summary["payments_updated"] == 2 and summary["errors"] == []
        db.commit()
    _assert_invoices(TestSessionLocal, ids, [0, 0, 100], ["unpaid", "unpaid", "paid"])


@pytest.fixture(scope="module")
def reassignment_postgres_engine():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL 1C reassignment races")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("1C reassignment races require loopback PostgreSQL without connection overrides")
    schema = f"payment_reassignment_{uuid4().hex}"
    engine = create_engine(
        url, connect_args={"options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"},
        pool_size=4, max_overflow=0, isolation_level="READ COMMITTED",
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        tables = {Payment.__table__}
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


def _wait_for_lock(observer, pids):
    deadline = monotonic() + 10
    while monotonic() < deadline:
        if all(bool(observer.execute(text("SELECT pg_blocking_pids(:pid)"), {"pid": pid}).scalar_one()) for pid in pids):
            return
        sleep(0.02)
    pytest.fail("Payment workers must reach real PostgreSQL lock waits")


@pytest.mark.parametrize("manual_target", [0, 1], ids=["old-invoice", "new-invoice"])
def test_postgres_reassignment_serializes_with_manual_invoice_payments(reassignment_postgres_engine, monkeypatch, manual_target):
    engine = reassignment_postgres_engine
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    ids = _invoices(session_factory)
    refreshed = Event()
    release = Event()
    ready = Queue()
    original_refresh = finance_1c._refresh_invoice_status

    def gated_refresh(db, invoice):
        original_refresh(db, invoice)
        if not refreshed.is_set():
            refreshed.set()
            assert release.wait(15), "Reassignment was not released"

    monkeypatch.setattr(finance_1c, "_refresh_invoice_status", gated_refresh)

    def reassign():
        with session_factory() as db:
            result = sync_from_1c(db, OneCSyncIn(payments=[_payment_row(ids, amount=60)]))
            db.commit()
            return result

    def manual():
        with session_factory() as db:
            cached = db.get(Invoice, ids["invoices"][manual_target])
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            create_invoice_payment(db, cached, amount=60)
            db.commit()

    with ThreadPoolExecutor(max_workers=2) as workers:
        moved = workers.submit(reassign)
        paid = None
        try:
            assert refreshed.wait(10), "Reassignment did not reach invoice status refresh"
            paid = workers.submit(manual)
            with engine.connect() as observer:
                _wait_for_lock(observer, [ready.get(timeout=10)])
        finally:
            release.set()
        assert moved.result(timeout=10)["errors"] == []
        assert paid is not None
        paid.result(timeout=10)
    _assert_invoices(session_factory, ids,
                     [60, 60, 0] if manual_target == 0 else [0, 120, 0],
                     ["partially_paid", "partially_paid", "unpaid"] if manual_target == 0 else ["unpaid", "paid", "unpaid"])


@pytest.mark.parametrize("reverse_second", [False, True])
def test_postgres_multi_payment_batches_lock_all_invoice_pairs_in_order(reassignment_postgres_engine, reverse_second):
    engine = reassignment_postgres_engine
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    ids = _invoices(session_factory, count=4)
    keys = [ids["external_id"], *[f"other-{index}-{ids['external_id']}" for index in (1, 2, 3)]]
    with session_factory() as db:
        for index, amount in [(1, 50), (2, 40), (3, 20)]:
            db.add(Payment(invoice_id=ids["invoices"][index], amount=amount, external_source="1c", external_id=keys[index]))
            db.get(Invoice, ids["invoices"][index]).status = "partially_paid"
        db.commit()
    batches = [
        [_payment_row(ids, target=2, amount=70), _payment_row(ids, target=3, amount=30, external_id=keys[1])],
        [_payment_row(ids, target=0, amount=80, external_id=keys[2]), _payment_row(ids, target=1, amount=20, external_id=keys[3])],
    ]
    if reverse_second:
        batches[1].reverse()
    ready = Queue()
    start = Event()

    def run(rows):
        with session_factory() as db:
            cached = [db.get(Invoice, invoice_id) for invoice_id in ids["invoices"]]
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            assert start.wait(10)
            result = sync_from_1c(db, OneCSyncIn(payments=rows))
            assert len(cached) == 4
            db.commit()
            return result

    with engine.connect() as holder, ThreadPoolExecutor(max_workers=2) as workers:
        holder.execute(text("SELECT id FROM invoices WHERE id = :id FOR UPDATE"), {"id": ids["invoices"][0]})
        futures = [workers.submit(run, rows) for rows in batches]
        try:
            pids = [ready.get(timeout=10) for _ in futures]
            start.set()
            _wait_for_lock(holder, pids)
        finally:
            start.set()
            holder.rollback()
        assert all(future.result(timeout=10)["errors"] == [] for future in futures)
    _assert_invoices(session_factory, ids, [80, 20, 70, 30], ["partially_paid"] * 4)


def test_postgres_reassignment_releases_old_invoice_foreign_key(reassignment_postgres_engine):
    session_factory = sessionmaker(bind=reassignment_postgres_engine, autoflush=False, expire_on_commit=False)
    ids = _invoices(session_factory)
    with session_factory() as db:
        assert sync_from_1c(db, OneCSyncIn(payments=[_payment_row(ids)]))["errors"] == []
        db.commit()
        db.delete(db.get(Invoice, ids["invoices"][0]))
        db.commit()
        payment = db.get(Payment, ids["payment_id"])
        assert payment.invoice_id == ids["invoices"][1] and float(payment.amount) == 100


def test_postgres_existing_payment_moves_reread_previous_invoice_after_wait(reassignment_postgres_engine):
    engine = reassignment_postgres_engine
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    ids = _invoices(session_factory)
    ready = Queue()
    start = Event()

    def move(target):
        with session_factory() as db:
            cached = db.get(Payment, ids["payment_id"])
            assert cached.invoice_id == ids["invoices"][0]
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            assert start.wait(10)
            summary = sync_from_1c(db, OneCSyncIn(payments=[_payment_row(ids, target)]))
            db.commit()
            return summary

    with engine.connect() as holder, ThreadPoolExecutor(max_workers=2) as workers:
        holder.execute(text("SELECT id FROM payments WHERE id = :id FOR UPDATE"), {"id": ids["payment_id"]})
        futures = [workers.submit(move, target) for target in (1, 2)]
        try:
            pids = [ready.get(timeout=10) for _ in futures]
            start.set()
            _wait_for_lock(holder, pids)
        finally:
            start.set()
            holder.rollback()
        assert all(future.result(timeout=10)["errors"] == [] for future in futures)
    with session_factory() as db:
        final_invoice = db.get(Payment, ids["payment_id"]).invoice_id
    assert final_invoice in ids["invoices"][1:]
    _assert_invoices(session_factory, ids,
                     [100 if invoice_id == final_invoice else 0 for invoice_id in ids["invoices"]],
                     ["paid" if invoice_id == final_invoice else "unpaid" for invoice_id in ids["invoices"]])
