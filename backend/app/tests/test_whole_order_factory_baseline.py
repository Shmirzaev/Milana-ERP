"""Unchanged whole-order factory routing behavior; SQLite is not PG lock proof."""
from datetime import datetime, timezone
import sys
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import object_session

from app.libs.dto.production.production import CuttingSewingFactoryIn
from app.models import cutting_sewing_factory_service as service
from app.models.production import nastil_factory_service
from app.schemas import (AuditLog, Bundle, BundleScanLog, Department, Employee, Package,
    PackagingReceipt, PackagingRecord, PayrollQrLabel, PayrollRecord, ProductionOrder,
    SewingAssignment, WorkOrder)
from app.tests.conftest import TestSessionLocal
from app.tests.test_packaging_payroll_routing import routed_order


def audit_rows(db, po):
    return db.query(AuditLog).filter_by(entity_type='ProductionOrder',entity_id=po,action='change_sewing_factory').order_by(AuditLog.id).all()


def snapshot(db, po):
    works=db.query(WorkOrder).filter_by(production_order_id=po).order_by(WorkOrder.id).all()
    sewing=[w for w in works if w.operation=='sewing' and w.status!='cancelled']
    packaging=[w for w in works if w.operation=='packaging' and w.status!='cancelled']
    bundles=db.query(Bundle).filter_by(production_order_id=po).order_by(Bundle.id).all()
    live=[b for b in bundles if b.status!='cancelled']
    assignments=db.query(SewingAssignment).filter(SewingAssignment.work_order_id.in_([w.id for w in sewing])).order_by(SewingAssignment.id).all()
    return {'work_orders':[{'id':w.id,'department_id':w.department_id,'sewing_flow_id':w.sewing_flow_id} for w in sewing+packaging],
            'bundles':[{'id':b.id,'factory':b.sewing_factory_code,'current_department_id':b.current_department_id,'next_department_id':b.next_department_id} for b in live],
            'assignments':[{'id':a.id,'status':a.status} for a in assignments]}


