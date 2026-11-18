"""Characterize the shipment invoice writer's transaction participation."""
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock
from types import SimpleNamespace

import pytest

from app.libs.enums.finance import InvoiceStatus
from app.schemas.finance.shipment_invoice_persistence import (
    set_shipment_invoice_amount, stage_shipment_invoice,
)


def test_staging_preserves_values_without_flushing_or_committing():
    db = Mock()
    issued = datetime(2026, 1, 1, tzinfo=timezone.utc)
    due = datetime(2026, 1, 15, tzinfo=timezone.utc)
    invoice = stage_shipment_invoice(
        db, sales_order_id=12, invoice_no="INV-12", amount=12.34,
        status=InvoiceStatus.UNPAID, issued_at=issued, due_date=due,
    )
    db.add.assert_called_once_with(invoice)
    db.flush.assert_not_called()
    db.commit.assert_not_called()
    assert (invoice.sales_order_id, invoice.invoice_no, invoice.amount, invoice.status,
            invoice.issued_at, invoice.due_date) == (12, "INV-12", 12.34, InvoiceStatus.UNPAID, issued, due)


def test_amount_assignment_keeps_caller_decided_precision():
    invoice = Mock()
    set_shipment_invoice_amount(Mock(), invoice, Decimal("123.40"))
    assert invoice.amount == Decimal("123.40")


def test_staging_propagates_add_failure_without_flush_or_commit():
    db = Mock()
    db.add.side_effect = RuntimeError("write failed")
    now = datetime.now(timezone.utc)
    with pytest.raises(RuntimeError, match="write failed"):
        stage_shipment_invoice(db, sales_order_id=1, invoice_no="x", amount=1.0,
                               status=InvoiceStatus.UNPAID, issued_at=now, due_date=now)
    db.flush.assert_not_called()
    db.commit.assert_not_called()


def test_ensure_invoice_stages_only_when_no_active_invoice(monkeypatch):
    from app.models import workflow_service

    db = Mock()
    db.get.return_value = SimpleNamespace(total_amount=Decimal("12.34"))
    query = db.query.return_value.filter.return_value
    existing = object()
    query.first.return_value = existing
    numbering = Mock(return_value="INV-12")
    monkeypatch.setattr(workflow_service, "next_invoice_no", numbering)
    assert workflow_service.ensure_invoice_for_delivered_shipment(db, sales_order_id=12) is existing
    numbering.assert_not_called()
    db.add.assert_not_called()

    query.first.return_value = None
    invoice = workflow_service.ensure_invoice_for_delivered_shipment(db, sales_order_id=12)
    assert invoice.invoice_no == "INV-12"
    assert invoice.amount == 12.34
    assert invoice.status is InvoiceStatus.UNPAID
    assert (invoice.due_date - invoice.issued_at).days == 14
    db.add.assert_called_once_with(invoice)
    db.flush.assert_not_called()
    db.commit.assert_not_called()


def test_ensure_invoice_missing_order_does_not_write():
    from app.models.workflow_service import ensure_invoice_for_delivered_shipment

    db = Mock()
    db.get.return_value = None
    assert ensure_invoice_for_delivered_shipment(db, sales_order_id=None) is None
    assert ensure_invoice_for_delivered_shipment(db, sales_order_id=99) is None
    db.query.assert_not_called()
    db.add.assert_not_called()
