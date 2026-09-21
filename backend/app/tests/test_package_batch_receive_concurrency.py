from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from time import monotonic, sleep
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text

from app.api.routes import packages as package_routes
from app.models import AuditLog, Model, Package, PackageScanLog, ProductionOrder, User
from app.schemas.tracking import PackageBatchReceiveStorageIn
from app.services.packages import prepare_locked_package_receive
from app.tests.test_password_change_races import (
    password_change_postgres_sessions as password_change_postgres_sessions,
)


def test_postgres_batch_receive_locks_refreshes_and_records_only_once(password_change_postgres_sessions):
    sessions, engine = password_change_postgres_sessions
    marker = uuid4().hex
    with sessions() as db:
        actor = User(name="Receive race", email=f"receive-{marker}@example.invalid",
                     password_hash="test-only", is_active=True, factory_code="MIL")
        model = Model(code=f"RX-{marker}", name="Receive race")
        db.add_all([actor, model])
        db.flush()
        order = ProductionOrder(production_no=f"RX-{marker}", model_id=model.id,
                                production_type="branded_stock", planned_quantity=1, status="packaging")
        db.add(order)
        db.flush()
        package = Package(package_no=f"RX-{marker}", barcode=f"QR-{marker}",
                          model_id=model.id, production_order_id=order.id, color="blue",
                          total_quantity=1, capacity=1, status="packed")
        db.add(package)
        db.commit()
        actor_id, package_id = actor.id, package.id

    payload = PackageBatchReceiveStorageIn(package_ids=[package_id], storage_cell="A-01", storage_shelf="S1")
    contender_pid = Queue()

    def contender():
        with sessions() as db:
            contender_pid.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            try:
                package_routes.api_batch_receive_storage(payload, db, db.get(User, actor_id))
            except HTTPException as exc:
                db.rollback()
                return exc.status_code
            return 200

    with sessions() as winner, ThreadPoolExecutor(max_workers=1) as executor:
        gate = prepare_locked_package_receive(winner, [package_id])
        assert gate.packages_by_id[package_id].status == "packed"
        future = executor.submit(contender)
        try:
            pid = contender_pid.get(timeout=10)
            deadline = monotonic() + 10
            with engine.connect() as observer:
                while monotonic() < deadline:
                    blocked = observer.execute(text("SELECT cardinality(pg_blocking_pids(:pid))"), {"pid": pid}).scalar_one()
                    if blocked:
                        break
                    assert not future.done(), "Contender did not wait for package lock"
                    sleep(0.02)
                else:
                    raise AssertionError("Contender never waited for package lock")
            result = package_routes.api_batch_receive_storage(payload, winner, winner.get(User, actor_id))
            assert result["count"] == 1
            assert result["packages"][0]["status"] == "received_in_storage"
        finally:
            winner.rollback()
        assert future.result(timeout=15) == 400

    with sessions() as db:
        assert db.get(Package, package_id).status == "received_in_storage"
        assert db.query(PackageScanLog).filter_by(package_id=package_id, scan_type="received_storage").count() == 1
        assert db.query(AuditLog).filter_by(entity_type="Package", entity_id=package_id, action="receive_storage").count() == 1
