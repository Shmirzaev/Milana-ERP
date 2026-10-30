"""Real PostgreSQL checks on an identity-pinned disposable target only."""
from pathlib import Path
from queue import Queue
from concurrent.futures import ThreadPoolExecutor
import time
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api.routes import production as production_route
from app.api.routes import usluga as usluga_route
from app.core.config import settings
from app.core.deps import get_current_user, get_db
from app.libs.dto.production.production import ProductionOrderIn
from app.api.routes.usluga import UslugaOrderIn
from app.models.planning import production_planning_service as service
from app.libs.enums.production import ProductionSourceType, ProductionType
from app.models import production_service as production
from app.models import numbering_service
from app.schemas import (
    AuditLog, BrandedPlanningOrder, Department, Item, MaterialReservation, Model, ModelSize, Role,
    Notification, ProductionBatch, ProductionOrder, ProductionOrderItem,
    ProductionOrderMaterial, SalesOrder, StockBatch, User, Warehouse, WorkOrder,
)
from app.tests.pg_approved_instance import (
    ApprovedInstanceUnavailable, create_target_database, finalize_target, load_approved_instance,
    owned_target_name, preflight_connection, require_or_skip, target_engine,
)


@pytest.fixture(scope="module")
def sessions():
    test_path = Path(__file__).resolve()
    backend = test_path.parents[2]
    if test_path.parent.name != "tests" or test_path.parent.parent.name != "app":
        raise RuntimeError("Place test under backend/app/tests before execution")
    alembic_ini = backend / "alembic.ini"
    if not alembic_ini.is_file():
        raise RuntimeError("Candidate backend/alembic.ini not found")
    try:
        instance = load_approved_instance()
    except ApprovedInstanceUnavailable as error:
        require_or_skip(error)
    target = create_target_database(instance)
    target_name = owned_target_name(target)
    engine = None
    factory = sessionmaker(autoflush=False, expire_on_commit=False)
    try:
        engine = target_engine(target, options="-c statement_timeout=20000 -c lock_timeout=10000")
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(settings, "DATABASE_URL", engine.url.render_as_string(hide_password=False).replace("%", "%%"))
            patch.setattr(sa, "engine_from_config", lambda *args, **kwargs: engine)
            command.upgrade(Config(str(alembic_ini)), "head")
        factory.configure(bind=engine)
        yield factory
    finally:
        factory.configure(bind=None)
        finalize_target(target, engine)
        admin = sa.create_engine(instance.admin_url, connect_args={"connect_timeout": 5}, future=True)
        try:
            with admin.connect() as connection:
                connection.execute(sa.text("SET TRANSACTION READ ONLY"))
                preflight_connection(connection, instance, "postgres")
                exists = connection.execute(sa.text("SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = :name)"),
                                            {"name": target_name}).scalar_one()
                if exists:
                    raise RuntimeError("owned test database still exists after cleanup")
        finally:
            admin.dispose()


@pytest.fixture
def seed(sessions):
    marker = uuid4().hex
    with sessions() as db:
        for code in ("CUT", "MIL", "PKG", "FGS", "PRT", "ECT", "ECO", "ECP"):
            if not db.query(Department).filter_by(code=code).first():
                db.add(Department(code=code, name=f"Synthetic {code}"))
        actor = User(name="Synthetic planning actor", email=f"planning-{marker}@example.test", password_hash="unused")
        model = Model(code=f"PLANNING-{marker}", name="Synthetic planning model", status="approved")
        db.add_all([actor, model]); db.commit()
        return actor.id, model.id


def payload(model_id, **kwargs):
    values = {
        "production_type": ProductionType.BRANDED_STOCK,
        "model_id": model_id,
        "planned_quantity": 20,
        "items": [{"model_id": model_id, "color": "white", "size": "M", "planned_quantity": 20}],
        "batches": [{"planned_quantity": 20}],
    }
    values.update(kwargs)
    return ProductionOrderIn(**values)


def counts(db):
    return tuple(db.query(cls).count() for cls in (
        BrandedPlanningOrder, ProductionOrder, ProductionOrderItem,
        ProductionOrderMaterial, ProductionBatch, WorkOrder, MaterialReservation,
        Notification, AuditLog,
    ))