def test_route_exact_snapshots_mapped_writes_and_preserved_fields(client,auth_headers,monkeypatch):
    po,batch,works,bundle_id,assignment_id=routed_order()
    with TestSessionLocal.begin() as db:
        departments={d.code:d.id for d in db.query(Department)}
        sewing=db.get(WorkOrder,works['sewing']);packaging=db.get(WorkOrder,works['packaging'])
        flow=sewing.sewing_flow_id;packaging.sewing_flow_id=flow
        # Make global ID order differ from snapshot sewing-then-packaging order.
        extra_pack=WorkOrder(production_order_id=po,operation='packaging',department_id=departments['PKG'],status='waiting',sewing_flow_id=flow)
        extra_sew=WorkOrder(production_order_id=po,operation='sewing',department_id=departments['MIL'],status='waiting',sewing_flow_id=flow)
        db.add_all([extra_pack,extra_sew]);db.flush()
        for status in ('cancelled','transferred'):
            db.add(SewingAssignment(work_order_id=sewing.id,production_batch_id=batch,sewing_flow_id=flow,quantity=1,status=status))
        original=db.get(Bundle,bundle_id)
        for current,next_,status in [('MIL','PKG','created'),('CUT','CUT','created'),('MIL','PKG','cancelled')]:
            db.add(Bundle(bundle_no=uuid4().hex,barcode=uuid4().hex,production_order_id=po,production_batch_id=batch,model_id=original.model_id,color='baseline',size='S',quantity=1,status=status,sewing_factory_code='MIL',current_department_id=departments[current],next_department_id=departments[next_]))
        db.add(BundleScanLog(bundle_id=bundle_id,scan_type='synthetic'))
        db.flush();before=snapshot(db,po)
        before_all=[(b.id,b.status,b.quantity,b.current_department_id,b.next_department_id,b.sewing_factory_code) for b in db.query(Bundle).filter_by(production_order_id=po).order_by(Bundle.id)]
        logs_before=db.query(BundleScanLog).filter_by(bundle_id=bundle_id).count();audit_before=len(audit_rows(db,po))
        extra_pack_id=extra_pack.id
    mapped=[];sessions=[];commits=[]
    def assignment(target,value,old,initiator):
        if not isinstance(target,(Bundle,WorkOrder,SewingAssignment)):return
        for frame in sys._getframe(1),:
            while frame:
                module=frame.f_globals.get('__name__','')
                if module.startswith('app.'):
                    mapped.append((type(target).__name__,initiator.key,module,id(object_session(target))));break
                frame=frame.f_back
    attrs=[Bundle.sewing_factory_code,Bundle.current_department_id,Bundle.next_department_id,WorkOrder.department_id,WorkOrder.sewing_flow_id,SewingAssignment.status]
    original=service.change_sewing_factory
    def delegate(db,*args,**kwargs):
        sessions.append(id(db));event.listen(db,'after_commit',lambda session:commits.append(id(session)))
        return original(db,*args,**kwargs)
    for attr in attrs:event.listen(attr,'set',assignment)
    monkeypatch.setattr(service,'change_sewing_factory',delegate)
    try:
        response=client.patch(f'/api/work-orders/{works["cutting"]}/sewing-factory',headers=auth_headers,json={'sewing_factory_code':'BST'})
    finally:
        for attr in attrs:event.remove(attr,'set',assignment)
    assert response.status_code==200,response.text
    assert response.json()=={'sewing_factory_code':'BST','changed':True}
    assert sessions==commits and len(sessions)==1
    assert {x[:2] for x in mapped}>={('Bundle','sewing_factory_code'),('WorkOrder','department_id'),('WorkOrder','sewing_flow_id'),('SewingAssignment','status')}
    assert all(module=='app.schemas.production.factory_routing' and session==sessions[0] for _,_,module,session in mapped),mapped
    with TestSessionLocal() as db:
        after=snapshot(db,po);logs=audit_rows(db,po)
        assert len(logs)==audit_before+1
        assert logs[-1].old_value_json==before
        assert logs[-1].new_value_json=={**after,'sewing_factory_code':'BST'}
        assert [r['id'] for r in before['work_orders']]!=sorted(r['id'] for r in before['work_orders'])
        assert db.get(WorkOrder,works['packaging']).sewing_flow_id==flow and db.get(WorkOrder,extra_pack_id).sewing_flow_id==flow
        assert [a['status'] for a in after['assignments']]==['cancelled','cancelled','transferred']
        after_all=[(b.id,b.status,b.quantity,b.current_department_id,b.next_department_id,b.sewing_factory_code) for b in db.query(Bundle).filter_by(production_order_id=po).order_by(Bundle.id)]
        assert all(old[2]==new[2] for old,new in zip(before_all,after_all))
        assert after_all[-1]==before_all[-1]
        assert after_all[1][3:]==(departments['BST'],departments['BPK'],'BST')
        assert after_all[2][3:]==(departments['CUT'],departments['CUT'],'BST')
        assert db.query(BundleScanLog).filter_by(bundle_id=bundle_id).count()==logs_before


