"""Caller isolation, legacy recovery and real concurrent request replay."""
import os
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import finance
from app.api.routes.finance import create_payment
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import SessionLocal
from app.models import AuditLog, IdempotencyRecord, Invoice, Payment, SalesOrder, User
from app.schemas.sales import PaymentIn
from app.services.idempotency import bind_idempotency_identity, replay_idempotent_response, request_fingerprint, store_idempotent_response


def actors_and_invoice(sessions):
    with sessions() as db:
        actors = [User(name=f"FN06 User {label}", email=f"fn06-{uuid4().hex}@example.invalid",
                       password_hash="unused", factory_code="MIL",
                       extra_permissions=["finance.payment", "admin.super"]) for label in (101, 202)]
        order = SalesOrder(order_no=f"FN06-{uuid4().hex}", order_type="client_order", status="ready")
        db.add_all([*actors, order])
        db.flush()
        invoice = Invoice(sales_order_id=order.id, invoice_no=f"FN06-{uuid4().hex}", amount=100)
        db.add(invoice)
        db.commit()
        return [actor.id for actor in actors], invoice.id


def bind(db, user_id, factory="MIL"):
    # Direct tests bypass authentication, so establish its session context here.
    user = db.get(User, user_id)
    user.session_factory_code = factory
    bind_idempotency_identity(db, user)
    return user


def headers(user_id, key, factory="MIL"):
    return {"Authorization": f"Bearer {create_access_token(str(user_id), {'factory_code': factory})}",
            "Idempotency-Key": key}


@pytest.mark.parametrize("second_amount", [25, 30])
def test_http_cross_user_same_key_create_independent_payments(client, second_amount):
    actors, invoice_id = actors_and_invoice(SessionLocal)
    payloads = [{"invoice_id": invoice_id, "amount": amount, "payment_method": "cash"}
                for amount in (25, second_amount)]
    results = [client.post("/api/finance/payments", json=payload, headers=headers(actor, "shared-key"))
               for actor, payload in zip(actors, payloads)]
    assert [r.status_code for r in results] == [201, 201], [r.text for r in results]
    assert results[0].json()["id"] != results[1].json()["id"]
    for actor, payload, result in zip(actors, payloads, results):
        retry = client.post("/api/finance/payments", json=payload, headers=headers(actor, "shared-key"))
        assert retry.status_code == 201, retry.text
        assert retry.json() == result.json()
    with SessionLocal() as db:
        assert db.query(Payment).filter_by(invoice_id=invoice_id).count() == 2


def test_http_factory_namespaces_are_independent(client):
    actors, invoice_id = actors_and_invoice(SessionLocal)
    payload = {"invoice_id": invoice_id, "amount": 25}
    results = [client.post("/api/finance/payments", json=payload,
                           headers=headers(actors[0], "shared-key", factory)) for factory in ("MIL", "ECO")]
    assert [r.status_code for r in results] == [201, 201], [r.text for r in results]
    assert results[0].json()["id"] != results[1].json()["id"]
    for factory, result in zip(("MIL", "ECO"), results):
        retry = client.post("/api/finance/payments", json=payload,
                            headers=headers(actors[0], "shared-key", factory))
        assert retry.status_code == 201 and retry.json() == result.json(), retry.text


def test_same_identity_changed_payload_conflicts(client):
    actors, invoice_id = actors_and_invoice(SessionLocal)
    payload = {"invoice_id": invoice_id, "amount": 25}
    assert client.post("/api/finance/payments", json=payload, headers=headers(actors[0], "key")).status_code == 201
    changed = client.post("/api/finance/payments", json={**payload, "amount": 26}, headers=headers(actors[0], "key"))
    assert changed.status_code == 409
    with SessionLocal() as db:
        assert db.query(Payment).filter_by(invoice_id=invoice_id).count() == 1


def test_explicit_operation_scope_survives_different_wrapper_functions():
    actors, _ = actors_and_invoice(SessionLocal)
    with SessionLocal() as db:
        bind(db, actors[0])
        def write():
            store_idempotent_response(db, scope="packages.synthetic", key="key", payload={},
                                      response={"id": 1}, user=db.get(User, actors[0]))
        def reconcile():
            return replay_idempotent_response(db, scope="packages.synthetic", key="key", payload={})
        write()
        assert reconcile() == {"id": 1}
        assert replay_idempotent_response(db, scope="shipments.synthetic", key="key", payload={}) is None


