"""Real PostgreSQL evidence for the movement and reservation writers.

The suite only runs against this worker's own disposable database on the
identity-pinned instance. Every connection is checked against the pinned
identity before the schema is used.
"""
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.libs.enums.inventory import (
    MaterialReservationSource,
    MaterialReservationStatus,
    MaterialReservationType,
    StockMovementType,
)
from app.models.inventory import transfers_service
from app.models.idempotency_service import bind_idempotency_identity
from app.schemas import AuditLog, Item, Role, StockBatch, StockMovement, User, Warehouse
from app.schemas.inventory import stock_movement_persistence
from app.tests.pg_approved_instance import (
    ApprovedInstanceUnavailable, create_target_database, finalize_target,
    load_approved_instance, require_or_skip, target_engine,
)


@pytest.fixture
def pg_engine():
    """Migrate a fresh owned database using only its identity-checked engine."""
    try:
        instance = load_approved_instance()
    except ApprovedInstanceUnavailable as error:
        require_or_skip(error)
    target = create_target_database(instance)
    engine = None
    try:
        engine = target_engine(target, options="-cstatement_timeout=20000 -clock_timeout=10000")
        from app.core.config import settings
        with pytest.MonkeyPatch.context() as patch:
            # Alembic's ConfigParser interpolates percent signs in URL escapes.
            url_for_config = engine.url.render_as_string(hide_password=False).replace("%", "%%")
            patch.setattr(settings, "DATABASE_URL", url_for_config)
            patch.setattr(sa, "engine_from_config", lambda *args, **kwargs: engine)
            config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
            command.upgrade(config, "head")
        yield engine
    finally:
        finalize_target(target, engine)


@pytest.fixture
def pg(pg_engine):
    return sessionmaker(bind=pg_engine, expire_on_commit=False)


@pytest.fixture
def stock(pg):
    marker = uuid4().hex[:8]
    with pg() as db:
        role = Role(name=f"Super Admin {marker}", permissions=["*"])
        db.add(role)
        db.flush()
        user = User(name=f"Movement QA {marker}", email=f"move-{marker}@example.test",
                    password_hash="unused", role_id=role.id)
        item = Item(sku=f"MOVE-{marker}", name="Movement fabric", category="fabric", unit="kg")
        source = Warehouse(name=f"Source {marker}", type="fabric_storage")
        destination = Warehouse(name=f"Destination {marker}", type="fabric_storage")
        db.add_all([user, item, source, destination])
        db.flush()
        batch = StockBatch(item_id=item.id, batch_no=f"MOVE-{marker}", warehouse_id=source.id,
                           quantity=10, unit="kg", qc_status="passed")
        db.add(batch)
        db.commit()
        ids = {
            "user": user.id, "item": item.id, "batch": batch.id,
            "source": source.id, "destination": destination.id,
        }
    yield ids


def _check_definitions(engine, table: str) -> dict[str, str]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = CAST(:table AS regclass) AND contype = 'c'"
            ),
            {"table": table},
        ).all()
    return {name: definition for name, definition in rows}


def test_postgres_constraints_match_the_canonical_vocabularies(pg_engine):
    definitions = _check_definitions(pg_engine, "stock_movements")
    movement = definitions["ck_stock_movements_type"]
    for member in StockMovementType:
        assert f"'{member.value}'" in movement, movement

    definitions = _check_definitions(pg_engine, "material_reservations")
    for name, members in (
        ("ck_material_reservations_status", MaterialReservationStatus),
        ("ck_material_reservations_type", MaterialReservationType),
        ("ck_material_reservations_source", MaterialReservationSource),
    ):
        definition = definitions[name]
        for member in members:
            assert f"'{member.value}'" in definition, (name, definition)


