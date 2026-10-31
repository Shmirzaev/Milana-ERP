"""Owner-authorized one-order correction; inspect, rollback rehearsal, then apply."""
import hashlib
import json
import sys

from sqlalchemy import text

from app.db.session import SessionLocal
from app.models.audit_service import log_action


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def rows(db, table, predicate, params=None):
    return [dict(row) for row in db.execute(
        text(f'SELECT * FROM "{table}" WHERE {predicate} ORDER BY id'), params or {}
    ).mappings()]


def snapshot(db):
    state = {
        'production_orders': rows(db, 'production_orders', 'id=285'),
        'work_orders': rows(db, 'work_orders', 'production_order_id=285'),
        'cutting_records': rows(db, 'cutting_records', 'work_order_id=1116'),
        'sewing_assignments': rows(db, 'sewing_assignments', 'work_order_id=1117'),
    }
    columns = db.execute(text("""
        SELECT table_name,column_name FROM information_schema.columns
        WHERE table_schema='public' AND column_name IN
        ('production_order_id','work_order_id','sewing_assignment_id','cutting_record_id','bundle_id')
        ORDER BY table_name,column_name
    """)).all()
    predicates = {}
    for table, column in columns:
        assert table.replace('_', '').isalnum()
        if table in state:
            continue
        value = {
            'production_order_id': '=285', 'work_order_id': ' IN (1116,1117,1118,1119)',
            'sewing_assignment_id': ' IN (161,163)', 'cutting_record_id': '=299',
            'bundle_id': ' IN (7550,7552,7554,7556,7558)',
        }[column]
        predicates.setdefault(table, []).append(f'"{column}"{value}')
    protected = {table: rows(db, table, ' OR '.join(parts)) for table, parts in predicates.items()}
    return state, protected


def validate(state, protected):
    po, = state['production_orders']
    assert po['production_no'] == 'PO-0260' and po['planned_quantity'] == 300
    assert po['status'] == 'sewing'
    work = state['work_orders']
    assert [r['id'] for r in work] == [1116,1117,1118,1119]
    assert [r['operation'] for r in work] == ['cutting','sewing','packaging','storage_transfer']
    assert work[0]['planned_input_qty'] == work[0]['planned_output_qty'] == 300
    assert work[1]['actual_input_qty'] == 250
    assert all(r['actual_output_qty'] == r['passed_qty'] == r['failed_qty'] == r['rework_qty'] == 0 for r in work[1:])
    cut, = state['cutting_records']
    assert cut['id'] == 299 and cut['approval_status'] == 'approved'
    assert cut['bundle_count'] == 5 and cut['total_bundled_quantity'] == 250
    assert cut['defective_pieces'] == 0
    bundles = protected['bundles']
    assert [r['id'] for r in bundles] == [7550,7552,7554,7556,7558]
    assert all(r['quantity'] == 50 and r['status'] == 'received_sewing' for r in bundles)
    assignments = state['sewing_assignments']
    assert [r['id'] for r in assignments] == [161,163]
    assert [r['status'] for r in assignments] == ['cancelled','planned']
    assert all(r['completed_qty'] == 0 for r in assignments)
    for table in ('sewing_records','printing_records','packaging_records','packaging_receipts',
                  'packages','finished_goods_stock','sewing_daily_reports','sewing_replacement_requests'):
        assert not protected.get(table), f'Unexpected downstream evidence: {table}'


def operation(mode, expected=None, backup=None):
    assert mode in {'inspect','rehearse','apply'}
    with SessionLocal() as db:
        db.execute(text("SET LOCAL lock_timeout='5s'"))
        if mode == 'inspect':
            db.execute(text('SET TRANSACTION READ ONLY'))
        else:
            for table, predicate in (
                ('production_orders','id=285'), ('work_orders','production_order_id=285'),
                ('cutting_records','work_order_id=1116'), ('sewing_assignments','work_order_id=1117'),
                ('bundles','production_order_id=285'),
            ):
                db.execute(text(f'SELECT id FROM {table} WHERE {predicate} ORDER BY id FOR UPDATE')).all()
        before, protected = snapshot(db)
        validate(before, protected)
        fingerprint = digest([before, protected])
        if mode == 'inspect':
            return {'fingerprint': fingerprint, 'state': before,
                    'protected_hash': digest(protected),
                    'linked_counts': {k: len(v) for k,v in protected.items()}}
        assert expected == fingerprint, 'Order changed since inspection'
        if mode == 'apply':
            assert backup and backup['bytes'] > 0 and backup['restore_objects'] > 100
            assert backup['mode'] == '0o600' and len(backup['sha256']) == 64
        changes = []
        targets = {
            ('cutting_records',299): ('cut_pieces','passed_pieces'),
            ('work_orders',1116): ('actual_input_qty','actual_output_qty','passed_qty'),
            ('work_orders',1117): ('planned_input_qty','planned_output_qty'),
            ('work_orders',1118): ('planned_input_qty','planned_output_qty'),
            ('work_orders',1119): ('planned_input_qty','planned_output_qty'),
            ('sewing_assignments',161): ('quantity',),
            ('sewing_assignments',163): ('quantity',),
        }
        for (table, identifier), fields in targets.items():
            old = next(r for r in before[table] if r['id'] == identifier)
            assert all(old[f] == 500 for f in fields), 'Unexpected old quantity'
            assignments = ','.join(f'"{f}"=250' for f in fields)
            result = db.execute(text(f'UPDATE "{table}" SET {assignments},updated_at=now() WHERE id=:id'), {'id':identifier})
            assert result.rowcount == 1
            changes.append({'table':table,'id':identifier,'before':{f:old[f] for f in fields},'after':{f:250 for f in fields}})
        after, protected_after = snapshot(db)
        validate(after, protected_after)
        assert protected == protected_after, 'Linked evidence changed'
        for table in before:
            for old,new in zip(before[table], after[table], strict=True):
                allowed = set(targets.get((table, old['id']), ()))
                if allowed:
                    allowed.add('updated_at')
                assert {k for k in old if old[k] != new[k]} <= allowed
        # Use the live resolver to verify the displayed Actual quantity.
        from app.api.routes.production import _production_order_actuals
        actuals = _production_order_actuals(db,285)
        assert actuals['actual_quantity'] == actuals['actual_cut_quantity'] == actuals['actual_bundle_quantity'] == 250
        result = {'mode':mode,'changes':changes,'actuals':actuals,
                  'protected_hash':digest(protected),'linked_counts':{k:len(v) for k,v in protected.items()}}
        if mode == 'apply':
            entry = log_action(db, None, 'correct_po0260_quantity', 'ProductionOrder', 285,
                       old_value={'fingerprint':fingerprint,'changes':changes},
                       new_value={'quantity':250,'backup':backup,'protected_hash':digest(protected),
                                  'reason':'Owner confirmed 250 actual pieces; erroneous 500 Cutting and downstream quantities corrected. Original 300 plan retained.'})
            db.commit()
            audit = entry.id
            assert audit is not None
            saved, saved_protected = snapshot(db)
            assert saved == after and saved_protected == protected
            result['audit_id'] = audit
            result['persisted_readback'] = True
        else:
            db.rollback()
            rolled_back, rollback_protected = snapshot(db)
            assert digest([rolled_back,rollback_protected]) == fingerprint
            result['rollback_verified'] = True
        return result


if __name__ == '__main__':
    print(json.dumps(operation(sys.argv[1], sys.argv[2] if len(sys.argv)>2 else None,
                               json.loads(sys.argv[3]) if len(sys.argv)>3 else None), default=str))
