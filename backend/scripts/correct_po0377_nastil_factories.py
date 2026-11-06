"""Preview PO-0377's requested routing correction; apply only after release/backup.

Run inside the reviewed candidate image using its configured database. Default
preview is read-only. --apply requires an existing super-admin actor and a verified
backup reference. This routes work; it never creates historical sewing output.
"""
import argparse
import hashlib
import json

from sqlalchemy import select, text

from app.db.session import SessionLocal
from app.models.cutting_sewing_factory_service import change_sewing_factory
from app.models.factory_scope_service import user_is_super_admin
from app.schemas import (Bundle, Package, PackageItem, FinishedGoodsStock, ProductionBatch,
                         ProductionOrder, SewingRecord, User, WorkOrder)


def fingerprint(db, table, predicate):
    rows = db.execute(select(table).where(predicate).order_by(table.c.id)).mappings().all()
    return hashlib.sha256(json.dumps([dict(r) for r in rows], default=str, sort_keys=True).encode()).hexdigest()


def protected_fingerprints(db, order_id, selected):
    packages = select(Package.id).where(Package.production_order_id == order_id)
    works = select(WorkOrder.id).where(WorkOrder.production_order_id == order_id)
    return {
        'order': fingerprint(db, ProductionOrder.__table__, ProductionOrder.id == order_id),
        'batches': fingerprint(db, ProductionBatch.__table__, ProductionBatch.production_order_id == order_id),
        'other_bundles': fingerprint(db, Bundle.__table__, (Bundle.production_order_id == order_id) &
            (Bundle.production_batch_id.is_(None) | Bundle.production_batch_id.notin_(selected))),
        'sewing_records': fingerprint(db, SewingRecord.__table__, SewingRecord.work_order_id.in_(works)),
        'packages': fingerprint(db, Package.__table__, Package.production_order_id == order_id),
        'package_items': fingerprint(db, PackageItem.__table__, PackageItem.package_id.in_(packages)),
        'stock': fingerprint(db, FinishedGoodsStock.__table__, FinishedGoodsStock.package_id.in_(packages)),
    }


def correct(db, *, actor_id=None, apply=False, expected_identity=(416, 253, 255, 256)):
    order = db.query(ProductionOrder).filter_by(production_no='PO-0377').one()
    rows = db.query(ProductionBatch).filter_by(production_order_id=order.id).all()
    if any(sum(b.batch_index == index for b in rows) != 1 for index in (1, 2, 3)):
        raise RuntimeError('Expected Nastils 1, 2 and 3 are missing or ambiguous')
    batches = {b.batch_index: b for b in rows}
    # No CLI override: these are the exact production identities inspected for
    # this correction. The function argument permits explicit isolated fixtures.
    if (order.id, *(batches[i].id for i in (1, 2, 3))) != expected_identity:
        raise RuntimeError('PO-0377 identity differs from the reviewed production records')
    selected = [batches[i].id for i in (2, 3)]
    cutting = db.query(WorkOrder).filter_by(production_order_id=order.id, operation='cutting', production_batch_id=None).one()
    routing = db.query(Bundle.production_batch_id, Bundle.sewing_factory_code, Bundle.quantity).filter(
        Bundle.production_order_id == order.id, Bundle.status != 'cancelled').all()
    if {code for bid, code, _ in routing if bid == batches[1].id} != {'MIL'}:
        raise RuntimeError('Nastil 1 is not exclusively Milana; stop for fresh review')
    before = protected_fingerprints(db, order.id, selected)
    report = {'production_no': order.production_no, 'selected_nastils': [2, 3],
              'selected_batch_ids': selected, 'destination': 'BST', 'applied': False,
              'current_routing': [dict(batch_id=bid, factory=code, quantity=qty) for bid, code, qty in routing],
              'protected_fingerprints': before}
    if not apply:
        return report
    actor = db.get(User, actor_id)
    if not actor or not actor.is_active or not user_is_super_admin(actor):
        raise RuntimeError('An active existing super-admin actor is required')
    result = change_sewing_factory(db, cutting, 'BST', actor, selected)
    db.flush()
    if before != protected_fingerprints(db, order.id, selected):
        raise RuntimeError('Protected quantities/history changed; transaction must roll back')
    report.update(applied=True, result=result)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--actor-id', type=int)
    parser.add_argument('--backup-reference')
    args = parser.parse_args()
    if args.apply and (not args.actor_id or not args.backup_reference):
        parser.error('--apply requires --actor-id and --backup-reference')
    with SessionLocal() as db:
        if not args.apply and db.get_bind().dialect.name == 'postgresql':
            db.execute(text('SET TRANSACTION READ ONLY'))
        report = correct(db, actor_id=args.actor_id, apply=args.apply)
        if args.apply:
            db.commit()
            report['backup_reference'] = args.backup_reference
        else:
            db.rollback()
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
