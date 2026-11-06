"""Old ModelColor CREATE characterization; SQLite is not PostgreSQL evidence."""
import inspect
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.api.routes import catalog, usluga
from app.core.deps import get_current_user, get_db
from app.libs.dto.catalog.model_color_input import ModelColorIn
from app.libs.enums.catalog import CatalogScope
from app.models.catalog import models_service as service
from app.schemas import AuditLog, IdempotencyRecord, Model, ModelColor, Notification, Role, User
from app.tests.conftest import TestSessionLocal


@pytest.fixture
def color_case():
    token = uuid4().hex
    with TestSessionLocal.begin() as db:
        allowed = Role(name=f'color-allow-{token}', permissions=['modeling.models', 'usluga.manage'])
        denied = Role(name=f'color-deny-{token}', permissions=[])
        db.add_all([allowed, denied]); db.flush()
        actors = {name: User(name=name, email=f'color-{name}-{token}@example.invalid', password_hash='unused', role_id=role.id, factory_code=factory, is_active=True) for name, role, factory in [('standard', allowed, 'MIL'), ('eco', allowed, 'ECO'), ('wrong_factory', allowed, 'MIL'), ('denied', denied, 'MIL')]}
        models = {scope: Model(code=f'COLOR-{scope}-{token}', name=scope, catalog_scope=scope, factory_code=factory) for scope, factory in [('standard', 'MIL'), ('usluga', 'ECO')]}
        db.add_all([*actors.values(), *models.values()]); db.flush()
        return {'actors': {k:v.id for k,v in actors.items()}, 'models': {k:v.id for k,v in models.items()}}


@pytest.fixture
def color_app(color_case):
    app = FastAPI(); app.include_router(catalog.router, prefix='/api'); app.include_router(usluga.router, prefix='/api')
    def get_session():
        with TestSessionLocal() as db:
            yield db
    def actor(request: Request):
        name = request.headers.get('X-Actor', 'standard')
        if name == 'anonymous':
            raise HTTPException(401, 'Not authenticated')
        with TestSessionLocal() as db:
            user = db.get(User, color_case['actors'][name]); _ = user.role, user.department
            db.expunge(user); return user
    app.dependency_overrides[get_db] = get_session
    app.dependency_overrides[get_current_user] = actor
    return app


@pytest.fixture
def color_client(color_app):
    with TestClient(color_app, raise_server_exceptions=False) as client:
        yield client


def snapshot(case):
    with TestSessionLocal() as db:
        colors = [(r.id, r.model_id, r.color_name, r.color_code) for r in db.query(ModelColor).filter(ModelColor.model_id.in_(case['models'].values())).order_by(ModelColor.id)]
        return colors, db.query(AuditLog).count(), db.query(Notification).count(), db.query(IdempotencyRecord).count()


@pytest.mark.parametrize(('scope','actor','path'), [('standard','standard','/api/models'), ('usluga','eco','/api/usluga/models')])
@pytest.mark.parametrize(('name','code'), [('', None), ('  ', ''), ('  A\u0301 🧵  ', ' К  '), ('A'*64, 'B'*16)])
def test_http_real_readback_preserves_data_and_duplicate(color_case, color_client, scope, actor, path, name, code):
    before = snapshot(color_case)
    body = {'color_name': name, 'color_code': code}
    ids = []
    for _ in range(2):
        response = color_client.post(f"{path}/{color_case['models'][scope]}/colors", headers={'X-Actor': actor}, json=body)
        assert response.status_code == 201, response.text
        assert set(response.json()) == {'id'}
        ids.append(response.json()['id'])
    after = snapshot(color_case)
    assert ids[0] != ids[1]
    assert [row for row in after[0] if row[0] in ids] == [(i, color_case['models'][scope], name, code) for i in ids]
    assert after[1:] == before[1:]


