"""Real PostgreSQL evidence for the movement and reservation writers.

The suite only runs against this worker's own disposable database on the
identity-pinned instance. Every connection is checked against the pinned
identity before the schema is used.
"""
import os
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.libs.enums.inventory import (
    MaterialReservationSource,
    MaterialReservationStatus,
    MaterialReservationType,
    StockMovementType,
)
from app.models.inventory import transfers_service
from app.schemas import AuditLog, Item, Role, StockBatch, StockMovement, User, Warehouse
from app.schemas.inventory import material_reservation_persistence, stock_movement_persistence
from app.tests.test_fresh_migration_bootstrap import postgres_migrations  # noqa: F401

PINNED_HOST = "127.0.0.1"
PINNED_PORT = 51716
PINNED_VERSION = "PostgreSQL 17.11"
PINNED_SYSTEM_IDENTIFIER = "7700371345869473300"
PINNED_DATA_DIRECTORY_SUFFIX = "work/finance-visual-qa-5aafe01d69/data"
OWNED_DATABASE = os.environ.get("REVIEW_MM_INVENTORY_DATABASE", "")


@pytest.fixture(autouse=True)
def _the_instance_is_the_approved_one(postgres_migrations):
    """Refuse any server that is not the identity-pinned instance."""
    url = postgres_migrations.engine.url
    assert url.host == PINNED_HOST, url
    assert url.port == PINNED_PORT, url
    assert OWNED_DATABASE.startswith("review_mm_inventory_"), OWNED_DATABASE
    assert OWNED_DATABASE in str(url), url
    with postgres_migrations.engine.connect() as connection:
        system_identifier = connection.exec_driver_sql(
            "SELECT system_identifier::text FROM pg_control_system()"
        ).scalar()
        version = connection.exec_driver_sql("SELECT version()").scalar()
        data_directory = connection.exec_driver_sql("SELECT current_setting('data_directory')").scalar()
    assert system_identifier == PINNED_SYSTEM_IDENTIFIER, system_identifier
    assert version.startswith(PINNED_VERSION), version
    assert data_directory.replace("\\", "/").endswith(PINNED_DATA_DIRECTORY_SUFFIX), data_directory


@pytest.fixture
def pg(postgres_migrations):
    command.upgrade(postgres_migrations.config, "head")
    return sessionmaker(bind=postgres_migrations.engine, expire_on_commit=False)


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
        rows = connection.exec_driver_sql(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = :table::regclass AND contype = 'c'",
            {"table": table},
        ).all()
    return {name: definition for name, definition in rows}


def test_postgres_constraints_match_the_canonical_vocabularies(postgres_migrations):
    definitions = _check_definitions(postgres_migrations.engine, "stock_movements")
    movement = definitions["ck_stock_movements_type"]
    for member in StockMovementType:
        assert f"'{member.value}'" in movement, movement

    definitions = _check_definitions(postgres_migrations.engine, "material_reservations")
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
        assert response["movement_type"] == "transfer"
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
        payload = StockMovementIn(
            movement_type="issue", item_id=stock["item"], batch_id=stock["batch"],
            from_warehouse_id=stock["source"], quantity=1, unit="kg",
        )
        first = transfers_service.transfer_stock(db, payload, actor, idempotency_key=key)
        assert first["movement_type"] == "issue"
        replay = transfers_service.transfer_stock(db, payload, actor, idempotency_key=key)
        assert replay == first
        assert db.query(StockMovement).filter_by(batch_id=stock["batch"]).count() == 1
        db.rollback()
