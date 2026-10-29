"""RF-011: the invoice status vocabulary has one definition.

`InvoiceStatus` owns the five persisted `invoices.status` strings. The CHECK
constraint and the column default are derived from it, so the enum, the DDL and
the stored default have to stay equal to the pre-refactor values.
"""
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from app.libs.enums.finance import InvoiceStatus
from app.models.payments_service import (
    REVERSED_INVOICE_STATUSES,
    invoice_payment_status,
    refresh_invoice_status,
)
from app.schemas import Invoice, SalesOrder
from app.tests.conftest import TestSessionLocal


PERSISTED_INVOICE_STATUSES = ("unpaid", "partially_paid", "paid", "void", "cancelled")
PRE_REFACTOR_STATUS_CHECK = "status IN ('unpaid', 'partially_paid', 'paid', 'void', 'cancelled')"


def _new_order(db) -> SalesOrder:
    order = SalesOrder(order_no=f"RF011-{uuid4().hex}", status="confirmed", total_amount=100)
    db.add(order)
    db.flush()
    return order


def _new_invoice(db, order_id: int, status: str | None = None) -> Invoice:
    invoice = Invoice(invoice_no=f"RF011-INV-{uuid4().hex}", sales_order_id=order_id, amount=100)
    if status is not None:
        invoice.status = status
    db.add(invoice)
    return invoice


def _status_constraint():
    for constraint in Invoice.__table__.constraints:
        if constraint.name == "ck_invoices_status":
            return constraint
    raise AssertionError("ck_invoices_status is not defined on the invoices table")


def test_invoice_status_enum_is_the_persisted_vocabulary():
    assert [(status.name, status.value) for status in InvoiceStatus] == [
        ("UNPAID", "unpaid"),
        ("PARTIALLY_PAID", "partially_paid"),
        ("PAID", "paid"),
        ("VOID", "void"),
        ("CANCELLED", "cancelled"),
    ]
    assert isinstance(InvoiceStatus.UNPAID, str)


def test_status_check_text_is_the_pre_refactor_ddl():
    assert str(_status_constraint().sqltext) == PRE_REFACTOR_STATUS_CHECK


def test_status_check_is_rendered_into_the_invoices_ddl():
    ddl = str(CreateTable(Invoice.__table__).compile(dialect=postgresql.dialect()))
    assert f"CHECK ({PRE_REFACTOR_STATUS_CHECK})" in ddl


def test_invoice_without_an_explicit_status_persists_unpaid():
    assert Invoice.__table__.c.status.default.arg == "unpaid"
    with TestSessionLocal() as db:
        invoice = _new_invoice(db, _new_order(db).id)
        db.commit()
        invoice_id = int(invoice.id)
    with TestSessionLocal() as db:
        assert db.get(Invoice, invoice_id).status == "unpaid"


@pytest.mark.parametrize("status", PERSISTED_INVOICE_STATUSES)
def test_database_accepts_every_persisted_status(status):
    with TestSessionLocal() as db:
        invoice = _new_invoice(db, _new_order(db).id, status)
        db.commit()
        invoice_id = int(invoice.id)
    with TestSessionLocal() as db:
        assert db.get(Invoice, invoice_id).status == status


def test_database_rejects_a_status_outside_the_enum():
    with TestSessionLocal() as db:
        _new_invoice(db, _new_order(db).id, "not_an_invoice_status")
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


@pytest.mark.parametrize(("amount", "paid", "expected"), [
    ("100.00", "99.00", InvoiceStatus.PAID),
    ("100.00", "99.01", InvoiceStatus.PAID),
    ("100.00", "98.99", InvoiceStatus.PARTIALLY_PAID),
    ("100.00", "0", InvoiceStatus.UNPAID),
])
def test_settlement_returns_the_persisted_status_values(amount, paid, expected):
    assert invoice_payment_status(Decimal(amount), Decimal(paid)) == expected.value


@pytest.mark.parametrize("status", [InvoiceStatus.VOID, InvoiceStatus.CANCELLED])
def test_reversed_invoice_keeps_its_own_status(status):
    assert invoice_payment_status(Decimal("100.00"), Decimal("100.00"), status.value) == status.value


def test_refresh_does_not_revive_a_reversed_invoice():
    with TestSessionLocal() as db:
        invoice = _new_invoice(db, _new_order(db).id, InvoiceStatus.VOID.value)
        db.commit()
        refresh_invoice_status(db, invoice)
        assert invoice.status == "void"
        db.commit()


def test_reversed_statuses_are_exactly_the_two_reversed_persisted_values():
    assert set(REVERSED_INVOICE_STATUSES) == {"void", "cancelled"}
