"""ST02: a stock movement must validate its batch and move it atomically.

``POST /api/inventory/transfer`` used to write a ``StockMovement`` ledger row and
stop there. The named batch was never locked, never validated against the
movement's item/unit/warehouse, and never decremented, so the ledger claimed
stock left a warehouse while the batch still held it. The same gap let a
movement overshoot the reservation floor or move fabric still held in Eco
custody.

Every rejection here must be total: batch quantity, ledger and audit are
asserted unchanged so a half-applied movement cannot hide.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.session import SessionLocal
from app.models import (
    AuditLog,
    EcoFabricDispatch,
    EcoFabricRoll,
    Item,
    MaterialReservation,
    Model,
    ProductionOrder,
    StockBatch,
    StockMovement,
    Warehouse,
)

ITEM_MISMATCH = "Stock batch does not belong to the selected item"
BATCH_UNIT_MISMATCH = "Movement unit must match the batch unit"
ITEM_UNIT_MISMATCH = "Movement unit must match the item unit"
WAREHOUSE_MISMATCH = "Movement warehouse must match the batch warehouse"
EXCEEDS_AVAILABLE = "Movement quantity exceeds available batch stock"
ECO_CUSTODY = "Return outstanding fabric through the Eco Cotton register"


# ===== Helpers =====


def _create_item(client, auth_headers, *, category="fabric", unit="kg", track_batch=True) -> int:
    suffix = uuid4().hex[:10].upper()
    response = client.post(
        "/api/inventory/items",
        headers=auth_headers,
        json={
            "sku": f"ST02-{suffix}",
            "name": f"ST02 item {suffix}",
            "category": category,
            "unit": unit,
            "default_cost": 1,
            "reorder_level": 0,
            "track_batch": track_batch,
            "is_active": True,
        },
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def _warehouses(client, auth_headers) -> dict:
    response = client.get("/api/inventory/warehouses", headers=auth_headers)
    assert response.status_code == 200, response.text
    rows = response.json()
    return {
        row["type"]: int(row["id"])
        for row in rows
        if row.get("type") in ("fabric_storage", "accessory_storage")
    }


def _receive(client, auth_headers, *, item_id, quantity, warehouse_id, unit="kg") -> int:
    response = client.post(
        "/api/inventory/receive",
        headers=auth_headers,
        json={
            "item_id": item_id,
            "batch_no": f"ST02-{uuid4().hex}",
            "quantity": quantity,
            "unit": unit,
            "cost_per_unit": 1,
            "warehouse_id": warehouse_id,
            "qc_status": "passed",
        },
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def _reserve(*, item_id, quantity, unit="kg", stock_batch_id, warehouse_id) -> int:
    suffix = uuid4().hex[:12]
    with SessionLocal() as db:
        model = Model(
            code=f"ST02-MODEL-{suffix}",
            name=f"ST02 model {suffix}",
            status="approved",
        )
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no=f"ST02-PO-{suffix}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=1,
        )
        db.add(order)
        db.flush()
        reservation = MaterialReservation(
            reservation_no=f"ST02-MR-{suffix}",
            production_order_id=order.id,
            item_id=item_id,
            stock_batch_id=stock_batch_id,
            warehouse_id=warehouse_id,
            reserved_quantity=quantity,
            consumed_quantity=0,
            released_quantity=0,
            unit=unit,
            status="reserved",
            reservation_type="material",
            source="manual",
        )
        db.add(reservation)
        db.commit()
        return int(reservation.id)


def _eco_custody(batch_id: int, *, item_no: str) -> None:
    """Hold one roll of the batch in the Eco Cotton register (not returned)."""
    with SessionLocal() as db:
        batch = db.get(StockBatch, batch_id)
        dispatch = EcoFabricDispatch(
            request_key=str(uuid4()),
            created_by=1,
            operator_name="ST02 operator",
            remaining_inventory=[],
        )
        db.add(dispatch)
        db.flush()
        db.add(
            EcoFabricRoll(
                dispatch_id=dispatch.id,
                batch_id=batch_id,
                roll_number=1,
                fabric_name="Eco Cotton jersey",
                batch_no=batch.batch_no,
                quantity=1,
                unit=batch.unit,
                returned_at=None,
            )
        )
        db.commit()


def _move(client, auth_headers, **payload):
    body = {"movement_type": "issue", "unit": "kg", **payload}
    return client.post("/api/inventory/transfer", headers=auth_headers, json=body)


def _batch_state(batch_id: int) -> tuple:
    """Quantity, warehouse, movement count and audit count for one batch."""
    with SessionLocal() as db:
        batch = db.get(StockBatch, batch_id)
        return (
            float(batch.quantity),
            int(batch.warehouse_id),
            db.query(StockMovement).filter(StockMovement.batch_id == batch_id).count(),
            db.query(AuditLog).filter(
                AuditLog.entity_type == "StockBatch",
                AuditLog.entity_id == batch_id,
            ).count(),
        )


def _seeded_batch(client, auth_headers, *, quantity=10.0):
    warehouses = _warehouses(client, auth_headers)
    warehouse_id = warehouses["fabric_storage"]
    item_id = _create_item(client, auth_headers)
    batch_id = _receive(
        client, auth_headers,
        item_id=item_id, quantity=quantity, warehouse_id=warehouse_id,
    )
    return item_id, batch_id, warehouse_id


# ===== Defect class 1: the movement never moved its batch =====


def test_issue_movement_decrements_the_batch_it_names(client, auth_headers):
    item_id, batch_id, warehouse_id = _seeded_batch(client, auth_headers, quantity=10)

    response = _move(
        client, auth_headers,
        item_id=item_id, batch_id=batch_id,
        from_warehouse_id=warehouse_id, quantity=4,
    )

    assert response.status_code == 201, response.text
    with SessionLocal() as db:
        assert float(db.get(StockBatch, batch_id).quantity) == 6
    assert db_movement_quantity(batch_id) == 4


def db_movement_quantity(batch_id: int) -> float:
    """The single outgoing ledger row the transfer wrote for this batch.

    Receiving also writes a movement against the batch, so the outgoing row has
    to be selected by type rather than by batch alone.
    """
    with SessionLocal() as db:
        return float(
            db.query(StockMovement)
            .filter(StockMovement.batch_id == batch_id, StockMovement.movement_type == "issue")
            .one()
            .quantity
        )


def test_return_movement_increments_the_batch_it_names(client, auth_headers):
    item_id, batch_id, warehouse_id = _seeded_batch(client, auth_headers, quantity=10)

    response = _move(
        client, auth_headers,
        movement_type="return",
        item_id=item_id, batch_id=batch_id,
        to_warehouse_id=warehouse_id, quantity=3,
    )

    assert response.status_code == 201, response.text
    with SessionLocal() as db:
        assert float(db.get(StockBatch, batch_id).quantity) == 13


def test_issue_that_empties_the_batch_archives_it(client, auth_headers):
    item_id, batch_id, warehouse_id = _seeded_batch(client, auth_headers, quantity=5)

    response = _move(
        client, auth_headers,
        item_id=item_id, batch_id=batch_id,
        from_warehouse_id=warehouse_id, quantity=5,
    )

    assert response.status_code == 201, response.text
    with SessionLocal() as db:
        batch = db.get(StockBatch, batch_id)
        assert float(batch.quantity) == 0
        assert batch.archived_at is not None


def test_transfer_moves_the_batch_to_the_destination_warehouse(client, auth_headers):
    warehouses = _warehouses(client, auth_headers)
    destination = _create_other_warehouse(client, auth_headers, name=f"ST02 dest {uuid4().hex[:6]}")
    item_id = _create_item(client, auth_headers)
    batch_id = _receive(
        client, auth_headers,
        item_id=item_id, quantity=8, warehouse_id=warehouses["fabric_storage"],
    )

    response = _move(
        client, auth_headers,
        movement_type="transfer",
        item_id=item_id, batch_id=batch_id,
        from_warehouse_id=warehouses["fabric_storage"],
        to_warehouse_id=destination,
        quantity=8,
    )

    assert response.status_code == 201, response.text
    with SessionLocal() as db:
        batch = db.get(StockBatch, batch_id)
        assert int(batch.warehouse_id) == destination
        assert float(batch.quantity) == 8
    assert destination != warehouses["fabric_storage"]


def _create_other_warehouse(client, auth_headers, *, name: str) -> int:
    response = client.post(
        "/api/inventory/warehouses",
        headers=auth_headers,
        json={"name": name, "type": "fabric_storage"},
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def test_batchless_movement_is_still_recorded(client, auth_headers):
    """A movement with no batch has no batch to move; it must not 404."""
    item_id, _, warehouse_id = _seeded_batch(client, auth_headers, quantity=10)

    response = _move(
        client, auth_headers,
        item_id=item_id, batch_id=None,
        from_warehouse_id=warehouse_id, quantity=1,
    )

    assert response.status_code == 201, response.text


# ===== Defect class 2: batch belonging to another item =====


def test_batch_of_a_different_item_is_rejected(client, auth_headers):
    item_id, batch_id, warehouse_id = _seeded_batch(client, auth_headers, quantity=10)
    other_item_id = _create_item(client, auth_headers)

    response = _move(
        client, auth_headers,
        item_id=other_item_id, batch_id=batch_id,
        from_warehouse_id=warehouse_id, quantity=1,
    )

    assert response.status_code == 409, response.text
    assert ITEM_MISMATCH in response.json()["detail"]


def test_unknown_batch_is_rejected(client, auth_headers):
    item_id, _, warehouse_id = _seeded_batch(client, auth_headers, quantity=10)

    response = _move(
        client, auth_headers,
        item_id=item_id, batch_id=99999999,
        from_warehouse_id=warehouse_id, quantity=1,
    )

    assert response.status_code == 404, response.text


# ===== Defect class 3: unit mismatch =====


def test_unit_that_differs_from_the_item_is_rejected(client, auth_headers):
    item_id, batch_id, warehouse_id = _seeded_batch(client, auth_headers, quantity=10)

    response = _move(
        client, auth_headers,
        item_id=item_id, batch_id=batch_id,
        from_warehouse_id=warehouse_id, quantity=1, unit="pcs",
    )

    assert response.status_code == 409, response.text
    assert ITEM_UNIT_MISMATCH in response.json()["detail"]


def test_unit_that_differs_from_the_batch_is_rejected(client, auth_headers):
    """Item and batch agree on 'kg'; a batch holding 'pcs' must not absorb it."""
    warehouses = _warehouses(client, auth_headers)
    item_id = _create_item(client, auth_headers, unit="kg")
    batch_id = _receive(
        client, auth_headers,
        item_id=item_id, quantity=10,
        warehouse_id=warehouses["fabric_storage"], unit="pcs",
    )
    with SessionLocal() as db:
        db.get(StockBatch, batch_id).unit = "pcs"
        db.commit()

    response = _move(
        client, auth_headers,
        item_id=item_id, batch_id=batch_id,
        from_warehouse_id=warehouses["fabric_storage"], quantity=1, unit="kg",
    )

    assert response.status_code == 409, response.text
    assert BATCH_UNIT_MISMATCH in response.json()["detail"]


# ===== Defect class 4: warehouse mismatch =====


def test_unknown_warehouse_is_rejected(client, auth_headers):
    item_id, batch_id, warehouse_id = _seeded_batch(client, auth_headers, quantity=10)

    response = _move(
        client, auth_headers,
        item_id=item_id, batch_id=batch_id,
        from_warehouse_id=99999999, quantity=1,
    )

    assert response.status_code == 404, response.text


def test_movement_from_a_warehouse_the_batch_is_not_in_is_rejected(client, auth_headers):
    # Seed the batch first, then add a second warehouse it was never received
    # into, so the two ids are guaranteed to differ.
    item_id, batch_id, warehouse_id = _seeded_batch(client, auth_headers, quantity=10)
    other = _create_other_warehouse(client, auth_headers, name=f"ST02 other {uuid4().hex[:6]}")
    assert other != warehouse_id

    response = _move(
        client, auth_headers,
        item_id=item_id, batch_id=batch_id,
        from_warehouse_id=other, quantity=1,
    )

    assert response.status_code == 409, response.text
    assert WAREHOUSE_MISMATCH in response.json()["detail"]


# ===== Defect class 5: active reservations =====


def test_issue_below_the_reservation_floor_is_rejected(client, auth_headers):
    item_id, batch_id, warehouse_id = _seeded_batch(client, auth_headers, quantity=10)
    _reserve(
        item_id=item_id, quantity=7, stock_batch_id=batch_id, warehouse_id=warehouse_id,
    )

    response = _move(
        client, auth_headers,
        item_id=item_id, batch_id=batch_id,
        from_warehouse_id=warehouse_id, quantity=8,
    )

    assert response.status_code == 409, response.text
    assert EXCEEDS_AVAILABLE in response.json()["detail"]


def test_issue_up_to_the_reservation_floor_is_allowed(client, auth_headers):
    item_id, batch_id, warehouse_id = _seeded_batch(client, auth_headers, quantity=10)
    _reserve(
        item_id=item_id, quantity=7, stock_batch_id=batch_id, warehouse_id=warehouse_id,
    )

    response = _move(
        client, auth_headers,
        item_id=item_id, batch_id=batch_id,
        from_warehouse_id=warehouse_id, quantity=3,
    )

    assert response.status_code == 201, response.text
    with SessionLocal() as db:
        assert float(db.get(StockBatch, batch_id).quantity) == 7


def test_issue_beyond_the_batch_quantity_is_rejected(client, auth_headers):
    item_id, batch_id, warehouse_id = _seeded_batch(client, auth_headers, quantity=10)

    response = _move(
        client, auth_headers,
        item_id=item_id, batch_id=batch_id,
        from_warehouse_id=warehouse_id, quantity=11,
    )

    assert response.status_code == 409, response.text
    assert EXCEEDS_AVAILABLE in response.json()["detail"]


# ===== Defect class 6: Eco custody =====


def test_issue_of_fabric_still_in_eco_custody_is_rejected(client, auth_headers):
    item_id, batch_id, warehouse_id = _seeded_batch(client, auth_headers, quantity=10)
    _eco_custody(batch_id, item_no="ST02")

    response = _move(
        client, auth_headers,
        item_id=item_id, batch_id=batch_id,
        from_warehouse_id=warehouse_id, quantity=1,
    )

    assert response.status_code == 409, response.text
    assert ECO_CUSTODY in response.json()["detail"]


def test_returned_eco_roll_frees_the_batch_again(client, auth_headers):
    from datetime import datetime, timezone

    item_id, batch_id, warehouse_id = _seeded_batch(client, auth_headers, quantity=10)
    _eco_custody(batch_id, item_no="ST02")
    with SessionLocal() as db:
        roll = db.query(EcoFabricRoll).filter_by(batch_id=batch_id, returned_at=None).one()
        roll.returned_at = datetime.now(timezone.utc)
        db.commit()

    response = _move(
        client, auth_headers,
        item_id=item_id, batch_id=batch_id,
        from_warehouse_id=warehouse_id, quantity=1,
    )

    assert response.status_code == 201, response.text


# ===== Atomicity: a rejected movement writes nothing at all =====


@pytest.mark.parametrize(
    "case",
    ["item_mismatch", "unit_mismatch", "warehouse_mismatch", "over_reserved", "eco_custody", "over_quantity"],
)
def test_rejected_movement_leaves_batch_ledger_and_audit_unchanged(client, auth_headers, case):
    item_id, batch_id, warehouse_id = _seeded_batch(client, auth_headers, quantity=10)
    if case == "item_mismatch":
        payload = {
            "item_id": _create_item(client, auth_headers),
            "batch_id": batch_id, "from_warehouse_id": warehouse_id, "quantity": 1,
        }
    elif case == "unit_mismatch":
        payload = {
            "item_id": item_id, "batch_id": batch_id,
            "from_warehouse_id": warehouse_id, "quantity": 1, "unit": "pcs",
        }
    elif case == "warehouse_mismatch":
        payload = {
            "item_id": item_id, "batch_id": batch_id,
            "from_warehouse_id": _create_other_warehouse(
                client, auth_headers, name=f"ST02 other {uuid4().hex[:6]}",
            ),
            "quantity": 1,
        }
    elif case == "over_reserved":
        _reserve(item_id=item_id, quantity=7, stock_batch_id=batch_id, warehouse_id=warehouse_id)
        payload = {
            "item_id": item_id, "batch_id": batch_id,
            "from_warehouse_id": warehouse_id, "quantity": 8,
        }
    elif case == "eco_custody":
        _eco_custody(batch_id, item_no="ST02")
        payload = {
            "item_id": item_id, "batch_id": batch_id,
            "from_warehouse_id": warehouse_id, "quantity": 1,
        }
    else:
        payload = {
            "item_id": item_id, "batch_id": batch_id,
            "from_warehouse_id": warehouse_id, "quantity": 11,
        }

    before = _batch_state(batch_id)
    with SessionLocal() as db:
        movements_for_item = db.query(StockMovement).filter(
            StockMovement.item_id == payload["item_id"],
        ).count()

    response = _move(client, auth_headers, **payload)

    assert response.status_code == 409, response.text
    # Batch row, its warehouse, its ledger rows and its audit trail are identical.
    assert _batch_state(batch_id) == before
    with SessionLocal() as db:
        assert db.query(StockMovement).filter(
            StockMovement.item_id == payload["item_id"],
        ).count() == movements_for_item


# ===== PostgreSQL: the batch lock must actually serialize against a reserve =====


@pytest.fixture
def movement_postgres_engine():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for PostgreSQL movement locking coverage")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Movement locking tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"movement_batch_{uuid4().hex}"
    engine = create_engine(
        url, connect_args={"options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"},
        pool_size=4, max_overflow=0, isolation_level="READ COMMITTED",
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        tables = {
            AuditLog.__table__, EcoFabricDispatch.__table__, EcoFabricRoll.__table__,
            Item.__table__, MaterialReservation.__table__, StockBatch.__table__,
            StockMovement.__table__, Warehouse.__table__,
        }
        pending = list(tables)
        while pending:
            for foreign_key in pending.pop().foreign_keys:
                target = foreign_key.column.table
                if target not in tables:
                    tables.add(target)
                    pending.append(target)
        Base.metadata.create_all(engine, tables=list(tables))
        yield engine
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def _pg_user() -> SimpleNamespace:
    """A caller with no role and no grants, matching user_permissions' reads."""
    return SimpleNamespace(id=None, role=None, extra_permissions=[], factory_code=None, department=None)


