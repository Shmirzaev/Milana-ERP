from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from app.libs.dto.sales.payment_input import PaymentIn
from app.libs.dto.sales.payment_output import PaymentOut
from app.models.finance import payments_service
from app.models.idempotency_service import _scoped_operation, request_fingerprint
from app.schemas import AuditLog, Customer, IdempotencyRecord, Invoice, Payment, SalesOrder, User
from app.tests.conftest import TestSessionLocal


class SessionStub:
    def __init__(self, invoice=None):
        self.invoice = invoice
        self.commits = 0
        self.refreshed = []

    def get(self, model, row_id):
        return self.invoice

    def commit(self):
        self.commits += 1

    def refresh(self, row):
        self.refreshed.append(row)


def test_fresh_invoice_payment_returns_typed_snapshot_and_stores_same_json(monkeypatch):
    invoice = SimpleNamespace(id=7)
    payment = SimpleNamespace(
        id=9,
        invoice_id=7,
        amount=Decimal("10.00"),
        payment_method=None,
        paid_at=None,
    )
    actor = SimpleNamespace(id=42)
    payload = PaymentIn(invoice_id=7, amount=Decimal("10.00"), payment_method=None, paid_at=None)
    db = SessionStub(invoice)
    writes = {}

    monkeypatch.setattr(payments_service, "replay_idempotent_response", lambda *a, **kw: None)
    monkeypatch.setattr(payments_service.low_level_payments, "create_invoice_payment", lambda *a, **kw: payment)
    monkeypatch.setattr(payments_service, "log_action", lambda *a, **kw: None)

    def store(_db, **kwargs):
        writes.update(kwargs)

    monkeypatch.setattr(payments_service, "store_idempotent_response", store)

    result = payments_service.record_invoice_payment(db, payload, actor, "receipt-key")

    expected_json = {
        "id": 9,
        "invoice_id": 7,
        "amount": 10.0,
        "payment_method": None,
        "paid_at": None,
    }
    assert isinstance(result, PaymentOut)
    assert result.model_dump(mode="json") == expected_json
    assert writes["response"] == expected_json
    assert writes["payload"] == payload.model_dump(mode="json")
    assert writes["status_code"] == 201
    assert db.commits == 1 and db.refreshed == [payment]


def test_legacy_idempotency_snapshot_returns_typed_output_without_rewriting(monkeypatch):
    legacy_snapshot = {
        "id": 19,
        "invoice_id": 7,
        "amount": 12.5,
        "payment_method": None,
        "paid_at": None,
    }
    actor = SimpleNamespace(id=42)
    payload = PaymentIn(invoice_id=7, amount=Decimal("12.50"), payment_method=None, paid_at=None)
    db = SessionStub()
    observed = {}

    def replay(_db, **kwargs):
        observed.update(kwargs)
        return legacy_snapshot

    def must_not_write(*args, **kwargs):
        raise AssertionError("replay must not create, audit, store, or commit")

    monkeypatch.setattr(payments_service, "replay_idempotent_response", replay)
    monkeypatch.setattr(payments_service.low_level_payments, "create_invoice_payment", must_not_write)
    monkeypatch.setattr(payments_service, "log_action", must_not_write)
    monkeypatch.setattr(payments_service, "store_idempotent_response", must_not_write)

    result = payments_service.record_invoice_payment(db, payload, actor, "receipt-key")

    assert isinstance(result, PaymentOut)
    assert result.model_dump(mode="json") == legacy_snapshot
    assert observed["scope"] == "finance.payments"
    assert observed["payload"] == payload.model_dump(mode="json")
    assert db.commits == 0 and db.refreshed == []


def test_saved_scoped_replay_preserves_hash_json_and_non_null_timestamp(client, auth_headers, monkeypatch):
    with TestSessionLocal() as db:
        customer = Customer(name=f"Typed payment {uuid4().hex}")
        db.add(customer)
        db.flush()
        order = SalesOrder(order_no=f"TYPED-{uuid4().hex}", customer_id=customer.id, total_amount=100)
        db.add(order)
        db.flush()
        invoice = Invoice(
            invoice_no=f"TYPED-INV-{uuid4().hex}",
            sales_order_id=order.id,
            amount=Decimal("100.00"),
            status="unpaid",
        )
        actor = db.query(User).filter_by(email="admin@example.com").one()
        db.add(invoice)
        db.commit()
        invoice_id = invoice.id
        actor_id = actor.id

    key = f"typed-payment-{uuid4().hex}"
    paid_at = "2024-11-12T13:14:15"
    body = {
        "invoice_id": invoice_id,
        "amount": 40.0,
        "payment_method": "cash",
        "paid_at": paid_at,
    }
    payload = PaymentIn.model_validate(body)
    typed_results = []
    original = payments_service.record_invoice_payment

    def capture_result(*args, **kwargs):
        result = original(*args, **kwargs)
        typed_results.append(result)
        return result

    from app.api.routes import finance as finance_routes

    monkeypatch.setattr(finance_routes, "record_invoice_payment", capture_result)
    headers = {**auth_headers, "Idempotency-Key": key}
    first = client.post("/api/finance/payments", headers=headers, json=body)
    assert first.status_code == 201, first.text

    expected_json = {
        "id": first.json()["id"],
        "invoice_id": invoice_id,
        "amount": 40.0,
        "payment_method": "cash",
        "paid_at": "2024-11-12T13:14:15+00:00",
    }
    assert first.json() == expected_json
    assert isinstance(typed_results[0], PaymentOut)
    assert typed_results[0].model_dump(mode="json") == expected_json

    with TestSessionLocal() as db:
        saved = db.query(IdempotencyRecord).filter_by(key=key).one()
        saved_snapshot = (
            saved.scope,
            saved.request_hash,
            dict(saved.response_json),
            saved.status_code,
            saved.user_id,
        )
        assert saved.scope == _scoped_operation("finance.payments", (actor_id, "MIL"))
        assert saved.request_hash == request_fingerprint(payload.model_dump(mode="json"))
        assert saved.response_json == expected_json
        assert saved.status_code == 201
        assert saved.user_id == actor_id
        payment_count = db.query(Payment).filter_by(invoice_id=invoice_id).count()
        audit_count = db.query(AuditLog).filter_by(entity_type="Payment", entity_id=expected_json["id"]).count()
        assert payment_count == audit_count == 1

    replay = client.post("/api/finance/payments", headers=headers, json=body)
    assert replay.status_code == 201, replay.text
    assert replay.json() == expected_json
    assert isinstance(typed_results[1], PaymentOut)
    assert typed_results[1].model_dump(mode="json") == expected_json

    with TestSessionLocal() as db:
        saved = db.query(IdempotencyRecord).filter_by(key=key).one()
        assert (
            saved.scope,
            saved.request_hash,
            dict(saved.response_json),
            saved.status_code,
            saved.user_id,
        ) == saved_snapshot
        assert db.query(Payment).filter_by(invoice_id=invoice_id).count() == 1
        assert db.query(AuditLog).filter_by(entity_type="Payment", entity_id=expected_json["id"]).count() == 1