@pytest.mark.parametrize("case", ["owned", "foreign_owner", "unknown_owner", "unknown_factory", "other_factory", "changed_payload", "scoped_factory"])
def test_guarded_legacy_recovery(case):
    actors, _ = actors_and_invoice(SessionLocal)
    scope = f"purchasing.receive:MIL:{actors[0]}:42" if case == "scoped_factory" else "finance.payments"
    response = {"id": 901}
    if case not in {"unknown_factory", "scoped_factory"}:
        response["factory_code"] = "ECO" if case == "other_factory" else "MIL"
    owner = None if case == "unknown_owner" else actors[1] if case == "foreign_owner" else actors[0]
    with SessionLocal() as db:
        legacy = IdempotencyRecord(scope=scope, key="legacy-key", request_hash=request_fingerprint({}),
                                   response_json=response, user_id=owner)
        db.add(legacy)
        db.commit()
        bind(db, actors[0])
        payload = {"changed": True} if case == "changed_payload" else {}
        if case in {"unknown_owner", "unknown_factory", "changed_payload"}:
            with pytest.raises(HTTPException) as conflict:
                replay_idempotent_response(db, scope=scope, key="legacy-key", payload=payload)
            assert conflict.value.status_code == 409
        elif case in {"foreign_owner", "other_factory"}:
            assert replay_idempotent_response(db, scope=scope, key="legacy-key", payload=payload) is None
            store_idempotent_response(db, scope=scope, key="legacy-key", payload=payload,
                                      response={"id": 902}, user=db.get(User, actors[0]))
            db.commit()
            assert replay_idempotent_response(db, scope=scope, key="legacy-key", payload=payload) == {"id": 902}
            assert db.query(IdempotencyRecord).count() == 2
        else:
            assert replay_idempotent_response(db, scope=scope, key="legacy-key", payload=payload) == response
        db.refresh(legacy)
        assert legacy.scope == scope and legacy.response_json == response


def test_missing_identity_never_replays_or_stores_keyed_requests():
    actors, _ = actors_and_invoice(SessionLocal)
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as unauthenticated:
            replay_idempotent_response(db, scope="finance.payments", key="key", payload={})
        assert unauthenticated.value.status_code == 401
        with pytest.raises(HTTPException):
            store_idempotent_response(db, scope="finance.payments", key="key", payload={},
                                      response={}, user=db.get(User, actors[0]))
        assert replay_idempotent_response(db, scope="finance.payments", key=None, payload={}) is None


def test_store_owner_must_match_authenticated_session():
    actors, _ = actors_and_invoice(SessionLocal)
    with SessionLocal() as db:
        bind(db, actors[0])
        with pytest.raises(HTTPException):
            store_idempotent_response(db, scope="finance.payments", key="key", payload={},
                                      response={}, user=db.get(User, actors[1]))
        assert db.query(IdempotencyRecord).count() == 0


def test_long_operation_scopes_are_bounded_without_aliasing():
    actors, _ = actors_and_invoice(SessionLocal)
    with SessionLocal() as db:
        bind(db, actors[0])
        for i in (1, 2):
            store_idempotent_response(db, scope="x" * 127 + str(i), key="k" * 128, payload={},
                                      response={"id": i}, user=db.get(User, actors[0]))
        rows = db.query(IdempotencyRecord).all()
        assert len(rows) == 2 and all(len(row.scope) <= 128 and row.key == "k" * 128 for row in rows)
        for i in (1, 2):
            assert replay_idempotent_response(db, scope="x" * 127 + str(i), key="k" * 128, payload={}) == {"id": i}


@pytest.fixture(scope="module")
def postgres_sessions():
    raw = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for local PostgreSQL, e.g. localhost:5433/milana_test")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("FN06 tests require loopback PostgreSQL without connection overrides")
    schema = f"fn06_{uuid4().hex}"
    engine = create_engine(url, pool_size=5, max_overflow=0, isolation_level="READ COMMITTED",
                           connect_args={"options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"})
    with engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        tables = {Payment.__table__, Invoice.__table__, IdempotencyRecord.__table__, AuditLog.__table__}
        pending = list(tables)
        while pending:
            for fk in pending.pop().foreign_keys:
                if fk.column.table not in tables:
                    tables.add(fk.column.table)
                    pending.append(fk.column.table)
        Base.metadata.create_all(engine, tables=list(tables))
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


