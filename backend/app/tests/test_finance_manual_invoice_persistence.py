"""The schema insert participates in the service's transaction, not its own."""
from datetime import datetime, timezone
from decimal import Decimal
from typing import get_type_hints

import pytest
from sqlalchemy import event, inspect

from app.libs.dto.sales.invoice_input import InvoiceIn
from app.libs.enums.finance import InvoiceStatus
from app.models.finance import invoices_service as issuance
from app.schemas import AuditLog, Invoice, User
from app.schemas.finance.invoice_persistence import insert_order_invoice
from app.tests.test_customer_invoice_creation_race import receipt_race_sessions as receipt_race_sessions
from app.tests.test_finance_manual_invoice_creation import seed


@pytest.mark.parametrize("status", list(InvoiceStatus))
def test_schema_insert_flushes_in_supplied_session_without_commit(receipt_race_sessions, status):
    sessions = receipt_race_sessions
    oid, _ = seed(sessions)
    with sessions() as db:
        commits = []
        event.listen(db, "before_commit", lambda _: commits.append(True))
        when = datetime.now(timezone.utc)
        invoice = insert_order_invoice(db, sales_order_id=oid, invoice_no=f"SCHEMA-{oid}",
                                       amount=Decimal("12.34"), status=status, issued_at=when)
        assert inspect(invoice).session is db and invoice.id is not None
        assert isinstance(invoice.amount, Decimal) and invoice.status is status
        assert invoice.issued_at == when and invoice.due_date is None
        assert invoice.external_source is None and invoice.external_id is None
        assert not commits
        with sessions() as reader:
            assert reader.query(Invoice).filter_by(sales_order_id=oid).count() == 0
        db.rollback()
    with sessions() as reader:
        assert reader.query(Invoice).filter_by(sales_order_id=oid).count() == 0


def test_service_passes_actual_typed_values_and_commits_once(receipt_race_sessions, monkeypatch):
    sessions = receipt_race_sessions
    oid, uid = seed(sessions)
    seen = []
    with sessions() as db:
        commits = []
        event.listen(db, "before_commit", lambda _: commits.append(True))
        def observed(session, **fields):
            assert session is db
            assert isinstance(fields["amount"], Decimal)
            assert fields["status"] is InvoiceStatus.UNPAID
            assert fields["issued_at"].tzinfo is not None
            row = insert_order_invoice(session, **fields)
            assert not commits
            seen.append(row.id)
            return row
        monkeypatch.setattr(issuance, "insert_order_invoice", observed)
        result = issuance.create_order_invoice(db, InvoiceIn(sales_order_id=oid), db.get(User, uid))
        assert seen == [result.id] and len(commits) == 1
        assert db.query(AuditLog).filter_by(user_id=uid).one().entry_hash
    hints = get_type_hints(insert_order_invoice)
    assert hints["amount"] is Decimal and hints["status"] is InvoiceStatus
    assert hints["return"] is Invoice
