"""One-time owner-confirmed historical BST status reconciliation.

No serving code is replaced. Run via the companion launcher. This deliberately
does not manufacture output/receipt evidence to satisfy normal completion guards.
The owner reports these physical works already sewn and handed over, including
PO-0377 Nastil 3. Keep the discrepancy between that attestation and stored counts.
"""
import hashlib
import json
import time
from datetime import datetime, timezone

from sqlalchemy import text

from app.api.routes import production as api
from app.db.session import SessionLocal
from app.models.audit_service import _finalize_postgres_audits, log_action


TARGETS = [1069, 1499, 1507, 1527, 1579, 1603, 1607, 1611, 1615, 1715, 1839, 1843, 1847, 2673]
MILANA_WORK_ORDER = 1627
REASON = (
    "Owner requested removal of all old assignable BST sewing work because it "
    "already left the factory; confirmed PO-0377 Nastil 3 was sewn and handed over. "
    "Historical status-only closure. Recorded output, shortfalls, future plans, "
    "bundles, payroll, packaging, inventory and shipment evidence remain unchanged. "
    "Do not treat this attestation as a new quantity/receipt or create replacement output."
)
ACTION = "owner_close_historical_bst_sewing_20261104"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def query(db, statement, **params):
    return db.execute(text(statement), params)


def rows(db, statement, **params):
    return [dict(r) for r in query(db, statement, **params).mappings()]


def snapshot(db):
    """Preserve all order rows and direct child evidence for the seeded parents."""
    seeds = {'production_orders': [r['production_order_id'] for r in rows(
        db, 'SELECT production_order_id FROM work_orders WHERE id=ANY(:ids)', ids=TARGETS)]}
    seeds['production_orders'] = sorted(set(seeds['production_orders']))
    for table in ('work_orders', 'production_batches', 'bundles', 'packages'):
        seeds[table] = [r['id'] for r in rows(db,
            f'SELECT id FROM "{table}" WHERE production_order_id=ANY(:ids) ORDER BY id',
            ids=seeds['production_orders'])]
    refs = rows(db, """SELECT tc.table_name,kcu.column_name,ccu.table_name AS target
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu ON tc.constraint_name=kcu.constraint_name
            AND tc.constraint_schema=kcu.constraint_schema
        JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name=tc.constraint_name
            AND ccu.constraint_schema=tc.constraint_schema
        WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_schema='public'""")
    clauses = {table: ['id=ANY(:seed_' + table + ')'] for table in seeds}
    params = {'seed_' + table: ids for table, ids in seeds.items()}
    for ref in refs:
        if ref['target'] in seeds and ref['table_name'] != 'audit_logs':
            assert ref['table_name'].replace('_', '').isalnum()
            assert ref['column_name'].replace('_', '').isalnum()
            clauses.setdefault(ref['table_name'], []).append(
                '"' + ref['column_name'] + '"=ANY(:seed_' + ref['target'] + ')')
    result = {}
    for table in sorted(clauses):
        result[table] = rows(db, 'SELECT * FROM "' + table + '" WHERE '
                            + ' OR '.join(clauses[table])
                            + ' ORDER BY to_jsonb("' + table + '")::text', **params)
    return result


def queue(db, factory):
    po_ids = db.query(api.Bundle.production_order_id).filter(
        api.Bundle.status == 'received_sewing', api.Bundle.sewing_factory_code == factory).distinct()
    work = db.query(api.WorkOrder).filter(
        api.WorkOrder.operation == 'sewing', api.WorkOrder.status.in_(api._ACTIVE_WO_STATUSES),
        api.WorkOrder.production_order_id.in_(po_ids),
        ~api.WorkOrder.production_order.has(api.ProductionOrder.source_type == 'usluga')).order_by(
            api.WorkOrder.id.desc()).all()
    payload = api._received_sewing_work_order_payloads(db, work, {})
    return [{key: item.get(key) for key in ('id', 'production_order_id', 'production_batch_id',
             'batch_no', 'assignable_qty', 'assigned_qty')} for item in payload]


def validate_before(db, before):
    work = {r['id']: r for r in before['work_orders']}
    departments = dict(query(db, 'SELECT id,code FROM departments').all())
    assert all(work[wid]['status'] == 'in_progress' and work[wid]['operation'] == 'sewing'
               and departments[work[wid]['department_id']] == 'BST'
               and work[wid]['sewing_flow_id'] is None for wid in TARGETS)
    assert not [a for a in before['sewing_assignments'] if a['work_order_id'] in TARGETS]
    # A shared BST work order must not own live physical work in another factory.
    for wid in TARGETS:
        w = db.get(api.WorkOrder, wid)
        from app.models.production.batch_scope_service import batch_owned_by_work_order
        owned = [b for b in before['bundles'] if b['production_order_id'] == w.production_order_id
                 and b['status'] != 'cancelled'
                 and (b['production_batch_id'] is None or batch_owned_by_work_order(db, w, b['production_batch_id']))]
        assert owned and all(b['sewing_factory_code'] == 'BST' for b in owned), wid
    assert work[MILANA_WORK_ORDER]['status'] == 'in_progress'
    assert departments[work[MILANA_WORK_ORDER]['department_id']] == 'MIL'
    q = queue(db, 'BST')
    true_bst = [r for r in q if r['id'] in TARGETS]
    assert len(true_bst) == 21 and sum(r['assignable_qty'] for r in true_bst) == 8277
    assert {r['id'] for r in true_bst} == set(TARGETS)
    assert [r for r in q if r['id'] not in TARGETS] == [{
        'id': 1627, 'production_order_id': 416, 'production_batch_id': 253,
        'batch_no': '0416-01', 'assignable_qty': 600, 'assigned_qty': 0}]


