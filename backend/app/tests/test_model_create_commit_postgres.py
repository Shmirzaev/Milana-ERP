"""Model CREATE on a migrated, owned PostgreSQL instance; runtime qualification pending."""
from threading import Event, Lock
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from app.api.routes import catalog, usluga
from app.core.deps import get_db
from app.core.security import create_access_token
from app.libs.dto.catalog.model_input import ModelIn
from app.models import audit_service, numbering_service
from app.models.catalog import models_service
from app.schemas import AuditLog, Model, SystemSetting, User
from app.tests.pg_catalog_create_concurrency import run_catalog_create_pair

pytest_plugins = ("app.tests.test_modelcolor_create_postgres",)


def app_for(sessions):
    app = FastAPI()
    app.include_router(catalog.router, prefix="/api")
    app.include_router(usluga.router, prefix="/api")
    def session():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = session
    return app


def headers(actor):
    return {"Authorization": f"Bearer {create_access_token(actor)}"}


def snapshot(sessions):
    with sessions() as db:
        models = [(r.id, r.code, r.status, r.approved_by, r.approved_at, r.catalog_scope, r.factory_code)
                  for r in db.query(Model).order_by(Model.id)]
        audits = [(r.id, r.entity_type, r.entity_id, r.action, r.prev_hash, r.entry_hash)
                  for r in db.query(AuditLog).order_by(AuditLog.id)]
        setting = db.query(SystemSetting).filter_by(key=numbering_service.MODEL_NUMBER_SETTING_KEY).one_or_none()
        return models, audits, setting.value_json if setting else None


@pytest.mark.parametrize(('path', 'actor', 'scope', 'factory'), [
    ('/api/models', 'standard', 'standard', None),
    ('/api/usluga/models', 'eco', 'usluga', 'ECO'),
])
def test_pg_signed_create_auth_scope_and_retained_readback(pg_sessions, pg_case, path, actor, scope, factory):
    code = 'CREATE' + uuid4().hex[:16].upper()
    body = {'code': code, 'name': 'Synthetic create'}
    before = snapshot(pg_sessions)
    with TestClient(app_for(pg_sessions), raise_server_exceptions=False) as client:
        assert client.post(path, json=body).status_code == 401
        assert client.post(path, headers=headers(pg_case['actors']['denied']), json=body).status_code == 403
        if scope == 'usluga':
            assert client.post(path, headers=headers(pg_case['actors']['wrong_factory']), json=body).status_code == 403
        assert snapshot(pg_sessions) == before
        response = client.post(path, headers=headers(pg_case['actors'][actor]), json=body)
        assert response.status_code == 201, response.text
        assert client.post(path, headers=headers(pg_case['actors'][actor]), json=body).status_code == 400
    with pg_sessions() as retained:
        row = retained.get(Model, response.json()['id'])
        assert (row.code, row.status, row.catalog_scope, row.factory_code) == (code, 'draft', scope, factory)
        retained.expire(row)
        assert row.code == code
        assert retained.query(AuditLog).filter_by(entity_type='Model', entity_id=row.id, action='create').count() == 1


def test_pg_variant_inherits_approval_without_changing_family_or_other_scope(pg_sessions, pg_case):
    key = 'FAM' + uuid4().hex[:12].upper()
    actor = pg_case['actors']['standard']
    with pg_sessions.begin() as db:
        from datetime import datetime, timezone
        approved_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        base = Model(code=key, name='base', status='approved', approved_by=actor, approved_at=approved_at,
                     catalog_scope='standard', details_json={'general': {'model_no': key}})
        other = Model(code=key+'-OTHER', name='other', status='draft', catalog_scope='usluga', factory_code='ECO',
                      details_json={'general': {'model_no': key}})
        db.add_all([base, other]); db.flush(); base_id, other_id = base.id, other.id
    with pg_sessions() as retained:
        base = retained.get(Model, base_id); other = retained.get(Model, other_id)
        before = (base.status, base.approved_by, base.approved_at, other.status, other.approved_by, other.approved_at)
        with TestClient(app_for(pg_sessions), raise_server_exceptions=False) as client:
            response = client.post('/api/models', headers=headers(actor), json={'code': key+'-1', 'name': 'variant',
                'details_json': {'general': {'model_no': key, 'variant_no': '1'}}})
        assert response.status_code == 201, response.text
        retained.expire_all()
        row = retained.get(Model, response.json()['id'])
        assert (row.status, row.approved_by, row.approved_at) == before[:3]
        assert (base.status, base.approved_by, base.approved_at, other.status, other.approved_by, other.approved_at) == before


