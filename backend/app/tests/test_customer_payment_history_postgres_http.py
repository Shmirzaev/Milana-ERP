"""Real PostgreSQL customer receipt-history HTTP contract; disposable DB only."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient

from app.api.routes.partners import router
from app.core.deps import get_db
from app.core.security import create_access_token
from app.models.finance.customer_ledger_service import _serialize_customer_payment
from app.schemas import AuditLog, Customer, IdempotencyRecord, Invoice, Payment, Role, SalesOrder, User
from app.tests.test_customer_invoice_creation_race import receipt_race_sessions as receipt_race_sessions  # noqa: F401


def test_customer_payment_history_http_postgres_and_replay(receipt_race_sessions):  # noqa: F811
    suffix = uuid4().hex[:12]
    with receipt_race_sessions.begin() as db:
        allowed = Role(name=f'ledger-allowed-{suffix}', permissions=['finance.view', 'finance.payment'])
        denied = Role(name=f'ledger-denied-{suffix}', permissions=[])
        db.add_all([allowed, denied])
        db.flush()
        actor = User(name='Ledger actor', email=f'ledger-{suffix}@example.invalid', password_hash='unused', role_id=allowed.id, is_active=True)
        outsider = User(name='Denied actor', email=f'denied-{suffix}@example.invalid', password_hash='unused', role_id=denied.id, is_active=True)
        customer = Customer(name=f'Customer {suffix}')
        db.add_all([actor, outsider, customer])
        db.flush()
        order = SalesOrder(order_no=f'LEDGER-{suffix}', customer_id=customer.id, total_amount=Decimal('20.00'))
        db.add(order)
        db.flush()
        invoice = Invoice(sales_order_id=order.id, invoice_no=f'INV-{suffix}', amount=Decimal('20.00'))
        db.add(invoice)
        db.flush()
        paid_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        invoice_payment = Payment(invoice_id=invoice.id, customer_id=customer.id, amount=Decimal('4.25'), payment_method='legacy custom method', paid_at=paid_at)
        advance = Payment(customer_id=customer.id, amount=Decimal('3.50'), payment_method=None, paid_at=None)
        db.add_all([invoice_payment, advance])
        db.flush()
        cid, actor_id, denied_id = customer.id, actor.id, outsider.id
        expected = [jsonable_encoder(_serialize_customer_payment(advance, None, None)), jsonable_encoder(_serialize_customer_payment(invoice_payment, invoice, order))]

    app = FastAPI()
    app.include_router(router, prefix='/api')

    def isolated_db():
        with receipt_race_sessions() as db:
            yield db

    app.dependency_overrides[get_db] = isolated_db
    headers = {'Authorization': f'Bearer {create_access_token(actor_id)}'}
    denied_headers = {'Authorization': f'Bearer {create_access_token(denied_id)}'}
    with TestClient(app) as client:
        assert client.get(f'/api/customers/{cid}/payments').status_code == 401
        assert client.get(f'/api/customers/{cid}/payments', headers=denied_headers).status_code == 403
        assert client.get('/api/customers/2147483647/payments', headers=headers).status_code == 404
        result = client.get(f'/api/customers/{cid}/payments', headers=headers)
        assert result.status_code == 200, result.text
        assert result.json() == expected
        assert list(result.json()[0]) == list(expected[0])
        assert result.json()[0]['invoice_amount'] is None and result.json()[0]['is_advance'] is True
        assert result.json()[1]['payment_method'] == 'legacy custom method'

        key = f'ledger-replay-{suffix}'
        post_headers = {**headers, 'Idempotency-Key': key}
        payload = {'amount': 1.25, 'payment_method': 'custom', 'notes': 'advance'}
        first = client.post(f'/api/customers/{cid}/payments', headers=post_headers, json=payload)
        assert first.status_code == 201, first.text
        with receipt_race_sessions() as db:
            counts = (db.query(Payment).count(), db.query(AuditLog).count(), db.query(IdempotencyRecord).count())
        replay = client.post(f'/api/customers/{cid}/payments', headers=post_headers, json=payload)
        assert replay.status_code == 201 and replay.json() == first.json()
        with receipt_race_sessions() as db:
            assert (db.query(Payment).count(), db.query(AuditLog).count(), db.query(IdempotencyRecord).count()) == counts
        latest = client.get(f'/api/customers/{cid}/payments', headers=headers)
        assert latest.status_code == 200
        assert latest.json()[0] == first.json()
