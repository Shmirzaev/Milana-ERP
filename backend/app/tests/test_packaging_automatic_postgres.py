"""Real PostgreSQL competing output, rollback and selected-source conservation."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func

from app.api.routes.production import post_packaging
from app.libs.dto.production.production import PackagingRecordIn
from app.libs.enums.packaging import PackagingDepartment
from app.models.packaging.sewing_availability_service import available_orders, input_budgets
from app.schemas import Package, PackagingReceipt, PackagingRecord, Role, User, WorkOrder
from app.tests.packaging_workflow_fixtures import seed_packaging_workflow
from app.tests.test_package_write_postgres import package_write_postgres_sessions  # noqa: F401


def test_concurrent_automatic_packaging_cannot_spend_same_sewing(package_write_postgres_sessions):
    sessions, _ = package_write_postgres_sessions
    with sessions.begin() as db:
        role = Role(name=f'WF02-{uuid4().hex}', permissions=['*'])
        actor = User(name='WF02 QA', email=f'{uuid4().hex}@example.invalid', password_hash='unused',
                     role=role, factory_code='MIL')
        db.add(actor); db.flush(); actor_id = actor.id
        fixture = seed_packaging_workflow(db)
        scenario = fixture['automatic']
    barrier = Barrier(2)
    def save():
        with sessions() as db:
            actor = db.get(User, actor_id)
            barrier.wait(timeout=10)
            try:
                post_packaging(PackagingRecordIn(work_order_id=scenario['work_order_id'],
                    production_batch_id=scenario['batch_ids'][0], input_qty=60, packed_qty=60), db, actor)
                return 'created'
            except HTTPException as error:
                db.rollback()
                assert error.status_code == 400
                return 'refused'
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(save) for _ in range(2)]
        assert sorted(f.result(timeout=25) for f in futures) == ['created', 'refused']
    with sessions() as db:
        target = db.get(WorkOrder, scenario['work_order_id'])
        assert input_budgets(db, target)[scenario['batch_ids'][0]]['available_input_qty'] == 35
        assert (target.actual_input_qty, target.actual_output_qty) == (60, 60)
        assert db.query(PackagingRecord).filter_by(work_order_id=target.id).count() == 1
        assert db.query(PackagingReceipt).filter_by(work_order_id=target.id).count() == 0
        assert db.query(Package).filter_by(production_order_id=scenario['order_id']).count() == 0
        assert next(row for row in available_orders(db, PackagingDepartment.MILANA)
                    if row.work_order_id == target.id).received_quantity == 95
    # Recover with the exact remaining partial quantity, never the original plan.
    with sessions() as db:
        post_packaging(PackagingRecordIn(work_order_id=scenario['work_order_id'],
            production_batch_id=scenario['batch_ids'][0], input_qty=35, packed_qty=34, damaged_qty=1),
            db, db.get(User, actor_id))
    with sessions() as db:
        assert db.query(func.sum(PackagingRecord.input_qty)).filter_by(work_order_id=scenario['work_order_id']).scalar() == 95
        assert input_budgets(db, db.get(WorkOrder, scenario['work_order_id']))[scenario['batch_ids'][0]]['available_input_qty'] == 0
