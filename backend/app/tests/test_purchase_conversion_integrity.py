"""Conversion refreshes the request under a real parent-row lock."""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from queue import Queue
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import Item, PurchaseOrder, PurchaseRequest, PurchaseRequestLine, User
from app.services.purchasing import approve_purchase_request, convert_purchase_request_to_order, reject_purchase_request
from app.tests.conftest import TestSessionLocal


def _case(sessions):
    marker = uuid4().hex
    with sessions.begin() as db:
        actor = User(name="Conversion test", email=f"conversion-{marker}@example.invalid", password_hash="unused")
        item = Item(sku=f"CONVERT-{marker}", name="Synthetic material", category="fabric", unit="kg")
        request = PurchaseRequest(request_no=f"CONVERT-{marker}", status="approved")
        db.add_all([actor, item, request])
        db.flush()
        line = PurchaseRequestLine(purchase_request_id=request.id, item_id=item.id, unit="kg", requested_quantity=5)
        db.add(line)
        db.flush()
        return request.id, actor.id, {
            "expected_date": datetime(2026, 10, 1, tzinfo=timezone.utc),
            "lines": [{"purchase_request_line_id": line.id, "ordered_quantity": 5}],
        }


@pytest.mark.parametrize("operation", ["convert", "reject", "approve"])
def test_conversion_rejects_stale_approved_identity_map(operation):
    request_id, actor_id, payload = _case(TestSessionLocal)
    with TestSessionLocal() as stale:
        cached = stale.get(PurchaseRequest, request_id)
        assert cached.status == "approved"
        stale.commit()
        with TestSessionLocal.begin() as other:
            other.get(PurchaseRequest, request_id).status = "converted"
        with pytest.raises(HTTPException) as rejected:
            kwargs = {"request_id": request_id, "current": stale.get(User, actor_id)}
            if operation == "reject":
                reject_purchase_request(stale, **kwargs)
            elif operation == "approve":
                approve_purchase_request(stale, data={}, **kwargs)
            else:
                convert_purchase_request_to_order(stale, data=payload, **kwargs)
        assert rejected.value.status_code == 409
        stale.rollback()
    with TestSessionLocal() as db:
        assert db.query(PurchaseOrder).filter_by(purchase_request_id=request_id).count() == 0


def test_conversion_rollback_allows_one_later_conversion():
    request_id, actor_id, payload = _case(TestSessionLocal)
    with TestSessionLocal() as db:
        convert_purchase_request_to_order(db, request_id=request_id, data=payload, current=db.get(User, actor_id))
        db.rollback()
    with TestSessionLocal() as db:
        assert db.get(PurchaseRequest, request_id).status == "approved"
        order = convert_purchase_request_to_order(db, request_id=request_id, data=payload, current=db.get(User, actor_id))
        db.commit()
        assert len(order.lines) == 1 and float(order.lines[0].ordered_quantity) == 5
        assert db.query(PurchaseOrder).filter_by(purchase_request_id=request_id).count() == 1


@pytest.fixture(scope="module")
def conversion_postgres_sessions():
    raw = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw:
        pytest.skip("Requires disposable PostgreSQL")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Only loopback PostgreSQL without overrides is supported")
    schema = f"conversion_{uuid4().hex}"
    engine = create_engine(url, pool_size=4, max_overflow=0, connect_args={
        "options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000",
    })
    assert engine.dialect.name == "postgresql"
    with engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


@pytest.mark.parametrize("second_operation", ["convert", "reject"])
def test_postgres_conversions_preserve_request_state(conversion_postgres_sessions, second_operation):
    sessions = conversion_postgres_sessions
    request_id, actor_id, payload = _case(sessions)
    ready, start = Queue(), Event()

    def convert(operation):
        with sessions() as db:
            assert db.bind.dialect.name == "postgresql"
            cached = db.get(PurchaseRequest, request_id)
            assert cached.status == "approved"
            actor = db.get(User, actor_id)
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            assert start.wait(10)
            try:
                if operation == "reject":
                    reject_purchase_request(db, request_id=request_id, current=actor)
                else:
                    convert_purchase_request_to_order(db, request_id=request_id, data=payload, current=actor)
                db.commit()
                return 200 if operation == "reject" else 201
            except HTTPException as rejected:
                db.rollback()
                return rejected.status_code

    with sessions() as holder, ThreadPoolExecutor(max_workers=2) as workers:
        holder.execute(text("SELECT id FROM purchase_requests WHERE id=:id FOR NO KEY UPDATE"), {"id": request_id})
        futures = [workers.submit(convert, operation) for operation in ("convert", second_operation)]
        try:
            pids = [ready.get(timeout=10) for _ in futures]
            start.set()
            deadline = monotonic() + 10
            while monotonic() < deadline:
                if all(holder.execute(text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid}).scalar_one() for pid in pids):
                    break
                sleep(0.02)
            else:
                pytest.fail("Both conversion transactions must visibly wait on locks")
        finally:
            start.set()
            holder.rollback()
        statuses = sorted(future.result(timeout=20) for future in futures)
        assert statuses in ([[201, 409]] if second_operation == "convert" else [[201, 409], [200, 409]])
    with sessions() as db:
        expected_state = "rejected" if 200 in statuses else "converted"
        assert db.get(PurchaseRequest, request_id).status == expected_state
        assert db.query(PurchaseOrder).filter_by(purchase_request_id=request_id).count() == (0 if expected_state == "rejected" else 1)
