"""DELETE characterization on an independently approved disposable PostgreSQL instance."""
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.catalog import models_service as service
from app.schemas import AuditLog, Model, ModelSize, Role, User
from app.tests.pg_approved_instance import (
    ApprovedInstanceUnavailable, create_target_database, finalize_target,
    load_approved_instance, require_or_skip, target_engine,
)


@pytest.fixture(scope='module')
def pg_delete_sessions():
    try:
        instance = load_approved_instance()
    except ApprovedInstanceUnavailable as error:
        require_or_skip(error)
    target = create_target_database(instance)
    engine = None
    try:
        engine = target_engine(target, options='-cstatement_timeout=20000 -clock_timeout=10000')
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(settings, 'DATABASE_URL', engine.url.render_as_string(hide_password=False).replace('%', '%%'))
            patch.setattr(sa, 'engine_from_config', lambda *args, **kwargs: engine)
            command.upgrade(Config(str(Path(__file__).resolve().parents[2] / 'alembic.ini')), 'head')
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        finalize_target(target, engine)


@pytest.fixture
def delete_case(pg_delete_sessions):
    suffix = uuid4().hex[:10]
    with pg_delete_sessions.begin() as db:
        role = Role(name=f'Delete PG {suffix}', permissions=['modeling.models', 'usluga.manage'])
        db.add(role); db.flush()
        actor = User(name='Delete PG', email=f'delete-{suffix}@example.invalid', password_hash='unused', role_id=role.id, factory_code='ECO', is_active=True)
        models = [Model(code=f'DEL-STANDARD-{suffix}', name='Standard', catalog_scope='standard', factory_code='MIL'), Model(code=f'DEL-ECO-{suffix}', name='Eco', catalog_scope='usluga', factory_code='ECO')]
        db.add_all([actor, *models]); db.flush()
        sizes = [ModelSize(model_id=models[0].id, size='oʻlcham 🧵'), ModelSize(model_id=models[0].id, size='oʻlcham 🧵'), ModelSize(model_id=models[1].id, size='oʻlcham 🧵')]
        db.add_all(sizes); db.flush()
        return actor.id, [m.id for m in models], [s.id for s in sizes]


def test_delete_exact_id_and_audit(pg_delete_sessions, delete_case):
    actor, models, sizes = delete_case
    with pg_delete_sessions() as db:
        service.delete_size(db.get(User, actor), db, models[0], sizes[0])
    with pg_delete_sessions() as db:
        assert db.get(ModelSize, sizes[0]) is None
        assert [(db.get(ModelSize, sid).model_id, db.get(ModelSize, sid).size) for sid in sizes[1:]] == [(models[0], 'oʻlcham 🧵'), (models[1], 'oʻlcham 🧵')]
        audit = db.query(AuditLog).filter_by(entity_type='ModelSize', entity_id=sizes[0]).one()
        assert (audit.action, audit.user_id, audit.new_value_json) == ('delete', actor, {'model_id': models[0], 'size': 'oʻlcham 🧵'})
        assert audit.entry_hash