@pytest.mark.parametrize('empty_live',[False,True])
def test_noop_ignores_packaging_flow_and_later_package_history_but_commits(client,auth_headers,monkeypatch,empty_live):
    po,_,works,bundle_id,_=routed_order();sessions=[];commits=[]
    with TestSessionLocal.begin() as db:
        db.get(WorkOrder,works['sewing']).department_id=db.query(Department.id).filter_by(code='MIL').scalar()
        pkg=db.get(WorkOrder,works['packaging']);pkg.department_id=db.query(Department.id).filter_by(code='BPK').scalar()
        pkg.sewing_flow_id=db.get(WorkOrder,works['sewing']).sewing_flow_id
        if empty_live:db.get(Bundle,bundle_id).status='cancelled'
        db.add(Package(package_no=uuid4().hex,barcode=uuid4().hex,production_order_id=po,color='synthetic'))
        db.flush();before=snapshot(db,po);before_audit=len(audit_rows(db,po));pkg_state=(pkg.department_id,pkg.sewing_flow_id)
    original=service.change_sewing_factory
    def delegate(db,*args,**kwargs):
        sessions.append(id(db));event.listen(db,'after_commit',lambda session:commits.append(id(session)))
        return original(db,*args,**kwargs)
    monkeypatch.setattr(service,'change_sewing_factory',delegate)
    response=client.patch(f'/api/work-orders/{works["cutting"]}/sewing-factory',headers=auth_headers,json={'sewing_factory_code':'MIL'})
    assert response.status_code==200 and response.json()=={'sewing_factory_code':'MIL','changed':False}
    assert sessions==commits and len(sessions)==1
    with TestSessionLocal() as db:
        assert snapshot(db,po)==before and len(audit_rows(db,po))==before_audit
        pkg=db.get(WorkOrder,works['packaging']);assert (pkg.department_id,pkg.sewing_flow_id)==pkg_state


def test_empty_selected_list_is_dto_invalid_but_direct_dispatches(monkeypatch):
    with pytest.raises(ValidationError):CuttingSewingFactoryIn(sewing_factory_code='BST',production_batch_ids=[])
    seen=[]
    def selected(db,work,factory,batch_ids,current):
        seen.append((db,work,factory,batch_ids,current));return {'selected':True}
    monkeypatch.setattr(nastil_factory_service,'change_nastil_factories',selected)
    values=(object(),object(),'BST',object())
    assert service.change_sewing_factory(*values,batch_ids=[])=={'selected':True}
    assert seen==[(values[0],values[1],'BST',[],values[3])]


@pytest.mark.parametrize(('state','expected'), [('55P03',409),('40001',None)])
def test_only_pg_lock_not_available_maps_to_409(monkeypatch,state,expected):
    class DriverError(Exception):
        pgcode=state
    error=OperationalError('synthetic',{},DriverError())
    def fail(*args,**kwargs):raise error
    monkeypatch.setattr(service,'_change',fail)
    if expected:
        with pytest.raises(HTTPException) as exc:service.change_sewing_factory(None,None,'BST',None)
        assert exc.value.status_code==expected and exc.value.detail=='Sewing is being updated. Reload this batch and try again.'
    else:
        with pytest.raises(OperationalError) as exc:service.change_sewing_factory(None,None,'BST',None)
        assert exc.value is error

@pytest.mark.parametrize('fault',['flush','audit'])
def test_request_teardown_rolls_back_and_retry_succeeds(client,auth_headers,monkeypatch,fault):
    po,_,works,_,_=routed_order()
    with TestSessionLocal() as db:
        before=snapshot(db,po); old_audits=len(audit_rows(db,po))
    original=service.change_sewing_factory
    original_log=service.log_action
    def delegate(db,*args,**kwargs):
        if fault=='flush':
            event.listen(db,'before_flush',lambda *a: (_ for _ in ()).throw(RuntimeError('synthetic flush failure')))
        return original(db,*args,**kwargs)
    def log_failure(db,*args,**kwargs):
        original_log(db,*args,**kwargs)
        db.flush()
        raise RuntimeError('synthetic audit failure after flush')
    with monkeypatch.context() as patch:
        patch.setattr(service,'change_sewing_factory',delegate)
        if fault=='audit': patch.setattr(service,'log_action',log_failure)
        with pytest.raises(RuntimeError,match='synthetic'):
            client.patch(f'/api/work-orders/{works["cutting"]}/sewing-factory',headers=auth_headers,json={'sewing_factory_code':'BST'})
    with TestSessionLocal() as db:
        assert snapshot(db,po)==before and len(audit_rows(db,po))==old_audits
    response=client.patch(f'/api/work-orders/{works["cutting"]}/sewing-factory',headers=auth_headers,json={'sewing_factory_code':'BST'})
    assert response.status_code==200 and response.json()['changed'] is True
    with TestSessionLocal() as db:
        assert len(audit_rows(db,po))==old_audits+1

