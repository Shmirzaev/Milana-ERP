"""Typing contract for the persisted invoice status.

Ismail's correction makes real enum annotations mandatory: a known
fixed-vocabulary output DTO field and the used internal/schema APIs must carry
the canonical `InvoiceStatus` class, not `str`, not `Enum | str`, not an
enum-backed default on a string field.

These tests pin the typed contract and the deliberate boundary
consequences:

* the stored value and the serialized API value stay the raw persisted strings
  (`unpaid`, `partially_paid`, `paid`, `void`, `cancelled`);
* `str(InvoiceStatus.VOID)` is `"InvoiceStatus.VOID"`, so `.value` - never
  `str()` - is used where a plain string is written;
* the mapped column owns the string/member conversion, so a reloaded row
  really returns the member and the raw column still holds the stored string.

Expected values are independent literals, not derived from the enum.
"""
from decimal import Decimal
from types import SimpleNamespace
from typing import get_type_hints
from uuid import uuid4

from sqlalchemy import text
from app.libs.dto.sales.invoice_output import InvoiceOut
from app.libs.enums.finance import InvoiceStatus
from app.models.payments_service import REVERSED_INVOICE_STATUSES, invoice_payment_status
from app.schemas import Customer, Invoice, SalesOrder
from app.schemas.finance.invoice_payment_persistence import set_invoice_status
from app.tests.conftest import TestSessionLocal
from app.tests.test_finance_payment_operation_contract import payable_invoice  # noqa: F401


def test_the_output_dto_field_is_annotated_with_the_canonical_enum():
    """`InvoiceOut.status` is the enum class itself, not a string escape."""
    field = InvoiceOut.model_fields["status"]
    assert field.annotation is InvoiceStatus
    assert "str" not in str(field.annotation)


def test_the_output_dto_runtime_type_is_the_member_and_serializes_the_raw_string():
    """The member is kept internally and serialized as the raw persisted string."""
    row = SimpleNamespace(
        id=1,
        sales_order_id=1,
        invoice_no="INV-1",
        amount=100.0,
        status="unpaid",
        issued_at=None,
        due_date=None,
    )
    parsed = InvoiceOut.model_validate(row)
    assert isinstance(parsed.status, InvoiceStatus)
    assert parsed.status == InvoiceStatus.UNPAID
    assert parsed.model_dump(mode="json")["status"] == "unpaid"


def test_the_mapped_column_default_is_the_enum_member():
    """A `.value` string default would leave the attribute a plain str."""
    default = Invoice.__table__.c.status.default
    assert default.arg is InvoiceStatus.UNPAID
    assert type(default.arg) is InvoiceStatus


def test_the_mapped_column_default_stores_the_raw_string(client, auth_headers, payable_invoice):
    """The member default reaches the database as the plain persisted string."""
    _customer_id, invoice_id = payable_invoice
    with TestSessionLocal() as db:
        stored = db.execute(
            text("SELECT status FROM invoices WHERE id = :id"), {"id": invoice_id}
        ).scalar()
    assert stored == "unpaid"
    assert "InvoiceStatus" not in str(stored)


def test_the_schema_helper_writes_the_raw_string_for_a_member():
    """`set_invoice_status` takes the member; the column stores the raw string."""
    with TestSessionLocal() as db:
        customer = Customer(name="typing contract")
        db.add(customer)
        db.flush()
        order = SalesOrder(order_no=f"TC-{uuid4().hex}", customer_id=customer.id, total_amount=10)
        db.add(order)
        db.flush()
        invoice = Invoice(
            invoice_no=f"TC-INV-{uuid4().hex}",
            sales_order_id=order.id,
            amount=Decimal("10"),
            status=InvoiceStatus.UNPAID,
        )
        db.add(invoice)
        db.flush()
        set_invoice_status(invoice, InvoiceStatus.PARTIALLY_PAID)
        db.flush()
        raw = db.execute(
            text("SELECT status FROM invoices WHERE id = :id"), {"id": invoice.id}
        ).scalar()
        db.rollback()
    assert raw == "partially_paid"
    assert type(raw) is str


def test_a_reloaded_invoice_really_returns_the_enum_member(client, auth_headers, payable_invoice):
    """The mapped annotation must describe the value a reloaded row returns."""
    _customer_id, invoice_id = payable_invoice
    with TestSessionLocal() as db:
        invoice = db.get(Invoice, invoice_id)
        assert type(invoice.status) is InvoiceStatus, (type(invoice.status), invoice.status)
        assert invoice.status is InvoiceStatus.UNPAID


