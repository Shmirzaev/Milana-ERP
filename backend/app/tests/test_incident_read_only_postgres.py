"""Actual PostgreSQL defense against old code mutating newer persisted facts."""
import os
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import Depends
from sqlalchemy import create_engine, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import create_database_engine, get_db
from app.main import app
from app.libs.dto.production.cutting_material import PassportMaterial
from app.schemas import (CuttingMaterialUsage, CuttingPassport, CuttingRecord, Department, Item, Model,
    ProductionOrder, Role, StockBatch, StockMovement, User, Warehouse, WorkOrder)
from app.schemas.inventory.eco_inventory import EcoMaterialBatch, EcoMaterialMovement


def test_old_recovery_preserves_grouped_rejected_eco_facts(client, monkeypatch):
    raw=os.environ.get('STABILIZATION_POSTGRES_URL')
    if not raw:
        pytest.skip('Set STABILIZATION_POSTGRES_URL for required PostgreSQL recovery gate')
    url=make_url(raw)
    assert url.get_backend_name()=='postgresql' and url.host in {'127.0.0.1','localhost','::1'}
    assert (url.database or '').endswith(('_qa','_ci')) and not url.query
    schema='incident_ro_'+uuid4().hex
    writer=create_engine(url)
    with writer.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    writable=writer.execution_options(schema_translate_map={None:schema})
    readonly=create_database_engine(str(url.render_as_string(hide_password=False)),incident_read_only=True)
    readonly=readonly.execution_options(schema_translate_map={None:schema})
    sessions=sessionmaker(bind=readonly,expire_on_commit=False)
    try:
        Base.metadata.create_all(writable)
        with sessionmaker(bind=writable,expire_on_commit=False)() as db:
            role=Role(name='Recovery inspector',permissions=['*','admin.super'])
            dept=Department(name='ECT recovery',code='ECT')
            db.add_all([role,dept]); db.flush()
            user=User(name='Recovery inspector',email='readonly@example.com',password_hash=hash_password('Read-only-qa-2026!'),factory_code='ECO',role_id=role.id)
            model=Model(code='RO-GROUP-01',name='Recovery grouped model',details_json={'legacy_import':True})
            item=Item(sku='RO-5A',name='Transferred fabric',category='fabric',unit='kg')
            warehouse=Warehouse(name='Recovery warehouse',type='fabric_storage',department_id=dept.id)
            db.add_all([user,model,item,warehouse]); db.flush()
            source=StockBatch(item_id=item.id,batch_no='5A',unit='kg',quantity=0,warehouse_id=warehouse.id,qc_status='passed',archived_at=datetime.now(timezone.utc))
            second=StockBatch(item_id=item.id,batch_no='CENTRAL-B',unit='kg',quantity=50,warehouse_id=warehouse.id,qc_status='passed')
            db.add_all([source,second]); db.flush()
            order=ProductionOrder(production_no='PO-RO-GROUPED',production_type='branded_stock',model_id=model.id,planned_quantity=600)
            rejected=ProductionOrder(production_no='PO-RO-REJECTED',production_type='branded_stock',model_id=model.id,planned_quantity=120)
            db.add_all([order,rejected]); db.flush()
            work=WorkOrder(production_order_id=order.id,department_id=dept.id,operation='cutting',status='in_progress',planned_input_qty=600,planned_output_qty=600)
            refused=WorkOrder(production_order_id=rejected.id,department_id=dept.id,operation='cutting',status='rejected',is_blocked=True,block_reason='New application rejection',planned_input_qty=120,planned_output_qty=120)
            db.add_all([work,refused]); db.flush()
            record=CuttingRecord(work_order_id=work.id,cut_pieces=600,passed_pieces=600,input_quantity=300)
            db.add(record); db.flush()
            material=PassportMaterial(stock_batch_id=source.id,pieces=600,layer_weight_kg=3,total_layers=100).model_dump()
            material['batch_allocations']=[{'stock_batch_id':source.id,'quantity':100},{'stock_batch_id':second.id,'quantity':200}]
            passport=CuttingPassport(passport_no='RO-GROUPED',production_order_id=order.id,date=datetime.now(timezone.utc),pieces=600,materials=[material])
            receipt=EcoMaterialBatch(item_id=item.id,kind='fabric',batch_no='5A',unit='kg',quantity=Decimal('51.8'),reserved_quantity=0,source_stock_batch_id=source.id,created_by=user.id)
            db.add_all([passport,receipt]); db.flush()
            movement=EcoMaterialMovement(batch_id=receipt.id,kind='consume',quantity=100,production_order_id=order.id,reference_type='CuttingRecord',reference_id=record.id,created_by=user.id)
            db.add_all([movement,StockMovement(item_id=item.id,batch_id=second.id,movement_type='consume',quantity=200,unit='kg',reference_type='CuttingRecord',reference_id=record.id,created_by=user.id)])
            for position,batch,quantity in [(1,source,100),(2,second,200)]:
                db.add(CuttingMaterialUsage(cutting_record_id=record.id,stock_batch_id=batch.id,quantity=quantity,unit='kg',position=position,details={'cut_pieces':600 if position==1 else 0}))
            db.commit()
            ids={'user':user.id,'work':refused.id,'group_work':work.id,'order':order.id,'passport':passport.id,'source':source.id,'receipt':receipt.id,'record':record.id}

        def snapshot():
            with writable.connect() as connection:
                return {table:connection.execute(text(f'SELECT row_to_json(t)::text FROM "{schema}"."{table}" t ORDER BY id')).scalars().all()
                    for table in ['users','work_orders','production_orders','cutting_passports','cutting_records','cutting_material_usages','stock_batches','eco_material_batches','eco_material_movements','bundles','stock_movements','waste_records','audit_logs']}

        before=snapshot()
        def override():
            with sessions() as db:
                yield db
        monkeypatch.setitem(app.dependency_overrides,get_db,override)
        monkeypatch.setattr(settings,'INCIDENT_READ_ONLY',True)
        response=client.post('/api/auth/login-json',json={'email':'readonly@example.com','password':'Read-only-qa-2026!','factory_code':'ECO'})
        assert response.status_code==200,response.text
        assert client.get('/api/auth/me').status_code==200
        assert client.get('/health').status_code==200
        assert client.get(f"/api/work-orders/{ids['work']}").status_code==200
        detail=client.get(f"/api/cutting-passports/{ids['passport']}")
        assert detail.status_code==200,detail.text
        assert detail.json()['pieces']==600
        with sessions() as db:
            persisted=db.get(CuttingPassport,ids['passport']).materials[0]['batch_allocations']
            assert [(row['stock_batch_id'],row['quantity']) for row in persisted]==[(source.id,100),(second.id,200)]
        for method,path in [('PATCH',f"/api/cutting-passports/{ids['passport']}"),('POST','/api/cutting/records'),
            ('POST',f"/api/work-orders/{ids['work']}/start"),('DELETE',f"/api/work-orders/{ids['work']}/batches/1"),('POST','/api/eco-inventory/consume'),('GET','/api/packages')]:
            response=client.request(method,path,json={})
            assert response.status_code==503,response.text

        # Every new transaction stays read-only, including repeated commits and
        # raw SQL. A hidden GET writer is stopped below the HTTP method guard.
        for _ in range(2):
            with sessions() as db:
                assert db.execute(text('SHOW default_transaction_read_only')).scalar_one()=='on'
                assert db.execute(text('SHOW transaction_read_only')).scalar_one()=='on'
                db.commit()
                with pytest.raises(DBAPIError) as failure:
                    db.execute(update(User).values(name='Forbidden raw write'))
                    db.commit()
                assert (getattr(failure.value.orig,'sqlstate',None) or getattr(failure.value.orig,'pgcode',None))=='25006'

        path='/api/incident-readonly-probe-'+uuid4().hex
        def hidden_write(db=Depends(get_db)):
            db.execute(update(User).values(name='Forbidden hidden GET write'))
            db.commit()
        app.add_api_route(path,hidden_write,methods=['GET'])
        try:
            assert client.get(path).status_code==503
        finally:
            app.router.routes[:]=[route for route in app.router.routes if getattr(route,'path',None)!=path]
        assert client.post('/api/auth/logout').status_code==200
        assert snapshot()==before
    finally:
        readonly.dispose()
        with writer.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        writer.dispose()
