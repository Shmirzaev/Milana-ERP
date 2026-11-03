"""Frozen characterization of the legacy ModelSize DELETE operation."""
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.api.routes import catalog, usluga
from app.libs.enums.catalog import CatalogScope
from app.models.catalog import models_service as service


@pytest.mark.parametrize(('value', 'expected'), [(None, 'standard'), (0, 'standard'), ('', 'standard'), (' StAnDaRd ', 'standard'), (' USLUGA ', 'usluga')])
def test_legacy_scope_normalization(value, expected):
    assert service._normalize_catalog_scope(value) == expected


@pytest.mark.parametrize('value', [' ', 'other', 'standard\u200b', 'CatalogScope.STANDARD', 'CatalogScope.USLUGA'])
def test_legacy_scope_rejects_invalid_before_query(value):
    db = Mock()
    with pytest.raises(HTTPException) as error:
        service.delete_size(object(), db, 4, 8, value)
    assert (error.value.status_code, error.value.detail) == (400, 'Invalid model catalog scope')
    db.query.assert_not_called()


def test_delete_order_and_audit_payload(monkeypatch):
    db, actor = Mock(), object()
    row = Mock(size='oʻlcham 🧵')
    events = []
    monkeypatch.setattr(service, '_catalog_model_for_scope', lambda *args: True)
    db.query.return_value.filter.return_value.first.return_value = row
    db.delete.side_effect = lambda value: events.append(('delete', value))
    db.commit.side_effect = lambda: events.append(('commit',))
    def audit(session, current, action, entity, entity_id, *, new_value):
        assert session is db and current is actor
        events.append((action, entity, entity_id, new_value))
    monkeypatch.setattr(service, 'log_action', audit)
    assert service.delete_size(actor, db, 4, 8, 'standard') is None
    assert events == [('delete', row), ('delete', 'ModelSize', 8, {'model_id': 4, 'size': 'oʻlcham 🧵'}), ('commit',)]


def test_parent_404_precedes_child_query(monkeypatch):
    db = Mock()
    monkeypatch.setattr(service, '_catalog_model_for_scope', lambda *args: None)
    with pytest.raises(HTTPException) as error:
        service.delete_size(object(), db, 4, 8)
    assert (error.value.status_code, error.value.detail) == (404, 'Model not found')
    db.query.assert_not_called()
    db.delete.assert_not_called()


def test_missing_child_404_no_write(monkeypatch):
    db = Mock()
    monkeypatch.setattr(service, '_catalog_model_for_scope', lambda *args: True)
    db.query.return_value.filter.return_value.first.return_value = None
    with pytest.raises(HTTPException) as error:
        service.delete_size(object(), db, 4, 8)
    assert (error.value.status_code, error.value.detail) == (404, 'Size not found')
    db.delete.assert_not_called()
    db.commit.assert_not_called()


def test_audit_failure_does_not_commit(monkeypatch):
    db = Mock()
    monkeypatch.setattr(service, '_catalog_model_for_scope', lambda *args: True)
    monkeypatch.setattr(service, 'log_action', Mock(side_effect=RuntimeError('audit failure')))
    with pytest.raises(RuntimeError, match='audit failure'):
        service.delete_size(object(), db, 4, 8)
    db.delete.assert_called_once()
    db.commit.assert_not_called()


def test_route_delegation_and_eco_gate(monkeypatch):
    call, eco = Mock(), Mock()
    monkeypatch.setattr(service, 'delete_size', call)
    monkeypatch.setattr(usluga, '_require_eco', eco)
    actor, db = object(), object()
    catalog.delete_size(7, 8, db, actor, CatalogScope.STANDARD)
    call.assert_called_with(actor, db, 7, 8, CatalogScope.STANDARD)
    usluga.delete_usluga_model_size(7, 8, db, actor)
    eco.assert_called_once_with(actor)
    call.assert_called_with(actor, db, 7, 8, CatalogScope.USLUGA)
    eco.side_effect = HTTPException(403, 'denied')
    call.reset_mock()
    with pytest.raises(HTTPException) as error:
        usluga.delete_usluga_model_size(7, 8, db, actor)
    assert error.value.status_code == 403
    call.assert_not_called()


def test_route_permission_and_status():
    for router, endpoint, permission in [(catalog.router, catalog.delete_size, 'modeling.models'), (usluga.router, usluga.delete_usluga_model_size, 'usluga.manage')]:
        route = next(r for r in router.routes if r.endpoint is endpoint)
        assert route.status_code == 204 and 'DELETE' in route.methods
        dependency = next(d for d in route.dependant.dependencies if d.name == 'current')
        assert any(permission in repr(c.cell_contents) for c in dependency.call.__closure__)


@pytest.mark.parametrize(('value', 'expected'), [(CatalogScope.STANDARD, CatalogScope.STANDARD), (CatalogScope.USLUGA, CatalogScope.USLUGA), (None, CatalogScope.STANDARD), (0, CatalogScope.STANDARD), ('', CatalogScope.STANDARD), (' StAnDaRd ', CatalogScope.STANDARD), (' USLUGA ', CatalogScope.USLUGA)])
def test_candidate_scope_adapter_passes_canonical_member(monkeypatch, value, expected):
    db = Mock()
    lookup = Mock(return_value=True)
    monkeypatch.setattr(service, '_catalog_model_for_scope', lookup)
    monkeypatch.setattr(service, 'log_action', Mock())
    service.delete_size(object(), db, 4, 8, value)
    lookup.assert_called_once_with(db, 4, expected)
    assert isinstance(lookup.call_args.args[2], CatalogScope)


def test_candidate_scope_default_is_canonical():
    import inspect
    parameter = inspect.signature(service.delete_size).parameters['catalog_scope']
    assert parameter.default is CatalogScope.STANDARD
    assert parameter.annotation in (CatalogScope, 'CatalogScope')
