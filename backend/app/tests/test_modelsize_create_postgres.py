"""Owned PostgreSQL ModelSize CREATE integrity checks; guarded disposable target only."""
from pathlib import Path
import sys
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.libs.dto.catalog.model_size_input import ModelSizeIn
from app.libs.enums.catalog import CatalogScope
from app.models.catalog import models_service as service
from app.schemas import AuditLog, Model, ModelSize, Role, User
from app.tests.pg_approved_instance import (
    ApprovedInstanceUnavailable, create_target_database, finalize_target,
    load_approved_instance, require_or_skip, retain_fixture_uncertainty, target_engine,
)

from app.tests.pg_catalog_create_concurrency import run_catalog_create_pair


@pytest.fixture(scope='module')
def pg_sessions():
    try:
        instance = load_approved_instance()
    except ApprovedInstanceUnavailable as error:
        require_or_skip(error)
    target = create_target_database(instance)
    engine = None
    sessions = None
    try:
        engine = target_engine(target, options='-cstatement_timeout=20000 -clock_timeout=10000')
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(settings, 'DATABASE_URL', engine.url.render_as_string(hide_password=False).replace('%', '%%'))
            patch.setattr(sa, 'engine_from_config', lambda *args, **kwargs: engine)
            command.upgrade(Config(str(Path(__file__).resolve().parents[2] / 'alembic.ini')), 'head')
        sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        yield sessions
    finally:
        prior_error = sys.exception()
        if sessions is not None:
            try:
                sessions.configure(bind=None)
            except BaseException as error:
                retain_fixture_uncertainty(target, engine, sessions, error, prior_error=prior_error)
        finalize_target(target, engine)


@pytest.fixture
def pg_case(pg_sessions):
    suffix = uuid4().hex[:10]
    with pg_sessions.begin() as db:
        role = Role(name=f'Size PG role {suffix}', permissions=['modeling.models', 'usluga.manage'])
        db.add(role); db.flush()
        actor = User(name='Size PG actor', email=f'size-pg-{suffix}@example.invalid', password_hash='unused', role_id=role.id, factory_code='ECO', is_active=True)
        models = [Model(code=f'SIZE-PG-STANDARD-{suffix}', name='Standard', catalog_scope='standard', factory_code='MIL'), Model(code=f'SIZE-PG-ECO-{suffix}', name='Eco', catalog_scope='usluga', factory_code='ECO')]
        db.add_all([actor, *models]); db.flush()
        return actor.id, [m.id for m in models]


def test_pg_create_atomic_audit_and_failure_retry(pg_sessions, pg_case, monkeypatch):
    actor_id, mids = pg_case
    for mid, scope in zip(mids, [CatalogScope.STANDARD, CatalogScope.USLUGA]):
        with pg_sessions() as db:
            result = service.add_size(db.get(User, actor_id), db, mid, ModelSizeIn(size='oʻlcham 🧵', measurement_json={'грудь': 42}), scope)
        with pg_sessions() as db:
            row = db.get(ModelSize, result['id'])
            assert (row.model_id, row.size, row.measurement_json) == (mid, 'oʻlcham 🧵', {'грудь': 42})
            audit = db.query(AuditLog).filter_by(entity_type='ModelSize', entity_id=row.id).one()
            assert (audit.action, audit.user_id, audit.new_value_json) == ('create', actor_id, {'model_id': mid, 'size': row.size})
            assert audit.entry_hash
    original = service.log_action
    def fail_after_append(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('after audit queue')
    with monkeypatch.context() as patch:
        patch.setattr(service, 'log_action', fail_after_append)
        with pg_sessions() as db:
            with pytest.raises(RuntimeError, match='after audit queue'):
                service.add_size(db.get(User, actor_id), db, mids[0], ModelSizeIn(size='retry'))
            db.rollback()
    with pg_sessions() as db:
        assert db.query(ModelSize).filter_by(model_id=mids[0], size='retry').count() == 0
        assert db.query(AuditLog).filter(AuditLog.entity_type == 'ModelSize', AuditLog.new_value_json['size'].as_string() == 'retry').count() == 0
        result = service.add_size(db.get(User, actor_id), db, mids[0], ModelSizeIn(size='retry'))
    with pg_sessions() as db:
        assert db.get(ModelSize, result['id']).size == 'retry'
        assert db.query(AuditLog).filter_by(entity_type='ModelSize', entity_id=result['id']).count() == 1


def test_pg_concurrent_duplicate_creates(pg_sessions, pg_case):
    actor_id, mids = pg_case
    def prepare(db):
        return db.get(User, actor_id)
    def create(db, actor):
        return service.add_size(actor, db, mids[0], ModelSizeIn(size='duplicate'))['id']
    ids = run_catalog_create_pair(pg_sessions, prepare, create)
    assert len(set(ids)) == 2
    with pg_sessions() as db:
        assert db.query(ModelSize).filter(ModelSize.id.in_(ids), ModelSize.size == 'duplicate').count() == 2
        audits = db.query(AuditLog).filter(AuditLog.entity_type == 'ModelSize', AuditLog.entity_id.in_(ids)).order_by(AuditLog.id).all()
        assert len(audits) == 2 and all(a.entry_hash for a in audits)
        assert audits[1].prev_hash == audits[0].entry_hash
