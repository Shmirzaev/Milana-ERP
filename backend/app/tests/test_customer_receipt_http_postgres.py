"""Receipt HTTP transaction against the approved disposable PostgreSQL target.

Minimal FastAPI router with real JWT dependencies; not full application middleware.
The imported fixture runs migrations and verifies the disposable DB is removed.
"""
from decimal import Decimal
import hashlib
import json
from uuid import uuid4

import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.partners import router
from app.core.deps import get_db
from app.core.security import create_access_token
from app.models import audit_service
from app.schemas import AuditLog, Customer, IdempotencyRecord, Invoice, Payment, Role, SalesOrder, User
from app.tests.test_customer_create_postgres import chain, customer_pg_sessions  # noqa: F401


def _client(sessions):
    app = FastAPI()
    app.include_router(router)

    def isolated_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = isolated_db
    return TestClient(app, raise_server_exceptions=False)


def _fixture(sessions):
    with sessions.begin() as db:
        allow = Role(name=f"receipt-allow-{uuid4().hex}", permissions=["finance.payment"])
        deny = Role(name=f"receipt-deny-{uuid4().hex}", permissions=["sales.view"])
        db.add_all([allow, deny])
        db.flush()
        users = [User(name="Receipt actor", email=f"{uuid4().hex}@example.invalid", password_hash="unused", factory_code="MIL", role_id=role.id, is_active=True) for role in (allow, deny)]
        customer = Customer(name="Receipt HTTP customer")
        db.add_all([*users, customer])
        db.flush()
        order = SalesOrder(order_no=f"RECEIPT-{uuid4().hex}", customer_id=customer.id, status="confirmed", total_amount=Decimal("100.00"))
        db.add(order)
        db.flush()
        return customer.id, order.id, users[0].id, users[1].id


def _headers(actor, key):
    return {"Authorization": f"Bearer {create_access_token(actor)}", "Idempotency-Key": key}


def _fingerprint(sessions):
    # All columns, including unrelated control rows, on receipt participant tables.
    with sessions() as db:
        return tuple(tuple(tuple(row) for row in db.execute(sa.select(model.__table__).order_by(model.id))) for model in (Customer, SalesOrder, Invoice, Payment, IdempotencyRecord, AuditLog))


def _sequences(sessions):
    with sessions() as db:
        return db.execute(sa.text("SELECT sequencename, last_value FROM pg_sequences WHERE schemaname = current_schema() ORDER BY sequencename")).all()


def _assert_split(sessions, cid, oid, actor, key):
    with sessions() as db:
        invoice = db.query(Invoice).filter_by(sales_order_id=oid).one()
        assert invoice.amount == Decimal("100.00") and invoice.status.value == "paid"
        payments = db.query(Payment).filter_by(customer_id=cid).order_by(Payment.id).all()
        assert [(p.invoice_id, p.amount) for p in payments] == [(invoice.id, Decimal("100.00")), (None, Decimal("29.00"))]
        encoded = json.dumps(["fn06-v2", "customers.payments", actor, "MIL"], separators=(",", ":"), ensure_ascii=True)
        scope = "customers.payments:v2:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        record = db.query(IdempotencyRecord).filter_by(user_id=actor, scope=scope, key=key).one()
        assert record.status_code == 201
        assert db.query(AuditLog).filter_by(user_id=actor, entity_type="Payment", entity_id=payments[-1].id, action="create").count() == 1
    chain(sessions)


def test_pg_receipt_http_auth_split_and_idempotent_replay(customer_pg_sessions):
    sessions = customer_pg_sessions
    cid, oid, actor, denied = _fixture(sessions)
    payload = {"sales_order_id": oid, "amount": "129.00", "payment_method": "cash"}
    key = uuid4().hex
    before = _fingerprint(sessions)
    with _client(sessions) as client:
        assert client.post(f"/customers/{cid}/payments", json=payload).status_code == 401
        assert client.post(f"/customers/{cid}/payments", headers=_headers(denied, key), json=payload).status_code == 403
        assert _fingerprint(sessions) == before
        response = client.post(f"/customers/{cid}/payments", headers=_headers(actor, key), json=payload)
        assert response.status_code == 201, response.text
        assert response.json()["is_advance"] is True and response.json()["amount"] == 29
        _assert_split(sessions, cid, oid, actor, key)
        saved = _fingerprint(sessions)
        replay = client.post(f"/customers/{cid}/payments", headers=_headers(actor, key), json=payload)
        assert replay.status_code == 201 and replay.json() == response.json()
        assert _fingerprint(sessions) == saved


def test_pg_receipt_http_finalization_flush_failure_rolls_back_then_retry(customer_pg_sessions, monkeypatch):
    sessions = customer_pg_sessions
    cid, oid, actor, _ = _fixture(sessions)
    payload = {"sales_order_id": oid, "amount": "129.00", "payment_method": "cash"}
    key = uuid4().hex
    before = _fingerprint(sessions)
    sequences_before = _sequences(sessions)
    inserted = []
    original = audit_service.add_audit_log_rows

    def fail_after_finalization_flush(db, rows):
        original(db, rows)
        db.flush()
        inserted.extend(row.id for row in rows)
        raise RuntimeError("injected receipt audit finalization failure")

    with monkeypatch.context() as patch:
        patch.setattr(audit_service, "add_audit_log_rows", fail_after_finalization_flush)
        with _client(sessions) as client:
            failed = client.post(f"/customers/{cid}/payments", headers=_headers(actor, key), json=payload)
        assert failed.status_code == 500 and inserted
    assert _fingerprint(sessions) == before
    chain(sessions)
    # PostgreSQL sequences are nontransactional; observe rather than assert rollback.
    print("receipt sequence observations", sequences_before, _sequences(sessions))
    with _client(sessions) as client:
        retry = client.post(f"/customers/{cid}/payments", headers=_headers(actor, key), json=payload)
    assert retry.status_code == 201, retry.text
    _assert_split(sessions, cid, oid, actor, key)
