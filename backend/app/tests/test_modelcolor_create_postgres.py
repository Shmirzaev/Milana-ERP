"""ModelColor CREATE regressions against an explicitly approved PostgreSQL instance.

Canonical scopes are accepted and mapped writes are schema-owned. Before-commit
injection is not a database COMMIT failure. No test-only DDL.
"""
import inspect
from itertools import count
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes import catalog, usluga
from app.core.deps import get_current_user, get_db
from app.libs.dto.catalog.model_color_input import ModelColorIn
from app.libs.enums.catalog import CatalogScope
from app.models.catalog import models_service as service
from app.schemas import AuditLog, IdempotencyRecord, Model, ModelColor, Notification, Role, User
from app.tests.pg_approved_instance import (
    ApprovedInstanceUnavailable, create_target_database, finalize_target,
    load_approved_instance, require_or_skip, retain_fixture_uncertainty, target_engine, verify_approved_instance,
)

from app.tests.pg_catalog_create_concurrency import run_catalog_create_pair


def record(event_name, **fields):
    """Emit observed outcomes; external orchestration owns durable artifacts."""
    print(json.dumps({'event':event_name, **fields},sort_keys=True,default=str),flush=True)


@pytest.fixture(scope='module')
def pg_sessions():
    # A present-but-empty variable is invalid configuration, never an opt-in skip.
    if 'MILANA_TEST_PG_INSTANCE' not in os.environ:
        require_or_skip(ApprovedInstanceUnavailable('explicit approved PostgreSQL instance not configured'))
    instance=load_approved_instance()
    verify_approved_instance(instance)
    target=create_target_database(instance)
    engine=None
    sessions=None
    try:
        engine=target_engine(target,options='-cstatement_timeout=30000 -clock_timeout=30000')
        assert engine.dialect.name=='postgresql'
        with engine.connect() as conn:
            assert sa.inspect(conn).get_table_names(schema='public')==[]
        from app.core.config import settings
        config=Config(str(Path(__file__).resolve().parents[2]/'alembic.ini'))
        config.set_main_option('script_location',str(Path(__file__).resolve().parents[2]/'alembic'))
        head=ScriptDirectory.from_config(config).get_current_head()
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(settings,'DATABASE_URL',engine.url.render_as_string(hide_password=False).replace('%','%%'))
            patch.setattr(sa,'engine_from_config',lambda *args,**kwargs:engine)
            command.upgrade(config,'head')
        with engine.connect() as conn:
            prep=conn.dialect.identifier_preparer
            tables=sorted(sa.inspect(conn).get_table_names(schema='public'))
            counts={table:conn.exec_driver_sql('select count(*) from '+prep.quote(table)).scalar_one() for table in tables}
            flows={tuple(row) for row in conn.execute(text('select factory_code,name,code from sewing_flows'))}
            departments={tuple(row) for row in conn.execute(text('select code,name from departments'))}
            warehouses={tuple(row) for row in conn.execute(text('select w.name,w.type,d.code from warehouses w join departments d on d.id=w.department_id'))}
            roles=[tuple(row) for row in conn.execute(text('select name,permissions from roles'))]
            heads=conn.execute(text('select version_num from alembic_version')).scalars().all()
            expected_flows={('MIL',name,code) for name,code in [('Maxmudova Nargiza','SEW-11'),('Muxlisa','SEW-12'),('Sevara','SEW-13')]} | {('ECO',f'{n}-Band',f'ECO-BAND-{n:02d}') for n in range(1,21)}
            expected_departments={('ECO','Eco Cotton Sewing Factory'),('ECP','Eco Cotton Packaging'),('ECT','Eco Cotton Cutting')}
            expected_warehouses={('Eco Cotton Packaging Floor','eco_cotton_packaging','ECP'),('Eco Cotton Cutting Floor','eco_cotton_cutting','ECT')}
            expected_permissions={'usluga.view','usluga.manage','usluga.handover','planning.production','usluga.cutting.approve'}
            expected_counts={'alembic_version':1,'sewing_flows':len(expected_flows),'departments':len(expected_departments),'warehouses':len(expected_warehouses),'roles':1}
            record('migration_census',counts=counts,flows=sorted(flows),departments=sorted(departments),warehouses=sorted(warehouses),roles=roles,heads=heads,candidate_head=head)
            assert heads==[head]
            assert {key:value for key,value in counts.items() if value}==expected_counts
            assert flows==expected_flows and departments==expected_departments and warehouses==expected_warehouses
            assert len(roles)==1 and roles[0][0]=='Eco Cotton Usluga'
            assert len(roles[0][1])==len(expected_permissions) and set(roles[0][1])==expected_permissions
        sessions=sessionmaker(bind=engine,autoflush=False,autocommit=False,expire_on_commit=False)
        yield sessions
    finally:
        prior_error=sys.exception()
        if sessions is not None:
            try:
                sessions.configure(bind=None)
            except BaseException as error:
                retain_fixture_uncertainty(target,engine,sessions,error,prior_error=prior_error)
        finalize_target(target,engine)