@pytest.mark.parametrize('history',['package','payroll_label','payroll_record','receipt','packaging_record','assignment_completed','assignment_end','packaging_output'])
def test_history_prevents_change_without_partial_effects(client,auth_headers,history):
    po,batch,works,bundle_id,assignment_id=routed_order()
    with TestSessionLocal.begin() as db:
        if history=='package':
            db.add(Package(package_no=uuid4().hex,barcode=uuid4().hex,production_order_id=po,color='synthetic'))
        elif history=='payroll_label':db.add(PayrollQrLabel(label_uid=uuid4().hex,production_order_id=po))
        elif history=='payroll_record':
            employee=Employee(full_name='Synthetic employee');db.add(employee);db.flush()
            db.add(PayrollRecord(employee_id=employee.id,dedupe_key=uuid4().hex,scanned_at=datetime.now(timezone.utc),production_order_id=po))
        elif history=='receipt':db.add(PackagingReceipt(work_order_id=works['packaging'],source_work_order_id=works['sewing'],production_order_id=po,production_batch_id=batch,bundle_id=bundle_id,quantity=1,receive_method='scan'))
        elif history=='packaging_record':db.add(PackagingRecord(work_order_id=works['packaging']))
        elif history=='assignment_completed':db.get(SewingAssignment,assignment_id).status='completed'
        elif history=='assignment_end':db.get(SewingAssignment,assignment_id).actual_end=datetime.now(timezone.utc)
        else:db.get(WorkOrder,works['packaging']).actual_output_qty=1
        db.flush(); before=snapshot(db,po); audits=len(audit_rows(db,po))
    response=client.patch(f'/api/work-orders/{works["cutting"]}/sewing-factory',headers=auth_headers,json={'sewing_factory_code':'BST'})
    assert response.status_code==409 and response.json()['detail']=='SEWING_FACTORY_HISTORY_LOCKED'
    with TestSessionLocal() as db:
        assert snapshot(db,po)==before and len(audit_rows(db,po))==audits

@pytest.mark.parametrize('status',['completed','cancelled','rejected'])
def test_terminal_order_blocks_whole_change(client,auth_headers,status):
    po,_,works,_,_=routed_order()
    with TestSessionLocal.begin() as db:
        db.get(ProductionOrder,po).status=status
        db.flush();before=snapshot(db,po);audits=len(audit_rows(db,po))
    response=client.patch(f'/api/work-orders/{works["cutting"]}/sewing-factory',headers=auth_headers,json={'sewing_factory_code':'BST'})
    assert response.status_code==409 and response.json()['detail']=='SEWING_FACTORY_ORDER_LOCKED'
    with TestSessionLocal() as db:
        assert snapshot(db,po)==before and len(audit_rows(db,po))==audits

def test_prior_sewing_output_blocks_even_matching_noop(client,auth_headers):
    po,_,works,_,assignment_id=routed_order()
    with TestSessionLocal.begin() as db:
        db.get(WorkOrder,works['sewing']).department_id=db.query(Department.id).filter_by(code='MIL').scalar()
        db.get(SewingAssignment,assignment_id).completed_qty=1
        db.flush();before=snapshot(db,po);audits=len(audit_rows(db,po))
    response=client.patch(f'/api/work-orders/{works["cutting"]}/sewing-factory',headers=auth_headers,json={'sewing_factory_code':'MIL'})
    assert response.status_code==409 and response.json()['detail']==service.require_cutting_batch_mutable.__globals__['LOCKED_MESSAGE']
    with TestSessionLocal() as db:
        assert snapshot(db,po)==before and len(audit_rows(db,po))==audits

@pytest.mark.parametrize('payload',[{'sewing_factory_code':'BST','production_batch_ids':[]}, {'sewing_factory_code':'BAD'}])
def test_http_invalid_dto_has_no_effect(client,auth_headers,payload):
    po,_,works,_,_=routed_order()
    with TestSessionLocal() as db:
        before=snapshot(db,po);audits=len(audit_rows(db,po))
    response=client.patch(f'/api/work-orders/{works["cutting"]}/sewing-factory',headers=auth_headers,json=payload)
    assert response.status_code==422
    with TestSessionLocal() as db:
        assert snapshot(db,po)==before and len(audit_rows(db,po))==audits