def test_the_member_survives_expiration_while_the_raw_column_keeps_the_stored_string(
    client, auth_headers, payable_invoice
):
    """A refreshed or expired attribute is the member; the column is unchanged."""
    _customer_id, invoice_id = payable_invoice
    with TestSessionLocal() as db:
        invoice = db.get(Invoice, invoice_id)
        set_invoice_status(invoice, InvoiceStatus.PARTIALLY_PAID)
        db.flush()
        raw = db.execute(
            text("SELECT status FROM invoices WHERE id = :id"), {"id": invoice_id}
        ).scalar_one()
        assert raw == "partially_paid"
        db.expire(invoice, ["status"])
        assert type(invoice.status) is InvoiceStatus, (type(invoice.status), invoice.status)
        assert invoice.status is InvoiceStatus.PARTIALLY_PAID
        db.rollback()


def test_the_used_settlement_seam_is_annotated_with_the_canonical_enum():
    """The shared internal contract speaks the canonical enum in and out."""
    hints = get_type_hints(invoice_payment_status)
    assert hints["current_status"] == InvoiceStatus | None
    assert hints["return"] is InvoiceStatus
    assert invoice_payment_status(Decimal("100"), Decimal("0"), InvoiceStatus.VOID) is InvoiceStatus.VOID


def test_the_settlement_derivation_returns_the_enum_member():
    """The shared internal contract speaks the canonical enum."""
    for amount, paid in [(Decimal("100"), Decimal("100")), (Decimal("100"), Decimal("40")),
                          (Decimal("100"), Decimal("0"))]:
        result = invoice_payment_status(amount, paid)
        assert isinstance(result, InvoiceStatus)
        assert not isinstance(result, str) or type(result) is InvoiceStatus
    assert invoice_payment_status(Decimal("100"), Decimal("100")) == InvoiceStatus.PAID
    assert invoice_payment_status(Decimal("100"), Decimal("40")) == InvoiceStatus.PARTIALLY_PAID
    assert invoice_payment_status(Decimal("100"), Decimal("0")) == InvoiceStatus.UNPAID


def test_the_reversed_statuses_are_real_members_that_still_match_the_stored_string():
    """Members in the set still match the raw database string."""
    assert REVERSED_INVOICE_STATUSES == frozenset({InvoiceStatus.VOID, InvoiceStatus.CANCELLED})
    assert InvoiceStatus.VOID in REVERSED_INVOICE_STATUSES
    assert "void" in REVERSED_INVOICE_STATUSES
    assert "cancelled" in REVERSED_INVOICE_STATUSES
    assert "unpaid" not in REVERSED_INVOICE_STATUSES


def test_the_member_is_never_stringified():
    """The trap the schema write must avoid."""
    assert str(InvoiceStatus.VOID) == "InvoiceStatus.VOID"
    assert str(InvoiceStatus.VOID) != InvoiceStatus.VOID.value
    assert InvoiceStatus.VOID.value == "void"


def test_the_invoice_api_response_carries_the_raw_persisted_string(client, auth_headers):
    """The typed output DTO still returns the same JSON string as before."""
    with TestSessionLocal() as db:
        customer = Customer(name="typing api")
        db.add(customer)
        db.flush()
        order = SalesOrder(
            order_no=f"TC-API-{uuid4().hex}", customer_id=customer.id, total_amount=Decimal("250")
        )
        db.add(order)
        db.commit()
        order_id = int(order.id)

    response = client.post(
        "/api/finance/invoices",
        headers=auth_headers,
        json={"sales_order_id": order_id},
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "unpaid"
    assert isinstance(response.json()["status"], str)


def test_the_invoice_list_consumer_returns_plain_strings(client, auth_headers, payable_invoice):
    """The finance report consumer converts the member at the JSON boundary."""
    _customer_id, invoice_id = payable_invoice
    response = client.get("/api/finance/invoices", headers=auth_headers)
    assert response.status_code == 200, response.text
    rows = response.json()["items"]
    row = next(item for item in rows if int(item["id"]) == invoice_id)
    assert row["status"] == "unpaid"
    assert type(row["status"]) is str
