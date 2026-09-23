from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.shipments import _ready_packages_for_sales_order
from app.db.session import SessionLocal
from app.models import (
    FinishedGoodsStock,
    Model,
    Package,
    ProductionOrder,
    SalesOrder,
    StockReservation,
)


@pytest.mark.parametrize("package_count", [1, 50, 401])
def test_ready_packages_merges_reserved_and_order_owned_rows_in_one_select(package_count):
    suffix = uuid4().hex[:8].upper()
    with SessionLocal() as db:
        model = Model(code=f"PERF35-SHIP-{suffix}", name=f"Ready package model {suffix}")
        db.add(model)
        db.flush()
        order = SalesOrder(order_no=f"PERF35-SHIP-SO-{suffix}", status="ready")
        db.add(order)
        db.flush()
        production_order = ProductionOrder(
            production_no=f"PERF35-SHIP-PO-{suffix}",
            production_type="client_order",
            model_id=model.id,
            sales_order_id=order.id,
            planned_quantity=package_count,
        )
        db.add(production_order)
        db.flush()
        packages = [
            Package(
                package_no=f"PERF35-SHIP-P-{suffix}-{index:04d}",
                barcode=f"PERF35-SHIP-BC-{suffix}-{index:04d}",
                production_order_id=production_order.id,
                sales_order_id=None if index % 2 == 0 else order.id,
                model_id=model.id,
                color="navy",
                total_quantity=1,
                capacity=60,
                status="reserved" if index % 2 == 0 else "received_in_storage",
            )
            for index in range(package_count)
        ]
        db.add_all(packages)
        db.flush()
        reserved_packages = packages[::2]
        stocks = [
            FinishedGoodsStock(
                package_id=package.id,
                model_id=model.id,
                color="navy",
                size="M",
                quantity=1,
                available_qty=0,
                reserved_qty=1,
                status="reserved",
            )
            for package in reserved_packages
        ]
        db.add_all(stocks)
        db.flush()
        db.add_all(
            StockReservation(
                sales_order_id=order.id,
                finished_goods_stock_id=stock.id,
                package_id=package.id,
                quantity=1,
            )
            for package, stock in zip(reserved_packages, stocks, strict=True)
        )
        db.commit()
        order_id = order.id
        expected_package_ids = [package.id for package in packages]
        model_code = model.code

    with SessionLocal() as db:
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            rows = _ready_packages_for_sales_order(db, order_id)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert [package.id for package, _model in rows] == expected_package_ids
    assert [row.code for _package, row in rows] == [model_code] * package_count
    assert len(statements) == 1, statements
    assert "from stock_reservations" in statements[0]
    assert "from packages" in statements[0]
