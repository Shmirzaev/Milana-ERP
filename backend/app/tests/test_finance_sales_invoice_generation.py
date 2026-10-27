"""Sales invoice generation: typed result, schema-owned write, one transaction.

The sales entry point is the second issuer of a sales-order invoice. These
assertions pin the contract it returns, the write it uses and the transaction
it owns. The PostgreSQL-only cases prove what SQLite cannot: row-lock
serialization of two issuers and the rollback residue of a failed issuance.

The PostgreSQL fixture uses this worker's own disposable database and refuses
any server whose identity is not the pinned review instance, both before the
first use and inside every connection it hands out.
"""
import os
import re
import threading
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url

from app.db.base import Base
from app.db.session import SessionLocal
from app.libs.dto.sales.invoice_generation_output import InvoiceGenerationOut
from app.libs.dto.sales.invoice_input import InvoiceIn
from app.libs.enums.finance import InvoiceStatus
from app.models.finance import invoices_service as issuance
from app.schemas import AuditLog, Invoice, SalesOrder, User
from app.tests.test_customer_invoice_creation_race import _GateSession, _wait_for_block

PINNED_HOST = "127.0.0.1"
PINNED_PORT = 51716
PINNED_SERVER_VERSION = "17.11"
PINNED_SYSTEM_IDENTIFIER = "7700371345869473300"
PINNED_DATA_DIRECTORY = "C:/Users/ismoi/Documents/Codex/2026-10-23/we-x20/work/finance-visual-qa-5aafe01d69/data"
OWNED_DATABASE_PATTERN = re.compile(r"review_mm_finance_[0-9a-f]{12}")

IDENTITY_QUERY = (
    "SELECT host(inet_server_addr()), inet_server_port(), current_setting('server_version'), "
    "(SELECT system_identifier::text FROM pg_control_system()), current_setting('data_directory')"
)


def _assert_pinned_identity(host, port, version, system_identifier, data_directory):
    assert host == PINNED_HOST, f"unexpected server address {host!r}"
    assert int(port) == PINNED_PORT, f"unexpected server port {port!r}"
    assert version == PINNED_SERVER_VERSION, f"unexpected server version {version!r}"
    assert system_identifier == PINNED_SYSTEM_IDENTIFIER, f"unexpected system identifier {system_identifier!r}"
    assert data_directory.replace("\\", "/").rstrip("/") == PINNED_DATA_DIRECTORY, f"unexpected data directory {data_directory!r}"


@pytest.fixture(scope="module")
def owned_pg_sessions():
    """This worker's own disposable database on the pinned review instance."""
    url = os.environ.get("FN04_TEST_PG_DB_URL")
    if not url:
        pytest.skip("Set FN04_TEST_PG_DB_URL to this worker's own review_mm_finance_<12hex> database")
    parsed = make_url(url)
    assert parsed.host == PINNED_HOST and parsed.port == PINNED_PORT, "the owned database is not on the pinned review instance"
    assert OWNED_DATABASE_PATTERN.fullmatch(parsed.database or ""), "the owned database must use the assigned review_mm_finance_<12hex> name"
    engine = create_engine(
        parsed,
        connect_args={"options": "-cstatement_timeout=20000 -clock_timeout=10000"},
    )

    @event.listens_for(engine, "connect")
    def _check_identity(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(IDENTITY_QUERY)
            _assert_pinned_identity(*cursor.fetchone())
        finally:
            cursor.close()

    try:
        with engine.connect() as connection:
            _assert_pinned_identity(*connection.execute(text(IDENTITY_QUERY)).one())
        Base.metadata.create_all(engine)
        from sqlalchemy.orm import sessionmaker

        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        engine.dispose()


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
        # The previous mapping result is still readable by key.
        assert result["id"] == result.id
        assert result["invoice_no"] == result.invoice_no
        assert result["status"] == result.status
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
