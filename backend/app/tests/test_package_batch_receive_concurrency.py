from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from time import monotonic, sleep
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text

from app.api.routes import package_workflows as package_workflow_routes
from app.api.routes import packages as package_routes
from app.models import (
    AuditLog,
    FinishedGoodsStock,
    Model,
    Package,
    PackageItem,
    PackagePrintRun,
    PackagePrintRunMember,
    PackageScanLog,
    ProductionOrder,
    User,
)
from app.schemas.package_workflows import PrintRunReceiveIn
from app.schemas.tracking import PackageBatchReceiveStorageIn
from app.services import package_workflows as package_workflow_service
from app.services.packages import prepare_locked_package_receive
from app.tests.test_password_change_races import (
    password_change_postgres_sessions as password_change_postgres_sessions,
)


def _print_run_fixture(sessions):
    marker = uuid4().hex
    with sessions() as db:
        actor = User(
            name="Print receive race",
            email=f"print-receive-{marker}@example.invalid",
            password_hash="test-only",
            is_active=True,
            factory_code="MIL",
        )
        model = Model(code=f"PRX-{marker}", name="Print receive race")
        db.add_all([actor, model])
        db.flush()
        order = ProductionOrder(
            production_no=f"PRX-{marker}",
            model_id=model.id,
            production_type="branded_stock",
            planned_quantity=1,
            status="packaging",
        )
        db.add(order)
        db.flush()
        package = Package(
            package_no=f"PRX-{marker}",
            barcode=f"QR-PRX-{marker}",
            model_id=model.id,
            production_order_id=order.id,
            packaging_department_code="PKG",
            color="blue",
            total_quantity=1,
            capacity=1,
            status="packed",
        )
        package.items = [PackageItem(model_id=model.id, color="blue", size="M", quantity=1)]
        db.add(package)
        db.flush()
        stock = FinishedGoodsStock(
            package_id=package.id,
            production_order_id=order.id,
            model_id=model.id,
            color="blue",
            size="M",
            quantity=1,
            available_qty=1,
        )
        print_run = PackagePrintRun(
            run_no=f"PRX-{marker}",
            code=f"PACKRUN:PRX-{marker}",
            packaging_department_code="PKG",
            package_ids=[package.id],
            created_by=actor.id,
        )
        db.add_all([stock, print_run])
        db.flush()
        db.add(
            PackagePrintRunMember(
                run_id=print_run.id,
                package_id=package.id,
                snapshot=package_workflow_service.contents(package),
            )
        )
        db.commit()
        return int(actor.id), int(package.id), int(print_run.id), str(print_run.code)


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


def test_postgres_print_run_receivers_serialize_on_run_and_record_once(password_change_postgres_sessions):
    sessions, engine = password_change_postgres_sessions
    actor_id, package_id, run_id, code = _print_run_fixture(sessions)
    payload = PrintRunReceiveIn(code=code, storage_cell="A-01", storage_shelf="S1")
    contender_pid = Queue()

    def contender():
        with sessions() as db:
            contender_pid.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            return package_workflow_routes.receive_print_run(payload, db, db.get(User, actor_id))["count"]

    with sessions() as winner, ThreadPoolExecutor(max_workers=1) as executor:
        locked_run = (
            winner.query(PackagePrintRun)
            .filter(PackagePrintRun.id == run_id)
            .with_for_update()
            .one()
        )
        assert locked_run.received_at is None
        future = executor.submit(contender)
        pid = contender_pid.get(timeout=10)
        deadline = monotonic() + 10
        with engine.connect() as observer:
            while monotonic() < deadline:
                blocked = observer.execute(
                    text("SELECT cardinality(pg_blocking_pids(:pid))"),
                    {"pid": pid},
                ).scalar_one()
                if blocked:
                    break
                assert not future.done(), "Contender did not wait for print-run lock"
                sleep(0.02)
            else:
                raise AssertionError("Contender never waited for print-run lock")
        assert package_workflow_routes.receive_print_run(payload, winner, winner.get(User, actor_id))["count"] == 1
        assert future.result(timeout=15) == 1

    with sessions() as db:
        assert db.get(PackagePrintRun, run_id).received_at is not None
        assert db.get(Package, package_id).status == "received_in_storage"
        assert db.query(PackageScanLog).filter_by(
            package_id=package_id,
            scan_type="received_storage",
        ).count() == 1
        assert db.query(AuditLog).filter_by(
            entity_type="PackagePrintRun",
            entity_id=run_id,
            action="receive_print_run",
        ).count() == 1


def test_postgres_print_run_receive_can_retry_after_outer_rollback(password_change_postgres_sessions):
    sessions, _engine = password_change_postgres_sessions
    actor_id, package_id, run_id, code = _print_run_fixture(sessions)
    payload = PrintRunReceiveIn(code=code, storage_cell="A-01", storage_shelf="S1")

    with sessions() as db:
        run, packages, members = package_workflow_service.receive_run(db, db.get(User, actor_id), payload)
        assert run.received_at is not None
        assert [package.id for package in packages] == [package_id]
        assert [member.package_id for member in members] == [package_id]
        assert db.query(PackageScanLog).filter_by(
            package_id=package_id,
            scan_type="received_storage",
        ).count() == 1
        db.rollback()

    with sessions() as db:
        assert db.get(PackagePrintRun, run_id).received_at is None
        assert db.get(Package, package_id).status == "packed"
        result = package_workflow_routes.receive_print_run(payload, db, db.get(User, actor_id))
        assert result["count"] == 1

    with sessions() as db:
        assert db.get(PackagePrintRun, run_id).received_at is not None
        assert db.get(Package, package_id).status == "received_in_storage"
        assert db.query(PackageScanLog).filter_by(
            package_id=package_id,
            scan_type="received_storage",
        ).count() == 1
        assert db.query(AuditLog).filter_by(
            entity_type="PackagePrintRun",
            entity_id=run_id,
            action="receive_print_run",
        ).count() == 1