@pytest.fixture
def pg_case(pg_sessions):
    token=uuid4().hex
    with pg_sessions.begin() as db:
        allowed=Role(name=f'color-allow-{token}',permissions=['modeling.models','usluga.manage'])
        denied=Role(name=f'color-deny-{token}',permissions=[])
        db.add_all([allowed,denied]); db.flush()
        actors={name:User(name=name,email=f'color-{name}-{token}@example.invalid',password_hash='unused',role_id=role.id,factory_code=factory,is_active=True) for name,role,factory in [('standard',allowed,'MIL'),('eco',allowed,'ECO'),('wrong_factory',allowed,'MIL'),('denied',denied,'MIL')]}
        models={scope:Model(code=f'PG-COLOR-{scope}-{token}',name=scope,catalog_scope=scope,factory_code=factory) for scope,factory in [('standard','MIL'),('usluga','ECO')]}
        db.add_all([*actors.values(),*models.values()]); db.flush()
        return {'actors':{k:v.id for k,v in actors.items()},'models':{k:v.id for k,v in models.items()}}


def state(sessions,case):
    with sessions() as db:
        rows=db.query(ModelColor).filter(ModelColor.model_id.in_(case['models'].values())).order_by(ModelColor.id).all()
        return ([(r.id,r.model_id,r.color_name,r.color_code) for r in rows],db.query(AuditLog).count(),db.query(Notification).count(),db.query(IdempotencyRecord).count())


@pytest.fixture
def pg_app(pg_sessions,pg_case):
    app=FastAPI(); app.include_router(catalog.router,prefix='/api');app.include_router(usluga.router,prefix='/api')
    def session():
        with pg_sessions() as db: yield db
    def actor(request:Request):
        name=request.headers.get('X-Actor','standard')
        if name=='anonymous': raise HTTPException(401,'Not authenticated')
        with pg_sessions() as db:
            user=db.get(User,pg_case['actors'][name]);_=user.role,user.department;db.expunge(user);return user
    app.dependency_overrides[get_db]=session;app.dependency_overrides[get_current_user]=actor
    return app


@pytest.mark.parametrize(('scope','actor','path'), [('standard','standard','/api/models'),('usluga','eco','/api/usluga/models')])
@pytest.mark.parametrize(('name','code'),[('',None),('  ',''),(' e\u0301 🧵 ',' К '),('e\u0301'*32,'K'*16)])
def test_pg_http_exact_unicode_null_empty_duplicate_readback(pg_sessions,pg_case,pg_app,scope,actor,path,name,code):
    before=state(pg_sessions,pg_case); ids=[];mid=pg_case['models'][scope]
    with TestClient(pg_app,raise_server_exceptions=False) as client:
        for _ in range(2):
            response=client.post(f'{path}/{mid}/colors',headers={'X-Actor':actor},json={'color_name':name,'color_code':code})
            assert response.status_code==201,response.text
            assert set(response.json())=={'id'};ids.append(response.json()['id'])
    after=state(pg_sessions,pg_case)
    assert ids[0]!=ids[1] and [x for x in after[0] if x[0] in ids]==[(i,mid,name,code) for i in ids]
    assert after[1:]==before[1:]


