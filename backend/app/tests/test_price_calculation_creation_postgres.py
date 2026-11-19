"""Signed request creation and transaction rollback on migrated PostgreSQL."""
from collections import Counter
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.core.deps import user_permissions
from app.models import audit_service

from app.models import price_calculation_service as pricing
from app.models.planning import variant_pricing_service as workflow
from app.schemas import AuditLog, Model, Notification, PriceCalculationRequest, User
from app.tests.test_price_calculation_status_postgres import app_for, auth, customer_pg_sessions  # noqa: F401


def seed(sessions, margin='-999999.99'):
    token = uuid4().hex
    with sessions.begin() as db:
        model = Model(code=token, name='Creation PG', category='T-shirt', status='approved',
                      details_json={'costing': {'target_margin_pct': margin}})
        sales = User(name='Sales', email=f'{token}s@example.invalid', password_hash='unused',
                     extra_permissions=['sales.orders'])
        recipient = User(name='Recipient', email=f'{token}r@example.invalid', password_hash='unused',
                         extra_permissions=['price_calculation.purchasing'])
        denied = User(name='Denied', email=f'{token}d@example.invalid', password_hash='unused',
                      extra_permissions=[])
        db.add_all([model, sales, recipient, denied]); db.flush()
        return model.id, model.code, sales.id, recipient.id, denied.id


def rows(db, model_id, code):
    requests = db.query(PriceCalculationRequest).filter_by(model_id=model_id).all()
    ids = [row.id for row in requests]
    audits = db.query(AuditLog).filter(AuditLog.entity_type == 'PriceCalculationRequest',
                                        AuditLog.entity_id.in_(ids), AuditLog.action == 'create').all()
    notices = db.query(Notification).filter_by(title='Variant price information required',
                                                message=f'Model {code}: enter and submit costs.').all()
    return requests, audits, notices


def test_pg_signed_creation_auth_duplicates_and_recipients(customer_pg_sessions):
    sessions = customer_pg_sessions
    model_id, code, sales, recipient, denied = seed(sessions)
    url = '/api/price-calculation/requests'
    with sessions() as db:
        eligible = {u.id for u in db.query(User).filter(User.is_active.is_(True)).all()
                    if '*' not in user_permissions(u) and any(check(u) for check in (
                        pricing.is_price_purchaser, pricing.is_accessory_pricing_user))}
    with TestClient(app_for(sessions), raise_server_exceptions=False) as client:
        assert client.post(url, json={'model_id': model_id}).status_code == 401
        assert client.post(url, headers=auth(denied), json={'model_id': 2147483647}).status_code == 403
        assert client.post(url, headers=auth(sales), json={'model_id': 0}).status_code == 422
        assert client.post(url, headers=auth(sales), json={'model_id': 2147483647}).status_code == 404
        first = client.post(url, headers=auth(sales), json={'model_id': model_id})
        second = client.post(url, headers=auth(sales), json={'model_id': model_id})
        assert first.status_code == second.status_code == 201
        assert first.json()['id'] == second.json()['id']
    with sessions() as db:
        requests, audits, notices = rows(db, model_id, code)
        assert {r.id for r in requests} == {first.json()['id'], second.json()['id']}
        assert all(r.profit_percentage == Decimal('-999999.99') and r.accessories_json == [] for r in requests)
        assert len(audits) == 1 and all(a.user_id == sales for a in audits)
        assert Counter(n.user_id for n in notices)[recipient] == 1
        assert all(n.link == '/purchasing/price-calculation' for n in notices if n.user_id == recipient)
        assert Counter(n.user_id for n in notices) == Counter({user_id: 1 for user_id in eligible})


@pytest.mark.parametrize(('margin', 'status', 'expected'), [
    ('999999.99', 201, Decimal('999999.99')),
    ('1000000', 422, None), ('0.001', 422, None), ('not-a-number', 201, None),
])
def test_pg_signed_creation_margin_contract(customer_pg_sessions, margin, status, expected):
    sessions = customer_pg_sessions
    model_id, code, sales, _, _ = seed(sessions, margin)
    with TestClient(app_for(sessions), raise_server_exceptions=False) as client:
        response = client.post('/api/price-calculation/requests', headers=auth(sales), json={'model_id': model_id})
        assert response.status_code == status, response.text
    with sessions() as db:
        requests, audits, notices = rows(db, model_id, code)
        if status == 201:
            assert len(requests) == len(audits) == 1
            assert requests[0].profit_percentage == expected
        else:
            assert requests == audits == notices == []


