"""Historical unit cost belongs to the consumption event, not today's batch."""

from decimal import Decimal
import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.db import session as session_module
from app.db.base import Base
from app.models import (
    Customer, Item, Model, ProductionOrder, SalesOrder, SalesOrderItem,
    StockBatch, StockMovement, Warehouse,
)
from app.services.finance import order_profit
from app.services.workflow import consume_item_from_batches, consume_stock_batch


def _stock(*, costs: tuple[str, ...], quantities: tuple[str, ...]):
    with session_module.SessionLocal() as db:
        item = Item(sku="COST-SNAPSHOT", name="Cost snapshot", category="accessory", unit="pcs")
        warehouse = Warehouse(name="Cost snapshot warehouse", type="accessory_storage")
        db.add_all([item, warehouse])
        db.flush()
        batches = [
            StockBatch(
                item_id=item.id, batch_no=f"COST-SNAPSHOT-{index}", quantity=quantity,
                cost_per_unit=cost, unit="pcs", warehouse_id=warehouse.id, qc_status="passed",
            )
            for index, (cost, quantity) in enumerate(zip(costs, quantities), start=1)
        ]
        db.add_all(batches)
        db.flush()
        ids = item.id, warehouse.id, [batch.id for batch in batches]
        db.commit()
        return ids


def test_direct_batch_consumption_keeps_original_cost_after_batch_repricing(client):
    _, _, batch_ids = _stock(costs=("4.7500",), quantities=("2",))
    with session_module.SessionLocal() as db:
        consume_stock_batch(
            db, batch_id=batch_ids[0], quantity=0.5, unit="pcs",
            reference_type="CuttingRecord", reference_id=741, user_id=None,
        )
        db.commit()
        movement = db.query(StockMovement).filter_by(reference_type="CuttingRecord", reference_id=741).one()
        assert movement.unit_cost_at_movement == Decimal("4.7500")
        db.get(StockBatch, batch_ids[0]).cost_per_unit = Decimal("9.2500")
        db.commit()
        db.refresh(movement)
        assert movement.unit_cost_at_movement == Decimal("4.7500")


def test_fifo_consumption_snapshots_each_batch_and_leaves_batchless_unknown(client):
    item_id, _, batch_ids = _stock(costs=("1.2500", "2.5000"), quantities=("2", "3"))
    with session_module.SessionLocal() as db:
        consumed = consume_item_from_batches(
            db, item_id=item_id, quantity=4, unit="pcs",
            reference_type="ProductionOrder", reference_id=742, user_id=None,
        )
        assert consumed == 4
        db.commit()
        movements = db.query(StockMovement).filter_by(
            reference_type="ProductionOrder", reference_id=742,
        ).order_by(StockMovement.id).all()
        assert [(row.batch_id, row.quantity, row.unit_cost_at_movement) for row in movements] == [
            (batch_ids[0], Decimal("2.0000"), Decimal("1.2500")),
            (batch_ids[1], Decimal("2.0000"), Decimal("2.5000")),
        ]

        batchless_item = Item(sku="COST-SNAPSHOT-BATCHLESS", name="Batchless", category="accessory", unit="pcs")
        db.add(batchless_item)
        db.flush()
        consume_item_from_batches(
            db, item_id=batchless_item.id, quantity=1, unit="pcs",
            reference_type="ProductionOrder", reference_id=743, user_id=None,
        )
        db.commit()
        batchless = db.query(StockMovement).filter_by(
            reference_type="ProductionOrder", reference_id=743,
        ).one()
        assert batchless.batch_id is None
        assert batchless.unit_cost_at_movement is None


def test_manual_batch_consume_snapshots_cost_but_issue_does_not(client, auth_headers):
    item_id, warehouse_id, batch_ids = _stock(costs=("3.1250",), quantities=("5",))
    base = {
        "item_id": item_id, "batch_id": batch_ids[0], "quantity": 1,
        "unit": "pcs", "from_warehouse_id": warehouse_id,
    }
    consume = client.post("/api/inventory/transfer", headers=auth_headers, json={
        **base, "movement_type": "consume", "reference_type": "ProductionOrder", "reference_id": 744,
    })
    assert consume.status_code == 201, consume.text
    issue = client.post("/api/inventory/transfer", headers=auth_headers, json={
        **base, "movement_type": "issue", "reference_type": "Other", "reference_id": 744,
    })
    assert issue.status_code == 201, issue.text
    with session_module.SessionLocal() as db:
        consumed = db.get(StockMovement, consume.json()["id"])
        issued = db.get(StockMovement, issue.json()["id"])
        assert consumed.unit_cost_at_movement == Decimal("3.1250")
        assert issued.unit_cost_at_movement is None


