import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import Department, Model, ProductionBatch, ProductionOrder, WorkOrder
from app.services.traceability import _batch_work_order_context


@pytest.fixture(scope="module")
def traceability_postgres_sessions():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL traceability coverage")
    url = make_url(raw_url)
    if (
        url.get_backend_name() != "postgresql"
        or url.host not in {"127.0.0.1", "localhost", "::1"}
        or url.query
    ):
        pytest.fail("Traceability plan tests require a loopback PostgreSQL URL without overrides")

    schema = f"traceability_plan_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={
            "options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"
        },
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


def test_postgres_batch_work_order_context_uses_existing_composite_index(
    traceability_postgres_sessions,
):
    with traceability_postgres_sessions() as db:
        suffix = uuid4().hex[:8].upper()
        model = Model(code=f"PERF21-PG-M-{suffix}", name="PERF21 PostgreSQL model")
        department = Department(name=f"PERF21 PG {suffix}", code=f"P21{suffix}")
        db.add_all([model, department])
        db.flush()
        order = ProductionOrder(
            production_no=f"PERF21-PG-PO-{suffix}",
            production_type="branded_stock",
            model_id=model.id,
            status="printing",
            planned_quantity=401,
        )
        db.add(order)
        db.flush()
        batches = [
            ProductionBatch(
                production_order_id=order.id,
                batch_no=f"PERF21-PG-B-{suffix}-{number:04d}",
                batch_index=number + 1,
                planned_quantity=1,
            )
            for number in range(401)
        ]
        db.add_all(batches)
        db.flush()
        work_orders = [
            WorkOrder(
                production_order_id=order.id,
                production_batch_id=batch.id,
                department_id=department.id,
                operation="printing",
                status="waiting",
                planned_input_qty=1,
                planned_output_qty=1,
            )
            for batch in batches
        ]
        db.add_all(work_orders)
        unrelated_order = ProductionOrder(
            production_no=f"PERF21-PG-UNRELATED-{suffix}",
            production_type="branded_stock",
            model_id=model.id,
            status="printing",
            planned_quantity=5000,
        )
        db.add(unrelated_order)
        db.flush()
        db.bulk_insert_mappings(
            WorkOrder,
            [
                {
                    "production_order_id": unrelated_order.id,
                    "production_batch_id": None,
                    "department_id": department.id,
                    "operation": "printing",
                    "status": "waiting",
                    "planned_input_qty": 1,
                    "planned_output_qty": 1,
                }
                for _number in range(5000)
            ],
        )
        db.commit()
        order_id = int(order.id)
        target_batch_id = int(batches[0].id)
        target_work_order_id = int(work_orders[0].id)
        db.execute(text("ANALYZE work_orders"))

        statements = []

        def capture(_connection, _cursor, statement, parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT") and "work_orders" in statement:
                statements.append((statement, parameters))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            (rows, operations) = _batch_work_order_context(db, order_id, target_batch_id)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

        assert len(statements) == 1
        statement, parameters = statements[0]
        plan = db.connection().exec_driver_sql(
            f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {statement}",
            parameters,
        ).scalars().all()

    assert [row.id for row in rows] == [target_work_order_id]
    assert operations == {"printing"}
    assert any("uq_work_orders_order_batch_operation" in line for line in plan), plan
    assert any("Append" in line for line in plan), plan
    print("PERF21 PostgreSQL EXPLAIN\n" + "\n".join(plan))
