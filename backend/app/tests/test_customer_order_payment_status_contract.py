from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.libs.dto.sales.customer_order_output import CustomerOrderLedgerOut
from app.libs.enums.finance import CustomerOrderPaymentStatus, InvoiceStatus
from app.libs.enums.sales import SalesOrderStatus
from app.models.finance.customer_ledger_service import _serialize_customer_order


@pytest.mark.parametrize(
    ("order_status", "shipped", "balance", "invoices", "invoice_total", "paid_total", "expected"),
    [
        (SalesOrderStatus.DRAFT, False, "0", [], "0", "0", CustomerOrderPaymentStatus.NO_INVOICE),
        (SalesOrderStatus.CANCELLED, False, "90", [], "0", "0", CustomerOrderPaymentStatus.CANCELLED),
        (SalesOrderStatus.SHIPPED, True, "90", [], "0", "0", CustomerOrderPaymentStatus.UNPAID),
        (SalesOrderStatus.DRAFT, False, "0", [InvoiceStatus.VOID], "0", "0", CustomerOrderPaymentStatus.VOID),
        (SalesOrderStatus.DRAFT, False, "0", [InvoiceStatus.VOID, InvoiceStatus.VOID], "0", "0", CustomerOrderPaymentStatus.VOID),
        (SalesOrderStatus.DRAFT, False, "0", [InvoiceStatus.CANCELLED], "0", "0", CustomerOrderPaymentStatus.CANCELLED),
        (SalesOrderStatus.DRAFT, False, "0", [InvoiceStatus.VOID, InvoiceStatus.CANCELLED], "0", "0", CustomerOrderPaymentStatus.CANCELLED),
        (SalesOrderStatus.DRAFT, False, "100", [InvoiceStatus.UNPAID], "100", "0", CustomerOrderPaymentStatus.UNPAID),
        (SalesOrderStatus.DRAFT, False, "60", [InvoiceStatus.UNPAID], "100", "40", CustomerOrderPaymentStatus.PARTIAL),
        (SalesOrderStatus.DRAFT, False, "0", [InvoiceStatus.UNPAID], "100", "100", CustomerOrderPaymentStatus.PAID),
    ],
)
def test_customer_order_payment_projection_preserves_all_ledger_branches(
    order_status, shipped, balance, invoices, invoice_total, paid_total, expected,
):
    invoice_rows = [
        SimpleNamespace(
            id=index,
            invoice_no=f"INV-{index}",
            amount=Decimal(invoice_total) / max(len(invoices), 1),
            status=status,
            issued_at=None,
            due_date=None,
        )
        for index, status in enumerate(invoices, start=1)
    ]
    active_invoice_rows = [row for row in invoice_rows if row.status not in {InvoiceStatus.VOID, InvoiceStatus.CANCELLED}]
    payments_by_invoice = {
        row.id: [SimpleNamespace(
            id=row.id,
            amount=Decimal(paid_total) / max(len(active_invoice_rows), 1),
            paid_at=None,
            payment_method="legacy custom method",
            notes=None,
        )]
        for row in active_invoice_rows
        if Decimal(paid_total) > 0
    }

    row = _serialize_customer_order(
        SimpleNamespace(
            id=7,
            order_no="SO-7",
            created_at=datetime(2026, 10, 27),
            total_amount=Decimal(balance),
            status=order_status.value,
        ),
        invoice_rows,
        payments_by_invoice,
        has_shipped_goods=shipped,
    )

    assert row.payment_status is expected
    assert row.payment_status.value in {"paid", "partial", "unpaid", "no_invoice", "void", "cancelled"}
    assert row.payment_status.value != "partially_paid"


@pytest.mark.parametrize(
    ("payment_amount", "expected_order_status", "expected_invoice_status", "expected_paid", "expected_balance", "expected_advance"),
    [
        ("99.01", CustomerOrderPaymentStatus.PAID, InvoiceStatus.PAID, 99.01, 0.99, 0.0),
        ("98.99", CustomerOrderPaymentStatus.PARTIAL, InvoiceStatus.PARTIALLY_PAID, 98.99, 1.01, 0.0),
        ("100.99", CustomerOrderPaymentStatus.PAID, InvoiceStatus.PAID, 100.0, 0.0, 0.99),
    ],
)
def test_customer_order_serializer_preserves_tolerance_overpayment_and_free_method(
    payment_amount, expected_order_status, expected_invoice_status, expected_paid, expected_balance, expected_advance,
):
    invoice = SimpleNamespace(
        id=8,
        invoice_no="INV-8",
        amount=Decimal("100.00"),
        status=InvoiceStatus.UNPAID,
        issued_at=None,
        due_date=None,
    )
    payment = SimpleNamespace(
        id=9,
        amount=Decimal(payment_amount),
        paid_at=None,
        payment_method="owner-entered-method",
        notes=None,
    )

    row = _serialize_customer_order(
        SimpleNamespace(
            id=7,
            order_no="SO-7",
            created_at=datetime(2026, 10, 27),
            total_amount=Decimal("100.00"),
            status="shipped",
        ),
        [invoice],
        {8: [payment]},
        has_shipped_goods=True,
    )

    assert row.payment_status is expected_order_status
    assert row.invoices[0].status is expected_invoice_status
    assert row.invoices[0].paid_amount == expected_paid
    assert row.invoices[0].raw_paid_amount == float(Decimal(payment_amount))
    assert row.balance_due == expected_balance
    assert row.invoices[0].advance_amount == expected_advance
    assert row.invoices[0].payments[0].payment_method == "owner-entered-method"


