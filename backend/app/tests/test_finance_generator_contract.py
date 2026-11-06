"""Bounded contract checks for the Sales invoice generator."""
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.libs.dto.sales.invoice_generation_output import InvoiceGenerationOut
from app.libs.enums.finance import InvoiceStatus
from app.libs.enums.sales import SalesOrderStatus
from app.models.finance import invoices_service as issuance


ALLOWED = {
    "confirmed", "in_production", "cutting", "sewing", "packaging", "storage",
    "ready", "reserved", "shipped", "delivered", "planning",
    "planning_approved", "production",
}


class ExistingInvoiceSession:
    def __init__(self, invoice):
        self.invoice = invoice
        self.queried = False

    def query(self, _model):
        self.queried = True
        return self

    def filter(self, *_args):
        return self

    def order_by(self, *_args):
        return self

    def first(self):
        return self.invoice


@pytest.mark.parametrize("status", [s.value for s in SalesOrderStatus] + ["unknown", ""])
def test_status_subset_and_refusal_precede_existing_reuse(monkeypatch, status):
    invoice = SimpleNamespace(id=7, sales_order_id=3, invoice_no="INV-1",
                              amount=Decimal("2.00"), status=InvoiceStatus.VOID,
                              issued_at=datetime(2026, 1, 1, tzinfo=timezone.utc), due_date=None)
    db = ExistingInvoiceSession(invoice)
    monkeypatch.setattr(issuance, "lock_sales_order", lambda *_: SimpleNamespace(status=status))
    if status in ALLOWED:
        result = issuance.generate_order_invoice(db, 3, object())
        assert result.id == 7 and result.status is InvoiceStatus.VOID
        assert result.created_existing is True and db.queried
    else:
        with pytest.raises(HTTPException) as error:
            issuance.generate_order_invoice(db, 3, object())
        assert error.value.status_code == 400
        assert error.value.detail == f"Cannot generate invoice for order in status '{status}'"
        assert not db.queried


def test_invoiceable_set_uses_canonical_members():
    assert all(type(item) is SalesOrderStatus for item in issuance.INVOICEABLE_ORDER_STATUSES)
    assert {item.value for item in issuance.INVOICEABLE_ORDER_STATUSES} == ALLOWED


def test_cancelled_existing_invoice_is_reused(monkeypatch):
    invoice = SimpleNamespace(id=9, sales_order_id=3, invoice_no="INV-9", amount=Decimal("2.00"),
                              status=InvoiceStatus.CANCELLED,
                              issued_at=datetime(2026, 1, 1, tzinfo=timezone.utc), due_date=None)
    db = ExistingInvoiceSession(invoice)
    monkeypatch.setattr(issuance, "lock_sales_order", lambda *_: SimpleNamespace(status="confirmed"))
    result = issuance.generate_order_invoice(db, 3, object())
    assert result.id == 9 and result.status is InvoiceStatus.CANCELLED
    assert result.created_existing is True


@pytest.mark.parametrize("value", ["-0.01", "1.001", "1000000000000", "NaN", "Infinity"])
def test_invalid_resolved_amount_is_422(value):
    with pytest.raises(HTTPException) as error:
        issuance.storable_invoice_amount(Decimal(value))
    assert error.value.status_code == 422
    assert error.value.detail == "Invoice amount must be finite and representable in cents"


def test_invalid_resolved_total_refuses_before_invoice_and_audit(monkeypatch):
    db = ExistingInvoiceSession(None)
    monkeypatch.setattr(issuance, "lock_sales_order", lambda *_: SimpleNamespace(status="confirmed", total_amount=Decimal("1.001")))
    monkeypatch.setattr(issuance, "next_invoice_no", lambda *_: "INV-test")
    monkeypatch.setattr(issuance, "insert_order_invoice", lambda *a, **kw: pytest.fail("insert called"))
    monkeypatch.setattr(issuance, "log_action", lambda *a, **kw: pytest.fail("audit called"))
    with pytest.raises(HTTPException) as error:
        issuance.generate_order_invoice(db, 3, object())
    assert error.value.status_code == 422


@pytest.mark.parametrize("value", ["0", "0.01", "0.50", "999999999999.99"])
def test_representable_amounts_are_preserved(value):
    assert issuance.storable_invoice_amount(Decimal(value)) == Decimal(value)


def test_utc_response_wire_spelling():
    app = FastAPI()

    @app.get("/invoice", response_model=InvoiceGenerationOut)
    def get_invoice():
        return InvoiceGenerationOut(id=7, sales_order_id=3, invoice_no="INV-1", amount=0.5,
                                    status=InvoiceStatus.UNPAID, issued_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                                    due_date=None, created_existing=False)

    response = TestClient(app).get("/invoice")
    assert response.status_code == 200
    assert response.json() == {"id": 7, "sales_order_id": 3, "invoice_no": "INV-1", "amount": 0.5,
                               "status": "unpaid", "issued_at": "2026-01-01T00:00:00Z", "due_date": None,
                               "created_existing": False}