def test_http_missing_denied_scope_dto_and_length_precedence(color_case, color_client):
    standard, eco = color_case['models']['standard'], color_case['models']['usluga']
    before = snapshot(color_case)
    too_long = {'color_name': 'a'*65, 'color_code': 'b'*17}
    checks = [
        (f'/api/models/{standard}/colors', 'anonymous', too_long, 401, None),
        (f'/api/models/{standard}/colors', 'denied', too_long, 403, None),
        (f'/api/usluga/models/{eco}/colors', 'denied', too_long, 403, None),
        (f'/api/usluga/models/{eco}/colors', 'wrong_factory', too_long, 403, None),
        (f'/api/models/{eco}/colors', 'standard', too_long, 404, 'Model not found'),
        (f'/api/usluga/models/{standard}/colors', 'eco', too_long, 404, 'Model not found'),
        ('/api/models/2147483647/colors', 'standard', too_long, 404, 'Model not found'),
        (f'/api/models/{standard}/colors', 'standard', too_long, 422, 'color_name must be at most 64 characters'),
        (f'/api/models/{standard}/colors', 'standard', {'color_name':'ok','color_code':'b'*17}, 422, 'color_code must be at most 16 characters'),
        ('/api/models/2147483647/colors', 'standard', {}, 422, None),
        (f'/api/models/{standard}/colors', 'denied', {}, 403, None),
    ]
    for url, actor, body, status, detail in checks:
        response = color_client.post(url, headers={'X-Actor':actor}, json=body)
        assert response.status_code == status, (url, actor, response.text)
        if detail is not None: assert response.json()['detail'] == detail
    assert snapshot(color_case) == before


@pytest.mark.parametrize(('raw','scope'), [(None,'standard'), (0,'standard'), ('','standard'), ('  StAnDaRd  ','standard'), (' USLUGA ','usluga')])
def test_old_direct_scope_normalization(color_case, raw, scope):
    with TestSessionLocal() as db:
        result = service.add_color(db.get(User,color_case['actors']['standard']), db, color_case['models'][scope], ModelColorIn(color_name=' a '), raw)
    with TestSessionLocal() as db:
        row = db.get(ModelColor, result['id'])
        assert (row.model_id,row.color_name,row.color_code)==(color_case['models'][scope],' a ',None)


@pytest.mark.parametrize('raw', [' ', 'unknown', 'standard\u200b'])
def test_direct_invalid_scope_precedes_parent_and_length(color_case, raw):
    before = snapshot(color_case)
    with TestSessionLocal() as db, pytest.raises(HTTPException) as exc:
        service.add_color(db.get(User,color_case['actors']['standard']), db, -1, ModelColorIn(color_name='a'*65, color_code='b'*17), raw)
    assert (exc.value.status_code, exc.value.detail)==(400,'Invalid model catalog scope')
    assert snapshot(color_case)==before


def test_omitted_code_and_unicode_codepoint_length(color_case, color_client):
    mid = color_case['models']['standard']
    value = 'e\u0301' * 32  # 64 codepoints, 32 graphemes.
    response = color_client.post(f'/api/models/{mid}/colors', json={'color_name': value})
    assert response.status_code==201
    with TestSessionLocal() as db:
        row=db.get(ModelColor,response.json()['id'])
        assert (row.color_name,row.color_code)==(value,None)
    too_long=color_client.post(f'/api/models/{mid}/colors',json={'color_name':value+'a'})
    assert too_long.status_code==422 and too_long.json()['detail']=='color_name must be at most 64 characters'


