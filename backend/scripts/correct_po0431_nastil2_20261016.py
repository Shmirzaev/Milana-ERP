"""Owner-authorized PO-0431 Nastil 2 correction. Dry-run unless explicitly applied.

The operator must verify a fresh PostgreSQL backup on the host before applying.
No bundle creation, stock adjustment, or Nastil 1 change is permitted.
"""
import argparse
import hashlib
import json

from sqlalchemy import text

from app.api.routes.production import (
    _cutting_reconciliation_context,
    _reconcile_cutting_workflow_plans,
    _sync_cutting_work_order_from_records,
)
from app.core.deps import is_super_admin
from app.db.session import SessionLocal
from app.models import CuttingRecord, ProductionBatch, ProductionOrder, User, WorkOrder
from app.services.audit import _finalize_postgres_audits, log_action


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def scoped_tables(db):
    columns = dict(db.execute(text(
        "SELECT table_name,array_agg(column_name::text) FROM information_schema.columns "
        "WHERE table_schema='public' GROUP BY table_name"
    )).all())
    result = {}
    for table, cols in sorted(columns.items()):
        clauses = []
        for column, ids in [
            ('production_order_id', '470'), ('production_batch_id', '350,356'),
            ('work_order_id', '1842,1843,1844,1845'), ('source_work_order_id', '1842,1843,1844,1845'),
            ('cutting_record_id', '464,469'), ('bundle_id', '19076,19077,19078,19079,19080,19081'),
        ]:
            if column in cols:
                clauses.append(f'"{column}" IN ({ids})')
        if table == 'production_orders':
            clauses.append('id=470')
        if 'reference_type' in cols and 'reference_id' in cols:
            clauses.append("reference_type='CuttingRecord' AND reference_id IN (464,469)")
        if clauses:
            result[table] = ' OR '.join(clauses)
    return result


def snapshot(db, scopes):
    result = {}
    for table, where in scopes.items():
        rows = [dict(row) for row in db.execute(text(
            f'SELECT * FROM "{table}" WHERE {where} ORDER BY id'
        )).mappings()]
        if rows:
            result[table] = rows
    return result


