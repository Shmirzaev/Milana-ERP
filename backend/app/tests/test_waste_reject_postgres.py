"""Rejection source coverage for the guarded migrated PostgreSQL fixture."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from app.core.security import create_access_token
from app.models import audit_service
from app.schemas import AuditLog, Role, User, WasteDisposalRequest, WasteRecord
from app.tests.test_modelsize_create_postgres import pg_sessions as pg_sessions  # noqa: F401
from app.tests.test_waste_create_receive_postgres import _app, _public_snapshot


def _seed(sessions):
    suffix = uuid4().hex
    with sessions.begin() as db:
        allowed = Role(name=f'mark-{suffix}', permissions=['management.approve'])
        denied = Role(name=f'mark-denied-{suffix}', permissions=[])
        db.add_all([allowed, denied]); db.flush()
        actor = User(name='Mark actor', email=f'{suffix}@example.invalid', password_hash='unused', role_id=allowed.id, factory_code='MIL', is_active=True)
        other = User(name='Denied', email=f'denied-{suffix}@example.invalid', password_hash='unused', role_id=denied.id, factory_code='MIL', is_active=True)
        record = WasteRecord(waste_type='fabric', quantity=2, unit='kg', sellable=False, status='pending_disposal_approval')
        db.add_all([actor, other, record]); db.flush()
        request = WasteDisposalRequest(waste_record_id=record.id, reason='test', status='pending', requested_by=actor.id, proof_file_url='fixture')
        db.add(request); db.flush()
        return actor.id, other.id, record.id, request.id


def _effect(sessions, wid, rid, actor, started, completed):
    with sessions() as db:
        record, request = db.get(WasteRecord, wid), db.get(WasteDisposalRequest, rid)
        assert record.status == 'received_by_waste_department' and request.status == 'rejected'
        assert request.approved_by == actor and started <= request.approved_at <= completed
        assert (request.requested_by, request.reason, request.proof_file_url) == (actor, 'test', 'fixture')
        audit = db.query(AuditLog).filter_by(entity_type='WasteDisposalRequest', entity_id=rid, action='reject_disposal').one()
        assert audit.user_id == actor and audit.entry_hash
        assert audit_service.verify_audit_hash_chain(db)['ok']


def _refusal_snapshot(sessions, wid, rid):
    # Project quantity as database text so numeric NaN compares deterministically.
    with sessions() as db:
        parent = db.execute(text("""SELECT (to_jsonb(w) - 'quantity')::text, quantity::text
            FROM waste_records w WHERE id=:wid"""), {'wid': wid}).one()
        request = db.execute(text("""SELECT row_to_json(r)::text FROM waste_disposal_requests r
            WHERE id=:rid"""), {'rid': rid}).scalar_one()
        audits = db.execute(text("""SELECT row_to_json(a)::text FROM audit_logs a
            WHERE (entity_type='WasteRecord' AND entity_id=:wid)
               OR (entity_type='WasteDisposalRequest' AND entity_id=:rid)
            ORDER BY id"""), {'wid': wid, 'rid': rid}).scalars().all()
        return tuple(parent), request, audits


def _assert_refusal(sessions, actor, wid, rid, detail):
    before = _refusal_snapshot(sessions, wid, rid)
    headers = {'Authorization': f'Bearer {create_access_token(actor)}'}
    with TestClient(_app(sessions)) as client:
        response = client.post(f'/waste/disposal/{rid}/reject', headers=headers)
    assert response.status_code == 400
    assert response.json() == {'detail': detail}
    assert _refusal_snapshot(sessions, wid, rid) == before


@pytest.mark.parametrize('request_state', ['approved', 'rejected', 'disposed'])
def test_pg_reject_refuses_request_before_invalid_parent(pg_sessions, request_state):
    actor, _, wid, rid = _seed(pg_sessions)
    with pg_sessions.begin() as db:
        db.execute(text("UPDATE waste_records SET status='recorded', sellable=true, quantity=0 WHERE id=:wid"), {'wid': wid})
        db.execute(text('UPDATE waste_disposal_requests SET status=:state WHERE id=:rid'), {'state': request_state, 'rid': rid})
    _assert_refusal(pg_sessions, actor, wid, rid, 'Disposal request is not pending')


@pytest.mark.parametrize('parent_state', [
    'recorded', 'received_by_waste_department', 'sold', 'disposal_approved', 'disposed',
])
def test_pg_reject_refuses_invalid_parent(pg_sessions, parent_state):
    actor, _, wid, rid = _seed(pg_sessions)
    with pg_sessions.begin() as db:
        db.execute(text('UPDATE waste_records SET status=:state WHERE id=:wid'), {'state': parent_state, 'wid': wid})
    _assert_refusal(pg_sessions, actor, wid, rid, f"Cannot dispose from status '{parent_state}'")


@pytest.mark.parametrize(('sellable', 'quantity'), [(True, '2'), (False, '0'), (False, '-0.25'), (False, 'NaN')])
def test_pg_reject_recovers_invalid_historical_parent(pg_sessions, sellable, quantity):
    actor, _, wid, rid = _seed(pg_sessions)
    with pg_sessions.begin() as db:
        db.execute(text('UPDATE waste_records SET sellable=:sellable, quantity=CAST(:quantity AS numeric) WHERE id=:wid'),
                   {'sellable': sellable, 'quantity': quantity, 'wid': wid})
    started = datetime.now(timezone.utc)
    with TestClient(_app(pg_sessions)) as client:
        response = client.post(f'/waste/disposal/{rid}/reject', headers={'Authorization': f'Bearer {create_access_token(actor)}'})
    completed = datetime.now(timezone.utc)
    assert response.status_code == 200, response.text
    _effect(pg_sessions, wid, rid, actor, started, completed)


def test_pg_reject_auth_refusal_audit_failure_retry(pg_sessions, monkeypatch):
    actor, denied, wid, rid = _seed(pg_sessions)
    path = f'/waste/disposal/{rid}/reject'
    headers = {'Authorization': f'Bearer {create_access_token(actor)}'}
    with pg_sessions() as db:
        before = _public_snapshot(db)
    with TestClient(_app(pg_sessions)) as client:
        assert client.post(path).status_code == 401
        assert client.post(path, headers={'Authorization': f'Bearer {create_access_token(denied)}'}).status_code == 403
        assert client.post('/waste/disposal/2000000000/reject', headers=headers).status_code == 404
        original = audit_service.add_audit_log_rows
        calls = []
        def fail(db, entries):
            original(db, entries); db.flush(); calls.append(len(entries))
            raise RuntimeError('rejection audit finalization failure')
        with monkeypatch.context() as patch:
            patch.setattr(audit_service, 'add_audit_log_rows', fail)
            with pytest.raises(RuntimeError, match='rejection audit finalization failure'):
                client.post(path, headers=headers)
        assert calls == [1]
        with pg_sessions() as db:
            assert _public_snapshot(db) == before
            assert audit_service.verify_audit_hash_chain(db)['ok']
        started = datetime.now(timezone.utc)
        response = client.post(path, headers=headers)
        completed = datetime.now(timezone.utc)
        assert response.status_code == 200, response.text
        duplicate = client.post(path, headers=headers)
        assert duplicate.status_code == 400
        assert duplicate.json()['detail'] == 'Disposal request is not pending'
    _effect(pg_sessions, wid, rid, actor, started, completed)


def test_pg_reject_deferred_commit_failure_retry(pg_sessions):
    actor, _, wid, rid = _seed(pg_sessions)
    path = f'/waste/disposal/{rid}/reject'
    headers = {'Authorization': f'Bearer {create_access_token(actor)}'}
    engine = pg_sessions.kw['bind']
    observed = []
    with pg_sessions() as db:
        before = _public_snapshot(db)
    with engine.begin() as conn:
        conn.exec_driver_sql("""CREATE FUNCTION pr408_rejection_commit_abort() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'fixture commit failure' USING ERRCODE = '23514', CONSTRAINT = 'pr408_rejection_commit_guard'; END; $$""")
        conn.exec_driver_sql(f"""CREATE CONSTRAINT TRIGGER pr408_rejection_commit_guard AFTER UPDATE ON waste_disposal_requests
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.id = {int(rid)} AND NEW.status = 'rejected')
            EXECUTE FUNCTION pr408_rejection_commit_abort()""")
    def capture(context):
        exc = context.original_exception
        if getattr(exc, 'pgcode', None) == '23514':
            observed.append((context.statement, exc.diag.constraint_name))
    event.listen(engine, 'handle_error', capture)
    try:
        with TestClient(_app(pg_sessions), raise_server_exceptions=False) as client:
            assert client.post(path, headers=headers).status_code == 500
        assert observed == [(None, 'pr408_rejection_commit_guard')]
        with pg_sessions() as db:
            assert _public_snapshot(db) == before
            assert audit_service.verify_audit_hash_chain(db)['ok']
    finally:
        event.remove(engine, 'handle_error', capture)
        with engine.begin() as conn:
            conn.exec_driver_sql('DROP TRIGGER pr408_rejection_commit_guard ON waste_disposal_requests')
            conn.exec_driver_sql('DROP FUNCTION pr408_rejection_commit_abort()')
    with TestClient(_app(pg_sessions)) as client:
        started = datetime.now(timezone.utc)
        response = client.post(path, headers=headers)
        completed = datetime.now(timezone.utc)
        assert response.status_code == 200, response.text
    _effect(pg_sessions, wid, rid, actor, started, completed)


@pytest.mark.parametrize('second', ['reject', 'approve'])
def test_pg_rejection_race_serializes_on_parent(pg_sessions, second):
    from concurrent.futures import ThreadPoolExecutor
    from queue import Queue
    from threading import Event
    from time import monotonic, sleep
    from fastapi import HTTPException
    from app.models.inventory import waste_service

    actor, _, wid, rid = _seed(pg_sessions)
    with pg_sessions.begin() as db:
        role = Role(name=f'rejection-race-{uuid4().hex}', permissions=['management.approve'])
        db.add(role); db.flush()
        other = User(name='Other rejectr', email=f'{uuid4().hex}@example.invalid', password_hash='unused', role_id=role.id, factory_code='MIL', is_active=True)
        db.add(other); db.flush()
        other_actor = other.id
    engine = pg_sessions.kw['bind']
    ready, start = Queue(), Event()

    def decide(action, actor_id):
        with pg_sessions() as db:
            parent = db.get(WasteRecord, wid)
            request = db.get(WasteDisposalRequest, rid)
            user = db.get(User, actor_id)
            assert parent.status == 'pending_disposal_approval' and request.status == 'pending'
            ready.put(db.execute(text('SELECT pg_backend_pid()')).scalar_one())
            assert start.wait(10)
            try:
                getattr(waste_service, f'{action}_disposal')(db, rid, user)
                expected = ('rejected', 'received_by_waste_department') if action == 'reject' else ('approved', 'disposal_approved')
                assert (request.status, parent.status) == expected
                return 200, actor_id, action
            except HTTPException as exc:
                return exc.status_code, actor_id, action

    with engine.connect() as holder, ThreadPoolExecutor(max_workers=2) as workers:
        holder_pid = holder.execute(text('SELECT pg_backend_pid()')).scalar_one()
        holder.execute(text('SELECT id FROM waste_records WHERE id=:id FOR NO KEY UPDATE'), {'id': wid})
        futures = [workers.submit(decide, action, actor_id) for action, actor_id in (('reject', actor), (second, other_actor))]
        try:
            pids = [ready.get(timeout=10) for _ in futures]
            started = datetime.now(timezone.utc)
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
                if (all(graph[pid] and set(graph[pid]) <= owned and reaches_holder(pid) for pid in pids)
                        and all(not future.done() for future in futures)):
                    print('OWNED_PARENT_WAIT_GRAPH', {'holder': holder_pid, 'workers': pids, 'blockers': graph})
                    break
                sleep(0.01)
            else:
                pytest.fail(f'Both rejection decisions did not enter owned parent wait chain holder={holder_pid}; graph={graph}')
        finally:
            start.set()
            holder.rollback()
        results = [f.result(timeout=20) for f in futures]
        completed = datetime.now(timezone.utc)
        assert sorted(result[0] for result in results) == [200, 400]
        _, winner, action = next(result for result in results if result[0] == 200)
    with pg_sessions() as db:
        parent, request = db.get(WasteRecord, wid), db.get(WasteDisposalRequest, rid)
        assert (request.status, parent.status) == (('rejected', 'received_by_waste_department') if action == 'reject' else ('approved', 'disposal_approved'))
        if second == 'reject':
            assert request.status == 'rejected'
        assert request.approved_by == winner and started <= request.approved_at <= completed
        assert (request.requested_by, request.reason, request.proof_file_url) == (actor, 'test', 'fixture')
        rows = db.query(AuditLog).filter_by(entity_type='WasteDisposalRequest', entity_id=rid).all()
        assert len(rows) == 1
        assert rows[0].action == ('reject_disposal' if request.status == 'rejected' else 'approve_disposal')
        assert rows[0].user_id == winner and rows[0].entry_hash
        assert audit_service.verify_audit_hash_chain(db)['ok']
