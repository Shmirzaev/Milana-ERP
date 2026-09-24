from concurrent.futures import ThreadPoolExecutor
import os
from threading import Event
import time
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import tasks
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import SessionLocal
from app.models import (
    AuditLog,
    Bundle,
    Department,
    Invoice,
    LegacyStockReceipt,
    ManualPackageReceipt,
    Model,
    Notification,
    Package,
    ProductionOrder,
    Role,
    SalesOrder,
    Shipment,
    Task,
    User,
    WorkOrder,
)
from app.schemas.tasks import TaskIn


@pytest.fixture(scope="module")
def task_reference_postgres_sessions():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Requires disposable PostgreSQL task-reference race coverage")
    url = make_url(raw_url)
    if (
        url.get_backend_name() != "postgresql"
        or url.host not in {"127.0.0.1", "localhost", "::1"}
        or url.query
    ):
        pytest.fail("Task-reference race tests require loopback PostgreSQL without URL overrides")
    schema = f"task_reference_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={
            "options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"
        },
        pool_size=3,
        max_overflow=0,
        isolation_level="READ COMMITTED",
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def _actor(
    permissions=(),
    *,
    factory="MIL",
    selected=None,
    extra=(),
    department=None,
    policy=None,
):
    with SessionLocal() as db:
        role = Role(name=f"Task reference {uuid4().hex}", permissions=list(permissions))
        user = User(
            name="Task reference actor",
            email=f"task-reference-{uuid4().hex}@example.com",
            password_hash="unused-token-fixture",
            role=role,
            department=_department(db, department) if department else None,
            factory_code=factory,
            extra_permissions=list(extra),
            access_policy=policy,
        )
        db.add(user)
        db.commit()
        return user.id, {
            "Authorization": f"Bearer {create_access_token(user.id, {'factory_code': selected or factory})}"
        }


def _department(db, code):
    row = db.query(Department).filter(Department.code == code).first()
    if row is None:
        row = Department(name=f"Task reference {code} {uuid4().hex}", code=code)
        db.add(row)
        db.flush()
    return row


def _model_id(db):
    model_id = db.query(Model.id).order_by(Model.id).scalar()
    assert model_id is not None
    return int(model_id)


def _seed_supported_references(db, actor_id):
    marker = uuid4().hex
    model_id = _model_id(db)
    cutting = _department(db, "CUT")
    sales_order = SalesOrder(order_no=f"TASK-SO-{marker}")
    production_order = ProductionOrder(
        production_no=f"TASK-PO-{marker}",
        production_type="branded_stock",
        source_type="standard",
        model_id=model_id,
        planned_quantity=1,
    )
    db.add_all([sales_order, production_order])
    db.flush()
    work_order = WorkOrder(
        production_order_id=production_order.id,
        department_id=cutting.id,
        operation="cutting",
    )
    bundle = Bundle(
        bundle_no=f"TASK-BUNDLE-{marker}",
        barcode=f"TASK-BUNDLE-BC-{marker}",
        production_order_id=production_order.id,
        model_id=model_id,
        color="Black",
        size="M",
        quantity=1,
        sewing_factory_code="BST",
    )
    package = Package(
        package_no=f"TASK-PACKAGE-{marker}",
        barcode=f"TASK-PACKAGE-BC-{marker}",
        packaging_department_code="PKG",
        production_order_id=production_order.id,
        model_id=model_id,
        color="Black",
        total_quantity=1,
        capacity=1,
    )
    shipment = Shipment(shipment_no=f"TASK-SHIP-{marker}")
    invoice = Invoice(
        sales_order_id=sales_order.id,
        invoice_no=f"TASK-INV-{marker}",
        amount=1,
    )
    db.add_all([work_order, bundle, package, shipment, invoice])
    db.commit()
    return {
        "sales-order": (sales_order.id, "SalesOrder", f"/sales-orders/{sales_order.id}"),
        "production_orders": (
            production_order.id,
            "ProductionOrder",
            f"/production-orders/{production_order.id}",
        ),
        "work order": (work_order.id, "WorkOrder", f"/work-orders/{work_order.id}/cutting"),
        "bundles": (bundle.id, "Bundle", f"/bundles/{bundle.id}"),
        "packages": (package.id, "Package", f"/packages/{package.id}"),
        "shipments": (shipment.id, "Shipment", "/shipments"),
        "invoices": (invoice.id, "Invoice", "/finance"),
    }