@pytest.mark.parametrize('fault', ['notification', 'audit', 'commit'])
def test_pg_signed_creation_failure_teardown_retry(customer_pg_sessions, monkeypatch, fault):
    sessions = customer_pg_sessions
    model_id, code, sales, recipient, _ = seed(sessions)
    original_notify = workflow._notify
    original_finalize = audit_service._finalize_postgres_audits
    attempted_ids = []
    observed = []
    engine = sessions.kw['bind']
    suffix = uuid4().hex[:12]
    trigger = f'pr402_guard_{suffix}'
    function = f'pr402_abort_{suffix}'

    def observe_notification(db, request, teams):
        attempted_ids.append(request.id)
        original_notify(db, request, teams)
        if fault == 'notification':
            db.flush()
            assert db.query(Notification).filter_by(user_id=recipient, message=f'Model {code}: enter and submit costs.').count() == 1
            raise RuntimeError('injected after notification flush')

    def fail_audit(db):
        original_finalize(db)
        request = db.query(PriceCalculationRequest).filter_by(model_id=model_id).one()
        assert attempted_ids == [request.id]
        assert db.query(AuditLog).filter_by(entity_type='PriceCalculationRequest', entity_id=request.id, action='create').count() == 1
        assert db.query(Notification).filter_by(user_id=recipient, message=f'Model {code}: enter and submit costs.').count() == 1
        observed.append('finalized')
        raise RuntimeError('injected after audit finalization')

    def capture(context):
        exc = context.original_exception
        if getattr(exc, 'pgcode', None) == '23514':
            observed.append((context.statement, exc.diag.constraint_name))

    if fault == 'commit':
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql(f"""CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
                RAISE EXCEPTION 'fixture commit failure' USING ERRCODE = '23514', CONSTRAINT = '{trigger}'; END; $$""")
                conn.exec_driver_sql(f"""CREATE CONSTRAINT TRIGGER {trigger} AFTER INSERT ON price_calculation_requests
                DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.model_id = {int(model_id)})
                EXECUTE FUNCTION {function}()""")
            event.listen(engine, 'handle_error', capture)
        except Exception as exc:
            raise RuntimeError(
                f'HOLD: uncertain commit fixture setup; inspect owned {function} and {trigger} before any cleanup or retry'
            ) from exc
    url = '/api/price-calculation/requests'
    try:
        with TestClient(app_for(sessions), raise_server_exceptions=False) as client:
            with monkeypatch.context() as patch:
                patch.setattr(workflow, '_notify', observe_notification)
                if fault == 'audit':
                    patch.setattr(audit_service, '_finalize_postgres_audits', fail_audit)
                assert client.post(url, headers=auth(sales), json={'model_id': model_id}).status_code == 500
        assert len(attempted_ids) == 1
        if fault == 'commit':
            assert observed == [(None, trigger)]
        if fault == 'audit':
            assert observed == ['finalized']
        with sessions() as db:
            assert rows(db, model_id, code) == ([], [], [])
            for attempted_id in attempted_ids:
                assert db.query(AuditLog).filter_by(entity_type='PriceCalculationRequest', entity_id=attempted_id).count() == 0
    finally:
        if fault == 'commit':
            event.remove(engine, 'handle_error', capture)
            with engine.begin() as conn:
                conn.exec_driver_sql(f'DROP TRIGGER {trigger} ON price_calculation_requests')
                conn.exec_driver_sql(f'DROP FUNCTION {function}()')
    with TestClient(app_for(sessions), raise_server_exceptions=False) as client:
        retry = client.post(url, headers=auth(sales), json={'model_id': model_id})
        assert retry.status_code == 201, retry.text
    with sessions() as db:
        requests, audits, notices = rows(db, model_id, code)
        assert len(requests) == len(audits) == 1
        assert requests[0].id == retry.json()['id'] and audits[0].user_id == sales
        assert Counter(n.user_id for n in notices)[recipient] == 1
