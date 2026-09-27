from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.sales import _reserve_branded_stock, _stock_rows_by_variant, _stock_variant_key
from app.models import Brand, Collection, FinishedGoodsStock, Model, SalesOrder, User
from app.tests.conftest import TestSessionLocal


def _reservation_case(variant_count: int):
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        current = db.query(User).order_by(User.id).first()
        assert current is not None
        brand = Brand(name=f"PERF26 query brand {marker}")
        db.add(brand)
        db.flush()
        collection = Collection(
            brand_id=brand.id,
            name=f"PERF26 query collection {marker}",
            year=2026,
        )
        model = Model(
            code=f"PERF26-Q-{marker}",
            name=f"PERF26 query model {marker}",
            product_type="shirt",
            brand_id=brand.id,
        )
        order = SalesOrder(
            order_no=f"PERF26-Q-SO-{marker}",
            order_type="branded_stock_sale",
            status="draft",
            created_by=current.id,
        )
        db.add_all([collection, model, order])
        db.flush()
        model.collection_id = collection.id
        colors = [f"color-{index:04d}" for index in range(variant_count)]
        db.add_all(
            [
                FinishedGoodsStock(
                    model_id=model.id,
                    brand_id=brand.id,
                    collection_id=collection.id,
                    color=color,
                    size="M",
                    quantity=1,
                    available_qty=1,
                    reserved_qty=0,
                    sold_qty=0,
                    status="available",
                )
                for color in colors
            ]
        )
        db.commit()
        current_id = int(current.id)
        order_id = int(order.id)
        model_id = int(model.id)
        brand_id = int(brand.id)

    lines = [
        SimpleNamespace(
            model_id=model_id,
            brand_id=brand_id,
            color=color,
            size="M",
            quantity=1,
            requested_pack_count=None,
        )
        for color in colors
    ]
    return current_id, order_id, lines


def _selects(bind, callback):
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select"):
            statements.append(normalized)

    event.listen(bind, "before_cursor_execute", capture)
    try:
        result = callback()
    finally:
        event.remove(bind, "before_cursor_execute", capture)
    return result, statements


@pytest.mark.parametrize("variant_count", [1, 50, 401])
def test_branded_reservation_variant_stock_reads_are_bounded(variant_count):
    current_id, order_id, lines = _reservation_case(variant_count)
    with TestSessionLocal() as db:
        current = db.get(User, current_id)
        order = db.get(SalesOrder, order_id)
        assert current is not None
        assert order is not None

        (reservations, shortages), statements = _selects(
            db.bind,
            lambda: _reserve_branded_stock(
                db,
                so=order,
                current=current,
                lines=lines,
                notify_shortage=False,
            ),
        )

    stock_selects = [statement for statement in statements if " from finished_goods_stock " in statement]
    expected_variant_reads = (variant_count + 199) // 200
    assert len(reservations) == variant_count
    assert shortages == []
    assert len(statements) == expected_variant_reads + 2
    assert len(stock_selects) == expected_variant_reads + 1


def test_batched_variant_reads_preserve_wildcards_brand_scope_and_order():
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        first_brand = Brand(name=f"PERF26 first brand {marker}")
        second_brand = Brand(name=f"PERF26 second brand {marker}")
        db.add_all([first_brand, second_brand])
        db.flush()
        first_collection = Collection(
            brand_id=first_brand.id,
            name=f"PERF26 first collection {marker}",
            year=2026,
        )
        second_collection = Collection(
            brand_id=second_brand.id,
            name=f"PERF26 second collection {marker}",
            year=2026,
        )
        model = Model(
            code=f"PERF26-MATCH-{marker}",
            name=f"PERF26 match model {marker}",
            product_type="shirt",
        )
        db.add_all([first_collection, second_collection, model])
        db.flush()
        rows = [
            FinishedGoodsStock(
                model_id=model.id,
                brand_id=brand.id,
                collection_id=collection.id,
                color=color,
                size=size,
                quantity=1,
                available_qty=available,
                reserved_qty=0,
                sold_qty=0,
                status="available",
            )
            for brand, collection, color, size, available in (
                (first_brand, first_collection, "navy", "M", 1),
                (first_brand, first_collection, "navy", "L", 1),
                (first_brand, first_collection, "red", "M", 1),
                (second_brand, second_collection, "navy", "M", 1),
                (first_brand, first_collection, "navy", "M", 0),
            )
        ]
        db.add_all(rows)
        db.flush()
        exact_key = _stock_variant_key(model.id, "navy", "M", first_brand.id)
        any_color_key = _stock_variant_key(model.id, "any", "M", first_brand.id)
        any_size_key = _stock_variant_key(model.id, "navy", "*", first_brand.id)
        any_brand_key = _stock_variant_key(model.id, "navy", "M", None)

        result = _stock_rows_by_variant(
            db,
            [any_brand_key, any_size_key, exact_key, any_color_key],
        )

        assert [row.id for row in result[exact_key]] == [rows[0].id]
        assert [row.id for row in result[any_color_key]] == [rows[0].id, rows[2].id]
        assert [row.id for row in result[any_size_key]] == [rows[0].id, rows[1].id]
        assert [row.id for row in result[any_brand_key]] == [rows[0].id, rows[3].id]