def run(mode='plan', expected=None, backup=None, backup_sha256=None):
    with SessionLocal() as db:
        db.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
        db.execute(text("SET LOCAL lock_timeout='5s'"))
        db.execute(text("SET LOCAL statement_timeout='30s'"))
        scopes = scoped_tables(db)
        if mode != 'plan':
            # Block newly inserted dependencies during this short, atomic repair.
            tables = ','.join(f'"{table}"' for table in scopes)
            db.execute(text(f'LOCK TABLE {tables} IN SHARE ROW EXCLUSIVE MODE'))
        po = db.query(ProductionOrder).filter_by(id=470).with_for_update().one()
        work = db.query(WorkOrder).filter_by(production_order_id=470).order_by(WorkOrder.id).with_for_update().all()
        batch = db.query(ProductionBatch).filter_by(id=356).with_for_update().one()
        record = db.query(CuttingRecord).filter_by(id=469).with_for_update().one()
        cutting = next(row for row in work if row.id == 1842)
        before = snapshot(db, scopes)
        assert set(before) == {
            'production_orders', 'production_batches', 'production_order_items',
            'production_order_materials', 'work_orders', 'cutting_records', 'bundles', 'bundle_scan_logs',
        }, 'Unexpected dependency: re-inspect before correcting'
        assert po.production_no == 'PO-0431' and po.planned_quantity == 900 and po.status == 'sewing'
        assert batch.production_order_id == 470 and batch.batch_no == '0470-02' and batch.planned_quantity == 480
        assert record.work_order_id == 1842 and record.production_batch_id == 356
        assert record.cut_pieces == record.passed_pieces == 480 and record.defective_pieces == 0
        assert record.bundle_count == record.total_bundled_quantity == 0
        assert {row['id'] for row in before['cutting_records']} == {464, 469}
        assert {row['id'] for row in before['production_batches']} == {350, 356}
        assert len(before['bundles']) == 6 and all(row['production_batch_id'] == 350 and row['quantity'] == 80 and row['status'] == 'created' for row in before['bundles'])
        assert cutting.status == 'completed' and cutting.actual_input_qty == cutting.actual_output_qty == cutting.passed_qty == 960
        assert cutting.failed_qty == 420 and cutting.rework_qty == 0
        assert {row.id for row in work} == {1842, 1843, 1844, 1845}
        assert all(not any((row.actual_input_qty, row.actual_output_qty, row.passed_qty, row.failed_qty, row.rework_qty)) for row in work if row.id != 1842)
        context = _cutting_reconciliation_context(db, po, work, cutting, extra_scopes={350, 356})
        assert not any(context.downstream_by_scope.values()) and context.bundle_by_scope.get(356, 0) == 0
        fingerprint = digest(before)
        if mode == 'plan':
            db.rollback()
            return {'fingerprint': fingerprint, 'before': before, 'downstream': context.downstream_by_scope}
        assert expected == fingerprint, 'Production state changed since review'
        assert backup and backup.startswith('/opt/milana-erp/shared/backups/') and '..' not in backup
        assert backup_sha256 and len(backup_sha256) == 64
        record.cut_pieces = record.passed_pieces = 420
        batch.planned_quantity = 420
        db.flush()
        _sync_cutting_work_order_from_records(db, cutting)
        _reconcile_cutting_workflow_plans(db, cutting, work_orders=work)
        db.flush()
        after = snapshot(db, scopes)
        changes = {}
        for table, old_rows in before.items():
            new_rows = {row['id']: row for row in after[table]}
            assert set(new_rows) == {row['id'] for row in old_rows}
            for old in old_rows:
                new = new_rows[old['id']]
                changed = {key for key in old if old[key] != new[key]}
                allowed = set()
                if table == 'cutting_records' and old['id'] == 469:
                    allowed = {'cut_pieces', 'passed_pieces', 'updated_at'}
                elif table == 'production_batches' and old['id'] == 356:
                    allowed = {'planned_quantity', 'updated_at'}
                elif table == 'work_orders':
                    allowed = {'planned_input_qty', 'planned_output_qty', 'updated_at'}
                    if old['id'] == 1842:
                        allowed |= {'actual_input_qty', 'actual_output_qty', 'passed_qty', 'failed_qty'}
                assert changed <= allowed, (table, old['id'], changed - allowed)
                if changed:
                    changes[f"{table}:{old['id']}"] = {key: {'before': old[key], 'after': new[key]} for key in sorted(changed)}
        assert set(after) == set(before)
        assert all(row.planned_input_qty == row.planned_output_qty == 900 for row in work)
        assert cutting.actual_input_qty == cutting.actual_output_qty == cutting.passed_qty == 900
        assert cutting.failed_qty == 0 and cutting.status == 'completed'
        actor = next(row for row in db.query(User).order_by(User.id) if row.is_active and is_super_admin(row))
        log_action(db, actor, 'correct_nastil_quantity', 'CuttingRecord', 469,
                   old_value=before, new_value={
                       'reason': 'Owner requested PO-0431 Nastil 2 actual quantity 420; preserve Nastil 1 unchanged',
                       'changes': changes, 'backup': backup, 'backup_sha256': backup_sha256,
                       'nastil_1_preserved': True, 'no_bundles_created': True,
                   })
        db.flush()
        _finalize_postgres_audits(db)
        result = {'fingerprint': fingerprint, 'after_fingerprint': digest(after), 'changes': changes, 'mode': mode}
        if mode == 'apply':
            db.commit()
            result['committed'] = True
        else:
            db.rollback()
            result['committed'] = False
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('plan', 'rehearse', 'apply'), default='plan')
    parser.add_argument('--expected')
    parser.add_argument('--backup')
    parser.add_argument('--backup-sha256')
    args = parser.parse_args()
    print(json.dumps(run(args.mode, args.expected, args.backup, args.backup_sha256), default=str))
