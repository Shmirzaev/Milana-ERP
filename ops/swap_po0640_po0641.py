"""One-time owner-authorized Nastil exchange. No serving source is changed.

Run through run_po0640_swap.py; inspect -> backup -> rehearse -> apply -> verify.
The two order identities/plans stay in place. Actual Nastil records change owner
and use their destination order's model. PO-0641 Nastil 2/payroll are immutable.
"""
import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import text

from app.db.session import SessionLocal
from app.schemas import Package, PackagePrintRun, PackagePrintRunMember, SewingAssignment, SewingRecord, CuttingRecord, User, WorkOrder
from app.models.audit_service import log_action, _finalize_postgres_audits
from app.models.package_workflows_service import contents
from app.models.barcode_service import generate_barcode_value
from app.models.numbering_service import _next
from app.models.production.nastil_factory_service import change_nastil_factories
from app.models.sewing_input_service import sync_sewing_input
from app.models.workflow_service import _complete_if_done, sync_production_order_status, sync_storage_transfer_work_order

RELEASE = '20261116_130518'
BASE = '4d7cf17e55b165b1edc05407065f92597cebdbe5'
PACKAGES = (21328, 21329, 21330)
QUERIES = {
    'production_orders': 'id IN (682,683)',
    'production_batches': 'production_order_id IN (682,683) OR id IN (917,918,921)',
    'work_orders': 'production_order_id IN (682,683)',
    'cutting_passports': 'production_order_id IN (682,683) OR id IN (702,703,706)',
    'cutting_records': 'work_order_id IN (2691,2695) OR production_batch_id IN (917,918,921)',
    'bundles': 'production_order_id IN (682,683) OR production_batch_id IN (917,918,921)',
    'sewing_assignments': 'work_order_id IN (2692,2696) OR production_batch_id IN (917,918,921)',
    'sewing_records': 'work_order_id IN (2692,2696) OR production_batch_id IN (917,918,921)',
    'packaging_records': 'work_order_id IN (2693,2697) OR production_batch_id IN (917,918,921)',
    'packages': 'production_order_id IN (682,683) OR id IN (21328,21329,21330)',
    'package_items': 'package_id IN (21328,21329,21330)',
    'package_batch_allocations': 'production_batch_id IN (917,918,921)',
    'finished_goods_stock': 'production_order_id IN (682,683) OR package_id IN (21328,21329,21330)',
    'package_print_run_members': 'package_id IN (21328,21329,21330)',
    'package_print_runs': 'id IN (SELECT run_id FROM package_print_run_members WHERE package_id IN (21328,21329,21330))',
    'waste_records': 'production_order_id IN (682,683)',
    'payroll_qr_labels': 'production_order_id IN (682,683) OR production_batch_id IN (917,918,921)',
    'payroll_records': 'production_order_id IN (682,683) OR production_batch_id IN (917,918,921)',
    'production_order_items': 'production_order_id IN (682,683)',
    'production_order_materials': 'production_order_id IN (682,683)',
    'material_reservations': 'production_order_id IN (682,683)',
    'stock_batches': 'id IN (1629,2025)',
    'stock_movements': "reference_type='CuttingRecord' AND reference_id IN (872,874,880)",
    'cutting_material_usages': 'cutting_record_id IN (872,874,880)',
    'cutting_beika_material_usages': 'cutting_record_id IN (872,874,880)',
    'bundle_scan_logs': 'bundle_id IN (SELECT id FROM bundles WHERE production_order_id IN (682,683))',
    'package_scan_logs': 'package_id IN (21328,21329,21330)',
    'packaging_receipts': 'production_order_id IN (682,683)',
    'sewing_daily_reports': 'production_order_id IN (682,683)',
    'printing_records': 'work_order_id BETWEEN 2691 AND 2698',
    'quality_checks': 'work_order_id BETWEEN 2691 AND 2698',
    'sewing_replacement_requests': 'production_order_id IN (682,683)',
    'price_calculation_requests': 'cutting_passport_id IN (702,703,706)',
    'eco_material_movements': 'production_order_id IN (682,683)',
    'eco_accessory_plans': 'production_order_id IN (682,683)',
    'manual_accessory_issues': 'production_order_id IN (682,683)',
    'purchase_requests': 'production_order_id IN (682,683)',
    'shipment_packages': 'package_id IN (21328,21329,21330)',
    'shipment_scan_logs': 'package_id IN (21328,21329,21330)',
    'stock_reservations': 'package_id IN (21328,21329,21330) OR finished_goods_stock_id BETWEEN 50912 AND 50926',
    'warehouse_pack_reservations': 'package_id IN (21328,21329,21330)',
    'warehouse_stocktake_rows': 'package_id IN (21328,21329,21330)',
    'package_customer_releases': 'package_id IN (21328,21329,21330)',
    'package_quantity_adjustments': 'package_id IN (21328,21329,21330)',
    'package_change_requests': 'package_id IN (21328,21329,21330)',
    'package_barcode_aliases': 'package_id IN (21328,21329,21330)',
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def snapshot(db):
    result = {}
    for table, where in QUERIES.items():
        # Tables with no id have one row per package; JSON sorting is deterministic.
        rows = [dict(r) for r in db.execute(text(f'SELECT * FROM {table} WHERE {where}')).mappings()]
        result[table] = sorted(rows, key=lambda r: json.dumps(r, sort_keys=True, default=str))
    return json.loads(json.dumps(result, default=str))


def preconditions(before):
    def by_id(table):
        return {r['id']: r for r in before[table]}
    p = by_id('production_orders')
    assert (p[682]['production_no'], p[682]['model_id'], p[683]['production_no'], p[683]['model_id']) == ('PO-0640',1592,'PO-0641',8525)
    assert all(p[i]['source_type']=='standard' and p[i]['planned_quantity']==600 for i in p)
    b = by_id('production_batches')
    assert set(b)=={917,918,921}
    assert [(b[i]['production_order_id'],b[i]['cutting_passport_id'],b[i]['planned_quantity']) for i in (917,918,921)] == [(682,702,495),(683,703,405),(683,706,310)]
    w = by_id('work_orders')
    assert set(w)==set(range(2691,2699)) and all(r['production_batch_id'] is None for r in w.values())
    assert (w[2692]['department_id'],w[2696]['department_id'],w[2693]['department_id'],w[2697]['department_id'])==(8,7,10,9)
    assert len(before['bundles'])==15
    for batch,quantity,factory,status in [(917,495,'BST','created'),(918,405,'MIL','received_sewing'),(921,310,'MIL','received_sewing')]:
        rows=[r for r in before['bundles'] if r['production_batch_id']==batch]
        assert len(rows)==5 and sum(r['quantity'] for r in rows)==quantity
        assert all(r['sewing_factory_code']==factory and r['status']==status for r in rows)
    assert [(r['id'],r['production_batch_id'],r['sewn_qty']) for r in before['sewing_records']]==[(521,918,405)]
    assert [(r['id'],r['production_batch_id'],r['packed_qty']) for r in before['packaging_records']]==[(988,918,270)]
    assert {r['id'] for r in before['sewing_assignments']}=={263,311,312}
    assert {r['id'] for r in before['waste_records']}=={331,333,337}
    assert {r['id'] for r in before['packages']}==set(PACKAGES)
    assert sum(r['total_quantity'] for r in before['packages'])==270
    assert all(r['production_batch_id']==918 and r['status']=='received_in_storage' and r['dispatched_quantity']==0 for r in before['packages'])
    assert len(before['finished_goods_stock'])==15 and sum(r['quantity'] for r in before['finished_goods_stock'])==270
    assert all(r['quantity']==r['available_qty'] and r['sold_qty']==r['reserved_qty']==0 for r in before['finished_goods_stock'])
    assert len(before['package_print_run_members'])==3
    run=before['package_print_runs'];assert len(run)==1 and run[0]['received_at'] and not run[0]['superseded_at'] and not run[0]['returned_at']
    for table in ('payroll_records','payroll_qr_labels'):
        assert len(before[table])==122 and all(r['production_batch_id']==921 and r['production_order_id']==683 and r['work_order_id'] in (None,2697) for r in before[table])
        assert sum(r['work_order_id']==2697 for r in before[table])==15
    for table in ('material_reservations','packaging_receipts','sewing_daily_reports','printing_records','quality_checks','sewing_replacement_requests','price_calculation_requests','eco_material_movements','eco_accessory_plans','manual_accessory_issues','purchase_requests','shipment_packages','shipment_scan_logs','stock_reservations','warehouse_pack_reservations','warehouse_stocktake_rows','package_customer_releases','package_quantity_adjustments','package_change_requests'):
        assert not before[table], table


def update(db, table, row_id, values):
    names=list(values)
    r=db.execute(text(f"UPDATE {table} SET "+','.join(f'{name}=:{name}' for name in names)+' WHERE id=:row_id'),dict(values,row_id=row_id))
    assert r.rowcount==1,(table,row_id)


def verify_delta(before, after):
    allowed={
        'production_orders': {682:{'status','updated_at'},683:{'status','updated_at'}},
        'production_batches': {917:{'production_order_id','batch_no'},918:{'production_order_id','batch_no'}},
        'cutting_passports': {702:{'production_order_id','order_no','model_code','variant'},703:{'production_order_id','order_no','model_code','variant'}},
        'cutting_records': {872:{'work_order_id'},874:{'work_order_id'}},
        'waste_records': {331:{'production_order_id','work_order_id'},333:{'production_order_id','work_order_id'}},
        'sewing_records': {521:{'work_order_id'}},
        'sewing_assignments': {263:{'work_order_id'},311:{'work_order_id'}},
        'packaging_records': {988:{'work_order_id'}},
        'bundles': {r['id']:{'production_order_id','model_id'} for r in before['bundles'] if r['production_batch_id'] in (917,918)},
        'packages': {i:{'production_order_id','model_id','barcode','qr_code_url','updated_at'} for i in PACKAGES},
        'package_items': {r['id']:{'model_id'} for r in before['package_items']},
        'finished_goods_stock': {r['id']:{'production_order_id','model_id'} for r in before['finished_goods_stock']},
        'package_print_runs': {1082:{'superseded_at'}},
        'work_orders': {i:{'department_id','planned_input_qty','planned_output_qty','actual_input_qty','actual_output_qty','passed_qty','failed_qty','rework_qty','start_time','end_time','status','sewing_flow_id','updated_at'} for i in range(2691,2699)},
    }
    changes={}
    for table, rows in before.items():
        if rows and 'id' not in rows[0]:
            assert rows==after[table],table
            continue
        old={r['id']:r for r in rows};new={r['id']:r for r in after[table]}
        added=set(new)-set(old)
        assert not set(old)-set(new),table
        if table=='work_orders':
            assert len(added)==2
            assert {(new[i]['operation'],new[i]['department_id'],new[i]['production_batch_id'],new[i]['production_order_id'],new[i]['planned_output_qty']) for i in added}=={('sewing',8,917,683,495),('packaging',10,917,683,495)}
        elif table=='package_print_runs':
            assert len(added)==1 and new[1082]['superseded_at']
            replacement=new[next(iter(added))]
            for key in ('package_ids','packaging_department_code','received_at','received_by','receipt_location'):
                assert replacement[key]==old[1082][key],key
            assert replacement['created_by']==1 and not replacement['superseded_at']
        elif table=='package_print_run_members':
            assert len(added)==3 and {new[i]['package_id'] for i in added}==set(PACKAGES)
            for i in added:
                assert new[i]['snapshot']['production_order_id']==682 and new[i]['snapshot']['model_id']==1592
        else:
            assert not added,table
        if added:changes.setdefault(table,{})['_added_ids']=sorted(added)
        for i,row in old.items():
            fields={key for key in row if row[key]!=new[i][key]}
            assert fields <= allowed.get(table,{}).get(i,set()),(table,i,fields)
            if fields:changes.setdefault(table,{})[i]=sorted(fields)
    # Stronger than label-identity preservation: every stored payroll byte/field.
    assert before['payroll_qr_labels']==after['payroll_qr_labels']
    assert before['payroll_records']==after['payroll_records']
    for table,key,value in [('production_batches','id',921),('cutting_passports','id',706),('cutting_records','id',880),('bundles','production_batch_id',921),('sewing_assignments','id',312)]:
        assert [r for r in before[table] if r[key]==value]==[r for r in after[table] if r[key]==value],table
    return changes


def operation(mode, expected=None, backup=None, script_hash=None):
    assert mode in ('inspect','rehearse','apply','verify')
    with SessionLocal() as db:
        db.execute(text("SET LOCAL lock_timeout='5s'"))
        db.execute(text("SET LOCAL statement_timeout='45s'"))
        if mode in ('inspect','verify'):
            db.execute(text('SET TRANSACTION READ ONLY'))
            result=snapshot(db)
            if mode=='inspect':preconditions(result)
            return {'fingerprint':digest(result),'snapshot':result}
        # Match receiving/correction lock order: run -> order -> stage -> evidence.
        db.execute(text('SELECT id FROM package_print_runs WHERE id=1082 FOR UPDATE NOWAIT'))
        # Parent FOR UPDATE locks also
        # exclude FK-backed concurrent inserts for these orders/batches/packages.
        db.execute(text('SELECT id FROM production_orders WHERE id IN (682,683) ORDER BY id FOR UPDATE NOWAIT'))
        db.execute(text('SELECT id FROM work_orders WHERE production_order_id IN (682,683) ORDER BY id FOR UPDATE NOWAIT'))
        for table,where in QUERIES.items():
            db.execute(text(f'SELECT * FROM {table} WHERE {where} FOR UPDATE NOWAIT'))
        before=snapshot(db);preconditions(before)
        assert digest(before)==expected['fingerprint'],'Evidence changed: re-inspect/review required'
        assert backup and backup['bytes']>0 and backup['restore_objects']>100 and backup['mode']=='0o600'
        for batch,order,number in [(917,683,'0683-01'),(918,682,'0682-01')]:
            update(db,'production_batches',batch,{'production_order_id':order})
        for batch,number in [(917,'0683-01'),(918,'0682-01')]:
            update(db,'production_batches',batch,{'batch_no':number})
        for passport,order,number,code,variant in [(702,683,'PO-0641','BJ5007-V-3504','V-3504'),(703,682,'PO-0640','BJ5007-1996','1996')]:
            update(db,'cutting_passports',passport,dict(production_order_id=order,order_no=number,model_code=code,variant=variant))
        for record,work in [(872,2695),(874,2691)]:update(db,'cutting_records',record,{'work_order_id':work})
        for waste,order,work in [(331,683,2695),(333,682,2691)]:update(db,'waste_records',waste,dict(production_order_id=order,work_order_id=work))
        for r in before['bundles']:
            if r['production_batch_id'] in (917,918):
                order,model=(683,8525) if r['production_batch_id']==917 else (682,1592)
                update(db,'bundles',r['id'],dict(production_order_id=order,model_id=model))
        update(db,'sewing_records',521,{'work_order_id':2692})
        for i in (263,311):update(db,'sewing_assignments',i,{'work_order_id':2692})
        update(db,'packaging_records',988,{'work_order_id':2693})
        for table in ('packages','finished_goods_stock'):
            for r in before[table]:update(db,table,r['id'],dict(production_order_id=682,model_id=1592))
        for r in before['package_items']:update(db,'package_items',r['id'],{'model_id':1592})
        # Original printed/receipt evidence is immutable. Supersede it using the
        # same versioning policy as package_corrections_service; no trigger bypass.
        # System Admin is the existing maintenance account, not the old operator.
        assert db.get(User,1).name=='System Admin' and db.get(User,1).is_active
        run=db.get(PackagePrintRun,1082)
        run.superseded_at=datetime.now(timezone.utc)
        replacement=PackagePrintRun(run_no=_next(db,PackagePrintRun,'run_no','PRN'),
            code='PACKRUN:'+uuid4().hex,packaging_department_code=run.packaging_department_code,
            package_ids=list(PACKAGES),created_by=1,received_by=run.received_by,
            received_at=run.received_at,receipt_location=run.receipt_location,deleted_package_ids=[])
        db.add(replacement);db.flush()
        for i in PACKAGES:
            pkg=db.get(Package,i)
            pkg.barcode=generate_barcode_value('PKG');pkg.qr_code_url=None
            db.add(PackagePrintRunMember(run_id=replacement.id,package_id=i,snapshot=contents(pkg)))
        db.flush()
        works={r.id:r for r in db.query(WorkOrder).filter(WorkOrder.production_order_id.in_((682,683))).all()}
        fields=('actual_input_qty','actual_output_qty','passed_qty','failed_qty','rework_qty','start_time','end_time','status','sewing_flow_id')
        old={i:{name:getattr(w,name) for name in fields} for i,w in works.items()}
        # Preserve planned PO quantities; rebuild execution totals from moved evidence.
        for i,qty in [(2691,405),(2695,805)]:
            w=works[i];w.actual_input_qty=w.actual_output_qty=w.passed_qty=qty
            w.failed_qty=max(0,w.planned_output_qty-qty)
            evidence=db.query(CuttingRecord).filter_by(work_order_id=i).all()
            w.start_time=min(r.created_at for r in evidence)
            w.end_time=max(r.approved_at or r.created_at for r in evidence)
        for left,right in [(2692,2696),(2693,2697)]:
            for name in fields:
                setattr(works[left],name,old[right][name])
            for name in ('actual_input_qty','actual_output_qty','passed_qty','failed_qty','rework_qty'):
                setattr(works[right],name,0)
            works[right].status='in_progress' if right==2696 else 'waiting'
            works[right].start_time=works[right].end_time=None
        works[2692].department_id=7;works[2693].department_id=9
        works[2696].sewing_flow_id=9;works[2697].sewing_flow_id=None
        works[2696].start_time=db.get(SewingAssignment,312).actual_start
        # Per-order cutting targets: overproduction raises downstream plans.
        for i in (2696,2697,2698):works[i].planned_input_qty=works[i].planned_output_qty=805
        db.flush()
        db.expire_all()
        # Incoming unworked Nastil gets the supported separate BST/BPK routes.
        result=change_nastil_factories(db,db.get(WorkOrder,2695),'BST',[917],None)
        assert result['changed']
        db.flush();db.expire_all()
        # The shared MIL/PKG routes own only the untouched 310-piece Nastil now.
        for i in (2696,2697):
            w=db.get(WorkOrder,i);w.planned_input_qty=w.planned_output_qty=310
        for i in (2692,2696):sync_sewing_input(db,db.get(WorkOrder,i))
        db.flush()
        _complete_if_done(db,db.get(WorkOrder,2692))
        assert db.get(WorkOrder,2692).status=='completed'
        db.get(WorkOrder,2692).end_time=db.get(SewingAssignment,311).actual_end or db.get(SewingRecord,521).created_at
        for order in (682,683):
            sync_storage_transfer_work_order(db,order)
            if order==682:db.get(WorkOrder,2694).start_time=old[2698]['start_time']
            sync_production_order_status(db,order)
        db.flush()
        after=snapshot(db);changes=verify_delta(before,after)
        # Evidence/model consistency and packaging budget under actual application helpers.
        for order in (682,683):
            assert db.execute(text('SELECT count(*) FROM bundles b JOIN production_batches n ON n.id=b.production_batch_id JOIN production_orders p ON p.id=b.production_order_id WHERE p.id=:id AND (n.production_order_id<>p.id OR b.model_id<>p.model_id)'),{'id':order}).scalar()==0
        assert sum(r['quantity'] for r in after['finished_goods_stock'])==270
        assert {r['id']:r['status'] for r in after['production_orders']}=={682:'storage_transfer',683:'sewing'}
        log_action(db,None,'exchange_nastil_entries','ProductionOrder',683,
            old_value={'snapshots':{k:before[k] for k in changes},'fingerprint':digest(before)},
            new_value={'reason':'Owner explicitly requested exchange of PO-0641 Nastil 1 with PO-0640; preserve all payroll labels',
                       'snapshots':{k:after[k] for k in changes},'fingerprint':digest(after),
                       'backup':backup,'base_commit':BASE,'script_sha256':script_hash,
                       'payroll_sha256':digest(before['payroll_qr_labels']),
                       'payroll_records_sha256':digest(before['payroll_records'])})
        if mode=='rehearse':
            db.rollback()
            assert digest(snapshot(db))==digest(before),'Rollback did not restore scoped rows'
            return {'rollback_verified':True,'before':digest(before),'changes':changes,
                    'payroll_sha256':digest(before['payroll_qr_labels']),
                    'preview':after,'script_sha256':script_hash}
        _finalize_postgres_audits(db)
        db.commit()
        persisted=snapshot(db)
        assert digest(persisted)==digest(after)
        return {'committed':True,'before':digest(before),'after':digest(after),'changes':changes,
                'payroll_sha256':digest(persisted['payroll_qr_labels']),
                'payroll_records_sha256':digest(persisted['payroll_records']),
                'snapshot':persisted,'script_sha256':script_hash}
