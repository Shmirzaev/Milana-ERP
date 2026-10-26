"""Customer auto-issuance must share the Finance/Sales parent-order lock.

Real PostgreSQL only: SQLite cannot prove row-lock serialization. Gates pause
real operations, and pg_blocking_pids proves the contender reached a database
lock before release. No query result or application policy is mocked.
"""
import os
import threading
import time
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.libs.dto.sales.customer_payment_input import CustomerPaymentIn
from app.libs.dto.sales.invoice_input import InvoiceIn
from app.models.finance import customer_ledger_service as ledger
from app.models.finance import invoices_service as issuance
from app.models.idempotency_service import bind_idempotency_identity
from app.schemas import AuditLog, Customer, IdempotencyRecord, Invoice, Payment, SalesOrder, User


@pytest.fixture(scope="module")
def receipt_race_sessions():
    url = os.environ.get("FN04_TEST_PG_ADMIN_URL")
    if not url:
        pytest.skip("Set FN04_TEST_PG_ADMIN_URL for the required PostgreSQL race checks")
    parsed = make_url(url)
    # Never create/drop databases on a non-local server or use an application DB.
    assert parsed.host in {"127.0.0.1", "localhost"} and parsed.database == "postgres"
    database = "review_receipt_invoice_" + uuid4().hex
    admin = create_engine(parsed, isolation_level="AUTOCOMMIT")
    engine = None
    created = False
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f'CREATE DATABASE "{database}"')
        created = True
        engine = create_engine(
            parsed.set(database=database),
            connect_args={"options": "-cstatement_timeout=20000 -clock_timeout=10000"},
        )
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            with admin.connect() as conn:
                conn.exec_driver_sql(f'DROP DATABASE "{database}" WITH (FORCE)')
        admin.dispose()


@pytest.fixture
def receipt_order(receipt_race_sessions):
    with receipt_race_sessions() as db:
        actor = User(name="Receipt race test", email=f"{uuid4().hex}@example.invalid", password_hash="unused")
        customer = Customer(name="Receipt race test")
        db.add_all([actor, customer])
        db.flush()
        order = SalesOrder(order_no=f"RACE-{uuid4().hex}", customer_id=customer.id,
                           status="confirmed", total_amount=Decimal("100.00"))
        db.add(order)
        db.commit()
        return order.id, customer.id, actor.id


def _manual(db, entry, ids):
    oid, _, uid = ids
    actor = db.get(User, uid)
    if entry == "finance":
        return issuance.create_order_invoice(db, InvoiceIn(sales_order_id=oid), actor).id
    return issuance.generate_order_invoice(db, oid, actor)["id"]


def _receipt(db, ids, amount="25.00", key=None):
    oid, cid, uid = ids
    actor = db.get(User, uid)
    bind_idempotency_identity(db, actor)
    return ledger.record_customer_payment(
        db, cid, CustomerPaymentIn(sales_order_id=oid, amount=Decimal(amount),
                                  payment_method="review-custom-text"), actor, key,
    )


def _assert_ledger(sessions, ids, invoice_audit):
    oid, cid, _ = ids
    with sessions() as db:
        invoices = db.query(Invoice).filter_by(sales_order_id=oid).all()
        assert len(invoices) == 1
        inv = invoices[0]
        assert inv.amount == Decimal("100.00")
        assert inv.status.value == "partially_paid"
        payments = db.query(Payment).filter_by(customer_id=cid).all()
        assert len(payments) == 1
        payment = payments[0]
        assert payment.invoice_id == inv.id and payment.amount == Decimal("25.00")
        assert payment.payment_method == "review-custom-text"
        assert payment.customer_id == cid
        assert not db.query(Payment).filter_by(customer_id=cid, invoice_id=None).count()
        assert not db.query(IdempotencyRecord).filter_by(user_id=ids[2]).count()
        audits = db.query(AuditLog).filter(
            ((AuditLog.entity_type == "Invoice") & (AuditLog.entity_id == inv.id)) |
            ((AuditLog.entity_type == "Payment") & (AuditLog.entity_id == payment.id)),
        ).order_by(AuditLog.id).all()
        # Auto-issuance historically audits the receipt only. Manual issuance
        # first produces its own Invoice audit, then the Payment audit.
        expected = [("Invoice", invoice_audit)] if invoice_audit else []
        expected += [("Payment", "create")]
        assert [(row.entity_type, row.action) for row in audits] == expected
        assert all(row.entry_hash for row in audits)
        return inv.id


class _GateSession(Session):
    def __init__(self, *args, reached, release, **kwargs):
        super().__init__(*args, **kwargs)
        self.reached, self.release = reached, release

    def commit(self):
        self.reached.set()
        assert self.release.wait(15), "First operation commit gate timed out"
        return super().commit()


def _wait_for_block(sessions, waiter, holder):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with sessions() as db:
            blockers = db.execute(text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter}).scalar_one()
            if holder in blockers:
                return
        threading.Event().wait(0.02)
    pytest.fail("Contender did not reach the first operation's PostgreSQL lock")


