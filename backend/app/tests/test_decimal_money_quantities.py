from decimal import Decimal
from uuid import uuid4

from app.db.session import SessionLocal
from app.models import Brand, FinishedGoodsStock, Item, Model, StockBatch, StockMovement, Warehouse
from app.services.finance import branded_stock_value
from app.services.inventory import stock_summary


def test_finance_and_stock_summary_keep_numeric_values_as_decimals(client, auth_headers):
    """Money and quantity aggregation must not introduce binary-float rounding."""
    suffix = uuid4().hex
    with SessionLocal() as db:
        model = db.query(Model).first()
        brand = db.query(Brand).first()
        warehouse = db.query(Warehouse).first()
        assert model and brand and warehouse

        db.add(
            FinishedGoodsStock(
                model_id=model.id,
                brand_id=brand.id,
                color="decimal-test",
                size="M",
                quantity=3,
                available_qty=3,
                reserved_qty=0,
                sold_qty=0,
                cost_per_piece=Decimal("0.10"),
                selling_price=Decimal("0.10"),
                status="available",
            )
        )
        item = Item(
            sku=f"DEC-{suffix}",
            name="Decimal quantity test",
            category="fabric",
            unit="m",
            default_cost=Decimal("0"),
            reorder_level=Decimal("0"),
            track_batch=True,
            is_active=True,
        )
        db.add(item)
        db.flush()
        db.add(
            StockBatch(
                item_id=item.id,
                batch_no=f"DEC-{suffix}",
                quantity=Decimal("0"),
                unit="m",
                cost_per_unit=Decimal("0"),
                warehouse_id=warehouse.id,
                qc_status="passed",
            )
        )
        db.add_all(
            [
                StockMovement(movement_type="return", item_id=item.id, quantity=Decimal("0.10"), unit="m"),
                StockMovement(movement_type="produce", item_id=item.id, quantity=Decimal("0.20"), unit="m"),
            ]
        )
        db.commit()

        assert branded_stock_value(db) == Decimal("0.30")
        row = next(row for row in stock_summary(db) if row["item_id"] == item.id)
        assert row["quantity"] == Decimal("0.30")
        assert row["available_quantity"] == Decimal("0.30")

    response = client.get("/api/finance/branded-stock-value", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["value"] == 0.3
