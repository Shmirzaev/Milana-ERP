"""Legacy retry keys must not disclose another actor's result or fail on concurrent retries."""

import os
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes.finance import create_payment
from app.db.base import Base
from app.db.session import SessionLocal
from app.models import IdempotencyRecord, Payment, User
from app.schemas.sales import PaymentIn
from app.services.idempotency import replay_idempotent_response
from app.tests.test_payment_integrity import _create_invoice


def _actors(sessions):
    with sessions() as db:
        rows = [User(name=f"Retry actor {i}", email=f"retry-{uuid4().hex}@example.invalid",
                     password_hash="unused", factory_code="MIL") for i in range(2)]
        db.add_all(rows)
        db.commit()
        return [row.id for row in rows]


def _pay(sessions, actor_id, invoice_id, key, amount=25):
    with sessions() as db:
        return create_payment(PaymentIn(invoice_id=invoice_id, amount=amount), db,
                              current=db.get(User, actor_id), idempotency_key=key)


@pytest.mark.parametrize("orphaned_owner", [False, True])
def test_retry_rejects_other_or_unknown_owner_without_disclosing_payment(orphaned_owner):
    first_actor, other_actor = _actors(SessionLocal)
    _, _, invoice_id = _create_invoice(SessionLocal)
    key = f"owner-{uuid4().hex}"
    first = _pay(SessionLocal, first_actor, invoice_id, key)
    if orphaned_owner:
        with SessionLocal() as db:
            db.query(IdempotencyRecord).filter_by(scope="finance.payments", key=key).one().user_id = None
            db.commit()
    with pytest.raises(HTTPException) as denied:
        _pay(SessionLocal, other_actor, invoice_id, key)
    assert denied.value.status_code == 409
    assert str(first["id"]) not in str(denied.value.detail)
    with SessionLocal() as db:
        assert db.query(Payment).filter_by(invoice_id=invoice_id).count() == 1


def test_same_owner_replay_and_conflicting_payload_keep_original_payment():
    actor_id, _ = _actors(SessionLocal)
    _, _, invoice_id = _create_invoice(SessionLocal)
    key = f"replay-{uuid4().hex}"
    first = _pay(SessionLocal, actor_id, invoice_id, key)
    assert _pay(SessionLocal, actor_id, invoice_id, key) == first
    with pytest.raises(HTTPException) as conflict:
        _pay(SessionLocal, actor_id, invoice_id, key, amount=26)
    assert conflict.value.status_code == 409
    with SessionLocal() as db:
        assert db.query(Payment).filter_by(invoice_id=invoice_id).count() == 1


@pytest.fixture(scope="module")
def retry_postgres_sessions():
    raw = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw:
        pytest.skip("Requires disposable PostgreSQL")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Only loopback PostgreSQL without connection overrides is supported")
    schema = f"retry_races_{uuid4().hex}"
    engine = create_engine(url, pool_size=5, max_overflow=0,
                           connect_args={"options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"})
    assert engine.dialect.name == "postgresql"
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


@pytest.mark.parametrize("collision", ["same", "other_owner", "changed_payload"])
def test_postgres_simultaneous_payment_retries_replay_one_committed_result(retry_postgres_sessions, collision):
    sessions = retry_postgres_sessions
    actor_id, other_actor_id = _actors(sessions)
    _, _, invoice_id = _create_invoice(sessions)
    key = f"race-{uuid4().hex}"
    ready = Queue()

    def submit(index):
        with sessions() as db:
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            try:
                amount = 26 if index and collision == "changed_payload" else 25
                current_id = other_actor_id if index and collision == "other_owner" else actor_id
                return create_payment(PaymentIn(invoice_id=invoice_id, amount=amount), db,
                                      current=db.get(User, current_id), idempotency_key=key)
            except Exception as exc:
                db.rollback()
                return exc

    with sessions() as holder, ThreadPoolExecutor(max_workers=2) as workers:
        holder.execute(text("SELECT id FROM invoices WHERE id=:id FOR UPDATE"), {"id": invoice_id})
        futures = [workers.submit(submit, index) for index in range(2)]
        pids = [ready.get(timeout=10) for _ in futures]
        try:
            deadline = monotonic() + 10
            while monotonic() < deadline:
                if all(holder.execute(text("SELECT cardinality(pg_blocking_pids(:pid))"), {"pid": pid}).scalar_one() > 0
                       for pid in pids):
                    break
                sleep(.02)
            else:
                pytest.fail("Both retry writers must reach a visible PostgreSQL lock wait")
        finally:
            holder.rollback()
        results = [future.result(timeout=20) for future in futures]
    if collision == "same":
        assert all(isinstance(result, dict) for result in results), results
        assert results[0] == results[1]
    else:
        assert sum(isinstance(result, dict) for result in results) == 1, results
        conflicts = [result for result in results if isinstance(result, HTTPException)]
        assert len(conflicts) == 1 and conflicts[0].status_code == 409, results
    with sessions() as db:
        assert db.query(Payment).filter_by(invoice_id=invoice_id).count() == 1
        assert db.query(IdempotencyRecord).filter_by(scope="finance.payments", key=key).count() == 1


def test_postgres_failed_transaction_releases_retry_key_for_next_writer(retry_postgres_sessions):
    sessions = retry_postgres_sessions
    actor_id, _ = _actors(sessions)
    _, _, invoice_id = _create_invoice(sessions)
    key = f"rollback-{uuid4().hex}"
    payload = PaymentIn(invoice_id=invoice_id, amount=25)
    ready = Queue()

    def submit():
        with sessions() as db:
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            return create_payment(payload, db, current=db.get(User, actor_id), idempotency_key=key)

    with sessions() as failed, ThreadPoolExecutor(max_workers=1) as workers:
        assert replay_idempotent_response(failed, user=failed.get(User, actor_id), scope="finance.payments",
                                         key=key, payload=payload.model_dump(mode="json")) is None
        failed.add(Payment(invoice_id=invoice_id, amount=25))
        failed.flush()
        future = workers.submit(submit)
        pid = ready.get(timeout=10)
        try:
            deadline = monotonic() + 10
            while monotonic() < deadline:
                if failed.execute(text("SELECT cardinality(pg_blocking_pids(:pid))"), {"pid": pid}).scalar_one() > 0:
                    break
                sleep(.02)
            else:
                pytest.fail("Retry must wait until the previous transaction rolls back")
        finally:
            failed.rollback()
        result = future.result(timeout=20)
    with sessions() as db:
        payments = db.query(Payment).filter_by(invoice_id=invoice_id).all()
        assert len(payments) == 1 and payments[0].id == result["id"]
        assert db.query(IdempotencyRecord).filter_by(scope="finance.payments", key=key).count() == 1
