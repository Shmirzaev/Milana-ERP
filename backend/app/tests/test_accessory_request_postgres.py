from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import (
    CuttingRecord,
    Department,
    Item,
    ManualAccessoryIssue,
    MaterialReservation,
    Model,
    ModelBOM,
    PackagingRecord,
    ProductionOrder,
    ProductionOrderItem,
    SalesOrder,
    SewingRecord,
    StockBatch,
    StockMovement,
    Warehouse,
    WorkOrder,
)
from app.services.inventory import accessory_issue_requests


@pytest.fixture(scope="module")
def accessory_request_postgres_sessions():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL through the disposable PostgreSQL launcher")
    url = make_url(raw_url)
    if (
        url.get_backend_name() != "postgresql"
        or url.host not in {"127.0.0.1", "localhost", "::1"}
        or url.query
    ):
        pytest.fail("Accessory request tests require a loopback PostgreSQL URL without overrides")

    schema = f"accessory_request_{uuid4().hex}"
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
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_stock_movements_reference "
                "ON stock_movements (reference_type, reference_id)"
            )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_stock_batches_item_warehouse "
                "ON stock_batches (item_id, warehouse_id)"
            )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_production_orders_status_id "
                "ON production_orders (status, id)"
            )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_work_orders_production_status "
                "ON work_orders (production_order_id, status)"
            )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_model_bom_model_id_id "
                "ON model_bom (model_id, id DESC)"
            )
        yield sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def _postgres_family(db, count: int) -> tuple[int, list[int]]:
    marker = uuid4().hex[:8]
    model = Model(code=f"PERF02-PG-{marker}", name=f"Accessory queue {marker}")
    item = Item(
        sku=f"PERF02-PG-{marker}",
        name=f"Accessory {marker}",
        category="accessory",
        unit="pcs",
        composition_json=[],
    )
    db.add_all([model, item])
    db.flush()
    db.add(ModelBOM(
        model_id=model.id,
        item_id=item.id,
        quantity_per_piece=1,
        unit="pcs",
        waste_percent=0,
    ))
    orders = [
        ProductionOrder(
            production_no=f"PERF02-PG-{marker}-{number:04d}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=10,
            status="new",
        )
        for number in range(count)
    ]
    db.add_all(orders)
    db.commit()
    return int(model.id), [int(order.id) for order in orders]