@pytest.mark.parametrize("case", ["same", "other_user", "other_factory", "changed_payload"])
def test_postgres_concurrent_payment_retries(postgres_sessions, case, monkeypatch):
    sessions = postgres_sessions
    actors, invoice_id = actors_and_invoice(sessions)
    ready = Queue()
    processed = Queue()
    key = f"race-{uuid4().hex}"
    original_payment = finance.create_invoice_payment

    def process_payment(*args, **kwargs):
        processed.put(1)
        return original_payment(*args, **kwargs)

    monkeypatch.setattr(finance, "create_invoice_payment", process_payment)

    def submit(index):
        with sessions() as db:
            actor_id = actors[1] if index and case == "other_user" else actors[0]
            current = bind(db, actor_id, "ECO" if index and case == "other_factory" else "MIL")
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            try:
                return create_payment(PaymentIn(invoice_id=invoice_id, amount=26 if index and case == "changed_payload" else 25),
                                      db, current=current, idempotency_key=key)
            except HTTPException as exc:
                db.rollback()
                return exc

    with sessions() as holder, ThreadPoolExecutor(max_workers=2) as workers:
        holder.execute(text("SELECT id FROM invoices WHERE id=:id FOR UPDATE"), {"id": invoice_id})
        futures = [workers.submit(submit, i) for i in (0, 1)]
        pids = [ready.get(timeout=10) for _ in futures]
        try:
            deadline = monotonic() + 10
            while monotonic() < deadline:
                if all(holder.execute(text("SELECT cardinality(pg_blocking_pids(:pid))"), {"pid": pid}).scalar_one() for pid in pids):
                    break
                sleep(.02)
            else:
                pytest.fail("Both independent retry writers must reach a PostgreSQL lock wait")
        finally:
            holder.rollback()
        results = [f.result(timeout=25) for f in futures]
    if case == "same":
        assert all(isinstance(r, dict) for r in results) and results[0] == results[1], results
    elif case == "changed_payload":
        assert sum(isinstance(r, dict) for r in results) == 1, results
        assert sum(isinstance(r, HTTPException) and r.status_code == 409 for r in results) == 1, results
    else:
        assert all(isinstance(r, dict) for r in results) and results[0]["id"] != results[1]["id"], results
    expected = 2 if case in {"other_user", "other_factory"} else 1
    assert processed.qsize() == expected, "Retries must replay before entering the business write path"
    with sessions() as db:
        assert db.query(Payment).filter_by(invoice_id=invoice_id).count() == expected
        assert db.query(IdempotencyRecord).filter_by(key=key).count() == expected


def test_postgres_other_users_key_does_not_wait_for_first_user(postgres_sessions):
    sessions = postgres_sessions
    actors, invoice_id = actors_and_invoice(sessions)
    key = f"independent-{uuid4().hex}"
    done = Event()

    def submit():
        with sessions() as db:
            bind(db, actors[1])
            result = replay_idempotent_response(db, scope="finance.payments", key=key, payload={})
            store_idempotent_response(db, scope="finance.payments", key=key, payload={}, response={"id": 2}, user=db.get(User, actors[1]))
            db.commit()
            done.set()
            return result

    with sessions() as first, ThreadPoolExecutor(max_workers=1) as worker:
        bind(first, actors[0])
        assert replay_idempotent_response(first, scope="finance.payments", key=key, payload={}) is None
        store_idempotent_response(first, scope="finance.payments", key=key, payload={}, response={"id": 1}, user=first.get(User, actors[0]))
        future = worker.submit(submit)
        try:
            assert done.wait(5), "A different user's namespace must not wait for the first user's uncommitted key"
            assert future.result(timeout=5) is None
        finally:
            first.rollback()


def test_postgres_rollback_releases_retry_lock_without_committing_business_write(postgres_sessions):
    sessions = postgres_sessions
    actors, invoice_id = actors_and_invoice(sessions)
    key = f"rollback-{uuid4().hex}"
    payload = PaymentIn(invoice_id=invoice_id, amount=25)
    ready = Queue()

    def submit():
        with sessions() as db:
            current = bind(db, actors[0])
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            return create_payment(payload, db, current=current, idempotency_key=key)

    with sessions() as failed, ThreadPoolExecutor(max_workers=1) as worker:
        bind(failed, actors[0])
        assert replay_idempotent_response(failed, scope="finance.payments", key=key,
                                         payload=payload.model_dump(mode="json")) is None
        failed.add(Payment(invoice_id=invoice_id, amount=25))
        failed.flush()
        future = worker.submit(submit)
        pid = ready.get(timeout=10)
        try:
            deadline = monotonic() + 10
            while monotonic() < deadline:
                if failed.execute(text("SELECT cardinality(pg_blocking_pids(:pid))"), {"pid": pid}).scalar_one():
                    break
                sleep(.02)
            else:
                pytest.fail("Retry must wait until the original transaction rolls back")
        finally:
            failed.rollback()
        result = future.result(timeout=25)
    with sessions() as db:
        rows = db.query(Payment).filter_by(invoice_id=invoice_id).all()
        assert len(rows) == 1 and rows[0].id == result["id"]
        assert db.query(IdempotencyRecord).filter_by(key=key).count() == 1
