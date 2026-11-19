"""Characterization of the existing ModelSize create operation, before extraction."""
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.api.routes import catalog, usluga
from app.libs.dto.catalog.model_size_input import ModelSizeIn
from app.libs.enums.catalog import CatalogScope
from app.models.catalog import models_service as service


@pytest.mark.parametrize(('value', 'expected'), [(None, 'standard'), ('', 'standard'), (' StAnDaRd ', 'standard'), (' USLUGA ', 'usluga'), (0, 'standard')])
def test_scope_normalization(value, expected):
    assert service._normalize_catalog_scope(value) == expected


@pytest.mark.parametrize('value', [' ', 'other', 'standard\u200b', CatalogScope.STANDARD, CatalogScope.USLUGA])
def test_scope_invalid_preserves_400(value):
    with pytest.raises(HTTPException) as exc:
        service._normalize_catalog_scope(value)
    assert (exc.value.status_code, exc.value.detail) == (400, 'Invalid model catalog scope')


class RecordingSession:
    def __init__(self):
        self.events = []
        self.row = None

    def add(self, row):
        self.events.append('add')
        self.row = row

    def flush(self):
        self.events.append('flush')
        self.row.id = 71

    def commit(self):
        self.events.append('commit')

    def refresh(self, row):
        assert row is self.row
        self.events.append('refresh')


def test_create_order_payload_and_literal_response(monkeypatch):
    db = RecordingSession()
    actor = object()
    measurements = {'грудь': 42, 'nested': {'uz': 'oʻlcham'}, 'list': [None, 1]}
    payload = ModelSizeIn(size='  XXL 🧵  ', measurement_json=measurements)
    lookup = Mock(return_value=object())
    monkeypatch.setattr(service, '_catalog_model_for_scope', lookup)

    def audit(session, current, action, entity, entity_id, *, new_value):
        assert session is db and current is actor
        assert (action, entity, entity_id, new_value) == ('create', 'ModelSize', 71, {'model_id': 5, 'size': '  XXL 🧵  '})
        db.events.append('audit')

    monkeypatch.setattr(service, 'log_action', audit)
    assert service.add_size(actor, db, 5, payload, ' UsLuGa ') == {'id': 71}
    lookup.assert_called_once_with(db, 5, CatalogScope.USLUGA)
    assert (db.row.model_id, db.row.size, db.row.measurement_json) == (5, '  XXL 🧵  ', measurements)
    assert db.events == ['add', 'flush', 'audit', 'commit', 'refresh']


def test_missing_model_has_no_writes(monkeypatch):
    db = RecordingSession()
    monkeypatch.setattr(service, '_catalog_model_for_scope', lambda *args: None)
    with pytest.raises(HTTPException) as exc:
        service.add_size(object(), db, 4, ModelSizeIn(size='M'))
    assert (exc.value.status_code, exc.value.detail) == (404, 'Model not found')
    assert db.events == []


def test_audit_failure_does_not_commit_or_refresh(monkeypatch):
    db = RecordingSession()
    monkeypatch.setattr(service, '_catalog_model_for_scope', lambda *args: True)
    def fail(*args, **kwargs):
        raise RuntimeError('audit failure')
    monkeypatch.setattr(service, 'log_action', fail)
    with pytest.raises(RuntimeError, match='audit failure'):
        service.add_size(object(), db, 4, ModelSizeIn(size='M'))
    assert db.events == ['add', 'flush']


def test_route_delegation_and_eco_gate(monkeypatch):
    call = Mock(return_value={'id': 3})
    eco = Mock()
    monkeypatch.setattr(service, 'add_size', call)
    monkeypatch.setattr(usluga, '_require_eco', eco)
    actor, db, payload = object(), object(), ModelSizeIn(size='M')
    assert catalog.add_size(7, payload, db, actor, 'standard') == {'id': 3}
    call.assert_called_with(actor, db, 7, payload, 'standard')
    assert usluga.add_usluga_model_size(7, payload, db, actor) == {'id': 3}
    eco.assert_called_once_with(actor)
    call.assert_called_with(actor, db, 7, payload, 'usluga')
    eco.side_effect = HTTPException(403, 'denied')
    call.reset_mock()
    with pytest.raises(HTTPException) as exc:
        usluga.add_usluga_model_size(7, payload, db, actor)
    assert exc.value.status_code == 403
    call.assert_not_called()


