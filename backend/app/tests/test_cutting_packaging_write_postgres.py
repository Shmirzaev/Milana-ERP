from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
import json
import os
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import (
    BusinessOrderAlias,
    Item,
    MaterialReservation,
    Model,
    ModelBOM,
    ProductionOrder,
    StockBatch,
    StockMovement,
    Warehouse,
)
from app.services.bundles import reserve_bundle_numbers
from app.services.inventory import ACTIVE_RESERVATION_STATUSES, consume_cutting_materials
from app.services.workflow import consume_packaging_materials_from_bom


@pytest.fixture(scope="module")
def perf20_postgres_sessions():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Requires disposable PostgreSQL")
    url = make_url(raw_url)
    if (
        url.get_backend_name() != "postgresql"
        or url.host not in {"127.0.0.1", "localhost", "::1"}
        or url.query
    ):
        pytest.fail("PERF20 tests require loopback PostgreSQL without connection overrides")
    schema = f"perf20_writes_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={
            "options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"
        },
        pool_size=4,
        max_overflow=0,
        isolation_level="READ COMMITTED",
    )
    assert engine.dialect.name == "postgresql"
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False), engine
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def _clear_bundle_numbers(sessions) -> None:
    with sessions.begin() as db:
        db.query(BusinessOrderAlias).filter(BusinessOrderAlias.namespace == "BND").delete(
            synchronize_session=False,
        )


@pytest.mark.parametrize("count", [1, 50, 401])
def test_postgres_bundle_range_reservation_has_constant_reads(perf20_postgres_sessions, count):
    sessions, engine = perf20_postgres_sessions
    _clear_bundle_numbers(sessions)
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with sessions.begin() as db:
            references = reserve_bundle_numbers(db, count)
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert len(statements) == 3
    assert len(references) == count
    assert references[0] == "BND-0001"
    assert references[-1] == f"BND-{count:04d}"


def test_postgres_bundle_ranges_serialize_without_overlap(perf20_postgres_sessions):
    sessions, _engine = perf20_postgres_sessions
    _clear_bundle_numbers(sessions)
    start = Event()

    def reserve() -> list[str]:
        with sessions() as db:
            assert start.wait(10)
            references = reserve_bundle_numbers(db, 401)
            db.commit()
            return references

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(reserve) for _ in range(2)]
        start.set()
        ranges = sorted((future.result(timeout=20) for future in futures), key=lambda row: row[0])

    assert ranges[0] == [f"BND-{number:04d}" for number in range(1, 402)]
    assert ranges[1] == [f"BND-{number:04d}" for number in range(402, 803)]
    assert set(ranges[0]).isdisjoint(ranges[1])


def test_postgres_bundle_range_reservation_releases_on_rollback(perf20_postgres_sessions):
    sessions, _engine = perf20_postgres_sessions
    _clear_bundle_numbers(sessions)
    with sessions() as db:
        rolled_back = reserve_bundle_numbers(db, 50)
        db.rollback()
    with sessions.begin() as db:
        committed = reserve_bundle_numbers(db, 50)

    assert committed == rolled_back


def _packaging_case(sessions, count: int) -> tuple[int, list[int]]:
    marker = uuid4().hex[:8]
    with sessions.begin() as db:
        model = Model(code=f"PERF20-PG-{marker}", name="PERF20 packaging plan")
        warehouse = Warehouse(name=f"PERF20 PG {marker}", type="materials")
        items = [
            Item(
                sku=f"PERF20-PG-{marker}-{index:04d}",
                name=f"Packaging material {index}",
                category="packaging",
                unit="pcs",
            )
            for index in range(count)
        ]
        db.add_all([model, warehouse, *items])
        db.flush()
        db.add_all([
            ModelBOM(
                model_id=model.id,
                item_id=item.id,
                quantity_per_piece=1,
                unit="pcs",
                waste_percent=0,
            )
            for item in items
        ])
        batches = [
            StockBatch(
                item_id=item.id,
                warehouse_id=warehouse.id,
                batch_no=f"PERF20-PG-BATCH-{marker}-{index:04d}",
                quantity=2,
                unit="pcs",
                qc_status="passed",
            )
            for index, item in enumerate(items)
        ]
        db.add_all(batches)
        order = ProductionOrder(
            production_no=f"PERF20-PG-PO-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=1,
        )
        db.add(order)
        db.flush()
        return int(order.id), [int(item.id) for item in items]