@pytest.mark.parametrize("entry", ["finance", "sales"])
def test_manual_then_receipt_preserves_original_control(receipt_race_sessions, receipt_order, entry):
    with receipt_race_sessions() as db:
        issued = _manual(db, entry, receipt_order)
    with receipt_race_sessions() as db:
        paid = _receipt(db, receipt_order)
    assert paid["invoice_id"] == issued
    assert _assert_ledger(receipt_race_sessions, receipt_order,
                          "create" if entry == "finance" else "generate_invoice") == issued


@pytest.mark.parametrize("entry", ["finance", "sales"])
@pytest.mark.parametrize("winner", ["receipt", "manual"])
def test_receipt_and_manual_issuance_share_one_invoice(receipt_race_sessions, receipt_order, entry, winner):
    sessions = receipt_race_sessions
    reached, release, second_started = threading.Event(), threading.Event(), threading.Event()
    results, errors, pids = {}, {}, {}

    def run(role):
        try:
            if role == winner:
                db = _GateSession(bind=sessions.kw["bind"], autoflush=False, expire_on_commit=False,
                                  reached=reached, release=release)
            else:
                db = sessions()
            with db:
                pids[role] = db.execute(text("SELECT pg_backend_pid()")).scalar_one()
                if role != winner:
                    second_started.set()
                results[role] = _receipt(db, receipt_order) if role == "receipt" else _manual(db, entry, receipt_order)
        except BaseException as exc:
            errors[role] = exc

    loser = "manual" if winner == "receipt" else "receipt"
    first, second = threading.Thread(target=run, args=(winner,)), threading.Thread(target=run, args=(loser,))
    try:
        first.start()
        assert reached.wait(10), errors
        second.start()
        assert second_started.wait(10), errors
        _wait_for_block(sessions, pids[loser], pids[winner])
    finally:
        release.set()
        first.join(15)
        if second.ident is not None:
            second.join(15)
    assert not first.is_alive() and not second.is_alive(), "Operations did not release locks"
    assert not errors, errors
    assert results["receipt"]["invoice_id"] == results["manual"]
    audit = ("create" if entry == "finance" else "generate_invoice") if winner == "manual" else None
    assert _assert_ledger(sessions, receipt_order, audit) == results["manual"]


@pytest.mark.parametrize("entry", ["finance", "sales"])
@pytest.mark.parametrize("amount", ["25.00", "125.00"])
def test_receipt_failure_rolls_back_participants_and_releases_order(
    receipt_race_sessions, receipt_order, monkeypatch, entry, amount,
):
    sessions = receipt_race_sessions
    reached, release, second_started = threading.Event(), threading.Event(), threading.Event()
    original_store = ledger.store_idempotent_response
    errors, results, pids = {}, {}, {}
    key = f"rollback-{uuid4().hex}"

    def fail_after_retry_record(db, **kwargs):
        original_store(db, **kwargs)

        def fail_before_commit(session):
            # log_action installed its before_commit hook before this listener.
            # Verify every participant, including the real finalized audit row,
            # has been flushed, then fail before the database transaction commits.
            assert session.query(IdempotencyRecord).filter_by(key=key).count() == 1
            audits = session.query(AuditLog).filter_by(user_id=receipt_order[2]).all()
            assert len(audits) == 1 and audits[0].entry_hash
            expected_payments = 2 if amount == "125.00" else 1
            assert session.query(Payment).filter_by(customer_id=receipt_order[1]).count() == expected_payments
            reached.set()
            assert release.wait(15)
            raise RuntimeError("injected after receipt participants")

        event.listen(db, "before_commit", fail_before_commit)

    monkeypatch.setattr(ledger, "store_idempotent_response", fail_after_retry_record)

    def receive():
        with sessions() as db:
            try:
                pids["receipt"] = db.execute(text("SELECT pg_backend_pid()")).scalar_one()
                _receipt(db, receipt_order, amount, key)
            except BaseException as exc:
                db.rollback()
                errors["receipt"] = exc

    def issue():
        try:
            with sessions() as db:
                pids["manual"] = db.execute(text("SELECT pg_backend_pid()")).scalar_one()
                second_started.set()
                results["manual"] = _manual(db, entry, receipt_order)
        except BaseException as exc:
            errors["manual"] = exc

    first, second = threading.Thread(target=receive), threading.Thread(target=issue)
    try:
        first.start()
        assert reached.wait(10), errors
        second.start()
        assert second_started.wait(10), errors
        _wait_for_block(sessions, pids["manual"], pids["receipt"])
    finally:
        release.set()
        first.join(15)
        if second.ident is not None:
            second.join(15)
    assert not first.is_alive() and not second.is_alive()
    assert set(errors) == {"receipt"}
    assert str(errors["receipt"]) == "injected after receipt participants"
    oid, cid, uid = receipt_order
    with sessions() as db:
        invoices = db.query(Invoice).filter_by(sales_order_id=oid).all()
        assert len(invoices) == 1 and invoices[0].id == results["manual"]
        assert invoices[0].amount == Decimal("100.00") and invoices[0].status.value == "unpaid"
        assert db.query(Payment).filter_by(customer_id=cid).count() == 0
        assert db.query(IdempotencyRecord).filter_by(key=key).count() == 0
        audits = db.query(AuditLog).filter_by(user_id=uid).all()
        assert len(audits) == 1 and audits[0].entity_type == "Invoice"
        assert audits[0].action == ("create" if entry == "finance" else "generate_invoice")
        assert audits[0].entry_hash
