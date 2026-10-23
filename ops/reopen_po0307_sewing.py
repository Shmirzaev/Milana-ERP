"""One-off owner-authorized status correction; never load at app startup.

Execute in the active backend: inspect, rehearse with rollback, then apply.
Only work order 1347's status/end_time/updated_at may change. Preserve every
linked business row and append one normal audit entry retaining the old state.
"""
import copy
import hashlib
import json

from sqlalchemy import text

from app.db.session import SessionLocal
from app.models import AuditLog, User
from app.services.audit import _audit_entry_hash, log_action


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def snapshot(db):
    result = {'production_orders': [dict(r) for r in db.execute(text(
        'SELECT * FROM production_orders WHERE id=346 FOR UPDATE')).mappings()]}
    order = result['production_orders'][0]
    assert order['production_no'] == 'PO-0307'
    links = db.execute(text("SELECT table_name,column_name FROM information_schema.columns "
                            "WHERE table_schema='public' AND column_name IN "
                            "('production_order_id','work_order_id','bundle_id','production_batch_id') "
                            "ORDER BY table_name,column_name")).all()
    tables = {}
    for table, column in links:
        tables.setdefault(table, []).append(column)
    predicates = {
        'production_order_id': 'production_order_id=346',
        'work_order_id': 'work_order_id IN (1346,1347,1348,1349)',
        'bundle_id': 'bundle_id IN (11459,11460,11461,11462,20161,20162,20163,20164)',
        'production_batch_id': 'production_batch_id IN (215,382)',
    }
    for table, columns in tables.items():
        result[table] = [dict(r) for r in db.execute(text(
            'SELECT * FROM "' + table + '" WHERE ' + ' OR '.join(predicates[c] for c in columns)
            + ' ORDER BY id FOR UPDATE')).mappings()]
    return result


def validate_evidence(rows):
    work = next(r for r in rows['work_orders'] if r['id'] == 1347)
    assert work['operation'] == 'sewing' and work['production_batch_id'] is None
    assert work['actual_input_qty'] == 256 and work['actual_output_qty'] == 128 and work['passed_qty'] == 128
    assert [(r['id'],r['quantity'],r['status']) for r in rows['bundles'] if r['production_batch_id']==382] == [
        (20161,32,'received_sewing'),(20162,32,'received_sewing'),
        (20163,32,'received_sewing'),(20164,32,'received_sewing')]
    assert [(r['id'],r['production_batch_id'],r['passed_qty']) for r in rows['sewing_records']] == [(101,215,128)]
    assert not [r for r in rows['sewing_assignments'] if r['production_batch_id']==382]
    return work


def run(mode, expected=None, backup=None):
    assert mode in {'inspect','rehearse','apply'}
    with SessionLocal() as db:
        db.execute(text("SET LOCAL lock_timeout='5s'"))
        db.execute(text("SET LOCAL statement_timeout='30s'"))
        before = snapshot(db)
        work = validate_evidence(before)
        fingerprint = digest(before)
        if mode == 'inspect':
            assert work['status'] == 'completed' and work['end_time']
            db.rollback()
            return {'fingerprint':fingerprint, 'work_order_status':work['status'],
                    'linked_rows':{k:len(v) for k,v in before.items()}}
        assert fingerprint == expected, 'Linked data changed since inspection; stop and review'
        assert work['status'] == 'completed' and work['end_time']
        assert backup and backup['bytes']>0 and backup['restore_objects']>100
        assert backup['mode']=='0o600' and len(backup['sha256'])==64
        target = copy.deepcopy(before)
        now = db.execute(text('SELECT clock_timestamp()')).scalar_one()
        corrected = next(r for r in target['work_orders'] if r['id']==1347)
        corrected.update(status='in_progress',end_time=None,updated_at=now)
        result = db.execute(text("UPDATE work_orders SET status='in_progress',end_time=NULL,updated_at=:now "
                                 "WHERE id=1347 AND production_order_id=346 AND status='completed'"),{'now':now})
        assert result.rowcount==1
        assert snapshot(db)==target, 'Unexpected linked business-row change'
        # No quantity, assignment, material, Packaging, order status or historical
        # timestamp is rewritten. The previous completion is retained in audit.
        audit=log_action(db,None,'reopen_po0307_sewing','WorkOrder',1347,
            old_value={'work_order':work,'linked_fingerprint':fingerprint},
            new_value={'status':'in_progress','end_time':None,'linked_fingerprint':digest(target),
                       'backup':backup,'reason':'Owner authorized reopening PO-0307 after Nastil 2 receipt; '
                       'Nastil 1 output and Packaging history must remain unchanged'})
        # Verify the actual department/list projection in the transaction.
        from app.api.routes.inbox import department_order_page
        current=db.get(User,1)
        assert current and current.is_active
        page=department_order_page(db,current,dept='SEW',tz='Asia/Tashkent',q='PO-0307',limit=50,offset=0)
        assert any(r.get('work_order_id',r.get('id'))==1347 and r.get('queue_kind')=='in_progress'
                   for r in page['rows']), 'PO-0307 is not visible on the active Sewing floor'
        assert snapshot(db)==target, 'Floor projection changed linked business data'
        if mode=='rehearse':
            db.rollback()
            assert snapshot(db)==before, 'Rollback did not restore exact linked state'
            db.rollback()
            return {'rollback_verified':True,'floor_visible':True,'fingerprint':fingerprint,
                    'changed_fields':['work_orders/1347/status','work_orders/1347/end_time','work_orders/1347/updated_at']}
        db.commit()
        audit_id=audit.id
        assert snapshot(db)==target
        saved=db.get(AuditLog,audit_id)
        assert saved.entry_hash==_audit_entry_hash(prev_hash=saved.prev_hash,user_id=saved.user_id,
            action=saved.action,entity_type=saved.entity_type,entity_id=saved.entity_id,
            old_value=saved.old_value_json,new_value=saved.new_value_json)
        db.rollback()
        return {'applied':True,'audit_id':audit_id,'floor_visible':True,'after_fingerprint':digest(target)}