def test_route_registration_and_permission_dependencies():
    for router, endpoint, permission in [(catalog.router, catalog.add_size, 'modeling.models'), (usluga.router, usluga.add_usluga_model_size, 'usluga.manage')]:
        route = next(r for r in router.routes if r.endpoint is endpoint)
        assert route.status_code == 201 and 'POST' in route.methods
        dependency = next(d for d in route.dependant.dependencies if d.name == 'current')
        assert permission in repr(dependency.call.__closure__[0].cell_contents) or any(permission in repr(c.cell_contents) for c in dependency.call.__closure__)

# Integration characterization uses the existing isolated SQLite fixture; PG remains a separate gate.
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from app.core.deps import get_current_user
from app.db.session import get_db
from app.schemas import AuditLog, Model, ModelSize, Role, User
from app.tests.conftest import TestSessionLocal


@pytest.fixture
def size_case():
    with TestSessionLocal.begin() as db:
        allowed = Role(name='Size allowed', permissions=['modeling.models', 'usluga.manage'])
        denied = Role(name='Size denied', permissions=[])
        db.add_all([allowed, denied]); db.flush()
        actors = {name: User(name=name, email=f'size-{name}@example.invalid', password_hash='unused', role_id=role.id, factory_code=factory, is_active=True) for name, role, factory in [('standard', allowed, 'MIL'), ('eco', allowed, 'ECO'), ('wrong_factory', allowed, 'MIL'), ('denied', denied, 'MIL')]}
        models = {scope: Model(code=f'SIZE-{scope}', name=scope, catalog_scope=scope, factory_code=factory) for scope, factory in [('standard', 'MIL'), ('usluga', 'ECO')]}
        db.add_all([*actors.values(), *models.values()]); db.flush()
        return {'actors': {k: v.id for k, v in actors.items()}, 'models': {k: v.id for k, v in models.items()}}


@pytest.fixture
def size_client(size_case):
    app = FastAPI(); app.include_router(catalog.router, prefix='/api'); app.include_router(usluga.router, prefix='/api')
    def db_override():
        with TestSessionLocal() as db:
            yield db
    def actor(request: Request):
        with TestSessionLocal() as db:
            user = db.get(User, size_case['actors'][request.headers.get('X-Actor', 'standard')])
            _ = user.role, user.department
            db.expunge_all()
            return user
    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_current_user] = actor
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize(('scope', 'actor', 'prefix'), [('standard', 'standard', '/api/models'), ('usluga', 'eco', '/api/usluga/models')])
def test_http_persist_duplicate_and_readback(size_case, size_client, scope, actor, prefix):
    mid = size_case['models'][scope]
    body = {'size': ' oʻlcham 🧵 ', 'measurement_json': {'грудь': 42, 'nested': {'уз': 'ҳа'}}}
    ids = []
    for _ in range(2):
        response = size_client.post(f'{prefix}/{mid}/sizes', headers={'X-Actor': actor}, json=body)
        assert response.status_code == 201, response.text
        assert set(response.json()) == {'id'}
        ids.append(response.json()['id'])
    assert ids[0] != ids[1]
    with TestSessionLocal() as db:
        rows = db.query(ModelSize).filter(ModelSize.id.in_(ids)).order_by(ModelSize.id).all()
        assert [(r.model_id, r.size, r.measurement_json) for r in rows] == [(mid, body['size'], body['measurement_json'])] * 2
        logs = db.query(AuditLog).filter(AuditLog.entity_type == 'ModelSize', AuditLog.entity_id.in_(ids)).order_by(AuditLog.id).all()
        assert [log.new_value_json for log in logs] == [{'model_id': mid, 'size': body['size']}] * 2
        assert [(log.action, log.user_id) for log in logs] == [('create', size_case['actors'][actor])] * 2


def test_http_permission_factory_and_scope_denials(size_case, size_client):
    standard, eco = size_case['models']['standard'], size_case['models']['usluga']
    with TestSessionLocal() as db:
        initial_audits = db.query(AuditLog).filter(AuditLog.entity_type == 'ModelSize').count()
    for path, actor, status in [(f'/api/models/{standard}/sizes', 'denied', 403), (f'/api/usluga/models/{eco}/sizes', 'denied', 403), (f'/api/usluga/models/{eco}/sizes', 'wrong_factory', 403), (f'/api/models/{eco}/sizes', 'standard', 404), (f'/api/usluga/models/{standard}/sizes', 'eco', 404), ('/api/models/999999/sizes', 'standard', 404)]:
        response = size_client.post(path, headers={'X-Actor': actor}, json={'size': 'M'})
        assert response.status_code == status, response.text
    with TestSessionLocal() as db:
        assert db.query(ModelSize).filter(ModelSize.model_id.in_(size_case['models'].values())).count() == 0
        assert db.query(AuditLog).filter(AuditLog.entity_type == 'ModelSize').count() == initial_audits