def _write_counts():
    with SessionLocal() as db:
        return (
            db.query(Task).count(),
            db.query(Notification).count(),
            db.query(AuditLog).count(),
        )


def _task_snapshot(task_id):
    with SessionLocal() as db:
        row = db.get(Task, task_id)
        return {column.name: getattr(row, column.name) for column in Task.__table__.columns}


def test_all_supported_reference_types_preserve_aliases_and_build_real_links(client):
    actor_id, headers = _actor(("*",))
    recipient_id, _ = _actor(("planning.view",))
    with SessionLocal() as db:
        references = _seed_supported_references(db, actor_id)

    for alias, (entity_id, canonical, link) in references.items():
        response = client.post(
            "/api/tasks",
            headers=headers,
            json={"title": f"Reference {canonical}", "entity_type": alias, "entity_id": entity_id},
        )
        assert response.status_code == 201, response.text
        assert response.json()["entity_type"] == alias
        with SessionLocal() as db:
            task = db.get(Task, response.json()["id"])
            assert tasks._task_link(task, db=db) == link

    compatibility_alias = "_Sales__Order_"
    alias_response = client.post(
        "/api/tasks",
        headers=headers,
        json={
            "title": "Preserve legacy alias",
            "entity_type": compatibility_alias,
            "entity_id": references["sales-order"][0],
        },
    )
    assert alias_response.status_code == 201, alias_response.text
    assert alias_response.json()["entity_type"] == compatibility_alias

    work_order_id, _, work_order_link = references["work order"]
    assigned = client.post(
        "/api/tasks",
        headers=headers,
        json={
            "title": "Open the cutting work order",
            "assigned_to": recipient_id,
            "entity_type": "WorkOrder",
            "entity_id": work_order_id,
        },
    )
    assert assigned.status_code == 201, assigned.text
    with SessionLocal() as db:
        notice = db.query(Notification).filter(Notification.user_id == recipient_id).one()
        assert notice.link == work_order_link


def test_missing_permission_hides_existing_and_missing_finance_target_before_writes(client):
    _, headers = _actor(("finance.view",), policy={"MIL": {"deny": ["finance.view"]}})
    with SessionLocal() as db:
        order = SalesOrder(order_no=f"TASK-DENIED-{uuid4().hex}")
        db.add(order)
        db.flush()
        invoice = Invoice(
            sales_order_id=order.id,
            invoice_no=f"TASK-DENIED-INV-{uuid4().hex}",
            amount=1,
        )
        db.add(invoice)
        db.commit()
        order_id = order.id
        invoice_id = invoice.id
    before = _write_counts()

    for entity_id in (invoice_id, 2_000_000_000):
        response = client.post(
            "/api/tasks",
            headers=headers,
            json={"title": "Denied", "entity_type": "Invoice", "entity_id": entity_id},
        )
        assert response.status_code == 403, response.text
        assert response.json() == {"detail": "Not allowed to reference this task target"}
        assert _write_counts() == before

    invalid = client.post(
        "/api/tasks",
        headers=headers,
        json={"title": "Invalid", "entity_type": "sales#order", "entity_id": order_id},
    )
    assert invalid.status_code == 422, invalid.text
    assert _write_counts() == before


def test_standard_production_references_match_target_read_routes_without_factory_rules(client):
    mil_id, mil_headers = _actor(("management.view",), factory="MIL")
    _, bst_headers = _actor(("management.view",), factory="BST")
    _, eco_headers = _actor(("management.view",), factory="ECO")
    _, current_user_only_headers = _actor(factory="ECO")
    with SessionLocal() as db:
        refs = _seed_supported_references(db, mil_id)
        bst = _department(db, "BST")
        bst_work_order = WorkOrder(
            production_order_id=refs["production_orders"][0],
            department_id=bst.id,
            operation="sewing",
        )
        db.add(bst_work_order)
        db.commit()
        bst_work_order_id = bst_work_order.id

    for alias in ("production_orders", "work order"):
        entity_id = refs[alias][0]
        for headers in (mil_headers, bst_headers, eco_headers):
            response = client.post(
                "/api/tasks",
                headers=headers,
                json={"title": alias, "entity_type": alias, "entity_id": entity_id},
            )
            assert response.status_code == 201, response.text

    for headers in (mil_headers, bst_headers, eco_headers):
        assert client.post(
            "/api/tasks",
            headers=headers,
            json={"title": "BST sewing", "entity_type": "WorkOrder", "entity_id": bst_work_order_id},
        ).status_code == 201

    # Bundle detail only requires an authenticated user, regardless of the
    # bundle's sewing alias or the selected factory.
    assert client.post(
        "/api/tasks",
        headers=current_user_only_headers,
        json={
            "title": "Routed bundle",
            "entity_type": "bundles",
            "entity_id": refs["bundles"][0],
        },
    ).status_code == 201