def _node_types(plan: dict) -> set[str]:
    result = {str(plan.get("Node Type"))}
    for child in plan.get("Plans", []):
        result.update(_node_types(child))
    return result


def _cutting_case(
    sessions,
    count: int,
    *,
    batch_quantity: float = 2,
    reserved_quantity: float = 0,
) -> tuple[int, list[int]]:
    marker = uuid4().hex[:8]
    with sessions.begin() as db:
        model = Model(code=f"PERF20-CUT-PG-{marker}", name="PERF20 cutting consumption")
        warehouse = Warehouse(name=f"PERF20 cutting PG {marker}", type="materials")
        items = [
            Item(
                sku=f"PERF20-CUT-PG-{marker}-{index:04d}",
                name=f"Cutting material {index}",
                category="fabric",
                unit="kg",
            )
            for index in range(count)
        ]
        db.add_all([model, warehouse, *items])
        db.flush()
        batches = [
            StockBatch(
                item_id=item.id,
                warehouse_id=warehouse.id,
                batch_no=f"PERF20-CUT-PG-BATCH-{marker}-{index:04d}",
                quantity=batch_quantity,
                unit="kg",
                qc_status="passed",
            )
            for index, item in enumerate(items)
        ]
        order = ProductionOrder(
            production_no=f"PERF20-CUT-PG-PO-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=1,
        )
        db.add_all([*batches, order])
        db.flush()
        if reserved_quantity > 0:
            db.add_all([
                MaterialReservation(
                    reservation_no=f"PERF20-PG-MR-{marker}-{index:04d}",
                    production_order_id=order.id,
                    item_id=item.id,
                    stock_batch_id=batch.id,
                    warehouse_id=warehouse.id,
                    reserved_quantity=reserved_quantity,
                    consumed_quantity=0,
                    released_quantity=0,
                    unit="kg",
                    status="reserved",
                    reservation_type="material",
                    source="manual",
                )
                for index, (item, batch) in enumerate(zip(items, batches, strict=True))
            ])
        return int(order.id), [int(batch.id) for batch in batches]


@pytest.mark.parametrize("count", [1, 50, 401])
def test_postgres_cutting_material_consumption_has_constant_locked_reads(
    perf20_postgres_sessions,
    count,
):
    sessions, engine = perf20_postgres_sessions
    production_order_id, batch_ids = _cutting_case(sessions, count)
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with sessions.begin() as db:
            consume_cutting_materials(
                db,
                production_order_id=production_order_id,
                lines=[
                    {"stock_batch_id": batch_id, "quantity": 1, "unit": "kg"}
                    for batch_id in batch_ids
                ],
                reference_type="CuttingRecord",
                reference_id=1,
                user_id=None,
            )
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert len(statements) == 3
    assert sum(" from material_reservations " in statement for statement in statements) == 1
    assert sum(" from stock_batches " in statement for statement in statements) == 1
    assert sum(" from items " in statement for statement in statements) == 1
    assert "for update of material_reservations" in statements[0]
    assert "for update of stock_batches" in statements[1]


def test_postgres_cutting_material_locks_serialize_reverse_input_order(
    perf20_postgres_sessions,
):
    sessions, _engine = perf20_postgres_sessions
    production_order_id, batch_ids = _cutting_case(sessions, 2, batch_quantity=1)
    start = Event()

    def consume(ordered_batch_ids: list[int]) -> tuple[str, list[int] | str]:
        with sessions() as db:
            assert start.wait(10)
            try:
                consume_cutting_materials(
                    db,
                    production_order_id=production_order_id,
                    lines=[
                        {"stock_batch_id": batch_id, "quantity": 1, "unit": "kg"}
                        for batch_id in ordered_batch_ids
                    ],
                    reference_type="CuttingRecord",
                    reference_id=2,
                    user_id=None,
                )
                db.commit()
                return "ok", ordered_batch_ids
            except HTTPException as exc:
                db.rollback()
                return str(exc.status_code), str(exc.detail)

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [
            workers.submit(consume, batch_ids),
            workers.submit(consume, list(reversed(batch_ids))),
        ]
        start.set()
        results = [future.result(timeout=20) for future in futures]

    assert sorted(result[0] for result in results) == ["409", "ok"]
    winning_order = next(result[1] for result in results if result[0] == "ok")
    with sessions() as db:
        batches = db.query(StockBatch).filter(StockBatch.id.in_(batch_ids)).order_by(StockBatch.id).all()
        movements = db.query(StockMovement).filter(
            StockMovement.batch_id.in_(batch_ids),
            StockMovement.reference_id == 2,
        ).order_by(StockMovement.id).all()
    assert [float(batch.quantity) for batch in batches] == [0.0, 0.0]
    assert [int(movement.batch_id) for movement in movements] == winning_order