def test_delete_audit_failure_rolls_back_then_retry(pg_delete_sessions, delete_case, monkeypatch):
    actor, models, sizes = delete_case
    original = service.log_action
    def fail_after_audit(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('after audit')
    with monkeypatch.context() as patch:
        patch.setattr(service, 'log_action', fail_after_audit)
        with pg_delete_sessions() as db:
            with pytest.raises(RuntimeError, match='after audit'):
                service.delete_size(db.get(User, actor), db, models[0], sizes[0])
            db.rollback()
    with pg_delete_sessions() as db:
        assert db.get(ModelSize, sizes[0]) is not None
        assert db.query(AuditLog).filter_by(entity_type='ModelSize', entity_id=sizes[0]).count() == 0
        service.delete_size(db.get(User, actor), db, models[0], sizes[0])
    with pg_delete_sessions() as db:
        assert db.get(ModelSize, sizes[0]) is None
        assert db.query(AuditLog).filter_by(entity_type='ModelSize', entity_id=sizes[0]).count() == 1


def test_report_declared_incoming_fks(pg_delete_sessions):
    with pg_delete_sessions() as db:
        rows = db.execute(sa.text("""
            SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid)
            FROM pg_constraint WHERE contype = 'f' AND confrelid = 'model_sizes'::regclass
            ORDER BY 1, 2
        """)).all()
        print('MODEL_SIZE_INCOMING_FKS:', [tuple(row) for row in rows])
        # This candidate has no authorized schema migration or new incoming FK.
        assert rows == []


def test_pg_eco_and_wrong_scope_are_isolated(pg_delete_sessions, delete_case):
    from fastapi import HTTPException
    actor, models, sizes = delete_case
    with pg_delete_sessions() as db:
        with pytest.raises(HTTPException) as error:
            service.delete_size(db.get(User, actor), db, models[1], sizes[1], 'standard')
        assert (error.value.status_code, error.value.detail) == (404, 'Model not found')
        with pytest.raises(HTTPException) as error:
            service.delete_size(db.get(User, actor), db, models[0], sizes[2], 'standard')
        assert (error.value.status_code, error.value.detail) == (404, 'Size not found')
        db.rollback()
    with pg_delete_sessions() as db:
        assert all(db.get(ModelSize, sid) is not None for sid in sizes)
        service.delete_size(db.get(User, actor), db, models[1], sizes[2], 'usluga')
    with pg_delete_sessions() as db:
        assert db.get(ModelSize, sizes[2]) is None
        assert db.get(ModelSize, sizes[0]) is not None and db.get(ModelSize, sizes[1]) is not None
        audit = db.query(AuditLog).filter_by(entity_type='ModelSize', entity_id=sizes[2]).one()
        assert (audit.action, audit.user_id, audit.new_value_json) == ('delete', actor, {'model_id': models[1], 'size': 'oʻlcham 🧵'})


@pytest.mark.parametrize('failure', ['flush', 'commit'])
def test_pg_failure_rollback_retry(pg_delete_sessions, delete_case, monkeypatch, failure):
    actor, models, sizes = delete_case
    with pg_delete_sessions() as db:
        user = db.get(User, actor)
        with monkeypatch.context() as patch:
            def fail(*args, **kwargs):
                raise RuntimeError('injected ' + failure)
            patch.setattr(db, failure, fail)
            with pytest.raises(RuntimeError, match='injected ' + failure):
                service.delete_size(user, db, models[0], sizes[0])
        db.rollback()
    with pg_delete_sessions() as db:
        assert db.get(ModelSize, sizes[0]) is not None
        assert db.query(AuditLog).filter_by(entity_type='ModelSize', entity_id=sizes[0]).count() == 0
        service.delete_size(db.get(User, actor), db, models[0], sizes[0])
    with pg_delete_sessions() as db:
        assert db.get(ModelSize, sizes[0]) is None
        assert db.query(AuditLog).filter_by(entity_type='ModelSize', entity_id=sizes[0]).count() == 1


@pytest.mark.parametrize('same_id', [True, False])
def test_pg_two_session_delete_observed_outcomes(pg_delete_sessions, delete_case, monkeypatch, same_id):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    actor, models, sizes = delete_case
    selected = [sizes[0], sizes[0] if same_id else sizes[1]]
    barrier = Barrier(2)
    original = service.log_action
    def synchronized_audit(*args, **kwargs):
        barrier.wait(timeout=10)
        return original(*args, **kwargs)
    monkeypatch.setattr(service, 'log_action', synchronized_audit)
    def invoke(sid):
        with pg_delete_sessions() as db:
            try:
                service.delete_size(db.get(User, actor), db, models[0], sid)
                return 'success'
            except Exception as error:
                db.rollback()
                return type(error).__name__
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(invoke, selected))
    with pg_delete_sessions() as db:
        remaining = [sid for sid in set(selected) if db.get(ModelSize, sid) is not None]
        audits = db.query(AuditLog).filter(AuditLog.entity_type == 'ModelSize', AuditLog.entity_id.in_(selected)).order_by(AuditLog.id).all()
        chain = all(later.prev_hash == earlier.entry_hash for earlier, later in zip(audits, audits[1:]))
        print('MODEL_SIZE_DELETE_RACE:', {'same_id': same_id, 'outcomes': sorted(outcomes), 'remaining_count': len(remaining), 'audit_count': len(audits), 'audit_chain': chain})
        assert outcomes == ['success', 'success']
        assert remaining == [] and len(audits) == 2
        assert sorted(a.entity_id for a in audits) == sorted(selected
        )
        assert all(a.action == 'delete' and a.user_id == actor and a.entry_hash and a.new_value_json == {'model_id': models[0], 'size': 'oʻlcham 🧵'} for a in audits)
        assert db.get(ModelSize, sizes[2]).model_id == models[1]
        assert chain


