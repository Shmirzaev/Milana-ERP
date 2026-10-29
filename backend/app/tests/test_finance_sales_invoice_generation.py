"""Sales invoice generation: typed result, schema-owned write, one transaction.

The sales entry point is the second issuer of a sales-order invoice. These
assertions pin the contract it returns, the write it uses and the transaction
it owns. The PostgreSQL-only cases prove what SQLite cannot: row-lock
serialization of two issuers and the rollback residue of a failed issuance.

The PostgreSQL fixture uses an approved instance and an owned disposable
database, checking the actual connections before use and cleaning up its target.
"""
import threading
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event, text

from app.db.base import Base
from app.db.session import SessionLocal
from app.libs.dto.sales.invoice_generation_output import InvoiceGenerationOut
from app.libs.dto.sales.invoice_input import InvoiceIn
from app.libs.enums.finance import InvoiceStatus
from app.models.finance import invoices_service as issuance
from app.schemas import AuditLog, Invoice, SalesOrder, User
from app.tests.test_customer_invoice_creation_race import _GateSession, _wait_for_block

from app.tests.pg_approved_instance import (
    ApprovedInstanceUnavailable, create_target_database, finalize_target,
    load_approved_instance, require_or_skip, target_engine,
)


@pytest.fixture(scope="module")
def owned_pg_sessions():
    """Create and clean up exactly one approved, guarded PostgreSQL target."""
    try:
        instance = load_approved_instance()
    except ApprovedInstanceUnavailable as error:
        require_or_skip(error)
    target = create_target_database(instance)
    engine = None
    try:
        engine = target_engine(target, options="-cstatement_timeout=20000 -clock_timeout=10000")
        Base.metadata.create_all(engine)
        from sqlalchemy.orm import sessionmaker

        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        finalize_target(target, engine)


def _seed_order(sessions, status="confirmed", total="250.00"):
    with sessions() as db:
        actor = User(name="Sales generation test", email=f"{uuid4().hex}@example.invalid", password_hash="unused")
        db.add(actor)
        db.flush()
        order = SalesOrder(order_no=f"SALESGEN-{uuid4().hex}", status=status, total_amount=Decimal(total))
        db.add(order)
        db.commit()
        return order.id, actor.id


def test_sales_generation_returns_the_typed_envelope(client, auth_headers):
    sid, _ = _seed_order(SessionLocal, total="123.45")
    response = client.post(f"/api/sales-orders/{sid}/generate-invoice", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "id", "sales_order_id", "invoice_no", "amount", "status", "issued_at", "due_date", "created_existing",
    }
    assert body["sales_order_id"] == sid
    assert body["amount"] == 123.45
    assert body["status"] == "unpaid"
    assert body["issued_at"] and body["due_date"] is None
    assert body["created_existing"] is False
    with SessionLocal() as db:
        row = db.get(Invoice, body["id"])
        assert row.amount == Decimal("123.45")
        assert row.status is InvoiceStatus.UNPAID
        audits = db.query(AuditLog).filter_by(entity_type="Invoice", entity_id=row.id).all()
        assert len(audits) == 1 and audits[0].action == "generate_invoice"
        assert audits[0].new_value_json == {"sales_order_id": sid, "amount": 123.45}


