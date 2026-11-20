"""PostgreSQL characterization of shipment's Finance participant, not its coordinator."""
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import inspect

from app.libs.enums.finance import InvoiceStatus
from app.models import shipment_review_service
from app.models.workflow_service import ensure_invoice_for_delivered_shipment
from app.schemas import AuditLog, Customer, Invoice, SalesOrder, Shipment, User
from app.tests.test_customer_create_postgres import chain, customer_pg_sessions  # noqa: F401


def make_case(sessions, *, invoice=False):
    marker = uuid4().hex
    with sessions.begin() as db:
        actor = User(name="Shipment PG actor", email=f"shipment-{marker}@example.invalid",
                     password_hash="unused", factory_code="MIL", extra_permissions=[], is_active=True)
        customer = Customer(name=f"Shipment customer {marker}")
        db.add_all([actor, customer])
        db.flush()
        order = SalesOrder(order_no=f"PG-SHP-{marker}", customer_id=customer.id,
                           total_amount=Decimal("12.34"), created_by=actor.id)
        db.add(order)
        db.flush()
        shipment = Shipment(shipment_no=f"PG-SHP-{marker}", sales_order_id=order.id,
                            customer_id=customer.id, status="shipped",
                            dispatch_snapshot={"document": {"amount": "9.87"}})
        db.add(shipment)
        if invoice:
            db.add(Invoice(sales_order_id=order.id, invoice_no=f"PG-INV-{marker}",
                           amount=Decimal("12.34"), status=InvoiceStatus.UNPAID))
        db.flush()
        return order.id, shipment.id, actor.id, customer.id


@pytest.mark.parametrize("commit", [False, True])
def test_pg_ensure_stages_until_caller_flush_and_transaction_end(customer_pg_sessions, commit):
    sessions = customer_pg_sessions
    order_id, _, _, customer_id = make_case(sessions)
    with sessions() as db:
        invoice = ensure_invoice_for_delivered_shipment(db, sales_order_id=order_id)
        assert inspect(invoice).pending and invoice.id is None
        assert invoice.amount == 12.34 and invoice.status == InvoiceStatus.UNPAID
        assert (invoice.due_date - invoice.issued_at).days == 14
        with sessions() as observer:
            assert observer.query(Invoice).filter_by(sales_order_id=order_id).count() == 0
        db.flush()
        assert invoice.id is not None and inspect(invoice).persistent
        with sessions() as observer:
            assert observer.query(Invoice).filter_by(sales_order_id=order_id).count() == 0
        db.commit() if commit else db.rollback()
    with sessions() as observer:
        rows = observer.query(Invoice).filter_by(sales_order_id=order_id).all()
        assert len(rows) == int(commit)
        assert observer.get(SalesOrder, order_id).customer_id == customer_id
        if commit:
            assert rows[0].amount == Decimal("12.34")
            assert rows[0].status == InvoiceStatus.UNPAID


@pytest.mark.parametrize("fail_after_audit", [False, True])
def test_pg_frozen_reconciliation_audit_and_amount_share_transaction(
    customer_pg_sessions, monkeypatch, fail_after_audit,
):
    sessions = customer_pg_sessions
    order_id, shipment_id, actor_id, customer_id = make_case(sessions, invoice=True)
    original_audit = shipment_review_service.log_action
    if fail_after_audit:
        def fail(db, *args, **kwargs):
            original_audit(db, *args, **kwargs)
            raise RuntimeError("after audit enqueue")
        monkeypatch.setattr(shipment_review_service, "log_action", fail)
    with sessions() as db:
        shipment, actor = db.get(Shipment, shipment_id), db.get(User, actor_id)
        if fail_after_audit:
            with pytest.raises(RuntimeError, match="after audit enqueue"):
                shipment_review_service.invoice_for_frozen_delivery(db, shipment, actor)
            db.rollback()
        else:
            invoice = shipment_review_service.invoice_for_frozen_delivery(db, shipment, actor)
            assert invoice.amount == Decimal("9.87")
            db.commit()
    with sessions() as observer:
        invoice = observer.query(Invoice).filter_by(sales_order_id=order_id).one()
        assert invoice.amount == Decimal("12.34" if fail_after_audit else "9.87")
        assert observer.get(SalesOrder, order_id).customer_id == customer_id
        audits = observer.query(AuditLog).filter_by(
            action="reconcile_frozen_shipment_invoice", entity_type="Invoice", entity_id=invoice.id,
        ).all()
        assert len(audits) == (0 if fail_after_audit else 1)
        if audits:
            assert audits[0].old_value_json["amount"] == "12.34"
            assert audits[0].new_value_json["amount"] == "9.87"
            assert audits[0].new_value_json["shipment_ids"] == [shipment_id]
    chain(sessions)
