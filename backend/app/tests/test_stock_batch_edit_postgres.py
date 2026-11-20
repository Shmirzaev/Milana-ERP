"""Stock batch edit on an identity-pinned, disposable PostgreSQL database."""
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.libs.dto.inventory.stock_batch_update import StockBatchUpdate
from app.models.inventory import stock_service
from app.schemas import (AuditLog, Item, MaterialReservation, Model, ModelBOM,
                         ProductionOrder, Role, StockBatch, StockMovement, User,
                         Warehouse, WasteRecord)
from app.tests.pg_approved_instance import (ApprovedInstanceUnavailable, create_target_database,
    finalize_target, load_approved_instance, require_or_skip, target_engine)


@pytest.fixture(scope="module")
def pg_sessions():
    try:
        instance = load_approved_instance()
    except ApprovedInstanceUnavailable as error:
        require_or_skip(error)
    target = create_target_database(instance)
    engine = None
    sessions = sessionmaker(autoflush=False, expire_on_commit=False)
    try:
        engine = target_engine(target, options="-c statement_timeout=20000 -c lock_timeout=10000")
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(settings, "DATABASE_URL", engine.url.render_as_string(hide_password=False).replace("%", "%%"))
            patch.setattr(sa, "engine_from_config", lambda *args, **kwargs: engine)
            command.upgrade(Config(str(Path(__file__).resolve().parents[2] / "alembic.ini")), "head")
        sessions.configure(bind=engine)
        yield sessions
    finally:
        sessions.configure(bind=None)
        finalize_target(target, engine)


@pytest.fixture
def pg_batch(pg_sessions, monkeypatch):
    # Access policy has separate tests; this fixture isolates the edit transaction.
    monkeypatch.setattr(stock_service.inventory_access, "require_batch", lambda *args: None)
    monkeypatch.setattr(stock_service.inventory_access, "require_item", lambda *args: None)
    monkeypatch.setattr(stock_service, "_require_admin_force", lambda *args: None)
    suffix = uuid4().hex[:12]
    with pg_sessions.begin() as db:
        role = Role(name=f"pg-edit-{suffix}", permissions=[])
        warehouse = Warehouse(name=f"pg-edit-{suffix}", type="fabric_storage")
        source = Item(sku=f"source-{suffix}", name=f"source-{suffix}", category="fabric", unit="kg", is_active=True)
        target = Item(sku=f"target-{suffix}", name=f"target-{suffix}", category="fabric", unit="kg", is_active=True)
        model = Model(code=f"model-{suffix}", name="PG edit", status="approved")
        db.add_all([role, warehouse, source, target, model]); db.flush()
        user = User(name="PG edit", email=f"{suffix}@example.invalid", password_hash="unused", role_id=role.id, is_active=True)
        batch = StockBatch(item_id=source.id, batch_no=f"batch-{suffix}", quantity=10, unit="kg", warehouse_id=warehouse.id, qc_status="passed")
        order = ProductionOrder(production_no=f"order-{suffix}", production_type="branded_stock", model_id=model.id, planned_quantity=1)
        db.add_all([user, batch, order]); db.flush()
        movement = StockMovement(movement_type="receive", item_id=source.id, batch_id=batch.id,
            to_warehouse_id=warehouse.id, quantity=10, unit="kg", reference_type="StockBatch", reference_id=batch.id)
        reservation = MaterialReservation(reservation_no=f"reservation-{suffix}", production_order_id=order.id,
            item_id=source.id, stock_batch_id=batch.id, warehouse_id=warehouse.id, reserved_quantity=1,
            consumed_quantity=0, released_quantity=0, unit="kg", status="reserved", reservation_type="material", source="manual")
        bom = ModelBOM(model_id=model.id, item_id=source.id, stock_batch_id=batch.id, quantity_per_piece=1, unit="kg")
        waste = WasteRecord(item_id=source.id, batch_id=batch.id, waste_type="fabric", quantity=1, unit="kg")
        db.add_all([movement, reservation, bom, waste]); db.flush()
        return dict(user=user.id, batch=batch.id, source=source.id, target=target.id,
                    movement=movement.id, reservation=reservation.id, bom=bom.id, waste=waste.id)


