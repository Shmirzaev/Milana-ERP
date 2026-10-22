"""Owner-authorized PO-0518 rollback with locked snapshots and rehearsal.

Run inside the backend interpreter, never by replacing serving files. For
rehearse/apply, the launcher supplies EXPECTED_FINGERPRINT and verified BACKUP.
The complete before-image is preserved in the correction's atomic audit row.
"""
import hashlib
import json
import os
from datetime import datetime, timezone
from sqlalchemy import text
from app.db.session import SessionLocal
from app.services.audit import log_action, _finalize_postgres_audits

MODE = os.environ.get('CORRECTION_MODE', 'inspect')
assert MODE in ('inspect', 'rehearse', 'apply', 'verify')
EXPECTED_FINGERPRINT = globals().get('EXPECTED_FINGERPRINT')
BACKUP = globals().get('BACKUP')
SEEDS = {'production_orders':[558], 'production_batches':[670,671],
         'work_orders':[2193,2194,2195,2196], 'sewing_records':[129],
         'payroll_qr_labels':list(range(109182,109398)), 'notifications':[3579],
         'cutting_records':[633], 'bundles':list(range(20022,20028)), 'packages':[]}

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def sql(db, statement, **params):
    return db.execute(text(statement), params)


def take_snapshot(db, lock=False):
    refs = sql(db, """SELECT tc.table_name,kcu.column_name,ccu.table_name AS target
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu ON tc.constraint_name=kcu.constraint_name
            AND tc.constraint_schema=kcu.constraint_schema
        JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name=tc.constraint_name
            AND ccu.constraint_schema=tc.constraint_schema
        WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_schema='public'""").mappings()
    clauses = {t: ['id = ANY(:seed_' + t + ')'] for t in SEEDS}
    params = {'seed_' + t: ids for t, ids in SEEDS.items()}
    for r in refs:
        if r['target'] in SEEDS and r['table_name'] != 'audit_logs':
            clauses.setdefault(r['table_name'], []).append(
                '"' + r['column_name'] + '" = ANY(:seed_' + r['target'] + ')')
    result = {}
    for table in sorted(clauses):
        statement = 'SELECT * FROM "' + table + '" WHERE ' + ' OR '.join(clauses[table]) + ' ORDER BY id'
        if lock:
            statement += ' FOR UPDATE'
        result[table] = [dict(r) for r in sql(db, statement, **params).mappings()]
    return result


def row(snapshot, table, id):
    return next(r for r in snapshot[table] if r['id'] == id)


def preconditions(snapshot):
    po = row(snapshot, 'production_orders', 558)
    assert po['production_no'] == 'PO-0518' and po['status'] == 'packaging'
    # Payroll already deleted record 129 while the original rollback was being
    # prepared (audit 109274); Cutting subsequently saved genuine record 633.
    assert not snapshot['sewing_records']
    cut = row(snapshot, 'work_orders', 2193)
    sew = row(snapshot, 'work_orders', 2194)
    pkg = row(snapshot, 'work_orders', 2195)
    assert cut['status'] == 'completed' and cut['end_time']
    assert cut['passed_qty'] == cut['actual_output_qty'] == cut['actual_input_qty'] == 600
    assert [(r['id'], r['production_batch_id'], r['passed_pieces'])
            for r in snapshot['cutting_records']] == [(633, 670, 600)]
    assert len(snapshot['bundles']) == 6 and sum(r['quantity'] for r in snapshot['bundles']) == 600
    assert all(r['status'] == 'created' and r['cutting_record_id'] == 633 for r in snapshot['bundles'])
    assert sew['status'] == 'in_progress'
    assert sew['actual_input_qty'] == sew['actual_output_qty'] == sew['passed_qty'] == 0
    assert pkg['status'] == 'in_progress'
    assert pkg['actual_input_qty'] == pkg['actual_output_qty'] == pkg['passed_qty'] == 0
    for table in ('packaging_records', 'packaging_receipts',
                  'packages', 'finished_goods_stock', 'payroll_records', 'sewing_assignments',
                  'sewing_replacement_requests', 'sewing_daily_reports'):
        assert not snapshot.get(table), table
    labels = snapshot['payroll_qr_labels']
    assert len(labels) == 216
    assert all(r['status'] == 'available' and not r['payroll_record_id'] and not r['last_scanned_at']
               and r['return_count'] == 0 and not r['production_batch_id'] for r in labels)
    assert len(snapshot['notifications']) == 1
    notice = snapshot['notifications'][0]
    assert notice['id'] == 3579 and not notice['is_read']
    assert notice['link'] == '/work-orders/2195/packaging'
    assert notice['message'] == 'Order PO-0518 has 600 pcs ready for packaging.'