def test_pg_http_auth_scope_dto_and_bound_precedence(pg_sessions,pg_case,pg_app):
    standard,eco=pg_case['models']['standard'],pg_case['models']['usluga'];before=state(pg_sessions,pg_case)
    invalid={'color_name':'a'*65,'color_code':'b'*17}
    checks=[(f'/api/models/{standard}/colors','anonymous',invalid,401,None),
            (f'/api/models/{standard}/colors','denied',invalid,403,None),
            (f'/api/usluga/models/{eco}/colors','denied',invalid,403,None),
            (f'/api/usluga/models/{eco}/colors','wrong_factory',invalid,403,None),
            (f'/api/models/{eco}/colors','standard',invalid,404,'Model not found'),
            (f'/api/usluga/models/{standard}/colors','eco',invalid,404,'Model not found'),
            ('/api/models/2147483647/colors','standard',invalid,404,'Model not found'),
            (f'/api/models/{standard}/colors','standard',invalid,422,'color_name must be at most 64 characters'),
            (f'/api/models/{standard}/colors','standard',{'color_name':'ok','color_code':'b'*17},422,'color_code must be at most 16 characters'),
            ('/api/models/2147483647/colors','standard',{},422,None)]
    with TestClient(pg_app,raise_server_exceptions=False) as client:
        for url,actor,body,status,detail in checks:
            response=client.post(url,headers={'X-Actor':actor},json=body)
            assert response.status_code==status,(url,actor,response.text)
            if detail is not None: assert response.json()['detail']==detail
    assert state(pg_sessions,pg_case)==before


@pytest.mark.parametrize(('raw','scope'),[(None,'standard'),(0,'standard'),('','standard'),(' StAnDaRd ','standard'),(' USLUGA ','usluga')])
def test_pg_old_raw_scope(pg_sessions,pg_case,raw,scope):
    with pg_sessions() as db:
        assert db.get_bind().dialect.name=='postgresql'
        result=service.add_color(db.get(User,pg_case['actors']['standard']),db,pg_case['models'][scope],ModelColorIn(color_name=' x '),raw)
    with pg_sessions() as db:
        row=db.get(ModelColor,result['id']);assert (row.model_id,row.color_name,row.color_code)==(pg_case['models'][scope],' x ',None)


@pytest.mark.parametrize('raw',[' ','unknown'])
def test_pg_invalid_scope_400_before_parent_and_length(pg_sessions,pg_case,raw):
    before=state(pg_sessions,pg_case)
    with pg_sessions() as db,pytest.raises(HTTPException) as exc:
        service.add_color(db.get(User,pg_case['actors']['standard']),db,-1,ModelColorIn(color_name='a'*65),raw)
    assert (exc.value.status_code,exc.value.detail)==(400,'Invalid model catalog scope')
    assert state(pg_sessions,pg_case)==before


