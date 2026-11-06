"""Disposal request atomicity on the guarded migrated PostgreSQL fixture."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.core.security import create_access_token
from app.models import audit_service
from app.schemas import AuditLog, Role, User, WasteDisposalRequest, WasteRecord
from app.tests.test_modelsize_create_postgres import pg_sessions as pg_sessions  # noqa: F401
from app.tests.test_waste_create_receive_postgres import _app, _public_snapshot


def _seed(sessions):
    suffix = uuid4().hex
    with sessions.begin() as db:
        allowed = Role(name=f'disposal-{suffix}', permissions=['waste.disposal'])
        denied = Role(name=f'disposal-denied-{suffix}', permissions=[])
        db.add_all([allowed, denied]); db.flush()
        actor = User(name='Disposal actor', email=f'{suffix}@example.invalid', password_hash='unused', role_id=allowed.id, factory_code='MIL', is_active=True)
        other = User(name='Denied actor', email=f'denied-{suffix}@example.invalid', password_hash='unused', role_id=denied.id, factory_code='MIL', is_active=True)
        record = WasteRecord(waste_type='fabric', quantity=2, unit='kg', sellable=False, status='received_by_waste_department')
        invalid = WasteRecord(waste_type='fabric', quantity=0, unit='kg', sellable=True, status='recorded')
        db.add_all([actor, other, record, invalid]); db.flush()
        return actor.id, other.id, record.id, invalid.id


def _assert_effect(sessions, wid, actor):
    with sessions() as db:
        assert db.get(WasteRecord, wid).status == 'pending_disposal_approval'
        request = db.query(WasteDisposalRequest).filter_by(waste_record_id=wid).one()
        assert (request.status, request.requested_by, request.reason) == ('pending', actor, 'test')
        audit = db.query(AuditLog).filter_by(entity_type='WasteRecord', entity_id=wid, action='request_disposal').one()
        assert audit.user_id == actor and audit.entry_hash
        assert audit_service.verify_audit_hash_chain(db)['ok']


def test_pg_disposal_http_refusal_and_audit_failure_retry(pg_sessions, monkeypatch):
    actor, denied, wid, invalid = _seed(pg_sessions)
    headers = {'Authorization': f'Bearer {create_access_token(actor)}'}
    denied_headers = {'Authorization': f'Bearer {create_access_token(denied)}'}
    path = f'/waste/{wid}/request-disposal'
    with pg_sessions() as db:
        before = _public_snapshot(db)
    with TestClient(_app(pg_sessions)) as client:
        assert client.post(path, headers=denied_headers, json={}).status_code == 403
        refusal = client.post(f'/waste/{invalid}/request-disposal', headers=headers, json={})
        assert refusal.status_code == 400
        assert refusal.json()['detail'] == "Cannot dispose from status 'recorded'"
        with pg_sessions() as db:
            assert _public_snapshot(db) == before
        original = audit_service.add_audit_log_rows
        calls = []
        def fail_after_flush(db, entries):
            original(db, entries)
            db.flush()
            calls.append(len(entries))
            raise RuntimeError('disposal audit finalization failure')
        with monkeypatch.context() as patch:
            patch.setattr(audit_service, 'add_audit_log_rows', fail_after_flush)
            with pytest.raises(RuntimeError, match='disposal audit finalization failure'):
                client.post(path, headers=headers, json={'reason': 'test'})
        assert calls == [1]
        with pg_sessions() as db:
            assert _public_snapshot(db) == before
            assert audit_service.verify_audit_hash_chain(db)['ok']
        response = client.post(path, headers=headers, json={'reason': 'test'})
        assert response.status_code == 200, response.text
    _assert_effect(pg_sessions, wid, actor)


def test_pg_disposal_deferred_commit_failure_retry(pg_sessions):
    actor, _, wid, _ = _seed(pg_sessions)
    headers = {'Authorization': f'Bearer {create_access_token(actor)}'}
    path = f'/waste/{wid}/request-disposal'
    engine = pg_sessions.kw['bind']
    observed = []
    with pg_sessions() as db:
        before = _public_snapshot(db)
    with engine.begin() as conn:
        conn.exec_driver_sql("""CREATE FUNCTION pr410_request_commit_abort() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'fixture commit failure' USING ERRCODE = '23514', CONSTRAINT = 'pr410_request_commit_guard'; END; $$""")
        conn.exec_driver_sql(f"""CREATE CONSTRAINT TRIGGER pr410_request_commit_guard AFTER INSERT ON waste_disposal_requests
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.waste_record_id = {int(wid)})
            EXECUTE FUNCTION pr410_request_commit_abort()""")
    def capture(context):
        exc = context.original_exception
        if getattr(exc, 'pgcode', None) == '23514':
            observed.append((context.statement, exc.diag.constraint_name))
    event.listen(engine, 'handle_error', capture)
    try:
        with TestClient(_app(pg_sessions), raise_server_exceptions=False) as client:
            failed = client.post(path, headers=headers, json={'reason': 'test'})
        assert failed.status_code == 500
        assert observed == [(None, 'pr410_request_commit_guard')]
        with pg_sessions() as db:
            assert _public_snapshot(db) == before
            assert audit_service.verify_audit_hash_chain(db)['ok']
    finally:
        event.remove(engine, 'handle_error', capture)
        with engine.begin() as conn:
            conn.exec_driver_sql('DROP TRIGGER pr410_request_commit_guard ON waste_disposal_requests')
            conn.exec_driver_sql('DROP FUNCTION pr410_request_commit_abort()')
    with TestClient(_app(pg_sessions)) as client:
        retry = client.post(path, headers=headers, json={'reason': 'test'})
        assert retry.status_code == 200, retry.text
    _assert_effect(pg_sessions, wid, actor)


def test_pg_disposal_request_race_serializes_on_parent(pg_sessions):
    from concurrent.futures import ThreadPoolExecutor
    from queue import Queue
    from threading import Event
    from time import monotonic, sleep

    from fastapi import HTTPException
    from sqlalchemy import text
    from app.libs.dto.inventory.waste_disposal_input import WasteDisposalIn
    from app.models.inventory import waste_service

    actor, _, wid, _ = _seed(pg_sessions)
    engine = pg_sessions.kw['bind']
    ready, start = Queue(), Event()

    def request():
        with pg_sessions() as db:
            cached = db.get(WasteRecord, wid)
            user = db.get(User, actor)
            ready.put(db.execute(text('SELECT pg_backend_pid()')).scalar_one())
            assert start.wait(10)
            try:
                waste_service.request_disposal(db, wid, WasteDisposalIn(reason='test'), user)
                assert cached.status == 'pending_disposal_approval'
                return 200
            except HTTPException as exc:
                return exc.status_code

    with engine.connect() as holder, ThreadPoolExecutor(max_workers=2) as workers:
        holder_pid = holder.execute(text('SELECT pg_backend_pid()')).scalar_one()
        holder.execute(text('SELECT id FROM waste_records WHERE id=:id FOR NO KEY UPDATE'), {'id': wid})
        futures = [workers.submit(request) for _ in range(2)]
        try:
            pids = [ready.get(timeout=10) for _ in futures]
            start.set()
            deadline = monotonic() + 10
            graph = {}
            owned = {*pids, holder_pid}

            def reaches_holder(pid, visited=frozenset()):
                if pid == holder_pid:
                    return True
                if pid in visited:
                    return False
                return any(reaches_holder(blocker, visited | {pid}) for blocker in graph.get(pid, ()))

            while monotonic() < deadline:
                graph = {pid: holder.execute(text('SELECT pg_blocking_pids(:pid)'), {'pid': pid}).scalar_one() for pid in pids}
                # PostgreSQL may queue a tuple-lock waiter behind the first waiter.
                # Require both live requests to reach ONLY our external parent holder.
                if (all(graph[pid] and set(graph[pid]) <= owned and reaches_holder(pid) for pid in pids)
                        and all(not future.done() for future in futures)):
                    print('OWNED_PARENT_WAIT_GRAPH', {'holder': holder_pid, 'workers': pids, 'blockers': graph})
                    break
                sleep(0.01)
            else:
                pytest.fail(f'Both requests did not enter the owned parent wait chain holder={holder_pid}; graph={graph}')
        finally:
            start.set()
            holder.rollback()
        assert sorted(future.result(timeout=20) for future in futures) == [200, 400]
    _assert_effect(pg_sessions, wid, actor)