def test_usluga_reference_requires_eco_factory(client):
    _, mil_headers = _actor(("*",), factory="MIL")
    _, bst_headers = _actor(("*",), factory="BST")
    _, eco_headers = _actor(("*",), factory="ECO")
    super_id, _ = _actor(("*", "admin.super"), factory="MIL")
    denied_super_id, _ = _actor(
        ("*", "admin.super"),
        factory="MIL",
        policy={
            "ECO": {
                "deny": [
                    permission
                    for permission in tasks.PRODUCTION_READ_PERMISSIONS
                    if permission != "*"
                ]
            }
        },
    )
    with SessionLocal() as db:
        marker = uuid4().hex
        model_id = _model_id(db)
        order = ProductionOrder(
            production_no=f"TASK-USLUGA-{marker}",
            production_type="service_order",
            source_type="usluga",
            model_id=model_id,
            planned_quantity=1,
        )
        db.add(order)
        db.flush()
        bst = _department(db, "BST")
        work_order = WorkOrder(
            production_order_id=order.id,
            department_id=bst.id,
            operation="sewing",
        )
        bundle = Bundle(
            bundle_no=f"TASK-USLUGA-BUNDLE-{marker}",
            barcode=f"TASK-USLUGA-BC-{marker}",
            production_order_id=order.id,
            model_id=model_id,
            color="Black",
            size="M",
            quantity=1,
            sewing_factory_code="BST",
        )
        db.add_all([work_order, bundle])
        db.commit()
        restricted_references = (
            ("ProductionOrder", order.id),
            ("WorkOrder", work_order.id),
        )
        bundle_id = bundle.id

    for entity_type, entity_id in restricted_references:
        for headers in (mil_headers, bst_headers):
            denied = client.post(
                "/api/tasks",
                headers=headers,
                json={"title": "Wrong factory", "entity_type": entity_type, "entity_id": entity_id},
            )
            assert denied.status_code == 403, denied.text
        allowed = client.post(
            "/api/tasks",
            headers=eco_headers,
            json={"title": "Eco task", "entity_type": entity_type, "entity_id": entity_id},
        )
        assert allowed.status_code == 201, allowed.text

    super_eco_headers = {
        "Authorization": f"Bearer {create_access_token(super_id, {'factory_code': 'ECO'})}"
    }
    denied_super_eco_headers = {
        "Authorization": f"Bearer {create_access_token(denied_super_id, {'factory_code': 'ECO'})}"
    }
    production_order_id = restricted_references[0][1]
    assert client.get(
        f"/api/production-orders/{production_order_id}",
        headers=super_eco_headers,
    ).status_code == 200
    assert client.get(
        f"/api/production-orders/{production_order_id}",
        headers=denied_super_eco_headers,
    ).status_code == 403
    for recipient_id, expected in ((super_id, 201), (denied_super_id, 422)):
        assigned = client.post(
            "/api/tasks",
            headers=eco_headers,
            json={
                "title": "Super Admin Usluga access",
                "assigned_to": recipient_id,
                "entity_type": "ProductionOrder",
                "entity_id": production_order_id,
            },
        )
        assert assigned.status_code == expected, assigned.text

    for headers in (mil_headers, bst_headers, eco_headers):
        allowed = client.post(
            "/api/tasks",
            headers=headers,
            json={"title": "Bundle follows bundle detail", "entity_type": "Bundle", "entity_id": bundle_id},
        )
        assert allowed.status_code == 201, allowed.text


