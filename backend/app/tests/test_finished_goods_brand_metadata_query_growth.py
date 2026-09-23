from uuid import uuid4

import pytest
from sqlalchemy import event

from app.models import Brand, Collection, FinishedGoodsStock, Model, SalesOrder, SalesOrderItem
from app.services.finished_goods import repair_missing_brand_metadata
from app.tests.conftest import TestSessionLocal


def _seed_missing_stock_metadata(stock_count: int) -> tuple[int, int, int, int, list[int]]:
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        brand = Brand(name=f"PERF35-repair-brand-{marker}")
        model = Model(
            code=f"PERF35-REPAIR-M-{marker}",
            name="Repair metadata model",
            status="approved",
        )
        db.add_all([brand, model])
        db.flush()
        collection = Collection(
            brand_id=brand.id,
            name=f"PERF35-repair-collection-{marker}",
            year=2026,
        )
        order = SalesOrder(order_no=f"PERF35-REPAIR-SO-{marker}")
        db.add_all([collection, order])
        db.flush()
        db.add(SalesOrderItem(
            sales_order_id=order.id,
            model_id=model.id,
            brand_id=brand.id,
            collection_id=collection.id,
            color="navy",
            size="M",
            quantity=stock_count,
            unit_price=1,
        ))
        stocks = [
            FinishedGoodsStock(
                sales_order_id=order.id,
                model_id=model.id,
                color="navy",
                size=f"M-{index:04d}",
                quantity=1,
                available_qty=1,
                status="available",
            )
            for index in range(stock_count)
        ]
        db.add_all(stocks)
        db.commit()
        return int(model.id), int(order.id), int(brand.id), int(collection.id), [int(row.id) for row in stocks]


@pytest.mark.parametrize("stock_count", [1, 50, 401])
def test_brand_metadata_repair_reuses_sales_order_model_references(stock_count):
    model_id, order_id, brand_id, collection_id, stock_ids = _seed_missing_stock_metadata(stock_count)
    with TestSessionLocal() as db:
        statements: list[str] = []
        stock_statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select") and " from sales_order_items " in normalized:
                statements.append(normalized)
            if normalized.startswith("select") and " from finished_goods_stock " in normalized:
                stock_statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            updated = repair_missing_brand_metadata(db, model_ids={model_id})
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        rows = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.id.in_(stock_ids)).all()

    print(f"Finished-goods metadata repair {stock_count}: {len(statements)} sales-item SELECTs")
    assert updated == stock_count
    assert len(statements) == 1
    assert len(stock_statements) == 1, stock_statements
    selected_columns = stock_statements[0].split(" from finished_goods_stock", 1)[0]
    for needed in (
        "finished_goods_stock.id",
        "finished_goods_stock.model_id",
        "finished_goods_stock.sales_order_id",
        "finished_goods_stock.production_order_id",
        "finished_goods_stock.package_id",
        "finished_goods_stock.brand_id",
        "finished_goods_stock.collection_id",
    ):
        assert needed in selected_columns
    assert "finished_goods_stock.created_at" not in selected_columns
    assert "finished_goods_stock.updated_at" not in selected_columns
    assert all(row.sales_order_id == order_id for row in rows)
    assert all(row.collection_id == collection_id for row in rows)
    assert all(row.brand_id == brand_id for row in rows)
