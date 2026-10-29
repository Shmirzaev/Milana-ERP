"""Print-run persistence against the approved disposable PostgreSQL fixture."""
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.routes.packages import router as packages_router
from app.core.deps import get_current_user, get_db
from app.models.idempotency_service import bind_idempotency_identity
from app.models import package_workflows_service
from app.models.package_workflows_service import (
    PrintRunAuthorizationContext,
    create_run,
    create_print_run,
    lock_request,
)
from app.libs.dto.fulfillment.package_workflows import PrintRunIn
from app.schemas import (
    AuditLog, Department, IdempotencyRecord, Model, Package, PackageItem,
    PackagePrintRun, PackagePrintRunMember, PackagingRecord, ProductionOrder,
    Role, User, WorkOrder,
)
from app.tests.test_customer_create_postgres import chain, customer_pg_sessions  # noqa: F401


def _seed_print_run_operation(
    sessions,
    *,
    package_count=2,
    actor_factory="MIL",
    actor_department="PKG",
    actor_permissions=None,
):
    marker = uuid4().hex
    with sessions.begin() as db:
        departments = {}
        for code in {"PKG", actor_department}:
            department = db.query(Department).filter_by(code=code).one_or_none()
            if department is None:
                department = Department(name=f"{code} QA {marker}", code=code)
                db.add(department)
                db.flush()
            departments[code] = department
        model = Model(
            code=f"PRINT-RUN-OP-{marker}",
            name=f"Print run operation {marker}",
            product_type="shirt",
        )
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no=f"PRINT-RUN-OP-PO-{marker}",
            production_type="branded_stock",
            source_type="standard",
            model_id=model.id,
            planned_quantity=package_count,
            status="packaging",
        )
        db.add(order)
        db.flush()
        work_order = WorkOrder(
            production_order_id=order.id,
            department_id=departments["PKG"].id,
            operation="packaging",
            status="completed",
            planned_input_qty=package_count,
            planned_output_qty=package_count,
            actual_input_qty=package_count,
            actual_output_qty=package_count,
            passed_qty=package_count,
        )
        db.add(work_order)
        db.flush()
        db.add(PackagingRecord(
            work_order_id=work_order.id,
            input_qty=package_count,
            packed_qty=package_count,
            package_count=package_count,
            total_packed_quantity=package_count,
        ))
        role = None
        if actor_permissions is not None:
            role = Role(name=f"Print run role {marker}", permissions=actor_permissions)
            db.add(role)
            db.flush()
        actor = User(
            name=f"Print run actor {marker}",
            email=f"print-run-actor-{marker}@example.invalid",
            password_hash="unused",
            factory_code=actor_factory,
            department_id=departments[actor_department].id,
            role_id=role.id if role else None,
        )
        packages = [
            Package(
                package_no=f"PRINT-RUN-OP-PKG-{marker}-{index}",
                barcode=f"PRINT-RUN-OP-BC-{marker}-{index}",
                production_order_id=order.id,
                model_id=model.id,
                color="navy",
                total_quantity=1,
                capacity=1,
                status="packed",
                packaging_department_code="PKG",
                items=[PackageItem(model_id=model.id, color="navy", size="M", quantity=1)],
            )
            for index in range(package_count)
        ]
        db.add(actor)
        db.add_all(packages)
        db.flush()
        return int(actor.id), [int(package.id) for package in packages]


def _run_context(db, actor_id, *, global_access=False):
    actor = db.get(User, actor_id)
    bind_idempotency_identity(db, actor)
    return PrintRunAuthorizationContext(
        actor=actor,
        can_access_all_print_runs=global_access,
    )


def _invoke_print_run(sessions, actor_id, package_ids, key):
    with sessions() as db:
        authorization = _run_context(db, actor_id)
        try:
            return create_print_run(
                db,
                PrintRunIn(request_key=key, package_ids=package_ids),
                authorization,
            )
        except BaseException:
            db.rollback()
            raise


def _assert_no_print_run_effects(sessions, actor_id, package_ids, key):
    with sessions() as db:
        assert db.query(PackagePrintRunMember).filter(
            PackagePrintRunMember.package_id.in_(package_ids),
        ).count() == 0
        assert db.query(AuditLog).filter_by(
            user_id=actor_id, action="create_print_run",
        ).count() == 0
        assert db.query(IdempotencyRecord).filter_by(
            user_id=actor_id, key=str(key),
        ).count() == 0


