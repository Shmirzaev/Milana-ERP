"""Owner-authorized PO-0293 status repair; run only with reviewed fingerprints."""
import hashlib
import json
from pathlib import Path

from sqlalchemy import or_, select, text

from app.db.base import Base
from app.db.session import SessionLocal
from app.models import CuttingRecord, Package, PackagingRecord, ProductionOrder, WorkOrder
from app.models.audit_service import log_action


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def row_data(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def snapshot(db):
    po = db.get(ProductionOrder, 318)
    assert po and po.production_no == 'PO-0293' and po.planned_quantity == 600
    work = db.query(WorkOrder).filter_by(production_order_id=po.id).order_by(WorkOrder.id).all()
    packages = db.query(Package).filter_by(production_order_id=po.id).order_by(Package.id).all()
    work_ids, package_ids = [w.id for w in work], [p.id for p in packages]
    protected = {}
    for name, table in sorted(Base.metadata.tables.items()):
        if name in {'production_orders', 'work_orders', 'audit_logs'}:
            continue
        filters = []
        for column, values in [('production_order_id', [318]), ('work_order_id', work_ids),
                               ('package_id', package_ids)]:
            if column in table.c:
                filters.append(table.c[column].in_(values))
        if name == 'package_print_runs':
            filters.append(text('true'))  # Historical print membership/snapshots must also survive.
        if filters:
            rows = db.execute(select(table).where(or_(*filters)).order_by(*table.primary_key.columns)).mappings()
            protected[name] = [dict(row) for row in rows]
    labels = {}
    for package in packages:
        url = str(package.qr_code_url or '').split('?', 1)[0]
        if url.startswith('/storage/'):
            path = Path('/app') / url.lstrip('/')
            assert path.is_file(), 'Existing QR file missing'
            labels[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    protected['label_file_hashes'] = labels
    state = {'order': row_data(po), 'work_orders': [row_data(w) for w in work]}
    return state, protected, packages


def operation(mode, expected=None, backup=None):
    assert mode in {'inspect', 'rehearse', 'apply'}
    with SessionLocal() as db:
        db.execute(text("SET LOCAL lock_timeout = '5s'"))
        if mode != 'inspect':
            assert expected and backup and backup['bytes'] > 0 and backup['restore_objects'] > 100
            db.query(ProductionOrder).filter_by(id=318).with_for_update().one()
            db.query(WorkOrder).filter_by(production_order_id=318).order_by(WorkOrder.id).with_for_update().all()
            db.query(Package).filter_by(production_order_id=318).order_by(Package.id).with_for_update(of=Package).all()
        before, protected, packages = snapshot(db)
        fingerprint = digest([before, protected])
        if mode == 'inspect':
            return {'fingerprint': fingerprint, 'protected_hash': digest(protected),
                    'state': before, 'package_count': len(packages),
                    'package_quantity': sum(p.total_quantity for p in packages)}
        assert fingerprint == expected['fingerprint'], 'Live order changed; inspect again before correction'
        work = {w.operation: w for w in db.query(WorkOrder).filter_by(production_order_id=318)}
        cutting, packaging, sewing = work['cutting'], work['packaging'], work['sewing']
        assert cutting.id == 1248 and packaging.id == 1250 and sewing.id == 1249
        assert cutting.passed_qty == sewing.passed_qty == 600 and cutting.failed_qty == 300
        cuts = db.query(CuttingRecord).filter_by(work_order_id=cutting.id).all()
        assert sum(r.passed_pieces for r in cuts) == 600
        assert sum(r.defective_pieces for r in cuts) == 0
        records = db.query(PackagingRecord).filter_by(work_order_id=packaging.id).all()
        assert packaging.passed_qty == sum(r.packed_qty for r in records) == 580
        assert packaging.failed_qty == sum(r.damaged_qty for r in records) == 0
        assert packaging.status == 'completed'
        assert len(packages) == 14 and sum(p.total_quantity for p in packages) == 560
        po = db.get(ProductionOrder, 318)
        assert po.status == 'storage_transfer'
        cutting.failed_qty = 0
        packaging.status = 'in_progress'
        packaging.end_time = None
        po.status = 'packaging'
        db.flush()
        after, protected_after, _ = snapshot(db)
        assert protected == protected_after, 'Package, label or execution evidence changed'
        allowed = {('order', 318): {'status', 'updated_at'},
                   ('work_orders', 1248): {'failed_qty', 'updated_at'},
                   ('work_orders', 1250): {'status', 'end_time', 'updated_at'}}
        changes = []
        for kind in ('order', 'work_orders'):
            old_rows = [before[kind]] if kind == 'order' else before[kind]
            new_rows = [after[kind]] if kind == 'order' else after[kind]
            for old, new in zip(old_rows, new_rows, strict=True):
                assert old['id'] == new['id']
                changed = {key for key in old if old[key] != new[key]}
                assert changed <= allowed.get((kind, old['id']), set()), 'Unexpected field change'
                if changed:
                    changes.append({'entity': kind, 'id': old['id'],
                                    'before': {key: old[key] for key in sorted(changed)},
                                    'after': {key: new[key] for key in sorted(changed)}})
        if mode == 'apply':
            log_action(db, None, 'correct_po0293_packaging_completion', 'ProductionOrder', 318,
                       old_value={'state': before, 'fingerprint': fingerprint},
                       new_value={'changes': changes, 'protected_hash': digest(protected),
                                  'backup': backup, 'reason': 'Owner requested remaining nastil access; fulfilled Cutting shortage was still counted'})
            db.commit()
        else:
            db.rollback()
            rolled_back, unchanged, _ = snapshot(db)
            assert digest([rolled_back, unchanged]) == fingerprint
        return {'mode': mode, 'changes': changes, 'protected_hash': digest(protected),
                'package_count': len(packages), 'package_quantity': 560,
                'remaining_packaging_quantity': 20, 'rollback_verified': mode == 'rehearse'}