def test_pg_alternate_create_and_existing_order_handoff(sessions, seed, monkeypatch):
    actor_id, model_id = seed
    with sessions() as db:
        before = counts(db)
        commit_calls = []
        commit = db.commit

        def counted_commit():
            commit_calls.append(None)
            return commit()

        monkeypatch.setattr(db, "commit", counted_commit)
        po = service.create_branded_stock_production(db, payload(model_id), db.get(User, actor_id))
        po_id, order_id = po.id, po.planning_order_id
        assert commit_calls == [None]
        assert po in db and db.get(ProductionOrder, po_id) is po
    with sessions() as db:
        po, order = db.get(ProductionOrder, po_id), db.get(BrandedPlanningOrder, order_id)
        assert (order.ordered_for_type, order.ordered_for_name, order.status, order.customer_id, order.notes) == (
            "milana", "Milana", "open", None, None)
        assert po.planning_order_id == order.id
        assert len(po.items) == 1 and po.items[0].model_id == model_id and po.items[0].planned_quantity == 20
        assert len(po.batches) == 1 and po.batches[0].production_order_id == po_id
        assert (po.production_type, po.source_type, po.status, po.planned_quantity) == (
            "branded_stock", "standard", "planning", 20,
        )
        assert po.materials == []
        assert len(po.batches) == 1 and (
            po.batches[0].batch_no,
            po.batches[0].batch_index,
            po.batches[0].name,
            po.batches[0].planned_quantity,
        ) == (f"{po_id:04d}-01", 1, "Nastil 1", 20)
        assert {wo.operation for wo in po.work_orders} == {
            "cutting", "sewing", "packaging", "storage_transfer",
        }
        assert all(
            (wo.status, wo.planned_input_qty, wo.planned_output_qty, wo.production_batch_id)
            == ("waiting", 20, 20, None)
            for wo in po.work_orders
        )
        audit = db.query(AuditLog).filter_by(
            entity_type="ProductionOrder", entity_id=po_id, action="create",
        ).one()
        assert audit.user_id == actor_id
        assert audit.new_value_json == {
            "production_no": po.production_no,
            "type": "branded_stock",
            "planning_order_no": order.order_no,
            "sewing_factory_code": None,
        }
        assert db.query(AuditLog).filter_by(entity_type="BrandedPlanningOrder", entity_id=order_id, action="create").count() == 0
        after = counts(db)
        assert tuple(after_value - before_value for before_value, after_value in zip(before, after)) == (
            1, 1, 1, 0, 1, 4, 0, 0, 1,
        )
        existing = BrandedPlanningOrder(order_no=f"EXISTING-{uuid4().hex}", ordered_for_type="eco_cotton",
                                       ordered_for_name="Eco Cotton", status="open", notes="preserve")
        db.add(existing); db.commit(); existing_id = existing.id
    with sessions() as db:
        before = db.query(BrandedPlanningOrder).count()
        po = service.create_branded_stock_production(db, payload(model_id, planning_order_id=existing_id), db.get(User, actor_id))
        second_id = po.id
        assert db.query(BrandedPlanningOrder).count() == before
    with sessions() as db:
        existing = db.get(BrandedPlanningOrder, existing_id)
        assert (existing.ordered_for_type, existing.ordered_for_name, existing.status, existing.notes) == (
            "eco_cotton", "Eco Cotton", "open", "preserve")
        assert db.get(ProductionOrder, second_id).planning_order_id == existing_id


