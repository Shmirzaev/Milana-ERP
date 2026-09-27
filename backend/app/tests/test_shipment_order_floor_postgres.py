"""Disposable PostgreSQL plan check for the combined shipment order floor."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes.shipments import shipment_order_floor
from app.db.base import Base
from app.models import Customer, SalesOrder, Shipment


@pytest.fixture(scope="module")
def floor_postgres_sessions():
    raw = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw:
        pytest.skip("Requires disposable PostgreSQL launcher")
    url = make_url(raw)
    assert url.get_backend_name() == "postgresql"
    assert url.host in {"127.0.0.1", "localhost", "::1"}
    assert not url.query
    schema = f"shipment_floor_{uuid4().hex}"
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def test_postgres_order_floor_limits_identities_before_hydration(floor_postgres_sessions):
    with floor_postgres_sessions() as db:
        customer = Customer(name="PG shipment floor customer")
        db.add(customer)
        db.flush()
        orders = [
            SalesOrder(order_no=f"PERF35-PG-FLOOR-{index:04d}", customer_id=customer.id, status="confirmed")
            for index in range(421)
        ]
        db.add_all(orders)
        db.flush()
        active = Shipment(sales_order_id=orders[0].id, shipment_no="PERF35-PG-OPEN", status="created")
        shipped = Shipment(sales_order_id=orders[1].id, shipment_no="PERF35-PG-SHIPPED", status="shipped")
        db.add_all((active, shipped))
        db.commit()

        selects = []

        def capture(_connection, _cursor, statement, parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append((statement, parameters))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            result = shipment_order_floor(
                db, object(), page=1, page_size=50, target_sales_order_id=orders[0].id,
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        assert result["total"] == 420
        assert len(result["rows"]) == 50
        assert result["pinned"]["id"] == orders[0].id
        assert len(selects) <= 7, selects
        identity_sql, identity_parameters = next(
            (statement, parameters) for statement, parameters in selects
            if "ORDER BY sales_orders.id DESC" in statement and "LIMIT" in statement
        )
        plan = "\n".join(row[0] for row in db.connection().exec_driver_sql(
            "EXPLAIN (ANALYZE, BUFFERS) " + identity_sql,
            identity_parameters,
        ))
        assert "Limit" in plan
        assert "rows=50 loops=1" in plan.splitlines()[0]