def test_schema_writers_store_values_postgres_accepts(pg, stock):
    with pg() as db:
        movement = stock_movement_persistence.insert_stock_movement(
            db,
            movement_type=StockMovementType.ISSUE,
            item_id=stock["item"],
            batch_id=stock["batch"],
            from_warehouse_id=stock["source"],
            to_warehouse_id=None,
            quantity=2,
            unit="kg",
            reference_type=None,
            reference_id=None,
            created_by=stock["user"],
        )
        assert movement.movement_type == "issue"
        db.flush()
        stored = db.execute(
            text("SELECT movement_type FROM stock_movements WHERE id = :id"), {"id": movement.id}
        ).scalar()
        assert stored == "issue"
        assert isinstance(stored, str)
        db.rollback()


def test_transfer_conserves_quantity_and_moves_the_batch_location(pg, stock):
    from app.libs.dto.inventory.stock_movement_input import StockMovementIn

    with pg() as db:
        actor = db.get(User, stock["user"])
        response = transfers_service.transfer_stock(
            db,
            StockMovementIn(
                movement_type="transfer", item_id=stock["item"], batch_id=stock["batch"],
                from_warehouse_id=stock["source"], to_warehouse_id=stock["destination"],
                quantity=10, unit="kg",
            ),
            actor,
        )
        assert response.movement_type == StockMovementType.TRANSFER
        db.refresh(db.get(StockBatch, stock["batch"]))
        batch = db.get(StockBatch, stock["batch"])
        assert float(batch.quantity) == 10
        assert batch.warehouse_id == stock["destination"]
        movements = db.query(StockMovement).filter_by(batch_id=stock["batch"]).all()
        assert [row.movement_type for row in movements] == ["transfer"]
        assert db.query(AuditLog).filter_by(entity_type="StockMovement").count() >= 1
        db.rollback()


def test_failed_audit_leaves_no_movement_and_no_batch_change(pg, stock, monkeypatch):
    from app.libs.dto.inventory.stock_movement_input import StockMovementIn
    import app.models.inventory.transfers_service as transfers

    def boom(*args, **kwargs):
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(transfers, "log_action", boom)
    with pg() as db:
        actor = db.get(User, stock["user"])
        with pytest.raises(RuntimeError):
            transfers_service.transfer_stock(
                db,
                StockMovementIn(
                    movement_type="issue", item_id=stock["item"], batch_id=stock["batch"],
                    from_warehouse_id=stock["source"], quantity=2, unit="kg",
                ),
                actor,
            )
        db.rollback()
    with pg() as db:
        assert db.query(StockMovement).filter_by(batch_id=stock["batch"]).count() == 0
        batch = db.get(StockBatch, stock["batch"])
        assert float(batch.quantity) == 10
        assert batch.warehouse_id == stock["source"]


def test_retry_with_the_same_key_replays_without_a_second_movement(pg, stock):
    from app.libs.dto.inventory.stock_movement_input import StockMovementIn

    key = f"movement-{uuid4().hex}"
    with pg() as db:
        actor = db.get(User, stock["user"])
        bind_idempotency_identity(db, actor)
        payload = StockMovementIn(
            movement_type="issue", item_id=stock["item"], batch_id=stock["batch"],
            from_warehouse_id=stock["source"], quantity=1, unit="kg",
        )
        first = transfers_service.transfer_stock(db, payload, actor, idempotency_key=key)
        assert first.movement_type == StockMovementType.ISSUE
        replay = transfers_service.transfer_stock(db, payload, actor, idempotency_key=key)
        assert replay == first
        assert db.query(StockMovement).filter_by(batch_id=stock["batch"]).count() == 1
        db.rollback()


def _create_adjustment_item(db, *, marker: str) -> Item:
    item = Item(
        sku=f"ADJ-PG-{marker}",
        name=f"Adjustment persistence {marker}",
        category="fabric",
        unit="kg",
        default_cost=2.125,
        track_batch=True,
        is_active=True,
    )
    db.add(item)
    db.commit()
    return item


