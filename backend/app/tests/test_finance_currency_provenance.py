"""Currency provenance must never turn unknown or mixed money into a total."""

from datetime import datetime, timezone

from app.db.session import SessionLocal
from app.api.routes.partners import CustomerPaymentIn
from app.models import IdempotencyRecord, Invoice, Payment, User
from app.schemas.integrations import OneCSyncIn
from app.schemas.sales import PaymentIn
from app.schemas.inventory import StockBatchIn
from app.schemas.purchasing import PurchaseOrderReceiveIn
from app.services.finance import payments_summary, revenue_summary
from app.services.idempotency import request_fingerprint
from app.tests.test_payment_integrity import _create_invoice
from app.tests.test_material_roll_weights import _material_context
from app.tests.test_purchase_receipt_idempotency import create_receipt_order


def test_legacy_unknown_and_mixed_currency_totals_are_unavailable(client, auth_headers):
    invoice_ids = [_create_invoice(SessionLocal, amount=amount)[2] for amount in (10, 20, 30)]
    with SessionLocal() as db:
        for invoice_id, currency in zip(invoice_ids, ("USD", "USD", None)):
            invoice = db.get(Invoice, invoice_id)
            invoice.currency = currency
            invoice.issued_at = datetime(2089, 1, 2, tzinfo=timezone.utc)
        db.add(Payment(invoice_id=invoice_ids[0], amount=5, currency="USD"))
        db.add(Payment(invoice_id=invoice_ids[1], amount=7, currency="UZS"))
        db.commit()
        assert revenue_summary(db) == (None, None)
        assert payments_summary(db) == (None, None)
    monthly = client.get("/api/finance/revenue-by-period", headers=auth_headers,
                         params={"from": "2089-01-01T00:00:00Z", "to": "2089-01-31T23:59:59Z"})
    assert monthly.status_code == 200, monthly.text
    assert monthly.json() == [{"period": "2089-01", "amount": None, "currency": None}]

    with SessionLocal() as db:
        db.get(Invoice, invoice_ids[2]).currency = "UZS"
        db.commit()
        assert revenue_summary(db) == (None, None)
        db.get(Invoice, invoice_ids[2]).currency = "USD"
        db.commit()
        assert revenue_summary(db) == (60.0, "USD")


def test_payment_rejects_known_currency_mismatch_and_preserves_legacy_unknown(client, auth_headers):
    _, _, invoice_id = _create_invoice(SessionLocal, amount=100)
    with SessionLocal() as db:
        db.get(Invoice, invoice_id).currency = "USD"
        db.commit()
    mismatch = client.post("/api/finance/payments", headers=auth_headers,
                           json={"invoice_id": invoice_id, "amount": 10, "currency": "UZS"})
    assert mismatch.status_code == 409
    with SessionLocal() as db:
        assert db.query(Payment).filter_by(invoice_id=invoice_id).count() == 0
    accepted = client.post("/api/finance/payments", headers=auth_headers,
                           json={"invoice_id": invoice_id, "amount": 10, "currency": "USD"})
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["currency"] == "USD"


def test_omitted_currency_replays_prechange_manual_payment_key(client, auth_headers):
    _, _, invoice_id = _create_invoice(SessionLocal, amount=100)
    payload = {"invoice_id": invoice_id, "amount": 10}
    legacy = PaymentIn(**payload).model_dump(mode="json")
    legacy.pop("currency")
    legacy["amount"] = 10.0
    response = {"id": 123, "invoice_id": invoice_id, "amount": 10.0,
                "payment_method": None, "paid_at": None}
    with SessionLocal() as db:
        admin_id = db.query(User.id).filter(User.email == "admin@example.com").scalar()
        db.add(IdempotencyRecord(scope="finance.payments", key="legacy-fn08-payment",
                                 request_hash=request_fingerprint(legacy), response_json=response,
                                 status_code=201, user_id=admin_id))
        db.commit()
    replay = client.post("/api/finance/payments", json=payload,
                         headers={**auth_headers, "Idempotency-Key": "legacy-fn08-payment"})
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == 123
    with SessionLocal() as db:
        assert db.query(Payment).filter_by(invoice_id=invoice_id).count() == 0


def test_omitted_currency_replays_prechange_1c_key(client):
    payload = {"invoices": [{"external_id": "legacy-fn08-invoice", "amount": 5}], "payments": []}
    legacy = OneCSyncIn(**payload).model_dump(mode="json")
    legacy["invoices"][0].pop("currency")
    with SessionLocal() as db:
        db.add(IdempotencyRecord(scope="integrations.1c:legacy-shared", key="legacy-fn08-1c",
                                 request_hash=request_fingerprint(legacy), response_json={"replayed": True},
                                 status_code=200, user_id=None))
        db.commit()
    response = client.post("/api/finance/integrations/1c/sync", json=payload,
                           headers={"X-1C-Token": "test-1c-token", "Idempotency-Key": "legacy-fn08-1c"})
    assert response.status_code == 200, response.text
    assert response.json() == {"replayed": True}