def test_pg_actual_schema_writer_one_session_commit_and_refresh(pg_sessions,pg_case,pg_app,monkeypatch):
    before=state(pg_sessions,pg_case); observed=[]; original_refresh=Session.refresh
    def assignment(target,value,old,initiator):
        for frame in inspect.stack()[1:]:
            module=frame.frame.f_globals.get('__name__','')
            if module.startswith('app.'):
                observed.append((initiator.key,module));break
    def attach(session,instance):
        if isinstance(instance,ModelColor):
            for frame in inspect.stack()[1:]:
                module=frame.frame.f_globals.get('__name__','')
                if module.startswith('app.'):
                    observed.append(('add',module));break
    def request_session():
        with pg_sessions() as db:
            event.listen(db,'before_commit',lambda session:observed.append(('before_commit',id(session))))
            event.listen(db,'after_commit',lambda session:observed.append(('after_commit',id(session))))
            yield db
    def refresh(session,instance,*args,**kwargs):
        result=original_refresh(session,instance,*args,**kwargs)
        if isinstance(instance,ModelColor): observed.append(('refresh',id(session)))
        return result
    attrs=[ModelColor.model_id,ModelColor.color_name,ModelColor.color_code]
    for attr in attrs:event.listen(attr,'set',assignment)
    event.listen(Session,'before_attach',attach)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(Session,'refresh',refresh);pg_app.dependency_overrides[get_db]=request_session
            with TestClient(pg_app,raise_server_exceptions=False) as client:
                response=client.post(f"/api/models/{pg_case['models']['standard']}/colors",json={'color_name':'pg baseline','color_code':'x'})
    finally:
        for attr in attrs:event.remove(attr,'set',assignment)
        event.remove(Session,'before_attach',attach)
    assert response.status_code==201,response.text
    writes=[x for x in observed if x[0] in {'model_id','color_name','color_code','add'}]
    assert {x[0] for x in writes}=={'model_id','color_name','color_code','add'}
    assert all(module=='app.schemas.catalog.model_color_persistence' for _,module in writes)
    sequence=[x for x in observed if x[0] in {'before_commit','after_commit','refresh'}]
    assert [x[0] for x in sequence]==['before_commit','after_commit','refresh'] and len({x[1] for x in sequence})==1
    after=state(pg_sessions,pg_case)
    assert [x for x in after[0] if x[0]==response.json()['id']]==[(response.json()['id'],pg_case['models']['standard'],'pg baseline','x')]
    assert after[1:]==before[1:]


@pytest.mark.parametrize(('field','value'), [('color_name','x'*65),('color_code','x'*17)])
def test_pg_actual_varchar_constraint_rejects_oversize(pg_sessions,pg_case,field,value):
    before=state(pg_sessions,pg_case)
    with pg_sessions() as db:
        row=ModelColor(model_id=pg_case['models']['standard'],color_name='ok',color_code='x')
        setattr(row,field,value);db.add(row)
        with pytest.raises(sa.exc.DataError): db.flush()
        # Session close supplies rollback; no manual transaction repair.
    assert state(pg_sessions,pg_case)==before


def test_pg_real_fk_flush_failure_request_teardown_then_retry(pg_sessions,pg_case,pg_app):
    before=state(pg_sessions,pg_case); observed=[];mid=pg_case['models']['standard']
    def fail_session():
        with pg_sessions() as db:
            def before_commit(session):
                # Explicit test participant invokes actual FK validation during commit's flush.
                session.add(ModelColor(model_id=-2147483647,color_name='synthetic invalid fk'))
            def flush_failure(session,ctx): observed.append('after_soft_rollback')
            event.listen(db,'before_commit',before_commit)
            event.listen(db,'after_soft_rollback',flush_failure)
            yield db
    pg_app.dependency_overrides[get_db]=fail_session
    sqlstates=[]
    def capture_db_error(context):
        sqlstates.append(getattr(context.original_exception,'pgcode',None))
    engine=pg_sessions.kw['bind']
    event.listen(engine,'handle_error',capture_db_error)
    try:
        with TestClient(pg_app,raise_server_exceptions=False) as client:
            response=client.post(f'/api/models/{mid}/colors',json={'color_name':'valid','color_code':'x'})
    finally:
        event.remove(engine,'handle_error',capture_db_error)
    assert response.status_code==500 and observed and '23503' in sqlstates
    assert state(pg_sessions,pg_case)==before
    def normal():
        with pg_sessions() as db: yield db
    pg_app.dependency_overrides[get_db]=normal
    with TestClient(pg_app,raise_server_exceptions=False) as client:
        response=client.post(f'/api/models/{mid}/colors',json={'color_name':'valid','color_code':'x'})
    assert response.status_code==201,response.text
    after=state(pg_sessions,pg_case)
    assert [x for x in after[0] if x[0]==response.json()['id']]==[(response.json()['id'],mid,'valid','x')]
    assert after[1:]==before[1:]