@pytest.mark.parametrize('fault', ['audit', 'commit'])
def test_pg_create_finalization_and_deferred_commit_rollback_retry(pg_sessions, pg_case, monkeypatch, fault):
    code = 'FAIL' + uuid4().hex[:16].upper()
    body = {'code': code, 'name': 'rollback'}
    app = app_for(pg_sessions); engine = pg_sessions.kw['bind']; before = snapshot(pg_sessions)
    observed = []
    original = audit_service._finalize_postgres_audits
    def fail_after_finalization(db):
        original(db)
        assert db.query(Model).filter_by(code=code).count() == 1
        observed.append('finalized')
        raise RuntimeError('injected after audit finalization')
    def capture(context):
        exc = context.original_exception
        if getattr(exc, 'pgcode', None) == '23514':
            observed.append((context.statement, exc.diag.constraint_name))
    if fault == 'commit':
        with engine.begin() as conn:
            conn.exec_driver_sql("""CREATE FUNCTION pr404_commit_abort() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
                RAISE EXCEPTION 'fixture commit failure' USING ERRCODE = '23514', CONSTRAINT = 'pr404_commit_guard'; END; $$""")
            conn.exec_driver_sql(f"""CREATE CONSTRAINT TRIGGER pr404_commit_guard AFTER INSERT ON models
                DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.code = '{code}')
                EXECUTE FUNCTION pr404_commit_abort()""")
        event.listen(engine, 'handle_error', capture)
    try:
        with monkeypatch.context() as patch:
            if fault == 'audit': patch.setattr(audit_service, '_finalize_postgres_audits', fail_after_finalization)
            with TestClient(app, raise_server_exceptions=False) as client:
                failed = client.post('/api/models', headers=headers(pg_case['actors']['standard']), json=body)
        assert failed.status_code == 500
        assert observed == (['finalized'] if fault == 'audit' else [(None, 'pr404_commit_guard')])
        assert snapshot(pg_sessions) == before
        with pg_sessions() as db: assert audit_service.verify_audit_hash_chain(db)['ok']
    finally:
        if fault == 'commit':
            event.remove(engine, 'handle_error', capture)
            with engine.begin() as conn:
                conn.exec_driver_sql('DROP TRIGGER pr404_commit_guard ON models')
                conn.exec_driver_sql('DROP FUNCTION pr404_commit_abort()')
    with TestClient(app, raise_server_exceptions=False) as client:
        retry = client.post('/api/models', headers=headers(pg_case['actors']['standard']), json=body)
    assert retry.status_code == 201, retry.text
    with pg_sessions() as db:
        assert db.get(Model, retry.json()['id']).code == code
        assert db.query(AuditLog).filter_by(entity_type='Model', entity_id=retry.json()['id'], action='create').count() == 1
        assert audit_service.verify_audit_hash_chain(db)['ok']


@pytest.mark.parametrize('lock_kind', ['numbering', 'family'])
def test_pg_create_serializes_on_numbering_and_family_lock(pg_sessions, pg_case, monkeypatch, lock_kind):
    """Observe an actual backend wait before releasing the first create transaction."""
    engine = pg_sessions.kw['bind']; guard = Lock(); pids = []; calls = []; acquired = Event()
    key = 'RACE' + uuid4().hex[:12].upper()
    if lock_kind == 'family':
        with pg_sessions.begin() as db:
            base = Model(code=key, name='base', status='approved', approved_by=pg_case['actors']['standard'],
                         catalog_scope='standard', details_json={'general': {'model_no': key}})
            db.add(base)
    original = models_service.next_model_no if lock_kind == 'numbering' else models_service._approval_family
    def observe(db, *args, **kwargs):
        with guard:
            order = len(calls); calls.append(db.scalar(text('select pg_backend_pid()')))
        if order == 0:
            result = original(db, *args, **kwargs)
            acquired.set()
            deadline = monotonic() + 10
            while monotonic() < deadline:
                with guard: second = calls[1] if len(calls) > 1 else None
                if second is not None:
                    with engine.connect() as connection:
                        waiting = connection.scalar(text('select :holder = any(pg_blocking_pids(:waiter))'),
                                                    {'holder': calls[0], 'waiter': second})
                    if waiting: return result
                sleep(0.02)
            raise AssertionError(f'{lock_kind} contender never waited on first create')
        assert acquired.wait(10)
        return original(db, *args, **kwargs)
    monkeypatch.setattr(models_service, 'next_model_no' if lock_kind == 'numbering' else '_approval_family', observe)
    def prepare(db):
        return db.get(User, pg_case['actors']['standard'])
    def create(db, actor):
        with guard:
            index = len(pids); pids.append(db.scalar(text('select pg_backend_pid()')))
        if lock_kind == 'numbering':
            payload = ModelIn(code='placeholder', name='numbered', automatic_model_prefix='FG')
        else:
            payload = ModelIn(code=f'{key}-{index + 1}', name='variant',
                              details_json={'general': {'model_no': key, 'variant_no': str(index + 1)}})
        return models_service.create_model(actor, db, payload)['id']
    ids = run_catalog_create_pair(pg_sessions, prepare, create, timeout=30)
    assert len(set(ids)) == 2 and len(set(pids)) == 2 and len(calls) == 2
    with pg_sessions() as db:
        rows = [db.get(Model, mid) for mid in ids]
        assert len({row.code for row in rows}) == 2
        if lock_kind == 'numbering':
            assert all(row.code.startswith('FG') for row in rows)
        else:
            assert all(row.status == 'approved' and row.approved_by == pg_case['actors']['standard'] for row in rows)
        assert db.query(AuditLog).filter(AuditLog.entity_type == 'Model', AuditLog.entity_id.in_(ids), AuditLog.action == 'create').count() == 2
        assert audit_service.verify_audit_hash_chain(db)['ok']