def test_omitted_currency_replays_prechange_customer_payment_key(client, auth_headers):
    customer_id, _, _ = _create_invoice(SessionLocal)
    payload = {"amount": 4}
    legacy = {"customer_id": customer_id, **CustomerPaymentIn(**payload).model_dump(mode="json")}
    legacy.pop("currency")
    with SessionLocal() as db:
        admin_id = db.query(User.id).filter(User.email == "admin@example.com").scalar()
        db.add(IdempotencyRecord(scope="customers.payments", key="legacy-fn08-customer",
                                 request_hash=request_fingerprint(legacy), response_json={"replayed": True},
                                 status_code=201, user_id=admin_id))
        db.commit()
    response = client.post(f"/api/customers/{customer_id}/payments", json=payload,
                           headers={**auth_headers, "Idempotency-Key": "legacy-fn08-customer"})
    assert response.status_code == 201, response.text
    assert response.json() == {"replayed": True}


def test_inventory_receipt_omitted_cost_currency_keeps_old_fingerprint(client, auth_headers):
    item, warehouse = _material_context(client, auth_headers)
    payload = {"item_id": item["id"], "batch_no": "FN08-REPLAY-BATCH", "quantity": 2,
               "unit": "kg", "warehouse_id": warehouse["id"], "cost_per_unit": 1}
    key = "fn08-inventory-legacy"
    first = client.post("/api/inventory/receive", json=payload,
                        headers={**auth_headers, "Idempotency-Key": key})
    assert first.status_code == 201, first.text
    old_payload = StockBatchIn(**payload).model_dump(mode="json")
    for field in ("length_m", "roll_lengths_m", "cost_currency"):
        old_payload.pop(field)
    with SessionLocal() as db:
        record = db.query(IdempotencyRecord).filter_by(scope="inventory.receive", key=key).one()
        assert record.request_hash == request_fingerprint(old_payload)
    retry = client.post("/api/inventory/receive", json=payload,
                        headers={**auth_headers, "Idempotency-Key": key})
    assert retry.status_code == 201 and retry.json()["id"] == first.json()["id"]


def test_purchase_receipt_omitted_cost_currency_keeps_old_fingerprint(client, auth_headers):
    from app.db import session as session_module

    order = create_receipt_order(session_module.SessionLocal)
    key = "fn08-purchase-legacy"
    url = f"/api/purchasing/orders/{order['order_id']}/receive"
    first = client.post(url, json=order["payload"], headers={**auth_headers, "Idempotency-Key": key})
    assert first.status_code == 200, first.text
    old_payload = PurchaseOrderReceiveIn(**order["payload"]).model_dump(mode="json")
    for line in old_payload["lines"]:
        line.pop("cost_currency")
    with SessionLocal() as db:
        record = db.query(IdempotencyRecord).filter_by(key=key).one()
        assert record.request_hash == request_fingerprint(old_payload)
    retry = client.post(url, json=order["payload"], headers={**auth_headers, "Idempotency-Key": key})
    assert retry.status_code == 200 and retry.json() == first.json()


def test_customer_order_history_hides_mixed_invoice_aggregate(client, auth_headers):
    customer_id, order_id, invoice_id = _create_invoice(SessionLocal, amount=10)
    with SessionLocal() as db:
        from app.models import SalesOrder

        db.get(SalesOrder, order_id).currency = "USD"
        db.get(Invoice, invoice_id).currency = "USD"
        other = Invoice(sales_order_id=order_id, invoice_no="FN08-MIXED-INVOICE",
                        amount=7, currency="UZS", status="unpaid")
        db.add(other)
        db.commit()
        other_id = other.id
    response = client.get(f"/api/customers/{customer_id}/orders", headers=auth_headers)
    assert response.status_code == 200, response.text
    row = next(row for row in response.json() if row["id"] == order_id)
    assert row["currency"] is None
    assert row["total"] is None
    assert row["invoice_total"] is None
    assert row["paid_total"] is None
    assert row["balance_due"] is None
    assert row["payment_status"] == "unavailable"
    with SessionLocal() as db:
        db.get(Invoice, other_id).currency = None
        db.add(Payment(invoice_id=invoice_id, amount=2, currency="UZS"))
        db.commit()
    unknown = client.get(f"/api/customers/{customer_id}/orders", headers=auth_headers)
    row = next(row for row in unknown.json() if row["id"] == order_id)
    assert all(invoice["amount"] is None for invoice in row["invoices"])
    assert row["invoices"][0]["paid_amount"] is None
    assert row["invoices"][1]["balance_due"] is None
    with SessionLocal() as db:
        db.get(Invoice, other_id).currency = "USD"
        db.query(Payment).filter_by(invoice_id=invoice_id).one().currency = "USD"
        db.commit()
    known = client.get(f"/api/customers/{customer_id}/orders", headers=auth_headers)
    row = next(row for row in known.json() if row["id"] == order_id)
    assert row["currency"] == "USD"
    assert row["invoice_total"] == 17
