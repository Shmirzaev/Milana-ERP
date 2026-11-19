"""HELD source proposal: controlled Customer delete versus Payment FK races."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models.catalog import partners_service
from app.schemas import Payment
from app.tests.test_customer_create_postgres import chain, customer_pg_sessions  # noqa: F401
from app.tests.test_customer_delete_postgres import create_customer, state


def test_pg_payment_commit_after_guards_before_delete_flush(customer_pg_sessions, monkeypatch):
    sessions = customer_pg_sessions
    cid, name = create_customer(sessions)
    guards_passed, reference_committed = Event(), Event()
    original = partners_service.log_action
    def after_guards(db, *args, **kwargs):
        guards_passed.set()
        assert reference_committed.wait(10), "payment commit did not complete"
        return original(db, *args, **kwargs)
    def delete():
        with sessions() as db:
            try:
                partners_service.delete_customer(None, db, cid)
            except IntegrityError as error:
                db.rollback()
                return error.orig.pgcode
            raise AssertionError("delete unexpectedly succeeded with committed reference")
    def insert():
        assert guards_passed.wait(10), "delete did not reach checkpoint"
        try:
            with sessions.begin() as db:
                payment = Payment(customer_id=cid, amount=1)
                db.add(payment)
                db.flush()
                payment_id = payment.id
            return payment_id
        finally:
            reference_committed.set()
    monkeypatch.setattr(partners_service, "log_action", after_guards)
    with ThreadPoolExecutor(max_workers=2) as pool:
        deletion = pool.submit(delete)
        insertion = pool.submit(insert)
        payment_id = insertion.result(timeout=25)
        assert deletion.result(timeout=25) == "23503"
    assert state(sessions, cid) == ((name, "saved", "preserve on failure"), [])
    with sessions() as db:
        assert db.get(Payment, payment_id).customer_id == cid
    chain(sessions)


def test_pg_delete_flush_blocks_payment_until_commit(customer_pg_sessions, monkeypatch):
    sessions = customer_pg_sessions
    cid, name = create_customer(sessions)
    flushed, release_delete, payment_ready = Event(), Event(), Event()
    original = partners_service.log_action
    pids = {}
    def after_flush(db, *args, **kwargs):
        entry = original(db, *args, **kwargs)
        pids["deleter"] = db.execute(text("SELECT pg_backend_pid()" )).scalar_one()
        flushed.set()
        assert release_delete.wait(12), "lock witness did not release delete"
        return entry
    def delete():
        with sessions() as db:
            partners_service.delete_customer(None, db, cid)
    def insert():
        assert flushed.wait(10), "delete did not flush"
        with sessions() as db:
            pids["inserter"] = db.execute(text("SELECT pg_backend_pid()" )).scalar_one()
            payment_ready.set()
            try:
                db.add(Payment(customer_id=cid, amount=1))
                db.flush()
                db.commit()
            except IntegrityError as error:
                db.rollback()
                return error.orig.pgcode
            raise AssertionError("reference unexpectedly committed after parent deletion")
    monkeypatch.setattr(partners_service, "log_action", after_flush)
    with ThreadPoolExecutor(max_workers=2) as pool:
        deletion = pool.submit(delete)
        insertion = pool.submit(insert)
        try:
            assert payment_ready.wait(10), "payment session did not start"
            deadline = monotonic() + 8
            witnessed = False
            with sessions() as observer:
                while monotonic() < deadline:
                    blockers = observer.execute(text("SELECT pg_blocking_pids(:pid)"), {"pid": pids["inserter"]}).scalar_one()
                    if pids["deleter"] in blockers:
                        witnessed = True
                        break
                    if insertion.done() or deletion.done():
                        break
                    # Delay is only polling cadence; pg_blocking_pids is the evidence.
                    Event().wait(0.05)
            assert witnessed, "no actual PostgreSQL blocker witnessed"
        finally:
            release_delete.set()
        deletion.result(timeout=25)
        assert insertion.result(timeout=25) == "23503"
    assert state(sessions, cid) == (None, [(None, None, {"name": name})])
    with sessions() as db:
        assert db.query(Payment).filter_by(customer_id=cid).count() == 0
    chain(sessions)
