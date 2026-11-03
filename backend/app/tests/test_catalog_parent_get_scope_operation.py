"""Baseline characterization of parent GET; no proposed type conversion.

Uses the existing disposable SQLite conftest. No production data or PG claim.
"""
import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.libs.enums.catalog import CatalogScope
from app.models.catalog import models_service as service
from app.core.security import hash_password
from app.schemas import Model, ModelBOM, ModelColor, ModelImage, ModelSize, Role, User
from app.tests.conftest import TestSessionLocal, test_engine
from app.tests.test_paid_operation_factory_scope import _create_payroll_manager, _operation


@pytest.fixture
def catalog_rows():
    with TestSessionLocal() as db:
        ids = []
        for scope, factory in (('standard', 'MIL'), ('usluga', 'ECO')):
            m = Model(code=f'PARENT-{scope}', name=f'Parent {scope}', catalog_scope=scope,
                      factory_code=factory, details_json={'note': ' O‘z 🧵 ', 'paid_operations': [
                          _operation('mil', 'milana'), _operation('bst', 'besttex'), _operation('eco', 'eco_cotton')]})
            m.sizes = [ModelSize(size='  M 🧵  ', measurement_json={'chest': 12.5, 'other': None})]
            m.colors = [ModelColor(color_name='  Qizil-Красный  ', color_code=None)]
            m.images = [ModelImage(file_url='/synthetic/model.png', file_name='model.png',
                                   content_type='image/png', image_type='model', is_primary=True)]
            m.bom = [ModelBOM(material_name='Материал', material_role=None,
                              quantity_per_piece=1.25, unit='m', waste_percent=0)]
            db.add(m); db.flush(); ids.append(m.id)
        db.commit()
    return tuple(ids)


@pytest.fixture
def current_user():
    with TestSessionLocal() as db:
        user = db.query(User).filter(User.email == 'admin@example.com').one()
        _ = user.role, user.department  # keep required relationships loaded after detach
        db.expunge(user)
        return user


@pytest.mark.parametrize(('scope', 'index'), [(None, 0), ('', 0), (' STANDARD ', 0),
                                              ('standard', 0), (' USLUGA ', 1), ('usluga', 1)])
def test_direct_raw_scope_normalization_preserves_nested_payload(scope, index, catalog_rows, current_user):
    with TestSessionLocal() as db:
        result = service.get_model(current_user, db, catalog_rows[index], scope)
    assert result['id'] == catalog_rows[index]
    assert result['sizes'][0]['size'] == '  M 🧵  '
    assert result['sizes'][0]['measurement_json'] == {'chest': 12.5, 'other': None}
    assert result['colors'][0]['color_name'] == '  Qizil-Красный  '
    assert result['colors'][0]['color_code'] is None
    assert result['images'][0]['file_url'] == '/synthetic/model.png'
    assert result['primary_image_url'] == '/synthetic/model.png'
    assert result['bom'][0]['material_name'] == 'Материал'
    assert result['bom'][0]['material_role'] is None
    assert result['details_json']['note'] == ' O‘z 🧵 '


def test_default_scope_and_query_scope_miss(current_user, catalog_rows):
    with TestSessionLocal() as db:
        assert service.get_model(current_user, db, catalog_rows[0])['id'] == catalog_rows[0]
        for mid, scope in ((catalog_rows[1], 'standard'), (catalog_rows[0], 'usluga'), (99999999, 'standard')):
            with pytest.raises(HTTPException) as caught:
                service.get_model(current_user, db, mid, scope)
            assert (caught.value.status_code, caught.value.detail) == (404, 'Model not found')


@pytest.mark.parametrize('scope', ['bogus', '   '])
def test_invalid_raw_scope_fails_before_missing_parent(scope, current_user, monkeypatch):
    called = []
    original = service.filter_paid_operations_for_factory
    def observe(*args, **kwargs):
        called.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(service, 'filter_paid_operations_for_factory', observe)
    with TestSessionLocal() as db, pytest.raises(HTTPException) as caught:
        service.get_model(current_user, db, 99999999, scope)
    assert (caught.value.status_code, caught.value.detail) == (400, 'Invalid model catalog scope')
    assert called == []