@pytest.mark.parametrize('fault',['before_commit','after_flush_before_commit','refresh_after_commit'])
def test_pg_request_teardown_fault_then_fresh_readback_and_retry(pg_sessions,pg_case,pg_app,monkeypatch,fault):
    before=state(pg_sessions,pg_case);mid=pg_case['models']['standard'];observed=[];original=Session.refresh
    def fault_session():
        with pg_sessions() as db:
            def precommit(session):
                observed.append('before_commit')
                if fault=='before_commit': raise RuntimeError('injected before commit')
                if fault=='after_flush_before_commit':
                    session.flush();observed.append('flushed');raise RuntimeError('injected after flush before commit')
            event.listen(db,'before_commit',precommit);event.listen(db,'after_commit',lambda session:observed.append('after_commit'))
            yield db
    def refresh(session,instance,*args,**kwargs):
        result=original(session,instance,*args,**kwargs)
        if isinstance(instance,ModelColor):
            observed.append('refresh_delegated')
            if fault=='refresh_after_commit':raise RuntimeError('injected after committed refresh')
        return result
    with monkeypatch.context() as patch:
        patch.setattr(Session,'refresh',refresh);pg_app.dependency_overrides[get_db]=fault_session
        with TestClient(pg_app,raise_server_exceptions=False) as client: response=client.post(f'/api/models/{mid}/colors',json={'color_name':'retry','color_code':'x'})
    assert response.status_code==500
    after=state(pg_sessions,pg_case)
    if fault=='refresh_after_commit':
        assert observed.index('after_commit')<observed.index('refresh_delegated')
        assert len(after[0])==len(before[0])+1 and after[0][-1][1:]==(mid,'retry','x')
    else:
        assert 'after_commit' not in observed and after==before
        if fault=='after_flush_before_commit':assert 'flushed' in observed
    assert after[1:]==before[1:]
    def normal():
        with pg_sessions() as db:yield db
    pg_app.dependency_overrides[get_db]=normal
    with TestClient(pg_app,raise_server_exceptions=False) as client: retry=client.post(f'/api/models/{mid}/colors',json={'color_name':'retry','color_code':'x'})
    assert retry.status_code==201,retry.text
    final=state(pg_sessions,pg_case)
    assert len(final[0])==len(after[0])+1 and final[1:]==before[1:]
    retry_row=next(row for row in final[0] if row[0]==retry.json()['id'])
    assert retry_row[1:]==(mid,'retry','x')
    if fault=='refresh_after_commit':
        first_row=after[0][-1]
        assert first_row[1:]==(mid,'retry','x') and first_row[0]!=retry_row[0]


@pytest.mark.parametrize('same_value',[True,False])
def test_pg_bounded_concurrent_independent_and_duplicate_values(pg_sessions,pg_case,same_value):
    before=state(pg_sessions,pg_case);mid=pg_case['models']['standard']
    indices=count()
    def prepare(db):
        return db.get(User,pg_case['actors']['standard']),next(indices)
    def create(db,prepared):
        actor,index=prepared
        return service.add_color(actor,db,mid,ModelColorIn(color_name='same' if same_value else f'distinct-{index}',color_code=None))['id']
    ids=run_catalog_create_pair(pg_sessions,prepare,create,timeout=40)
    after=state(pg_sessions,pg_case)
    actual=[x for x in after[0] if x[0] in ids]
    expected=['same','same'] if same_value else ['distinct-0','distinct-1']
    assert len(set(ids))==2 and sorted(x[2] for x in actual)==sorted(expected) and all(x[1]==mid and x[3] is None for x in actual)
    assert after[1:]==before[1:]
    record('bounded_concurrency',same_value=same_value,ids=ids,observed=actual)


@pytest.mark.parametrize(('scope','actor'),[(CatalogScope.STANDARD,'standard'),(CatalogScope.USLUGA,'eco')])
def test_pg_canonical_scope_accepted(pg_sessions,pg_case,scope,actor):
    with pg_sessions() as db:
        result=service.add_color(db.get(User,pg_case['actors'][actor]),db,pg_case['models'][scope.value],ModelColorIn(color_name='enum'),scope)
    with pg_sessions() as db:
        row=db.get(ModelColor,result['id'])
        assert (row.model_id,row.color_name,row.color_code)==(pg_case['models'][scope.value],'enum',None)
