"""Manual Finance issuance policy and transaction characterization.

These assertions apply before and after schema persistence extraction. PostgreSQL
fixtures create and remove only their own randomly named disposable database.
"""
from decimal import Decimal
import threading
from uuid import uuid4

import pytest
from sqlalchemy import event, text

from app.db.session import SessionLocal
from app.libs.dto.sales.invoice_input import InvoiceIn
from app.libs.dto.sales.invoice_output import InvoiceOut
from app.libs.enums.finance import InvoiceStatus
from app.models.finance import invoices_service as issuance
from app.schemas import AuditLog, Invoice, Payment, SalesOrder, User
from app.tests.test_customer_invoice_creation_race import (
    receipt_race_sessions, _GateSession, _wait_for_block,
)


def seed(sessions, total="250.00"):
    with sessions() as db:
        actor = User(name="Manual issuance test", email=f"{uuid4().hex}@example.invalid", password_hash="unused")
        order = SalesOrder(order_no=f"MANUAL-{uuid4().hex}", status="draft", total_amount=Decimal(total))
        db.add_all([actor, order])
        db.commit()
        return order.id, actor.id


@pytest.mark.parametrize("amount,expected,status", [
    ("omitted", 250.0, "unpaid"), (None, 250.0, "unpaid"),
    ("0.00", 0.0, "paid"), ("0.01", 0.01, "paid"),
    ("1.00", 1.0, "paid"), ("1.01", 1.01, "unpaid"),
    ("123.45", 123.45, "unpaid"),
])
def test_manual_draft_issuance_wire_policy(client, auth_headers, amount, expected, status):
    oid, _ = seed(SessionLocal)
    payload = {"sales_order_id": oid}
    if amount != "omitted":
        payload["amount"] = amount
    response = client.post("/api/finance/invoices", headers=auth_headers, json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {"id", "sales_order_id", "invoice_no", "amount", "status", "issued_at", "due_date"}
    assert body["amount"] == expected and body["status"] == status
    assert body["issued_at"] and body["due_date"] is None
    with SessionLocal() as db:
        row = db.get(Invoice, body["id"])
        assert row.amount == Decimal(str(expected))
        assert isinstance(row.status, InvoiceStatus)
        assert isinstance(InvoiceOut.model_validate(row).status, InvoiceStatus)
        audits = db.query(AuditLog).filter_by(entity_type="Invoice", entity_id=row.id).all()
        assert len(audits) == 1 and audits[0].action == "create"
        assert audits[0].new_value_json == {"invoice_no": row.invoice_no}
        assert db.query(Payment).filter_by(invoice_id=row.id).count() == 0


@pytest.mark.parametrize("status", [InvoiceStatus.VOID, InvoiceStatus.CANCELLED])
def test_latest_reversed_invoice_reused_without_commit_or_audit(status):
    oid, uid = seed(SessionLocal)
    with SessionLocal() as db:
        db.add(Invoice(sales_order_id=oid, invoice_no=f"old-{uuid4().hex}", amount=10, status=InvoiceStatus.UNPAID))
        db.flush()
        latest = Invoice(sales_order_id=oid, invoice_no=f"latest-{uuid4().hex}", amount=20, status=status)
        db.add(latest)
        db.commit()
        latest_id = latest.id
    with SessionLocal() as db:
        commits = []
        event.listen(db, "before_commit", lambda _: commits.append(True))
        result = issuance.create_order_invoice(db, InvoiceIn(sales_order_id=oid, amount=100), db.get(User, uid))
        assert result.id == latest_id and result.status is status and result.amount == 20
        assert not commits
        assert db.query(AuditLog).filter_by(entity_type="Invoice", entity_id=latest_id).count() == 0


@pytest.mark.parametrize("phase", ["invoice_flush", "audit_enqueue", "audit_finalized"])
def test_manual_pg_failure_rolls_back_invoice_and_audit_then_retry(receipt_race_sessions, monkeypatch, phase):
    sessions = receipt_race_sessions
    oid, uid = seed(sessions)
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
                    assert session.query(Invoice).filter_by(sales_order_id=oid).count() == 1
                    observed.append("finalized")
                    raise RuntimeError("injected finalized audit")
                event.listen(db, "before_commit", after_finalizer)
            monkeypatch.setattr(issuance, "log_action", fail_log)
        with pytest.raises(RuntimeError, match="injected"):
            issuance.create_order_invoice(db, InvoiceIn(sales_order_id=oid), actor)
        db.rollback()
        assert observed
    monkeypatch.undo()
    with sessions() as db:
        assert db.query(Invoice).filter_by(sales_order_id=oid).count() == 0
        assert db.query(AuditLog).filter_by(user_id=uid).count() == 0
        result = issuance.create_order_invoice(db, InvoiceIn(sales_order_id=oid), db.get(User, uid))
        assert result.amount == Decimal("250.00") and result.status is InvoiceStatus.UNPAID
    with sessions() as db:
        assert db.query(Invoice).filter_by(sales_order_id=oid).count() == 1
        assert db.query(AuditLog).filter_by(user_id=uid).count() == 1


def test_manual_pg_numbering_serializes_different_orders(receipt_race_sessions):
    sessions = receipt_race_sessions
    ids = [seed(sessions), seed(sessions)]
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
                oid, uid = ids[index]
                row = issuance.create_order_invoice(db, InvoiceIn(sales_order_id=oid), db.get(User, uid))
                results[index] = row.invoice_no
        except BaseException as exc:
            errors[index] = exc
    first, second = threading.Thread(target=run, args=(0,)), threading.Thread(target=run, args=(1,))
    try:
        first.start()
        assert reached.wait(10), errors
        second.start()
        assert started.wait(10), errors
        _wait_for_block(sessions, pids[1], pids[0])
        with sessions() as db:
            assert db.execute(text("select count(*) from pg_locks where pid=:pid and locktype='advisory' and not granted"), {"pid": pids[1]}).scalar_one() == 1
    finally:
        release.set()
        first.join(15)
        if second.ident is not None:
            second.join(15)
    assert not first.is_alive() and not second.is_alive()
    assert not errors, errors
    assert int(results[1].rsplit("-", 1)[1]) == int(results[0].rsplit("-", 1)[1]) + 1
    with sessions() as db:
        assert db.query(Invoice).filter(Invoice.sales_order_id.in_([row[0] for row in ids])).count() == 2
        assert db.query(AuditLog).filter(AuditLog.user_id.in_([row[1] for row in ids])).count() == 2