def test_real_session_audit_failure_then_caller_rollback(size_case, monkeypatch):
    with TestSessionLocal() as db:
        initial_audits = db.query(AuditLog).filter(AuditLog.entity_type == 'ModelSize').count()
    original = service.log_action
    def fail_after_append(*args, **kwargs):
        session, actor, action, entity, entity_id = args
        assert session is db and actor.id == size_case['actors']['standard']
        assert action == 'create' and entity == 'ModelSize' and entity_id is not None
        original(*args, **kwargs)
        assert session.query(AuditLog).filter_by(entity_type='ModelSize', entity_id=entity_id).count() == 1
        raise RuntimeError('injected after audit append')
    monkeypatch.setattr(service, 'log_action', fail_after_append)
    with TestSessionLocal() as db:
        with pytest.raises(RuntimeError, match='injected'):
            service.add_size(db.get(User, size_case['actors']['standard']), db, size_case['models']['standard'], ModelSizeIn(size='M'))
        db.rollback()
    with TestSessionLocal() as db:
        assert db.query(ModelSize).filter(ModelSize.model_id.in_(size_case['models'].values())).count() == 0
        assert db.query(AuditLog).filter(AuditLog.entity_type == 'ModelSize').count() == initial_audits


@pytest.mark.parametrize(('scope', 'model'), [(CatalogScope.STANDARD, 'standard'), (CatalogScope.USLUGA, 'usluga'), (' StAnDaRd ', 'standard'), (' USLUGA ', 'usluga'), (None, 'standard'), ('', 'standard'), (0, 'standard')])
def test_candidate_scope_adapter_preserves_legacy_and_accepts_enums(size_case, scope, model):
    with TestSessionLocal() as db:
        actor = db.get(User, size_case['actors']['standard'])
        result = service.add_size(actor, db, size_case['models'][model], ModelSizeIn(size='M'), scope)
        assert set(result) == {'id'}
        assert db.get(ModelSize, result['id']).model_id == size_case['models'][model]


@pytest.mark.parametrize('scope', [' ', 'other', 'standard\u200b'])
def test_candidate_scope_invalid_before_write(size_case, scope):
    with TestSessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            service.add_size(db.get(User, size_case['actors']['standard']), db, size_case['models']['standard'], ModelSizeIn(size='M'), scope)
        assert (exc.value.status_code, exc.value.detail) == (400, 'Invalid model catalog scope')
        assert db.query(ModelSize).filter_by(model_id=size_case['models']['standard']).count() == 0


def test_insert_helper_flushes_without_transaction_control():
    from app.libs.types.catalog import ModelSizeCreateCommand
    from app.schemas.catalog.model_size_persistence import insert_model_size
    db = RecordingSession()
    row = insert_model_size(db, ModelSizeCreateCommand(model_id=4, size='  🧵 ', measurement_json={'уз': 'ҳа'}))
    assert row is db.row and row.id == 71
    assert (row.model_id, row.size, row.measurement_json) == (4, '  🧵 ', {'уз': 'ҳа'})
    assert db.events == ['add', 'flush']


def test_standard_route_passes_legacy_direct_scope_unchanged(monkeypatch):
    call = Mock(return_value={'id': 9})
    monkeypatch.setattr(service, 'add_size', call)
    actor, db, payload = object(), object(), ModelSizeIn(size='M')
    assert catalog._standard_size_catalog_scope() is CatalogScope.STANDARD
    assert catalog.add_size(7, payload, db, actor, ' StAnDaRd ') == {'id': 9}
    call.assert_called_once_with(actor, db, 7, payload, ' StAnDaRd ')


def test_payload_measurements_are_detached_from_mapped_row(monkeypatch):
    payload = ModelSizeIn(size='M', measurement_json={'nested': {'value': 'original'}})
    class MutatingSession(RecordingSession):
        def flush(self):
            super().flush()
            self.row.measurement_json['nested']['value'] = 'modified'
    db = MutatingSession()
    monkeypatch.setattr(service, '_catalog_model_for_scope', lambda *args: True)
    monkeypatch.setattr(service, 'log_action', lambda *args, **kwargs: None)
    service.add_size(object(), db, 4, payload)
    assert db.row.measurement_json['nested']['value'] == 'modified'
    assert payload.measurement_json == {'nested': {'value': 'original'}}
