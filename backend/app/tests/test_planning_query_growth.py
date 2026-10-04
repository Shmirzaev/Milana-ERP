"""PERF15: planning reads must not issue one query per sales-order line or item.

`material_requirements_for_sales_order` loaded the BOM with one query per
sales-order line, then called `available_stock_for_item` once per distinct
material item, and `planning_estimate_for_sales_order` re-read every Item and
Model one row at a time. An order with N lines therefore cost O(N) round trips
and the round-trip count grew linearly with the order.

The invariant is deliberately *not* a hardcoded query count, which would be
brittle. It is that the count does not grow with the number of lines/items: the
test measures a small order and a much larger one built from the same models and
the same materials, and fails when the larger order costs materially more.

Correctness is pinned separately by `test_*_matches_recorded_output`, which
compares the response against the payload recorded from the pre-fix code.

Requires real PostgreSQL. Set STABILIZATION_POSTGRES_URL to run it.
"""

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import (
    Item,
    MaterialReservation,
    Model,
    ModelBOM,
    ProductionOrder,
    SalesOrder,
    SalesOrderItem,
    StockBatch,
    StockMovement,
    Warehouse,
)
from app.services.planning import (
    material_requirements_for_quantity,
    material_requirements_for_sales_order,
    planning_estimate_for_sales_order,
)

# Line counts that differ by 10x while sharing every model and material, so the
# only variable between the two measurements is the number of planning lines.
SMALL_LINES = 4
LARGE_LINES = 40

# A correct bounded implementation issues the same statement count for both
# orders. Two per-row queries (a BOM read and a Model read) would each add 36
# statements at LARGE_LINES, so this bound fails loudly on per-line reads while
# tolerating a fixed number of setup statements.
MAX_GROWTH_FACTOR = 2
MAX_GROWTH_ALLOWANCE = 8

SIZES = ("S", "M", "L")
COLORS = ("black", "white")
MODEL_COUNT = 4
ITEM_COUNT = 6

# Recorded from the unfixed service (commit 88dcffb5) for the small fixture.
# Never regenerate this from the fixed service: it is the compatibility
# contract, so a changed value means a behaviour change, not a perf win.
EXPECTED_SMALL_REQUIREMENTS = [
    {"item_id": 1,
     "sku": "PERF15-small-I0",
     "name": "Material small 0",
     "composition": [{"name": "Cotton", "percentage": 95.0},
                     {"name": "Elastane", "percentage": 5.0}],
     "unit": "m",
     "required_quantity": 57.5,
     "available_quantity": 71.0,
     "shortage": 0.0},
    {"item_id": 2,
     "sku": "PERF15-small-I1",
     "name": "Material small 1",
     "composition": [{"name": "Cotton", "percentage": 95.0},
                     {"name": "Elastane", "percentage": 5.0}],
     "unit": "pcs",
     "required_quantity": 138.0,
     "available_quantity": 114.0,
     "shortage": 24.0},
    {"item_id": 4,
     "sku": "PERF15-small-I3",
     "name": "Material small 3",
     "composition": [],
     "unit": "pcs",
     "required_quantity": 44.0,
     "available_quantity": 136.0,
     "shortage": 0.0},
    {"item_id": 5,
     "sku": "PERF15-small-I4",
     "name": "Material small 4",
     "composition": [],
     "unit": "kg",
     "required_quantity": 46.0,
     "available_quantity": 115.0,
     "shortage": 0.0},
    {"item_id": 3,
     "sku": "PERF15-small-I2",
     "name": "Material small 2",
     "composition": [],
     "unit": "m",
     "required_quantity": 14.5,
     "available_quantity": 93.0,
     "shortage": 0.0},
]

