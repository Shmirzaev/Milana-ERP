from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event
from time import monotonic, sleep

from sqlalchemy import text, update

from app.api.routes.production import PackagingReceiveFromSewingIn, post_packaging, receive_packaging_from_sewing
from app.schemas.production import PackagingRecordIn
from app.models import Department, PackagingReceipt, User, WorkOrder
from app.tests.conftest import TestSessionLocal
from app.tests.test_sewing_corrections import setup_record
from app.tests.test_purchase_conversion_integrity import conversion_postgres_sessions  # noqa: F401


def test_packaging_receipt_refreshes_cached_target_before_increment(client):
    _, source_id, _ = setup_record()
    with TestSessionLocal() as db:
        source = db.get(WorkOrder, source_id)
        department = db.query(Department).filter_by(code="PKG").one()
        target = WorkOrder(production_order_id=source.production_order_id,
                           department_id=department.id, operation="packaging",
                           status="collected", actual_input_qty=5)
        db.add(target)
        db.commit()
        target_id = target.id
        assert target.actual_input_qty == 5
        # Model a cached identity after another serialized writer changes the row.
        db.execute(update(WorkOrder).where(WorkOrder.id == target_id)
                   .values(actual_input_qty=9).execution_options(synchronize_session=False))
        assert target.actual_input_qty == 5
        current = db.query(User).filter_by(email="admin@example.com").one()
        result = receive_packaging_from_sewing(
            PackagingReceiveFromSewingIn(work_order_id=target_id, quantity=3), db, current,
        )
        assert result["quantity"] == 3
    with TestSessionLocal() as db:
        assert db.get(WorkOrder, target_id).actual_input_qty == 12
        assert db.query(PackagingReceipt).filter_by(work_order_id=target_id).count() == 1


def test_packaging_record_refreshes_cached_output_counters(client):
    _, source_id, _ = setup_record()
    with TestSessionLocal() as db:
        source = db.get(WorkOrder, source_id)
        department = db.query(Department).filter_by(code="PKG").one()
        target = WorkOrder(production_order_id=source.production_order_id,
                           department_id=department.id, operation="packaging",
                           status="in_progress", planned_input_qty=100, planned_output_qty=100,
                           actual_input_qty=5, actual_output_qty=5, passed_qty=5)
        db.add(target)
        db.commit()
        target_id = target.id
        assert target.actual_output_qty == 5
        db.execute(update(WorkOrder).where(WorkOrder.id == target_id)
                   .values(actual_input_qty=9, actual_output_qty=9, passed_qty=9)
                   .execution_options(synchronize_session=False))
        assert target.actual_output_qty == 5
        current = db.query(User).filter_by(email="admin@example.com").one()
        post_packaging(PackagingRecordIn(work_order_id=target_id, input_qty=3, packed_qty=3), db, current)
    with TestSessionLocal() as db:
        target = db.get(WorkOrder, target_id)
        assert (target.actual_input_qty, target.actual_output_qty, target.passed_qty) == (12, 12, 12)


def test_postgres_packaging_receipts_preserve_both_increments(conversion_postgres_sessions):
    from app.models import Model, ProductionOrder, Role, SewingRecord

    sessions = conversion_postgres_sessions
    with sessions.begin() as db:
        role = Role(name="Packaging regression", permissions=["*"])
        actor = User(name="Packaging tester", email="packaging@example.invalid", password_hash="unused", role=role, factory_code="MIL")
        model = Model(code="WF06-PG", name="Synthetic packaging")
        sewing = Department(code="SEW", name="Sewing")
        packaging = Department(code="PKG", name="Packaging")
        db.add_all([actor, model, sewing, packaging])
        db.flush()
        order = ProductionOrder(production_no="WF06-PG", model_id=model.id, production_type="branded_stock", planned_quantity=100)
        db.add(order)
        db.flush()
        source = WorkOrder(production_order_id=order.id, department_id=sewing.id, operation="sewing", status="in_progress", passed_qty=80)
        target = WorkOrder(production_order_id=order.id, department_id=packaging.id, operation="packaging", status="collected", actual_input_qty=5)
        db.add_all([source, target])
        db.flush()
        db.add(SewingRecord(work_order_id=source.id, input_qty=80, sewn_qty=80, passed_qty=80))
        source_id, target_id, actor_id = source.id, target.id, actor.id

    ready, start = Queue(), Event()

    def receive(quantity):
        with sessions() as db:
            cached = db.get(WorkOrder, target_id)
            assert cached.actual_input_qty == 5
            actor = db.get(User, actor_id)
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            assert start.wait(15)
            return receive_packaging_from_sewing(
                PackagingReceiveFromSewingIn(work_order_id=target_id, quantity=quantity), db, actor,
            )["quantity"]

    with sessions() as holder, ThreadPoolExecutor(max_workers=2) as pool:
        holder.execute(text("SELECT id FROM work_orders WHERE id=:id FOR UPDATE"), {"id": source_id})
        futures = [pool.submit(receive, quantity) for quantity in (3, 4)]
        try:
            pids = [ready.get(timeout=15) for _ in futures]
            start.set()
            deadline = monotonic() + 15
            while monotonic() < deadline:
                if all(holder.execute(text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid}).scalar_one() for pid in pids):
                    break
                sleep(0.02)
            else:
                raise AssertionError("Both packaging writers must wait on the source lock")
        finally:
            start.set()
            holder.rollback()
        assert sorted(future.result(timeout=25) for future in futures) == [3, 4]
    with sessions() as db:
        assert db.get(WorkOrder, target_id).actual_input_qty == 12
        assert db.query(PackagingReceipt).filter_by(work_order_id=target_id).count() == 2