def test_customer_order_response_model_matches_legacy_datetime_json_encoding(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from app.core.deps import get_current_user
    from app.db.session import get_db
    from app.api.routes import partners as partners_route

    order_date = datetime(2026, 10, 27, 9, 5, 3)
    utc_payment_date = datetime(2026, 10, 27, 9, 5, 3, tzinfo=timezone.utc)
    offset_invoice_date = datetime(2026, 10, 27, 9, 5, 3, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    offset_receipt_date = datetime(2026, 10, 27, 9, 5, 3, tzinfo=timezone(timedelta(hours=-4)))
    row = CustomerOrderLedgerOut(
        id=7,
        order_no="SO-7",
        date=order_date,
        total=100,
        status=SalesOrderStatus.SHIPPED,
        invoice_total=100,
        paid_total=40,
        balance_due=60,
        payment_status=CustomerOrderPaymentStatus.PARTIAL,
        last_payment_at=utc_payment_date,
        invoices=[{
            "id": 8,
            "invoice_no": "INV-8",
            "amount": 100,
            "status": InvoiceStatus.PARTIALLY_PAID,
            "issued_at": offset_invoice_date,
            "due_date": None,
            "paid_amount": 40,
            "raw_paid_amount": 40,
            "advance_amount": 0,
            "balance_due": 60,
            "payments": [
                {"id": 9, "amount": 20, "payment_method": "legacy custom method", "paid_at": None},
                {"id": 10, "amount": 20, "payment_method": None, "paid_at": offset_receipt_date},
            ],
        }],
    )
    query_calls = []

    def stub_list_customer_orders(db, cid):
        query_calls.append((db, cid))
        return [row]

    monkeypatch.setattr(partners_route, "list_customer_orders", stub_list_customer_orders)

    python_dump = row.model_dump(mode="python")
    assert python_dump["date"] == order_date
    assert python_dump["last_payment_at"] == utc_payment_date
    assert python_dump["invoices"][0]["issued_at"] == offset_invoice_date
    assert python_dump["invoices"][0]["due_date"] is None
    assert python_dump["invoices"][0]["payments"][0]["paid_at"] is None
    assert python_dump["invoices"][0]["payments"][1]["paid_at"] == offset_receipt_date

    actor = SimpleNamespace(
        role=SimpleNamespace(name="Authorized test reader", permissions=["*"]),
        extra_permissions=[],
        factory_code="MIL",
        access_policy=None,
        department=None,
    )
    db = Session()
    app = FastAPI()
    app.include_router(partners_route.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: actor

    def get_local_db():
        yield db

    app.dependency_overrides[get_db] = get_local_db
    try:
        with TestClient(app) as client:
            response = client.get("/api/customers/7/orders")
    finally:
        app.dependency_overrides.clear()
        db.close()

    assert response.status_code == 200, response.text
    assert query_calls == [(db, 7)]
    # Golden JSON reflects the 6f dictionary serializer contract independently
    # of the candidate DTO. Datetimes use the old datetime.isoformat() spelling.
    legacy_json = [{
        "id": 7,
        "order_no": "SO-7",
        "date": order_date.isoformat(),
        "total": 100.0,
        "status": "shipped",
        "invoice_total": 100.0,
        "paid_total": 40.0,
        "balance_due": 60.0,
        "payment_status": "partial",
        "last_payment_at": utc_payment_date.isoformat(),
        "invoices": [
            {
                "id": 8,
                "invoice_no": "INV-8",
                "amount": 100.0,
                "status": "partially_paid",
                "issued_at": offset_invoice_date.isoformat(),
                "due_date": None,
                "paid_amount": 40.0,
                "raw_paid_amount": 40.0,
                "advance_amount": 0.0,
                "balance_due": 60.0,
                "payments": [
                    {"id": 9, "amount": 20.0, "payment_method": "legacy custom method", "paid_at": None, "notes": None},
                    {"id": 10, "amount": 20.0, "payment_method": None, "paid_at": offset_receipt_date.isoformat(), "notes": None},
                ],
            }
        ],
    }]
    assert response.json() == legacy_json
    assert response.json()[0]["payment_status"] == "partial"
    assert response.json()[0]["invoices"][0]["status"] == "partially_paid"
    assert response.json()[0]["date"] == order_date.isoformat()
    assert response.json()[0]["last_payment_at"] == utc_payment_date.isoformat()
    assert response.json()[0]["invoices"][0]["issued_at"] == offset_invoice_date.isoformat()
    assert response.json()[0]["invoices"][0]["due_date"] is None
    assert response.json()[0]["invoices"][0]["payments"][0]["paid_at"] is None
    assert response.json()[0]["invoices"][0]["payments"][1]["paid_at"] == offset_receipt_date.isoformat()
