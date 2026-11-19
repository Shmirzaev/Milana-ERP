"""Receipt on a signed, migrated, explicitly approved PostgreSQL fixture."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from uuid import uuid4

from app.core.security import create_access_token
from app.models import audit_service
from app.schemas import AuditLog, Notification, WasteRecord
from app.tests.test_waste_create_receive_postgres import _app, _seed, pg_sessions  # noqa: F401


def seed(sessions):
    actor, denied, _, _ = _seed(sessions)
    with sessions.begin() as db:
        row = WasteRecord(waste_type='қирқим 🧵', quantity=4, unit='kg', sellable=True, status='recorded')
        db.add(row); db.flush()
        assert row.id > 0
        return actor, denied, row.id


def headers(actor):
    return {'Authorization': f'Bearer {create_access_token(actor)}'}


def audits(db, wid):
    return db.query(AuditLog).filter_by(entity_type='WasteRecord', entity_id=wid, action='receive').all()


def test_signed_receive_refusals_and_retained_readback(pg_sessions):
    actor, denied, wid = seed(pg_sessions)
    with pg_sessions() as retained:
        row = retained.get(WasteRecord, wid)
        notices = retained.query(Notification).count()
        with TestClient(_app(pg_sessions), raise_server_exceptions=False) as client:
            assert client.post(f'/waste/{wid}/receive').status_code == 401
            assert client.post(f'/waste/{wid}/receive', headers=headers(denied)).status_code == 403
            assert client.post('/waste/2147483647/receive', headers=headers(actor)).status_code == 404
            with pg_sessions() as db:
                assert db.get(WasteRecord, wid).status == 'recorded' and audits(db, wid) == []
            response = client.post(f'/waste/{wid}/receive', headers=headers(actor))
            assert response.status_code == 200, response.text
            assert response.json()['status'] == 'received_by_waste_department'
            assert client.post(f'/waste/{wid}/receive', headers=headers(actor)).status_code == 400
        assert row.status == 'recorded'
        retained.expire(row)
        assert row.status == 'received_by_waste_department' and row.waste_type == 'қирқим 🧵'
        rows = audits(retained, wid)
        assert len(rows) == 1 and rows[0].id > 0 and rows[0].user_id == actor and rows[0].entry_hash
        assert retained.query(Notification).count() == notices


@pytest.mark.parametrize('fault', ['audit', 'commit'])
def test_signed_receipt_finalization_commit_rollback_retry(pg_sessions, monkeypatch, fault):
    actor, _, wid = seed(pg_sessions)
    engine = pg_sessions.kw['bind']
    suffix = uuid4().hex[:12]
    trigger, function = f'pr390_guard_{suffix}', f'pr390_abort_{suffix}'
    attempted, observed = [], []
    finalize = audit_service._finalize_postgres_audits
    with pg_sessions() as db:
        notices = db.query(Notification).count()
        assert audits(db, wid) == []
    def observe_finalize(db):
        finalize(db)
        rows = audits(db, wid)
        assert len(rows) == 1 and rows[0].id > 0 and rows[0].entry_hash and rows[0].user_id == actor
        assert db.get(WasteRecord, wid).status == 'received_by_waste_department'
        attempted.append(rows[0].id)
        observed.append('finalized')
        if fault == 'audit':
            raise RuntimeError('injected after audit finalization')
    def capture(context):
        exc = context.original_exception
        if getattr(exc, 'pgcode', None) == '23514':
            observed.append((context.statement, exc.diag.constraint_name))
    if fault == 'commit':
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql(f"""CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
                    RAISE EXCEPTION 'fixture commit failure' USING ERRCODE = '23514', CONSTRAINT = '{trigger}'; END; $$""")
                conn.exec_driver_sql(f"""CREATE CONSTRAINT TRIGGER {trigger} AFTER UPDATE ON waste_records
                    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.id = {int(wid)}) EXECUTE FUNCTION {function}()""")
            event.listen(engine, 'handle_error', capture)
        except Exception as exc:
            raise RuntimeError(f'HOLD: uncertain setup; inspect {trigger} and {function}') from exc
    try:
        with monkeypatch.context() as patch:
            patch.setattr(audit_service, '_finalize_postgres_audits', observe_finalize)
            with TestClient(_app(pg_sessions), raise_server_exceptions=False) as client:
                assert client.post(f'/waste/{wid}/receive', headers=headers(actor)).status_code == 500
        assert observed == (['finalized'] if fault == 'audit' else ['finalized', (None, trigger)])
        assert len(attempted) == 1 and attempted[0] > 0
        with pg_sessions() as db:
            assert db.get(WasteRecord, wid).status == 'recorded'
            assert db.get(AuditLog, attempted[0]) is None and audits(db, wid) == []
            assert db.query(Notification).count() == notices
            assert audit_service.verify_audit_hash_chain(db)['ok']
    finally:
        if fault == 'commit':
            event.remove(engine, 'handle_error', capture)
            with engine.begin() as conn:
                conn.exec_driver_sql(f'DROP TRIGGER {trigger} ON waste_records')
                conn.exec_driver_sql(f'DROP FUNCTION {function}()')
    with TestClient(_app(pg_sessions), raise_server_exceptions=False) as client:
        response = client.post(f'/waste/{wid}/receive', headers=headers(actor))
        assert response.status_code == 200, response.text
    with pg_sessions() as db:
        assert db.get(WasteRecord, wid).status == 'received_by_waste_department'
        rows = audits(db, wid)
        assert len(rows) == 1 and rows[0].id > 0 and rows[0].id != attempted[0]
        assert rows[0].user_id == actor and rows[0].entry_hash
        assert db.query(Notification).count() == notices
        assert audit_service.verify_audit_hash_chain(db)['ok']


def test_signed_receipt_observed_wait_one_transition(pg_sessions):
    import sys
    import threading
    import time
    from fastapi import Request
    from sqlalchemy import text
    from app.core.deps import get_db
    from app.tests.pg_approved_instance import _park

    actor, _, wid = seed(pg_sessions)
    app = _app(pg_sessions)
    pids, responses, failures = {}, {}, []
    started = threading.Barrier(3, timeout=10)
    def isolated_db(request: Request):
        with pg_sessions() as db:
            pids[request.headers['X-Test-Request']] = db.scalar(text('select pg_backend_pid()'))
            yield db
    app.dependency_overrides[get_db] = isolated_db
    def receive(key):
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                started.wait()
                responses[key] = client.post(f'/waste/{wid}/receive', headers={**headers(actor), 'X-Test-Request': key})
        except BaseException as exc:
            failures.append(exc)
    with pg_sessions() as holder:
        holder.execute(text('select id from waste_records where id=:id for update'), {'id': wid}).one()
        holder_pid = holder.scalar(text('select pg_backend_pid()'))
        workers = [threading.Thread(target=receive, args=(str(i),), daemon=True) for i in range(2)]
        for worker in workers:
            worker.start()
        try:
            started.wait()
            deadline = time.monotonic() + 10
            proven = False
            with pg_sessions() as observer:
                while time.monotonic() < deadline:
                    if len(pids) == 2 and len(set(pids.values())) == 2:
                        def reaches_holder(pid):
                            pending, seen = [pid], set()
                            while pending:
                                current = pending.pop()
                                if current == holder_pid:
                                    return True
                                if current not in seen:
                                    seen.add(current)
                                    pending.extend(observer.scalar(text('select pg_blocking_pids(:pid)'), {'pid': current}))
                            return False
                        if all(reaches_holder(pid) for pid in pids.values()):
                            proven = True
                            break
                    time.sleep(0.05)
            assert proven, f'owned requests did not wait on holder: {pids}'
        finally:
            try:
                holder.rollback()
            finally:
                for worker in workers:
                    worker.join(25)
                if any(worker.is_alive() for worker in workers):
                    active = sys.exc_info()[1]
                    errors = ([active] if active else []) + failures
                    _park('PR390_RECEIPT_WORKERS_UNKNOWN', (pg_sessions, holder, workers, started, pids, responses), errors)
                    raise RuntimeError('HOLD observer unexpectedly returned')
    assert not failures and set(responses) == {'0', '1'}
    assert sorted(response.status_code for response in responses.values()) == [200, 400]
    assert next(r for r in responses.values() if r.status_code == 400).json() == {'detail': "Can't receive from status 'received_by_waste_department'"}
    with pg_sessions() as db:
        assert db.get(WasteRecord, wid).status == 'received_by_waste_department'
        rows = audits(db, wid)
        assert len(rows) == 1 and rows[0].id > 0 and rows[0].user_id == actor and rows[0].entry_hash
        assert audit_service.verify_audit_hash_chain(db)['ok']