def test_pg_before_commit_audit_finalization_failure_rolls_back_and_retries(pg_delete_sessions, delete_case, monkeypatch):
    from app.models import audit_service
    actor, models, sizes = delete_case
    original = audit_service.add_audit_log_rows
    def fail_after_persist(session, entries):
        original(session, entries)
        session.flush()
        assert session.query(AuditLog).filter_by(entity_type='ModelSize', entity_id=sizes[0]).count() == 1
        raise RuntimeError('after audit finalization flush')
    with monkeypatch.context() as patch:
        patch.setattr(audit_service, 'add_audit_log_rows', fail_after_persist)
        with pg_delete_sessions() as db:
            with pytest.raises(RuntimeError, match='after audit finalization flush'):
                service.delete_size(db.get(User, actor), db, models[0], sizes[0])
            db.rollback()
    with pg_delete_sessions() as db:
        assert db.get(ModelSize, sizes[0]) is not None
        assert db.query(AuditLog).filter_by(entity_type='ModelSize', entity_id=sizes[0]).count() == 0
        service.delete_size(db.get(User, actor), db, models[0], sizes[0])
    with pg_delete_sessions() as db:
        assert db.get(ModelSize, sizes[0]) is None
        assert db.query(AuditLog).filter_by(entity_type='ModelSize', entity_id=sizes[0]).count() == 1


def test_pg_concurrent_http_post_delete_and_failure_partial_commit(pg_delete_sessions, delete_case):
    """Characterize mixed API operations, not the browser Promise.all implementation."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes import catalog
    from app.core.deps import get_current_user
    from app.db.session import get_db
    actor_id, models, sizes = delete_case
    application = FastAPI()
    application.include_router(catalog.router, prefix='/api')
    def db_override():
        with pg_delete_sessions() as db:
            yield db
    def actor_override():
        with pg_delete_sessions() as db:
            actor = db.get(User, actor_id)
            _ = actor.role, actor.department
            db.expunge_all()
            return actor
    application.dependency_overrides[get_db] = db_override
    application.dependency_overrides[get_current_user] = actor_override
    barrier = Barrier(3)
    with TestClient(application) as client:
        def invoke(operation):
            barrier.wait(timeout=10)
            if operation == 'post':
                response = client.post(f'/api/models/{models[0]}/sizes', json={'size': '52', 'measurement_json': None})
                return response.status_code, response.json()['id']
            sid = sizes[0] if operation == 'delete' else 2147483647
            response = client.delete(f'/api/models/{models[0]}/sizes/{sid}')
            return response.status_code, None
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(invoke, ['post', 'delete', 'missing']))
    assert [result[0] for result in results] == [201, 204, 404]
    created = results[0][1]
    with pg_delete_sessions() as db:
        assert db.get(ModelSize, sizes[0]) is None
        assert (db.get(ModelSize, created).model_id, db.get(ModelSize, created).size) == (models[0], '52')
        assert db.get(ModelSize, sizes[1]) is not None and db.get(ModelSize, sizes[2]) is not None
        logs = db.query(AuditLog).filter(AuditLog.entity_type == 'ModelSize', AuditLog.entity_id.in_([sizes[0], created])).all()
        assert {(log.action, log.entity_id, log.user_id) for log in logs} == {('delete', sizes[0], actor_id), ('create', created, actor_id)}