def test_postgres_movement_waits_for_the_batch_lock(movement_postgres_engine):
    """Two real connections: the movement must block on the batch row lock.

    SQLite has no row locking, so only PostgreSQL can show that the batch is
    locked and that the reservation floor is re-read after the lock is granted.
    """
    from app.api.routes.inventory import transfer_stock
    from app.schemas.inventory import StockMovementIn

    session_factory = sessionmaker(movement_postgres_engine, expire_on_commit=False)
    marker = uuid4().hex[:8]
    with session_factory() as db:
        item = Item(sku=f"ST02-PG-{marker}", name="ST02 pg", category="fabric", unit="kg", track_batch=True)
        warehouse = Warehouse(name=f"ST02 pg {marker}", type="fabric_storage")
        db.add_all([item, warehouse])
        db.flush()
        batch = StockBatch(
            item_id=item.id, batch_no=f"ST02-PG-{marker}", quantity=10, unit="kg",
            cost_per_unit=1, warehouse_id=warehouse.id, qc_status="passed",
        )
        db.add(batch)
        db.commit()
        item_id, batch_id, warehouse_id = item.id, batch.id, warehouse.id

    def payload(quantity: float) -> StockMovementIn:
        return StockMovementIn(
            movement_type="issue", item_id=item_id, batch_id=batch_id,
            from_warehouse_id=warehouse_id, quantity=quantity, unit="kg",
        )

    with session_factory() as first:
        select_for_update_batch(first, batch_id)
        first_pid = first.execute(text("SELECT pg_backend_pid()")).scalar_one()
        started = Event()
        second_pid = []

        def second_movement():
            with session_factory() as second:
                second_pid.append(second.execute(text("SELECT pg_backend_pid()")).scalar_one())
                started.set()
                try:
                    transfer_stock(
                        payload(4), second, current=_pg_user(), idempotency_key=None,
                    )
                    second.commit()
                    return 201
                except HTTPException as error:
                    second.rollback()
                    return error.status_code

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(second_movement)
            assert started.wait(5)
            deadline = monotonic() + 5
            blocked = False
            while monotonic() < deadline and not future.done():
                with movement_postgres_engine.connect() as observer:
                    blockers = observer.execute(
                        text("SELECT pg_blocking_pids(:pid)"), {"pid": second_pid[0]},
                    ).scalar_one()
                if first_pid in blockers:
                    blocked = True
                    break
                sleep(0.02)
            assert blocked, "Movement did not wait for the stock batch lock"
            first.commit()
            assert future.result(timeout=10) == 201

    with session_factory() as db:
        assert float(db.get(StockBatch, batch_id).quantity) == 6
        assert db.query(StockMovement).filter_by(batch_id=batch_id).count() == 1