def assert_only_status_changes(before, after):
    assert before.keys() == after.keys()
    changed = []
    for table, old_rows in before.items():
        if old_rows and 'id' not in old_rows[0]:
            assert old_rows == after[table], table
            continue
        old, new = ({r['id']: r for r in items} for items in (old_rows, after[table]))
        assert old.keys() == new.keys(), table
        for rid, prior in old.items():
            fields = {key for key in prior if prior[key] != new[rid][key]}
            allowed = {'status', 'end_time', 'updated_at'} if table == 'work_orders' and rid in TARGETS else set()
            assert fields <= allowed, (table, rid, fields)
            if fields:
                assert new[rid]['status'] == 'completed' and new[rid]['end_time']
                changed.append(rid)
    assert sorted(changed) == TARGETS


def operation(mode, expected=None, backup=None):
    assert mode in ('inspect', 'rehearse', 'apply', 'verify')
    with SessionLocal() as db:
        query(db, "SET LOCAL lock_timeout='2s'")
        query(db, "SET LOCAL statement_timeout='30s'")
        assert query(db, 'SELECT version_num FROM alembic_version').scalar() == '0150_package_customer_release'
        if mode in ('inspect', 'verify'):
            db.rollback()
            query(db, 'SET TRANSACTION READ ONLY')
            query(db, "SET LOCAL statement_timeout='30s'")
        else:
            assert backup and backup['bytes'] > 0 and backup['restore_objects'] > 100
            assert backup['mode'] == '0o600'
            # Fail quickly if this narrow correction would contend with active work.
            lock_started = time.monotonic()
            query(db, """LOCK TABLE production_orders,work_orders,bundles,production_batches,
                sewing_assignments,sewing_records,cutting_records,printing_records,
                packaging_receipts,packaging_records,packages,payroll_qr_labels,payroll_records,
                sewing_daily_reports IN SHARE ROW EXCLUSIVE MODE NOWAIT""")
            query(db, 'SELECT id FROM work_orders WHERE id=ANY(:ids) ORDER BY id FOR UPDATE', ids=TARGETS)
        before = snapshot(db)
        if mode == 'inspect':
            validate_before(db, before)
            result = {'fingerprint': digest(before), 'snapshot': before,
                      'queues': {f: queue(db, f) for f in ('BST', 'MIL', 'ECO')},
                      'target_work_orders': TARGETS, 'target_batches': 21, 'target_received_pieces': 8277}
            db.rollback()
            return result
        if mode == 'verify':
            assert digest(before) == expected['after'], 'Persisted state changed since correction'
            for wid in TARGETS:
                assert next(r for r in before['work_orders'] if r['id'] == wid)['status'] == 'completed'
            assert queue(db, 'BST') == expected['remaining_bst_queue']
            audits = rows(db, 'SELECT id,action,entity_type,entity_id,prev_hash,entry_hash FROM audit_logs WHERE id=ANY(:ids) ORDER BY id',
                          ids=expected['audit_ids'])
            assert len(audits) == len(TARGETS) and all(a['action'] == ACTION for a in audits)
            assert [a['entity_id'] for a in audits] == TARGETS
            db.rollback()
            return {'persisted_verified': True, 'fingerprint': digest(before), 'audits': audits,
                    'remaining_bst_queue': expected['remaining_bst_queue']}
        validate_before(db, before)
        assert digest(before) == expected['fingerprint'], 'Snapshot changed; stop and re-inspect'
        previous_queues = {f: queue(db, f) for f in ('BST', 'MIL', 'ECO')}
        assert previous_queues == expected['queues']
        assert not query(db, 'SELECT id FROM audit_logs WHERE action=:action LIMIT 1', action=ACTION).first(), 'Already applied'
        now = datetime.now(timezone.utc)
        assert query(db, """UPDATE work_orders SET status='completed',end_time=:now,updated_at=:now
            WHERE id=ANY(:ids) AND status='in_progress' AND operation='sewing'""", ids=TARGETS, now=now).rowcount == len(TARGETS)
        db.expire_all()
        after = snapshot(db)
        assert_only_status_changes(before, after)
        current_queues = {f: queue(db, f) for f in ('BST', 'MIL', 'ECO')}
        for f in current_queues:
            assert current_queues[f] == [r for r in previous_queues[f] if r['id'] not in TARGETS], f
        old_work = {w['id']: w for w in before['work_orders']}
        new_work = {w['id']: w for w in after['work_orders']}
        audits = [log_action(db, None, ACTION, 'WorkOrder', wid,
            old_value={'work_order': old_work[wid]},
            new_value={'work_order': new_work[wid], 'requested_by': 'owner via Codex chat',
                       'reason': REASON, 'backup': backup, 'before_sha256': digest(before)}) for wid in TARGETS]
        _finalize_postgres_audits(db)
        assert all(a.id and a.entry_hash for a in audits)
        result = {'mode': mode, 'before': digest(before), 'after': digest(after),
                  'changed_work_orders': TARGETS, 'audit_ids': [a.id for a in audits],
                  'preserved_tables': {t: len(v) for t, v in before.items()},
                  'cleared_bst_batches': 21, 'cleared_bst_received_pieces': 8277,
                  'remaining_bst_queue': current_queues['BST']}
        if mode == 'apply':
            db.commit()
            result['write_gate_seconds'] = round(time.monotonic() - lock_started, 3)
            assert digest(snapshot(db)) == result['after']
            result['committed_and_verified'] = True
        else:
            db.rollback()
            result['write_gate_seconds'] = round(time.monotonic() - lock_started, 3)
            assert digest(snapshot(db)) == result['before']
            result['rollback_verified'] = True
        return result