def test_pg_alternate_optional_material_printing_and_full_children(sessions, seed):
    actor_id, model_id = seed
    marker = uuid4().hex
    with sessions() as db:
        item = Item(sku=f"FABRIC-{marker}", name="Fixture fabric", category="fabric", unit="kg")
        warehouse = Warehouse(name=f"Fixture raw {marker}", type="raw_material")
        db.add_all([item, warehouse])
        db.flush()
        batch = StockBatch(
            item_id=item.id,
            batch_no=f"BATCH-{marker}",
            quantity=50,
            unit="kg",
            warehouse_id=warehouse.id,
        )
        db.add(batch)
        db.commit()
        stock_batch_id = batch.id

    with sessions() as db:
        before = counts(db)
        po = service.create_branded_stock_production(
            db,
            payload(
                model_id,
                items=[{
                    "model_id": model_id,
                    "color": "white",
                    "size": "M",
                    "planned_quantity": 20,
                    "printing_required": True,
                }],
                materials=[{
                    "stock_batch_id": stock_batch_id,
                    "estimated_quantity": 1.25,
                    "unit": "kg",
                }],
                printing_instructions="Print front logo",
                printing_attachments=[{
                    "file_url": "/uploads/fixture-logo.png?signature=discard-me",
                    "file_name": "fixture-logo.png",
                    "content_type": "image/png",
                }],
            ),
            db.get(User, actor_id),
        )
        po_id = po.id

    with sessions() as db:
        po = db.get(ProductionOrder, po_id)
        material = db.query(ProductionOrderMaterial).filter_by(production_order_id=po_id).one()
        assert (
            material.stock_batch_id,
            float(material.estimated_quantity),
            material.unit,
            material.position,
        ) == (stock_batch_id, 1.25, "kg", 1)
        assert po.fabric_batch_id == stock_batch_id
        assert (po.estimated_material_code, float(po.estimated_material_amount), po.estimated_material_unit) == (
            f"FABRIC-{marker}", 1.25, "kg",
        )
        assert po.printing_instructions == "Print front logo"
        assert po.printing_attachments == [{
            "file_url": "/uploads/fixture-logo.png",
            "file_name": "fixture-logo.png",
            "content_type": "image/png",
        }]
        assert len(po.items) == 1 and po.items[0].printing_required is True
        assert {wo.operation for wo in po.work_orders} == {
            "cutting", "printing", "sewing", "packaging", "storage_transfer",
        }
        after = counts(db)
        assert tuple(after_value - before_value for before_value, after_value in zip(before, after)) == (
            1, 1, 1, 1, 1, 5, 0, 0, 1,
        )


def test_pg_shared_production_writer_keeps_client_general_and_usluga_callers(sessions, seed):
    actor_id, model_id = seed
    with sessions() as db:
        actor = db.get(User, actor_id)
        sales_order = SalesOrder(
            order_no=f"SO-{uuid4().hex}",
            status="confirmed",
            created_by=actor_id,
        )
        db.add(sales_order)
        db.commit()
        sales_order_id = sales_order.id

    with sessions() as db:
        actor = db.get(User, actor_id)
        client_order = service.create_client_order_production(
            db,
            payload(
                model_id,
                production_type=ProductionType.CLIENT_ORDER,
                sales_order_id=sales_order_id,
                batches=[],
            ),
            actor,
        )
        assert client_order.production_type == ProductionType.CLIENT_ORDER.value
        assert client_order.sales_order_id == sales_order_id
        client_order_id = client_order.id

    with sessions() as db:
        client_order = db.get(ProductionOrder, client_order_id)
        sales_order = db.get(SalesOrder, sales_order_id)
        assert client_order.source_type == ProductionSourceType.STANDARD.value
        assert sales_order.status == "planning"

    with sessions() as db:
        general = production_route.create_po(payload(model_id), db, db.get(User, actor_id))
        assert general.production_type == ProductionType.BRANDED_STOCK.value
        assert general.planning_order_id is None
        general_id = general.id

    with sessions() as db:
        assert db.get(ProductionOrder, general_id).planning_order_id is None
    with sessions() as db:
        usluga_model = Model(
            code=f"USLUGA-{uuid4().hex}",
            name="Fixture Usluga model",
            status="approved",
            catalog_scope="usluga",
            factory_code="ECO",
        )
        usluga_model.sizes.append(ModelSize(size="40-42"))
        usluga_role = Role(
            name=f"Synthetic Usluga manage {uuid4().hex}",
            permissions=["usluga.manage"],
        )
        usluga_actor = User(
            name="Synthetic Usluga actor",
            email=f"usluga-{uuid4().hex}@example.test",
            password_hash="unused",
            factory_code="ECO",
            role=usluga_role,
        )
        db.add_all([usluga_model, usluga_actor])
        db.flush()
        db.commit()

    app = FastAPI()
    app.include_router(usluga_route.router, prefix="/api")

    def isolated_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = isolated_db
    app.dependency_overrides[get_current_user] = lambda: usluga_actor
    usluga_payload = UslugaOrderIn(
        customer_name="Fixture customer",
        model_id=usluga_model.id,
        lines=[{"color": "Natural", "size": "40-42", "quantity": 3}],
        material_usage_kg=0.75,
    ).model_dump(mode="json")
    with TestClient(app) as client:
        response = client.post("/api/usluga/orders", json=usluga_payload)
    assert response.status_code == 201, response.text
    usluga_id = response.json()["id"]
    assert response.json()["order_no"].startswith("USL-")

    with sessions() as db:
        usluga_order = db.get(ProductionOrder, usluga_id)
        assert (usluga_order.production_no.startswith("USL-"), usluga_order.production_type,
                usluga_order.source_type, usluga_order.planned_quantity) == (
            True, ProductionType.SERVICE_ORDER.value, ProductionSourceType.USLUGA.value, 3,
        )
        assert len(usluga_order.items) == 1 and usluga_order.items[0].size == "40-42"
        assert usluga_order.materials == []
        assert {row.operation for row in usluga_order.work_orders} == {
            "cutting", "sewing", "packaging",
        }