def test_batch_stock_adjustment_increase_and_depletion_persist_postgres(pg, stock):
    """Run the real service on PostgreSQL and read back committed batch, ledger, and audit rows."""
    from app.libs.dto.inventory.stock_quantity_adjustment_input import StockQuantityAdjustmentIn
    from app.models.inventory import stock_service

    marker = uuid4().hex[:8].upper()
    with pg() as db:
        actor = db.get(User, stock["user"])
        item = _create_adjustment_item(db, marker=marker)
        item_id = item.id
        increase = stock_service.set_stock_quantity(
            db, item_id, StockQuantityAdjustmentIn(quantity=5, unit="kg"), actor
        )
        assert increase.movement_type == StockMovementType.ADJUSTMENT
        increase_movement_id = increase.movement_id

    with pg() as db:
        batch = db.query(StockBatch).filter_by(item_id=item_id).one()
        movement = db.get(StockMovement, increase_movement_id)
        assert movement is not None
        batch_id = batch.id
        warehouse_id = batch.warehouse_id
        assert float(batch.quantity) == 5
        assert batch.qc_status == "passed"
        assert batch.archived_at is None
        assert movement.batch_id == batch_id
        assert movement.from_warehouse_id is None
        assert movement.to_warehouse_id == warehouse_id
        assert movement.movement_type == "adjustment"
        assert movement.reference_type == "StockAdjustment"
        assert float(movement.quantity) == 5
        assert db.query(AuditLog).filter_by(entity_type="Item", entity_id=item_id).count() == 1

    with pg() as db:
        actor = db.get(User, stock["user"])
        decrease = stock_service.set_stock_quantity(
            db, item_id, StockQuantityAdjustmentIn(quantity=0, unit="kg"), actor
        )
        assert decrease.movement_type == StockMovementType.ISSUE
        decrease_movement_id = decrease.movement_id

    with pg() as db:
        batch = db.get(StockBatch, batch_id)
        movement = db.get(StockMovement, decrease_movement_id)
        assert float(batch.quantity) == 0
        assert batch.archived_at is not None
        assert batch.archived_by == stock["user"]
        assert movement.batch_id == batch_id
        assert movement.from_warehouse_id == warehouse_id
        assert movement.to_warehouse_id is None
        assert movement.movement_type == "issue"
        assert movement.reference_type == "StockAdjustment"
        assert float(movement.quantity) == 5
        assert db.query(AuditLog).filter_by(entity_type="Item", entity_id=item_id).count() == 2


def test_batch_stock_adjustment_audit_failure_rolls_back_postgres(pg, stock, monkeypatch):
    """An audit failure after batch/movement flush leaves no committed partial adjustment."""
    from app.libs.dto.inventory.stock_quantity_adjustment_input import StockQuantityAdjustmentIn
    from app.models.inventory import stock_service

    marker = uuid4().hex[:8].upper()
    with pg() as db:
        item = _create_adjustment_item(db, marker=marker)
        item_id = item.id
        audit_before = db.query(AuditLog).filter_by(entity_type="Item", entity_id=item_id).count()

    def fail_audit(*args, **kwargs):
        raise RuntimeError("injected adjustment audit failure")

    monkeypatch.setattr(stock_service, "log_action", fail_audit)
    with pg() as db:
        actor = db.get(User, stock["user"])
        with pytest.raises(RuntimeError, match="injected adjustment audit failure"):
            stock_service.set_stock_quantity(
                db, item_id, StockQuantityAdjustmentIn(quantity=5, unit="kg"), actor
            )
        db.rollback()

    with pg() as db:
        assert db.query(StockBatch).filter_by(item_id=item_id).count() == 0
        assert db.query(StockMovement).filter_by(
            item_id=item_id, reference_type="StockAdjustment",
        ).count() == 0
        assert db.query(AuditLog).filter_by(entity_type="Item", entity_id=item_id).count() == audit_before