def test_cost_snapshot_migration_preserves_legacy_unknown_and_reverses():
    migration_path = Path(__file__).resolve().parents[2] / "alembic/versions/0133_stock_movement_cost_snapshot.py"
    spec = importlib.util.spec_from_file_location("cost_snapshot_migration", migration_path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE stock_movements (id INTEGER PRIMARY KEY, quantity NUMERIC NOT NULL)"))
        connection.execute(text("INSERT INTO stock_movements (id, quantity) VALUES (1, 2)"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert "unit_cost_at_movement" in {
            column["name"] for column in inspect(connection).get_columns("stock_movements")
        }
        assert connection.execute(text(
            "SELECT quantity, unit_cost_at_movement FROM stock_movements WHERE id=1"
        )).one() == (2, None)
        connection.execute(text("INSERT INTO stock_movements (id, quantity, unit_cost_at_movement) VALUES (2, 1, 0)"))
        connection.execute(text("INSERT INTO stock_movements (id, quantity, unit_cost_at_movement) VALUES (3, 1, 4.25)"))
        migration.downgrade()
        assert "unit_cost_at_movement" not in {
            column["name"] for column in inspect(connection).get_columns("stock_movements")
        }
        assert connection.execute(text("SELECT id, quantity FROM stock_movements ORDER BY id")).all() == [
            (1, 2), (2, 1), (3, 1),
        ]


@pytest.fixture
def postgres_cost_sessions():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL through the disposable PostgreSQL launcher")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Cost snapshot test requires a loopback PostgreSQL URL without overrides")
    schema = f"cost_snapshot_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"},
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


def test_postgres_zero_cost_consumption_remains_known_after_repricing(postgres_cost_sessions):
    marker = uuid4().hex
    with postgres_cost_sessions() as db:
        customer = Customer(name=f"Snapshot customer {marker}")
        model = Model(code=f"SNAPSHOT-{marker}", name="Snapshot model")
        item = Item(sku=f"SNAPSHOT-{marker}", name="Free material", category="accessory", unit="pcs")
        warehouse = Warehouse(name=f"Snapshot warehouse {marker}", type="accessory_storage")
        db.add_all([customer, model, item, warehouse])
        db.flush()
        order = SalesOrder(order_no=f"SNAPSHOT-{marker}", customer_id=customer.id, total_amount=10,
                           currency="USD")
        db.add(order)
        db.flush()
        db.add(SalesOrderItem(
            sales_order_id=order.id, model_id=model.id, quantity=1, unit_price=10,
            color="black", size="M",
        ))
        production = ProductionOrder(
            production_no=f"SNAPSHOT-{marker}", production_type="client_order",
            sales_order_id=order.id, model_id=model.id, planned_quantity=1,
        )
        batch = StockBatch(
            item_id=item.id, batch_no=f"SNAPSHOT-{marker}", quantity=2,
            cost_per_unit=0, cost_currency="USD", unit="pcs", warehouse_id=warehouse.id, qc_status="passed",
        )
        db.add_all([production, batch])
        db.flush()

        consume_stock_batch(
            db, batch_id=batch.id, quantity=1, unit="pcs",
            reference_type="ProductionOrder", reference_id=production.id, user_id=None,
        )
        db.commit()
        movement = db.query(StockMovement).filter_by(
            reference_type="ProductionOrder", reference_id=production.id,
        ).one()
        assert movement.unit_cost_at_movement == Decimal("0.0000")
        assert movement.cost_currency_at_movement == "USD"
        before = order_profit(db, order.id)
        assert before["material_cost"] == 0
        assert before["gross_profit"] == 10
        assert before["material_cost_basis"] == "transaction_snapshot"

        batch.cost_per_unit = 7
        db.commit()
        assert order_profit(db, order.id) == before