@pytest.mark.parametrize("order_count", [1, 50, 401])
def test_postgres_accessory_request_derives_before_limit_with_constant_round_trips(
    accessory_request_postgres_sessions,
    order_count,
):
    sessions = accessory_request_postgres_sessions
    with sessions() as db:
        model_id, _order_ids = _postgres_family(db, order_count)
        expected = accessory_issue_requests(db, model_id=model_id)
        statements: list[tuple[str, object]] = []

        def capture(_connection, _cursor, statement, parameters, _context, _executemany):
            if statement.lstrip().upper().startswith(("SELECT", "WITH")):
                statements.append((statement, parameters))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            rows, total = accessory_issue_requests(
                db,
                model_id=model_id,
                page=1,
                page_size=10,
                include_total=True,
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert rows == expected[:10]
    assert total == order_count
    assert len(statements) == 1
    assert "page_rows AS MATERIALIZED" in statements[0][0]


def _postgres_mixed_case(db) -> tuple[int, int, str]:
    marker = uuid4().hex[:8]
    model = Model(code=f"PERF02-PG-MIX-{marker}", name=f"Mixed queue {marker}")
    button = Item(
        sku=f"BUTTON-{marker}",
        name=f"Button {marker}",
        category="accessory",
        unit="pcs",
        composition_json=[],
    )
    carton = Item(
        sku=f"CARTON-{marker}",
        name=f"Carton {marker}",
        category="packaging",
        unit="box",
        composition_json=[],
    )
    db.add_all([model, button, carton])
    db.flush()
    db.add_all([
        ModelBOM(
            model_id=model.id,
            item_id=button.id,
            size="M",
            quantity_per_piece=2,
            unit="pcs",
            waste_percent=0,
        ),
        ModelBOM(
            model_id=model.id,
            item_id=button.id,
            size="L",
            quantity_per_piece=3,
            unit="pcs",
            waste_percent=0,
        ),
        ModelBOM(
            model_id=model.id,
            item_id=carton.id,
            quantity_per_piece=1,
            unit="box",
            waste_percent=0,
        ),
    ])
    sales_order = SalesOrder(
        order_no=f"SO-PERF02-PG-{marker}",
        order_type="client_order",
        status="in_production",
        total_amount=0,
    )
    db.add(sales_order)
    db.flush()
    order = ProductionOrder(
        production_no=f"PERF02-PG-MIX-{marker}",
        production_type="branded_stock",
        sales_order_id=sales_order.id,
        model_id=model.id,
        planned_quantity=6,
        status="new",
    )
    db.add(order)
    db.flush()
    db.add_all([
        ProductionOrderItem(
            production_order_id=order.id,
            model_id=model.id,
            color="white",
            size="M",
            planned_quantity=4,
        ),
        ProductionOrderItem(
            production_order_id=order.id,
            model_id=model.id,
            color="black",
            size="L",
            planned_quantity=2,
        ),
    ])
    warehouse = Warehouse(name=f"PERF02 PG {marker}", type="main")
    department = Department(name=f"PERF02 PG {marker}", code=f"P2{marker}")
    db.add_all([warehouse, department])
    db.flush()
    batch = StockBatch(
        item_id=button.id,
        batch_no=f"PERF02-PG-{marker}",
        quantity=12,
        unit="pcs",
        cost_per_unit=1,
        warehouse_id=warehouse.id,
        qc_status="passed",
    )
    work_order = WorkOrder(
        production_order_id=order.id,
        department_id=department.id,
        operation="cutting",
        status="waiting",
        planned_input_qty=6,
        planned_output_qty=6,
    )
    db.add_all([batch, work_order])
    db.flush()
    cutting = CuttingRecord(work_order_id=work_order.id)
    sewing = SewingRecord(work_order_id=work_order.id)
    packaging = PackagingRecord(work_order_id=work_order.id)
    db.add_all([cutting, sewing, packaging])
    db.flush()
    db.add_all([
        MaterialReservation(
            reservation_no=f"PERF02-PG-{marker}",
            production_order_id=order.id,
            item_id=button.id,
            stock_batch_id=batch.id,
            warehouse_id=warehouse.id,
            reserved_quantity=2,
            unit="pcs",
            status="reserved",
            reservation_type="accessory",
            source="manual",
        ),
        StockMovement(
            movement_type="issue",
            item_id=button.id,
            batch_id=batch.id,
            from_warehouse_id=warehouse.id,
            quantity=3,
            unit="pcs",
            reference_type="ProductionOrder",
            reference_id=order.id,
        ),
        StockMovement(
            movement_type="consume",
            item_id=button.id,
            batch_id=batch.id,
            from_warehouse_id=warehouse.id,
            quantity=1,
            unit="pcs",
            reference_type="WorkOrder",
            reference_id=work_order.id,
        ),
        StockMovement(
            movement_type="issue",
            item_id=button.id,
            batch_id=batch.id,
            from_warehouse_id=warehouse.id,
            quantity=0.25,
            unit="pcs",
            reference_type="CuttingRecord",
            reference_id=cutting.id,
        ),
        StockMovement(
            movement_type="consume",
            item_id=button.id,
            batch_id=batch.id,
            from_warehouse_id=warehouse.id,
            quantity=0.25,
            unit="pcs",
            reference_type="SewingRecord",
            reference_id=sewing.id,
        ),
        StockMovement(
            movement_type="issue",
            item_id=button.id,
            batch_id=batch.id,
            from_warehouse_id=warehouse.id,
            quantity=0.25,
            unit="pcs",
            reference_type="PackagingRecord",
            reference_id=packaging.id,
        ),
        StockMovement(
            movement_type="return",
            item_id=button.id,
            to_warehouse_id=warehouse.id,
            quantity=3,
            unit="pcs",
            reference_type="StockAdjustment",
        ),
        StockMovement(
            movement_type="waste",
            item_id=button.id,
            from_warehouse_id=warehouse.id,
            quantity=1,
            unit="pcs",
            reference_type="StockAdjustment",
        ),
        ManualAccessoryIssue(
            production_order_id=order.id,
            item_id=button.id,
            item_sku=button.sku,
            item_name=button.name,
            quantity=0.5,
            unit="pcs",
        ),
        ManualAccessoryIssue(
            production_order_id=order.id,
            item_sku=f"  {carton.sku.lower()}  ",
            item_name="Legacy carton label",
            quantity=6,
            unit="box",
        ),
    ])
    db.commit()
    return int(model.id), int(order.id), model.code


def _assert_request_rows_equal(actual: list[dict], expected: list[dict]) -> None:
    quantity_fields = {
        "required_quantity",
        "issued_quantity",
        "remaining_quantity",
        "available_quantity",
        "shortage",
    }
    assert len(actual) == len(expected)
    for actual_row, expected_row in zip(actual, expected, strict=True):
        assert actual_row.keys() == expected_row.keys()
        for key in actual_row:
            if key in quantity_fields:
                assert actual_row[key] == pytest.approx(expected_row[key], abs=1e-12)
            else:
                assert actual_row[key] == expected_row[key]


def test_postgres_accessory_request_matches_legacy_bom_issue_stock_and_completion_semantics(
    accessory_request_postgres_sessions,
):
    sessions = accessory_request_postgres_sessions
    with sessions() as db:
        model_id, order_id, model_code = _postgres_mixed_case(db)
        expected_all = accessory_issue_requests(
            db,
            production_order_id=order_id,
            include_complete=True,
        )
        expected_incomplete = accessory_issue_requests(db, production_order_id=order_id)

        actual_all, all_total = accessory_issue_requests(
            db,
            production_order_id=order_id,
            q=model_code.replace("-", ""),
            include_complete=True,
            page=1,
            page_size=50,
            include_total=True,
        )
        actual_incomplete, incomplete_total = accessory_issue_requests(
            db,
            production_order_id=order_id,
            page=1,
            page_size=50,
            include_total=True,
        )
        empty, empty_total = accessory_issue_requests(
            db,
            model_id=model_id,
            include_complete=True,
            page=99,
            page_size=50,
            include_total=True,
        )

    assert actual_all == expected_all
    assert all_total == len(expected_all)
    assert actual_incomplete == expected_incomplete
    assert incomplete_total == len(expected_incomplete)
    assert empty == []
    assert empty_total == len(expected_all)


def test_postgres_accessory_request_adversarial_parity(
    accessory_request_postgres_sessions,
):
    sessions = accessory_request_postgres_sessions
    with sessions() as db:
        marker = uuid4().hex[:8]
        model = Model(code=f"PERF02-ADV-{marker}", name=f"Adversarial {marker}")
        upper = Item(
            sku=f"A-CASE-{marker}",
            name=f"Upper case {marker}",
            category="accessory",
            unit="pcs",
            composition_json=[],
        )
        lower = Item(
            sku=f"a-case-{marker}",
            name=f"Lower case {marker}",
            category="accessory",
            unit="pcs",
            composition_json=[],
        )
        decimal_item = Item(
            sku=f"DEC-{marker}",
            name=f"Decimal legacy alias {marker}",
            category="accessory",
            unit="pcs",
            composition_json=[],
        )
        epsilon_open = Item(
            sku=f"EPS-OPEN-{marker}",
            name=f"Epsilon open {marker}",
            category="accessory",
            unit="pcs",
            composition_json=[],
        )
        epsilon_ready = Item(
            sku=f"EPS-READY-{marker}",
            name=f"Epsilon ready {marker}",
            category="accessory",
            unit="pcs",
            composition_json=[],
        )
        db.add_all([model, upper, lower, decimal_item, epsilon_open, epsilon_ready])
        db.flush()
        db.add_all([
            ModelBOM(
                model_id=model.id,
                item_id=upper.id,
                quantity_per_piece=1,
                unit="pcs",
                waste_percent=0,
            ),
            ModelBOM(
                model_id=model.id,
                item_id=lower.id,
                quantity_per_piece=1,
                unit="pcs",
                waste_percent=0,
            ),
            ModelBOM(
                model_id=model.id,
                item_id=decimal_item.id,
                quantity_per_piece=0.1,
                unit="   ",
                waste_percent=0,
            ),
            ModelBOM(
                model_id=model.id,
                item_id=decimal_item.id,
                quantity_per_piece=0.2,
                unit="pcs",
                waste_percent=0,
            ),
            ModelBOM(
                model_id=model.id,
                item_id=epsilon_open.id,
                quantity_per_piece=0.0001,
                unit="pcs",
                waste_percent=0.01,
            ),
            ModelBOM(
                model_id=model.id,
                item_id=epsilon_ready.id,
                quantity_per_piece=1,
                unit="pcs",
                waste_percent=0.01,
            ),
        ])
        order = ProductionOrder(
            production_no=f"PERF02-ADV-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=1,
            status="new",
        )
        db.add(order)
        db.flush()
        db.add_all([
            StockMovement(
                movement_type="issue",
                item_id=decimal_item.id,
                quantity=0.1,
                unit="   ",
                reference_type="ProductionOrder",
                reference_id=order.id,
            ),
            StockMovement(
                movement_type="return",
                item_id=decimal_item.id,
                quantity=99,
                unit="pcs",
                reference_type="ProductionOrderAccessoryReturn",
                reference_id=order.id,
            ),
            ManualAccessoryIssue(
                production_order_id=order.id,
                item_sku=f"  {decimal_item.sku.lower()}  ",
                item_name="Legacy-only-label",
                quantity=0.1,
                unit=" pcs ",
            ),
            ManualAccessoryIssue(
                production_order_id=order.id,
                item_sku=None,
                item_name=f"  {decimal_item.name.upper()}   ",
                quantity=0.05,
                unit="pcs",
            ),
            ManualAccessoryIssue(
                production_order_id=order.id,
                item_id=epsilon_open.id,
                item_sku=epsilon_open.sku,
                item_name=epsilon_open.name,
                quantity=0.0001,
                unit="pcs",
            ),
            ManualAccessoryIssue(
                production_order_id=order.id,
                item_id=epsilon_ready.id,
                item_sku=epsilon_ready.sku,
                item_name=epsilon_ready.name,
                quantity=1.0001,
                unit="pcs",
            ),
        ])
        db.commit()
        order_id = int(order.id)
        model_id = int(model.id)

        expected = accessory_issue_requests(
            db,
            production_order_id=order_id,
            include_complete=True,
        )
        actual, total = accessory_issue_requests(
            db,
            production_order_id=order_id,
            include_complete=True,
            page=1,
            page_size=50,
            include_total=True,
        )
        legacy_label_rows, legacy_label_total = accessory_issue_requests(
            db,
            production_order_id=order_id,
            q="legacy-only-label",
            include_complete=True,
            page=1,
            page_size=50,
            include_total=True,
        )
        hidden_ready, hidden_ready_total = accessory_issue_requests(
            db,
            production_order_id=order_id,
            q=epsilon_ready.sku,
            page=1,
            page_size=50,
            include_total=True,
        )
        visible_ready, visible_ready_total = accessory_issue_requests(
            db,
            production_order_id=order_id,
            q=epsilon_ready.sku,
            include_complete=True,
            page=1,
            page_size=50,
            include_total=True,
        )
        no_rows, no_rows_total = accessory_issue_requests(
            db,
            model_id=model_id + 10_000_000,
            page=1,
            page_size=50,
            include_total=True,
        )

    _assert_request_rows_equal(actual, expected)
    assert total == len(expected) == 5
    assert [
        row["item_sku"]
        for row in actual
        if row["item_sku"] in {upper.sku, lower.sku}
    ] == [upper.sku, lower.sku]
    decimal_row = next(row for row in actual if row["item_id"] == decimal_item.id)
    assert decimal_row["required_quantity"] == pytest.approx(0.3)
    assert decimal_row["issued_quantity"] == pytest.approx(0.3)
    assert decimal_row["available_quantity"] == pytest.approx(98.9)
    assert decimal_row["remaining_quantity"] >= 0
    open_row = next(row for row in actual if row["item_id"] == epsilon_open.id)
    ready_row = next(row for row in actual if row["item_id"] == epsilon_ready.id)
    assert open_row["remaining_quantity"] > 1e-9
    assert open_row["status"] == "shortage"
    assert ready_row["remaining_quantity"] <= 1e-9
    assert ready_row["status"] == "ready"
    assert legacy_label_rows == []
    assert legacy_label_total == 0
    assert hidden_ready == []
    assert hidden_ready_total == 0
    assert visible_ready == [ready_row]
    assert visible_ready_total == 1
    assert no_rows == []
    assert no_rows_total == 0
    assert ModelBOM.__table__.c.unit.nullable is False
    assert StockMovement.__table__.c.unit.nullable is False
    assert ManualAccessoryIssue.__table__.c.unit.nullable is False


def test_postgres_accessory_request_preserves_global_status_order_across_pages(
    accessory_request_postgres_sessions,
):
    sessions = accessory_request_postgres_sessions
    with sessions() as db:
        model_id, order_ids = _postgres_family(db, 2)
        item = (
            db.query(Item)
            .join(ModelBOM, ModelBOM.item_id == Item.id)
            .filter(ModelBOM.model_id == model_id)
            .one()
        )
        db.add(ManualAccessoryIssue(
            production_order_id=order_ids[0],
            item_id=item.id,
            item_sku=item.sku,
            item_name=item.name,
            quantity=10,
            unit="pcs",
        ))
        db.commit()
        expected = accessory_issue_requests(
            db,
            model_id=model_id,
            include_complete=True,
        )
        first, first_total = accessory_issue_requests(
            db,
            model_id=model_id,
            include_complete=True,
            page=1,
            page_size=1,
            include_total=True,
        )
        second, second_total = accessory_issue_requests(
            db,
            model_id=model_id,
            include_complete=True,
            page=2,
            page_size=1,
            include_total=True,
        )

    assert first + second == expected
    assert first_total == second_total == 2
    assert first[0]["status"] == "shortage"
    assert first[0]["production_order_id"] == order_ids[1]
    assert second[0]["status"] == "ready"
    assert second[0]["production_order_id"] == order_ids[0]


def test_postgres_accessory_request_plan_limits_after_global_classification_and_uses_indexes(
    accessory_request_postgres_sessions,
):
    sessions = accessory_request_postgres_sessions
    with sessions() as db:
        model_id, order_ids = _postgres_family(db, 401)
        marker = uuid4().hex[:8]
        department = Department(name=f"PERF02 plan {marker}", code=f"PX{marker}")
        db.add(department)
        db.flush()
        db.bulk_insert_mappings(
            WorkOrder,
            [
                {
                    "production_order_id": order_id,
                    "department_id": department.id,
                    "operation": "cutting",
                    "status": "waiting",
                    "planned_input_qty": 1,
                    "planned_output_qty": 1,
                }
                for order_id in order_ids
            ],
        )
        first_work_order = (
            db.query(WorkOrder)
            .filter(WorkOrder.production_order_id == order_ids[0])
            .one()
        )
        item_id = (
            db.query(ModelBOM.item_id)
            .filter(ModelBOM.model_id == model_id)
            .scalar()
        )
        db.add(StockMovement(
            movement_type="issue",
            item_id=item_id,
            quantity=0.1,
            unit="pcs",
            reference_type="WorkOrder",
            reference_id=first_work_order.id,
        ))
        db.commit()
        statements: list[tuple[str, object]] = []

        def capture(_connection, _cursor, statement, parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("WITH"):
                statements.append((statement, parameters))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            rows, total = accessory_issue_requests(
                db,
                model_id=model_id,
                page=1,
                page_size=10,
                include_total=True,
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

        assert len(statements) == 1
        statement, parameters = statements[0]
        plan = db.connection().exec_driver_sql(
            f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {statement}",
            parameters,
        ).scalars().all()
        indexes = set(db.execute(text(
            "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()"
        )).scalars())

    assert len(rows) == 10
    assert total == 401
    assert any("Limit  (" in line and "actual" in line for line in plan), plan
    assert any("CTE filtered" in line for line in plan), plan
    assert any("ix_work_orders_production_status" in line for line in plan), plan
    assert any("ix_stock_batches_item_warehouse" in line for line in plan), plan
    assert not any("Rows Removed by Join Filter: 160400" in line for line in plan), plan
    assert {
        "ix_stock_movements_reference",
        "ix_stock_batches_item_warehouse",
        "ix_production_orders_status_id",
        "ix_work_orders_production_status",
        "ix_model_bom_model_id_id",
    }.issubset(indexes)
    evidence = [
        line
        for line in plan
        if any(token in line for token in (
            "CTE filtered",
            "Limit  (",
            "ix_work_orders_production_status",
            "ix_stock_batches_item_warehouse",
            "Execution Time:",
        ))
    ]
    print("PERF02 PostgreSQL EXPLAIN evidence\n" + "\n".join(evidence))