@pytest.mark.parametrize("case,code", [("closed", 400), ("missing", 404)])
def test_pg_alternate_missing_and_closed_orders_refused(sessions, seed, case, code):
    actor_id, model_id = seed
    with sessions() as db:
        row = BrandedPlanningOrder(order_no=f"CLOSED-{uuid4().hex}", ordered_for_type="milana",
                                   ordered_for_name="Milana", status="closed")
        db.add(row); db.commit(); closed_id = row.id
        before = counts(db)
    order_id = closed_id if case == "closed" else 2147483647
    with sessions() as db:
        with pytest.raises(HTTPException) as failure:
            service.create_branded_stock_production(db, payload(model_id, planning_order_id=order_id), db.get(User, actor_id))
        assert failure.value.status_code == code
        db.rollback()
    with sessions() as db:
        assert counts(db) == before


@pytest.mark.parametrize("hook", [
    "insert_branded_planning_order",
    "insert_production_order",
    "insert_production_order_components",
    "persist_production_batches",
    "add_work_orders",
    "apply_initial_production_workflow_state",
    "log_action",
])
def test_pg_alternate_postflush_and_audit_failure_rollback_retry(sessions, seed, monkeypatch, hook):
    actor_id, model_id = seed
    owner = service if hook in {"insert_branded_planning_order", "log_action"} else production
    original = getattr(owner, hook)

    def fail_after_write(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected after participant write")

    with sessions() as db:
        before = counts(db)
        with monkeypatch.context() as patch:
            patch.setattr(owner, hook, fail_after_write)
            with pytest.raises(RuntimeError, match="injected after participant write"):
                service.create_branded_stock_production(db, payload(model_id), db.get(User, actor_id))
        db.rollback()
        assert counts(db) == before
        po = service.create_branded_stock_production(db, payload(model_id), db.get(User, actor_id))
        po_id = po.id
        assert po in db and db.get(ProductionOrder, po_id) is po
        after = counts(db)
        assert tuple(after_value - before_value for before_value, after_value in zip(before, after)) == (
            1, 1, 1, 0, 1, 4, 0, 0, 1,
        )
        assert db.get(ProductionOrder, po_id).planning_order_id is not None


def test_pg_alternate_commit_failure_rolls_back_audit_and_retries_same_session(sessions, seed, monkeypatch):
    actor_id, model_id = seed
    with sessions() as db:
        before = counts(db)
        real_commit = db.commit

        def fail_before_commit():
            raise RuntimeError("injected outer commit failure")

        with monkeypatch.context() as patch:
            patch.setattr(db, "commit", fail_before_commit)
            with pytest.raises(RuntimeError, match="outer commit failure"):
                service.create_branded_stock_production(db, payload(model_id), db.get(User, actor_id))
        db.rollback()
        assert counts(db) == before
        po = service.create_branded_stock_production(db, payload(model_id), db.get(User, actor_id))
        assert db.get(ProductionOrder, po.id) is po
        after = counts(db)
        assert tuple(after_value - before_value for before_value, after_value in zip(before, after)) == (
            1, 1, 1, 0, 1, 4, 0, 0, 1,
        )


def test_pg_alternate_concurrent_implicit_orders_witness_number_lock_chain(sessions, seed):
    actor_id, model_id = seed
    ready: Queue[int] = Queue()

    def create_one():
        with sessions() as db:
            actor = db.get(User, actor_id)
            pid = db.execute(sa.text("SELECT pg_backend_pid()")).scalar_one()
            ready.put(int(pid))
            order = service.create_branded_stock_production(db, payload(model_id), actor)
            return order.production_no, order.planning_order.order_no

    def blocker_snapshot(observer, pid):
        graph = {}
        pending = [pid]
        while pending:
            current = pending.pop(0)
            if current in graph:
                continue
            blockers = observer.execute(
                sa.text("SELECT pg_blocking_pids(:pid)"), {"pid": current},
            ).scalar_one()
            graph[current] = sorted(int(blocker) for blocker in (blockers or []))
            pending.extend(blocker for blocker in graph[current] if blocker not in graph)
        return graph

    def reaches_holder(graph, worker_pid, holder_pid):
        visited = set()
        pending = list(graph.get(worker_pid, []))
        while pending:
            blocker = pending.pop()
            if blocker == holder_pid:
                return True
            if blocker not in visited:
                visited.add(blocker)
                pending.extend(graph.get(blocker, []))
        return False

    with sessions() as holder:
        resource = "production_orders:production_no:PO:compact"
        numbering_service._acquire_numbering_lock(holder, resource)
        holder_pid = int(holder.execute(sa.text("SELECT pg_backend_pid()")).scalar_one())
        expected_hash = int(holder.execute(
            sa.text("SELECT hashtext(:resource)"), {"resource": resource},
        ).scalar_one()) & 0xFFFFFFFF
        held_locks = [dict(row) for row in holder.execute(sa.text(
            "SELECT classid::bigint AS classid, objid::bigint AS objid, objsubid, mode, granted "
            "FROM pg_locks WHERE pid = :pid AND locktype = 'advisory' AND granted ORDER BY classid, objid"
        ), {"pid": holder_pid}).mappings().all()]
        assert any(
            row["classid"] == numbering_service._NUMBERING_LOCK_NAMESPACE
            and row["objid"] == expected_hash
            and row["objsubid"] == 2
            and row["mode"] == "ExclusiveLock"
            for row in held_locks
        ), {"holder_pid": holder_pid, "resource": resource, "expected_hash": expected_hash,
            "held_advisory_locks": held_locks}
        before = counts(holder)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(create_one) for _ in range(2)]
            try:
                worker_pids = [ready.get(timeout=10) for _ in futures]
                deadline = time.monotonic() + 5
                last_snapshot = {}
                while time.monotonic() < deadline:
                    last_snapshot = {
                        pid: {
                            "blocker_graph": blocker_snapshot(holder, pid),
                            "activity": dict(holder.execute(sa.text(
                                "SELECT wait_event_type, wait_event, state FROM pg_stat_activity WHERE pid = :pid"
                            ), {"pid": pid}).mappings().one()),
                        }
                        for pid in worker_pids
                    }
                    if all(
                        reaches_holder(snapshot["blocker_graph"], pid, holder_pid)
                        and snapshot["activity"]["wait_event_type"] == "Lock"
                        and snapshot["activity"]["wait_event"] == "advisory"
                        for pid, snapshot in last_snapshot.items()
                    ):
                        break
                    time.sleep(0.05)
                assert len(worker_pids) == 2 and len(set(worker_pids)) == 2
                assert set(last_snapshot) == set(worker_pids)
                assert all(
                    reaches_holder(snapshot["blocker_graph"], pid, holder_pid)
                    and snapshot["activity"]["wait_event_type"] == "Lock"
                    and snapshot["activity"]["wait_event"] == "advisory"
                    for pid, snapshot in last_snapshot.items()
                ), {
                    "holder_pid": holder_pid,
                    "held_lock_identity": {
                        "classid": numbering_service._NUMBERING_LOCK_NAMESPACE,
                        "objid": expected_hash,
                        "objsubid": 2,
                    },
                    "worker_snapshots": last_snapshot,
                }
            finally:
                holder.rollback()
            created = [future.result(timeout=20) for future in futures]
        assert len(set(created)) == 2

    with sessions() as db:
        after = counts(db)
        assert tuple(after_value - before_value for before_value, after_value in zip(before, after)) == (
            2, 2, 2, 0, 2, 8, 0, 0, 2,
        )
