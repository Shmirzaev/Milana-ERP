"""Owner-authorized, one-off PO-0328 size correction; execute in active backend.

Call run('inspect'), then run('rehearse', fingerprint, backup), then run('apply',
fingerprint, backup). Never import this as an application startup operation.
"""
import copy
import hashlib
import json

from sqlalchemy import text

from app.db.session import SessionLocal
from app.models import AuditLog, Bundle
from app.services.audit import _audit_entry_hash, log_action
from app.services.bundles import bundle_qr_payload, find_bundle_by_scanned_code


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def snapshot(db):
    """Lock and fingerprint all order/work-order/bundle-linked business rows."""
    result = {}
    result['production_orders'] = [dict(r) for r in db.execute(text(
        'SELECT * FROM production_orders WHERE id=367 FOR UPDATE')).mappings()]
    order = result['production_orders'][0]
    assert order['production_no'] == 'PO-0328' and order['model_id'] == 8510
    assert order['planned_quantity'] == 600 and order['status'] == 'packaging'
    cols = db.execute(text("SELECT table_name,column_name FROM information_schema.columns "
                           "WHERE table_schema='public' AND column_name IN "
                           "('production_order_id','work_order_id','bundle_id') ORDER BY table_name")).all()
    tables = {}
    for table, column in cols:
        tables.setdefault(table, []).append(column)
    for table, columns in tables.items():
        if table == 'production_orders':
            continue
        predicates = []
        for column in columns:
            predicates.append({
                'production_order_id': 'production_order_id=367',
                'work_order_id': 'work_order_id IN (1430,1431,1432,1433)',
                'bundle_id': 'bundle_id IN (11489,11490,11491,11492,11493,11494)',
            }[column])
        result[table] = [dict(r) for r in db.execute(text(
            'SELECT * FROM "' + table + '" WHERE ' + ' OR '.join(predicates)
            + ' ORDER BY id FOR UPDATE')).mappings()]
    result['model_sizes'] = [dict(r) for r in db.execute(text(
        'SELECT * FROM model_sizes WHERE model_id=8510 ORDER BY id FOR UPDATE')).mappings()]
    assert {r['size'] for r in result['model_sizes']} == {'44','46','48','50','52','54'}
    assert not result['packages'] and not result['finished_goods_stock']
    assert not result['payroll_qr_labels'] and not result['payroll_records']
    assert all(not r['size_quantities'] for r in result['sewing_records'])
    return result


def run(mode, expected=None, backup=None):
    assert mode in {'inspect','rehearse','apply'}
    with SessionLocal() as db:
        db.execute(text("SET LOCAL lock_timeout='5s'"))
        db.execute(text("SET LOCAL statement_timeout='30s'"))
        before = snapshot(db)
        fingerprint = digest(before)
        if mode == 'inspect':
            db.rollback()
            return {'fingerprint': fingerprint,
                    'linked_rows': {k: len(v) for k,v in before.items()},
                    'items': [{k:r[k] for k in ('id','size','planned_quantity')} for r in before['production_order_items']]}
        assert fingerprint == expected, 'Order changed since inspection'
        assert backup and backup['bytes'] > 0 and backup['restore_objects'] > 100
        assert backup['mode'] == '0o600' and len(backup['sha256']) == 64
        target = copy.deepcopy(before)
        changes = []
        for table, ids in [('production_order_items',range(2143,2149)),('bundles',range(11489,11495))]:
            rows = target[table]
            assert [r['id'] for r in rows] == list(ids)
            assert [r['size'] for r in rows] == ['46','48','50','52','54','56']
            for row in rows:
                assert row['model_id'] == 8510
                assert row['planned_quantity' if table == 'production_order_items' else 'quantity'] == 100
                old = row['size']
                row['size'] = str(int(old)-2)
                changes.append({'table':table,'id':row['id'],'old':old,'new':row['size']})
        passports = target['cutting_passports']
        assert len(passports)==1 and passports[0]['id']==352 and passports[0]['size_range']=='46-56'
        passports[0]['size_range']='44-54'
        changes.append({'table':'cutting_passports','id':352,'old':'46-56','new':'44-54'})
        # QR identity is based on stable bundle identifiers; preserve printed codes.
        qr_before = {b.id:bundle_qr_payload(db,b) for b in db.query(Bundle).filter(Bundle.production_order_id==367)}
        for change in changes:
            column = 'size_range' if change['table']=='cutting_passports' else 'size'
            updated = db.execute(text('UPDATE '+change['table']+' SET '+column+'=:new WHERE id=:id AND '+column+'=:old'),change)
            assert updated.rowcount==1
        after = snapshot(db)
        assert after == target, 'Unexpected business-row change'
        db.expire_all()
        for bundle in db.query(Bundle).filter(Bundle.production_order_id==367):
            assert find_bundle_by_scanned_code(db,bundle.barcode).id == bundle.id
            assert bundle_qr_payload(db,bundle) == qr_before[bundle.id]
        audit = log_action(db,None,'correct_po0328_sizes','ProductionOrder',367,
                           old_value={'fingerprint':fingerprint,'changes':changes},
                           new_value={'fingerprint':digest(after),'size_range':'44-54',
                                      'quantity':600,'backup':backup,
                                      'reason':'Owner confirmed PJ1225 in PO-0328 is sizes 44-54, not 46-56'})
        if mode=='rehearse':
            db.rollback()
            assert digest(snapshot(db))==fingerprint
            db.rollback()
            return {'rollback_verified':True,'fingerprint':fingerprint,'changes':changes}
        db.commit()
        audit_id=audit.id
        assert snapshot(db)==target
        saved=db.get(AuditLog,audit_id)
        assert saved.entry_hash == _audit_entry_hash(
            prev_hash=saved.prev_hash,user_id=saved.user_id,action=saved.action,
            entity_type=saved.entity_type,entity_id=saved.entity_id,
            old_value=saved.old_value_json,new_value=saved.new_value_json)
        db.rollback()
        return {'applied':True,'audit_id':audit_id,'after_fingerprint':digest(target),'changes':changes}
