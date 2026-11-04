"""Deletion contract, authorization and rollback for both catalogue routes."""
from unittest.mock import Mock, call

import pytest
from fastapi import HTTPException

from app.api.routes import catalog, usluga
from app.libs.enums.catalog import CatalogScope
from app.models.catalog import models_service as service
from app.schemas import AuditLog, ModelSize, User
from app.schemas.catalog.model_size_persistence import delete_model_size
from app.tests.conftest import TestSessionLocal
from app.tests.test_modelsize_create_operation import size_case, size_client  # noqa: F401


def test_helper_only_schedules_delete():
    db, row = Mock(), object()
    delete_model_size(db, row)
    assert db.method_calls == [call.delete(row)]


@pytest.mark.parametrize(('scope', 'actor', 'prefix'), [('standard', 'standard', '/api/models'), ('usluga', 'eco', '/api/usluga/models')])
def test_http_delete_persisted_audit(size_case, size_client, scope, actor, prefix):
    mid = size_case['models'][scope]
    with TestSessionLocal.begin() as db:
        row = ModelSize(model_id=mid, size=' oʻlcham 🧵 ', measurement_json={'уз': 'ҳа'})
        db.add(row); db.flush(); sid = row.id
    response = size_client.delete(f'{prefix}/{mid}/sizes/{sid}', headers={'X-Actor': actor})
    assert response.status_code == 204 and response.content == b''
    with TestSessionLocal() as db:
        assert db.get(ModelSize, sid) is None
        audit = db.query(AuditLog).filter_by(entity_type='ModelSize', entity_id=sid, action='delete').one()
        assert audit.user_id == size_case['actors'][actor]
        assert audit.new_value_json == {'model_id': mid, 'size': ' oʻlcham 🧵 '}
    assert size_client.delete(f'{prefix}/{mid}/sizes/{sid}', headers={'X-Actor': actor}).status_code == 404


def test_denials_preserve_size(size_case, size_client):
    standard, eco = size_case['models']['standard'], size_case['models']['usluga']
    with TestSessionLocal.begin() as db:
        row = ModelSize(model_id=standard, size='M'); db.add(row); db.flush(); sid = row.id
    for path, actor, status in [(f'/api/models/{standard}/sizes/{sid}', 'denied', 403), (f'/api/usluga/models/{standard}/sizes/{sid}', 'wrong_factory', 403), (f'/api/usluga/models/{standard}/sizes/{sid}', 'eco', 404), (f'/api/models/{eco}/sizes/{sid}', 'standard', 404), (f'/api/models/{standard}/sizes/999999', 'standard', 404)]:
        assert size_client.delete(path, headers={'X-Actor': actor}).status_code == status
    with TestSessionLocal() as db:
        assert db.get(ModelSize, sid) is not None
        assert db.query(AuditLog).filter_by(entity_type='ModelSize', entity_id=sid, action='delete').count() == 0


def test_audit_failure_rolls_back_delete_and_audit(size_case, monkeypatch):
    mid = size_case['models']['standard']
    with TestSessionLocal.begin() as db:
        row = ModelSize(model_id=mid, size='M'); db.add(row); db.flush(); sid = row.id
    original = service.log_action
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('audit failure')
    monkeypatch.setattr(service, 'log_action', fail)
    with TestSessionLocal() as db:
        with pytest.raises(RuntimeError, match='audit failure'):
            service.delete_size(db.get(User, size_case['actors']['standard']), db, mid, sid)
        db.rollback()
    with TestSessionLocal() as db:
        assert db.get(ModelSize, sid) is not None
        assert db.query(AuditLog).filter_by(entity_type='ModelSize', entity_id=sid, action='delete').count() == 0


@pytest.mark.parametrize(('scope', 'expected'), [(CatalogScope.STANDARD, 'standard'), (CatalogScope.USLUGA, 'usluga'), (' StAnDaRd ', 'standard'), (' USLUGA ', 'usluga'), (None, 'standard')])
def test_scope_adapter(size_case, scope, expected):
    mid = size_case['models'][expected]
    with TestSessionLocal.begin() as db:
        row = ModelSize(model_id=mid, size='M'); db.add(row); db.flush(); sid = row.id
    with TestSessionLocal() as db:
        service.delete_size(db.get(User, size_case['actors']['standard']), db, mid, sid, scope)
        assert db.get(ModelSize, sid) is None


def test_route_permissions_and_eco_gate(monkeypatch):
    call, eco = Mock(), Mock(side_effect=HTTPException(403, 'denied'))
    monkeypatch.setattr(service, 'delete_size', call); monkeypatch.setattr(usluga, '_require_eco', eco)
    with pytest.raises(HTTPException):
        usluga.delete_usluga_model_size(1, 2, object(), object())
    call.assert_not_called()
    for router, endpoint, permission in [(catalog.router, catalog.delete_size, 'modeling.models'), (usluga.router, usluga.delete_usluga_model_size, 'usluga.manage')]:
        route = next(r for r in router.routes if r.endpoint is endpoint)
        assert route.status_code == 204 and 'DELETE' in route.methods
        dependency = next(d for d in route.dependant.dependencies if d.name == 'current')
        assert any(permission in repr(c.cell_contents) for c in dependency.call.__closure__)
