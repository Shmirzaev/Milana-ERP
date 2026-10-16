"""Owner-authorized PO-0413 restart. Defaults to read-only plan; never deploys.

Run through the verified active application runtime. Rehearse first, then use
--commit only after the full PostgreSQL backup and unchanged snapshot checks.
"""
import argparse
import hashlib
import json

from sqlalchemy import text

from app.db.session import SessionLocal
from app.services.audit import log_action
from app.api.routes.production import _production_order_actuals

EXPECTED_SHA256 = '432cb40de86e0801d36aa51685e9f984e2cf29a03b7107d3ee088846c16b0bde'
EXPECTED_COUNTS = {
    'production_orders': 1, 'work_orders': 4, 'production_batches': 2,
    'cutting_records': 1, 'bundles': 5, 'bundle_scan_logs': 5,
    'production_order_items': 5, 'production_order_materials': 1,
}
BACKUP = '/opt/milana-erp/shared/backups/pre_reset_po0413_cutting_20261016_111721.dump'


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def snapshot(db):
    columns = {r[0]: r[1] for r in db.execute(text(
        "select table_name,array_agg(column_name::text) from information_schema.columns "
        "where table_schema='public' group by table_name"
    ))}
    quote = db.bind.dialect.identifier_preparer.quote
    result = {'production_orders': [dict(r) for r in db.execute(text(
        'select * from production_orders where id=452'
    )).mappings()]}
    ids = {
        'production_order_id': [452], 'work_order_id': [1770,1771,1772,1773],
        'source_work_order_id': [1770,1771,1772,1773],
        'cutting_work_order_id': [1770], 'sewing_work_order_id': [1771],
        'production_batch_id': [373,374], 'cutting_record_id': [493],
        'bundle_id': [19236,19237,19238,19239,19240],
    }
    for table, cols in sorted(columns.items()):
        clauses = [f'{quote(c)} IN ({",".join(map(str,v))})'
                   for c,v in ids.items() if c in cols]
        if not clauses:
            continue
        rows = [dict(r) for r in db.execute(text(
            f'SELECT * FROM {quote(table)} WHERE ' + ' OR '.join(clauses)
            + (' ORDER BY id' if 'id' in cols else '')
        )).mappings()]
        if rows:
            result[table] = rows
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--rehearse', action='store_true')
    mode.add_argument('--commit', action='store_true')
    args = parser.parse_args()
    with SessionLocal() as db:
        if not (args.rehearse or args.commit):
            db.execute(text('SET TRANSACTION READ ONLY'))
        db.execute(text("SET LOCAL lock_timeout = '5s'"))
        db.execute(text("SET LOCAL statement_timeout = '20s'"))
        assert db.execute(text('select version_num from alembic_version')).scalar_one() == '0146_payroll_qr_closure'
        if args.rehearse or args.commit:
            # Parent row locks also block new FK-linked downstream evidence.
            for table, where in [
                ('production_orders','id=452'),
                ('work_orders','production_order_id=452'),
                ('production_batches','production_order_id=452'),
                ('cutting_records','work_order_id=1770'),
                ('bundles','production_order_id=452'),
                ('bundle_scan_logs','bundle_id between 19236 and 19240'),
                ('production_order_items','production_order_id=452'),
                ('production_order_materials','production_order_id=452'),
                ('notifications','id between 2840 and 2843'),
            ]:
                db.execute(text(f'SELECT id FROM {table} WHERE {where} ORDER BY id FOR UPDATE')).all()
        before = snapshot(db)
        assert {k:len(v) for k,v in before.items()} == EXPECTED_COUNTS, 'Dependencies changed'
        assert fingerprint(before) == EXPECTED_SHA256, 'Reviewed snapshot changed; stop and re-inspect'
        assert before['production_orders'][0]['production_no'] == 'PO-0413'
        assert all(r['status']=='created' and r['quantity']==50 for r in before['bundles'])
        assert all(r['scan_type']=='created' for r in before['bundle_scan_logs'])
        assert not db.execute(text('select id from stock_movements where reference_id in (493,452,373,374)')).first()
        notifications = [dict(r) for r in db.execute(text(
            "select * from notifications where message like '%PO-0413%' order by id"
        )).mappings()]
        assert [r['id'] for r in notifications] == [2840,2841,2842,2843]
        assert all(not r['is_read'] and r['message']=='5 bundle(s) ready from order PO-0413.' for r in notifications)
        stock = [dict(r) for r in db.execute(text('select * from stock_batches where id=1468')).mappings()]
        if not (args.rehearse or args.commit):
            print(json.dumps({'mode':'plan','counts':EXPECTED_COUNTS,'fingerprint':fingerprint(before),
                              'remove':'one Cutting record, five unused bundles/creation scans, two Nastil batches, four unread incoming notifications',
                              'preserve':'600-piece order plan, size breakdown, material selection, history, stock'},default=str))
            db.rollback()
            return
        for sql, count in [
            ('DELETE FROM bundle_scan_logs WHERE id between 30182 and 30186 AND bundle_id between 19236 and 19240',5),
            ('DELETE FROM bundles WHERE id between 19236 and 19240 AND production_order_id=452',5),
            ('DELETE FROM cutting_records WHERE id=493 AND work_order_id=1770',1),
            ('DELETE FROM production_batches WHERE id in (373,374) AND production_order_id=452',2),
            ("DELETE FROM notifications WHERE id between 2840 and 2843 AND NOT is_read AND message='5 bundle(s) ready from order PO-0413.'",4),
            ("UPDATE work_orders SET status=CASE WHEN operation='cutting' THEN 'in_progress' ELSE 'waiting' END, actual_input_qty=0,actual_output_qty=0,passed_qty=0,failed_qty=0,rework_qty=0,start_time=NULL,end_time=NULL,updated_at=now() WHERE production_order_id=452 AND id between 1770 and 1773",4),
            ("UPDATE production_orders SET status='cutting',updated_at=now() WHERE id=452 AND production_no='PO-0413'",1),
        ]:
            assert db.execute(text(sql)).rowcount == count
        after = snapshot(db)
        assert set(after)=={'production_orders','work_orders','production_order_items','production_order_materials'}
        for table in ['production_order_items','production_order_materials']:
            assert after[table] == before[table]
        allowed = {'production_orders':{'status','updated_at'},
                   'work_orders':{'status','actual_input_qty','actual_output_qty','passed_qty','failed_qty','rework_qty','start_time','end_time','updated_at'}}
        for table, fields in allowed.items():
            for old,new in zip(before[table],after[table],strict=True):
                assert {k:v for k,v in old.items() if k not in fields} == {k:v for k,v in new.items() if k not in fields}
        assert stock == [dict(r) for r in db.execute(text('select * from stock_batches where id=1468')).mappings()]
        actuals = _production_order_actuals(db,452)
        assert all(v==0 for v in actuals.values())
        for row in after['work_orders']:
            assert all(row[k]==0 for k in ['actual_input_qty','actual_output_qty','passed_qty','failed_qty','rework_qty'])
            assert row['status']==('in_progress' if row['operation']=='cutting' else 'waiting')
        details={'reason':'Owner requested P-0413 returned as newly arrived to Cutting because entered information is wrong; fresh re-entry authorized.',
                 'active_release':'20261016_101413','backup':BACKUP,
                 'actuals':actuals,'after':after,'retired_bundle_numbers':[r['bundle_no'] for r in before['bundles']],
                 'sequences_preserved':True,'material_stock_unchanged':True}
        if args.commit:
            audit=log_action(db,None,'owner_authorized_cutting_reset','ProductionOrder',452,
                             old_value={'records':before,'notifications':notifications},new_value=details)
            db.commit()
            print(json.dumps({'committed':True,'audit_id':audit.id,'details':details},default=str))
        else:
            db.rollback()
            assert fingerprint(snapshot(db))==EXPECTED_SHA256
            db.rollback()
            print(json.dumps({'committed':False,'rehearsal':'passed and rolled back','details':details},default=str))


if __name__=='__main__':
    main()