@pytest.mark.parametrize("total", ["0.00", "0.50"])
def test_sales_generation_keeps_zero_and_subunit_unpaid(client, auth_headers, total):
    sid, _ = _seed_order(SessionLocal, total=total)
    response = client.post(f"/api/sales-orders/{sid}/generate-invoice", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["amount"] == float(total)
    assert response.json()["status"] == "unpaid"
    with SessionLocal() as db:
        row = db.get(Invoice, response.json()["id"])
        assert row.amount == Decimal(total)
        assert row.status is InvoiceStatus.UNPAID


def test_sales_generation_reuses_the_existing_invoice_without_writing(client, auth_headers):
    sid, _ = _seed_order(SessionLocal)
    first = client.post(f"/api/sales-orders/{sid}/generate-invoice", headers=auth_headers)
    assert first.status_code == 200, first.text
    second = client.post(f"/api/sales-orders/{sid}/generate-invoice", headers=auth_headers)
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["id"] == first.json()["id"]
    assert body["created_existing"] is True
    assert body["amount"] == first.json()["amount"]
    assert body["status"] == first.json()["status"]
    with SessionLocal() as db:
        assert db.query(Invoice).filter_by(sales_order_id=sid).count() == 1
        assert db.query(AuditLog).filter_by(entity_type="Invoice", entity_id=body["id"]).count() == 1


def test_sales_generation_service_writes_through_the_schema_owned_insert(monkeypatch):
    sid, uid = _seed_order(SessionLocal, total="123.45")
    calls = []
    real_insert = issuance.insert_order_invoice

    def spy(db, **kwargs):
        calls.append(kwargs)
        return real_insert(db, **kwargs)

    monkeypatch.setattr(issuance, "insert_order_invoice", spy)
    with SessionLocal() as db:
        result = issuance.generate_order_invoice(db, sid, db.get(User, uid))
        assert isinstance(result, InvoiceGenerationOut)
        assert result.status is InvoiceStatus.UNPAID
        assert result.created_existing is False
        assert result.id > 0
        assert result.invoice_no.startswith("INV-")
    assert len(calls) == 1
    assert calls[0]["sales_order_id"] == sid
    assert calls[0]["status"] is InvoiceStatus.UNPAID
    assert calls[0]["amount"] == Decimal("123.45")


def test_sales_generation_commits_once_and_reuse_commits_nothing():
    sid, uid = _seed_order(SessionLocal)
    with SessionLocal() as db:
        commits = []
        event.listen(db, "before_commit", lambda _: commits.append(True))
        issued = issuance.generate_order_invoice(db, sid, db.get(User, uid))
        assert issued.created_existing is False
        assert len(commits) == 1
    with SessionLocal() as db:
        commits = []
        event.listen(db, "before_commit", lambda _: commits.append(True))
        reused = issuance.generate_order_invoice(db, sid, db.get(User, uid))
        assert reused.created_existing is True
        assert reused.id == issued.id
        assert not commits


@pytest.mark.parametrize("phase", ["invoice_flush", "audit_enqueue", "audit_finalized"])
def test_sales_generation_pg_failure_rolls_back_invoice_and_audit_then_retry(owned_pg_sessions, monkeypatch, phase):
    sessions = owned_pg_sessions
    sid, uid = _seed_order(sessions)
    real_log = issuance.log_action
    with sessions() as db:
        actor = db.get(User, uid)
        real_flush = db.flush
        observed = []
        if phase == "invoice_flush":
            def fail_flush(*args, **kwargs):
                real_flush(*args, **kwargs)
                if any(isinstance(row, Invoice) for row in db.identity_map.values()):
                    observed.append("flushed")
                    raise RuntimeError("injected invoice flush")
            monkeypatch.setattr(db, "flush", fail_flush)
        else:
            def fail_log(*args, **kwargs):
                real_log(*args, **kwargs)
                if phase == "audit_enqueue":
                    observed.append("queued")
                    raise RuntimeError("injected audit enqueue")
                def after_finalizer(session):
                    rows = session.query(AuditLog).filter_by(user_id=uid).all()
                    assert len(rows) == 1 and rows[0].entry_hash
                    assert session.query(Invoice).filter_by(sales_order_id=sid).count() == 1
                    observed.append("finalized")
                    raise RuntimeError("injected finalized audit")
                event.listen(db, "before_commit", after_finalizer)
            monkeypatch.setattr(issuance, "log_action", fail_log)
        with pytest.raises(RuntimeError, match="injected"):
            issuance.generate_order_invoice(db, sid, actor)
        db.rollback()
        assert observed
    monkeypatch.undo()
    with sessions() as db:
        assert db.query(Invoice).filter_by(sales_order_id=sid).count() == 0
        assert db.query(AuditLog).filter_by(user_id=uid).count() == 0
        result = issuance.generate_order_invoice(db, sid, db.get(User, uid))
        assert result.amount == Decimal("250.00") and result.status is InvoiceStatus.UNPAID
    with sessions() as db:
        assert db.query(Invoice).filter_by(sales_order_id=sid).count() == 1
        assert db.query(AuditLog).filter_by(user_id=uid).count() == 1


def test_sales_generation_pg_serializes_two_issuers_of_one_order(owned_pg_sessions):
    sessions = owned_pg_sessions
    sid, uid = _seed_order(sessions)
    reached, release, started = threading.Event(), threading.Event(), threading.Event()
    results, errors, pids = {}, {}, {}

    def run(index):
        db = (_GateSession(bind=sessions.kw["bind"], autoflush=False, expire_on_commit=False,
                           reached=reached, release=release) if index == 0 else sessions())
        try:
            with db:
                pids[index] = db.execute(text("select pg_backend_pid()")).scalar_one()
                if index == 1:
                    started.set()
                results[index] = issuance.generate_order_invoice(db, sid, db.get(User, uid))
        except BaseException as exc:
            errors[index] = exc

    first, second = threading.Thread(target=run, args=(0,)), threading.Thread(target=run, args=(1,))
    try:
        first.start()
        assert reached.wait(10), errors
        second.start()
        assert started.wait(10), errors
        _wait_for_block(sessions, pids[1], pids[0])
    finally:
        release.set()
        first.join(15)
        if second.ident is not None:
            second.join(15)
    assert not first.is_alive() and not second.is_alive(), "the issuers did not release the order lock"
    assert not errors, errors
    assert results[0].id == results[1].id
    assert results[0].created_existing is False
    assert results[1].created_existing is True
    with sessions() as db:
        assert db.query(Invoice).filter_by(sales_order_id=sid).count() == 1
        assert db.query(AuditLog).filter_by(user_id=uid).count() == 1


def test_sales_generation_pg_and_manual_entry_points_share_one_invoice(owned_pg_sessions):
    sessions = owned_pg_sessions
    sid, uid = _seed_order(sessions)
    with sessions() as db:
        generated = issuance.generate_order_invoice(db, sid, db.get(User, uid))
    with sessions() as db:
        manual = issuance.create_order_invoice(db, InvoiceIn(sales_order_id=sid), db.get(User, uid))
        assert manual.id == generated.id
        assert manual.status is generated.status
    with sessions() as db:
        assert db.query(Invoice).filter_by(sales_order_id=sid).count() == 1
        assert db.query(AuditLog).filter_by(user_id=uid).count() == 1