def select_for_update_batch(db, batch_id: int):
    """Take the same row lock the movement path uses, on connection one."""
    from app.api.routes.inventory import _locked_stock_batch_statement

    return db.execute(
        _locked_stock_batch_statement(batch_id).execution_options(populate_existing=True)
    ).scalar_one()


def _reservation_style_lock(db, batch_id: int):
    """Take the exact lock the reservation path takes in services.inventory."""
    from app.services.inventory import _lock_batch_query

    return _lock_batch_query(db, batch_id).filter(StockBatch.id == batch_id).one()


def test_postgres_claim_committed_while_movement_waits_still_blocks_it(movement_postgres_engine):
    """A claim that lands during the movement's lock wait must raise the floor.

    Connection one mirrors ``create_material_reservations``: it takes
    ``FOR UPDATE OF stock_batches`` and writes a reservation without committing.
    Connection two issues 5 kg against a 10 kg batch and may only read the
    reservation sum after the claim commits, so the move is rejected and the
    batch is untouched.
    """
    from app.api.routes.inventory import transfer_stock
    from app.schemas.inventory import StockMovementIn

    session_factory = sessionmaker(movement_postgres_engine, expire_on_commit=False)
    marker = uuid4().hex[:8]
    with session_factory() as db:
        item = Item(sku=f"ST02-CLM-{marker}", name="ST02 claim", category="fabric", unit="kg", track_batch=True)
        warehouse = Warehouse(name=f"ST02 claim {marker}", type="fabric_storage")
        model = Model(code=f"ST02-CLM-M-{marker}", name="ST02 claim model", status="approved")
        db.add_all([item, warehouse, model])
        db.flush()
        order = ProductionOrder(
            production_no=f"ST02-CLM-PO-{marker}", production_type="branded_stock",
            model_id=model.id, planned_quantity=1,
        )
        db.add(order)
        db.flush()
        batch = StockBatch(
            item_id=item.id, batch_no=f"ST02-CLM-{marker}", quantity=10, unit="kg",
            cost_per_unit=1, warehouse_id=warehouse.id, qc_status="passed",
        )
        db.add(batch)
        db.commit()
        item_id, batch_id, warehouse_id = item.id, batch.id, warehouse.id
        order_id = order.id

    with session_factory() as first:
        _reservation_style_lock(first, batch_id)
        first.add(MaterialReservation(
            reservation_no=f"ST02-CLM-MR-{marker}", production_order_id=order_id,
            item_id=item_id, stock_batch_id=batch_id, warehouse_id=warehouse_id,
            reserved_quantity=8, consumed_quantity=0, released_quantity=0, unit="kg",
            status="reserved", reservation_type="material", source="manual",
        ))
        first_pid = first.execute(text("SELECT pg_backend_pid()")).scalar_one()
        started = Event()
        second_pid = []

        def second_movement():
            with session_factory() as second:
                second_pid.append(second.execute(text("SELECT pg_backend_pid()")).scalar_one())
                started.set()
                try:
                    transfer_stock(
                        StockMovementIn(
                            movement_type="issue", item_id=item_id, batch_id=batch_id,
                            from_warehouse_id=warehouse_id, quantity=5, unit="kg",
                        ),
                        second, current=_pg_user(), idempotency_key=None,
                    )
                    second.commit()
                    return 201
                except HTTPException as error:
                    second.rollback()
                    return error.status_code

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(second_movement)
            assert started.wait(5)
            deadline = monotonic() + 5
            blocked = False
            while monotonic() < deadline and not future.done():
                with movement_postgres_engine.connect() as observer:
                    blockers = observer.execute(
                        text("SELECT pg_blocking_pids(:pid)"), {"pid": second_pid[0]},
                    ).scalar_one()
                if first_pid in blockers:
                    blocked = True
                    break
                sleep(0.02)
            assert blocked, "Movement did not wait for the reserving transaction"
            first.commit()
            assert future.result(timeout=10) == 409

    with session_factory() as db:
        assert float(db.get(StockBatch, batch_id).quantity) == 10
        assert db.query(StockMovement).filter_by(batch_id=batch_id).count() == 0