EXPECTED_SMALL_ESTIMATE = {
    "sales_order_id": 1,
    "estimated_material_cost": 933.0,
    "estimated_labor_cost": 0.0,
    "estimated_electricity_cost": 0.0,
    "estimated_other_expenses": 0.0,
    "estimated_net_cost": 933.0,
    "suggested_price_15": 1072.95,
    "suggested_price_20": 1119.6,
    "estimated_sales_value": 1000.0,
    "estimated_lead_time_minutes": 534,
    "estimated_lead_time_hours": 8.9,
    "total_quantity": 46,
    "materials": [
        {"item_id": 1,
         "sku": "PERF15-small-I0",
         "name": "Material small 0",
         "composition": [{"name": "Cotton", "percentage": 95.0},
                         {"name": "Elastane", "percentage": 5.0}],
         "unit": "m",
         "required_quantity": 57.5,
         "available_quantity": 71.0,
         "shortage": 0.0,
         "category": "fabric",
         "unit_cost": 1.5,
         "estimated_cost": 86.25},
        {"item_id": 2,
         "sku": "PERF15-small-I1",
         "name": "Material small 1",
         "composition": [{"name": "Cotton", "percentage": 95.0},
                         {"name": "Elastane", "percentage": 5.0}],
         "unit": "pcs",
         "required_quantity": 138.0,
         "available_quantity": 114.0,
         "shortage": 24.0,
         "category": "accessory",
         "unit_cost": 2.5,
         "estimated_cost": 345.0},
        {"item_id": 4,
         "sku": "PERF15-small-I3",
         "name": "Material small 3",
         "composition": [],
         "unit": "pcs",
         "required_quantity": 44.0,
         "available_quantity": 136.0,
         "shortage": 0.0,
         "category": "accessory",
         "unit_cost": 4.5,
         "estimated_cost": 198.0},
        {"item_id": 5,
         "sku": "PERF15-small-I4",
         "name": "Material small 4",
         "composition": [],
         "unit": "kg",
         "required_quantity": 46.0,
         "available_quantity": 115.0,
         "shortage": 0.0,
         "category": "fabric",
         "unit_cost": 5.5,
         "estimated_cost": 253.0},
        {"item_id": 3,
         "sku": "PERF15-small-I2",
         "name": "Material small 2",
         "composition": [],
         "unit": "m",
         "required_quantity": 14.5,
         "available_quantity": 93.0,
         "shortage": 0.0,
         "category": "fabric",
         "unit_cost": 3.5,
         "estimated_cost": 50.75},
    ],
}

EXPECTED_QUANTITY_REQUIREMENTS = [
    {"item_id": 1,
     "sku": "PERF15-small-I0",
     "name": "Material small 0",
     "composition": [{"name": "Cotton", "percentage": 95.0},
                     {"name": "Elastane", "percentage": 5.0}],
     "unit": "m",
     "required_quantity": 58.75,
     "available_quantity": 71.0,
     "shortage": 0.0},
    {"item_id": 2,
     "sku": "PERF15-small-I1",
     "name": "Material small 1",
     "composition": [{"name": "Cotton", "percentage": 95.0},
                     {"name": "Elastane", "percentage": 5.0}],
     "unit": "pcs",
     "required_quantity": 141.0,
     "available_quantity": 114.0,
     "shortage": 27.0},
    {"item_id": 3,
     "sku": "PERF15-small-I2",
     "name": "Material small 2",
     "composition": [],
     "unit": "m",
     "required_quantity": 25.25,
     "available_quantity": 93.0,
     "shortage": 0.0},
    {"item_id": 4,
     "sku": "PERF15-small-I3",
     "name": "Material small 3",
     "composition": [],
     "unit": "pcs",
     "required_quantity": 80.0,
     "available_quantity": 136.0,
     "shortage": 0.0},
    {"item_id": 5,
     "sku": "PERF15-small-I4",
     "name": "Material small 4",
     "composition": [],
     "unit": "kg",
     "required_quantity": 47.0,
     "available_quantity": 115.0,
     "shortage": 0.0},
]