def test_same_raw_scope_reaches_query_and_paid_operation_filter_only_on_success(monkeypatch, catalog_rows, current_user):
    query, paid = [], []
    orig_query, orig_paid = service._models_query, service._catalog_paid_operation_factory_scope
    def observe_query(db, scope):
        query.append(scope); return orig_query(db, scope)
    def observe_paid(user, scope):
        paid.append(scope); return orig_paid(user, scope)
    monkeypatch.setattr(service, '_models_query', observe_query)
    monkeypatch.setattr(service, '_catalog_paid_operation_factory_scope', observe_paid)
    raw = ' USLUGA '
    with TestSessionLocal() as db:
        result = service.get_model(current_user, db, catalog_rows[1], raw)
        assert [x['id'] for x in result['details_json']['paid_operations']] == ['eco']
        with pytest.raises(HTTPException): service.get_model(current_user, db, 99999999, raw)
    assert query == [raw, raw] and paid == [raw]


def test_direct_get_performs_no_flush_commit_or_sql_write(catalog_rows, current_user, monkeypatch):
    statements = []
    def record(_conn, _cursor, statement, *_args): statements.append(statement.lstrip().upper())
    event.listen(test_engine, 'before_cursor_execute', record)
    try:
        with TestSessionLocal() as db:
            monkeypatch.setattr(db, 'flush', lambda *a, **k: pytest.fail('GET flushed'))
            monkeypatch.setattr(db, 'commit', lambda *a, **k: pytest.fail('GET committed'))
            service.get_model(current_user, db, catalog_rows[0], 'standard')
    finally:
        event.remove(test_engine, 'before_cursor_execute', record)
    assert statements and all(not sql.startswith(('INSERT', 'UPDATE', 'DELETE', 'REPLACE')) for sql in statements)


def test_standard_and_usluga_routes_ignore_scope_query_and_enforce_scope(client, auth_headers, catalog_rows):
    eco = _create_payroll_manager(client, auth_headers, 'ECO')
    standard = client.get(f'/api/models/{catalog_rows[0]}?catalog_scope=usluga', headers=auth_headers)
    usluga = client.get(f'/api/usluga/models/{catalog_rows[1]}?catalog_scope=standard', headers=eco)
    assert standard.status_code == 200 and standard.json()['id'] == catalog_rows[0]
    assert usluga.status_code == 200 and usluga.json()['id'] == catalog_rows[1]
    assert client.get(f'/api/models/{catalog_rows[1]}', headers=auth_headers).status_code == 404
    assert client.get(f'/api/usluga/models/{catalog_rows[0]}', headers=eco).status_code == 404
    assert client.get('/api/models/99999999', headers=auth_headers).status_code == 404
    assert client.get(f'/api/models/{catalog_rows[0]}').status_code == 401


def test_usluga_route_requires_permission_and_eco_factory(client, auth_headers, catalog_rows):
    mil = _create_payroll_manager(client, auth_headers, 'MIL')
    assert client.get(f'/api/usluga/models/{catalog_rows[1]}', headers=mil).status_code == 403
    assert client.get(f'/api/usluga/models/{catalog_rows[1]}').status_code == 401



@pytest.mark.parametrize(('factory', 'visible'), [('MIL', 'mil'), ('BST', 'bst')])
def test_standard_payroll_factory_sees_only_its_paid_operations(client, auth_headers, catalog_rows, factory, visible):
    headers = _create_payroll_manager(client, auth_headers, factory)
    response = client.get(f'/api/models/{catalog_rows[0]}', headers=headers)
    assert response.status_code == 200, response.text
    assert [row['id'] for row in response.json()['details_json']['paid_operations']] == [visible]