def test_constructor_and_add_are_schema_owned(color_case):
    # Actual mapped construction and add occur in the schema-owned writer.
    observed=[]
    def assignment(target, value, old, initiator):
        for frame in inspect.stack()[1:]:
            module=frame.frame.f_globals.get('__name__','')
            if module.startswith('app.'):
                observed.append((initiator.key,module)); break
    def attached(session, instance):
        if isinstance(instance, ModelColor):
            for frame in inspect.stack()[1:]:
                module=frame.frame.f_globals.get('__name__','')
                if module.startswith('app.'):
                    observed.append(('add',module)); break
    attributes = [ModelColor.model_id,ModelColor.color_name,ModelColor.color_code]
    for a in attributes: event.listen(a,'set',assignment)
    event.listen(Session,'before_attach',attached)
    try:
        with TestSessionLocal() as db:
            service.add_color(db.get(User,color_case['actors']['standard']), db, color_case['models']['standard'], ModelColorIn(color_name='original',color_code='x'))
    finally:
        for a in attributes: event.remove(a,'set',assignment)
        event.remove(Session,'before_attach',attached)
    assert {x[0] for x in observed} >= {'model_id','color_name','color_code','add'}
    assert all(module=='app.schemas.catalog.model_color_persistence' for _,module in observed), observed


@pytest.mark.parametrize('failure', ['precommit','flush','commit_after_flush','refresh_after_commit'])
def test_http_real_session_teardown_failure_and_retry(color_case, color_app, monkeypatch, failure):
    mid=color_case['models']['standard']; body={'color_name':'persist?','color_code':'x'}
    before=snapshot(color_case); observed=[]
    original_refresh=Session.refresh
    def get_fault_session():
        with TestSessionLocal() as db:
            def precommit(session):
                observed.append('before_commit')
                if failure=='precommit': raise RuntimeError('injected precommit')
                if failure=='commit_after_flush':
                    session.flush(); observed.append('flushed')
                    raise RuntimeError('injected after flush before commit')
            def flush(session,ctx,instances):
                observed.append('before_flush')
                if failure=='flush': raise RuntimeError('injected flush')
            def committed(session): observed.append('after_commit')
            event.listen(db,'before_commit',precommit); event.listen(db,'before_flush',flush); event.listen(db,'after_commit',committed)
            yield db
    def refresh(session, instance, *args, **kwargs):
        result=original_refresh(session,instance,*args,**kwargs)
        if isinstance(instance,ModelColor):
            observed.append('refresh_delegated')
            if failure=='refresh_after_commit': raise RuntimeError('injected after refresh')
        return result
    with monkeypatch.context() as patch:
        patch.setattr(Session,'refresh',refresh)
        color_app.dependency_overrides[get_db]=get_fault_session
        with TestClient(color_app,raise_server_exceptions=False) as client:
            response=client.post(f'/api/models/{mid}/colors',json=body)
        assert response.status_code==500
    after=snapshot(color_case)
    if failure=='refresh_after_commit':
        assert observed.index('after_commit') < observed.index('refresh_delegated')
        assert len(after[0])==len(before[0])+1 and after[0][-1][1:]==(mid,'persist?','x')
    else:
        assert 'after_commit' not in observed and after==before
        if failure=='commit_after_flush': assert 'flushed' in observed
    assert after[1:]==before[1:]
    # Restore normal request dependency and retry only after independent persisted readback.
    def normal():
        with TestSessionLocal() as db: yield db
    color_app.dependency_overrides[get_db]=normal
    with TestClient(color_app,raise_server_exceptions=False) as client:
        retry=client.post(f'/api/models/{mid}/colors',json=body)
    assert retry.status_code==201, retry.text
    final=snapshot(color_case)
    assert len(final[0])==len(after[0])+1
    retry_row=next(row for row in final[0] if row[0]==retry.json()['id'])
    assert retry_row[1:]==(mid,'persist?','x')
    if failure=='refresh_after_commit':
        first_row=after[0][-1]
        assert first_row[1:]==(mid,'persist?','x') and first_row[0]!=retry_row[0]
    assert final[1:]==before[1:]