@pytest.fixture(scope="module")
def planning_postgres():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL planning query-growth coverage")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Planning query-growth tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"planning_growth_{uuid4().hex}"
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"}, future=True)
    assert engine.dialect.name == "postgresql"
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        tables = {
            Item.__table__,
            MaterialReservation.__table__,
            Model.__table__,
            ModelBOM.__table__,
            # MaterialReservation.production_order_id is NOT NULL.
            ProductionOrder.__table__,
            SalesOrder.__table__,
            SalesOrderItem.__table__,
            StockBatch.__table__,
            StockMovement.__table__,
            Warehouse.__table__,
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


def _counted(engine, fn):
    """Run `fn` on a fresh session and return (result, statements_executed).

    A fresh session per measurement keeps SQLAlchemy's identity map empty, so
    per-row `Session.get` lookups really do reach the database and are counted.
    """
    statements: list[str] = []

    def _before(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    event.listen(engine, "before_cursor_execute", _before)
    try:
        with session_factory() as db:
            result = fn(db)
    finally:
        event.remove(engine, "before_cursor_execute", _before)
    return result, len(statements)


def _seed(session_factory, tag: str, line_count: int) -> int:
    """Create a sales order of `line_count` lines over a fixed model/material set.

    Every seed uses the same number of models, BOM rows, items, batches,
    movements and reservations, so the two fixtures differ only in line count.
    """
    with session_factory.begin() as db:
        assert db.bind.dialect.name == "postgresql"
        warehouse = Warehouse(name=f"PERF15 store {tag}", type="fabric_storage")
        models = [
            Model(code=f"PERF15-{tag}-M{index}", name=f"Model {tag} {index}", status="approved",
                  sam_minutes=10 + index)
            for index in range(MODEL_COUNT)
        ]
        items = [
            Item(
                sku=f"PERF15-{tag}-I{index}",
                name=f"Material {tag} {index}",
                category="fabric" if index % 2 == 0 else "accessory",
                unit="m" if index % 2 == 0 else "pcs",
                default_cost=1.5 + index,
                composition_json=(
                    [{"name": "Cotton", "percentage": 95}, {"name": "Elastane", "percentage": 5}]
                    if index < 2
                    else []
                ),
            )
            for index in range(ITEM_COUNT)
        ]
        db.add_all([warehouse, *models, *items])
        db.flush()

        production_order = ProductionOrder(
            production_no=f"PERF15-{tag}-PO", production_type="client_order",
            model_id=models[0].id, status="new", planned_quantity=1,
        )
        db.add(production_order)
        db.flush()

        batches, movements, reservations = [], [], []
        for index, item in enumerate(items):
            batches.append(StockBatch(item_id=item.id, batch_no=f"PERF15-{tag}-B{index}",
                                      warehouse_id=warehouse.id, quantity=100 + 10 * index,
                                      cost_per_unit=2 + index, unit=item.unit))
            # Batchless ledger movements: "produce" is incoming, "consume" outgoing.
            movements.append(StockMovement(item_id=item.id, movement_type="produce",
                                           quantity=5 + index, unit=item.unit, batch_id=None))
            movements.append(StockMovement(item_id=item.id, movement_type="consume",
                                           quantity=2, unit=item.unit, batch_id=None))
            if index % 2 == 0:
                reservations.append(
                    MaterialReservation(production_order_id=production_order.id, item_id=item.id, reserved_quantity=40, consumed_quantity=5,
                                        released_quantity=3, status="reserved", unit=item.unit,
                                        reservation_no=f"PERF15-{tag}-R{index}")
                )
            else:
                reservations.append(
                    MaterialReservation(production_order_id=production_order.id, item_id=item.id, reserved_quantity=30, consumed_quantity=0,
                                        released_quantity=30, status="released", unit=item.unit,
                                        reservation_no=f"PERF15-{tag}-R{index}")
                )
        db.add_all(batches + movements + reservations)

        # Two unconditional materials, one size-specific pair, one
        # colour-specific line, and one material reached with a different unit.
        for model in models:
            db.add_all([
                ModelBOM(model_id=model.id, item_id=items[0].id, quantity_per_piece=1.25, unit="m"),
                ModelBOM(model_id=model.id, item_id=items[1].id, quantity_per_piece=3, unit="pcs"),
                ModelBOM(model_id=model.id, item_id=items[2].id, quantity_per_piece=0.5, unit="m",
                         size="M"),
                ModelBOM(model_id=model.id, item_id=items[2].id, quantity_per_piece=0.75, unit="m",
                         size="L"),
                ModelBOM(model_id=model.id, item_id=items[3].id, quantity_per_piece=2, unit="pcs",
                         color="black"),
                ModelBOM(model_id=model.id, item_id=items[4].id, quantity_per_piece=1, unit="kg"),
            ])
        db.flush()

        order = SalesOrder(order_no=f"PERF15-{tag}", status="planning_approved", total_amount=1000)
        db.add(order)
        db.flush()
        for index in range(line_count):
            db.add(
                SalesOrderItem(
                    sales_order_id=order.id,
                    model_id=models[index % MODEL_COUNT].id,
                    color=COLORS[index % len(COLORS)],
                    size=SIZES[index % len(SIZES)],
                    quantity=10 + index,
                    unit_price=20,
                )
            )
        return order.id


@pytest.fixture(scope="module")
def small_order(planning_postgres):
    session_factory = sessionmaker(bind=planning_postgres, autoflush=False, expire_on_commit=False)
    return session_factory, _seed(session_factory, "small", SMALL_LINES)


@pytest.fixture(scope="module")
def large_order(planning_postgres):
    session_factory = sessionmaker(bind=planning_postgres, autoflush=False, expire_on_commit=False)
    return session_factory, _seed(session_factory, "large", LARGE_LINES)


def test_requirements_query_count_does_not_grow_with_line_count(planning_postgres, small_order, large_order):
    small_factory, small_id = small_order
    large_factory, large_id = large_order
    small_rows, small_queries = _counted(
        planning_postgres, lambda db: material_requirements_for_sales_order(db, small_id)
    )
    large_rows, large_queries = _counted(
        planning_postgres, lambda db: material_requirements_for_sales_order(db, large_id)
    )
    assert small_rows, "small fixture must produce material rows"
    assert large_rows, "large fixture must produce material rows"
    budget = small_queries * MAX_GROWTH_FACTOR + MAX_GROWTH_ALLOWANCE
    assert large_queries <= budget, (
        f"material requirements grew with line count: {SMALL_LINES} lines -> {small_queries} queries, "
        f"{LARGE_LINES} lines -> {large_queries} queries (budget {budget})"
    )


def test_estimate_query_count_does_not_grow_with_line_count(planning_postgres, small_order, large_order):
    small_factory, small_id = small_order
    large_factory, large_id = large_order
    small_estimate, small_queries = _counted(
        planning_postgres, lambda db: planning_estimate_for_sales_order(db, small_id)
    )
    large_estimate, large_queries = _counted(
        planning_postgres, lambda db: planning_estimate_for_sales_order(db, large_id)
    )
    assert small_estimate and large_estimate
    budget = small_queries * MAX_GROWTH_FACTOR + MAX_GROWTH_ALLOWANCE
    assert large_queries <= budget, (
        f"planning estimate grew with line count: {SMALL_LINES} lines -> {small_queries} queries, "
        f"{LARGE_LINES} lines -> {large_queries} queries (budget {budget})"
    )


def test_requirements_match_recorded_output(planning_postgres, small_order):
    _, small_id = small_order
    rows, _ = _counted(planning_postgres, lambda db: material_requirements_for_sales_order(db, small_id))
    assert rows == EXPECTED_SMALL_REQUIREMENTS


def test_estimate_matches_recorded_output(planning_postgres, small_order):
    _, small_id = small_order
    estimate, _ = _counted(planning_postgres, lambda db: planning_estimate_for_sales_order(db, small_id))
    assert estimate == EXPECTED_SMALL_ESTIMATE


def test_quantity_requirements_match_recorded_output(planning_postgres, small_order):
    small_factory, _ = small_order
    with small_factory() as db:
        model = db.query(Model).filter(Model.code == "PERF15-small-M0").one()
        rows = material_requirements_for_quantity(
            db, model.id,
            [{"color": "black", "size": "M", "quantity": 40},
             {"color": "white", "size": "L", "quantity": 7}],
        )
    assert rows == EXPECTED_QUANTITY_REQUIREMENTS