def test_eco_user_without_usluga_viewer_permission_is_forbidden(client, catalog_rows):
    password = 'OwnedSyntheticECO!2026'
    with TestSessionLocal() as db:
        role = Role(name='Parent GET ECO denied', permissions=[])
        db.add(role); db.flush()
        db.add(User(name='Parent GET denied', email='parent-get-eco-denied@example.com',
                    password_hash=hash_password(password), role_id=role.id,
                    factory_code='ECO', extra_permissions=[], is_active=True))
        db.commit()
    login = client.post('/api/auth/login-json', json={'email': 'parent-get-eco-denied@example.com',
                                                       'password': password, 'factory_code': 'ECO'})
    assert login.status_code == 200, login.text
    me = client.get('/api/auth/me')
    assert me.status_code == 200 and me.json()['factory_code'] == 'ECO'
    denied = client.get(f'/api/usluga/models/{catalog_rows[1]}')
    assert denied.status_code == 403

def test_openapi_parent_get_uses_modeldetail_without_public_scope_parameter(client):
    spec = client.get('/openapi.json').json()
    for path in ('/api/models/{mid}', '/api/usluga/models/{mid}'):
        op = spec['paths'][path]['get']
        assert not any(p['name'] == 'catalog_scope' for p in op.get('parameters', []))
        assert op['responses']['200']['content']['application/json']['schema'] == {'$ref': '#/components/schemas/ModelDetail'}
    props = spec['components']['schemas']['ModelDetail']['properties']
    assert {'id', 'code', 'name', 'details_json', 'primary_image', 'primary_image_url',
            'variant_picture_url', 'images', 'sizes', 'colors', 'bom'} <= set(props)


@pytest.mark.parametrize(('scope', 'index'), [(CatalogScope.STANDARD, 0), (CatalogScope.USLUGA, 1)])
def test_canonical_enum_existing_parent_matches_raw_scope(scope, index, catalog_rows, current_user):
    with TestSessionLocal() as db:
        raw = service.get_model(current_user, db, catalog_rows[index], scope.value)
        typed = service.get_model(current_user, db, catalog_rows[index], scope)
    assert typed == raw


@pytest.mark.parametrize(('scope', 'index'), [(CatalogScope.STANDARD, 1), (CatalogScope.USLUGA, 0)])
def test_canonical_enum_wrong_scope_and_missing_return_404(scope, index, catalog_rows, current_user):
    with TestSessionLocal() as db:
        for mid in (catalog_rows[index], 99999999):
            with pytest.raises(HTTPException) as caught: service.get_model(current_user, db, mid, scope)
            assert caught.value.status_code == 404


def test_canonical_enum_adapts_same_value_for_query_and_filter(monkeypatch, catalog_rows, current_user):
    query, paid = [], []
    original_query, original_paid = service._models_query, service._catalog_paid_operation_factory_scope
    def track_query(db, scope): query.append(scope); return original_query(db, scope)
    def track_paid(user, scope): paid.append(scope); return original_paid(user, scope)
    monkeypatch.setattr(service, '_models_query', track_query)
    monkeypatch.setattr(service, '_catalog_paid_operation_factory_scope', track_paid)
    with TestSessionLocal() as db: service.get_model(current_user, db, catalog_rows[1], CatalogScope.USLUGA)
    assert query == paid == ['usluga']
    assert type(query[0]) is str


def test_signature_default_is_canonical_enum():
    import inspect
    from typing import get_type_hints
    param = inspect.signature(service.get_model).parameters['catalog_scope']
    assert get_type_hints(service.get_model)['catalog_scope'] is CatalogScope
    assert param.default is CatalogScope.STANDARD


def test_actual_routes_pass_canonical_enum_and_invoke_real_service(client, auth_headers, catalog_rows, monkeypatch):
    eco = _create_payroll_manager(client, auth_headers, 'ECO')
    calls = []
    original = service.get_model
    def spy(current, db, mid, scope):
        calls.append(scope)
        return original(current, db, mid, scope)
    monkeypatch.setattr(service, 'get_model', spy)
    assert client.get(f'/api/models/{catalog_rows[0]}', headers=auth_headers).status_code == 200
    assert client.get(f'/api/usluga/models/{catalog_rows[1]}', headers=eco).status_code == 200
    assert calls == [CatalogScope.STANDARD, CatalogScope.USLUGA]
    assert calls[0] is CatalogScope.STANDARD and calls[1] is CatalogScope.USLUGA
