from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import event

from app.api.routes import inbox
from app.models import Customer, FinishedGoodsStock, Model, SalesOrder, SalesOrderItem, StockReservation
from app.tests.conftest import TestSessionLocal


def test_ready_to_ship_item_model_read_omits_unused_model_json(monkeypatch):
    suffix = uuid4().hex[:8]
    with TestSessionLocal() as db:
        customer = Customer(name=f"Inbox customer {suffix}", address="Test destination")
        model = Model(
            code=f"INBOX-MODEL-{suffix}",
            name="Ready-to-ship model",
            details_json={"unused": ["large-model-context"] * 20},
        )
        db.add_all([customer, model])
        db.flush()
        order = SalesOrder(
            order_no=f"INBOX-SO-{suffix}",
            customer_id=customer.id,
            order_type="branded_stock_sale",
            status="ready",
        )
        db.add(order)
        db.flush()
        item = SalesOrderItem(
            sales_order_id=order.id,
            model_id=model.id,
            color="navy",
            size="M",
            quantity=3,
            unit_price=12,
        )
        stock = FinishedGoodsStock(
            sales_order_id=order.id,
            model_id=model.id,
            color="navy",
            size="M",
            quantity=3,
            reserved_qty=3,
            status="reserved",
        )
        db.add_all([item, stock])
        db.flush()
        reservation = StockReservation(
            sales_order_id=order.id,
            finished_goods_stock_id=stock.id,
            quantity=3,
        )
        db.add(reservation)
        db.commit()
        order_id = int(order.id)

    monkeypatch.setattr(inbox, "require_operational_department_access", lambda *_args: None)
    monkeypatch.setattr(inbox, "user_permissions", lambda _user: ["*"])
    statements = []
    with TestSessionLocal() as db:
        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            result = inbox.department_inbox(db, SimpleNamespace(department_id=None), dept="FGS")
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    row = next(row for row in result["ready_to_ship"] if row["sales_order_id"] == order_id)
    assert row["item_lines"] == [{
        "id": item.id,
        "model_id": model.id,
        "model_code": model.code,
        "model_name": model.name,
        "color": "navy",
        "size": "M",
        "quantity": 3,
    }]
    item_reads = [
        statement for statement in statements
        if "from sales_order_items" in statement and "join models" in statement
    ]
    assert len(item_reads) == 1
    assert "models.code" in item_reads[0]
    assert "models.name" in item_reads[0]
    assert "models.details_json" not in item_reads[0]
    assert "sales_order_items.notes" not in item_reads[0]
