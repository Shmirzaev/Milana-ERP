"""An enum ORM annotation must describe actual reloaded values."""
from decimal import Decimal
from typing import get_type_hints

from sqlalchemy import text

from app.libs.enums.finance import InvoiceStatus
from app.models.payments_service import invoice_payment_status
from app.schemas import Invoice
from app.schemas.finance.invoice_payment_persistence import set_invoice_status
from app.tests.conftest import TestSessionLocal
from app.tests.test_finance_payment_operation_contract import payable_invoice as payable_invoice


def test_fresh_session_status_matches_orm_enum_annotation(client, auth_headers, payable_invoice):
    _, invoice_id = payable_invoice
    with TestSessionLocal() as db:
        invoice = db.get(Invoice, invoice_id)
        assert type(invoice.status) is InvoiceStatus, (type(invoice.status), invoice.status)
        assert invoice.status is InvoiceStatus.UNPAID


def test_schema_update_survives_expiration_as_enum(client, auth_headers, payable_invoice):
    _, invoice_id = payable_invoice
    with TestSessionLocal() as db:
        invoice = db.get(Invoice, invoice_id)
        set_invoice_status(invoice, InvoiceStatus.PARTIALLY_PAID)
        db.flush()
        raw = db.execute(text('SELECT status FROM invoices WHERE id = :id'), {'id': invoice_id}).scalar_one()
        assert raw == 'partially_paid'
        db.expire(invoice, ['status'])
        assert type(invoice.status) is InvoiceStatus, (type(invoice.status), invoice.status)
        assert invoice.status is InvoiceStatus.PARTIALLY_PAID
        db.rollback()


def test_used_settlement_seam_has_enum_status_input_and_output():
    hints = get_type_hints(invoice_payment_status)
    assert hints['current_status'] == InvoiceStatus | None
    assert hints['return'] is InvoiceStatus
    assert invoice_payment_status(Decimal('100'), Decimal('0'), InvoiceStatus.VOID) is InvoiceStatus.VOID
