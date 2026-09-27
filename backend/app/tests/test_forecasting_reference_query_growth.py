from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.models import (
    Brand,
    Collection,
    Item,
    Model,
    ModelBOM,
    ProductionOrder,
    SalesOrder,
    SalesOrderItem,
    StockBatch,
    Warehouse,
)
from app.services import forecasting
from app.tests.conftest import TestSessionLocal


def _branded_reference_case(count: int) -> tuple[str, list[str]]:
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        models = [
            Model(
                code=f"PERF32-FC-{marker}-{index:04d}",
                name=f"Forecast model {index}",
                status="approved",
            )
            for index in range(count)
        ]
        brands = [
            Brand(name=f"PERF32 brand {marker} {index:04d}")
            for index in range(count)
        ]
        db.add_all([*models, *brands])
        db.flush()
        collections = [
            Collection(
                brand_id=brand.id,
                name=f"PERF32 collection {marker} {index:04d}",
                year=2026,
            )
            for index, brand in enumerate(brands)
        ]
        db.add_all(collections)
        db.flush()
        order = SalesOrder(
            order_no=f"PERF32-FC-{marker}",
            order_type="branded_stock_sale",
            status="ready",
            total_amount=count,
            created_at=datetime.now(timezone.utc),
        )
        db.add(order)
        db.flush()
        db.add_all([
            SalesOrderItem(
                sales_order_id=order.id,
                model_id=model.id,
                brand_id=brand.id,
                collection_id=collection.id,
                color=f"Color {index:04d}",
                size="M",
                quantity=1,
                unit_price=1,
                source_type="produce_new",
            )
            for index, (model, brand, collection) in enumerate(
                zip(models, brands, collections, strict=True)
            )
        ])
        db.commit()
    return marker, [model.code for model in models]


@pytest.mark.parametrize("group_count,expected_selects", [(1, 7), (50, 7), (401, 10)])
def test_branded_analysis_batches_reference_labels(group_count, expected_selects):
    marker, expected_codes = _branded_reference_case(group_count)
    with TestSessionLocal() as db:
        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            rows = forecasting._branded_stock_analysis(db)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    selected = [row for row in rows if str(row.get("model_code") or "").startswith(f"PERF32-FC-{marker}")]
    print(f"forecast groups {group_count}: {len(statements)} SELECTs")
    assert len(statements) == expected_selects
    assert [row["model_code"] for row in selected] == expected_codes
    assert [row["model_name"] for row in selected] == [
        f"Forecast model {index}" for index in range(group_count)
    ]
    assert [row["brand_name"] for row in selected] == [
        f"PERF32 brand {marker} {index:04d}" for index in range(group_count)
    ]
    assert [row["collection_name"] for row in selected] == [
        f"PERF32 collection {marker} {index:04d}" for index in range(group_count)
    ]
    assert all(row["suggested_quantity"] == 4 for row in selected)
    assert all(row["demand_source"] == "sales_orders" for row in selected)


def test_branded_analysis_preserves_optional_reference_shape():
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        model = Model(code=f"PERF32-OPTIONAL-{marker}", name="Optional references", status="approved")
        order = SalesOrder(
            order_no=f"PERF32-OPTIONAL-{marker}",
            order_type="branded_stock_sale",
            status="ready",
            total_amount=2,
        )
        db.add_all([model, order])
        db.flush()
        db.add(SalesOrderItem(
            sales_order_id=order.id,
            model_id=model.id,
            brand_id=None,
            collection_id=None,
            color="Natural",
            size="L",
            quantity=2,
            unit_price=1,
            source_type="produce_new",
        ))
        db.commit()

    with TestSessionLocal() as db:
        row = next(
            row for row in forecasting._branded_stock_analysis(db)
            if row["model_code"] == f"PERF32-OPTIONAL-{marker}"
        )

    assert row["brand_id"] is None
    assert row["brand_name"] is None
    assert row["collection_id"] is None
    assert row["collection_name"] is None


@pytest.mark.parametrize("group_count", [1, 50, 401])
def test_forecasting_dashboard_reuses_branded_demand_rows(group_count):
    marker, expected_codes = _branded_reference_case(group_count)
    with TestSessionLocal() as db:
        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            dashboard = forecasting.forecasting_dashboard(db)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    selected = [
        row for row in dashboard["branded_stock_suggestions"]
        if str(row.get("model_code") or "").startswith(f"PERF32-FC-{marker}")
    ]
    sales_demand_reads = [
        statement for statement in statements
        if "sales_orders.order_type =" in statement
    ]
    production_demand_reads = [
        statement for statement in statements
        if "production_orders.production_type =" in statement
        and " from production_order_items " in statement
    ]
    print(f"forecast dashboard groups {group_count}: {len(statements)} SELECTs")
    assert [row["model_code"] for row in selected] == expected_codes
    assert len(sales_demand_reads) == 1
    assert len(production_demand_reads) == 2
    assert len(statements) == (18 if group_count == 401 else 15)


def _planned_demand_case(count: int):
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        warehouse_id = db.query(Warehouse.id).order_by(Warehouse.id).first()[0]
        models = [
            Model(code=f"PERF32-DEMAND-{marker}-{index:04d}", name=f"Demand model {index}")
            for index in range(count)
        ]
        items = [
            Item(
                sku=f"PERF32-DEMAND-{marker}-{index:04d}",
                name=f"Demand item {index}",
                category="fabric",
                unit="kg",
                composition_json=[{"unused": "must not hydrate"}],
            )
            for index in range(count)
        ]
        db.add_all([*models, *items])
        db.flush()
        batches = [
            StockBatch(
                item_id=item.id,
                warehouse_id=warehouse_id,
                batch_no=f"PERF32-DEMAND-{marker}-{index:04d}",
                quantity=1,
                unit="kg",
                cost_per_unit=1,
                qc_status="passed",
                image_url=f"/unused/{marker}-{index}.webp",
                roll_weights_kg=[999],
            )
            for index, item in enumerate(items)
        ]
        db.add_all(batches)
        db.flush()
        orders = [
            ProductionOrder(
                production_no=f"PERF32-DEMAND-PO-{marker}-{index:04d}",
                production_type="client_order",
                model_id=model.id,
                status="planning",
                planned_quantity=3,
                printing_attachments=[{"unused": "must not hydrate"}],
            )
            for index, model in enumerate(models)
        ]
        db.add_all([
            *orders,
            *[
                ModelBOM(
                    model_id=model.id,
                    item_id=None,
                    stock_batch_id=batch.id,
                    quantity_per_piece=2,
                    unit="kg",
                )
                for model, batch in zip(models, batches, strict=True)
            ],
        ])
        db.commit()
        return [int(item.id) for item in items]


@pytest.mark.parametrize("row_count,expected_selects", [(1, 4), (50, 4), (401, 7)])
def test_planned_demand_uses_bounded_narrow_reference_maps(row_count, expected_selects):
    item_ids = _planned_demand_case(row_count)
    with TestSessionLocal() as db:
        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            demand = forecasting._planned_bom_demand(db)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert len(statements) == expected_selects
    assert [demand[(item_id, "kg")] for item_id in item_ids] == [6] * row_count
    selected = "\n".join(statements)
    assert "production_orders.printing_attachments" not in selected
    assert "items.composition_json" not in selected
    assert "stock_batches.image_url" not in selected
    assert "stock_batches.roll_weights_kg" not in selected
    assert "stock_batches.roll_lengths_m" not in selected