def _assert_one_print_run(sessions, actor_id, package_ids, key, expected):
    with sessions() as db:
        members = (
            db.query(PackagePrintRunMember)
            .filter(PackagePrintRunMember.package_id.in_(package_ids))
            .order_by(PackagePrintRunMember.id)
            .all()
        )
        assert len(members) == len(package_ids)
        run_ids = {int(member.run_id) for member in members}
        assert len(run_ids) == 1
        run = db.get(PackagePrintRun, next(iter(run_ids)))
        assert run.package_ids == package_ids
        assert run.created_by == actor_id
        assert [member.package_id for member in members] == package_ids
        for member in members:
            package = db.get(Package, member.package_id)
            assert member.snapshot["package_no"] == package.package_no
            assert member.snapshot["barcode"] == package.barcode
            assert member.snapshot["quantity"] == 1
            assert member.snapshot["items"] == [{
                "model_id": package.model_id,
                "color": "navy",
                "size": "M",
                "quantity": 1,
            }]
        audit = db.query(AuditLog).filter_by(
            user_id=actor_id,
            action="create_print_run",
            entity_type="PackagePrintRun",
            entity_id=run.id,
        ).all()
        assert len(audit) == 1
        assert audit[0].new_value_json["package_ids"] == package_ids
        idempotency = db.query(IdempotencyRecord).filter_by(
            user_id=actor_id,
            key=str(key),
        ).all()
        assert len(idempotency) == 1
        assert idempotency[0].response_json == expected
        assert idempotency[0].status_code == 200


def _route_client(sessions, actor_id):
    app = FastAPI()
    app.include_router(packages_router)

    def isolated_db():
        with sessions() as db:
            yield db

    def current_user():
        with sessions() as db:
            user = db.get(User, actor_id)
            db.expunge(user)
            return user

    app.dependency_overrides[get_db] = isolated_db
    app.dependency_overrides[get_current_user] = current_user
    return TestClient(app, raise_server_exceptions=False)


def test_print_run_persistence_roundtrips_on_approved_postgres(customer_pg_sessions):
    sessions = customer_pg_sessions
    marker = uuid4().hex
    with sessions.begin() as db:
        department = db.query(Department).filter_by(code="PKG").one_or_none()
        if department is None:
            department = Department(name="Packaging", code="PKG")
            db.add(department)
            db.flush()
        model = Model(
            code=f"PRINT-RUN-{marker}",
            name=f"Print run persistence {marker}",
            product_type="shirt",
        )
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no=f"PRINT-RUN-PO-{marker}",
            production_type="branded_stock",
            source_type="standard",
            model_id=model.id,
            planned_quantity=2,
            status="packaging",
        )
        db.add(order)
        db.flush()
        work_order = WorkOrder(
            production_order_id=order.id,
            department_id=department.id,
            operation="packaging",
            status="completed",
            planned_input_qty=2,
            planned_output_qty=2,
            actual_input_qty=2,
            actual_output_qty=2,
            passed_qty=2,
        )
        db.add(work_order)
        db.flush()
        db.add(PackagingRecord(
            work_order_id=work_order.id,
            input_qty=2,
            packed_qty=2,
            package_count=2,
            total_packed_quantity=2,
        ))
        actor = User(
            name="Print run persistence QA",
            email=f"print-run-{marker}@example.invalid",
            password_hash="unused",
        )
        db.add(actor)
        packages = [
            Package(
                package_no=f"PRINT-RUN-PKG-{marker}-{index}",
                barcode=f"PRINT-RUN-BC-{marker}-{index}",
                production_order_id=order.id,
                model_id=model.id,
                color="navy",
                total_quantity=1,
                capacity=1,
                status="packed",
                packaging_department_code="PKG",
                items=[PackageItem(model_id=model.id, color="navy", size="M", quantity=1)],
            )
            for index in range(2)
        ]
        db.add_all(packages)
        db.flush()
        run = create_run(db, actor, packages)
        run_id = int(run.id)
        package_ids = [int(package.id) for package in packages]
        actor_id = int(actor.id)

    with sessions() as db:
        persisted = db.get(PackagePrintRun, run_id)
        members = (
            db.query(PackagePrintRunMember)
            .filter_by(run_id=run_id)
            .order_by(PackagePrintRunMember.id)
            .all()
        )
        audit = db.query(AuditLog).filter_by(
            action="create_print_run", entity_id=run_id,
        ).one()
        assert persisted.package_ids == package_ids
        assert persisted.created_by == actor_id
        assert persisted.packaging_department_code == "PKG"
        assert persisted.received_by is None and persisted.received_at is None
        assert [member.package_id for member in members] == package_ids
        assert all(member.snapshot["quantity"] == 1 for member in members)
        assert audit.new_value_json["package_ids"] == package_ids
    chain(sessions)