def test_actual_single_session_commit_and_delegating_refresh(color_case, color_app, monkeypatch):
    observed=[]
    original_refresh=Session.refresh
    def instrumented_session():
        with TestSessionLocal() as db:
            event.listen(db,'before_commit',lambda session: observed.append(('before_commit', id(session))))
            event.listen(db,'after_commit',lambda session: observed.append(('after_commit', id(session))))
            yield db
    def refresh(session, instance, *args, **kwargs):
        result=original_refresh(session,instance,*args,**kwargs)
        if isinstance(instance,ModelColor): observed.append(('refresh',id(session)))
        return result
    before=snapshot(color_case)
    with monkeypatch.context() as patch:
        patch.setattr(Session,'refresh',refresh)
        color_app.dependency_overrides[get_db]=instrumented_session
        with TestClient(color_app,raise_server_exceptions=False) as client:
            response=client.post(f"/api/models/{color_case['models']['standard']}/colors",json={'color_name':'single','color_code':None})
    assert response.status_code==201, response.text
    assert [name for name,_ in observed]==['before_commit','after_commit','refresh']
    assert len({session for _,session in observed})==1
    after=snapshot(color_case)
    assert [row for row in after[0] if row[0]==response.json()['id']]==[(response.json()['id'],color_case['models']['standard'],'single',None)]
    assert after[1:]==before[1:]


@pytest.mark.parametrize(('scope','actor'), [(CatalogScope.STANDARD,'standard'), (CatalogScope.USLUGA,'eco')])
def test_canonical_enum_is_accepted(color_case, scope, actor):
    with TestSessionLocal() as db:
        result=service.add_color(db.get(User,color_case['actors'][actor]),db,color_case['models'][scope.value],ModelColorIn(color_name='enum',color_code=None),scope)
    with TestSessionLocal() as db:
        row=db.get(ModelColor,result['id'])
        assert (row.model_id,row.color_name,row.color_code)==(color_case['models'][scope.value],'enum',None)


def test_routes_pass_canonical_scope_to_real_service(color_case, color_client, monkeypatch):
    seen=[]
    original=service.add_color
    def spy(current,db,mid,payload,scope):
        seen.append(scope)
        return original(current,db,mid,payload,scope)
    monkeypatch.setattr(service,'add_color',spy)
    for scope,actor,prefix in [(CatalogScope.STANDARD,'standard','/api/models'),(CatalogScope.USLUGA,'eco','/api/usluga/models')]:
        response=color_client.post(f"{prefix}/{color_case['models'][scope.value]}/colors",headers={'X-Actor':actor},json={'color_name':'route'})
        assert response.status_code==201,response.text
    assert seen==[CatalogScope.STANDARD,CatalogScope.USLUGA]
    assert all(type(scope) is CatalogScope for scope in seen)


def test_schema_helper_adds_without_flush_or_commit():
    from app.libs.types.catalog import ModelColorCreateCommand
    from app.schemas.catalog.model_color_persistence import insert_model_color
    class SessionSpy:
        def __init__(self): self.rows=[]
        def add(self,row): self.rows.append(row)
        def flush(self): pytest.fail('helper must not flush')
        def commit(self): pytest.fail('helper must not commit')
    db=SessionSpy(); row=insert_model_color(db,ModelColorCreateCommand(model_id=7,color_name=' x ',color_code=None))
    assert db.rows==[row] and (row.model_id,row.color_name,row.color_code)==(7,' x ',None)


def test_color_contracts_use_canonical_scope_and_typed_command():
    from typing import get_type_hints
    from app.libs.types.catalog import ModelColorCreateCommand, ModelColorCreateResult
    from app.schemas.catalog.model_color_persistence import insert_model_color
    hints=get_type_hints(service.add_color)
    assert hints['catalog_scope'] is CatalogScope and hints['return'] is ModelColorCreateResult
    assert inspect.signature(service.add_color).parameters['catalog_scope'].default is CatalogScope.STANDARD
    assert get_type_hints(insert_model_color)['command'] is ModelColorCreateCommand
    assert get_type_hints(ModelColorCreateCommand)=={'model_id':int,'color_name':str,'color_code':str|None}
    assert get_type_hints(catalog.add_color)['catalog_scope'] is CatalogScope
