"""Real PostgreSQL routing race and committed sibling conservation."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from fastapi import HTTPException

from app.schemas import (AuditLog, Bundle, CuttingRecord, Department, Model, ProductionBatch,
                         ProductionOrder, SewingRecord, User, WorkOrder)
from app.models.cutting_sewing_factory_service import change_sewing_factory
from app.tests.test_password_change_races import password_change_postgres_sessions  # noqa: F401


def test_postgres_competing_nastil_routes_commit_once_preserving_sibling(password_change_postgres_sessions):
    sessions, _ = password_change_postgres_sessions
    with sessions() as db:
        marker = uuid4().hex[:12]
        actor = User(name='QA routing actor', email=f'{marker}@qa.local', password_hash='unused')
        model = Model(code=f'QA-{marker}',name='Routing fixture',status='approved')
        departments = {code: Department(code=code,name=code) for code in ('CUT','MIL','BST','PKG','BPK')}
        db.add_all([actor, model, *departments.values()]); db.flush()
        order = ProductionOrder(production_no=f'QA-{marker}',model_id=model.id,planned_quantity=90,production_type='branded_stock')
        db.add(order); db.flush()
        batches = [ProductionBatch(production_order_id=order.id,batch_index=i,batch_no=f'{marker}-{i}',planned_quantity=30) for i in (1,2,3)]
        db.add_all(batches);db.flush()
        works = {op: WorkOrder(production_order_id=order.id,operation=op,department_id=departments[code].id,
                    planned_input_qty=90,planned_output_qty=90,status='in_progress')
                 for op,code in (('cutting','CUT'),('sewing','MIL'),('packaging','PKG'))}
        db.add_all(works.values());db.flush()
        for batch in batches:
            db.add(CuttingRecord(work_order_id=works['cutting'].id,production_batch_id=batch.id,cut_pieces=30,passed_pieces=30))
            db.add(Bundle(bundle_no=f'{marker}-{batch.id}',barcode=f'{marker}-{batch.id}',production_order_id=order.id,
                production_batch_id=batch.id,model_id=model.id,color='White',size='S',quantity=30,status='received_sewing',
                sewing_factory_code='MIL',current_department_id=departments['MIL'].id,next_department_id=departments['PKG'].id))
        db.add(SewingRecord(work_order_id=works['sewing'].id,production_batch_id=batches[0].id,input_qty=30,sewn_qty=30,passed_qty=30))
        works['sewing'].actual_input_qty=90
        works['sewing'].passed_qty=works['sewing'].actual_output_qty=30
        db.commit()
        oid, wid, uid = order.id, works['cutting'].id, actor.id
        selected = [b.id for b in batches[1:]]
    barrier = Barrier(2)
    def change(_):
        with sessions() as db:
            work, user = db.get(WorkOrder,wid),db.get(User,uid)
            barrier.wait(timeout=10)
            try:
                result = change_sewing_factory(db,work,'BST',user,selected)
                db.commit()
                return 200,result['changed']
            except HTTPException as rejected:
                db.rollback()
                return rejected.status_code,False
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(change,range(2)))
    assert all(status in {200,409} for status,_ in results),results
    assert sum(changed for _,changed in results) == 1
    with sessions() as db:
        result = change_sewing_factory(db,db.get(WorkOrder,wid),'BST',db.get(User,uid),selected)
        assert not result['changed'];db.commit()
    with sessions() as db:
        assert db.query(WorkOrder).filter_by(production_order_id=oid,operation='sewing').count() == 3
        assert sum(w.planned_output_qty for w in db.query(WorkOrder).filter_by(production_order_id=oid,operation='sewing')) == 90
        assert db.query(SewingRecord).join(WorkOrder).filter(WorkOrder.production_order_id==oid).one().passed_qty == 30
        assert db.query(AuditLog).filter_by(entity_type='ProductionOrder',entity_id=oid,action='change_nastil_factory').count() == 1
