"""Explicit owner-authorized PO-0276 reset; never run at startup or migration.

Return the existing six bundles to the Sewing arrival queue, reverse unused
Sewing/Packaging evidence, and use the approved 67 x six-size order plan.
Cutting history, material balances, passport and bundle identities stay intact.
Plan is read-only. Rehearse rolls back. Apply requires reviewed state and backup.
"""
import argparse
import hashlib
import json
import re

from sqlalchemy import text

from app.core.deps import is_super_admin
from app.db.session import SessionLocal
from app.schemas import ProductionOrder, ProductionOrderItem, User, WorkOrder
from app.models.audit_service import _finalize_postgres_audits, log_action


SIZES = ('48', '50', '52', '54', '56', '58')
DELETIONS = {
    'sewing_records': {42, 93},
    'packaging_receipts': {6, 7},
    'packaging_records': {27, 75},
    'waste_records': {151},
}
EXPECTED_TABLES = {
    'production_orders', 'production_order_items', 'production_batches',
    'production_order_materials', 'work_orders', 'cutting_records',
    'cutting_passports', 'bundles', 'bundle_scan_logs', *DELETIONS,
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def scoped_tables(db):
    columns = dict(db.execute(text(
        "SELECT table_name,array_agg(column_name::text) FROM information_schema.columns "
        "WHERE table_schema='public' GROUP BY table_name"
    )).all())
    scopes = {}
    for table, cols in sorted(columns.items()):
        clauses = []
        for column, ids in (
            ('production_order_id', '301'), ('production_batch_id', '168'),
            ('work_order_id', '1180,1181,1182,1183'),
            ('source_work_order_id', '1180,1181,1182,1183'),
            ('sewing_work_order_id', '1181'), ('sewing_record_id', '42,93'),
            ('cutting_record_id', '281,282,283,285'),
            ('cutting_passport_id', '312'), ('bundle_id', '7465,7466,7467,7468,7469,7470'),
            ('waste_record_id', '151'),
        ):
            if column in cols:
                clauses.append(f'"{column}" IN ({ids})')
        if table == 'production_orders':
            clauses.append('id=301')
        # Include material/ledger references as protected evidence, never audit history.
        if table != 'audit_logs' and 'reference_type' in cols and 'reference_id' in cols:
            clauses.append("(reference_type='ProductionOrder' AND reference_id=301) "
                           "OR (reference_type='SewingRecord' AND reference_id IN (42,93)) "
                           "OR (reference_type='WasteRecord' AND reference_id=151)")
        if clauses:
            scopes[table] = ' OR '.join(f'({clause})' for clause in clauses)
    return scopes


def snapshot(db, scopes):
    return {
        table: [dict(row) for row in db.execute(text(
            f'SELECT * FROM "{table}" WHERE {where} ORDER BY id'
        )).mappings()]
        for table, where in scopes.items()
    }


def validate(before):
    populated = {table for table, rows in before.items() if rows}
    assert populated <= EXPECTED_TABLES, f'Unexpected linked data: {populated - EXPECTED_TABLES}'
    for table, ids in DELETIONS.items():
        assert {row['id'] for row in before[table]} == ids, f'Changed {table}'
    po, = before['production_orders']
    item, = before['production_order_items']
    batch, = before['production_batches']
    assert (po['id'], po['production_no'], po['model_id'], po['planned_quantity'], po['status']) == (
        301, 'PO-0276', 8438, 400, 'packaging')
    assert po['packaging_size_breakdowns'] is None
    assert (item['id'], item['model_id'], item['color'], item['size'],
            item['planned_quantity'], item['completed_quantity'], item['printing_required']) == (
        1746, 8438, 'white', '48', 400, 0, False)
    assert (batch['id'], batch['batch_no'], batch['planned_quantity']) == (168, '0301-01', 402)
    bundles = before['bundles']
    assert {row['id'] for row in bundles} == set(range(7465, 7471))
    assert {row['size']: row['quantity'] for row in bundles} == dict.fromkeys(SIZES, 67)
    assert all(row['status'] == 'created' and row['production_batch_id'] == 168
               and row['sewing_factory_code'] == 'BST' and row['cutting_record_id'] == 285
               and row['current_department_id'] == 4 and row['next_department_id'] == 8
               for row in bundles)
    assert all(row['scan_type'] == 'created' for row in before['bundle_scan_logs'])
    assert {row['id'] for row in before['work_orders']} == {1180, 1181, 1182, 1183}
    sewing = {row['id']: row for row in before['sewing_records']}
    assert (sewing[42]['input_qty'], sewing[42]['passed_qty'], sewing[42]['failed_qty']) == (402, 391, 11)
    assert (sewing[93]['input_qty'], sewing[93]['passed_qty'], sewing[93]['failed_qty']) == (408, 408, 0)
    assert all(row['production_batch_id'] == 168 and row['work_order_id'] == 1181
               and not row['sewing_assignment_id'] and not row['assignment_applied_qty']
               and not row['correction_version'] for row in sewing.values())
    assert {row['id']: row['quantity'] for row in before['packaging_receipts']} == {6: 391, 7: 408}
    assert all(row['production_batch_id'] == 168 and row['work_order_id'] == 1182
               and row['source_work_order_id'] == 1181 for row in before['packaging_receipts'])
    assert all(not any(row[key] for key in ('input_qty', 'packed_qty', 'damaged_qty',
                   'package_count', 'total_packed_quantity')) for row in before['packaging_records'])
    waste, = before['waste_records']
    assert waste['work_order_id'] == 1181 and waste['waste_type'] == 'sewing_defect'
    assert waste['quantity'] == 11 and waste['status'] == 'recorded' and not waste['sellable']


def verify_changes(before, after):
    assert set(before) == set(after)
    for table, old_rows in before.items():
        if table in DELETIONS:
            assert not after[table], table
            continue
        new = {row['id']: row for row in after[table]}
        old_ids = {row['id'] for row in old_rows}
        if table == 'production_order_items':
            assert len(new) == 6 and old_ids <= set(new)
            assert {row['size']: row['planned_quantity'] for row in new.values()} == dict.fromkeys(SIZES, 67)
            assert all(row['model_id'] == 8438 and row['color'] == 'white'
                       and row['production_order_id'] == 301 and not row['completed_quantity']
                       and not row['printing_required'] for row in new.values())
        else:
            assert set(new) == old_ids, table
        for old in old_rows:
            changed = {key for key in old if old[key] != new[old['id']][key]}
            allowed = set()
            if table == 'production_orders':
                allowed = {'status', 'planned_quantity', 'updated_at'}
            elif table == 'production_order_items':
                allowed = {'planned_quantity', 'updated_at'}
            elif table == 'work_orders' and old['id'] in (1181, 1182):
                allowed = {'status', 'actual_input_qty', 'actual_output_qty', 'passed_qty',
                           'failed_qty', 'rework_qty', 'start_time', 'end_time', 'updated_at'}
            assert changed <= allowed, (table, old['id'], changed - allowed)
    po, = after['production_orders']
    assert po['status'] == 'sewing' and po['planned_quantity'] == 402
    for wo in after['work_orders']:
        if wo['id'] in (1181, 1182, 1183):
            assert not any(wo[key] for key in ('actual_input_qty', 'actual_output_qty',
                                              'passed_qty', 'failed_qty', 'rework_qty'))
            assert wo['status'] == ('in_progress' if wo['id'] == 1181 else 'waiting')


def run(mode='plan', expected=None, backup=None, backup_sha256=None):
    with SessionLocal() as db:
        assert db.get_bind().dialect.name == 'postgresql', 'Requires PostgreSQL transaction guards'
        if mode == 'plan':
            db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
        db.execute(text("SET LOCAL lock_timeout='5s'"))
        db.execute(text("SET LOCAL statement_timeout='30s'"))
        scopes = scoped_tables(db)
        if mode != 'plan':
            # Keep concurrent receipt, output, payroll and downstream insertions out
            # of this short correction; acquire a deterministic table lock order.
            tables = ','.join(f'"{table}"' for table in sorted(scopes))
            db.execute(text(f'LOCK TABLE {tables} IN SHARE ROW EXCLUSIVE MODE'))
        before = snapshot(db, scopes)
        validate(before)
        fingerprint = digest(before)
        if mode == 'plan':
            db.rollback()
            return {'fingerprint': fingerprint, 'before': before}
        assert expected == fingerprint, 'State changed after review; inspect again'
        assert backup and re.fullmatch(r'/opt/milana-erp/shared/backups/milana_erp_pre_\d{8}_\d{6}\.dump', backup)
        assert backup_sha256 and re.fullmatch(r'[0-9a-f]{64}', backup_sha256)
        po = db.get(ProductionOrder, 301)
        po.status = 'sewing'
        po.planned_quantity = 402
        db.get(ProductionOrderItem, 1746).planned_quantity = 67
        for size in SIZES[1:]:
            db.add(ProductionOrderItem(production_order_id=301, model_id=8438, color='white',
                                       size=size, planned_quantity=67, completed_quantity=0,
                                       printing_required=False))
        for table in ('packaging_receipts', 'packaging_records', 'waste_records', 'sewing_records'):
            ids = ','.join(str(value) for value in sorted(DELETIONS[table]))
            result = db.execute(text(f'DELETE FROM "{table}" WHERE id IN ({ids})'))
            assert result.rowcount == len(DELETIONS[table])
        for wid in (1181, 1182):
            wo = db.get(WorkOrder, wid)
            for key in ('actual_input_qty', 'actual_output_qty', 'passed_qty', 'failed_qty', 'rework_qty'):
                setattr(wo, key, 0)
            wo.status = 'in_progress' if wid == 1181 else 'waiting'
            wo.end_time = None
            if wid == 1182:
                wo.start_time = None
        db.flush()
        after = snapshot(db, scopes)
        verify_changes(before, after)
        actor = db.get(User, 1)
        assert actor and actor.is_active and is_super_admin(actor)
        entry = log_action(db, actor, 'reset_sewing_arrival', 'ProductionOrder', 301,
                           old_value=before, new_value={
                               'reason': 'Owner requested fresh Sewing arrival and approved 67 each in sizes 48–58 (402 total)',
                               'after': after, 'backup': backup, 'backup_sha256': backup_sha256,
                               'preserved': 'Cutting records, material ledger, passport, bundles and scan history',
                           })
        db.flush()
        _finalize_postgres_audits(db)
        result = {'fingerprint': fingerprint, 'after_fingerprint': digest(after),
                  'after': after, 'audit_id': entry.id, 'mode': mode}
        if mode == 'apply':
            db.commit()
        else:
            db.rollback()
        result['committed'] = mode == 'apply'
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('plan', 'rehearse', 'apply'), default='plan')
    parser.add_argument('--expected')
    parser.add_argument('--backup')
    parser.add_argument('--backup-sha256')
    args = parser.parse_args()
    print(json.dumps(run(args.mode, args.expected, args.backup, args.backup_sha256), default=str))
