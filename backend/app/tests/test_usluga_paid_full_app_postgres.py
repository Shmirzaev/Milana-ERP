"""Full-app Usluga HTTP and middleware checks against an approved disposable PG database."""
from copy import deepcopy
import sqlite3
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core import shared_store
from app.core.config import settings
from app.core.deps import get_db
from app.core.security import create_access_token
from app.main import app
from app.models import audit_service
from app.schemas import AuditLog, Model, Role, User
from app.tests.test_modelsize_create_postgres import pg_sessions as pg_sessions  # noqa: F401
from app.tests.test_paid_operation_factory_scope import _operation


def test_full_app_usluga_paid_auth_middleware_and_persistence(pg_sessions, monkeypatch, tmp_path):  # noqa: F811
    # Startup must not seed or mutate schema. The test fixture has already migrated
    # the approved, disposable database. Strict startup migration checking is not
    # covered here because the application test configuration is development.
    monkeypatch.setenv('RUN_SEED_ON_STARTUP', 'false')
    assert not settings.STARTUP_SCHEMA_SYNC
    assert not settings.strict_security_required
    assert settings.GLOBAL_RATE_LIMIT_ENABLED
    counter = shared_store.SQLiteSharedCounterStore(f'sqlite:///{tmp_path / "counter.db"}', prefix='usluga-full-test')
    monkeypatch.setattr(shared_store, '_store', counter)

    def isolated_db():
        with pg_sessions() as db:
            yield db

    monkeypatch.setitem(app.dependency_overrides, get_db, isolated_db)
    suffix = uuid4().hex[:10]
    with pg_sessions.begin() as db:
        roles = [Role(name=f'full-usluga-{suffix}-{i}', permissions=permissions)
                 for i, permissions in enumerate(([], ['usluga.manage'], ['usluga.manage']))]
        db.add_all(roles)
        db.flush()
        actors = [User(name=f'actor-{i}', email=f'full-usluga-{suffix}-{i}@example.invalid',
                       password_hash='unused', role_id=role.id, factory_code=factory, is_active=True)
                  for i, (role, factory) in enumerate(zip(roles, ('ECO', 'MIL', 'ECO')))]
        model = Model(code=f'FULL-USLUGA-{suffix}', name='Usluga full app test', status='draft',
                      catalog_scope='usluga', factory_code='ECO', details_json={})
        db.add_all([*actors, model])
        db.flush()
        ids, model_id = [actor.id for actor in actors], model.id

    def headers(actor_id, **extra):
        return {'Authorization': f'Bearer {create_access_token(actor_id)}', **extra}

    payload = {'sewing_factory': 'eco_cotton', 'paid_operations': [_operation('eco-full', 'eco_cotton')]}
    invalid = {'sewing_factory': 'milana', 'paid_operations': [_operation('wrong-factory', 'milana')]}
    path = f'/api/usluga/models/{model_id}/paid-operations'
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.patch(path, headers=headers(ids[2], Origin='https://untrusted.invalid'), json=payload)
        assert response.status_code == 403
        assert response.json()['detail'] == 'Untrusted request origin'
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert client.patch(path, json=payload).status_code == 401
        assert client.patch(path, headers=headers(ids[0]), json=payload).status_code == 403
        assert client.patch(path, headers=headers(ids[1]), json=payload).status_code == 403
        assert client.patch(path, headers=headers(ids[2]), json=invalid).status_code == 403
        with pg_sessions() as db:
            assert deepcopy(db.get(Model, model_id).details_json) == {}
            assert db.query(AuditLog).filter_by(action='update_paid_operations', entity_id=model_id).count() == 0
        response = client.patch(path, headers=headers(ids[2], Origin='http://localhost:3000'), json=payload)
        assert response.status_code == 200, response.text
        assert response.headers['x-frame-options'] == 'DENY'
        assert 'server-timing' in response.headers

    with sqlite3.connect(tmp_path / 'counter.db') as counter_db:
        assert counter_db.execute('SELECT count(*) FROM shared_counters').fetchone()[0] > 0

    with pg_sessions() as db:
        assert db.get(Model, model_id).details_json['paid_operations'] == payload['paid_operations']
        audit = db.query(AuditLog).filter_by(action='update_paid_operations', entity_id=model_id).one()
        assert audit.user_id == ids[2]
        assert audit.entry_hash
        assert audit_service.verify_audit_hash_chain(db)['ok']