def test_manual_and_legacy_packages_use_packaging_ownership_not_production_parent(client):
    actor_id, mil_headers = _actor(("*",), factory="MIL", department="CUT")
    _, bst_headers = _actor(("*",), factory="BST", department="BST")
    _, office_headers = _actor(factory="MIL")
    secondary_id, _ = _actor(
        factory="MIL",
        extra=("factory:BST:packaging.packages",),
        department="CUT",
    )
    wrong_assignee_id, _ = _actor(factory="MIL", department="CUT")
    with SessionLocal() as db:
        marker = uuid4().hex
        model_id = _model_id(db)
        manual = ManualPackageReceipt(
            receipt_no=f"TASK-MANUAL-{marker}",
            created_by=actor_id,
            evidence={"source": "test"},
            evidence_hash="a" * 64,
        )
        legacy = LegacyStockReceipt(
            source_system="TEST",
            source_warehouse_id=f"WH-{marker}",
            source_record_id=f"ROW-{marker}",
            source_checksum="b" * 64,
            source_payload={"source": "test"},
            imported_by=actor_id,
        )
        db.add_all([manual, legacy])
        db.flush()
        manual_package = Package(
            package_no=f"TASK-MANUAL-PKG-{marker}",
            barcode=f"TASK-MANUAL-BC-{marker}",
            packaging_department_code="BPK",
            manual_receipt_id=manual.id,
            model_id=model_id,
            color="Black",
            total_quantity=1,
            capacity=1,
        )
        legacy_package = Package(
            package_no=f"TASK-LEGACY-PKG-{marker}",
            barcode=f"TASK-LEGACY-BC-{marker}",
            packaging_department_code="PKG",
            legacy_receipt_id=legacy.id,
            model_id=model_id,
            color="Black",
            total_quantity=1,
            capacity=1,
        )
        db.add_all([manual_package, legacy_package])
        db.commit()
        manual_id = manual_package.id
        legacy_id = legacy_package.id

    wrong = client.post(
        "/api/tasks",
        headers=mil_headers,
        json={"title": "Wrong package factory", "entity_type": "Package", "entity_id": manual_id},
    )
    assert wrong.status_code == 403, wrong.text
    assert client.post(
        "/api/tasks",
        headers=bst_headers,
        json={"title": "Manual package", "entity_type": "Package", "entity_id": manual_id},
    ).status_code == 201
    delegated = client.post(
        "/api/tasks",
        headers=bst_headers,
        json={
            "title": "Cross-factory package",
            "assigned_to": secondary_id,
            "entity_type": "Package",
            "entity_id": manual_id,
        },
    )
    assert delegated.status_code == 201, delegated.text
    wrong_assignee = client.post(
        "/api/tasks",
        headers=bst_headers,
        json={
            "title": "Wrong assignee factory",
            "assigned_to": wrong_assignee_id,
            "entity_type": "Package",
            "entity_id": manual_id,
        },
    )
    assert wrong_assignee.status_code == 422, wrong_assignee.text
    assert client.post(
        "/api/tasks",
        headers=office_headers,
        json={"title": "Office package access", "entity_type": "Package", "entity_id": manual_id},
    ).status_code == 201
    assert client.post(
        "/api/tasks",
        headers=mil_headers,
        json={"title": "Legacy package", "entity_type": "Package", "entity_id": legacy_id},
    ).status_code == 201


