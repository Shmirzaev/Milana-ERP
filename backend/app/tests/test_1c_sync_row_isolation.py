from uuid import uuid4

from sqlalchemy.orm import sessionmaker

from app.models import Customer, Invoice, Payment, SalesOrder
from app.schemas.integrations import OneCSyncIn
from app.services.finance_1c import sync_from_1c
from app.tests.conftest import TestSessionLocal
from app.tests.test_1c_payment_reassignment import reassignment_postgres_engine as reassignment_postgres_engine


def _run_row_isolation(session_factory, *, expected_dialect: str, rollback: bool = False):
    marker = uuid4().hex[:12]
    with session_factory() as db:
        assert db.bind.dialect.name == expected_dialect
        customer = Customer(name=f"FN01 row isolation {marker}")
        db.add(customer)
        db.flush()
        order = SalesOrder(order_no=f"FN01-{marker}", customer_id=customer.id, total_amount=500)
        db.add(order)
        db.flush()
        existing_invoice = Invoice(
            sales_order_id=order.id, invoice_no=f"FN01-EXISTING-{marker}", amount=100,
            status="paid", external_source="1c", external_id=f"invoice-existing-{marker}",
        )
        target_invoice = Invoice(
            sales_order_id=order.id, invoice_no=f"FN01-TARGET-{marker}", amount=100,
            status="unpaid", external_source="1c", external_id=f"invoice-target-{marker}",
        )
        db.add_all([existing_invoice, target_invoice])
        db.flush()
        moved_payment = Payment(
            invoice_id=existing_invoice.id, amount=100, external_source="1c",
            external_id=f"payment-move-{marker}",
        )
        db.add(moved_payment)
        db.commit()

        summary = sync_from_1c(db, OneCSyncIn(
            invoices=[
                {"external_id": f"invoice-good-a-{marker}", "invoice_no": f"FN01-A-{marker}",
                 "sales_order_id": order.id, "amount": 80},
                # Real unique-constraint failure; this row must not poison the batch.
                {"external_id": f"invoice-bad-{marker}", "invoice_no": f"FN01-A-{marker}",
                 "sales_order_id": order.id, "amount": 90},
                {"external_id": f"invoice-good-c-{marker}", "invoice_no": f"FN01-C-{marker}",
                 "sales_order_id": order.id, "amount": 70},
                # Invalid reference is a separate row-level error.
                {"external_id": f"invoice-invalid-{marker}", "sales_order_id": 2**40, "amount": 60},
            ],
            payments=[
                {"external_id": f"payment-good-a-{marker}", "invoice_external_id": f"invoice-good-a-{marker}", "amount": 20},
                # Real positive-amount constraint failure while moving an existing payment.
                {"external_id": f"payment-move-{marker}", "invoice_id": target_invoice.id, "amount": 0},
                {"external_id": f"payment-good-c-{marker}", "invoice_external_id": f"invoice-good-c-{marker}", "amount": 30},
                # Invalid reference after valid rows must not abort the session.
                {"external_id": f"payment-invalid-{marker}", "invoice_id": 2**40, "amount": 10},
            ],
        ))
        if rollback:
            db.rollback()
        else:
            db.commit()

        assert summary["invoices_created"] == 2
        assert summary["invoices_updated"] == 0
        assert summary["payments_created"] == 2
        assert summary["payments_updated"] == 0
        assert len(summary["errors"]) == 4

        expected_persisted = 0 if rollback else 1
        assert db.query(Invoice).filter_by(external_id=f"invoice-good-a-{marker}").count() == expected_persisted
        assert db.query(Invoice).filter_by(external_id=f"invoice-good-c-{marker}").count() == expected_persisted
        assert db.query(Invoice).filter_by(external_id=f"invoice-bad-{marker}").count() == 0
        assert db.query(Invoice).filter_by(external_id=f"invoice-invalid-{marker}").count() == 0

        moved_payment = db.query(Payment).filter_by(external_id=f"payment-move-{marker}").one()
        assert moved_payment.invoice_id == existing_invoice.id
        assert moved_payment.amount == 100
        assert db.query(Payment).filter_by(external_id=f"payment-good-a-{marker}").count() == expected_persisted
        assert db.query(Payment).filter_by(external_id=f"payment-good-c-{marker}").count() == expected_persisted
        assert db.query(Payment).filter_by(external_id=f"payment-invalid-{marker}").count() == 0
        assert db.get(Invoice, existing_invoice.id).status == "paid"
        assert db.get(Invoice, target_invoice.id).status == "unpaid"


def test_1c_sync_keeps_good_rows_after_bad_invoice_and_payment_rows():
    _run_row_isolation(TestSessionLocal, expected_dialect="sqlite")


def test_1c_sync_postgres_row_isolation(reassignment_postgres_engine):
    session_factory = sessionmaker(bind=reassignment_postgres_engine, autoflush=False, expire_on_commit=False)
    _run_row_isolation(session_factory, expected_dialect="postgresql")


def test_1c_sync_caller_rollback_keeps_accepted_rows_uncommitted():
    _run_row_isolation(TestSessionLocal, expected_dialect="sqlite", rollback=True)


def test_1c_sync_postgres_caller_rollback(reassignment_postgres_engine):
    session_factory = sessionmaker(bind=reassignment_postgres_engine, autoflush=False, expire_on_commit=False)
    _run_row_isolation(session_factory, expected_dialect="postgresql", rollback=True)