def test_selected_print_run_same_key_replays_and_changed_body_refuses(customer_pg_sessions):
    sessions = customer_pg_sessions
    actor_id, package_ids = _seed_print_run_operation(sessions)
    key = str(uuid4())

    first = _invoke_print_run(sessions, actor_id, package_ids[:1], key)
    replay = _invoke_print_run(sessions, actor_id, package_ids[:1], key)
    assert replay == first
    with pytest.raises(HTTPException) as changed:
        _invoke_print_run(sessions, actor_id, package_ids[1:], key)
    assert changed.value.status_code == 409

    with sessions() as db:
        assert db.query(PackagePrintRunMember).filter_by(
            package_id=package_ids[1],
        ).count() == 0
    _assert_one_print_run(sessions, actor_id, package_ids[:1], key, first)
    chain(sessions)


def test_selected_print_run_route_role_denial_has_no_writes(customer_pg_sessions):
    sessions = customer_pg_sessions
    actor_id, package_ids = _seed_print_run_operation(
        sessions,
        actor_permissions=["sales.view"],
    )
    key = str(uuid4())
    with _route_client(sessions, actor_id) as client:
        response = client.post(
            "/packages/print-runs",
            json={"request_key": key, "package_ids": package_ids[:1]},
        )
    assert response.status_code == 403, response.text
    _assert_no_print_run_effects(sessions, actor_id, package_ids, key)


def test_selected_print_run_foreign_department_denial_has_no_writes(customer_pg_sessions):
    sessions = customer_pg_sessions
    actor_id, package_ids = _seed_print_run_operation(
        sessions,
        actor_factory="BST",
        actor_department="BPK",
        actor_permissions=["packaging.packages"],
    )
    key = str(uuid4())
    with pytest.raises(HTTPException) as denied:
        _invoke_print_run(sessions, actor_id, package_ids, key)
    assert denied.value.status_code == 403
    _assert_no_print_run_effects(sessions, actor_id, package_ids, key)


@pytest.mark.parametrize("failure_point", ["audit_finalize", "idempotency_store"])
def test_selected_print_run_failure_rolls_back_then_retry(
    customer_pg_sessions, monkeypatch, failure_point,
):
    from app.models import audit_service

    sessions = customer_pg_sessions
    actor_id, package_ids = _seed_print_run_operation(sessions)
    key = str(uuid4())
    if failure_point == "audit_finalize":
        def fail_audit(*_args, **_kwargs):
            raise RuntimeError("injected print-run audit-finalize failure")

        patch_target = (audit_service, "add_audit_log_rows", fail_audit)
    else:
        original_store = package_workflows_service.store_idempotent_response

        def fail_after_idempotency_insert(db, **values):
            original_store(db, **values)
            raise RuntimeError("injected print-run idempotency-store failure")

        patch_target = (package_workflows_service, "store_idempotent_response", fail_after_idempotency_insert)

    with monkeypatch.context() as patch:
        patch.setattr(*patch_target)
        with sessions() as db:
            authorization = _run_context(db, actor_id)
            payload = PrintRunIn(request_key=key, package_ids=package_ids)
            with pytest.raises(RuntimeError, match="injected print-run"):
                create_print_run(db, payload, authorization)
            db.rollback()

    _assert_no_print_run_effects(sessions, actor_id, package_ids, key)
    result = _invoke_print_run(sessions, actor_id, package_ids, key)
    _assert_one_print_run(sessions, actor_id, package_ids, key, result)
    chain(sessions)


def test_selected_print_run_same_key_concurrency_serializes_exactly_once(customer_pg_sessions):
    sessions = customer_pg_sessions
    actor_id, package_ids = _seed_print_run_operation(sessions)
    key = str(uuid4())
    ready = Queue()

    def submit():
        with sessions() as db:
            authorization = _run_context(db, actor_id)
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            payload = PrintRunIn(request_key=key, package_ids=package_ids)
            try:
                return create_print_run(db, payload, authorization)
            except BaseException as error:
                db.rollback()
                return error

    with sessions() as holder, ThreadPoolExecutor(max_workers=2) as workers:
        lock_request(holder, actor_id, "print-run", key)
        futures = [workers.submit(submit) for _ in range(2)]
        pids = [ready.get(timeout=10) for _ in futures]
        try:
            deadline = monotonic() + 10
            while monotonic() < deadline:
                if all(
                    holder.execute(
                        text("SELECT cardinality(pg_blocking_pids(:pid))"),
                        {"pid": pid},
                    ).scalar_one()
                    for pid in pids
                ):
                    break
                sleep(0.02)
            else:
                pytest.fail("Both selected print-run requests must wait on the request lock")
        finally:
            holder.rollback()
        results = [future.result(timeout=30) for future in futures]

    assert all(isinstance(result, dict) for result in results), results
    assert results[0] == results[1]
    _assert_one_print_run(sessions, actor_id, package_ids, key, results[0])
    chain(sessions)
