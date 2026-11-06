"""Mark-disposed source coverage for the guarded migrated PostgreSQL fixture."""
from datetime import datetime, timezone
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
        allowed = Role(name=f'mark-{suffix}', permissions=['waste.disposal'])
        denied = Role(name=f'mark-denied-{suffix}', permissions=[])
        db.add_all([allowed, denied]); db.flush()
        actor = User(name='Mark actor', email=f'{suffix}@example.invalid', password_hash='unused', role_id=allowed.id, factory_code='MIL', is_active=True)
        other = User(name='Denied', email=f'denied-{suffix}@example.invalid', password_hash='unused', role_id=denied.id, factory_code='MIL', is_active=True)
        record = WasteRecord(waste_type='fabric', quantity=2, unit='kg', sellable=False, status='disposal_approved')
        db.add_all([actor, other, record]); db.flush()
        request = WasteDisposalRequest(waste_record_id=record.id, reason='test', status='approved', requested_by=actor.id, approved_by=actor.id, approved_at=datetime(2025, 1, 1, tzinfo=timezone.utc), proof_file_url='fixture')
        db.add(request); db.flush()
        return actor.id, other.id, record.id, request.id


def _effect(sessions, wid, rid, actor):
    with sessions() as db:
        record, request = db.get(WasteRecord, wid), db.get(WasteDisposalRequest, rid)
        assert record.status == request.status == 'disposed'
        assert (request.approved_by, request.approved_at, request.requested_by, request.reason, request.proof_file_url) == (actor, datetime(2025, 1, 1, tzinfo=timezone.utc), actor, 'test', 'fixture')
        audit = db.query(AuditLog).filter_by(entity_type='WasteDisposalRequest', entity_id=rid, action='mark_disposed').one()
        assert audit.user_id == actor and audit.entry_hash
        assert audit_service.verify_audit_hash_chain(db)['ok']


def test_pg_mark_disposed_auth_refusal_audit_failure_retry(pg_sessions, monkeypatch):
    actor, denied, wid, rid = _seed(pg_sessions)
    path = f'/waste/disposal/{rid}/mark-disposed'
    headers = {'Authorization': f'Bearer {create_access_token(actor)}'}
    with pg_sessions() as db:
        before = _public_snapshot(db)
    with TestClient(_app(pg_sessions)) as client:
        assert client.post(path).status_code == 401
        assert client.post(path, headers={'Authorization': f'Bearer {create_access_token(denied)}'}).status_code == 403
        assert client.post('/waste/disposal/2000000000/mark-disposed', headers=headers).status_code == 404
        original = audit_service.add_audit_log_rows
        calls = []
        def fail(db, entries):
            original(db, entries); db.flush(); calls.append(len(entries))
            raise RuntimeError('mark audit finalization failure')
        with monkeypatch.context() as patch:
            patch.setattr(audit_service, 'add_audit_log_rows', fail)
            with pytest.raises(RuntimeError, match='mark audit finalization failure'):
                client.post(path, headers=headers)
        assert calls == [1]
        with pg_sessions() as db:
            assert _public_snapshot(db) == before
            assert audit_service.verify_audit_hash_chain(db)['ok']
        response = client.post(path, headers=headers)
        assert response.status_code == 200, response.text
        duplicate = client.post(path, headers=headers)
        assert duplicate.status_code == 400
        assert duplicate.json()['detail'] == 'Disposal not approved yet'
    _effect(pg_sessions, wid, rid, actor)


def test_pg_mark_disposed_deferred_commit_failure_retry(pg_sessions):
    actor, _, wid, rid = _seed(pg_sessions)
    path = f'/waste/disposal/{rid}/mark-disposed'
    headers = {'Authorization': f'Bearer {create_access_token(actor)}'}
    engine = pg_sessions.kw['bind']
    observed = []
    with pg_sessions() as db:
        before = _public_snapshot(db)
    with engine.begin() as conn:
        conn.exec_driver_sql("""CREATE FUNCTION pr409_mark_commit_abort() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'fixture commit failure' USING ERRCODE = '23514', CONSTRAINT = 'pr409_mark_commit_guard'; END; $$""")
        conn.exec_driver_sql(f"""CREATE CONSTRAINT TRIGGER pr409_mark_commit_guard AFTER UPDATE ON waste_disposal_requests
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.id = {int(rid)} AND NEW.status = 'disposed')
            EXECUTE FUNCTION pr409_mark_commit_abort()""")
    def capture(context):
        exc = context.original_exception
        if getattr(exc, 'pgcode', None) == '23514':
            observed.append((context.statement, exc.diag.constraint_name))
    event.listen(engine, 'handle_error', capture)
    try:
        with TestClient(_app(pg_sessions), raise_server_exceptions=False) as client:
            assert client.post(path, headers=headers).status_code == 500
        assert observed == [(None, 'pr409_mark_commit_guard')]
        with pg_sessions() as db:
            assert _public_snapshot(db) == before
            assert audit_service.verify_audit_hash_chain(db)['ok']
    finally:
        event.remove(engine, 'handle_error', capture)
        with engine.begin() as conn:
            conn.exec_driver_sql('DROP TRIGGER pr409_mark_commit_guard ON waste_disposal_requests')
            conn.exec_driver_sql('DROP FUNCTION pr409_mark_commit_abort()')
    with TestClient(_app(pg_sessions)) as client:
        response = client.post(path, headers=headers)
        assert response.status_code == 200, response.text
    _effect(pg_sessions, wid, rid, actor)


def test_pg_mark_disposed_race_serializes_on_parent(pg_sessions):
    from concurrent.futures import ThreadPoolExecutor
    from queue import Queue
    from threading import Event
    from time import monotonic, sleep
    from fastapi import HTTPException
    from sqlalchemy import text
    from app.models.inventory import waste_service

    actor, _, wid, rid = _seed(pg_sessions)
    engine = pg_sessions.kw['bind']
    ready, start = Queue(), Event()
    def mark():
        with pg_sessions() as db:
            cached = db.get(WasteRecord, wid)
            user = db.get(User, actor)
            ready.put(db.execute(text('SELECT pg_backend_pid()')).scalar_one())
            assert start.wait(10)
            try:
                waste_service.mark_disposed(db, rid, user)
                assert cached.status == 'disposed'
                return 200
            except HTTPException as exc:
                return exc.status_code
    with engine.connect() as holder, ThreadPoolExecutor(max_workers=2) as workers:
        holder_pid = holder.execute(text('SELECT pg_backend_pid()')).scalar_one()
        holder.execute(text('SELECT id FROM waste_records WHERE id=:id FOR NO KEY UPDATE'), {'id': wid})
        futures = [workers.submit(mark) for _ in range(2)]
        try:
            pids = [ready.get(timeout=10) for _ in futures]
            start.set()
            deadline = monotonic() + 10
            while monotonic() < deadline:
                if all(holder_pid in holder.execute(text('SELECT pg_blocking_pids(:pid)'), {'pid': pid}).scalar_one() for pid in pids):
                    break
                sleep(0.01)
            else:
                pytest.fail('Both mark requests did not wait on the owned parent lock')
        finally:
            start.set()
            holder.rollback()
        assert sorted(future.result(timeout=20) for future in futures) == [200, 400]
    _effect(pg_sessions, wid, rid, actor)