def _assert_links(db, ids, item_id):
    for model, key in ((StockBatch, "batch"), (StockMovement, "movement"),
                       (MaterialReservation, "reservation"), (ModelBOM, "bom"), (WasteRecord, "waste")):
        assert db.get(model, ids[key]).item_id == item_id


def test_pg_relink_audit_failure_rolls_back_then_success(pg_sessions, pg_batch, monkeypatch):
    ids = pg_batch
    original_log = stock_service.log_action
    def fail_after_audit(db, *args, **kwargs):
        original_log(db, *args, **kwargs)
        db.flush()
        assert db.query(ModelBOM.item_id).filter_by(id=ids["bom"]).scalar() == ids["target"]
        assert db.query(WasteRecord.item_id).filter_by(id=ids["waste"]).scalar() == ids["target"]
        raise RuntimeError("injected audit failure")
    monkeypatch.setattr(stock_service, "log_action", fail_after_audit)
    with pg_sessions() as db:
        with pytest.raises(RuntimeError, match="injected audit failure"):
            stock_service.update_batch(db, ids["batch"], StockBatchUpdate(item_id=ids["target"]), db.get(User, ids["user"]), force=True)
        db.rollback()
    with pg_sessions() as db:
        _assert_links(db, ids, ids["source"])
        assert db.query(AuditLog).filter_by(entity_type="StockBatch", entity_id=ids["batch"]).count() == 0
    monkeypatch.setattr(stock_service, "log_action", original_log)
    with pg_sessions() as db:
        result = stock_service.update_batch(db, ids["batch"], StockBatchUpdate(item_id=ids["target"]), db.get(User, ids["user"]), force=True)
        assert result["item_id"] == ids["target"]
    with pg_sessions() as db:
        _assert_links(db, ids, ids["target"])
        assert db.query(AuditLog).filter_by(entity_type="StockBatch", entity_id=ids["batch"], action="update").count() == 1


def test_pg_simultaneous_batch_edits_serialize_without_lost_movement(pg_sessions, pg_batch):
    from concurrent.futures import ThreadPoolExecutor
    from queue import Queue
    from threading import Event
    from time import monotonic, sleep

    ids = pg_batch
    ready = Queue()
    start = Event()

    def edit(quantity):
        with pg_sessions() as db:
            actor = db.get(User, ids["user"])
            ready.put(db.scalar(sa.text("SELECT pg_backend_pid()")))
            assert start.wait(10)
            return stock_service.update_batch(db, ids["batch"], StockBatchUpdate(quantity=quantity), actor)["quantity"]

    with pg_sessions() as holder, ThreadPoolExecutor(max_workers=2) as workers:
        holder.execute(sa.select(StockBatch.id).where(StockBatch.id == ids["batch"]).with_for_update()).scalar_one()
        futures = [workers.submit(edit, quantity) for quantity in (11, 12)]
        pids = [ready.get(timeout=10) for _ in futures]
        start.set()
        try:
            deadline = monotonic() + 8
            waiting = False
            while monotonic() < deadline:
                waiting = all(holder.scalar(sa.text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid}) for pid in pids)
                if waiting:
                    break
                sleep(0.02)
            assert waiting, "Both batch edits must wait for the held row lock"
        finally:
            holder.rollback()
        results = [future.result(timeout=15) for future in futures]
    # Refresh runs after commit; the other edit may already be visible.
    assert all(float(value) in (11, 12) for value in results)
    with pg_sessions() as db:
        saved = db.get(StockBatch, ids["batch"])
        movements = db.query(StockMovement).filter_by(batch_id=ids["batch"], reference_type="StockBatchAdjustment").all()
        assert len(movements) == 2
        signed_delta = sum(float(row.quantity) * (1 if row.movement_type == "adjustment" else -1) for row in movements)
        assert signed_delta == float(saved.quantity) - 10
        assert db.query(AuditLog).filter_by(entity_type="StockBatch", entity_id=ids["batch"], action="update").count() == 2