def test_assignee_must_have_target_permission_on_create_reassign_and_reference_change(client):
    manager_id, manager_headers = _actor(("tasks.manage", "finance.view"))
    allowed_id, _ = _actor(("finance.view",))
    denied_id, _ = _actor(
        ("finance.view",),
        policy={"MIL": {"deny": ["finance.view"]}},
    )
    scoped_id, _ = _actor(extra=("factory:BST:finance.view",))
    with SessionLocal() as db:
        order = SalesOrder(order_no=f"TASK-ASSIGN-{uuid4().hex}")
        db.add(order)
        db.flush()
        invoice = Invoice(
            sales_order_id=order.id,
            invoice_no=f"TASK-ASSIGN-INV-{uuid4().hex}",
            amount=1,
        )
        db.add(invoice)
        db.commit()
        invoice_id = invoice.id

    created = client.post(
        "/api/tasks",
        headers=manager_headers,
        json={
            "title": "Allowed assignment",
            "assigned_to": allowed_id,
            "entity_type": "Invoice",
            "entity_id": invoice_id,
        },
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]

    before_counts = _write_counts()
    before_task = _task_snapshot(task_id)
    denied_reassignment = client.patch(
        f"/api/tasks/{task_id}",
        headers=manager_headers,
        json={"assigned_to": denied_id},
    )
    assert denied_reassignment.status_code == 422, denied_reassignment.text
    assert _task_snapshot(task_id) == before_task
    assert _write_counts() == before_counts

    repeated_reference_reassignment = client.patch(
        f"/api/tasks/{task_id}",
        headers=manager_headers,
        json={
            "assigned_to": denied_id,
            "entity_type": "Invoice",
            "entity_id": invoice_id,
        },
    )
    assert repeated_reference_reassignment.status_code == 422, repeated_reference_reassignment.text
    assert _task_snapshot(task_id) == before_task
    assert _write_counts() == before_counts

    unreferenced = client.post(
        "/api/tasks",
        headers=manager_headers,
        json={"title": "No reference yet", "assigned_to": denied_id},
    )
    assert unreferenced.status_code == 201, unreferenced.text
    unreferenced_id = unreferenced.json()["id"]
    before_counts = _write_counts()
    before_task = _task_snapshot(unreferenced_id)
    denied_reference = client.patch(
        f"/api/tasks/{unreferenced_id}",
        headers=manager_headers,
        json={"entity_type": "Invoice", "entity_id": invoice_id},
    )
    assert denied_reference.status_code == 422, denied_reference.text
    assert _task_snapshot(unreferenced_id) == before_task
    assert _write_counts() == before_counts

    denied_create = client.post(
        "/api/tasks",
        headers=manager_headers,
        json={
            "title": "Denied assignment",
            "assigned_to": denied_id,
            "entity_type": "Invoice",
            "entity_id": invoice_id,
        },
    )
    assert denied_create.status_code == 422, denied_create.text
    assert _write_counts() == before_counts
    assert manager_id != allowed_id != denied_id

    scoped = client.post(
        "/api/tasks",
        headers=manager_headers,
        json={
            "title": "Secondary factory grant",
            "assigned_to": scoped_id,
            "entity_type": "Invoice",
            "entity_id": invoice_id,
        },
    )
    assert scoped.status_code == 201, scoped.text
    before_counts = _write_counts()

    with SessionLocal() as db:
        inactive = db.get(User, allowed_id)
        inactive.is_active = False
        db.commit()
    inactive_assignment = client.post(
        "/api/tasks",
        headers=manager_headers,
        json={
            "title": "Inactive assignment",
            "assigned_to": allowed_id,
            "entity_type": "Invoice",
            "entity_id": invoice_id,
        },
    )
    assert inactive_assignment.status_code == 422, inactive_assignment.text
    assert _write_counts() == before_counts


def test_legacy_missing_or_unsupported_reference_can_still_be_reassigned(client):
    manager_id, headers = _actor(("tasks.manage",))
    recipient_id, _ = _actor()
    with SessionLocal() as db:
        legacy_tasks = [
            Task(
                title="Unsupported legacy reference",
                created_by=manager_id,
                assigned_to=manager_id,
                status="pending",
                priority="medium",
                entity_type="RetiredThing",
                entity_id=123,
            ),
            Task(
                title="Deleted legacy reference",
                created_by=manager_id,
                assigned_to=manager_id,
                status="pending",
                priority="medium",
                entity_type="Work_Order",
                entity_id=2_000_000_000,
            ),
        ]
        db.add_all(legacy_tasks)
        db.commit()
        task_ids = [task.id for task in legacy_tasks]

    for task_id in task_ids:
        response = client.patch(
            f"/api/tasks/{task_id}",
            headers=headers,
            json={"assigned_to": recipient_id},
        )
        assert response.status_code == 200, response.text
        assert response.json()["assigned_to"] == recipient_id