def test_postgres_cutting_material_failure_rolls_back_all_locked_rows(
    perf20_postgres_sessions,
):
    sessions, _engine = perf20_postgres_sessions
    production_order_id, batch_ids = _cutting_case(sessions, 2)
    with sessions() as db:
        with pytest.raises(HTTPException, match="Insufficient stock in batch"):
            consume_cutting_materials(
                db,
                production_order_id=production_order_id,
                lines=[
                    {"stock_batch_id": batch_ids[0], "quantity": 1, "unit": "kg"},
                    {"stock_batch_id": batch_ids[1], "quantity": 3, "unit": "kg"},
                ],
                reference_type="CuttingRecord",
                reference_id=3,
                user_id=None,
            )
        db.rollback()
    with sessions() as db:
        batches = db.query(StockBatch).filter(StockBatch.id.in_(batch_ids)).order_by(StockBatch.id).all()
        movement_count = db.query(StockMovement).filter(
            StockMovement.batch_id.in_(batch_ids),
            StockMovement.reference_id == 3,
        ).count()
    assert [float(batch.quantity) for batch in batches] == [2.0, 2.0]
    assert movement_count == 0


def test_postgres_cutting_material_lock_plans_are_set_based(perf20_postgres_sessions):
    sessions, _engine = perf20_postgres_sessions
    production_order_id, batch_ids = _cutting_case(sessions, 401, reserved_quantity=1)
    reservation_statement = (
        select(MaterialReservation.id)
        .where(
            MaterialReservation.production_order_id == production_order_id,
            MaterialReservation.stock_batch_id.in_(batch_ids),
            MaterialReservation.status.in_(ACTIVE_RESERVATION_STATUSES),
        )
        .order_by(
            MaterialReservation.stock_batch_id,
            MaterialReservation.created_at,
            MaterialReservation.id,
        )
        .with_for_update(of=MaterialReservation)
    )
    stock_statement = (
        select(StockBatch.id)
        .where(StockBatch.id.in_(batch_ids))
        .order_by(StockBatch.id)
        .with_for_update(of=StockBatch)
    )
    plans = []
    with sessions.begin() as db:
        for statement in (reservation_statement, stock_statement):
            compiled = statement.compile(bind=db.get_bind(), compile_kwargs={"literal_binds": True})
            raw_plan = db.execute(
                text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {compiled}"),
            ).scalar_one()
            plans.append(raw_plan[0]["Plan"])

    for plan in plans:
        assert "SubPlan" not in json.dumps(plan, sort_keys=True)
        assert "LockRows" in _node_types(plan)
        assert int(plan["Actual Rows"]) == 401


def test_postgres_packaging_stock_preload_is_one_locked_set_plan(perf20_postgres_sessions):
    sessions, engine = perf20_postgres_sessions
    production_order_id, item_ids = _packaging_case(sessions, 401)
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and " from stock_batches " in normalized:
            statements.append(normalized)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with sessions.begin() as db:
            consume_packaging_materials_from_bom(
                db,
                production_order_id=production_order_id,
                packed_qty=1,
                reference_type="PackagingRecord",
                reference_id=1,
                user_id=None,
            )
            db.flush()
            movements = db.query(StockMovement).filter(
                StockMovement.item_id.in_(item_ids),
            ).order_by(StockMovement.id).all()
            assert [movement.item_id for movement in movements] == item_ids
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert len(statements) == 1
    assert "for update of stock_batches" in statements[0]

    statement = (
        select(StockBatch.id)
        .where(StockBatch.item_id.in_(item_ids), StockBatch.quantity > 0)
        .order_by(StockBatch.item_id, StockBatch.received_date, StockBatch.id)
        .with_for_update(of=StockBatch)
    )
    with sessions.begin() as db:
        compiled = statement.compile(bind=db.get_bind(), compile_kwargs={"literal_binds": True})
        raw_plan = db.execute(
            text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {compiled}"),
        ).scalar_one()
    plan = raw_plan[0]["Plan"]
    plan_text = json.dumps(plan, sort_keys=True)
    assert "SubPlan" not in plan_text
    assert "LockRows" in _node_types(plan)
    assert int(plan["Actual Rows"]) == 401
