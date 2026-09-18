"""Whole-record waste disposal decisions cannot replay or reopen terminal stock."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import os
from queue import Queue
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import waste
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import SessionLocal
from app.models import AuditLog, User, WasteDisposalRequest, WasteRecord


def _actor(permissions=("waste.receive", "waste.disposal", "management.approve"), session_factory=SessionLocal):
    with session_factory() as db:
        actor = User(name="Synthetic waste operator", email=f"waste-{uuid4().hex}@example.com",
                     password_hash="unused-token-fixture", factory_code="MIL", extra_permissions=list(permissions))
        db.add(actor)
        db.commit()
        return actor.id, {"Authorization": f"Bearer {create_access_token(actor.id)}"}


def _fixture(*, state="received_by_waste_department", request_state=None, quantity=2.75, sellable=False, session_factory=SessionLocal):
    with session_factory() as db:
        record = WasteRecord(waste_type="Synthetic fabric offcuts", quantity=quantity, unit="kg",
                             sellable=sellable, estimated_value=12.50, status=state)
        db.add(record)
        db.flush()
        request = None
        if request_state:
            request = WasteDisposalRequest(waste_record_id=record.id, reason="Synthetic disposal",
                                           status=request_state)
            db.add(request)
        db.commit()
        return record.id, request.id if request else None


def _snapshot(wid, session_factory=SessionLocal):
    with session_factory() as db:
        record = db.get(WasteRecord, wid)
        requests = db.query(WasteDisposalRequest).filter_by(waste_record_id=wid).order_by(WasteDisposalRequest.id).all()
        return {
            "record": {column.name: getattr(record, column.name) for column in record.__table__.columns},
            "requests": [{column.name: getattr(row, column.name) for column in row.__table__.columns} for row in requests],
            "audits": db.query(AuditLog).count(),
        }


@pytest.mark.parametrize("state", ["recorded", "sold", "pending_disposal_approval", "disposal_approved", "disposed", "unknown"])
def test_request_disposal_requires_received_state_without_writes(client, state):
    _, headers = _actor()
    wid, _ = _fixture(state=state)
    before = _snapshot(wid)
    response = client.post(f"/api/waste/{wid}/request-disposal", headers=headers, json={"reason": "Test"})
    assert response.status_code == 400, response.text
    assert _snapshot(wid) == before


def test_request_disposal_refuses_duplicate_without_second_request_or_audit(client):
    _, headers = _actor()
    wid, _ = _fixture()
    first = client.post(f"/api/waste/{wid}/request-disposal", headers=headers, json={"reason": "First"})
    assert first.status_code == 200, first.text
    before = _snapshot(wid)
    repeat = client.post(f"/api/waste/{wid}/request-disposal", headers=headers, json={"reason": "Repeated"})
    assert repeat.status_code == 400, repeat.text
    assert _snapshot(wid) == before


@pytest.mark.parametrize("action", ["approve", "reject"])
@pytest.mark.parametrize(("request_state", "state"), [
    ("approved", "disposal_approved"), ("rejected", "received_by_waste_department"), ("disposed", "disposed"),
])
def test_management_decisions_cannot_replay_or_reopen_terminal_disposal(client, action, request_state, state):
    _, headers = _actor()
    wid, rid = _fixture(state=state, request_state=request_state)
    before = _snapshot(wid)
    response = client.post(f"/api/waste/disposal/{rid}/{action}", headers=headers)
    assert response.status_code == 400, response.text
    assert _snapshot(wid) == before


@pytest.mark.parametrize("action", ["approve", "reject", "mark-disposed"])
@pytest.mark.parametrize("state", ["recorded", "received_by_waste_department", "sold", "disposed"])
def test_disposal_decision_requires_matching_waste_state(client, action, state):
    _, headers = _actor()
    wid, rid = _fixture(state=state, request_state="approved" if action == "mark-disposed" else "pending")
    before = _snapshot(wid)
    response = client.post(f"/api/waste/disposal/{rid}/{action}", headers=headers)
    assert response.status_code == 400, response.text
    assert _snapshot(wid) == before


@pytest.mark.parametrize("state", ["pending", "rejected", "disposed"])
def test_mark_disposed_still_requires_approved_request(client, state):
    _, headers = _actor()
    wid, rid = _fixture(state="disposal_approved", request_state=state)
    before = _snapshot(wid)
    response = client.post(f"/api/waste/disposal/{rid}/mark-disposed", headers=headers)
    assert response.status_code == 400, response.text
    assert _snapshot(wid) == before


def test_sellable_waste_cannot_enter_disposal(client):
    _, headers = _actor()
    wid, _ = _fixture(sellable=True)
    before = _snapshot(wid)
    response = client.post(f"/api/waste/{wid}/request-disposal", headers=headers, json={})
    assert response.status_code == 400
    assert _snapshot(wid) == before


@pytest.mark.parametrize("quantity", [0, -0.25, float("inf"), float("-inf")])
@pytest.mark.parametrize("action", ["request-disposal", "approve", "mark-disposed"])
def test_disposal_rejects_invalid_stored_quantity_before_writes(client, quantity, action):
    _, headers = _actor()
    state = "received_by_waste_department" if action == "request-disposal" else "disposal_approved" if action == "mark-disposed" else "pending_disposal_approval"
    wid, rid = _fixture(state=state, quantity=quantity, request_state=None if action == "request-disposal" else "approved" if action == "mark-disposed" else "pending")
    path = f"/api/waste/{wid}/request-disposal" if action == "request-disposal" else f"/api/waste/disposal/{rid}/{action}"
    before = _snapshot(wid)
    response = client.post(path, headers=headers, json={})
    assert response.status_code == 400, response.text
    assert response.json() == {"detail": "Waste quantity must be finite and greater than zero"}
    assert _snapshot(wid) == before


@pytest.mark.parametrize("quantity", [2.75, 0.0001])
def test_complete_disposal_keeps_original_quantity_and_one_audit_per_transition(client, quantity):
    actor_id, headers = _actor()
    created = client.post("/api/waste", headers=headers, json={
        "waste_type": "Synthetic offcuts", "quantity": quantity, "unit": "kg", "sellable": False,
    })
    assert created.status_code == 201, created.text
    wid = created.json()["id"]
    assert client.post(f"/api/waste/{wid}/receive", headers=headers).status_code == 200
    requested = client.post(f"/api/waste/{wid}/request-disposal", headers=headers, json={"reason": "Physical disposal required"})
    assert requested.status_code == 200, requested.text
    rid = requested.json()["id"]
    approved = client.post(f"/api/waste/disposal/{rid}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    approval_evidence = approved.json()
    assert approval_evidence["approved_by"] == actor_id and approval_evidence["approved_at"]
    disposed = client.post(f"/api/waste/disposal/{rid}/mark-disposed", headers=headers)
    assert disposed.status_code == 200, disposed.text
    assert disposed.json() == {**approval_evidence, "status": "disposed"}
    final = _snapshot(wid)
    assert final["record"]["status"] == "disposed"
    assert float(final["record"]["quantity"]) == quantity
    assert len(final["requests"]) == 1
    with SessionLocal() as db:
        actions = [row.action for row in db.query(AuditLog).filter_by(user_id=actor_id).order_by(AuditLog.id)]
        assert actions == ["create", "receive", "request_disposal", "approve_disposal", "mark_disposed"]
    for action in ("approve", "reject", "mark-disposed"):
        assert client.post(f"/api/waste/disposal/{rid}/{action}", headers=headers).status_code == 400
        assert _snapshot(wid) == final


def test_rejected_request_allows_new_request_but_old_decision_cannot_touch_it(client):
    _, headers = _actor()
    wid, _ = _fixture()
    first = client.post(f"/api/waste/{wid}/request-disposal", headers=headers, json={"reason": "First"}).json()
    assert client.post(f"/api/waste/disposal/{first['id']}/reject", headers=headers).status_code == 200
    second = client.post(f"/api/waste/{wid}/request-disposal", headers=headers, json={"reason": "Reconsidered"})
    assert second.status_code == 200 and second.json()["id"] != first["id"]
    before = _snapshot(wid)
    for action in ("approve", "reject"):
        assert client.post(f"/api/waste/disposal/{first['id']}/{action}", headers=headers).status_code == 400
        assert _snapshot(wid) == before
    assert client.post(f"/api/waste/disposal/{second.json()['id']}/approve", headers=headers).status_code == 200


@pytest.mark.parametrize("action", ["request-disposal", "approve", "reject", "mark-disposed"])
def test_disposal_authentication_permissions_and_missing_ids_unchanged(client, action):
    _, permitted = _actor()
    _, restricted = _actor(())
    wid, rid = _fixture(state="disposal_approved" if action == "mark-disposed" else "pending_disposal_approval",
                        request_state="approved" if action == "mark-disposed" else "pending")
    path = f"/api/waste/{wid}/request-disposal" if action == "request-disposal" else f"/api/waste/disposal/{rid}/{action}"
    missing = "/api/waste/2000000000/request-disposal" if action == "request-disposal" else f"/api/waste/disposal/2000000000/{action}"
    before = _snapshot(wid)
    assert client.post(path, json={}).status_code == 401
    assert client.post(path, headers=restricted, json={}).status_code == 403
    assert client.post(missing, headers=permitted, json={}).status_code == 404
    assert _snapshot(wid) == before


@pytest.mark.parametrize("action", ["request-disposal", "approve", "reject", "mark-disposed"])
def test_disposal_audit_failure_rolls_back_state_and_allows_retry(client, monkeypatch, action):
    _, headers = _actor()
    state = "received_by_waste_department" if action == "request-disposal" else "disposal_approved" if action == "mark-disposed" else "pending_disposal_approval"
    wid, rid = _fixture(state=state, request_state=None if action == "request-disposal" else "approved" if action == "mark-disposed" else "pending")
    path = f"/api/waste/{wid}/request-disposal" if action == "request-disposal" else f"/api/waste/disposal/{rid}/{action}"
    before = _snapshot(wid)
    original = waste.log_action

    def fail_audit(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Synthetic audit failure")

    monkeypatch.setattr(waste, "log_action", fail_audit)
    with pytest.raises(RuntimeError, match="Synthetic audit failure"):
        client.post(path, headers=headers, json={})
    assert _snapshot(wid) == before
    monkeypatch.setattr(waste, "log_action", original)
    response = client.post(path, headers=headers, json={})
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("action", ["approve", "mark-disposed"])
def test_legacy_sellable_disposal_request_cannot_progress(client, action):
    _, headers = _actor()
    wid, rid = _fixture(sellable=True, state="disposal_approved" if action == "mark-disposed" else "pending_disposal_approval",
                        request_state="approved" if action == "mark-disposed" else "pending")
    before = _snapshot(wid)
    assert client.post(f"/api/waste/disposal/{rid}/{action}", headers=headers).status_code == 400
    assert _snapshot(wid) == before


@pytest.mark.parametrize(("quantity", "sellable"), [
    (0, False), (-0.25, False), (float("inf"), False), (float("-inf"), False), (2.75, True),
])
def test_rejection_allows_safe_recovery_from_invalid_historical_pending_waste(client, quantity, sellable):
    actor_id, headers = _actor()
    wid, rid = _fixture(state="pending_disposal_approval", request_state="pending", quantity=quantity, sellable=sellable)
    before = _snapshot(wid)
    rejected = client.post(f"/api/waste/disposal/{rid}/reject", headers=headers)
    assert rejected.status_code == 200, rejected.text
    after = _snapshot(wid)
    assert after["record"]["status"] == "received_by_waste_department"
    assert after["record"]["quantity"] == before["record"]["quantity"]
    assert after["record"]["sellable"] == before["record"]["sellable"]
    assert after["requests"][0]["status"] == "rejected"
    assert after["requests"][0]["approved_by"] == actor_id
    assert after["audits"] == before["audits"] + 1
    for action in ("approve", "mark-disposed", "reject"):
        response = client.post(f"/api/waste/disposal/{rid}/{action}", headers=headers)
        assert response.status_code == 400, response.text
        assert _snapshot(wid) == after
    # Recovery does not make the invalid whole-record stock eligible for disposal.
    retry = client.post(f"/api/waste/{wid}/request-disposal", headers=headers, json={})
    assert retry.status_code == 400, retry.text
    assert _snapshot(wid) == after


@pytest.mark.parametrize("action", ["approve", "reject", "mark-disposed"])
def test_orphan_disposal_request_is_not_mutated(client, action):
    _, headers = _actor()
    with SessionLocal() as db:
        request = WasteDisposalRequest(waste_record_id=2_000_000_000,
                                       status="approved" if action == "mark-disposed" else "pending")
        db.add(request)
        db.commit()
        rid, original_status = request.id, request.status
        audit_count = db.query(AuditLog).count()
    response = client.post(f"/api/waste/disposal/{rid}/{action}", headers=headers)
    assert response.status_code == 404
    with SessionLocal() as db:
        request = db.get(WasteDisposalRequest, rid)
        assert request.status == original_status and request.approved_by is None and request.approved_at is None
        assert db.query(AuditLog).count() == audit_count


def test_nonfinite_legacy_numeric_nan_is_refused():
    # SQLite cannot store NaN in its NOT NULL numeric column; PostgreSQL numeric can.
    record = WasteRecord(status="received_by_waste_department", sellable=False, quantity=Decimal("NaN"))
    with pytest.raises(HTTPException) as denied:
        waste._require_disposal_waste(record, "received_by_waste_department")
    assert denied.value.status_code == 400


@pytest.fixture(scope="module")
def disposal_postgres_engine():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL disposal concurrency coverage")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Disposal concurrency tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"waste_disposal_{uuid4().hex}"
    engine = create_engine(
        url, connect_args={"options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"},
        pool_size=4, max_overflow=0, isolation_level="READ COMMITTED",
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        tables = {WasteRecord.__table__, WasteDisposalRequest.__table__, AuditLog.__table__}
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


@pytest.mark.parametrize("actions", [
    ("request-disposal", "request-disposal"), ("approve", "approve"), ("approve", "reject"),
    ("mark-disposed", "mark-disposed"),
])
def test_postgres_concurrent_disposal_has_one_effect_and_refreshes_cached_state(disposal_postgres_engine, actions):
    engine = disposal_postgres_engine
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    actors = [_actor(session_factory=sessions)[0] for _ in actions]
    is_request = actions[0] == "request-disposal"
    is_mark = actions[0] == "mark-disposed"
    wid, rid = _fixture(
        state="received_by_waste_department" if is_request else "disposal_approved" if is_mark else "pending_disposal_approval",
        request_state=None if is_request else "approved" if is_mark else "pending", session_factory=sessions,
    )
    before = _snapshot(wid, sessions)
    ready, start = Queue(), Event()

    def mutate(action, actor_id):
        with sessions() as db:
            # Keep strong references so a waiting request really has stale identity-map state.
            cached_waste = db.get(WasteRecord, wid)
            cached_request = db.get(WasteDisposalRequest, rid) if rid else None
            actor = db.get(User, actor_id)
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            assert start.wait(10), "Disposal workers were not started"
            try:
                if is_request:
                    result = waste.request_disposal(wid, waste.WasteDisposalIn(reason=f"Worker {actor_id}"), db, actor)
                else:
                    handler = {"approve": waste.approve_disposal, "reject": waste.reject_disposal, "mark-disposed": waste.mark_disposed}[action]
                    result = handler(rid, db, actor)
                assert cached_waste.status != before["record"]["status"]
                assert cached_request is None or cached_request is result
                return 200, action, actor_id
            except HTTPException as rejected:
                return rejected.status_code, action, actor_id

    with engine.connect() as holder, ThreadPoolExecutor(max_workers=2) as workers:
        holder.execute(text("SELECT id FROM waste_records WHERE id = :id FOR NO KEY UPDATE"), {"id": wid})
        futures = [workers.submit(mutate, action, actor) for action, actor in zip(actions, actors)]
        try:
            pids = [ready.get(timeout=10) for _ in futures]
            start.set()
            deadline = monotonic() + 10
            while monotonic() < deadline:
                if all(holder.execute(text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid}).scalar_one() for pid in pids):
                    break
                sleep(0.01)
            else:
                pytest.fail("Both disposal transactions did not reach a demonstrable lock wait")
        finally:
            start.set()
            holder.rollback()
        results = [future.result(timeout=20) for future in futures]
    assert sorted(result[0] for result in results) == [200, 400], results
    _, action, actor = next(result for result in results if result[0] == 200)
    after = _snapshot(wid, sessions)
    assert after["audits"] == before["audits"] + 1
    assert after["record"]["quantity"] == before["record"]["quantity"]
    assert len(after["requests"]) == 1
    expected = {"request-disposal": ("pending_disposal_approval", "pending"), "approve": ("disposal_approved", "approved"),
                "reject": ("received_by_waste_department", "rejected"), "mark-disposed": ("disposed", "disposed")}
    assert (after["record"]["status"], after["requests"][0]["status"]) == expected[action]
    if action in {"approve", "reject"}:
        assert after["requests"][0]["approved_by"] == actor
    if is_request:
        assert after["requests"][0]["requested_by"] == actor
