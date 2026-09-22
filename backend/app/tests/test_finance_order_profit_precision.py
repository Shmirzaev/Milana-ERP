from uuid import uuid4

from app.db.session import SessionLocal
from app.models import Customer, SalesOrder, SalesOrderItem
from app.services.finance import order_profit


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
        db.add_all([
            SalesOrderItem(
                sales_order_id=order.id,
                model_id=1,
                quantity=7,
                unit_price="0.10",
                color="black",
                size="M",
            ),
            SalesOrderItem(
                sales_order_id=order.id,
                model_id=1,
                quantity=3,
                unit_price="0.20",
                color="black",
                size="L",
            ),
        ])
        db.commit()

        result = order_profit(db, order.id)

    assert result["revenue"] == 1.3
    assert result["material_cost"] == 0.0
    assert result["waste_cost"] == 0.0
    assert result["gross_profit"] == 1.3
