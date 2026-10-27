"""Frozen 8a characterization. Owned migrated-constraint PG fixture; no app edits."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from decimal import Decimal

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.session import get_db
from app.core.deps import get_current_user
from app.api.routes.catalog import router as catalog_router
from app.api.routes.usluga import router as usluga_router
from app.schemas import Model, ModelBOM, Item, StockBatch, Warehouse, Role, User, AuditLog
from app.models.catalog import models_service as service
from app.models import audit_service
from app.libs.dto.catalog.model_bom_input import ModelBOMIn
from app.libs.dto.catalog.model_bom_update import ModelBOMUpdate
from app.libs.dto.catalog.model_bom_output import ModelBOMOut
from app.libs.dto.catalog.model_input import ModelVariantCreateIn

url=make_url(os.environ['BOM_REVIEW_URL'])
assert url.host=='127.0.0.1' and url.port==51716 and url.database.startswith('review_bom_add_')
engine=create_engine(url)
Sessions=sessionmaker(bind=engine,autoflush=False,expire_on_commit=False)

@pytest.fixture(autouse=True)
def case():
    with engine.begin() as c:
        c.exec_driver_sql('TRUNCATE models, items, warehouses, users, roles, audit_logs RESTART IDENTITY CASCADE')
    with Sessions.begin() as db:
        role=Role(name='BOM reviewer',permissions=['modeling.bom','usluga.manage'])
        warehouse=Warehouse(name='Synthetic BOM warehouse',type='fabric')
        db.add_all([role,warehouse]);db.flush()
        actors=[User(name=f'BOM {factory}',email=f'{factory}@example.invalid',password_hash='unused',role_id=role.id,factory_code=factory,is_active=True) for factory in ['MIL','ECO']]
        models=[Model(code=f'BOM-{scope}',name='BOM characterization',catalog_scope=scope,factory_code=factory) for scope,factory in [('standard','MIL'),('usluga','ECO')]]
        items=[Item(sku=f'BOM-{category}',name=category,category=category,unit='kg' if category in ('fabric','semi_finished') else 'pcs',is_active=False) for category in ['fabric','semi_finished','accessory','packaging','finished','waste']]
        db.add_all(actors+models+items);db.flush()
        batches=[StockBatch(item_id=item.id,batch_no=f'BOM-{item.id}',quantity=10,unit=item.unit,warehouse_id=warehouse.id,color='Batch blue',image_url='https://example.invalid/batch.png') for item in items]
        db.add_all(batches);db.flush()
        return dict(role=role.id,actors=dict(zip(['standard','usluga'],[r.id for r in actors])),models=dict(zip(['standard','usluga'],[r.id for r in models])),items={r.category:r.id for r in items},batches={r.category:b.id for r,b in zip(items,batches)})

@pytest.fixture
def client(case):
    app=FastAPI();app.include_router(catalog_router,prefix='/api');app.include_router(usluga_router,prefix='/api')
    def db_override():
        with Sessions() as db:yield db
    def actor(request:Request):
        with Sessions() as db:
            user=db.get(User,case['actors'][request.headers.get('X-Review-Scope','standard')])
            _=user.role,user.department
            db.expunge_all();return user
    app.dependency_overrides[get_db]=db_override;app.dependency_overrides[get_current_user]=actor
    with TestClient(app,raise_server_exceptions=False) as c:yield c

def payload(case,category='accessory',**extra):
    return {'item_id':case['items'][category],'quantity_per_piece':1,'unit':'pcs',**extra}

def manual(**extra):return {'material_name':' Cotton ','material_role':'main','quantity_per_piece':1,'unit':'kg',**extra}

def post(client,case,scope='standard',body=None,actor_scope=None,model_scope=None):
    prefix='/api/usluga/models' if scope=='usluga' else '/api/models'
    return client.post(f"{prefix}/{case['models'][model_scope or scope]}/bom",headers={'X-Review-Scope':actor_scope or scope},json=body or payload(case))

def counts():
    with Sessions() as db:return db.query(ModelBOM).count(),db.query(AuditLog).count()

@pytest.mark.parametrize('role',['main',' MAIN ','secondary',' Secondary '])
def test_manual_normalizes_role_name_and_discards_stale_references(case,client,role):
    r=post(client,case,'usluga',manual(material_role=role,item_id=999999,stock_batch_id=999998))
    assert r.status_code==201,r.text
    assert set(r.json())=={'id'}
    with Sessions() as db:
        row=db.get(ModelBOM,r.json()['id'])
        assert (row.material_name,row.material_role,row.item_id,row.stock_batch_id)==('Cotton',role.strip().lower(),None,None)
        audit=db.query(AuditLog).one()
        assert (audit.action,audit.entity_type,audit.entity_id,audit.new_value_json)==('create','ModelBOM',row.id,{'model_id':case['models']['usluga']})
        assert audit.entry_hash and type(row.material_role) is str

@pytest.mark.parametrize('role',[None,'','  ','fabric','trim','MAIN_WRONG'])
def test_manual_invalid_role_is_currently_service400_and_no_write(case,client,role):
    r=post(client,case,'usluga',manual(material_role=role))
    assert r.status_code==400 and 'Choose whether' in r.json()['detail']
    assert counts()==(0,0)

@pytest.mark.parametrize('scope',['standard','usluga'])
@pytest.mark.parametrize('role',[None,'unrecognized',' MAIN '])
def test_inventory_link_ignores_supplied_role_and_whitespace_name(case,client,scope,role):
    r=post(client,case,scope,payload(case,material_name='  ',material_role=role))
    assert r.status_code==201,r.text
    with Sessions() as db:
        row=db.get(ModelBOM,r.json()['id'])
        assert row.item_id==case['items']['accessory'] and row.material_name is None and row.material_role is None

def test_inventory_role_length_still_validated_before_normalization(case,client):
    r=post(client,case,body=payload(case,material_role='x'*17))
    assert r.status_code==422 and counts()==(0,0)

@pytest.mark.parametrize('category',['fabric','semi_finished'])
def test_standard_fabric_discards_nonexistent_batch_and_fills_blank_unit(case,client,category):
    r=post(client,case,body=payload(case,category,stock_batch_id=999999,unit=''))
    assert r.status_code==201,r.text
    with Sessions() as db:
        row=db.get(ModelBOM,r.json()['id']);assert row.stock_batch_id is None and row.unit=='kg'

@pytest.mark.parametrize('category',['fabric','semi_finished','finished','waste'])
def test_usluga_disallows_inventory_fabric_and_nonaccessory_categories(case,client,category):
    r=post(client,case,'usluga',payload(case,category))
    assert r.status_code==400 and counts()==(0,0)

@pytest.mark.parametrize('category',['accessory','packaging'])
def test_batch_link_defaults_and_explicit_overrides(case,client,category):
    r=post(client,case,'usluga',payload(case,category,stock_batch_id=case['batches'][category]))
    assert r.status_code==201,r.text
    with Sessions() as db:
        row=db.get(ModelBOM,r.json()['id']);assert (row.color,row.photo_url)==('Batch blue','https://example.invalid/batch.png')
    r=post(client,case,body=payload(case,category,stock_batch_id=case['batches'][category],color='Explicit red',photo_url='/storage/model-files/chosen.png'))
    assert r.status_code==201,r.text
    with Sessions() as db:
        row=db.get(ModelBOM,r.json()['id']);assert (row.color,row.photo_url)==('Explicit red','/storage/model-files/chosen.png')

@pytest.mark.parametrize('changes,expected,detail',[
    ({'item_id':999999},404,'Inventory master item not found'),
    ({'stock_batch_id':999999},404,'Stock batch not found'),
    ({'material_name':'Cotton','material_role':'main'},400,'Manual fabric names'),
    ({'photo_url':'javascript:alert(1)'},400,'Unsupported file URL'),
    ({'photo_url':'/private/file.png'},400,'File URL must'),
])
def test_reference_and_photo_failures_do_not_write(case,client,changes,expected,detail):
    r=post(client,case,body=payload(case,**changes))
    assert r.status_code==expected and detail in r.json()['detail']
    assert counts()==(0,0)

def test_batch_must_belong_to_selected_item(case,client):
    r=post(client,case,body=payload(case,stock_batch_id=case['batches']['packaging']))
    assert r.status_code==400 and 'does not belong' in r.text and counts()==(0,0)

@pytest.mark.parametrize('scope',['standard','usluga'])
def test_wrong_catalog_scope_is404(case,client,scope):
    other='usluga' if scope=='standard' else 'standard'
    r=post(client,case,scope,model_scope=other)
    assert r.status_code==404 and counts()==(0,0)

@pytest.mark.parametrize('scope',['standard','usluga'])
def test_permission_revocation_is_enforced(case,client,scope):
    with Sessions.begin() as db:db.get(Role,case['role']).permissions=['modeling.models']
    r=post(client,case,scope)
    assert r.status_code==403 and counts()==(0,0)

def test_usluga_requires_selected_eco_factory(case,client):
    r=post(client,case,'usluga',actor_scope='standard')
    assert r.status_code==403 and 'Eco Cotton' in r.text and counts()==(0,0)

@pytest.mark.parametrize('quantity',[-1,0,0.12345])
def test_existing_numeric_policy_and_pg_rounding_preserved(case,client,quantity):
    r=post(client,case,body=payload(case,quantity_per_piece=quantity,waste_percent=-2))
    assert r.status_code==201,r.text
    with Sessions() as db:
        row=db.get(ModelBOM,r.json()['id'])
        assert row.quantity_per_piece==Decimal(str(quantity)).quantize(Decimal('.0001'),rounding='ROUND_HALF_UP')
        assert row.waste_percent==Decimal('-2')

def test_second_main409_secondary_repeated_and_other_model_main_allowed(case,client):
    first=post(client,case,'usluga',manual());assert first.status_code==201
    duplicate=post(client,case,'usluga',manual());assert duplicate.status_code==409
    for _ in range(2):assert post(client,case,'usluga',manual(material_role='secondary')).status_code==201
    with Sessions.begin() as db:
        other=Model(code='BOM-other',name='Other',catalog_scope='usluga',factory_code='ECO');db.add(other);db.flush();other_id=other.id
    with Sessions() as db:service.add_bom(db.get(User,case['actors']['usluga']),db,other_id,ModelBOMIn(**manual()),'usluga')
    assert counts()==(4,4)

def test_shared_patch_and_output_contract_remain_permissive_but_identity_rules_apply(case,client):
    assert ModelBOMUpdate(material_role='historical').material_role=='historical'
    legacy=ModelBOMOut.model_validate({'id':100,'material_role':'historical','quantity_per_piece':1,'unit':'kg','waste_percent':0})
    assert legacy.material_role=='historical'  # Contract evidence, not a claim migrated DB permits this value.
    r=post(client,case,'usluga',manual());bid=r.json()['id']
    with Sessions() as db:
        actor=db.get(User,case['actors']['usluga'])
        service.update_bom(actor,db,case['models']['usluga'],bid,ModelBOMUpdate(quantity_per_piece=2),'usluga')
        assert db.get(ModelBOM,bid).material_role=='main'
        service.update_bom(actor,db,case['models']['usluga'],bid,ModelBOMUpdate(material_role=' SECONDARY '),'usluga')
        assert db.get(ModelBOM,bid).material_role=='secondary'

def test_clone_and_variant_copy_roles_without_calling_add_bom(case,client,monkeypatch):
    assert post(client,case,'usluga',manual(color='Original')).status_code==201
    assert post(client,case,'usluga',manual(material_role='secondary',material_name='Lining',color='Lining color')).status_code==201
    monkeypatch.setattr(service,'add_bom',lambda *a,**k:pytest.fail('Clone/variant unexpectedly delegated to add_bom'))
    with Sessions() as db:
        actor=db.get(User,case['actors']['usluga']);mid=case['models']['usluga']
        cloned=service.clone_model(actor,db,mid,'usluga')
        variant=service.create_model_variant(actor,db,mid,ModelVariantCreateIn(variant_no='V1',color='Variant red'),'usluga')
        def value(result):return result.id if hasattr(result,'id') else result['id']
        clone_rows=db.query(ModelBOM).filter_by(model_id=value(cloned)).all()
        variant_rows=db.query(ModelBOM).filter_by(model_id=value(variant)).all()
        assert sorted((r.material_role,r.material_name,r.color) for r in clone_rows)==[('main','Cotton','Original'),('secondary','Lining','Lining color')]
        assert sorted((r.material_role,r.material_name,r.color) for r in variant_rows)==[('main','Cotton','Variant red'),('secondary','Lining','Lining color')]

def test_same_session_audit_outer_commit_and_precommit_invisibility(case,monkeypatch):
    original=service.log_action;commits=[];seen=[]
    with Sessions() as db:
        actor=db.get(User,case['actors']['standard'])
        event.listen(db,'after_commit',lambda s:commits.append(s))
        def audit(session,*args,**kwargs):
            assert session is db and not commits
            with engine.connect() as observer:assert observer.execute(text('SELECT count(*) FROM model_bom')).scalar_one()==0
            seen.append(session);return original(session,*args,**kwargs)
        monkeypatch.setattr(service,'log_action',audit)
        service.add_bom(actor,db,case['models']['standard'],ModelBOMIn(**payload(case)))
        assert seen==[db] and commits==[db]
    assert counts()==(1,1)

@pytest.mark.parametrize('failure',['queued','finalized','audit_actor_fk'])
def test_real_audit_failure_rolls_back_bom_and_audit(case,monkeypatch,failure):
    if failure=='queued':
        original=service.log_action
        def fail(*args,**kwargs):original(*args,**kwargs);raise RuntimeError('BOM queued audit challenge')
        monkeypatch.setattr(service,'log_action',fail)
    elif failure=='finalized':
        original=audit_service.add_audit_log_rows
        def fail(db,rows):original(db,rows);db.flush();raise RuntimeError('BOM finalized audit challenge')
        monkeypatch.setattr(audit_service,'add_audit_log_rows',fail)
    with Sessions() as db:
        actor=db.get(User,case['actors']['standard']) if failure!='audit_actor_fk' else User(id=999999,name='Missing audit actor')
        with pytest.raises(IntegrityError if failure=='audit_actor_fk' else RuntimeError):
            service.add_bom(actor,db,case['models']['standard'],ModelBOMIn(**payload(case)))
        db.rollback()
    assert counts()==(0,0)

@pytest.mark.parametrize('values,constraint',[
    ({'item_id':None,'material_name':None,'material_role':None},'ck_model_bom_item_or_manual_material'),
    ({'item_id':'fixture','material_name':'Cotton','material_role':'main'},'ck_model_bom_item_or_manual_material'),
    ({'item_id':None,'material_name':'Cotton','material_role':'trim'},'ck_model_bom_material_role'),
    ({'item_id':'fixture','material_name':None,'material_role':'main'},'ck_model_bom_material_role'),
])
def test_actual_migration_checks_reject_invalid_storage(case,values,constraint):
    values={k:(case['items']['accessory'] if v=='fixture' else v) for k,v in values.items()}
    with Sessions() as db:
        db.add(ModelBOM(model_id=case['models']['usluga'],quantity_per_piece=1,unit='kg',**values))
        with pytest.raises(IntegrityError) as error:db.flush()
        assert error.value.orig.diag.constraint_name==constraint
        db.rollback()
    assert counts()==(0,0)

def test_nullable_sql_check_is_not_a_nonnull_role_guarantee(case):
    with Sessions.begin() as db:
        row=ModelBOM(model_id=case['models']['usluga'],material_name='Direct null role',material_role=None,quantity_per_piece=1,unit='kg')
        db.add(row);db.flush();bid=row.id
    with Sessions() as db:assert db.get(ModelBOM,bid).material_role is None
    # Existing SQL CHECK accepts UNKNOWN; service rejects this input. No repair policy is invented.

def test_competing_main_creates_reach_unique_index_one_business_outcome(case,monkeypatch):
    barrier=Barrier(2);original=service._ensure_unique_usluga_main_material
    def synchronized(db,mid,data,**kwargs):
        original(db,mid,data,**kwargs);barrier.wait(timeout=12)
    monkeypatch.setattr(service,'_ensure_unique_usluga_main_material',synchronized)
    def create():
        with Sessions() as db:
            try:
                result=service.add_bom(db.get(User,case['actors']['usluga']),db,case['models']['usluga'],ModelBOMIn(**manual()),'usluga')
                return ('created',result['id'])
            except IntegrityError as error:
                constraint=error.orig.diag.constraint_name;db.rollback();return ('integrity',constraint)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:create(),range(2)))
    assert sorted(r[0] for r in results)==['created','integrity']
    assert next(r[1] for r in results if r[0]=='integrity')=='uq_model_bom_main_material_per_model'
    assert counts()==(1,1)

def test_post_openapi_current_nullable_free_string_role_and_id_only_wire(case,client):
    schema=client.get('/openapi.json').json()['components']['schemas']['ModelBOMIn']
    role=schema['properties']['material_role']
    assert 'default' not in role and role['anyOf']==[{'type':'string','maxLength':16},{'type':'null'}]
    assert ModelBOMIn.model_fields['material_role'].default is None
    assert 'quantity_per_piece' in schema['required'] and 'unit' in schema['required']
    assert 'material_role' not in schema['required']

def test_blanket_strict_role_mutation_would_break_inventory_compatibility(case,client,monkeypatch):
    original=service.add_bom
    def globally_strict(current,db,mid,payload,catalog_scope='standard'):
        if payload.material_role not in (None,'main','secondary'):raise HTTPException(422,'Synthetic blanket enum boundary')
        return original(current,db,mid,payload,catalog_scope)
    monkeypatch.setattr(service,'add_bom',globally_strict)
    r=post(client,case,body=payload(case,material_role='unrecognized'))
    assert r.status_code==422 and counts()==(0,0)
    # Companion baseline tests require 201 for this exact accepted inventory branch.