@pytest.mark.parametrize('work_kind',['missing','noncutting'])
def test_missing_or_noncutting_work_rejected(client,auth_headers,work_kind):
    po,_,works,_,_=routed_order()
    work_id=99999999 if work_kind=='missing' else works['sewing']
    with TestSessionLocal() as db:
        before=snapshot(db,po);audits=len(audit_rows(db,po))
    response=client.patch(f'/api/work-orders/{work_id}/sewing-factory',headers=auth_headers,json={'sewing_factory_code':'BST'})
    assert response.status_code==404
    with TestSessionLocal() as db:
        assert snapshot(db,po)==before and len(audit_rows(db,po))==audits

@pytest.mark.parametrize(('factory','packaging'), [('MIL','PKG'),('BST','BPK'),('ECO','ECP')])
def test_real_factory_success_matrix(client,auth_headers,factory,packaging):
    po,_,works,bundle_id,_=routed_order()
    response=client.patch(f'/api/work-orders/{works["cutting"]}/sewing-factory',headers=auth_headers,json={'sewing_factory_code':factory})
    assert response.status_code==200 and response.json()=={'sewing_factory_code':factory,'changed':True}
    with TestSessionLocal() as db:
        assert db.get(WorkOrder,works['sewing']).department_id==db.query(Department.id).filter_by(code=factory).scalar()
        assert db.get(WorkOrder,works['packaging']).department_id==db.query(Department.id).filter_by(code=packaging).scalar()
        assert db.get(Bundle,bundle_id).sewing_factory_code==factory and len(audit_rows(db,po))==1

@pytest.mark.parametrize('case',['usluga','no_sewing','missing_target'])
def test_order_precondition_rejection(client,auth_headers,case):
    po,_,works,_,_=routed_order()
    with TestSessionLocal.begin() as db:
        if case=='usluga':db.get(ProductionOrder,po).source_type='usluga'
        elif case=='no_sewing':db.get(WorkOrder,works['sewing']).status='cancelled'
        else:db.query(Department).filter_by(code='BST').one().code='TMP-BST'
        db.flush();before=snapshot(db,po);audits=len(audit_rows(db,po))
    response=client.patch(f'/api/work-orders/{works["cutting"]}/sewing-factory',headers=auth_headers,json={'sewing_factory_code':'BST'})
    assert response.status_code==409 and response.json()['detail']=='SEWING_FACTORY_ORDER_LOCKED'
    with TestSessionLocal() as db:
        assert snapshot(db,po)==before and len(audit_rows(db,po))==audits

@pytest.mark.parametrize(('failure_call','count'),[(1,1),(2,2)])
def test_mutability_guards_rechecked_and_stop_in_order(client,auth_headers,monkeypatch,failure_call,count):
    po,_,works,_,_=routed_order();seen=[];original=service.require_cutting_batch_mutable
    def guarded(db,work,batch):
        seen.append((id(db),work.id,batch))
        if len(seen)==failure_call:raise HTTPException(409,'synthetic guard stop')
        return original(db,work,batch)
    with TestSessionLocal() as db:
        before=snapshot(db,po);audits=len(audit_rows(db,po))
    monkeypatch.setattr(service,'require_cutting_batch_mutable',guarded)
    response=client.patch(f'/api/work-orders/{works["cutting"]}/sewing-factory',headers=auth_headers,json={'sewing_factory_code':'BST'})
    assert response.status_code==409 and response.json()['detail']=='synthetic guard stop'
    assert len(seen)==count and len({x[0] for x in seen})==1 and all(x[1:]==(works['cutting'],None) for x in seen)
    with TestSessionLocal() as db:
        assert snapshot(db,po)==before and len(audit_rows(db,po))==audits
