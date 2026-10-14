"""Owner-requested CUT-251 correction; run a reviewed route in an isolated interpreter.

The launcher supplies the undecorated candidate FUNCTION_SOURCE and its hash.
No serving module or file is modified. The route's commit is deferred until
all preconditions and preservation checks pass. Audit attribution is system,
not Oyatullo; his account is checked only for the existing Cutting authority.
"""
import hashlib
import json

from sqlalchemy import text

from app.api.routes import production as routes
from app.core.deps import user_permissions
from app.db.session import SessionLocal
from app.models import (
    Bundle, BundleScanLog, CuttingRecord, ProductionBatch, ProductionOrder,
    SewingAssignment, User, WorkOrder,
)
from app.services.audit import log_action
from app.services.factory_scope import bind_session_factory


def snapshot(db):
    def rows(model, query):
        return [{column.name: getattr(row, column.name) for column in model.__table__.columns}
                for row in query.order_by(model.id)]

    work_ids = db.query(WorkOrder.id).filter_by(production_order_id=271)
    bundle_ids = db.query(Bundle.id).filter_by(production_order_id=271)
    return {
        'order': rows(ProductionOrder, db.query(ProductionOrder).filter_by(id=271)),
        'batches': rows(ProductionBatch, db.query(ProductionBatch).filter_by(production_order_id=271)),
        'cutting': rows(CuttingRecord, db.query(CuttingRecord).filter(CuttingRecord.work_order_id.in_(work_ids))),
        'work': rows(WorkOrder, db.query(WorkOrder).filter_by(production_order_id=271)),
        'bundles': rows(Bundle, db.query(Bundle).filter_by(production_order_id=271)),
        'assignments': rows(SewingAssignment, db.query(SewingAssignment).filter(SewingAssignment.work_order_id.in_(work_ids))),
        'scans': rows(BundleScanLog, db.query(BundleScanLog).filter(BundleScanLog.bundle_id.in_(bundle_ids))),
    }


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def operation(mode, function_source, source_hash, expected=None, backup=None):
    assert mode in ('inspect', 'rehearse', 'apply')
    assert hashlib.sha256(function_source.encode()).hexdigest() == source_hash
    with SessionLocal() as db:
        db.execute(text('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE'))
        db.execute(text("SET LOCAL lock_timeout = '5s'"))
        po = db.query(ProductionOrder).filter_by(id=271).with_for_update(of=ProductionOrder).one()
        assert po.source_type == 'usluga' and po.order_no == 'USL-0008'
        db.query(WorkOrder).filter_by(production_order_id=271).order_by(WorkOrder.id).with_for_update().all()
        rec = db.query(CuttingRecord).filter_by(id=251).with_for_update().one()
        assert rec.work_order_id == 1062 and rec.production_batch_id == 139
        assert rec.material_role == 'main' and rec.approval_status == 'approved'
        assert (rec.cut_pieces, rec.passed_pieces, rec.total_bundled_quantity) == (606, 606, 606)
        batch = db.get(ProductionBatch, 139)
        assert batch.batch_no == '0271-01' and batch.name == 'Nastil 1' and batch.planned_quantity == 606
        bundles = db.query(Bundle).filter_by(cutting_record_id=251).order_by(Bundle.id).with_for_update().all()
        assert len(bundles) == 606 and all(b.quantity == 1 and b.status == 'received_sewing' for b in bundles)
        sizes = {str(size): 0 for size in range(44, 55, 2)}
        for bundle in bundles:
            assert bundle.production_batch_id == 139 and bundle.color == 'Dark Blue'
            sizes[bundle.size] += bundle.quantity
        assert set(sizes.values()) == {101}
        user = db.get(User, 20)
        assert user.name == 'Oyatullo' and user.is_active and user.factory_code == 'ECO'
        bind_session_factory(user, 'ECO')
        assert 'cutting.records' in user_permissions(user)
        before = snapshot(db)
        fingerprint = digest(before)
        if mode == 'inspect':
            return {'fingerprint': fingerprint, 'sizes': sizes, 'source_hash': source_hash}
        assert expected['fingerprint'] == fingerprint and expected['source_hash'] == source_hash
        assert backup and backup['bytes'] > 0 and backup['restore_objects'] > 100

        # Execute precisely the tested handler, with no server reload or code replacement.
        namespace = dict(vars(routes))
        audits = []

        def system_audit(session, _actor, action, entity_type, entity_id, **values):
            values['new_value'] = dict(values['new_value'],
                reason='Owner requested 110 pieces per size, total 660; system maintenance',
                permission_user_id=20, backup=backup, source_hash=source_hash)
            audits.append(log_action(session, None, action, entity_type, entity_id, **values))

        namespace['log_action'] = system_audit
        exec(compile(function_source, '<reviewed-nastil-correction>', 'exec'), namespace)
        commit = db.commit
        db.commit = db.flush
        payload = routes.UslugaBundleSizeCountUpdateIn(sizes=[
            {'color': 'Dark Blue', 'size': size, 'quantity': 110} for size in sizes
        ])
        result = namespace['update_usluga_bundle_size_counts'](251, payload, db, user)
        db.flush()
        after = snapshot(db)
        assert result['cut_pieces'] == 660 and {row['quantity'] for row in result['size_counts']} == {110}
        assert db.get(SewingAssignment, 62).quantity == 660
        allowed = {
            'batches': {139: {'planned_quantity', 'updated_at'}},
            'cutting': {251: {'cut_pieces', 'passed_pieces', 'total_bundled_quantity', 'bundle_count', 'updated_at'}},
            'work': {
                1062: {'planned_input_qty', 'planned_output_qty', 'actual_input_qty', 'actual_output_qty', 'passed_qty', 'updated_at'},
                1063: {'planned_input_qty', 'planned_output_qty', 'updated_at'},
                1064: {'planned_input_qty', 'planned_output_qty', 'updated_at'},
            },
            'bundles': {b.id: {'quantity', 'updated_at'} for b in bundles},
            'assignments': {62: {'quantity', 'updated_at'}},
        }
        changed = {}
        for table, old_rows in before.items():
            assert len(old_rows) == len(after[table]), table
            changed[table] = []
            for old, new in zip(old_rows, after[table]):
                assert old['id'] == new['id']
                fields = {key for key in old if old[key] != new[key]}
                assert fields <= allowed.get(table, {}).get(old['id'], set()), (table, old['id'], fields)
                if fields:
                    changed[table].append({'id': old['id'], 'fields': sorted(fields)})
        log_action(db, None, 'owner_correct_nastil_0271', 'CuttingRecord', 251,
                   old_value=before, new_value={'snapshot': after, 'backup': backup, 'source_hash': source_hash})
        output = {'changed': changed, 'before': fingerprint, 'after': digest(after),
                  'sizes': {size: 110 for size in sizes}, 'total': 660}
        if mode == 'apply':
            commit()
        else:
            db.rollback()
            assert digest(snapshot(db)) == fingerprint
            output['rollback_verified'] = True
        return output
