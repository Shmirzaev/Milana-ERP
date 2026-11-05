from decimal import Decimal
from typing import get_type_hints

from sqlalchemy import Numeric, create_engine, select
from sqlalchemy.orm import Mapped, Session

import app.schemas  # noqa: F401 - register referenced tables
from app.schemas.sales.sales import Invoice, Payment


def test_amount_mapping_metadata_and_annotation():
    for model, check in ((Invoice, "amount >= 0"), (Payment, "amount > 0")):
        column = model.__table__.c.amount
        assert get_type_hints(model)["amount"] == Mapped[Decimal]
        assert isinstance(column.type, Numeric)
        assert (column.type.precision, column.type.scale, column.type.asdecimal) == (14, 2, True)
        assert column.nullable is False
        assert column.default.arg == 0
        assert any(str(c.sqltext) == check for c in model.__table__.constraints if hasattr(c, "sqltext"))


def test_amount_roundtrip_and_transient_float_compatibility():
    engine = create_engine("sqlite://")
    Invoice.__table__.create(engine)
    Payment.__table__.create(engine)
    with Session(engine) as session:
        invoice = Invoice(sales_order_id=1, invoice_no="TYPE-1", amount=12.34)
        payment = Payment(amount=Decimal("2.10"))
        assert isinstance(invoice.amount, float)  # shipment workflow assigns a float
        session.add_all([invoice, payment])
        session.commit()
        invoice_id, payment_id = invoice.id, payment.id
    with Session(engine) as session:
        invoice = session.get(Invoice, invoice_id)
        payment = session.get(Payment, payment_id)
        assert invoice.amount == Decimal("12.34") and isinstance(invoice.amount, Decimal)
        assert payment.amount == Decimal("2.10") and isinstance(payment.amount, Decimal)
        assert float(invoice.amount) == 12.34
        assert float(payment.amount) == 2.1
        session.expire(invoice, ["amount"])
        assert invoice.amount == Decimal("12.34")
        assert session.scalar(select(Payment.amount).where(Payment.id == payment_id)) == Decimal("2.10")