def verify(snapshot):
    assert row(snapshot, 'production_orders', 558)['status'] == 'sewing'
    cut = row(snapshot, 'work_orders', 2193)
    assert cut['status'] == 'completed' and cut['passed_qty'] == 600
    sew = row(snapshot, 'work_orders', 2194)
    assert sew['status'] == 'in_progress' and sew['passed_qty'] == 0 and not sew['end_time']
    for id in (2195, 2196):
        wo = row(snapshot, 'work_orders', id)
        assert wo['status'] == 'waiting' and not wo['start_time'] and not wo['end_time']
        assert wo['actual_input_qty'] == wo['actual_output_qty'] == wo['passed_qty'] == 0
    assert not snapshot['sewing_records'] and not snapshot['notifications']
    assert len(snapshot['payroll_qr_labels']) == 216
    assert all(r['status'] == 'superseded' and r['superseded_at'] for r in snapshot['payroll_qr_labels'])


with SessionLocal() as db:
    sql(db, "SET LOCAL lock_timeout='5s'")
    sql(db, "SET LOCAL statement_timeout='30s'")
    if MODE in ('inspect', 'verify'):
        sql(db, 'SET TRANSACTION READ ONLY')
    else:
        sql(db, 'SELECT id FROM production_orders WHERE id=558 FOR UPDATE')
        sql(db, 'SELECT id FROM work_orders WHERE production_order_id=558 ORDER BY id FOR UPDATE')
    before = take_snapshot(db, lock=MODE in ('rehearse', 'apply'))
    if MODE == 'inspect':
        preconditions(before)
        print(json.dumps({'fingerprint': digest(before), 'snapshot': before}, default=str))
    elif MODE == 'verify':
        verify(before)
        print(json.dumps({'verified': True, 'fingerprint': digest(before), 'stage': 'sewing',
                          'sewing_output': 0, 'retired_unscanned_labels': 216}, default=str))
    else:
        preconditions(before)
        assert digest(before) == EXPECTED_FINGERPRINT, 'Order changed since inspection'
        assert BACKUP['bytes'] > 0 and BACKUP['restore_objects'] > 100 and BACKUP['mode'] == '0o600'
        now = datetime.now(timezone.utc)
        def update(query, count):
            assert sql(db, query, now=now).rowcount == count, query
        update("UPDATE work_orders SET status='waiting',start_time=NULL,updated_at=:now WHERE id=2195", 1)
        update("UPDATE production_orders SET status='sewing',updated_at=:now WHERE id=558", 1)
        update("""UPDATE payroll_qr_labels SET status='superseded',superseded_at=:now,updated_at=:now
            WHERE production_order_id=558 AND status='available'""", 216)
        update('DELETE FROM notifications WHERE id=3579 AND is_read=false', 1)
        after = take_snapshot(db)
        verify(after)
        allowed = {
            'production_orders': {558: {'status', 'updated_at'}},
            'work_orders': {2195: {'status', 'start_time', 'updated_at'}},
            'payroll_qr_labels': {r['id']: {'status', 'superseded_at', 'updated_at'} for r in before['payroll_qr_labels']},
        }
        deleted = {'notifications': {3579}}
        changes = []
        for table, old_rows in before.items():
            old = {r['id']: r for r in old_rows}
            new = {r['id']: r for r in after[table]}
            assert not (set(new) - set(old)), table
            assert set(old) - set(new) == deleted.get(table, set()), table
            for id in new:
                fields = {k for k in old[id] if old[id][k] != new[id][k]}
                assert fields <= allowed.get(table, {}).get(id, set()), (table, id, fields)
                if fields:
                    changes.append({'table': table, 'id': id, 'fields': sorted(fields)})
        audit = log_action(db, None, 'owner_reverse_po0518_premature_sewing', 'ProductionOrder', 558,
            old_value={'snapshot': before}, new_value={'snapshot': after, 'backup': BACKUP,
                'requested_by': 'owner via Codex chat',
                'prior_sewing_deletion_audit': 109274, 'preserved_new_cutting_record': 633,
                'reason': 'Finish rollback after Payroll deleted wrong Sewing record 129 and Cutting saved real 600-piece record 633. Restore Sewing stage, retire 216 unused process labels and remove false unread Packaging notice; preserve genuine Cutting, material usage, plans, passports, nastils and unrelated data.'})
        _finalize_postgres_audits(db)
        assert audit.id and audit.entry_hash
        result = {'mode': MODE, 'before': digest(before), 'after': digest(after), 'changed_rows': len(changes),
                  'audit_id': audit.id, 'sewing_record_already_deleted': 129, 'retired_labels': 216}
        if MODE == 'apply':
            db.commit()
            assert digest(take_snapshot(db)) == digest(after)
            result['committed_and_verified'] = True
        else:
            db.rollback()
            assert digest(take_snapshot(db)) == digest(before)
            result['rollback_verified'] = True
        print(json.dumps(result, default=str))

