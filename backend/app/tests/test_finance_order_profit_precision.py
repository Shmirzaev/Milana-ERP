from uuid import uuid4

from app.db.session import SessionLocal
from app.models import (
    Brand,
    Customer,
    FinishedGoodsStock,
    Item,
    ModelBOM,
    Model,
    ProductionOrder,
    SalesOrder,
    SalesOrderItem,
    StockBatch,
    Warehouse,
    WasteRecord,
)
from app.services.finance import branded_stock_value, order_profit


def test_order_profit_uses_decimal_for_fractional_revenue():
    with SessionLocal() as db:
        customer = Customer(name=f"Profit precision {uuid4().hex}")
        db.add(customer)
        db.flush()
        order = SalesOrder(
            order_no=f"PROFIT-{uuid4().hex}",
            customer_id=customer.id,
            total_amount=1.3,
        )
        db.add(order)
        db.flush()
        model = Model(code=f"PROFIT-MODEL-{uuid4().hex}", name="Profit precision model")
        db.add(model)
        db.flush()
        item = Item(
            sku=f"PROFIT-ITEM-{uuid4().hex}",
            name="Profit precision material",
            category="material",
            unit="kg",
            composition_json=[],
        )
        db.add(item)
        db.flush()
        warehouse = db.query(Warehouse).order_by(Warehouse.id.asc()).first()
        db.add_all([
            SalesOrderItem(
                sales_order_id=order.id,
                model_id=model.id,
                quantity=7,
                unit_price="0.10",
                color="black",
                size="M",
            ),
            SalesOrderItem(
                sales_order_id=order.id,
                model_id=model.id,
                quantity=3,
                unit_price="0.20",
                color="black",
                size="L",
            ),
        ])
        production = ProductionOrder(
            production_no=f"PO-PROFIT-{uuid4().hex}",
            production_type="client_order",
            sales_order_id=order.id,
            model_id=model.id,
            planned_quantity=3,
        )
        db.add(production)
        db.flush()
        db.add(ModelBOM(
            model_id=model.id,
            item_id=item.id,
            quantity_per_piece="0.10",
            unit="kg",
            waste_percent="10.00",
        ))
        db.add(StockBatch(
            item_id=item.id,
            batch_no=f"BATCH-PROFIT-{uuid4().hex}",
            quantity=10,
            unit="kg",
            cost_per_unit="0.20",
            warehouse_id=warehouse.id,
        ))
        db.add(WasteRecord(
            production_order_id=production.id,
            waste_type="fabric",
            quantity="0.50",
            unit="kg",
            estimated_value="0.10",
        ))
        db.commit()

        result = order_profit(db, order.id)

    assert result["revenue"] == 1.3
    assert result["material_cost"] == 0.066
    assert result["waste_cost"] == 0.1
    assert result["gross_profit"] == 1.134


def test_branded_stock_value_uses_decimal_intermediates():
    with SessionLocal() as db:
        model = Model(code=f"STOCK-PRECISION-{uuid4().hex}", name="Stock precision model")
        brand = Brand(name=f"Stock precision brand {uuid4().hex}")
        db.add_all([model, brand])
        db.flush()
        db.add_all([
            FinishedGoodsStock(model_id=model.id, brand_id=brand.id, color="black", size="S", quantity=3, available_qty=3, cost_per_piece="0.10", selling_price="1.00", status="available"),
            FinishedGoodsStock(model_id=model.id, brand_id=brand.id, color="black", size="M", quantity=7, available_qty=7, cost_per_piece="0.20", selling_price="1.00", status="available"),
        ])
        db.commit()
        value = branded_stock_value(db)

    assert isinstance(value, float)
    assert value == 1.7