def test_postgres_delete_winning_reference_race_rejects_task_without_writes(
    task_reference_postgres_sessions,
):
    sessions = task_reference_postgres_sessions
    marker = uuid4().hex
    with sessions.begin() as db:
        actor = User(
            name="Task race actor",
            email=f"task-race-{marker}@example.invalid",
            password_hash="unused",
            factory_code="MIL",
        )
        order = SalesOrder(order_no=f"TASK-RACE-{marker}")
        db.add_all([actor, order])
        db.flush()
        actor_id = actor.id
        order_id = order.id

    delete_db = sessions()
    target = (
        delete_db.query(SalesOrder)
        .filter(SalesOrder.id == order_id)
        .with_for_update()
        .one()
    )
    delete_db.delete(target)
    delete_db.flush()

    worker_ready = Event()
    worker_pid: dict[str, int] = {}

    def create_referenced_task():
        with sessions() as db:
            worker_pid["value"] = int(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            worker_ready.set()
            actor = db.get(User, actor_id)
            try:
                tasks.create_task(
                    TaskIn(
                        title="Losing reference race",
                        entity_type="SalesOrder",
                        entity_id=order_id,
                    ),
                    db,
                    actor,
                )
            except HTTPException as exc:
                db.rollback()
                return exc.status_code, exc.detail
            return 201, None

    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            creation = workers.submit(create_referenced_task)
            assert worker_ready.wait(5)
            deadline = time.monotonic() + 5
            lock_state = None
            with sessions() as observer:
                while time.monotonic() < deadline:
                    lock_state = observer.execute(
                        text(
                            "SELECT wait_event_type, pg_blocking_pids(pid) "
                            "FROM pg_stat_activity WHERE pid = :pid"
                        ),
                        {"pid": worker_pid["value"]},
                    ).one_or_none()
                    if lock_state and lock_state[0] == "Lock" and lock_state[1]:
                        break
                    time.sleep(0.01)
            assert lock_state is not None
            assert lock_state[0] == "Lock"
            assert lock_state[1]
            assert not creation.done()
            delete_db.commit()
            result = creation.result(timeout=15)
    finally:
        delete_db.close()

    assert result == (404, "Task reference target not found")
    with sessions() as db:
        assert db.get(SalesOrder, order_id) is None
        assert db.query(Task).filter(Task.title == "Losing reference race").count() == 0


def test_referenced_broadcast_rejects_mixed_access_without_partial_writes(client):
    manager_id, headers = _actor(("tasks.manage", "finance.view"))
    with SessionLocal() as db:
        db.query(User).filter(User.id != manager_id).update({"is_active": False}, synchronize_session=False)
        allowed_role = Role(name=f"Broadcast allowed {uuid4().hex}", permissions=["finance.view"])
        denied_role = Role(name=f"Broadcast denied {uuid4().hex}", permissions=[])
        allowed = User(
            name="Allowed broadcast recipient",
            email=f"broadcast-allowed-{uuid4().hex}@example.com",
            password_hash="unused",
            role=allowed_role,
            factory_code="MIL",
        )
        denied = User(
            name="Denied broadcast recipient",
            email=f"broadcast-denied-{uuid4().hex}@example.com",
            password_hash="unused",
            role=denied_role,
            factory_code="MIL",
        )
        order = SalesOrder(order_no=f"TASK-BROADCAST-{uuid4().hex}")
        db.add_all([allowed, denied, order])
        db.flush()
        invoice = Invoice(
            sales_order_id=order.id,
            invoice_no=f"TASK-BROADCAST-INV-{uuid4().hex}",
            amount=1,
        )
        db.add(invoice)
        db.commit()
        invoice_id = invoice.id

    before = _write_counts()
    response = client.post(
        "/api/tasks",
        headers=headers,
        json={
            "title": "Unsafe broadcast",
            "assigned_to": -1,
            "entity_type": "Invoice",
            "entity_id": invoice_id,
        },
    )
    assert response.status_code == 422, response.text
    assert response.json() == {
        "detail": "Task reference is not accessible to every broadcast recipient"
    }
    assert _write_counts() == before

    reference_free = client.post(
        "/api/tasks",
        headers=headers,
        json={"title": "Safe broadcast", "assigned_to": -1},
    )
    assert reference_free.status_code == 201, reference_free.text
    with SessionLocal() as db:
        assert db.query(Task).filter(Task.title == "Safe broadcast").count() == 3
